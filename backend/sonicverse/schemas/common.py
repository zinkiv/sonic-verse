"""Common schemas."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters."""

    page: int = 1
    page_size: int = 50


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class TimestampMixin(BaseModel):
    """Mixin for timestamp fields."""

    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    updated_at: datetime | None = None


class ArtistSummary(BaseModel):
    """Artist summary for embedding."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    sort_name: str | None = None
    avatar_path: str | None = None


class AlbumSummary(BaseModel):
    """Album summary for embedding."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    artist_id: str | None = None
    year: int | None = None
    cover_path: str | None = None


class TrackSummary(BaseModel):
    """Track summary for embedding."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    track_number: int = 1
    disc_number: int = 1
    duration_ms: int | None = None
    file_path: str
