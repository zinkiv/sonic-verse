"""Artists API routes."""

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select, func

from sonicverse.api.dependencies import DbSession, Pagination
from sonicverse.core.paths import music_file_path_filter
from sonicverse.library.normalize_artists import heal_library_rows
from sonicverse.matcher.artist_match import apply_artist_image, search_artist_images
from sonicverse.models import Artist, Track
from sonicverse.models.track_artist import track_artists
from sonicverse.providers import get_provider
from sonicverse.schemas import ArtistResponse, ArtistListResponse, ArtistUpdate
from sonicverse.schemas.artist import ArtistImageCandidate, ArtistMatchResponse
from sonicverse.schemas.match import ProviderName

router = APIRouter(prefix="/artists", tags=["artists"])


@router.get("", response_model=ArtistListResponse)
async def list_artists(
    db: DbSession,
    pagination: Pagination,
    search: str | None = Query(None, description="Search in name"),
) -> ArtistListResponse:
    """List artists credited on tracks in the /music library."""
    await heal_library_rows(db)

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
    # Remaining same-name rows stay stable; duplicates are merged first.
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


@router.post("/{artist_id}/match", response_model=ArtistMatchResponse)
async def match_artist(
    db: DbSession,
    artist_id: str,
    provider: ProviderName = Query("qqmusic", description="Metadata provider"),
) -> ArtistMatchResponse:
    """Search provider avatars for the artist. Does not write the avatar."""
    try:
        get_provider(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    try:
        candidates = await search_artist_images(artist.name, provider)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Artist metadata match failed: {exc}",
        ) from exc

    return ArtistMatchResponse(
        artist_id=artist.id,
        artist_name=artist.name,
        candidates=[
            ArtistImageCandidate.model_validate(item, from_attributes=True)
            for item in candidates
        ],
    )


@router.post("/{artist_id}/avatar", response_model=ArtistResponse)
async def set_artist_avatar(
    db: DbSession,
    artist_id: str,
    image_url: str | None = Form(None),
    image: UploadFile | None = File(None),
) -> ArtistResponse:
    """Apply a chosen provider image URL or an uploaded custom avatar."""
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    payload: bytes | None = None
    if image is not None:
        payload = await image.read()
        if not payload:
            raise HTTPException(status_code=400, detail="Uploaded image is empty")

    url = (image_url or "").strip() or None
    if payload is None and not url:
        raise HTTPException(status_code=400, detail="Provide image_url or an image file")

    previous = artist.avatar_path
    await apply_artist_image(db, artist, image_url=url, image_bytes=payload)
    if artist.avatar_path == previous:
        raise HTTPException(status_code=502, detail="Could not save artist image")

    await db.commit()
    await db.refresh(artist)
    return ArtistResponse.model_validate(artist)
