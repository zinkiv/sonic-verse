"""Match scoring and candidate re-ranking."""

import pytest

from sonicverse.matcher.batch import _meets_threshold
from sonicverse.matcher.matcher import TrackMatcher
from sonicverse.matcher.percent import as_match_percent, clamp_match_threshold
from sonicverse.metadata.parser import AudioMetadata
from sonicverse.providers.base import AlbumResult, BaseProvider, TrackResult


class FakeProvider(BaseProvider):
    """Returns a canned candidate list and records how it was called."""

    name = "fake"

    def __init__(self, results: list[TrackResult]):
        self.results = results
        self.calls: list[tuple] = []

    async def search_track(self, title, artist, duration=None) -> list[TrackResult]:
        self.calls.append((title, artist, duration))
        return list(self.results)

    async def search_album(self, album, artist) -> list[AlbumResult]:
        return []

    async def get_cover(self, mbid) -> bytes | None:
        return None


def candidate(title="晴天", artist="周杰伦", duration=269, confidence=0.0):
    return TrackResult(
        title=title,
        artist=artist,
        album="叶惠美",
        duration=duration,
        mbid=f"mbid-{title}",
        confidence=confidence,
    )


def test_identical_strings_score_100():
    assert TrackMatcher._string_similarity("abc", "abc") == 100


def test_empty_string_scores_zero():
    assert TrackMatcher._string_similarity("", "abc") == 0
    assert TrackMatcher._string_similarity("abc", "") == 0


def test_substring_scores_80():
    assert TrackMatcher._string_similarity("hello", "hello world") == 80


def test_space_separated_uses_word_jaccard():
    # {a, b} vs {b, c} -> 1 shared out of 3 distinct → 33%
    assert TrackMatcher._string_similarity("a b", "b c") == 33


def test_cjk_uses_character_bigrams():
    # {我的, 的地, 地盘} vs {我的, 的天, 天空} -> 1 shared out of 5 → 20%
    assert TrackMatcher._string_similarity("我的地盘", "我的天空") == 20


def test_bigrams():
    assert TrackMatcher._bigrams("abc") == {"ab", "bc"}
    assert TrackMatcher._bigrams("a") == {"a"}


def test_perfect_match_scores_100():
    local = AudioMetadata(title="晴天", artist="周杰伦", duration_ms=269_000)
    assert TrackMatcher.calculate_match_score(candidate(), local) == 100


def test_as_match_percent_accepts_legacy_fractions():
    assert as_match_percent(1.0) == 100
    assert as_match_percent(0.8) == 80
    assert as_match_percent(80) == 80
    assert as_match_percent(0) == 0
    assert clamp_match_threshold(0.65) == 65
    assert clamp_match_threshold(100) == 100


def test_integer_percent_threshold_gate():
    assert _meets_threshold(100, 100)
    assert _meets_threshold(80, 80)
    assert not _meets_threshold(79, 80)
    assert _meets_threshold(0.999, 100)  # legacy fraction → 100


@pytest.mark.parametrize(
    ("candidate_duration", "expected"),
    [(269, 100), (275, 93), (289, 88), (320, 85)],
)
def test_duration_bonus_decays(candidate_duration, expected):
    local = AudioMetadata(title="晴天", artist="周杰伦", duration_ms=269_000)
    score = TrackMatcher.calculate_match_score(
        candidate(duration=candidate_duration), local
    )
    assert score == expected


def test_missing_local_title_scores_artist_only():
    local = AudioMetadata(title=None, artist="周杰伦", duration_ms=None)
    # artist 100% * 25 weight → 25
    assert TrackMatcher.calculate_match_score(candidate(), local) == 25


def test_long_podcast_title_scores_below_exact_song():
    local = AudioMetadata(title="听说你", artist="于冬然", duration_ms=239_000)
    exact = candidate(title="听说你", artist="于冬然", duration=239)
    podcast = candidate(
        title="第2078章 听说你是全米人民的希望？(节目)",
        artist="播音酷言",
        duration=665,
    )
    assert TrackMatcher.calculate_match_score(exact, local) > TrackMatcher.calculate_match_score(
        podcast, local
    )


def test_resolve_match_query_prefers_filename_artist_when_tags_disagree():
    from sonicverse.matcher.query import resolve_match_query

    title, artist = resolve_match_query(
        title="听说你",
        artist="全网找歌君",
        file_path="/music/于冬然 - 听说你.flac",
    )
    assert title == "听说你"
    assert artist == "于冬然"


def test_resolve_match_query_accepts_hyphen_filename():
    from sonicverse.matcher.query import resolve_match_query

    title, artist = resolve_match_query(
        title="",
        artist="",
        file_path="/music/周杰伦,费玉清-千里之外.flac",
    )
    assert title == "千里之外"
    assert artist == "周杰伦,费玉清"


def test_resolve_match_query_strips_remix_suffix():
    from sonicverse.matcher.query import resolve_match_query

    title, artist = resolve_match_query(
        title="青花瓷 (Tanii1.2x变速版)",
        artist="Simyee陈芯怡",
        file_path="/transfer/Simyee陈芯怡-青花瓷.flac",
    )
    assert title == "青花瓷"
    assert artist == "Simyee陈芯怡"


def test_remix_local_title_scores_core_candidate_high():
    local = AudioMetadata(
        title="青花瓷 (Tanii1.2x变速版)",
        artist="SimYee陈芯怡",
        duration_ms=201_000,
    )
    hit = candidate(title="青花瓷", artist="SimYee陈芯怡", duration=201)
    other = candidate(title="青花瓷", artist="阿杰", duration=201)
    assert TrackMatcher.calculate_match_score(hit, local) > TrackMatcher.calculate_match_score(
        other, local
    )
    assert TrackMatcher.calculate_match_score(hit, local) >= 80


async def test_find_matches_reranks_by_local_score():
    weak = candidate(title="完全不同的歌", artist="别的歌手", confidence=0.9)
    strong = candidate(confidence=0.1)
    matcher = TrackMatcher(FakeProvider([weak, strong]))

    results = await matcher.find_matches("晴天", "周杰伦", duration_ms=269_000)

    assert [r.title for r in results] == ["晴天", "完全不同的歌"]
    assert results[0].score == 100
    assert results[0].confidence == 10  # provider 0.1 → 10%


async def test_find_matches_passes_duration_in_seconds():
    provider = FakeProvider([candidate()])
    matcher = TrackMatcher(provider)

    await matcher.find_matches("晴天", "周杰伦", duration_ms=269_000)

    assert provider.calls == [("晴天", "周杰伦", 269)]


async def test_find_matches_respects_limit():
    provider = FakeProvider([candidate(title=f"t{i}") for i in range(10)])
    matcher = TrackMatcher(provider)

    results = await matcher.find_matches("晴天", "周杰伦", limit=3)

    assert len(results) == 3
