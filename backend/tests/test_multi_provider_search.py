"""Merged NetEase + QQ Music candidate ranking."""

from unittest.mock import patch

from sonicverse.matcher.search import search_and_store_candidates
from sonicverse.providers.base import AlbumResult, BaseProvider, TrackResult


class NamedProvider(BaseProvider):
    def __init__(self, name: str, results: list[TrackResult]):
        self.name = name
        self.results = results

    async def search_track(self, title, artist, duration=None) -> list[TrackResult]:
        return list(self.results)

    async def search_album(self, album, artist) -> list[AlbumResult]:
        return []

    async def get_cover(self, mbid) -> bytes | None:
        return None


def _hit(*, title: str, artist: str, mbid: str, provider: str) -> TrackResult:
    return TrackResult(
        title=title,
        artist=artist,
        album="叶惠美",
        duration=200,
        mbid=mbid,
        provider=provider,
    )


async def test_equal_scores_prefer_qqmusic(session, library):
    track = library["tracks"][0]
    providers = {
        "netease": NamedProvider(
            "netease",
            [_hit(title="以父之名", artist="周杰伦", mbid="ne:song:1", provider="netease")],
        ),
        "qqmusic": NamedProvider(
            "qqmusic",
            [_hit(title="以父之名", artist="周杰伦", mbid="qq:song:1", provider="qqmusic")],
        ),
    }

    with (
        patch(
            "sonicverse.matcher.matcher.get_provider",
            side_effect=lambda name: providers[name],
        ),
        patch("sonicverse.matcher.search.MetadataReader.read", return_value=None),
    ):
        candidates = await search_and_store_candidates(session, track)

    assert [item.provider for item in candidates] == ["qqmusic", "netease"]
    assert [item.mbid for item in candidates] == ["qq:song:1", "ne:song:1"]


async def test_higher_score_beats_provider_priority(session, library):
    track = library["tracks"][0]
    providers = {
        "netease": NamedProvider(
            "netease",
            [_hit(title="以父之名", artist="路人", mbid="ne:song:miss", provider="netease")],
        ),
        "qqmusic": NamedProvider(
            "qqmusic",
            [_hit(title="以父之名", artist="周杰伦", mbid="qq:song:hit", provider="qqmusic")],
        ),
    }

    with (
        patch(
            "sonicverse.matcher.matcher.get_provider",
            side_effect=lambda name: providers[name],
        ),
        patch("sonicverse.matcher.search.MetadataReader.read", return_value=None),
    ):
        candidates = await search_and_store_candidates(session, track)

    assert candidates[0].provider == "qqmusic"
    assert candidates[0].mbid == "qq:song:hit"
    assert candidates[1].provider == "netease"


async def test_manual_query_uses_selected_provider_only(session, library):
    track = library["tracks"][0]
    providers = {
        "netease": NamedProvider(
            "netease",
            [_hit(title="以父之名", artist="周杰伦", mbid="ne:song:1", provider="netease")],
        ),
        "qqmusic": NamedProvider(
            "qqmusic",
            [_hit(title="以父之名", artist="周杰伦", mbid="qq:song:1", provider="qqmusic")],
        ),
    }

    with (
        patch(
            "sonicverse.matcher.matcher.get_provider",
            side_effect=lambda name: providers[name],
        ),
        patch("sonicverse.matcher.search.MetadataReader.read", return_value=None),
    ):
        candidates = await search_and_store_candidates(session, track, "netease")

    assert [item.provider for item in candidates] == ["netease"]
    assert candidates[0].mbid == "ne:song:1"
