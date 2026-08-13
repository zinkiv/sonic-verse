"""Move a confirmed track from /transfer into /music and rename it."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from sonicverse.core.artists import join_artist_names
from sonicverse.metadata.parser import AudioMetadata
from sonicverse.models import Track
from sonicverse.organizer.organizer import FileOrganizer, path_keys

logger = logging.getLogger(__name__)


def filename_artist_for_track(track: Track) -> str:
    """Build the ``歌手名[,歌手名]`` segment from a track's credits."""
    credits = list(track.artists or [])
    if not credits and track.artist is not None:
        credits = [track.artist]
    if track.artist_id:
        credits.sort(key=lambda artist: (0 if artist.id == track.artist_id else 1, artist.name))
    return join_artist_names([artist.name for artist in credits])


async def _remove_conflicting_tracks(session, track: Track, destination: Path) -> None:
    """Drop other DB rows that already claim the destination path."""
    # Local import avoids a module-level cycle with matcher.apply → import_file.
    from sonicverse.library.delete import delete_track

    desired = path_keys(destination)
    result = await session.execute(select(Track).where(Track.id != track.id))
    for other in result.scalars().all():
        if path_keys(other.file_path) & desired:
            await delete_track(session, other.id)


async def import_track_to_library(
    session,
    track: Track,
    *,
    artist: str,
    title: str,
) -> Path | None:
    """Rename to ``歌手名-歌曲名`` and move into the music library.

    Files still in /transfer are imported (and the transfer copy is removed).
    An existing file at the destination is overwritten (no `` (2)`` suffix).
    Missing source files are left unchanged.
    """
    source = Path(track.file_path)
    if not source.exists():
        logger.warning("Skip library import, source missing: %s", source)
        return None

    organizer = FileOrganizer()
    metadata = AudioMetadata(title=title, artist=artist)
    destination = organizer.get_destination_path(metadata, source)
    await _remove_conflicting_tracks(session, track, destination)

    moved = organizer.organize_file(
        source,
        metadata,
        destination=destination,
        overwrite=True,
    )
    if moved is None:
        logger.warning("Library import skipped for %s", track.id)
        return None

    track.file_path = str(moved)
    return moved
