"""Apply a provider candidate to a local track (DB + on-disk tags)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, or_, select

from sonicverse.core.config import get_settings
from sonicverse.core.http import http_client
from sonicverse.core.artists import (
    artist_name_key,
    join_artist_names,
    normalize_album_title,
    normalize_artist_name,
    split_artist_names,
)
from sonicverse.library.file_tags import apply_file_tags
from sonicverse.library.import_file import import_track_to_library
from sonicverse.metadata.parser import AudioMetadata, MetadataReader
from sonicverse.models import Album, Artist, ProviderResult, Track
from sonicverse.models.track_artist import track_artists
from sonicverse.providers import get_provider
from sonicverse.tagger.tagger import Tagger

logger = logging.getLogger(__name__)
settings = get_settings()

# Sentinel mbid meaning "user accepted local tags; leave pending_review".
LOCAL_CONFIRMED_MBID = "local-confirmed"


class ApplyError(Exception):
    """Raised when apply cannot persist tags; session is rolled back."""

    def __init__(self, message: str, *, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ApplyPayload:
    """Fields needed to overwrite a track from a match candidate."""

    title: str
    artist: str
    album: str
    mbid: str
    album_mbid: str | None = None
    album_artist: str | None = None
    filename: str | None = None
    year: int | None = None
    duration: int | None = None  # seconds
    fetch_cover: bool = True
    cover_url: str | None = None
    clear_cover: bool = False
    artist_image_url: str | None = None
    artist_images: tuple[dict[str, str], ...] | None = None
    force_artist_images: bool = False
    provider: str = "netease"
    artist_names: tuple[str, ...] | None = None


def _detect_cover_ext(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".jpg"


async def _count_tracks_for_album(
    session, album_id: str, exclude_track_id: str | None = None
) -> int:
    query = select(func.count(Track.id)).where(Track.album_id == album_id)
    if exclude_track_id:
        query = query.where(Track.id != exclude_track_id)
    return int(await session.scalar(query) or 0)


async def _count_usage_for_artist(
    session, artist_id: str, exclude_track_id: str | None = None
) -> int:
    credit_tracks = select(track_artists.c.track_id).where(
        track_artists.c.artist_id == artist_id
    )
    track_q = select(func.count(Track.id)).where(
        or_(Track.artist_id == artist_id, Track.id.in_(credit_tracks))
    )
    album_q = select(func.count(Album.id)).where(Album.artist_id == artist_id)
    if exclude_track_id:
        track_q = track_q.where(Track.id != exclude_track_id)
    tracks = int(await session.scalar(track_q) or 0)
    albums = int(await session.scalar(album_q) or 0)
    return tracks + albums


async def _clear_album_mbid(session, mbid: str, keep_album_id: str) -> None:
    """Free ``mbid`` on other albums before reassignment.

    Flush immediately so PostgreSQL unique index ``ix_albums_mbid`` is released
    before we assign the same value to ``keep_album_id`` (autoflush can otherwise
    UPDATE the new row first and raise UniqueViolationError).
    """
    result = await session.execute(
        select(Album).where(Album.mbid == mbid, Album.id != keep_album_id)
    )
    others = list(result.scalars().all())
    if not others:
        return
    for other in others:
        other.mbid = None
    await session.flush()


async def _get_or_create_artist_by_name(session, name: str) -> Artist:
    canonical = normalize_artist_name(name)
    result = await session.execute(
        select(Artist).where(Artist.name == canonical).order_by(Artist.id)
    )
    artist = result.scalars().first()
    if artist is None:
        artist = Artist(name=canonical)
        session.add(artist)
        await session.flush()
    return artist


async def _overwrite_artists(
    session,
    track: Track,
    raw_name: str,
    *,
    names: Sequence[str] | None = None,
) -> list[Artist]:
    """Resolve credits into Artist rows and attach them to the track.

    ``names`` is used as-is (manual editor chips). Otherwise ``raw_name`` is split.
    """
    if names is not None:
        resolved: list[str] = []
        seen: set[str] = set()
        for part in names:
            text = normalize_artist_name(part)
            if not text:
                continue
            key = artist_name_key(text)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(text)
        names_list = resolved
    else:
        names_list = split_artist_names(raw_name)
    if not names_list:
        track.artists = []
        return []

    # Single exclusive credit: rename in place so we keep a stable artist id.
    if len(names_list) == 1 and track.artist_id:
        result = await session.execute(select(Artist).where(Artist.id == track.artist_id))
        current = result.scalar_one_or_none()
        if current is not None:
            other_tracks = int(
                await session.scalar(
                    select(func.count(Track.id)).where(
                        Track.artist_id == current.id,
                        Track.id != track.id,
                    )
                )
                or 0
            )
            credit_others = int(
                await session.scalar(
                    select(func.count(track_artists.c.track_id)).where(
                        track_artists.c.artist_id == current.id,
                        track_artists.c.track_id != track.id,
                    )
                )
                or 0
            )
            other_albums_q = select(func.count(Album.id)).where(Album.artist_id == current.id)
            if track.album_id:
                other_albums_q = other_albums_q.where(Album.id != track.album_id)
            other_albums = int(await session.scalar(other_albums_q) or 0)
            if other_tracks == 0 and credit_others == 0 and other_albums == 0:
                existing = await session.execute(
                    select(Artist)
                    .where(Artist.name == names_list[0], Artist.id != current.id)
                    .order_by(Artist.id)
                )
                sibling = existing.scalars().first()
                if sibling is not None:
                    track.artists = [sibling]
                    return [sibling]
                current.name = names_list[0]
                track.artists = [current]
                return [current]

    artists = [await _get_or_create_artist_by_name(session, name) for name in names_list]
    track.artists = artists
    return artists


async def _overwrite_album(
    session,
    track: Track,
    title: str,
    artist: Artist,
    year: int | None,
    mbid: str | None,
) -> Album:
    title = normalize_album_title(title) or (title or "").strip()
    # Prefer the album that already owns this provider album id (unique mbid).
    if mbid:
        result = await session.execute(select(Album).where(Album.mbid == mbid))
        album = result.scalar_one_or_none()
        if album is not None:
            album.title = title
            album.artist_id = artist.id
            if year is not None:
                album.year = year
            return album

    if track.album_id:
        result = await session.execute(select(Album).where(Album.id == track.album_id))
        current = result.scalar_one_or_none()
        if current is not None:
            siblings = await _count_tracks_for_album(
                session, current.id, exclude_track_id=track.id
            )
            if siblings == 0:
                existing = await session.execute(
                    select(Album)
                    .where(
                        Album.title == title,
                        Album.artist_id == artist.id,
                        Album.id != current.id,
                    )
                    .order_by(Album.id)
                )
                sibling = existing.scalars().first()
                if sibling is not None:
                    if year is not None:
                        sibling.year = year
                    if mbid:
                        await _clear_album_mbid(session, mbid, sibling.id)
                        sibling.mbid = mbid
                    return sibling
                current.title = title
                current.artist_id = artist.id
                if year is not None:
                    current.year = year
                if mbid:
                    current.mbid = mbid
                return current

    result = await session.execute(
        select(Album)
        .where(Album.title == title, Album.artist_id == artist.id)
        .order_by(Album.id)
    )
    album = result.scalars().first()
    if album is None:
        album = Album(title=title, artist_id=artist.id, year=year, mbid=mbid)
        session.add(album)
        await session.flush()
    else:
        if year is not None:
            album.year = year
        if mbid:
            # mbid is free after the lookup above; flush-clear kept for safety if
            # another row raced in (Postgres unique) or session had stale state.
            await _clear_album_mbid(session, mbid, album.id)
            album.mbid = mbid
    return album


async def _delete_orphan_album(session, album_id: str | None) -> None:
    if not album_id:
        return
    remaining = await _count_tracks_for_album(session, album_id)
    if remaining > 0:
        return
    result = await session.execute(select(Album).where(Album.id == album_id))
    album = result.scalar_one_or_none()
    if album is None:
        return
    cover_path = album.cover_path
    await session.delete(album)
    if cover_path and cover_path.startswith("/covers/"):
        try:
            cover_file = Path(cover_path.split("?", 1)[0]).name
            file_path = Path(settings.covers_path) / cover_file
            await asyncio.to_thread(file_path.unlink, missing_ok=True)
        except Exception:
            logger.warning("Failed to delete orphan cover %s", cover_path, exc_info=True)


async def _purge_empty_albums(session) -> None:
    result = await session.execute(
        select(Album.id).where(
            ~Album.id.in_(select(Track.album_id).where(Track.album_id.is_not(None)))
        )
    )
    for album_id in result.scalars().all():
        await _delete_orphan_album(session, album_id)


async def _delete_orphan_artist(session, artist_id: str | None) -> None:
    if not artist_id:
        return
    usage = await _count_usage_for_artist(session, artist_id)
    if usage > 0:
        return
    result = await session.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        return
    avatar_path = artist.avatar_path
    await session.delete(artist)
    if avatar_path and avatar_path.startswith("/covers/"):
        try:
            avatar_file = Path(avatar_path.split("?", 1)[0]).name
            file_path = Path(settings.covers_path) / avatar_file
            await asyncio.to_thread(file_path.unlink, missing_ok=True)
        except Exception:
            logger.warning("Failed to delete orphan avatar %s", avatar_path, exc_info=True)


async def _save_cover(album: Album, cover_data: bytes) -> None:
    try:
        ext = _detect_cover_ext(cover_data)
        covers_dir = Path(settings.covers_path)
        covers_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{album.id}{ext}"
        await asyncio.to_thread((covers_dir / file_name).write_bytes, cover_data)
        album.cover_path = f"/covers/{file_name}?v={int(time.time() * 1000)}"
    except Exception:
        logger.warning("Failed to save cover for album %s", album.id, exc_info=True)


async def _clear_album_cover(album: Album) -> None:
    cover_path = album.cover_path
    album.cover_path = None
    if cover_path and cover_path.startswith("/covers/"):
        try:
            cover_file = Path(cover_path.split("?", 1)[0]).name
            file_path = Path(settings.covers_path) / cover_file
            await asyncio.to_thread(file_path.unlink, missing_ok=True)
        except Exception:
            logger.warning("Failed to clear cover %s", cover_path, exc_info=True)


async def _save_artist_avatar(artist: Artist, image_data: bytes) -> None:
    try:
        ext = _detect_cover_ext(image_data)
        covers_dir = Path(settings.covers_path)
        covers_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"artist-{artist.id}{ext}"
        await asyncio.to_thread((covers_dir / file_name).write_bytes, image_data)
        artist.avatar_path = f"/covers/{file_name}?v={int(time.time() * 1000)}"
    except Exception:
        logger.warning("Failed to save avatar for artist %s", artist.id, exc_info=True)


async def _download_image(url: str | None) -> bytes | None:
    if not url:
        return None
    headers = None
    lower = url.lower()
    if "gtimg.cn" in lower or "y.qq.com" in lower:
        headers = {
            "Referer": "https://y.qq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }
    try:
        response = await http_client().get(url, headers=headers)
        if response.status_code == 200 and response.content:
            return response.content
    except Exception:
        logger.warning("Image download failed: %s", url, exc_info=True)
    return None


def _artist_image_map(
    artist_images: tuple[dict[str, str], ...] | list[dict[str, str]] | None,
    artist_image_url: str | None,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in artist_images or ():
        name = (item.get("name") or "").strip()
        url = (item.get("url") or "").strip()
        if name and url:
            mapping[name.casefold()] = url
    return mapping


async def _lookup_artist_image_url(provider_name: str, artist_name: str) -> str | None:
    """Search the provider for an avatar URL for this artist name."""
    name = (artist_name or "").strip()
    if not name or not provider_name:
        return None
    try:
        provider = get_provider(provider_name)
    except Exception:
        logger.warning("Unknown provider for artist image lookup: %s", provider_name)
        return None

    try:
        direct = await provider.lookup_artist_image(name)
        if direct:
            return direct
    except Exception:
        logger.warning(
            "Provider artist lookup failed for %s via %s",
            name,
            provider_name,
            exc_info=True,
        )

    try:
        results = await provider.search_track(title="", artist=name)
    except Exception:
        logger.warning(
            "Artist image lookup failed for %s via %s",
            name,
            provider_name,
            exc_info=True,
        )
        return None

    target = name.casefold()
    for result in results:
        for item in result.artist_images or ():
            item_name = (item.get("name") or "").strip()
            url = (item.get("url") or "").strip()
            if item_name and url and item_name.casefold() == target:
                return url
        credited = split_artist_names(result.artist)
        if len(credited) == 1 and credited[0].casefold() == target:
            url = (result.artist_image_url or "").strip()
            if url:
                return url
    return None


async def _maybe_save_artist_avatars(
    artists: list[Artist],
    *,
    artist_image_url: str | None,
    artist_images: tuple[dict[str, str], ...] | list[dict[str, str]] | None,
    force: bool = False,
    provider: str | None = None,
) -> None:
    """Fill artist avatars from provider image URLs (best-effort).

    Prefer name match from the candidate payload. When QQ packs many singers
    into one credit (no per-person URL), look each artist up individually.
    """
    by_name = _artist_image_map(artist_images, artist_image_url)
    images = list(artist_images or ())
    for index, artist in enumerate(artists):
        if artist.avatar_path and not force:
            continue
        url = by_name.get(artist.name.casefold())
        if not url and index == 0:
            url = (artist_image_url or "").strip() or None
        if not url and index < len(images):
            url = (images[index].get("url") or "").strip() or None
        if not url and provider:
            url = await _lookup_artist_image_url(provider, artist.name)
        image = await _download_image(url)
        if image:
            await _save_artist_avatar(artist, image)


async def refresh_artist_avatars_from_images(
    session,
    track: Track,
    *,
    artist_image_url: str | None,
    artist_images: tuple[dict[str, str], ...] | list[dict[str, str]] | None,
    force: bool = False,
    provider: str | None = None,
) -> None:
    """Update avatars for artists already linked to a track (no tag rewrite)."""
    await session.refresh(track, attribute_names=["artist", "artists"])
    artists = list(track.artists)
    if not artists and track.artist is not None:
        artists = [track.artist]
    if not artists:
        return
    await _maybe_save_artist_avatars(
        artists,
        artist_image_url=artist_image_url,
        artist_images=artist_images,
        force=force,
        provider=provider,
    )


async def refresh_artists_from_candidate(
    session,
    track: Track,
    *,
    artist_image_url: str | None,
    artist_images: tuple[dict[str, str], ...] | list[dict[str, str]] | None,
    force: bool = True,
    provider: str | None = None,
) -> None:
    """Refresh avatars for artists linked to the track or its album."""
    await session.refresh(track, attribute_names=["artist", "artists", "album"])

    artists: list[Artist] = list(track.artists)
    if track.artist is not None and all(item.id != track.artist.id for item in artists):
        artists.append(track.artist)
    if track.album is not None:
        await session.refresh(track.album, attribute_names=["artist"])
        if track.album.artist is not None and all(
            item.id != track.album.artist.id for item in artists
        ):
            artists.append(track.album.artist)

    if not artists:
        return

    # Release the DB connection before avatar HTTP downloads.
    await session.commit()

    await _maybe_save_artist_avatars(
        artists,
        artist_image_url=artist_image_url,
        artist_images=artist_images,
        force=force,
        provider=provider,
    )


async def fetch_cover_bytes(
    provider_name: str,
    album_mbid: str | None,
    cover_url: str | None,
) -> bytes | None:
    if cover_url:
        try:
            response = await http_client().get(cover_url)
            if response.status_code == 200 and response.content:
                return response.content
        except Exception:
            logger.warning("Direct cover download failed: %s", cover_url, exc_info=True)

    if album_mbid:
        try:
            provider = get_provider(provider_name)
            return await provider.get_cover(album_mbid)
        except Exception:
            logger.warning(
                "Provider cover fetch failed: %s %s",
                provider_name,
                album_mbid,
                exc_info=True,
            )
    return None


async def apply_match_to_track(
    session,
    track: Track,
    data: ApplyPayload,
    *,
    cover_data: bytes | None = None,
) -> None:
    """Overwrite local track/album/artist and write tags.

    On tag write failure the session is rolled back and ``ApplyError`` is raised.
    Caller must commit on success.

    ``cover_data`` may be pre-downloaded so callers can avoid holding a DB
    connection during cover HTTP.
    """
    source = Path(track.file_path)
    if not source.is_file():
        raise ApplyError(
            f"音频文件不存在，无法保存：{track.file_path}。"
            "请确认中转目录里还有该文件；若已改名或删除，请重新上传/扫描后再试。",
            status_code=400,
        )

    # Prefer downloading cover before touching the session so API callers that
    # have not yet checked out a connection do not hold one during HTTP.
    cover: bytes | None = cover_data
    if cover is None and data.fetch_cover and (data.cover_url or data.album_mbid):
        cover = await fetch_cover_bytes(data.provider, data.album_mbid, data.cover_url)

    await session.refresh(track, attribute_names=["artist", "album", "artists"])
    old_album_id = track.album_id
    old_artist_ids = {artist.id for artist in track.artists}
    if track.artist_id:
        old_artist_ids.add(track.artist_id)

    artists = await _overwrite_artists(
        session, track, data.artist, names=data.artist_names
    )
    if not artists:
        raise ApplyError("Matched artist name is empty")
    artist = artists[0]
    album = await _overwrite_album(
        session,
        track,
        title=data.album or data.title,
        artist=artist,
        year=data.year,
        mbid=data.album_mbid,
    )

    if cover:
        await _save_cover(album, cover)
    elif data.clear_cover:
        await _clear_album_cover(album)

    # Artist avatars are independent of album cover fetch. QQ group credits often
    # lack per-person URLs, so always try (payload URLs first, then per-artist lookup).
    if artists:
        await _maybe_save_artist_avatars(
            artists,
            artist_image_url=data.artist_image_url,
            artist_images=data.artist_images,
            force=data.force_artist_images,
            provider=data.provider,
        )

    track.title = data.title
    track.mbid = data.mbid
    track.artist_id = artist.id
    track.album_id = album.id
    if data.duration and data.duration > 0 and not track.duration_ms:
        track.duration_ms = data.duration * 1000

    result = await session.execute(
        select(ProviderResult).where(
            ProviderResult.track_id == track.id,
            ProviderResult.provider_mbid == data.mbid,
        )
    )
    for row in result.scalars().all():
        row.applied = True

    if old_album_id and old_album_id != album.id:
        await _delete_orphan_album(session, old_album_id)
    new_artist_ids = {item.id for item in artists}
    for old_artist_id in old_artist_ids - new_artist_ids:
        await _delete_orphan_artist(session, old_artist_id)
    await _purge_empty_albums(session)

    artist_label = (
        join_artist_names(list(data.artist_names))
        if data.artist_names
        else (join_artist_names(data.artist) or data.artist)
    )
    if data.album_artist:
        album_artist_label = (
            data.album_artist.strip()
            if data.artist_names
            else (join_artist_names(data.album_artist) or artist_label)
        ) or artist_label
    else:
        album_artist_label = artist_label
    file_meta = AudioMetadata(
        title=data.title,
        artist=artist_label,
        album=data.album or data.title,
        album_artist=album_artist_label,
        year=data.year,
        cover_data=cover,
        clear_cover=bool(data.clear_cover and not cover),
    )
    written = await asyncio.to_thread(Tagger().write_metadata, track.file_path, file_meta)
    if not written:
        raise ApplyError(f"Failed to write tags to file: {track.file_path}")

    saved = await asyncio.to_thread(MetadataReader.read, track.file_path)
    if not saved or (saved.title or "").strip() != data.title.strip():
        raise ApplyError(f"Tags were not persisted to file: {track.file_path}")

    # Keep transfer-queue file-tag snapshot in sync with what is on disk now.
    has_cover = bool(saved.cover_data)
    if not has_cover:
        embedded = await asyncio.to_thread(MetadataReader.read_cover, track.file_path)
        has_cover = embedded is not None
    apply_file_tags(track, saved, has_cover=has_cover)

    await import_track_to_library(
        session,
        track,
        artist=artist_label,
        title=data.title,
        filename=data.filename,
    )
