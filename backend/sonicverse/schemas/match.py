"""Match schemas."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from sonicverse.matcher.percent import as_match_percent

ProviderName = Literal["qqmusic", "netease"]


class MatchRequest(BaseModel):
    """Request body for searching match candidates."""

    provider: ProviderName = "netease"
    stage_to_transfer: bool = False


class MatchCandidate(BaseModel):
    """A single provider candidate for a local track."""

    title: str
    artist: str
    album: str
    duration: int = 0
    mbid: str
    album_mbid: str | None = None
    year: int | None = None
    confidence: int = 0
    score: int = 0
    cover_url: str | None = None
    artist_image_url: str | None = None
    artist_images: list[dict[str, str]] | None = None
    provider: ProviderName | None = None

    @field_validator("confidence", "score", mode="before")
    @classmethod
    def normalize_percent(cls, value: object) -> int:
        return as_match_percent(value)  # type: ignore[arg-type]


class MatchCandidatesResponse(BaseModel):
    """Candidates returned by a match search."""

    track_id: str
    provider: ProviderName
    candidates: list[MatchCandidate]


class MatchApplyRequest(BaseModel):
    """Apply a chosen candidate to a local track."""

    title: str
    artist: str
    album: str
    mbid: str
    album_mbid: str | None = None
    year: int | None = None
    duration: int | None = Field(
        default=None,
        description="Candidate duration in seconds",
    )
    fetch_cover: bool = True
    cover_url: str | None = None
    artist_image_url: str | None = None
    artist_images: list[dict[str, str]] | None = None
    provider: ProviderName = "netease"
