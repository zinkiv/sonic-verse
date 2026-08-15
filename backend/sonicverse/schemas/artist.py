"""Artist schemas."""

from pydantic import BaseModel, ConfigDict

from sonicverse.schemas.common import TimestampMixin, PaginatedResponse, PaginationParams


class ArtistBase(BaseModel):
    """Base artist schema."""

    name: str
    sort_name: str | None = None
    mbid: str | None = None
    avatar_path: str | None = None


class ArtistCreate(ArtistBase):
    """Schema for creating an artist."""

    pass


class ArtistUpdate(BaseModel):
    """Schema for updating an artist."""

    name: str | None = None
    sort_name: str | None = None
    mbid: str | None = None
    avatar_path: str | None = None


class ArtistResponse(ArtistBase, TimestampMixin):
    """Schema for artist response."""

    model_config = ConfigDict(from_attributes=True)

    id: str


class ArtistListResponse(PaginatedResponse[ArtistResponse]):
    """Schema for artist list response."""

    pass


class ArtistImageCandidate(BaseModel):
    """A provider avatar the user can pick in the match dialog."""

    name: str
    url: str
    provider: str


class ArtistMatchResponse(BaseModel):
    """Search-only artist match payload (does not write the avatar)."""

    artist_id: str
    artist_name: str
    candidates: list[ArtistImageCandidate]
