"""File-embedded tag snapshot helpers for the transfer queue."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import or_, select

from sonicverse.core.paths import transfer_file_path_filter
from sonicverse.metadata.parser import AudioMetadata, MetadataReader
from sonicverse.models import Track

logger = logging.getLogger(__name__)


def apply_file_tags(track: Track, metadata: AudioMetadata, *, has_cover: bool) -> None:
    """Store the audio file's own tags (independent of library/apply fields)."""
    title = (metadata.title or "").strip()
    artist = (metadata.artist or metadata.album_artist or "").strip()
    album = (metadata.album or "").strip()
    track.tag_title = title or Path(track.file_path).stem
    track.tag_artist = artist or None
    track.tag_album = album or None
    track.tag_has_cover = bool(has_cover)


async def refresh_missing_file_tags(session, *, limit: int = 500) -> int:
    """Backfill tag_* for transfer tracks that predate the file-tag columns."""
    result = await session.execute(
        select(Track)
        .where(
            transfer_file_path_filter(),
            or_(Track.tag_title.is_(None), Track.tag_has_cover.is_(None)),
        )
        .limit(limit)
    )
    tracks = list(result.scalars().all())
    if not tracks:
        return 0

    updated = 0
    for track in tracks:
        path = Path(track.file_path)
        if not path.is_file():
            continue
        try:
            metadata = await asyncio.to_thread(MetadataReader.read, path, True)
        except Exception:
            logger.debug("Could not read tags for %s", path, exc_info=True)
            continue
        if metadata is None:
            metadata = AudioMetadata()
        apply_file_tags(track, metadata, has_cover=bool(metadata.cover_data))
        updated += 1

    if updated:
        await session.commit()
    return updated
