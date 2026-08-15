"""Tracks API routes."""

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, func, or_

from sonicverse.api.dependencies import DbSession, Pagination
from sonicverse.core.covers import (
    cover_filesystem_path,
    detect_cover_media_type,
)
from sonicverse.core.paths import music_file_path_filter, transfer_file_path_filter
from sonicverse.library.delete import NotFoundError, delete_track
from sonicverse.library.file_tags import refresh_missing_file_tags
from sonicverse.metadata.parser import MetadataReader
from sonicverse.models import Album, Artist, Track
from sonicverse.models.track_artist import track_artists
from sonicverse.schemas import TrackDetailResponse, TrackListResponse, TrackUpdate

router = APIRouter(prefix="/tracks", tags=["tracks"])

_ISSUE_FILTERS = {
    "pending_review",
    "unknown_artist",
    "missing_cover",
    "missing_album",
    "transfer",
    "all",
}


@router.get("", response_model=TrackListResponse)
async def list_tracks(
    db: DbSession,
    pagination: Pagination,
    album_id: str | None = Query(None, description="Filter by album ID"),
    artist_id: str | None = Query(None, description="Filter by artist ID"),
    search: str | None = Query(None, description="Search in title, album, or artist"),
    issue: str | None = Query(
        None,
        description=(
            "Issue filter: transfer | pending_review | unknown_artist | missing_cover | missing_album | all"
        ),
    ),
) -> TrackListResponse:
    """List all tracks with pagination."""
    if issue is not None and issue not in _ISSUE_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown issue filter: {issue}",
        )

    query = select(Track)
    count_query = select(func.count(Track.id))

    if album_id:
        query = query.where(Track.album_id == album_id)
        count_query = count_query.where(Track.album_id == album_id)
    if artist_id:
        credited = select(track_artists.c.track_id).where(
            track_artists.c.artist_id == artist_id
        )
        artist_filter = or_(Track.artist_id == artist_id, Track.id.in_(credited))
        query = query.where(artist_filter)
        count_query = count_query.where(artist_filter)
    if search:
        like = f"%{search}%"
        matching_artists = select(Artist.id).where(Artist.name.ilike(like))
        matching_albums = select(Album.id).where(Album.title.ilike(like))
        credited = select(track_artists.c.track_id).where(
            track_artists.c.artist_id.in_(matching_artists)
        )
        condition = or_(
            Track.title.ilike(like),
            Track.album_id.in_(matching_albums),
            Track.artist_id.in_(matching_artists),
            Track.id.in_(credited),
        )
        query = query.where(condition)
        count_query = count_query.where(condition)
    if issue == "transfer":
        await refresh_missing_file_tags(db)
        transfer_filter = transfer_file_path_filter()
        query = query.where(transfer_filter)
        count_query = count_query.where(transfer_filter)
    elif issue in {"missing_album", "missing_cover", "unknown_artist"}:
        # Issue chips use embedded file tags, not post-match library fields.
        await refresh_missing_file_tags(db)
        transfer_filter = transfer_file_path_filter()
        query = query.where(transfer_filter)
        count_query = count_query.where(transfer_filter)
        if issue == "unknown_artist":
            query = query.where(Track.tag_artist.is_(None))
            count_query = count_query.where(Track.tag_artist.is_(None))
        elif issue == "missing_cover":
            query = query.where(Track.tag_has_cover.is_(False))
            count_query = count_query.where(Track.tag_has_cover.is_(False))
        else:  # missing_album
            query = query.where(Track.tag_album.is_(None))
            count_query = count_query.where(Track.tag_album.is_(None))
    else:
        # Music library lives under /music; transfer inbox is a separate queue.
        library_filter = music_file_path_filter()
        query = query.where(library_filter)
        count_query = count_query.where(library_filter)
        if issue == "pending_review":
            query = query.where(Track.mbid.is_(None))
            count_query = count_query.where(Track.mbid.is_(None))
        # issue == "all" (or None): every track already in the music library.

    # Get total count
    total = await db.scalar(count_query)

    # Get paginated results
    offset = (pagination.page - 1) * pagination.page_size
    # id breaks ties so equally-titled rows keep a stable order across pages.
    query = (
        query.order_by(Track.title, Track.id)
        .offset(offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(query)
    tracks = list(result.scalars().all())

    total_pages = (total + pagination.page_size - 1) // pagination.page_size if total else 0

    return TrackListResponse(
        items=[TrackDetailResponse.from_track(t) for t in tracks],
        total=total or 0,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=total_pages,
    )


@router.get("/{track_id}/cover")
async def get_track_cover(
    db: DbSession,
    track_id: str,
    source: Literal["file", "album", "auto"] = Query(
        "auto",
        description=(
            "file=embedded art only; album=saved /covers first; "
            "auto=album then file"
        ),
    ),
) -> Response:
    """Serve cover art for a track."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")

    async def _from_file() -> Response | None:
        audio_path = Path(track.file_path) if track.file_path else None
        if audio_path is None or not audio_path.is_file():
            return None
        embedded = await asyncio.to_thread(MetadataReader.read_cover, audio_path)
        if not embedded:
            return None
        return Response(
            content=embedded,
            media_type=detect_cover_media_type(embedded),
            headers={"Cache-Control": "private, max-age=3600"},
        )

    async def _from_album() -> Response | None:
        await db.refresh(track, attribute_names=["album"])
        album = track.album
        if not album or not album.cover_path:
            return None
        path = cover_filesystem_path(album.cover_path)
        if path is not None and path.is_file():
            data = await asyncio.to_thread(path.read_bytes)
            return Response(
                content=data,
                media_type=detect_cover_media_type(data),
                headers={"Cache-Control": "private, max-age=86400"},
            )
        # Stale DB pointer.
        album.cover_path = None
        await db.commit()
        return None

    if source == "file":
        response = await _from_file()
    elif source == "album":
        response = await _from_album()
        if response is None:
            response = await _from_file()
    else:
        response = await _from_album()
        if response is None:
            response = await _from_file()

    if response is None:
        raise HTTPException(status_code=404, detail="Cover not found")
    return response


@router.get("/{track_id}", response_model=TrackDetailResponse)
async def get_track(db: DbSession, track_id: str) -> TrackDetailResponse:
    """Get a track by ID."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    return TrackDetailResponse.from_track(track)


@router.put("/{track_id}", response_model=TrackDetailResponse)
async def update_track(
    db: DbSession,
    track_id: str,
    data: TrackUpdate,
) -> TrackDetailResponse:
    """Update a track."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(track, key, value)

    await db.commit()
    await db.refresh(track)
    # Explicitly reload relationships - refresh() expires them and implicit
    # lazy-loading would fail in async context.
    await db.refresh(track, attribute_names=["artist", "album"])

    return TrackDetailResponse.from_track(track)


@router.delete("/{track_id}")
async def remove_track(db: DbSession, track_id: str) -> dict:
    """Delete a track, its audio file, orphan artists, and refresh album metadata."""
    try:
        return await delete_track(db, track_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
