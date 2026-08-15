"""Match / refresh artist metadata (primarily avatar images)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sonicverse.matcher.apply import _download_image, _save_artist_avatar
from sonicverse.models import Artist
from sonicverse.providers import get_provider

logger = logging.getLogger(__name__)

_CANDIDATE_LIMIT = 12
_COLLECT_LIMIT = 20
_MIN_IMAGE_BYTES = 512


def _artist_name_matches(query: str, candidate: str) -> bool:
    """True when the candidate is the queried artist (exact or query in name)."""
    want = (query or "").casefold().strip()
    got = (candidate or "").casefold().strip()
    if not want or not got:
        return False
    return want == got or want in got


@dataclass(frozen=True)
class ArtistImageCandidate:
    name: str
    url: str
    provider: str


def _collect_track_images(artist_name: str, results) -> list[tuple[str, str]]:
    seen: set[str] = set()
    hits: list[tuple[str, str]] = []

    def add(name: str, url: str) -> None:
        url = (url or "").strip()
        name = (name or "").strip()
        if not url or not name or url in seen:
            return
        if not _artist_name_matches(artist_name, name):
            return
        seen.add(url)
        hits.append((name, url))

    for result in results:
        for item in result.artist_images or ():
            add(item.get("name") or "", item.get("url") or "")
    return hits


def _looks_like_image(data: bytes) -> bool:
    if len(data) < _MIN_IMAGE_BYTES:
        return False
    if data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG"):
        return True
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return data[:6] in (b"GIF87a", b"GIF89a")


async def _url_has_image(url: str) -> bool:
    data = await _download_image(url)
    return bool(data) and _looks_like_image(data)


async def _keep_reachable(
    hits: list[ArtistImageCandidate],
) -> list[ArtistImageCandidate]:
    if not hits:
        return []
    flags = await asyncio.gather(*(_url_has_image(item.url) for item in hits))
    return [item for item, ok in zip(hits, flags, strict=True) if ok]


async def search_artist_images(
    artist_name: str,
    provider_name: str = "qqmusic",
) -> list[ArtistImageCandidate]:
    """Return unique avatar URLs for the artist, without writing the avatar."""
    name = (artist_name or "").strip()
    if not name:
        return []
    provider = get_provider(provider_name)
    hits: list[ArtistImageCandidate] = []
    seen: set[str] = set()

    def append(person: str, url: str) -> None:
        url = (url or "").strip()
        person = (person or "").strip()
        if not url or not person or url in seen:
            return
        if not _artist_name_matches(name, person):
            return
        seen.add(url)
        hits.append(
            ArtistImageCandidate(
                name=person,
                url=url,
                provider=provider.name,
            )
        )

    try:
        for item in await provider.lookup_artist_images(name):
            append(item.get("name") or "", item.get("url") or "")
    except Exception:
        logger.warning(
            "Artist image list lookup failed for %s via %s",
            name,
            provider_name,
            exc_info=True,
        )

    if len(hits) < _COLLECT_LIMIT:
        try:
            results = await provider.search_track(title="", artist=name)
        except Exception:
            logger.warning(
                "Artist metadata search failed for %s via %s",
                name,
                provider_name,
                exc_info=True,
            )
            results = []
        for person, url in _collect_track_images(name, results):
            append(person, url)
            if len(hits) >= _COLLECT_LIMIT:
                break

    return (await _keep_reachable(hits))[:_CANDIDATE_LIMIT]


async def apply_artist_image(
    session,
    artist: Artist,
    *,
    image_url: str | None = None,
    image_bytes: bytes | None = None,
) -> Artist:
    """Write a chosen (or uploaded) image onto the artist avatar."""
    data = image_bytes if image_bytes else None
    if not data:
        data = await _download_image(image_url)
    if not data:
        return artist
    await _save_artist_avatar(artist, data)
    await session.flush()
    return artist


async def match_artist_metadata(
    session,
    artist: Artist,
    provider_name: str = "qqmusic",
    *,
    force: bool = True,
) -> Artist:
    """Search the provider and update the artist's avatar when found."""
    if artist.avatar_path and not force:
        return artist

    candidates = await search_artist_images(artist.name, provider_name)
    if not candidates:
        return artist
    return await apply_artist_image(session, artist, image_url=candidates[0].url)
