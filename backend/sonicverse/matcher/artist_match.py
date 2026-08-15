"""Match / refresh artist metadata (primarily avatar images)."""

from __future__ import annotations

import logging

from sonicverse.matcher.apply import _download_image, _save_artist_avatar
from sonicverse.models import Artist
from sonicverse.providers import get_provider

logger = logging.getLogger(__name__)


def _pick_artist_image_url(artist_name: str, results) -> str | None:
    """Prefer an image whose singer name matches ``artist_name``."""
    target = artist_name.casefold().strip()
    if not target:
        return None

    for result in results:
        for item in result.artist_images or ():
            name = (item.get("name") or "").strip()
            url = (item.get("url") or "").strip()
            if name and url and name.casefold() == target:
                return url

    for result in results:
        credited = (result.artist or "").casefold()
        if target in credited or credited in target:
            if result.artist_image_url:
                return result.artist_image_url
            for item in result.artist_images or ():
                url = (item.get("url") or "").strip()
                if url:
                    return url

    for result in results:
        if result.artist_image_url:
            return result.artist_image_url
        for item in result.artist_images or ():
            url = (item.get("url") or "").strip()
            if url:
                return url
    return None


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

    provider = get_provider(provider_name)
    image_url: str | None = None
    try:
        image_url = await provider.lookup_artist_image(artist.name)
    except Exception:
        logger.warning(
            "Artist direct image lookup failed for %s via %s",
            artist.name,
            provider_name,
            exc_info=True,
        )

    if not image_url:
        try:
            results = await provider.search_track(title="", artist=artist.name)
        except Exception:
            logger.warning(
                "Artist metadata search failed for %s via %s",
                artist.name,
                provider_name,
                exc_info=True,
            )
            raise
        image_url = _pick_artist_image_url(artist.name, results)

    if not image_url:
        return artist

    image = await _download_image(image_url)
    if not image:
        return artist

    await _save_artist_avatar(artist, image)
    await session.flush()
    return artist
