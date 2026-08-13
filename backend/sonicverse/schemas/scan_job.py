"""ScanJob schemas."""

from pydantic import BaseModel, ConfigDict

from sonicverse.schemas.common import TimestampMixin


class ScanJobCreate(BaseModel):
    """Schema for creating a scan job."""

    root_path: str


class ScanJobResponse(TimestampMixin):
    """Schema for scan job response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    root_path: str
    tracks_found: int
    tracks_processed: int
    error_msg: str | None = None


class ScanJobStatusResponse(BaseModel):
    """Schema for scan job status update."""

    status: str
    tracks_found: int | None = None
    tracks_processed: int | None = None
    error_msg: str | None = None


class MusicSyncResponse(BaseModel):
    """Result of a conditional music-library sync check."""

    changed: bool
    file_count: int
    fingerprint: str
    job: ScanJobResponse | None = None
