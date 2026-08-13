"""Artist model."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sonicverse.core.database import Base


class Artist(Base):
    """Artist entity."""

    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sort_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mbid: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True, index=True)
    avatar_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
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

    # Relationships (lazy: avoid pulling an artist's entire discography on every query)
    albums: Mapped[list["Album"]] = relationship(  # noqa: F821
        "Album",
        back_populates="artist",
    )
    tracks: Mapped[list["Track"]] = relationship(  # noqa: F821
        "Track",
        back_populates="artist",
    )

    def __repr__(self) -> str:
        return f"<Artist(id={self.id}, name={self.name})>"
