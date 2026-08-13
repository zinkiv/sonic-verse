"""Batch organize provider cascade (QQ → NetEase when QQ < 100%)."""

from unittest.mock import patch

import pytest

from sonicverse.matcher.search import search_and_store_candidates
from sonicverse.providers.base import AlbumResult, BaseProvider, TrackResult


class RecordingProvider(BaseProvider):
    calls: list[str] = []

    def __init__(self, name: str, results: list[TrackResult]):
        self.name = name
        self.results = results

    async def search_track(self, title, artist, duration=None) -> list[TrackResult]:
        RecordingProvider.calls.append(self.name)
        return list(self.results)

    async def search_album(self, album, artist) -> list[AlbumResult]:
        return []

    async def get_cover(self, mbid) -> bytes | None:
        return None


def _hit(
    *,
    title: str,
    artist: str,
    mbid: str,
    provider: str,
    duration: int = 200,
) -> TrackResult:
    return TrackResult(
        title=title,
        artist=artist,
        album="Test Album",
        duration=duration,
        mbid=mbid,
        provider=provider,
    )


@pytest.fixture(autouse=True)
def reset_calls():
    RecordingProvider.calls = []
    yield
    RecordingProvider.calls = []


async def test_batch_organize_uses_qq_only_when_qq_is_perfect(session, library):
    track = library["tracks"][0]
    providers = {
        "qqmusic": RecordingProvider(
            "qqmusic",
            [_hit(title="以父之名", artist="周杰伦", mbid="qq:song:1", provider="qqmusic")],
        ),
        "netease": RecordingProvider(
            "netease",
            [_hit(title="以父之名", artist="周杰伦", mbid="ne:song:1", provider="netease")],
        ),
    }

    with (
        patch(
            "sonicverse.matcher.matcher.get_provider",
            side_effect=lambda name: providers[name],
        ),
        patch("sonicverse.matcher.search.MetadataReader.read", return_value=None),
    ):
        candidates = await search_and_store_candidates(
            session, track, batch_organize=True
        )

    assert RecordingProvider.calls == ["qqmusic"]
    assert [item.provider for item in candidates] == ["qqmusic"]
    assert candidates[0].score == 100


async def test_batch_organize_queries_netease_when_qq_below_100(session, library):
    track = library["tracks"][0]
    providers = {
        "qqmusic": RecordingProvider(
            "qqmusic",
            # Wrong artist → local score well below 100%.
            [_hit(title="以父之名", artist="其他歌手", mbid="qq:song:weak", provider="qqmusic")],
        ),
        "netease": RecordingProvider(
            "netease",
            [_hit(title="以父之名", artist="周杰伦", mbid="ne:song:1", provider="netease")],
        ),
    }

    with (
        patch(
            "sonicverse.matcher.matcher.get_provider",
            side_effect=lambda name: providers[name],
        ),
        patch("sonicverse.matcher.search.MetadataReader.read", return_value=None),
    ):
        candidates = await search_and_store_candidates(
            session, track, batch_organize=True
        )

    assert RecordingProvider.calls == ["qqmusic", "netease"]
    assert candidates[0].provider == "netease"
    assert candidates[0].score == 100
    assert candidates[0].mbid == "ne:song:1"


async def test_batch_organize_falls_back_to_netease_when_qq_empty(session, library):
    track = library["tracks"][0]
    providers = {
        "qqmusic": RecordingProvider("qqmusic", []),
        "netease": RecordingProvider(
            "netease",
            [_hit(title="以父之名", artist="周杰伦", mbid="ne:song:1", provider="netease")],
        ),
    }

    with (
        patch(
            "sonicverse.matcher.matcher.get_provider",
            side_effect=lambda name: providers[name],
        ),
        patch("sonicverse.matcher.search.MetadataReader.read", return_value=None),
    ):
        candidates = await search_and_store_candidates(
            session, track, batch_organize=True
        )

    assert RecordingProvider.calls == ["qqmusic", "netease"]
    assert candidates[0].provider == "netease"


async def test_batch_organize_falls_back_when_qq_raises(session, library):
    track = library["tracks"][0]

    class FailQQ(RecordingProvider):
        async def search_track(self, title, artist, duration=None):
            RecordingProvider.calls.append("qqmusic")
            raise RuntimeError("rate limited")

    providers = {
        "qqmusic": FailQQ("qqmusic", []),
        "netease": RecordingProvider(
            "netease",
            [_hit(title="以父之名", artist="周杰伦", mbid="ne:song:1", provider="netease")],
        ),
    }

    with (
        patch(
            "sonicverse.matcher.matcher.get_provider",
            side_effect=lambda name: providers[name],
        ),
        patch("sonicverse.matcher.search.MetadataReader.read", return_value=None),
    ):
        candidates = await search_and_store_candidates(
            session, track, batch_organize=True
        )

    assert RecordingProvider.calls == ["qqmusic", "netease"]
    assert candidates[0].mbid == "ne:song:1"
