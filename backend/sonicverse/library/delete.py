"""Delete tracks/albums from the DB and best-effort remove audio/cover files."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from sonicverse.core.paths import is_path_under, is_transfer_path, music_root, transfer_root
from sonicverse.matcher.apply import _delete_orphan_album, _delete_orphan_artist
from sonicverse.models import Album, Artist, Track

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    """Raised when the target row does not exist."""


async def _unlink_managed_file(file_path: str | None) -> None:
    """Remove a file only if it lives under music or transfer roots."""
    if not file_path:
        return
    path = Path(file_path.split("?", 1)[0])
    try:
        if not (
            is_path_under(path, music_root()) or is_path_under(path, transfer_root())
        ):
            logger.warning("Refusing to delete unmanaged path: %s", file_path)
            return
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except Exception:
        logger.warning("Failed to delete file %s", file_path, exc_info=True)


async def _unlink_cover(cover_path: str | None) -> None:
    """Remove a cover file stored under /covers/…."""
    if not cover_path or not cover_path.startswith("/covers/"):
        return
    from sonicverse.core.config import get_settings

    try:
        cover_file = Path(cover_path.split("?", 1)[0]).name
        file_path = Path(get_settings().covers_path) / cover_file
        await asyncio.to_thread(file_path.unlink, missing_ok=True)
    except Exception:
        logger.warning("Failed to delete cover %s", cover_path, exc_info=True)


async def _touch_album(session, album_id: str) -> None:
    result = await session.execute(select(Album).where(Album.id == album_id))
    album = result.scalar_one_or_none()
    if album is not None:
        album.updated_at = datetime.now(timezone.utc)


async def delete_track(session, track_id: str) -> dict:
    """Delete a track, its audio file, orphan artists, and refresh album metadata."""
    result = await session.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise NotFoundError("Track not found")

    await session.refresh(track, attribute_names=["artists"])

    file_path = track.file_path
    album_id = track.album_id
    artist_ids = {artist.id for artist in track.artists}
    if track.artist_id:
        artist_ids.add(track.artist_id)
    album_artist_id: str | None = None
    if album_id:
        album_result = await session.execute(select(Album).where(Album.id == album_id))
        album = album_result.scalar_one_or_none()
        if album is not None:
            album_artist_id = album.artist_id

    await session.delete(track)
    await session.flush()

    if album_id:
        remaining = await session.scalar(
            select(Track.id).where(Track.album_id == album_id).limit(1)
        )
        if remaining is None:
            await _delete_orphan_album(session, album_id)
            if album_artist_id:
                artist_ids.add(album_artist_id)
        else:
            await _touch_album(session, album_id)

    for artist_id in artist_ids:
        await _delete_orphan_artist(session, artist_id)
    await session.commit()
    await _unlink_managed_file(file_path)

    return {"message": "Track deleted successfully", "deleted_tracks": 1}


async def delete_album(session, album_id: str) -> dict:
    """Delete an album, all of its tracks/files, and orphaned artists."""
    result = await session.execute(select(Album).where(Album.id == album_id))
    album = result.scalar_one_or_none()
    if album is None:
        raise NotFoundError("Album not found")

    tracks_result = await session.execute(
        select(Track).where(Track.album_id == album_id)
    )
    tracks = list(tracks_result.scalars().all())

    artist_ids: set[str] = set()
    if album.artist_id:
        artist_ids.add(album.artist_id)
    file_paths: list[str] = []
    for track in tracks:
        await session.refresh(track, attribute_names=["artists"])
        file_paths.append(track.file_path)
        if track.artist_id:
            artist_ids.add(track.artist_id)
        artist_ids.update(artist.id for artist in track.artists)
        await session.delete(track)

    await session.flush()

    cover_path = album.cover_path
    await session.delete(album)
    await session.flush()

    for artist_id in artist_ids:
        await _delete_orphan_artist(session, artist_id)

    await session.commit()

    for path in file_paths:
        await _unlink_managed_file(path)
    await _unlink_cover(cover_path)

    return {
        "message": "Album deleted successfully",
        "deleted_tracks": len(tracks),
    }


async def clear_library_catalog(session) -> int:
    """Remove music-library tracks/albums/artists (and cached cover/avatar files).

    Used when a full music-library scan finds no audio files. Transfer-inbox
    rows are kept so the pending queue is not wiped. Does not delete audio
    files on disk. Does not commit.
    """
    tracks = list((await session.execute(select(Track))).scalars().all())
    keep_track_ids = {track.id for track in tracks if is_transfer_path(track.file_path)}
    keep_album_ids: set[str] = set()
    keep_artist_ids: set[str] = set()
    for track in tracks:
        if track.id not in keep_track_ids:
            continue
        if track.album_id:
            keep_album_ids.add(track.album_id)
        if track.artist_id:
            keep_artist_ids.add(track.artist_id)
        keep_artist_ids.update(artist.id for artist in track.artists)

    albums = list((await session.execute(select(Album))).scalars().all())
    artists = list((await session.execute(select(Artist))).scalars().all())

    cover_paths = [
        album.cover_path for album in albums if album.id not in keep_album_ids
    ]
    avatar_paths = [
        artist.avatar_path for artist in artists if artist.id not in keep_artist_ids
    ]

    removed = 0
    for track in tracks:
        if track.id in keep_track_ids:
            continue
        await session.delete(track)
        removed += 1
    await session.flush()
    for album in albums:
        if album.id in keep_album_ids:
            continue
        await session.delete(album)
    await session.flush()
    for artist in artists:
        if artist.id in keep_artist_ids:
            continue
        await session.delete(artist)
    await session.flush()

    for cover_path in cover_paths:
        await _unlink_cover(cover_path)
    for avatar_path in avatar_paths:
        await _unlink_cover(avatar_path)

    return removed
