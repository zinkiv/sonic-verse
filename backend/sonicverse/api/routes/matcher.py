"""Metadata matching API routes."""

import asyncio
import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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
from sonicverse.metadata.parser import MetadataReader
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

_MAX_COVER_BYTES = 12 * 1024 * 1024


def _manual_mbid(track_id: str) -> str:
    return f"manual:{track_id}"


def _looks_like_image(data: bytes) -> bool:
    if len(data) < 12:
        return False
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return True
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return True
    return False


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
        force_artist_images=bool(data.artist_image_url or data.artist_images),
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
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await db.commit()
    return await _track_detail(db, track.id)


@router.post("/{track_id}/manual-save", response_model=TrackDetailResponse)
async def manual_save(
    db: DbSession,
    track_id: str,
    title: str = Form(...),
    artist: str = Form(...),
    album: str = Form(""),
    album_artist: str | None = Form(None),
    filename: str | None = Form(None),
    year: str | None = Form(None),
    mbid: str | None = Form(None),
    album_mbid: str | None = Form(None),
    duration: str | None = Form(None),
    provider: str = Form("qqmusic"),
    cover_url: str | None = Form(None),
    cover_source: str | None = Form(None),
    cover: UploadFile | None = File(None),
    artist_image_url: str | None = Form(None),
    artist_images: str | None = Form(None),
    artist_names: str | None = Form(None),
) -> TrackDetailResponse:
    """Write user-edited tags (optional cover upload) and import into the library."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")

    clean_title = (title or "").strip()
    clean_artist = (artist or "").strip()
    clean_album = (album or "").strip() or clean_title
    clean_album_artist = (album_artist or "").strip() or None
    clean_filename = (filename or "").strip() or None
    if not clean_title or not clean_artist:
        raise HTTPException(status_code=400, detail="title and artist are required")

    parsed_year: int | None = None
    if year is not None and str(year).strip():
        try:
            parsed_year = int(str(year).strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="year must be an integer") from exc

    parsed_duration: int | None = None
    if duration is not None and str(duration).strip():
        try:
            parsed_duration = int(str(duration).strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="duration must be an integer") from exc

    source = (cover_source or "").strip().lower()
    cover_data: bytes | None = None
    clear_cover = source in {"none", "clear"}

    if cover is not None and (cover.filename or cover.content_type):
        raw = await cover.read(_MAX_COVER_BYTES + 1)
        if len(raw) > _MAX_COVER_BYTES:
            raise HTTPException(status_code=400, detail="Cover image is too large (max 12MB)")
        if raw and not _looks_like_image(raw):
            raise HTTPException(status_code=400, detail="Cover must be a PNG, JPEG, GIF, or WebP image")
        cover_data = raw or None
        source = "upload"
        clear_cover = False

    if cover_data is None and source == "file":
        cover_data = await asyncio.to_thread(MetadataReader.read_cover, track.file_path)

    clean_mbid = (mbid or "").strip() or _manual_mbid(track.id)
    clean_album_mbid = (album_mbid or "").strip() or None
    clean_cover_url = (cover_url or "").strip() or None
    # Blob / local API preview URLs are not fetchable as remote covers.
    if clean_cover_url and (
        clean_cover_url.startswith("blob:")
        or "/api/v1/tracks/" in clean_cover_url
    ):
        clean_cover_url = None

    if cover_data is None and not clear_cover and source != "file" and clean_cover_url:
        from sonicverse.matcher.apply import fetch_cover_bytes

        await db.commit()
        cover_data = await fetch_cover_bytes(
            provider if provider in ("qqmusic", "netease") else "netease",
            clean_album_mbid,
            clean_cover_url,
        )

    parsed_artist_images: list[dict[str, str]] | None = None
    if artist_images and str(artist_images).strip():
        try:
            raw_images = json.loads(artist_images)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail="artist_images must be a JSON array"
            ) from exc
        if not isinstance(raw_images, list):
            raise HTTPException(
                status_code=400, detail="artist_images must be a JSON array"
            )
        parsed_artist_images = []
        for item in raw_images:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            if name and url:
                parsed_artist_images.append({"name": name, "url": url})
        if not parsed_artist_images:
            parsed_artist_images = None

    parsed_artist_names: tuple[str, ...] | None = None
    if artist_names and str(artist_names).strip():
        try:
            raw_names = json.loads(artist_names)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail="artist_names must be a JSON array"
            ) from exc
        if not isinstance(raw_names, list):
            raise HTTPException(
                status_code=400, detail="artist_names must be a JSON array"
            )
        cleaned_names = [str(item).strip() for item in raw_names if str(item).strip()]
        if cleaned_names:
            parsed_artist_names = tuple(cleaned_names)

    clean_artist_image_url = (artist_image_url or "").strip() or None
    if (
        not clean_artist_image_url
        and parsed_artist_images
    ):
        clean_artist_image_url = parsed_artist_images[0]["url"]

    payload = ApplyPayload(
        title=clean_title,
        artist=clean_artist,
        album=clean_album,
        mbid=clean_mbid,
        album_mbid=clean_album_mbid,
        album_artist=clean_album_artist,
        filename=clean_filename,
        year=parsed_year,
        duration=parsed_duration,
        fetch_cover=False,
        cover_url=None,
        clear_cover=clear_cover,
        artist_image_url=clean_artist_image_url,
        artist_images=tuple(parsed_artist_images) if parsed_artist_images else None,
        force_artist_images=True,
        provider=provider if provider in ("qqmusic", "netease") else "netease",
        artist_names=parsed_artist_names,
    )
    try:
        await apply_match_to_track(db, track, payload, cover_data=cover_data)
    except ApplyError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

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
