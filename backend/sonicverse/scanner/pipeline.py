"""Scan pipeline: walks audio files, reads tags and persists them to the library."""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select, update

from sonicverse.core.artists import (
    artist_name_key,
    normalize_album_title,
    normalize_artist_name,
    split_artist_names,
)
from sonicverse.core.config import get_settings
from sonicverse.core.covers import cover_file_exists
from sonicverse.core.database import get_db_context
from sonicverse.core.paths import is_path_under, music_root, path_matches_configured_root, transfer_root
from sonicverse.library.delete import clear_library_catalog
from sonicverse.library.file_tags import apply_file_tags
from sonicverse.matcher.apply import (
    _delete_orphan_album,
    _delete_orphan_artist,
    _get_or_create_artist_by_name,
    _purge_empty_albums,
)
from sonicverse.metadata.parser import AudioMetadata, MetadataReader
from sonicverse.models import Album, Artist, ScanJob, ScanJobStatus, Track
from sonicverse.scanner.scanner import AudioScanner

logger = logging.getLogger(__name__)

settings = get_settings()

# How often to commit progress (in processed files).
_BATCH_SIZE = 100
# Parallel tag reads; SQLite upserts stay serial in this task.
_READ_CONCURRENCY = 8

# Cooperative cancellation: job ids requested to cancel.
_cancel_requests: set[str] = set()

# Serializes scan jobs - SQLite cannot handle concurrent writers anyway.
_scan_lock = asyncio.Lock()

# The event loop only holds weak references to tasks, so a scan task without a
# strong reference here can be garbage collected mid-run.
_running_tasks: set[asyncio.Task] = set()


def start_scan_job(job_id: str) -> None:
    """Schedule a scan job on the event loop."""
    task = asyncio.create_task(run_scan_job(job_id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


async def reset_interrupted_jobs() -> None:
    """Fail jobs left mid-flight by a previous process.

    Their asyncio task died with the process, so nothing would ever move them
    out of pending/running and the UI would show a progress bar forever.
    """
    async with get_db_context() as session:
        result = await session.execute(
            update(ScanJob)
            .where(
                ScanJob.status.in_(
                    [ScanJobStatus.PENDING.value, ScanJobStatus.RUNNING.value]
                )
            )
            .values(
                status=ScanJobStatus.FAILED.value,
                error_msg="Interrupted by a server restart",
            )
        )
        if result.rowcount:
            logger.warning("Reset %d interrupted scan job(s)", result.rowcount)


def request_cancel(job_id: str) -> None:
    """Request cooperative cancellation of a scan job."""
    _cancel_requests.add(job_id)


def _is_cancel_requested(job_id: str) -> bool:
    return job_id in _cancel_requests


def _detect_cover_ext(data: bytes) -> str:
    """Detect cover image extension from magic bytes."""
    if data.startswith(b"\x89PNG"):
        return ".png"
    return ".jpg"


class _LibraryCache:
    """Per-job memo of already-resolved artists and albums.

    Every track of a release resolves the same artist and album, so without
    this each file costs two extra SELECTs. Bounded by the number of distinct
    artists/albums in the scanned tree, and the objects stay valid across
    commits because the session uses expire_on_commit=False.
    """

    def __init__(self) -> None:
        self.artists: dict[str, Artist] = {}
        self.albums: dict[tuple[str, str | None], Album] = {}


async def _get_or_create_artist(session, cache: _LibraryCache, name: str) -> Artist:
    """Find an artist by exact name or create it."""
    canonical = normalize_artist_name(name)
    key = artist_name_key(canonical)
    cached = cache.artists.get(key)
    if cached is not None:
        return cached

    artist = await _get_or_create_artist_by_name(session, canonical)
    cache.artists[key] = artist
    return artist


async def _resolve_artists(
    session, cache: _LibraryCache, raw_name: str | None
) -> list[Artist]:
    """Split a credit string and resolve each name to an Artist row."""
    artists: list[Artist] = []
    for name in split_artist_names(raw_name):
        artists.append(await _get_or_create_artist(session, cache, name))
    return artists


async def _get_or_create_album(
    session, cache: _LibraryCache, title: str, artist: Artist | None, year: int | None
) -> Album:
    """Find an album by (title, artist) or create it."""
    title = normalize_album_title(title)
    artist_id = artist.id if artist else None
    key = (title, artist_id)

    album = cache.albums.get(key)
    if album is None:
        query = select(Album).where(Album.title == title)
        if artist_id is None:
            query = query.where(Album.artist_id.is_(None))
        else:
            query = query.where(Album.artist_id == artist_id)
        result = await session.execute(query.order_by(Album.id))
        album = result.scalars().first()
        if album is None:
            album = Album(title=title, artist_id=artist_id, year=year)
            session.add(album)
            await session.flush()
        cache.albums[key] = album

    if album.year is None and year is not None:
        album.year = year
    return album


async def _save_album_cover(session, album: Album, cover_data: bytes) -> None:
    """Persist embedded cover art to the covers directory and link it."""
    # Keep a valid on-disk cover; rewrite when the DB path is stale/missing.
    if album.cover_path and cover_file_exists(album.cover_path):
        return
    try:
        ext = _detect_cover_ext(cover_data)
        covers_dir = Path(settings.covers_path)
        covers_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{album.id}{ext}"
        await asyncio.to_thread((covers_dir / file_name).write_bytes, cover_data)
        # Store a URL path (served by the /covers static mount).
        album.cover_path = f"/covers/{file_name}"
        await session.flush()
    except Exception:
        logger.warning("Failed to save cover for album %s", album.id, exc_info=True)


async def _upsert_track(
    session,
    cache: _LibraryCache,
    file_path: Path,
    metadata: AudioMetadata,
    *,
    file_stamp: str | None = None,
) -> None:
    """Create or update Artist/Album/Track rows for one audio file."""
    # Prefer album artist for the album row; fall back to the track artist.
    album_artist_name = metadata.album_artist or metadata.artist
    track_artist_name = metadata.artist or metadata.album_artist

    track_artists_list = await _resolve_artists(session, cache, track_artist_name)
    album_artists_list = track_artists_list
    if album_artist_name and album_artist_name != track_artist_name:
        album_artists_list = await _resolve_artists(session, cache, album_artist_name)

    track_artist = track_artists_list[0] if track_artists_list else None
    album_artist = album_artists_list[0] if album_artists_list else None

    album = None
    cover = metadata.cover_data
    if cover is None:
        cover = await asyncio.to_thread(MetadataReader.read_cover, file_path)
    has_cover = cover is not None

    if metadata.album:
        album = await _get_or_create_album(
            session, cache, metadata.album, album_artist, metadata.year
        )
        needs_cover = not album.cover_path or not cover_file_exists(album.cover_path)
        if cover and needs_cover:
            await _save_album_cover(session, album, cover)

    title = metadata.title or file_path.stem
    stored_path = str(file_path)

    result = await session.execute(
        select(Track).where(Track.file_path.in_(list(_path_keys(file_path))))
    )
    track = result.scalars().first()
    if track is None:
        track = Track(file_path=stored_path, title=title)
        session.add(track)

    track.file_path = stored_path

    track.title = title
    track.artist_id = track_artist.id if track_artist else None
    track.artists = track_artists_list
    track.album_id = album.id if album else None
    track.track_number = metadata.track_number or 1
    track.disc_number = metadata.disc_number or 1
    track.duration_ms = metadata.duration_ms
    apply_file_tags(track, metadata, has_cover=has_cover)
    if file_stamp:
        track.file_hash = file_stamp


def _file_stamp(path: Path) -> str | None:
    """Cheap change token: size + mtime, stored on Track.file_hash."""
    try:
        stat = path.stat()
        mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
        return f"{int(stat.st_size)}:{mtime_ns}"
    except OSError:
        return None


async def _existing_file_stamps(session) -> dict[str, str | None]:
    result = await session.execute(select(Track.file_path, Track.file_hash))
    stamps: dict[str, str | None] = {}
    for file_path, file_hash in result.all():
        for key in _path_keys(file_path):
            stamps[key] = file_hash
    return stamps


def _cached_stamp(path: Path, stamps: dict[str, str | None]) -> str | None:
    for key in _path_keys(path):
        if key in stamps:
            return stamps[key]
    return None


def _path_keys(path: Path | str) -> set[str]:
    """Comparable path strings so stored rows match files from this scan."""
    raw = Path(str(path).split("?", 1)[0])
    keys = {str(raw), raw.as_posix()}
    try:
        resolved = raw.resolve()
        keys.update({str(resolved), resolved.as_posix()})
    except OSError:
        pass
    return keys


def _is_full_music_library_scan(scan_root: Path) -> bool:
    """True when this job scanned the configured music library root."""
    if _path_keys(scan_root) & _path_keys(music_root()):
        return True
    # Configured path as written in settings (often ``/music`` in Docker).
    return bool(_path_keys(scan_root) & _path_keys(Path(settings.music_path)))


def _is_transfer_scan(scan_root: Path) -> bool:
    """True when this job scanned the configured transfer inbox root."""
    if _path_keys(scan_root) & _path_keys(transfer_root()):
        return True
    return bool(_path_keys(scan_root) & _path_keys(Path(settings.transfer_path)))


def _track_belongs_to_scan_root(file_path: str, root: Path, *, music_scan: bool) -> bool:
    if is_path_under(file_path, root):
        return True
    if music_scan:
        return path_matches_configured_root(file_path, settings.music_path)
    return False


async def prune_tracks_absent_from_scan(
    session, root: Path, found: list[Path]
) -> int:
    """Remove library rows whose files were not found under ``root``.

    A settings-page library scan that finds nothing therefore clears the
    homepage entries that used to live in that folder. Tracks outside the
    scan root (e.g. transfer inbox) are left alone.
    """
    present: set[str] = set()
    for path in found:
        present.update(_path_keys(path))

    music_scan = _is_full_music_library_scan(root)
    result = await session.execute(select(Track))
    tracks = list(result.scalars().all())

    removed_artist_ids: set[str] = set()
    removed_album_ids: set[str] = set()
    removed = 0

    for track in tracks:
        if not _track_belongs_to_scan_root(
            track.file_path, root, music_scan=music_scan
        ):
            continue
        if _path_keys(track.file_path) & present:
            continue

        await session.refresh(track, attribute_names=["artists"])
        if track.artist_id:
            removed_artist_ids.add(track.artist_id)
        removed_artist_ids.update(artist.id for artist in track.artists)
        if track.album_id:
            removed_album_ids.add(track.album_id)
            album = await session.get(Album, track.album_id)
            if album is not None and album.artist_id:
                removed_artist_ids.add(album.artist_id)

        await session.delete(track)
        removed += 1

    if removed == 0:
        return 0

    await session.flush()
    for album_id in removed_album_ids:
        await _delete_orphan_album(session, album_id)
    await _purge_empty_albums(session)
    for artist_id in removed_artist_ids:
        await _delete_orphan_artist(session, artist_id)
    return removed


async def run_scan_job(job_id: str) -> None:
    """Execute a scan job in the background.

    Transitions: pending -> running -> completed | failed | cancelled.
    """
    async with _scan_lock:
        try:
            await _run_scan_job(job_id)
        except Exception:
            logger.error("Scan job %s crashed", job_id, exc_info=True)
            try:
                async with get_db_context() as session:
                    job = await session.get(ScanJob, job_id)
                    if job is not None:
                        job.status = ScanJobStatus.FAILED.value
                        job.error_msg = "Internal error, see server logs"
            except Exception:
                logger.error("Failed to mark job %s as failed", job_id, exc_info=True)
        finally:
            _cancel_requests.discard(job_id)


async def _run_scan_job(job_id: str) -> None:
    async with get_db_context() as session:
        job = await session.get(ScanJob, job_id)
        if job is None:
            logger.error("Scan job %s not found", job_id)
            return

        if _is_cancel_requested(job_id):
            job.status = ScanJobStatus.CANCELLED.value
            return

        from sonicverse.library.normalize_artists import heal_library_rows

        # Split combined credits and collapse duplicate names/albums before ingest.
        await heal_library_rows(session, commit=False)

        job.status = ScanJobStatus.RUNNING.value
        await session.flush()

        scanner = AudioScanner(job.root_path)
        files = await asyncio.to_thread(scanner.collect)
        job.tracks_found = len(files)
        await session.flush()

        cache = _LibraryCache()
        existing_stamps = await _existing_file_stamps(session)
        processed = 0
        need_read: list[tuple[Path, str | None]] = []
        for file_path in files:
            if _is_cancel_requested(job_id):
                job.status = ScanJobStatus.CANCELLED.value
                job.tracks_processed = processed
                logger.info("Scan job %s cancelled after %d files", job_id, processed)
                return
            stamp = _file_stamp(file_path)
            if stamp and _cached_stamp(file_path, existing_stamps) == stamp:
                processed += 1
                continue
            need_read.append((file_path, stamp))

        if processed:
            job.tracks_processed = processed
            await session.flush()

        for offset in range(0, len(need_read), _READ_CONCURRENCY):
            if _is_cancel_requested(job_id):
                job.status = ScanJobStatus.CANCELLED.value
                job.tracks_processed = processed
                logger.info("Scan job %s cancelled after %d files", job_id, processed)
                return

            chunk = need_read[offset : offset + _READ_CONCURRENCY]
            metas = await asyncio.gather(
                *[
                    asyncio.to_thread(MetadataReader.read, path, False)
                    for path, _ in chunk
                ]
            )
            for (file_path, stamp), metadata in zip(chunk, metas, strict=True):
                try:
                    if metadata is not None:
                        await _upsert_track(
                            session,
                            cache,
                            file_path,
                            metadata,
                            file_stamp=stamp,
                        )
                    else:
                        logger.warning("Skipped unreadable file: %s", file_path)
                except Exception:
                    logger.warning("Failed to process file: %s", file_path, exc_info=True)
                processed += 1

            if processed % _BATCH_SIZE == 0 or offset + _READ_CONCURRENCY >= len(need_read):
                job.tracks_processed = processed
                await session.commit()

        scan_root = Path(job.root_path).resolve()
        if not files and _is_full_music_library_scan(scan_root):
            # Settings-page library scan found nothing: wipe the catalog so
            # the homepage cannot keep showing stale albums/artists/tracks
            # (including rows whose stored paths no longer match this host).
            pruned = await clear_library_catalog(session)
        else:
            pruned = await prune_tracks_absent_from_scan(session, scan_root, files)
        job.tracks_processed = processed
        job.status = ScanJobStatus.COMPLETED.value
        logger.info(
            "Scan job %s completed: %d files, pruned %d missing",
            job_id,
            processed,
            pruned,
        )

        if _is_full_music_library_scan(scan_root):
            from sonicverse.scanner.fingerprint import save_music_fingerprint

            try:
                await asyncio.to_thread(save_music_fingerprint)
            except Exception:
                logger.warning(
                    "Failed to persist music fingerprint after scan %s",
                    job_id,
                    exc_info=True,
                )

        if _is_transfer_scan(scan_root):
            from sonicverse.scanner.fingerprint import save_transfer_fingerprint

            try:
                await asyncio.to_thread(save_transfer_fingerprint)
            except Exception:
                logger.warning(
                    "Failed to persist transfer fingerprint after scan %s",
                    job_id,
                    exc_info=True,
                )


async def ingest_audio_file(session, file_path: Path) -> Track:
    """Import one audio file into the library database."""
    resolved = file_path.resolve()
    cache = _LibraryCache()
    stamp = _file_stamp(resolved)
    metadata = await asyncio.to_thread(MetadataReader.read, resolved)
    if metadata is None:
        metadata = AudioMetadata(title=resolved.stem)
    await _upsert_track(session, cache, resolved, metadata, file_stamp=stamp)
    await session.flush()

    result = await session.execute(
        select(Track).where(Track.file_path == str(resolved))
    )
    track = result.scalar_one()
    await session.refresh(track, attribute_names=["artist", "album"])
    return track
