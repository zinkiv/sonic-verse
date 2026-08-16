"""Match / refresh artist metadata (primarily avatar images)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from sonicverse.core.artists import split_artist_names
from sonicverse.matcher.apply import _download_image, _save_artist_avatar
from sonicverse.matcher.matcher import TrackMatcher
from sonicverse.models import Artist
from sonicverse.providers import SEARCH_PROVIDERS, get_provider, provider_rank

logger = logging.getLogger(__name__)

_CANDIDATE_LIMIT = 12
_COLLECT_LIMIT = 20
_MIN_IMAGE_BYTES = 512
_PLACEHOLDER_MARKERS = (
    "109951163799671647",
    "18686200114669622",
)
_PUNCT_RE = re.compile(r"[\s,./&;；、'\"·\-]+")


def _fold_name(value: str) -> str:
    return _PUNCT_RE.sub("", (value or "").casefold())


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _has_name_boundary(full: str, part: str) -> bool:
    """True when ``part`` appears in ``full`` as its own name, not a substring."""
    if not part or part not in full:
        return False
    start = 0
    while True:
        idx = full.find(part, start)
        if idx < 0:
            return False
        before_ok = idx == 0 or not full[idx - 1].isalnum()
        end = idx + len(part)
        if end >= len(full):
            after_ok = True
        else:
            nxt = full[end]
            after_ok = (
                not nxt.isalnum()
                or (_is_cjk(part[-1]) and nxt.isascii())
                or (part[-1].isascii() and _is_cjk(nxt))
            )
        if before_ok and after_ok:
            return True
        start = idx + 1


def _artist_name_matches(query: str, candidate: str) -> bool:
    """True when the candidate is the queried artist (exact or bounded name)."""
    want = (query or "").strip()
    got = (candidate or "").strip()
    if not want or not got:
        return False
    want_cf = want.casefold()
    got_cf = got.casefold()
    if want_cf == got_cf:
        return True
    want_fold = _fold_name(want)
    got_fold = _fold_name(got)
    if want_fold and want_fold == got_fold:
        return True
    if len(want_cf) < 2 and not _is_cjk(want_cf):
        return False
    return _has_name_boundary(got_cf, want_cf)


def _is_placeholder_url(url: str) -> bool:
    return any(marker in url for marker in _PLACEHOLDER_MARKERS)


def _track_credits_artist(result, artist_name: str) -> bool:
    if _artist_name_matches(artist_name, result.artist or ""):
        return True
    for item in result.artist_images or ():
        if _artist_name_matches(artist_name, item.get("name") or ""):
            return True
    return any(
        _artist_name_matches(artist_name, part)
        for part in split_artist_names(result.artist)
    )


@dataclass(frozen=True)
class ArtistImageCandidate:
    name: str
    url: str
    provider: str


def _collect_track_images(artist_name: str, results) -> list[tuple[str, str]]:
    seen: set[str] = set()
    hits: list[tuple[str, str]] = []

    def add(name: str, url: str) -> None:
        url = (url or "").strip()
        name = (name or "").strip()
        if not url or not name or url in seen or _is_placeholder_url(url):
            return
        if not _artist_name_matches(artist_name, name):
            return
        seen.add(url)
        hits.append((name, url))

    for result in results:
        if TrackMatcher._looks_like_junk(result.title):
            continue
        if not _track_credits_artist(result, artist_name):
            continue
        for item in result.artist_images or ():
            add(item.get("name") or "", item.get("url") or "")
    return hits


def _looks_like_image(data: bytes) -> bool:
    if len(data) < _MIN_IMAGE_BYTES:
        return False
    if data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG"):
        return True
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return data[:6] in (b"GIF87a", b"GIF89a")


async def _url_has_image(url: str) -> bool:
    if _is_placeholder_url(url):
        return False
    data = await _download_image(url)
    return bool(data) and _looks_like_image(data)


async def _keep_reachable(
    hits: list[ArtistImageCandidate],
) -> list[ArtistImageCandidate]:
    if not hits:
        return []
    flags = await asyncio.gather(*(_url_has_image(item.url) for item in hits))
    return [item for item, ok in zip(hits, flags, strict=True) if ok]


async def _search_one_provider(
    artist_name: str,
    provider_name: str,
) -> list[ArtistImageCandidate]:
    hits: list[ArtistImageCandidate] = []
    seen: set[str] = set()

    def append(person: str, url: str, source: str) -> None:
        url = (url or "").strip()
        person = (person or "").strip()
        if not url or not person or url in seen or _is_placeholder_url(url):
            return
        if not _artist_name_matches(artist_name, person):
            return
        seen.add(url)
        hits.append(
            ArtistImageCandidate(name=person, url=url, provider=source)
        )

    try:
        provider = get_provider(provider_name)
    except Exception:
        logger.warning("Unknown artist-image provider: %s", provider_name)
        return []

    try:
        for item in await provider.lookup_artist_images(artist_name):
            append(item.get("name") or "", item.get("url") or "", provider.name)
    except Exception:
        logger.warning(
            "Artist image list lookup failed for %s via %s",
            artist_name,
            provider_name,
            exc_info=True,
        )

    if len(hits) < _COLLECT_LIMIT:
        try:
            results = await provider.search_track(title="", artist=artist_name)
        except Exception:
            logger.warning(
                "Artist metadata search failed for %s via %s",
                artist_name,
                provider_name,
                exc_info=True,
            )
            results = []
        for person, url in _collect_track_images(artist_name, results):
            append(person, url, provider.name)
            if len(hits) >= _COLLECT_LIMIT:
                break

    return hits


async def search_artist_images(
    artist_name: str,
    provider_name: str | None = None,
) -> list[ArtistImageCandidate]:
    """Return unique avatar URLs from QQ and/or NetEase, without writing."""
    name = (artist_name or "").strip()
    if not name:
        return []
    targets = (
        (provider_name,)
        if provider_name in SEARCH_PROVIDERS
        else SEARCH_PROVIDERS
    )
    batches = await asyncio.gather(
        *(_search_one_provider(name, source) for source in targets)
    )
    hits: list[ArtistImageCandidate] = []
    seen: set[str] = set()
    for batch in batches:
        for item in batch:
            if item.url in seen:
                continue
            seen.add(item.url)
            hits.append(item)
    folded = _fold_name(name)
    hits.sort(
        key=lambda item: (
            0 if _fold_name(item.name) == folded else 1,
            provider_rank(item.provider),
        )
    )
    return (await _keep_reachable(hits))[:_CANDIDATE_LIMIT]


async def apply_artist_image(
    session,
    artist: Artist,
    *,
    image_url: str | None = None,
    image_bytes: bytes | None = None,
) -> Artist:
    """Write a chosen (or uploaded) image onto the artist avatar."""
    data = image_bytes if image_bytes else None
    if not data:
        data = await _download_image(image_url)
    if not data:
        return artist
    await _save_artist_avatar(artist, data)
    await session.flush()
    return artist


async def match_artist_metadata(
    session,
    artist: Artist,
    provider_name: str | None = None,
    *,
    force: bool = True,
) -> Artist:
    """Search providers and update the artist's avatar when found."""
    if artist.avatar_path and not force:
        return artist

    candidates = await search_artist_images(artist.name, provider_name)
    if not candidates:
        return artist
    return await apply_artist_image(session, artist, image_url=candidates[0].url)
