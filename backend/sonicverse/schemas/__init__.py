"""Schemas package."""

from sonicverse.schemas.common import (
    PaginationParams,
    PaginatedResponse,
    TimestampMixin,
    ArtistSummary,
    AlbumSummary,
    TrackSummary,
)
from sonicverse.schemas.artist import (
    ArtistBase,
    ArtistCreate,
    ArtistUpdate,
    ArtistResponse,
    ArtistListResponse,
)
from sonicverse.schemas.album import (
    AlbumBase,
    AlbumCreate,
    AlbumUpdate,
    AlbumResponse,
    AlbumDetailResponse,
    AlbumListResponse,
)
from sonicverse.schemas.track import (
    TrackBase,
    TrackCreate,
    TrackUpdate,
    TrackResponse,
    TrackDetailResponse,
    TrackListResponse,
)
from sonicverse.schemas.scan_job import (
    ScanJobCreate,
    ScanJobResponse,
    ScanJobStatusResponse,
    MusicSyncResponse,
)
from sonicverse.schemas.match_job import (
    BatchMatchRequest,
    MatchJobResponse,
)
from sonicverse.schemas.settings import SettingsUpdate

__all__ = [
    "PaginationParams",
    "PaginatedResponse",
    "TimestampMixin",
    "ArtistSummary",
    "AlbumSummary",
    "TrackSummary",
    "ArtistBase",
    "ArtistCreate",
    "ArtistUpdate",
    "ArtistResponse",
    "ArtistListResponse",
    "AlbumBase",
    "AlbumCreate",
    "AlbumUpdate",
    "AlbumResponse",
    "AlbumDetailResponse",
    "AlbumListResponse",
    "TrackBase",
    "TrackCreate",
    "TrackUpdate",
    "TrackResponse",
    "TrackDetailResponse",
    "TrackListResponse",
    "ScanJobCreate",
    "ScanJobResponse",
    "ScanJobStatusResponse",
    "MusicSyncResponse",
    "BatchMatchRequest",
    "MatchJobResponse",
    "SettingsUpdate",
]
