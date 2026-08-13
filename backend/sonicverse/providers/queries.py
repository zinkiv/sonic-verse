"""Build provider search queries from local title/artist."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from sonicverse.core.titles import core_title


class _TitledHit(Protocol):
    mbid: str
    title: str


def search_query_variants(title: str, artist: str) -> list[str]:
    """Most-specific queries first, title-only last as a fallback.

    Remix suffixes like ``(Tanii1.2x变速版)`` are stripped so providers search
    ``青花瓷`` instead of the full tagged title. Mixed names such as
    ``SimYee陈芯怡`` also get a CJK-only artist query.
    """
    raw_title = (title or "").strip()
    primary = core_title(raw_title) or raw_title
    artist = (artist or "").strip()
    queries: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        query = " ".join(raw.split())
        if query and query not in seen:
            seen.add(query)
            queries.append(query)

    if primary and artist:
        add(f"{primary} {artist}")
        add(primary)
    elif primary:
        add(primary)
    elif artist:
        add(artist)
    return queries


def is_strong_title_hit(result_title: str, query_title: str) -> bool:
    """True when a provider hit is the same song name (ignoring remix suffixes)."""
    want = (query_title or "").strip().lower()
    got = (result_title or "").strip().lower()
    if not want or not got:
        return False
    if got == want:
        return True
    want_core = (core_title(query_title) or query_title).strip().lower()
    got_core = (core_title(result_title) or result_title).strip().lower()
    return bool(want_core) and got_core == want_core


async def merge_query_searches(
    search: Callable[[str], Awaitable[list[_TitledHit]]],
    title: str,
    artist: str,
) -> list[_TitledHit]:
    """Run query variants until one returns an exact/core title hit."""
    merged: dict[str, _TitledHit] = {}
    for query in search_query_variants(title, artist):
        for track in await search(query):
            if track.mbid not in merged:
                merged[track.mbid] = track
        if any(is_strong_title_hit(item.title, title) for item in merged.values()):
            break
    return list(merged.values())
