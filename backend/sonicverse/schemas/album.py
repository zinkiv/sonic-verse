"""Album schemas."""

from pydantic import BaseModel, ConfigDict

from sonicverse.schemas.common import TimestampMixin, PaginatedResponse, ArtistSummary


class AlbumBase(BaseModel):
    """Base album schema."""

    title: str
    year: int | None = None
    mbid: str | None = None
    cover_path: str | None = None


class AlbumCreate(AlbumBase):
    """Schema for creating an album."""

    artist_id: str | None = None


class AlbumUpdate(BaseModel):
    """Schema for updating an album."""

    title: str | None = None
    year: int | None = None
    mbid: str | None = None
    cover_path: str | None = None


class AlbumResponse(AlbumBase, TimestampMixin):
    """Schema for album response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    artist_id: str | None = None


class AlbumDetailResponse(AlbumResponse):
    """Schema for album detail with artist."""

    model_config = ConfigDict(from_attributes=True)

    artist: ArtistSummary | None = None
    track_count: int = 0


class AlbumListResponse(PaginatedResponse[AlbumDetailResponse]):
    """Schema for album list response (includes artist summary)."""

    pass
