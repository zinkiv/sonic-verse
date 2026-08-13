"""MatchJob model for batch metadata matching."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from sonicverse.core.database import Base


class MatchJobStatus(str, Enum):
    """Batch match job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MatchJob(Base):
    """Background job that matches (and optionally auto-applies) many tracks."""

    __tablename__ = "match_jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=MatchJobStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="netease")
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    auto_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # pending | transfer | all — used when track_ids_json is null.
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # When true, overwrite existing album covers / artist avatars on apply.
    force_refresh_images: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON array of track ids; null means resolve by scope.
    track_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracks_total: Mapped[int] = mapped_column(Integer, default=0)
    tracks_processed: Mapped[int] = mapped_column(Integer, default=0)
    auto_applied: Mapped[int] = mapped_column(Integer, default=0)
    needs_review: Mapped[int] = mapped_column(Integer, default=0)
    unmatched: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<MatchJob(id={self.id}, status={self.status})>"
