"""Models package."""

from sonicverse.models.artist import Artist
from sonicverse.models.album import Album
from sonicverse.models.track import Track
from sonicverse.models.track_artist import track_artists
from sonicverse.models.genre import Genre
from sonicverse.models.scan_job import ScanJob, ScanJobStatus
from sonicverse.models.match_job import MatchJob, MatchJobStatus
from sonicverse.models.provider_result import ProviderResult

__all__ = [
    "Artist",
    "Album",
    "Track",
    "track_artists",
    "Genre",
    "ScanJob",
    "ScanJobStatus",
    "MatchJob",
    "MatchJobStatus",
    "ProviderResult",
]
