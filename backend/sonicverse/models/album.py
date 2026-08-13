"""Album model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sonicverse.core.database import Base


class Album(Base):
    """Album entity."""

    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    artist_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mbid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    cover_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
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

    # Relationships
    artist: Mapped["Artist | None"] = relationship(  # noqa: F821
        "Artist",
        back_populates="albums",
        lazy="selectin",
    )
    # Lazy: no response schema embeds the tracklist, and eager-loading it here
    # would pull every track of every album returned by /tracks and /albums.
    tracks: Mapped[list["Track"]] = relationship(  # noqa: F821
        "Track",
        back_populates="album",
    )

    def __repr__(self) -> str:
        return f"<Album(id={self.id}, title={self.title})>"
