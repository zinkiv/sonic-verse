"""Batch match job schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sonicverse.matcher.percent import clamp_match_threshold
from sonicverse.schemas.common import TimestampMixin
from sonicverse.schemas.match import ProviderName

MatchScope = Literal["pending", "transfer", "all"]


class BatchMatchRequest(BaseModel):
    """Start a batch match job."""

    provider: ProviderName = "netease"
    track_ids: list[str] | None = Field(
        default=None,
        description="Track ids to process; omit to resolve by scope",
    )
    scope: MatchScope = Field(
        default="pending",
        description=(
            "When track_ids omitted: pending=mbid IS NULL; "
            "transfer=under transfer_path; all=entire library"
        ),
    )
    threshold: int | None = Field(
        default=None,
        ge=50,
        le=100,
        description="Auto-apply when top score >= this percent; defaults to settings",
    )
    auto_apply: bool = True
    force_refresh_images: bool = Field(
        default=False,
        description="Overwrite existing album covers and artist avatars when applying",
    )

    @field_validator("threshold", mode="before")
    @classmethod
    def normalize_threshold(cls, value: object) -> int | None:
        if value is None:
            return None
        return clamp_match_threshold(value)  # type: ignore[arg-type]


class MatchJobResponse(TimestampMixin):
    """Batch match job status."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    provider: str
    threshold: int
    auto_apply: bool
    scope: str = "pending"
    force_refresh_images: bool = False
    tracks_total: int
    tracks_processed: int
    auto_applied: int
    needs_review: int
    unmatched: int
    failed: int
    error_msg: str | None = None

    @field_validator("threshold", mode="before")
    @classmethod
    def normalize_threshold(cls, value: object) -> int:
        return clamp_match_threshold(value)  # type: ignore[arg-type]
