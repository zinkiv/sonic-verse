"""MusicBrainz provider."""

import asyncio
import logging
import time
from typing import Optional

import musicbrainzngs
import httpx

from sonicverse.core.config import get_settings
from sonicverse.providers.base import BaseProvider, TrackResult, AlbumResult

logger = logging.getLogger(__name__)

settings = get_settings()

# MusicBrainz allows at most 1 request/second.
_RATE_LIMIT_INTERVAL = 1.0

# Lucene special characters that break unquoted tokens.
_LUCENE_SPECIAL = set(r'+-&|!(){}[]^"~*?:\\')


class _RateLimiter:
    """Ensures a minimum interval between API calls across all callers."""

    def __init__(self, interval: float):
        self._interval = interval
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()


# MusicBrainz throttles per IP, so the interval has to be shared by every
# provider instance in the process - not stored per instance.
_rate_limiter = _RateLimiter(_RATE_LIMIT_INTERVAL)

musicbrainzngs.set_useragent(
    settings.musicbrainz_user_agent,
    "0.1",
    "contact@example.com",
)


def _escape_lucene(value: str) -> str:
    """Escape Lucene special characters for an unquoted token/phrase."""
    return "".join(f"\\{ch}" if ch in _LUCENE_SPECIAL else ch for ch in value)


class MusicBrainzProvider(BaseProvider):
    """MusicBrainz metadata provider."""

    name = "musicbrainz"

    def __init__(self):
        self.cover_art_url = "https://coverartarchive.org/release/{mbid}/front"

    async def search_track(
        self,
        title: str,
        artist: str,
        duration: Optional[int] = None,
    ) -> list[TrackResult]:
        """Search for a track on MusicBrainz.

        Uses unquoted Lucene field queries. Quoted phrase search often returns
        zero hits for CJK titles even when the recording exists under a looser
        token match.
        """
        title = (title or "").strip()
        artist = (artist or "").strip()
        if not title and not artist:
            return []

        # Prefer fielded title+artist, then free-text, then title-only. Quoted
        # phrase search is avoided: it often yields zero CJK hits.
        queries: list[str] = []
        if title and artist:
            queries.append(
                f"recording:{_escape_lucene(title)} AND artist:{_escape_lucene(artist)}"
            )
            queries.append(f"{_escape_lucene(title)} {_escape_lucene(artist)}")
        if title:
            queries.append(f"recording:{_escape_lucene(title)}")
        elif artist:
            queries.append(f"artist:{_escape_lucene(artist)}")

        merged: dict[str, TrackResult] = {}
        for index, query in enumerate(queries):
            batch = await self._search_recordings(query, title)
            for track in batch:
                existing = merged.get(track.mbid)
                if existing is None or (not existing.album and track.album):
                    merged[track.mbid] = track

            # Good enough title hit from a tighter query → stop to save rate limit.
            if any(t.confidence >= 0.8 for t in batch):
                break
            # First query empty → keep falling back; weak-only hits → also try next.
            if index == 0 and batch and any(t.confidence >= 0.6 for t in batch):
                break

        return list(merged.values())
    async def _search_recordings(self, query: str, title_hint: str) -> list[TrackResult]:
        try:
            await _rate_limiter.wait()
            result = await asyncio.to_thread(
                musicbrainzngs.search_recordings,
                query=query,
                limit=10,
                offset=0,
            )
        except Exception:
            logger.warning("MusicBrainz track search failed: %s", query, exc_info=True)
            return []

        tracks: list[TrackResult] = []
        for recording in result.get("recording-list", []):
            mbid = recording.get("id") or ""
            if not mbid:
                continue

            releases = recording.get("release-list", []) or []
            release = releases[0] if releases else {}

            track_duration = recording.get("length")
            if track_duration:
                track_duration = int(track_duration) // 1000

            year = None
            date = release.get("date", "") if release else ""
            if date:
                try:
                    year = int(date[:4])
                except ValueError:
                    pass

            rec_title = recording.get("title", "") or ""
            confidence = self._calculate_title_confidence(title_hint, rec_title)

            tracks.append(
                TrackResult(
                    title=rec_title,
                    artist=self._get_artist_name(recording),
                    album=release.get("title", "") if release else "",
                    duration=track_duration or 0,
                    mbid=mbid,
                    confidence=confidence,
                    album_mbid=release.get("id") if release else None,
                    year=year,
                )
            )
        return tracks

    async def search_album(
        self,
        album: str,
        artist: str,
    ) -> list[AlbumResult]:
        """Search for an album on MusicBrainz."""
        try:
            album = (album or "").strip()
            artist = (artist or "").strip()
            parts = []
            if album:
                parts.append(f"release:{_escape_lucene(album)}")
            if artist:
                parts.append(f"artist:{_escape_lucene(artist)}")
            if not parts:
                return []
            query = " AND ".join(parts)

            await _rate_limiter.wait()
            result = await asyncio.to_thread(
                musicbrainzngs.search_releases,
                query=query,
                limit=10,
            )

            albums = []
            for release in result.get("release-list", []):
                date = release.get("date", "")
                year = None
                if date:
                    try:
                        year = int(date[:4])
                    except ValueError:
                        pass

                albums.append(
                    AlbumResult(
                        title=release.get("title", ""),
                        artist=self._get_release_artist(release),
                        year=year,
                        mbid=release.get("id", ""),
                        cover_url=self.cover_art_url.format(mbid=release.get("id", "")),
                    )
                )

            return albums

        except Exception:
            logger.warning("MusicBrainz album search failed: %s - %s", album, artist, exc_info=True)
            return []

    async def get_cover(self, mbid: str) -> Optional[bytes]:
        """Get album cover from Cover Art Archive."""
        try:
            url = self.cover_art_url.format(mbid=mbid)
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.content
        except Exception:
            logger.warning("Failed to fetch cover for %s", mbid, exc_info=True)
        return None

    @staticmethod
    def _get_artist_name(recording: dict) -> str:
        """Extract artist credit string from a recording."""
        return MusicBrainzProvider._format_artist_credit(
            recording.get("artist-credit", [])
        )

    @staticmethod
    def _get_release_artist(release: dict) -> str:
        """Extract artist credit string from a release."""
        return MusicBrainzProvider._format_artist_credit(
            release.get("artist-credit", [])
        )

    @staticmethod
    def _format_artist_credit(artist_credit: list) -> str:
        if not artist_credit:
            return "Unknown Artist"
        parts: list[str] = []
        for item in artist_credit:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                artist = item.get("artist") or {}
                if isinstance(artist, dict):
                    name = artist.get("name")
            if name:
                parts.append(str(name))
            joinphrase = item.get("joinphrase")
            if joinphrase:
                parts.append(str(joinphrase))
        text = "".join(parts).strip()
        return text or "Unknown Artist"

    @staticmethod
    def _calculate_title_confidence(query: str, result: str) -> float:
        """Calculate title similarity confidence."""
        query_lower = query.lower().strip()
        result_lower = result.lower().strip()

        if not query_lower:
            return 0.5
        if query_lower == result_lower:
            return 1.0
        if query_lower in result_lower or result_lower in query_lower:
            return 0.8
        if MusicBrainzProvider._levenshtein_ratio(query_lower, result_lower) > 0.8:
            return 0.6
        return 0.3

    @staticmethod
    def _levenshtein_ratio(s1: str, s2: str) -> float:
        """Calculate Levenshtein distance ratio."""
        if len(s1) == 0 and len(s2) == 0:
            return 1.0
        if len(s1) == 0 or len(s2) == 0:
            return 0.0

        # Simple ratio calculation
        longer = s1 if len(s1) >= len(s2) else s2
        shorter = s2 if len(s1) >= len(s2) else s1

        longer_len = len(longer)
        shorter_len = len(shorter)

        # Trivial case: exact match
        if longer == shorter:
            return 1.0

        # Simple character overlap ratio as approximation
        common = sum(1 for c in shorter if c in longer)
        return 2.0 * common / (longer_len + shorter_len)
