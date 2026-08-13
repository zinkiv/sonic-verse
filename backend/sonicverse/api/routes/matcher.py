"""Metadata matching API routes."""

import json
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from sonicverse.api.dependencies import DbSession
from sonicverse.core.user_settings import get_match_confidence_threshold
from sonicverse.library.import_file import (
    filename_artist_for_track,
    import_track_to_library,
)
from sonicverse.library.stage import StageError, stage_track_to_transfer
from sonicverse.matcher.apply import (
    LOCAL_CONFIRMED_MBID,
    ApplyError,
    ApplyPayload,
    apply_match_to_track,
)
from sonicverse.matcher.batch import request_cancel, start_match_job
from sonicverse.matcher.percent import as_match_percent, clamp_match_threshold
from sonicverse.matcher.search import search_and_store_candidates
from sonicverse.models import MatchJob, MatchJobStatus, ProviderResult, Track
from sonicverse.providers import provider_rank
from sonicverse.schemas import TrackDetailResponse
from sonicverse.schemas.match import (
    MatchApplyRequest,
    MatchCandidate,
    MatchCandidatesResponse,
    MatchRequest,
    ProviderName,
)
from sonicverse.schemas.match_job import BatchMatchRequest, MatchJobResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracks", tags=["matching"])
jobs_router = APIRouter(prefix="/match-jobs", tags=["matching"])


async def _track_detail(db, track_id: str) -> TrackDetailResponse:
    """Re-load a track after commit so response serialization stays async-safe."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one()
    _ = track.artist
    _ = track.album
    return TrackDetailResponse.from_track(track)


@router.post("/batch-match", response_model=MatchJobResponse, status_code=201)
async def create_batch_match_job(
    db: DbSession,
    data: BatchMatchRequest,
) -> MatchJobResponse:
    """Start a batch match job (high score auto-apply, low score needs review)."""
    threshold = clamp_match_threshold(
        data.threshold
        if data.threshold is not None
        else get_match_confidence_threshold()
    )

    track_ids_json: str | None = None
    if data.track_ids is not None:
        if len(data.track_ids) == 0:
            raise HTTPException(status_code=400, detail="track_ids must not be empty")
        # Validate ids exist up front.
        result = await db.execute(select(Track.id).where(Track.id.in_(data.track_ids)))
        found = set(result.scalars().all())
        missing = [tid for tid in data.track_ids if tid not in found]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown track ids: {', '.join(missing[:5])}",
            )
        track_ids_json = json.dumps(list(dict.fromkeys(data.track_ids)))

    job = MatchJob(
        status=MatchJobStatus.PENDING.value,
        provider=data.provider,
        threshold=threshold,
        auto_apply=data.auto_apply,
        scope=data.scope if data.track_ids is None else "pending",
        force_refresh_images=data.force_refresh_images,
        track_ids_json=track_ids_json,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    start_match_job(job.id)
    return MatchJobResponse.model_validate(job)


@jobs_router.get("/{job_id}", response_model=MatchJobResponse)
async def get_match_job(db: DbSession, job_id: str) -> MatchJobResponse:
    result = await db.execute(select(MatchJob).where(MatchJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Match job not found")
    return MatchJobResponse.model_validate(job)


@jobs_router.post("/{job_id}/cancel", response_model=MatchJobResponse)
async def cancel_match_job(db: DbSession, job_id: str) -> MatchJobResponse:
    result = await db.execute(select(MatchJob).where(MatchJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Match job not found")

    if job.status not in (MatchJobStatus.PENDING.value, MatchJobStatus.RUNNING.value):
        raise HTTPException(status_code=409, detail="Job is not cancellable")

    request_cancel(job.id)
    if job.status == MatchJobStatus.PENDING.value:
        job.status = MatchJobStatus.CANCELLED.value
        await db.commit()
        await db.refresh(job)

    return MatchJobResponse.model_validate(job)


@router.get("/{track_id}/candidates", response_model=MatchCandidatesResponse)
async def get_stored_candidates(db: DbSession, track_id: str) -> MatchCandidatesResponse:
    """Return unapplied provider candidates previously stored for a track."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")

    rows = (
        await db.execute(
            select(ProviderResult)
            .where(
                ProviderResult.track_id == track_id,
                ProviderResult.applied.is_(False),
            )
        )
    ).scalars().all()

    candidates: list[MatchCandidate] = []
    for row in rows:
        payload = dict(row.metadata_json or {})
        payload.setdefault("title", "")
        payload.setdefault("artist", "")
        payload.setdefault("album", "")
        payload.setdefault("mbid", row.provider_mbid)
        payload.setdefault("confidence", row.confidence)
        payload.setdefault("score", row.confidence)
        payload.setdefault("provider", row.provider)
        payload["confidence"] = as_match_percent(payload.get("confidence"))
        payload["score"] = as_match_percent(payload.get("score"))
        try:
            candidates.append(MatchCandidate.model_validate(payload))
        except Exception:
            continue

    candidates.sort(
        key=lambda item: (
            -(item.score or item.confidence or 0),
            provider_rank(item.provider),
        )
    )
    top_provider: ProviderName = (
        candidates[0].provider if candidates and candidates[0].provider else "netease"
    )
    return MatchCandidatesResponse(
        track_id=track.id,
        provider=top_provider,
        candidates=candidates,
    )


@router.post("/{track_id}/match", response_model=MatchCandidatesResponse)
async def match_track(
    db: DbSession,
    track_id: str,
    data: MatchRequest | None = None,
) -> MatchCandidatesResponse:
    """Search the selected provider and persist ranked candidates."""
    body = data or MatchRequest()
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")

    if body.stage_to_transfer:
        try:
            await stage_track_to_transfer(db, track)
        except StageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await db.commit()
        await db.refresh(track)

    await db.refresh(track, attribute_names=["artist", "album"])
    if not (track.title or "").strip():
        raise HTTPException(status_code=400, detail="Track has no title to match on")

    try:
        candidates = await search_and_store_candidates(db, track, body.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    return MatchCandidatesResponse(
        track_id=track.id,
        provider=body.provider,
        candidates=candidates,
    )


@router.post("/{track_id}/apply", response_model=TrackDetailResponse)
async def apply_match(
    db: DbSession,
    track_id: str,
    data: MatchApplyRequest,
) -> TrackDetailResponse:
    """Overwrite local track/album/artist with a provider candidate."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")

    payload = ApplyPayload(
        title=data.title,
        artist=data.artist,
        album=data.album,
        mbid=data.mbid,
        album_mbid=data.album_mbid,
        year=data.year,
        duration=data.duration,
        fetch_cover=data.fetch_cover,
        cover_url=data.cover_url,
        artist_image_url=data.artist_image_url,
        artist_images=tuple(data.artist_images) if data.artist_images else None,
        provider=data.provider,
    )
    cover = None
    if payload.fetch_cover and (payload.cover_url or payload.album_mbid):
        from sonicverse.matcher.apply import fetch_cover_bytes

        # Download before further DB work so the connection is not held idle.
        await db.commit()
        cover = await fetch_cover_bytes(
            payload.provider, payload.album_mbid, payload.cover_url
        )
    try:
        await apply_match_to_track(db, track, payload, cover_data=cover)
    except ApplyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=exc.message) from exc

    await db.commit()
    return await _track_detail(db, track.id)


@router.post("/{track_id}/confirm-local", response_model=TrackDetailResponse)
async def confirm_local(db: DbSession, track_id: str) -> TrackDetailResponse:
    """Accept current local tags and remove the track from pending review."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")

    if not track.mbid:
        track.mbid = LOCAL_CONFIRMED_MBID

    await db.refresh(track, attribute_names=["artist", "artists"])
    await import_track_to_library(
        db,
        track,
        artist=filename_artist_for_track(track),
        title=track.title,
    )

    await db.commit()
    return await _track_detail(db, track.id)
