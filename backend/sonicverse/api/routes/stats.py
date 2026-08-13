"""Stats API routes."""

from fastapi import APIRouter
from sqlalchemy import select, func

from sonicverse.api.dependencies import DbSession
from sonicverse.core.paths import music_file_path_filter, transfer_file_path_filter
from sonicverse.library.file_tags import refresh_missing_file_tags
from sonicverse.models import Track, Album, Artist

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=dict)
async def get_stats(db: DbSession) -> dict:
    """Get library statistics."""
    # Transfer issue counts are based on embedded file tags.
    await refresh_missing_file_tags(db)

    library_album_ids = (
        select(Track.album_id)
        .where(Track.album_id.is_not(None), music_file_path_filter())
        .distinct()
    )
    library_artist_ids = (
        select(Track.artist_id)
        .where(Track.artist_id.is_not(None), music_file_path_filter())
        .distinct()
    )
    result = await db.execute(
        select(
            select(func.count(Track.id))
            .where(music_file_path_filter())
            .scalar_subquery()
            .label("total_tracks"),
            select(func.count(Album.id))
            .where(Album.id.in_(library_album_ids))
            .scalar_subquery()
            .label("total_albums"),
            select(func.count(Artist.id))
            .where(Artist.id.in_(library_artist_ids))
            .scalar_subquery()
            .label("total_artists"),
            select(func.count(Track.id))
            .where(Track.tag_has_cover.is_(False), transfer_file_path_filter())
            .scalar_subquery()
            .label("missing_covers"),
            select(func.count(Track.id))
            .where(Track.tag_artist.is_(None), transfer_file_path_filter())
            .scalar_subquery()
            .label("unknown_artists"),
            select(func.count(Track.id))
            .where(Track.tag_album.is_(None), transfer_file_path_filter())
            .scalar_subquery()
            .label("missing_albums"),
            select(func.count(Track.id))
            .where(Track.mbid.is_(None), music_file_path_filter())
            .scalar_subquery()
            .label("pending_review"),
            select(func.count(Track.id))
            .where(transfer_file_path_filter())
            .scalar_subquery()
            .label("transfer_pending"),
        )
    )
    row = result.one()

    return {
        "total_tracks": row.total_tracks or 0,
        "total_albums": row.total_albums or 0,
        "total_artists": row.total_artists or 0,
        "missing_covers": row.missing_covers or 0,
        "unknown_artists": row.unknown_artists or 0,
        "missing_albums": row.missing_albums or 0,
        "pending_review": row.pending_review or 0,
        "transfer_pending": row.transfer_pending or 0,
    }
