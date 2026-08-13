"""Settings API schemas."""

from pydantic import BaseModel, Field, field_validator

from sonicverse.matcher.percent import (
    MATCH_THRESHOLD_MAX,
    MATCH_THRESHOLD_MIN,
    clamp_match_threshold,
)


class SettingsUpdate(BaseModel):
    """Partial update for UI-editable settings."""

    match_confidence_threshold: int = Field(
        ge=MATCH_THRESHOLD_MIN,
        le=MATCH_THRESHOLD_MAX,
        description="Auto-apply when top match score >= this percent (50–100)",
    )

    @field_validator("match_confidence_threshold", mode="before")
    @classmethod
    def normalize_threshold(cls, value: object) -> int:
        return clamp_match_threshold(value)  # type: ignore[arg-type]
