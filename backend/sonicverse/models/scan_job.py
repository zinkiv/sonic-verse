"""ScanJob model."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import String, Integer, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from sonicverse.core.database import Base


class ScanJobStatus(str, Enum):
    """Scan job status enum."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanJob(Base):
    """Scan job entity."""

    __tablename__ = "scan_jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=ScanJobStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    tracks_found: Mapped[int] = mapped_column(Integer, default=0)
    tracks_processed: Mapped[int] = mapped_column(Integer, default=0)
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
        return f"<ScanJob(id={self.id}, status={self.status})>"
