from sonicverse.providers.queries import (
    is_strong_title_hit,
    merge_query_searches,
    search_query_variants,
)


def test_mixed_artist_adds_title_and_artist_queries():
    assert search_query_variants("青花瓷", "SimYee陈芯怡") == [
        "青花瓷 SimYee陈芯怡",
        "青花瓷",
    ]


def test_remix_suffix_is_stripped_before_search():
    assert search_query_variants("青花瓷 (Tanii1.2x变速版)", "SimYee陈芯怡") == [
        "青花瓷 SimYee陈芯怡",
        "青花瓷",
    ]


def test_title_only():
    assert search_query_variants("青花瓷", "") == ["青花瓷"]


def test_artist_only():
    assert search_query_variants("", "SimYee陈芯怡") == ["SimYee陈芯怡"]


def test_strong_title_hit_ignores_remix_suffix():
    assert is_strong_title_hit("青花瓷", "青花瓷 (Tanii1.2x变速版)")


async def test_merge_query_searches_stops_after_exact_title():
    calls: list[str] = []

    class Hit:
        def __init__(self, mbid: str, title: str):
            self.mbid = mbid
            self.title = title

    async def search(query: str) -> list[Hit]:
        calls.append(query)
        if "周杰伦" in query:
            return [Hit("ne:song:1", "以父之名")]
        return [Hit("ne:song:other", "其他")]

    results = await merge_query_searches(search, "以父之名", "周杰伦")
    assert [item.mbid for item in results] == ["ne:song:1"]
    assert calls == ["以父之名 周杰伦"]
