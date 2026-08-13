"""ProviderResult model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Float, DateTime, ForeignKey, Boolean, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sonicverse.core.database import Base


class ProviderResult(Base):
    """Provider match result entity."""

    __tablename__ = "provider_results"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider_mbid: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    # Lazy: eager-loading the track would drag in its album and artist too.
    track: Mapped["Track"] = relationship(  # noqa: F821
        "Track",
        back_populates="provider_results",
    )

    def __repr__(self) -> str:
        return f"<ProviderResult(id={self.id}, provider={self.provider})>"
