"""Move a library track from /music into the /transfer inbox for rematch."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from sqlalchemy import delete, select

from sonicverse.core.paths import is_music_path, is_transfer_path, music_root, transfer_root
from sonicverse.matcher.apply import _delete_orphan_album, _delete_orphan_artist
from sonicverse.models import ProviderResult, Track
from sonicverse.organizer.organizer import prune_empty_parents

logger = logging.getLogger(__name__)


class StageError(Exception):
    """Raised when a library file cannot be staged into /transfer."""


def _unique_transfer_path(root: Path, filename: str) -> Path:
    candidate = root / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        alt = root / f"{stem} ({counter}){suffix}"
        if not alt.exists():
            return alt
        counter += 1


def _move_to_transfer(source: Path) -> Path:
    root = transfer_root()
    root.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise StageError(f"Source file missing: {source}")

    try:
        if source.resolve() == root.resolve() or root.resolve() in source.resolve().parents:
            return source.resolve()
    except OSError as exc:
        raise StageError(f"Cannot resolve source path: {source}") from exc

    destination = _unique_transfer_path(root, source.name)
    shutil.move(str(source), str(destination))
    prune_empty_parents(source.parent, stop_at=music_root())
    return destination.resolve()


async def _reset_match_metadata(session, track: Track) -> None:
    """Drop prior match state and detach library album/artist links."""
    await session.refresh(track, attribute_names=["artists", "album", "artist"])

    old_album_id = track.album_id
    old_artist_ids = {artist.id for artist in track.artists}
    if track.artist_id:
        old_artist_ids.add(track.artist_id)
    if track.album is not None and track.album.artist_id:
        old_artist_ids.add(track.album.artist_id)

    track.mbid = None
    track.album_id = None
    track.artist_id = None
    track.artists = []

    await session.execute(
        delete(ProviderResult).where(ProviderResult.track_id == track.id)
    )
    await session.flush()

    if old_album_id:
        await _delete_orphan_album(session, old_album_id)
    for artist_id in old_artist_ids:
        await _delete_orphan_artist(session, artist_id)


async def stage_track_to_transfer(session, track: Track) -> Path:
    """Move a /music file into /transfer and reset library match metadata.

    Already-staged transfer files only refresh match state. Does not commit.
    """
    source = Path(track.file_path.split("?", 1)[0])
    already_transfer = is_transfer_path(track.file_path)

    if already_transfer:
        destination = source
    else:
        if not is_music_path(track.file_path):
            raise StageError("Track file is not in the music library")

        destination = await asyncio.to_thread(_move_to_transfer, source)

        clash = await session.scalar(
            select(Track.id).where(
                Track.id != track.id,
                Track.file_path == str(destination),
            )
        )
        if clash is not None:
            raise StageError(f"Transfer path already claimed: {destination}")

        track.file_path = str(destination)

    await _reset_match_metadata(session, track)

    # Rebuild title/artist/album from on-disk tags as a fresh transfer row.
    from sonicverse.scanner.pipeline import ingest_audio_file

    refreshed = await ingest_audio_file(session, destination)
    if refreshed.id != track.id:
        raise StageError("Staged file resolved to a different track row")
    track.mbid = None

    if not already_transfer:
        from sonicverse.scanner.fingerprint import save_music_fingerprint

        await asyncio.to_thread(save_music_fingerprint)

    logger.info("Staged track %s to transfer: %s", track.id, destination)
    return destination
