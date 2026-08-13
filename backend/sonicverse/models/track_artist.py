"""Association table for tracks credited to multiple artists."""

from sqlalchemy import Column, ForeignKey, String, Table

from sonicverse.core.database import Base

track_artists = Table(
    "track_artists",
    Base.metadata,
    Column(
        "track_id",
        String(36),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "artist_id",
        String(36),
        ForeignKey("artists.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
