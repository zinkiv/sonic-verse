"""Batch match pipeline: search → threshold gate → auto-apply or queue for review."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from sqlalchemy import select, update

from sonicverse.core.database import async_session_maker, get_db_context
from sonicverse.core.paths import transfer_file_path_filter
from sonicverse.matcher.apply import (
    ApplyError,
    ApplyPayload,
    apply_match_to_track,
    fetch_cover_bytes,
    refresh_artists_from_candidate,
)
from sonicverse.matcher.percent import as_match_percent, clamp_match_threshold
from sonicverse.matcher.search import search_and_store_candidates
from sonicverse.models import MatchJob, MatchJobStatus, Track

logger = logging.getLogger(__name__)

# Gentle pacing so QQ / Netease are less likely to rate-limit.
# Per-provider interval is shared by all workers; 8 workers × 2 providers
# still serialize to ~8 searches/sec per API.
_PROVIDER_PAUSE_SEC = 0.12
_TRACK_WORKERS = 8

_cancel_requests: set[str] = set()
_match_lock = asyncio.Lock()
_running_tasks: set[asyncio.Task] = set()


class _ProviderThrottle:
    """Provider-aware throttling shared by all workers in one job."""

    def __init__(self, interval_sec: float) -> None:
        self.interval_sec = max(0.0, float(interval_sec))
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_allowed: dict[str, float] = {}

    async def acquire(self, provider_name: str) -> None:
        if self.interval_sec <= 0:
            return
        key = (provider_name or "unknown").strip().lower() or "unknown"
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            ready_at = self._next_allowed.get(key, now)
            wait_for = ready_at - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)
                now = time.monotonic()
            self._next_allowed[key] = now + self.interval_sec


def start_match_job(job_id: str) -> None:
    """Schedule a batch match job on the event loop."""
    task = asyncio.create_task(run_match_job(job_id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


async def reset_interrupted_match_jobs() -> None:
    """Fail jobs left mid-flight by a previous process."""
    async with get_db_context() as session:
        result = await session.execute(
            update(MatchJob)
            .where(
                MatchJob.status.in_(
                    [MatchJobStatus.PENDING.value, MatchJobStatus.RUNNING.value]
                )
            )
            .values(
                status=MatchJobStatus.FAILED.value,
                error_msg="Interrupted by a server restart",
            )
        )
        if result.rowcount:
            logger.warning("Reset %d interrupted match job(s)", result.rowcount)


def request_cancel(job_id: str) -> None:
    """Request cooperative cancellation of a match job."""
    _cancel_requests.add(job_id)


def _is_cancel_requested(job_id: str) -> bool:
    return job_id in _cancel_requests


def _candidate_score(candidate) -> int:
    score = getattr(candidate, "score", None)
    if score is not None:
        return as_match_percent(score)
    return as_match_percent(getattr(candidate, "confidence", None))


def _meets_threshold(score: int | float, threshold: int | float) -> bool:
    """Compare integer percent scores against the auto-apply threshold."""
    return as_match_percent(score) >= clamp_match_threshold(threshold)


async def _resolve_track_ids(session, job: MatchJob) -> list[str]:
    if job.track_ids_json:
        raw = json.loads(job.track_ids_json)
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]

    query = select(Track.id).order_by(Track.title, Track.id)
    if job.scope == "transfer":
        # Process every track still sitting in the transfer inbox.
        query = query.where(transfer_file_path_filter())
    elif job.scope == "all":
        # Full-library refresh: every track, matched or not.
        pass
    else:
        query = query.where(Track.mbid.is_(None))
    result = await session.execute(query)
    return list(result.scalars().all())


async def run_match_job(job_id: str) -> None:
    """Process a MatchJob serially (SQLite-friendly)."""
    async with _match_lock:
        try:
            await _run_match_job_locked(job_id)
        finally:
            _cancel_requests.discard(job_id)


async def _run_match_job_locked(job_id: str) -> None:
    async with get_db_context() as session:
        job = await session.get(MatchJob, job_id)
        if job is None:
            return
        if _is_cancel_requested(job_id):
            job.status = MatchJobStatus.CANCELLED.value
            return

        track_ids = await _resolve_track_ids(session, job)
        job.tracks_total = len(track_ids)
        job.tracks_processed = 0
        job.auto_applied = 0
        job.needs_review = 0
        job.unmatched = 0
        job.failed = 0
        job.status = MatchJobStatus.RUNNING.value

    if track_ids:
        throttle = _ProviderThrottle(_PROVIDER_PAUSE_SEC)
        queue: asyncio.Queue[str] = asyncio.Queue()
        for track_id in track_ids:
            queue.put_nowait(track_id)

        async def worker() -> None:
            while True:
                if _is_cancel_requested(job_id):
                    return
                try:
                    track_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await _process_one_track(
                        job_id,
                        track_id,
                        before_provider_search=throttle.acquire,
                    )
                finally:
                    queue.task_done()

        worker_count = min(_TRACK_WORKERS, len(track_ids))
        tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        await asyncio.gather(*tasks)

    async with get_db_context() as session:
        job = await session.get(MatchJob, job_id)
        if job is None:
            return
        if _is_cancel_requested(job_id):
            job.status = MatchJobStatus.CANCELLED.value
        elif job.status == MatchJobStatus.RUNNING.value:
            job.status = MatchJobStatus.COMPLETED.value


async def _bump_job(job_id: str, **deltas: int) -> None:
    """Atomically increment MatchJob counters (safe under concurrent workers)."""
    values = {
        key: getattr(MatchJob, key) + int(value)
        for key, value in deltas.items()
        if int(value)
    }
    if not values:
        return
    async with get_db_context() as session:
        await session.execute(
            update(MatchJob).where(MatchJob.id == job_id).values(**values)
        )


async def _process_one_track(
    job_id: str,
    track_id: str,
    *,
    before_provider_search=None,
) -> None:
    # Phase 1: search + store candidates (committed even if apply later fails).
    # Outcome counters are mutually exclusive so:
    # tracks_processed == auto_applied + needs_review + unmatched + failed
    payload: ApplyPayload | None = None
    artist_image_url: str | None = None
    artist_images = None
    outcome: str | None = None

    async with get_db_context() as session:
        job = await session.get(MatchJob, job_id)
        track = await session.get(Track, track_id)
        if job is None:
            return
        if track is None:
            outcome = "failed"
        else:
            threshold = clamp_match_threshold(job.threshold)
            auto_apply = bool(job.auto_apply)
            try:
                candidates = await search_and_store_candidates(
                    session,
                    track,
                    before_provider_search=before_provider_search,
                    batch_organize=True,
                )
            except Exception:
                logger.exception("Batch match search failed for track %s", track_id)
                outcome = "failed"
                candidates = None

            if outcome is None and not candidates:
                outcome = "unmatched"
            elif outcome is None:
                top = candidates[0]
                score = _candidate_score(top)
                artist_image_url = top.artist_image_url
                artist_images = top.artist_images
                if auto_apply and _meets_threshold(score, threshold):
                    payload = ApplyPayload(
                        title=top.title,
                        artist=top.artist,
                        album=top.album or top.title,
                        mbid=top.mbid,
                        album_mbid=top.album_mbid,
                        year=top.year,
                        duration=top.duration or None,
                        fetch_cover=True,
                        cover_url=top.cover_url,
                        artist_image_url=top.artist_image_url,
                        artist_images=(
                            tuple(top.artist_images) if top.artist_images else None
                        ),
                        force_artist_images=True,
                        provider=top.provider or "netease",
                    )
                else:
                    outcome = "needs_review"

    if outcome == "failed":
        await _bump_job(job_id, failed=1, tracks_processed=1)
        return
    if outcome == "unmatched":
        await _bump_job(job_id, unmatched=1, tracks_processed=1)
        return
    if outcome == "needs_review":
        await _bump_job(job_id, needs_review=1, tracks_processed=1)

    # Avatar HTTP outside any open DB transaction.
    if artist_image_url or artist_images:
        async with get_db_context() as session:
            track = await session.get(Track, track_id)
            if track is not None:
                try:
                    await refresh_artists_from_candidate(
                        session,
                        track,
                        artist_image_url=artist_image_url,
                        artist_images=artist_images,
                        force=True,
                    )
                except Exception:
                    logger.warning(
                        "Artist metadata refresh failed for %s",
                        track_id,
                        exc_info=True,
                    )

    if outcome == "needs_review" or payload is None:
        return

    # Download cover before opening the apply session.
    cover: bytes | None = None
    if payload.fetch_cover and (payload.cover_url or payload.album_mbid):
        cover = await fetch_cover_bytes(
            payload.provider, payload.album_mbid, payload.cover_url
        )

    # Phase 2: auto-apply in a fresh session so a tag write failure only rolls
    # back this phase (candidates from phase 1 stay available for review).
    async with async_session_maker() as session:
        try:
            track = await session.get(Track, track_id)
            if track is None:
                await _bump_job(job_id, failed=1, tracks_processed=1)
                return
            await apply_match_to_track(
                session, track, payload, cover_data=cover
            )
            await session.commit()
        except ApplyError as exc:
            logger.warning("Auto-apply failed for %s: %s", track_id, exc.message)
            await session.rollback()
            await _bump_job(job_id, failed=1, tracks_processed=1)
            return
        except Exception:
            logger.exception("Auto-apply crashed for track %s", track_id)
            await session.rollback()
            await _bump_job(job_id, failed=1, tracks_processed=1)
            return

    await _bump_job(job_id, auto_applied=1, tracks_processed=1)
