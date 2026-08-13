"""Track model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sonicverse.core.database import Base
from sonicverse.models.track_artist import track_artists


class Track(Base):
    """Track entity."""

    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    album_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("albums.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    artist_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    track_number: Mapped[int] = mapped_column(Integer, default=1)
    disc_number: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # External provider ids (MusicBrainz UUID / qq:song:… / ne:song:…).
    mbid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Snapshot of tags embedded in the audio file (transfer-queue source of truth).
    # Not overwritten by provider apply — only refreshed when the file is re-scanned.
    tag_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tag_artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tag_album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tag_has_cover: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
    album: Mapped["Album | None"] = relationship(  # noqa: F821
        "Album",
        back_populates="tracks",
        lazy="selectin",
    )
    artist: Mapped["Artist | None"] = relationship(  # noqa: F821
        "Artist",
        back_populates="tracks",
        lazy="selectin",
        foreign_keys=[artist_id],
    )
    # Credits when a tag lists multiple artists (comma / &).
    artists: Mapped[list["Artist"]] = relationship(  # noqa: F821
        "Artist",
        secondary=track_artists,
        lazy="selectin",
    )
    provider_results: Mapped[list["ProviderResult"]] = relationship(  # noqa: F821
        "ProviderResult",
        back_populates="track",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Track(id={self.id}, title={self.title})>"
