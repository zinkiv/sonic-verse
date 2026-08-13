"""Base provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TrackResult:
    """Track search result."""

    title: str
    artist: str
    album: str
    duration: int  # seconds
    mbid: str
    # Provider title hint; TrackMatcher normalizes to 0–100 percent.
    confidence: float = 0.0
    album_mbid: str | None = None
    year: int | None = None
    # Direct cover URL when the provider already knows it (QQ / NetEase).
    cover_url: str | None = None
    # Primary artist avatar URL (first credited singer).
    artist_image_url: str | None = None
    # Optional per-singer avatars: [{"name": "...", "url": "..."}, ...]
    artist_images: list[dict[str, str]] | None = None
    # Local re-rank score as integer percent (0–100).
    score: int = 0
    provider: str = ""


@dataclass
class AlbumResult:
    """Album search result."""

    title: str
    artist: str
    year: Optional[int]
    mbid: str
    cover_url: Optional[str]


class BaseProvider(ABC):
    """Base metadata provider interface."""

    name: str

    @abstractmethod
    async def search_track(
        self,
        title: str,
        artist: str,
        duration: Optional[int] = None,
    ) -> List[TrackResult]:
        """Search for a track."""
        ...

    @abstractmethod
    async def search_album(
        self,
        album: str,
        artist: str,
    ) -> List[AlbumResult]:
        """Search for an album."""
        ...

    @abstractmethod
    async def get_cover(self, mbid: str) -> Optional[bytes]:
        """Get album cover by provider-specific album/release id."""
        ...
