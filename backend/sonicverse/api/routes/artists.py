"""Artists API routes."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func

from sonicverse.api.dependencies import DbSession, Pagination
from sonicverse.core.paths import music_file_path_filter
from sonicverse.library.normalize_artists import normalize_combined_artists
from sonicverse.matcher.artist_match import match_artist_metadata
from sonicverse.models import Artist, Track
from sonicverse.models.track_artist import track_artists
from sonicverse.providers import get_provider
from sonicverse.schemas import ArtistResponse, ArtistListResponse, ArtistUpdate
from sonicverse.schemas.match import ProviderName

router = APIRouter(prefix="/artists", tags=["artists"])


@router.get("", response_model=ArtistListResponse)
async def list_artists(
    db: DbSession,
    pagination: Pagination,
    search: str | None = Query(None, description="Search in name"),
) -> ArtistListResponse:
    """List artists credited on tracks in the /music library."""
    # Self-heal legacy rows that still store combined credits as one name.
    await normalize_combined_artists(db)

    library_track_ids = select(Track.id).where(music_file_path_filter())
    primary = (
        select(Track.artist_id.label("artist_id"))
        .where(Track.artist_id.is_not(None), music_file_path_filter())
    )
    credited = select(track_artists.c.artist_id.label("artist_id")).where(
        track_artists.c.track_id.in_(library_track_ids)
    )
    # UNION removes duplicate ids so count/list stay aligned under concurrent credits.
    library_artist_ids = primary.union(credited).subquery()
    in_library = Artist.id.in_(select(library_artist_ids.c.artist_id))

    query = select(Artist).where(in_library)
    count_query = select(func.count()).select_from(library_artist_ids)

    if search:
        matched = select(Artist.id).where(
            in_library, Artist.name.ilike(f"%{search}%")
        )
        query = select(Artist).where(Artist.id.in_(matched))
        count_query = select(func.count()).select_from(
            matched.subquery()
        )

    total = int(await db.scalar(count_query) or 0)

    offset = (pagination.page - 1) * pagination.page_size
    # id breaks ties so identically-named rows keep a stable order across pages.
    query = (
        query.order_by(Artist.name, Artist.id)
        .offset(offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(query)
    artists = list(result.scalars().all())

    total_pages = (
        (total + pagination.page_size - 1) // pagination.page_size if total else 0
    )

    return ArtistListResponse(
        items=[ArtistResponse.model_validate(a) for a in artists],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=total_pages,
    )


@router.get("/{artist_id}", response_model=ArtistResponse)
async def get_artist(db: DbSession, artist_id: str) -> ArtistResponse:
    """Get an artist by ID."""
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()

    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    return ArtistResponse.model_validate(artist)


@router.put("/{artist_id}", response_model=ArtistResponse)
async def update_artist(
    db: DbSession,
    artist_id: str,
    data: ArtistUpdate,
) -> ArtistResponse:
    """Update an artist."""
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()

    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(artist, key, value)

    await db.commit()
    await db.refresh(artist)

    return ArtistResponse.model_validate(artist)


@router.post("/{artist_id}/match", response_model=ArtistResponse)
async def match_artist(
    db: DbSession,
    artist_id: str,
    provider: ProviderName = Query("qqmusic", description="Metadata provider"),
) -> ArtistResponse:
    """Search provider metadata and refresh the artist avatar."""
    try:
        get_provider(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    try:
        await match_artist_metadata(db, artist, provider, force=True)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Artist metadata match failed: {exc}",
        ) from exc

    await db.commit()
    await db.refresh(artist)

    if not artist.avatar_path:
        raise HTTPException(
            status_code=404,
            detail="No matching artist image found",
        )

    return ArtistResponse.model_validate(artist)
