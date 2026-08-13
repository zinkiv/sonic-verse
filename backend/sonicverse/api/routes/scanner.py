"""Scanner API routes."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from sonicverse.api.dependencies import DbSession
from sonicverse.core.config import get_settings
from sonicverse.core.paths import allowed_scan_roots, music_root, transfer_root
from sonicverse.models import ScanJob, ScanJobStatus
from sonicverse.scanner.fingerprint import music_library_changed, transfer_library_changed
from sonicverse.scanner.pipeline import request_cancel, start_scan_job
from sonicverse.schemas import MusicSyncResponse, ScanJobCreate, ScanJobResponse

router = APIRouter(prefix="/scanner", tags=["scanner"])

settings = get_settings()


def _resolve_scan_root(raw_path: str) -> Path:
    """Resolve a scan root inside music_path or transfer_path only."""
    try:
        candidate = Path(raw_path).resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid root_path")

    allowed = allowed_scan_roots()
    for root in allowed:
        if candidate == root or root in candidate.parents:
            if not candidate.is_dir():
                raise HTTPException(status_code=400, detail="root_path is not a directory")
            return candidate

    roots = ", ".join(str(r) for r in allowed)
    raise HTTPException(
        status_code=400,
        detail=f"root_path must be inside music or transfer library ({roots})",
    )


@router.post("/scan", response_model=ScanJobResponse, status_code=201)
async def create_scan_job(
    db: DbSession,
    data: ScanJobCreate,
) -> ScanJobResponse:
    """Create a new scan job and start it in the background."""
    root = _resolve_scan_root(data.root_path)

    job = ScanJob(
        root_path=str(root),
        status=ScanJobStatus.PENDING.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    start_scan_job(job.id)

    return ScanJobResponse.model_validate(job)


@router.post("/sync-music", response_model=MusicSyncResponse)
async def sync_music_library(db: DbSession) -> MusicSyncResponse:
    """Scan /music only when the on-disk fingerprint changed since last sync."""
    root = music_root()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="music_path is not a directory")

    changed, snapshot = await asyncio.to_thread(music_library_changed, root)
    if not changed:
        return MusicSyncResponse(
            changed=False,
            file_count=snapshot.file_count,
            fingerprint=snapshot.fingerprint,
            job=None,
        )

    job = ScanJob(
        root_path=str(root),
        status=ScanJobStatus.PENDING.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    start_scan_job(job.id)

    return MusicSyncResponse(
        changed=True,
        file_count=snapshot.file_count,
        fingerprint=snapshot.fingerprint,
        job=ScanJobResponse.model_validate(job),
    )


@router.post("/sync-transfer", response_model=MusicSyncResponse)
async def sync_transfer_library(db: DbSession) -> MusicSyncResponse:
    """Scan /data/transfer only when the on-disk fingerprint changed."""
    root = transfer_root()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="transfer_path is not a directory")

    changed, snapshot = await asyncio.to_thread(transfer_library_changed, root)
    if not changed:
        return MusicSyncResponse(
            changed=False,
            file_count=snapshot.file_count,
            fingerprint=snapshot.fingerprint,
            job=None,
        )

    job = ScanJob(
        root_path=str(root),
        status=ScanJobStatus.PENDING.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    start_scan_job(job.id)

    return MusicSyncResponse(
        changed=True,
        file_count=snapshot.file_count,
        fingerprint=snapshot.fingerprint,
        job=ScanJobResponse.model_validate(job),
    )


@router.get("/jobs", response_model=list[ScanJobResponse])
async def list_scan_jobs(db: DbSession) -> list[ScanJobResponse]:
    """List all scan jobs."""
    result = await db.execute(
        select(ScanJob).order_by(ScanJob.created_at.desc()).limit(50)
    )
    jobs = list(result.scalars().all())

    return [ScanJobResponse.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=ScanJobResponse)
async def get_scan_job(db: DbSession, job_id: str) -> ScanJobResponse:
    """Get a scan job by ID."""
    result = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")

    return ScanJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=ScanJobResponse)
async def cancel_scan_job(db: DbSession, job_id: str) -> ScanJobResponse:
    """Request cancellation of a pending or running scan job."""
    result = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")

    if job.status not in (ScanJobStatus.PENDING.value, ScanJobStatus.RUNNING.value):
        raise HTTPException(status_code=409, detail="Job is not cancellable")

    request_cancel(job.id)

    if job.status == ScanJobStatus.PENDING.value:
        # Not started yet (queued behind the scan lock) - mark immediately.
        job.status = ScanJobStatus.CANCELLED.value
        await db.commit()
        await db.refresh(job)

    return ScanJobResponse.model_validate(job)


@router.get("/stats", response_model=dict)
async def get_scan_stats(db: DbSession) -> dict:
    """Get scanning statistics."""
    total_jobs = await db.scalar(select(func.count(ScanJob.id)))
    pending_jobs = await db.scalar(
        select(func.count(ScanJob.id)).where(ScanJob.status == ScanJobStatus.PENDING.value)
    )
    running_jobs = await db.scalar(
        select(func.count(ScanJob.id)).where(ScanJob.status == ScanJobStatus.RUNNING.value)
    )

    return {
        "total_jobs": total_jobs or 0,
        "pending_jobs": pending_jobs or 0,
        "running_jobs": running_jobs or 0,
    }
