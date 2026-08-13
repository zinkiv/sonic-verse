"""Audio file upload API."""

import asyncio
import re
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import select

from sonicverse.api.dependencies import DbSession
from sonicverse.core.config import get_settings
from sonicverse.models import Track
from sonicverse.scanner.pipeline import ingest_audio_file
from sonicverse.schemas import TrackDetailResponse

router = APIRouter(prefix="/upload", tags=["upload"])

settings = get_settings()

_UNSAFE_NAME = re.compile(r"[^\w\s.\-()\u4e00-\u9fff]", re.UNICODE)


def _upload_root() -> Path:
    """Uploads land in the transfer inbox for metadata processing."""
    root = Path(settings.transfer_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sanitize_filename(name: str) -> str:
    base = Path(name).name.strip()
    if not base or base.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    cleaned = _UNSAFE_NAME.sub("_", base)
    if not cleaned or cleaned.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return cleaned


def _unique_destination(root: Path, filename: str) -> Path:
    ext = Path(filename).suffix.lower()
    if ext not in settings.audio_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {ext or '(none)'}",
        )

    candidate = (root / filename).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=400, detail="Invalid upload path")

    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    counter = 1
    while True:
        alt_name = f"{stem} ({counter}){ext}"
        alt_path = (root / alt_name).resolve()
        if not alt_path.exists():
            return alt_path
        counter += 1


@router.post("", response_model=list[TrackDetailResponse])
async def upload_tracks(
    db: DbSession,
    files: list[UploadFile] = File(...),
) -> list[TrackDetailResponse]:
    """Upload audio files into the transfer inbox and import them."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    root = _upload_root()
    imported: list[Track] = []

    for upload in files:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="Missing filename")

        safe_name = _sanitize_filename(upload.filename)
        destination = _unique_destination(root, safe_name)

        try:
            content = await upload.read()
            if not content:
                raise HTTPException(status_code=400, detail=f"Empty file: {safe_name}")
            await asyncio.to_thread(destination.write_bytes, content)
            track = await ingest_audio_file(db, destination)
            imported.append(track)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload {safe_name}: {exc}",
            ) from exc

    await db.commit()

    responses: list[TrackDetailResponse] = []
    for track in imported:
        result = await db.execute(select(Track).where(Track.id == track.id))
        fresh = result.scalar_one()
        _ = fresh.artist
        _ = fresh.album
        responses.append(TrackDetailResponse.from_track(fresh))

    return responses
