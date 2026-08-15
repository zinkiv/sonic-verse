"""Albums API routes."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func

from sonicverse.api.dependencies import DbSession, Pagination
from sonicverse.core.paths import music_file_path_filter
from sonicverse.library.delete import NotFoundError, delete_album
from sonicverse.library.normalize_artists import heal_library_rows
from sonicverse.models import Album, Track
from sonicverse.schemas import AlbumResponse, AlbumDetailResponse, AlbumListResponse, AlbumUpdate

router = APIRouter(prefix="/albums", tags=["albums"])


async def _track_counts(db: DbSession, album_ids: list[str]) -> dict[str, int]:
    if not album_ids:
        return {}
    result = await db.execute(
        select(Track.album_id, func.count(Track.id))
        .where(Track.album_id.in_(album_ids), music_file_path_filter())
        .group_by(Track.album_id)
    )
    return {album_id: int(count) for album_id, count in result.all()}


def _album_detail(album: Album, track_count: int) -> AlbumDetailResponse:
    data = AlbumDetailResponse.model_validate(album)
    return data.model_copy(update={"track_count": track_count})


@router.get("", response_model=AlbumListResponse)
async def list_albums(
    db: DbSession,
    pagination: Pagination,
    artist_id: str | None = Query(None, description="Filter by artist ID"),
    search: str | None = Query(None, description="Search in title"),
) -> AlbumListResponse:
    """List albums that have at least one track in the /music library."""
    await heal_library_rows(db)
    library_album_ids = (
        select(Track.album_id.label("album_id"))
        .where(Track.album_id.is_not(None), music_file_path_filter())
        .distinct()
        .subquery()
    )
    in_library = Album.id.in_(select(library_album_ids.c.album_id))
    query = select(Album).where(in_library)
    count_query = select(func.count()).select_from(library_album_ids)

    if artist_id or search:
        filtered = select(Album.id).where(in_library)
        if artist_id:
            filtered = filtered.where(Album.artist_id == artist_id)
        if search:
            filtered = filtered.where(Album.title.ilike(f"%{search}%"))
        query = select(Album).where(Album.id.in_(filtered))
        count_query = select(func.count()).select_from(filtered.subquery())

    total = int(await db.scalar(count_query) or 0)

    offset = (pagination.page - 1) * pagination.page_size
    # id breaks ties so equally-titled rows keep a stable order across pages.
    query = (
        query.order_by(Album.title, Album.id)
        .offset(offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(query)
    albums = list(result.scalars().all())
    counts = await _track_counts(db, [album.id for album in albums])

    total_pages = (
        (total + pagination.page_size - 1) // pagination.page_size if total else 0
    )

    return AlbumListResponse(
        items=[_album_detail(a, counts.get(a.id, 0)) for a in albums],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=total_pages,
    )


@router.get("/{album_id}", response_model=AlbumDetailResponse)
async def get_album(db: DbSession, album_id: str) -> AlbumDetailResponse:
    """Get an album by ID."""
    result = await db.execute(select(Album).where(Album.id == album_id))
    album = result.scalar_one_or_none()

    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    counts = await _track_counts(db, [album.id])
    return _album_detail(album, counts.get(album.id, 0))


@router.put("/{album_id}", response_model=AlbumResponse)
async def update_album(
    db: DbSession,
    album_id: str,
    data: AlbumUpdate,
) -> AlbumResponse:
    """Update an album."""
    result = await db.execute(select(Album).where(Album.id == album_id))
    album = result.scalar_one_or_none()

    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(album, key, value)

    await db.commit()
    await db.refresh(album)

    return AlbumResponse.model_validate(album)


@router.delete("/{album_id}")
async def remove_album(db: DbSession, album_id: str) -> dict:
    """Delete an album, its tracks, audio files, and orphaned artists."""
    try:
        return await delete_album(db, album_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
