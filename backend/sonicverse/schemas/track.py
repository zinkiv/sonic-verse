"""Track schemas."""

from pydantic import BaseModel, ConfigDict

from sonicverse.schemas.common import TimestampMixin, PaginatedResponse, ArtistSummary, AlbumSummary


class TrackBase(BaseModel):
    """Base track schema."""

    title: str
    track_number: int = 1
    disc_number: int = 1
    duration_ms: int | None = None
    mbid: str | None = None
    file_path: str
    file_hash: str | None = None


class TrackCreate(TrackBase):
    """Schema for creating a track."""

    album_id: str | None = None
    artist_id: str | None = None


class TrackUpdate(BaseModel):
    """Schema for updating a track."""

    title: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    duration_ms: int | None = None
    mbid: str | None = None
    album_id: str | None = None
    artist_id: str | None = None


class FileTagsSummary(BaseModel):
    """Tags embedded in the audio file (transfer-queue source of truth)."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    has_cover: bool = False


class TrackResponse(TrackBase, TimestampMixin):
    """Schema for track response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    album_id: str | None = None
    artist_id: str | None = None


class TrackDetailResponse(TrackResponse):
    """Schema for track detail with artist and album."""

    model_config = ConfigDict(from_attributes=True)

    artist: ArtistSummary | None = None
    artists: list[ArtistSummary] = []
    album: AlbumSummary | None = None
    file_tags: FileTagsSummary | None = None

    @classmethod
    def from_track(cls, track) -> "TrackDetailResponse":
        data = cls.model_validate(track)
        return data.model_copy(
            update={
                "file_tags": FileTagsSummary(
                    title=getattr(track, "tag_title", None),
                    artist=getattr(track, "tag_artist", None),
                    album=getattr(track, "tag_album", None),
                    has_cover=bool(getattr(track, "tag_has_cover", False)),
                )
            }
        )


class TrackListResponse(PaginatedResponse[TrackDetailResponse]):
    """Schema for track list response (includes artist/album summaries)."""

    pass
