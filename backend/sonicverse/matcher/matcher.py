"""Music matching algorithm (integer 0–100 percent scores)."""

from sonicverse.core.titles import core_title
from sonicverse.matcher.percent import as_match_percent
from sonicverse.metadata.parser import AudioMetadata
from sonicverse.providers import get_provider
from sonicverse.providers.base import TrackResult, BaseProvider

# Titles that usually mean podcasts / radio / covers of ambient recordings.
_JUNK_TITLE_MARKERS = (
    "节目",
    "播音",
    "哄睡",
    "录音笔",
    "电台",
    "有声",
    "章节",
    "广播",
    "解读",
    "听书",
)

# Weighted parts in percent points (sum to 100).
_TITLE_WEIGHT = 60
_ARTIST_WEIGHT = 25
_DURATION_CLOSE = 15  # |Δ| < 5s
_DURATION_NEAR = 8  # |Δ| < 10s
_DURATION_LOOSE = 3  # |Δ| < 30s


class TrackMatcher:
    """Matches local tracks to metadata providers."""

    def __init__(self, provider: BaseProvider | str | None = None):
        if isinstance(provider, str):
            self.provider = get_provider(provider)
        elif provider is None:
            self.provider = get_provider("netease")
        else:
            self.provider = provider

    async def find_matches(
        self,
        title: str,
        artist: str,
        duration_ms: int | None = None,
        limit: int = 5,
    ) -> list[TrackResult]:
        """Find matching tracks from provider, ranked by local match score."""
        duration_sec = duration_ms // 1000 if duration_ms else None

        results = await self.provider.search_track(
            title=title,
            artist=artist,
            duration=duration_sec,
        )

        local = AudioMetadata(title=title, artist=artist, duration_ms=duration_ms)
        provider_name = getattr(self.provider, "name", "") or ""
        for result in results:
            # Providers still emit 0–1 confidence; normalize before local scoring.
            result.confidence = as_match_percent(result.confidence)
            result.score = self.calculate_match_score(result, local)
            if not result.provider:
                result.provider = provider_name
        query_core = core_title(title).lower()
        results.sort(
            key=lambda r: (
                r.score,
                1 if core_title(r.title or "").lower() == query_core else 0,
                r.confidence,
            ),
            reverse=True,
        )
        return results[:limit]

    @staticmethod
    def calculate_match_score(candidate: TrackResult, metadata: AudioMetadata) -> int:
        """Score a candidate as an integer percent (0–100)."""
        local_title = metadata.title.lower() if metadata.title else ""
        cand_title = candidate.title.lower() if candidate.title else ""

        title_pct = TrackMatcher._title_similarity(cand_title, local_title)
        artist_pct = TrackMatcher._string_similarity(
            candidate.artist.lower() if candidate.artist else "",
            metadata.artist.lower() if metadata.artist else "",
        )
        # Integer weighted average of title/artist, then add duration points.
        score = (title_pct * _TITLE_WEIGHT + artist_pct * _ARTIST_WEIGHT) // 100

        if metadata.duration_ms and candidate.duration:
            duration_diff = abs(candidate.duration - metadata.duration_ms / 1000)
            if duration_diff < 5:
                score += _DURATION_CLOSE
            elif duration_diff < 10:
                score += _DURATION_NEAR
            elif duration_diff < 30:
                score += _DURATION_LOOSE

        if TrackMatcher._looks_like_junk(candidate.title):
            score = (score * 25) // 100

        return max(0, min(100, int(score)))

    @staticmethod
    def _title_similarity(candidate: str, query: str) -> int:
        """Title similarity as 0–100."""
        if not candidate or not query:
            return 0
        if candidate == query:
            return 100
        cand_core = core_title(candidate)
        query_core = core_title(query)
        if cand_core and query_core and cand_core == query_core:
            return 95
        if cand_core == query or query_core == candidate:
            return 95
        if candidate.startswith(query) and len(candidate) <= len(query) + 12:
            return 90
        # Long titles that merely contain the query (podcasts) score poorly.
        if query_core and query_core in candidate and query_core != candidate:
            if len(candidate) > len(query_core) * 2:
                return 15
            return 55
        if cand_core and cand_core in query:
            return 70
        return TrackMatcher._string_similarity(
            cand_core or candidate, query_core or query
        )

    @staticmethod
    def _looks_like_junk(title: str | None) -> bool:
        if not title:
            return False
        return any(marker in title for marker in _JUNK_TITLE_MARKERS)

    @staticmethod
    def _string_similarity(s1: str, s2: str) -> int:
        """String similarity ratio as 0–100.

        Word-level Jaccard for space-separated languages; character-bigram
        Jaccard for languages without whitespace (e.g. Chinese/Japanese).
        """
        if not s1 or not s2:
            return 0
        if s1 == s2:
            return 100
        if s1 in s2 or s2 in s1:
            return 80

        if " " in s1 or " " in s2:
            set1 = set(s1.split())
            set2 = set(s2.split())
        else:
            set1 = TrackMatcher._bigrams(s1)
            set2 = TrackMatcher._bigrams(s2)

        if not set1 or not set2:
            return 0

        intersection = len(set1 & set2)
        union = len(set1 | set2)
        if union <= 0:
            return 0
        return (intersection * 100) // union

    @staticmethod
    def _bigrams(s: str) -> set[str]:
        """Character bigrams of a string (single character → unigram set)."""
        if len(s) < 2:
            return {s}
        return {s[i : i + 2] for i in range(len(s) - 1)}
