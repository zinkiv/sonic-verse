"""Search providers and persist match candidates for a track."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import delete

from sonicverse.matcher.matcher import TrackMatcher
from sonicverse.matcher.percent import as_match_percent
from sonicverse.matcher.query import resolve_match_query
from sonicverse.metadata.parser import MetadataReader
from sonicverse.models import ProviderResult, Track
from sonicverse.providers import BATCH_SEARCH_PROVIDERS, SEARCH_PROVIDERS, provider_rank
from sonicverse.providers.base import TrackResult
from sonicverse.schemas.match import MatchCandidate

logger = logging.getLogger(__name__)

_PER_PROVIDER_LIMIT = 8
_MERGED_LIMIT = 16
# Organize: skip NetEase only when QQ already has a perfect local score.
_BATCH_PERFECT_SCORE = 100


def _provider_names(provider_name: str | None) -> tuple[str, ...]:
    key = (provider_name or "").strip().lower()
    if key in SEARCH_PROVIDERS:
        return (key,)
    return SEARCH_PROVIDERS


async def search_and_store_candidates(
    session,
    track: Track,
    provider_name: str | None = None,
    *,
    limit: int | None = None,
    before_provider_search: Callable[[str], Awaitable[None]] | None = None,
    batch_organize: bool = False,
) -> list[MatchCandidate]:
    """Search one provider, or both when ``provider_name`` is omitted.

    Manual query passes a source. Organize searches QQ Music first; if QQ is
    empty/fails or its best local score is below 100%, also query NetEase, then
    rank by score (QQ wins ties). Commits once before outbound HTTP so the
    pooled DB connection is released during provider searches; candidate writes
    remain uncommitted for the caller.
    """
    names = _provider_names(provider_name)
    keep = limit if limit is not None else (
        _MERGED_LIMIT if len(names) > 1 else _PER_PROVIDER_LIMIT
    )

    await session.refresh(track, attribute_names=["artist", "album"])

    tagged_artist = track.artist.name if track.artist else ""
    title, artist_name = resolve_match_query(
        title=track.title,
        artist=tagged_artist,
        file_path=track.file_path,
    )
    if not title:
        return []

    track_id = track.id
    duration_ms = track.duration_ms
    if duration_ms is None:
        try:
            file_meta = await asyncio.to_thread(MetadataReader.read, track.file_path)
            if file_meta and file_meta.duration_ms:
                duration_ms = file_meta.duration_ms
                track.duration_ms = file_meta.duration_ms
        except Exception:
            logger.debug(
                "Could not re-read duration for %s", track.file_path, exc_info=True
            )

    # Release the pooled connection before slow provider HTTP calls.
    await session.commit()

    if batch_organize and provider_name is None:
        matches = await _search_providers_batch(
            title,
            artist_name,
            duration_ms,
            before_provider_search=before_provider_search,
        )
    else:
        matches = await _search_providers(
            names,
            title,
            artist_name,
            duration_ms,
            before_provider_search=before_provider_search,
        )
    matches.sort(
        key=lambda item: (
            -as_match_percent(item.score),
            provider_rank(item.provider),
            -as_match_percent(item.confidence),
        )
    )
    matches = matches[: max(1, keep)]

    await session.execute(
        delete(ProviderResult).where(
            ProviderResult.track_id == track_id,
            ProviderResult.applied.is_(False),
        )
    )

    candidates: list[MatchCandidate] = []
    for match in matches:
        source = match.provider or "netease"
        score_pct = as_match_percent(match.score)
        confidence_pct = as_match_percent(match.confidence) or score_pct
        payload = {
            "title": match.title,
            "artist": match.artist,
            "album": match.album,
            "duration": match.duration,
            "mbid": match.mbid,
            "album_mbid": match.album_mbid,
            "year": match.year,
            "confidence": confidence_pct,
            "score": score_pct,
            "cover_url": match.cover_url,
            "artist_image_url": match.artist_image_url,
            "artist_images": match.artist_images,
            "provider": source,
        }
        session.add(
            ProviderResult(
                track_id=track_id,
                provider=source,
                provider_mbid=match.mbid,
                confidence=float(score_pct or confidence_pct),
                metadata_json=payload,
                applied=False,
            )
        )
        candidates.append(MatchCandidate.model_validate(payload))

    return candidates


async def _search_providers_batch(
    title: str,
    artist_name: str,
    duration_ms: int | None,
    *,
    before_provider_search: Callable[[str], Awaitable[None]] | None = None,
) -> list[TrackResult]:
    """QQ first; NetEase when QQ is empty/fails or best QQ score < 100%."""
    merged: list[TrackResult] = []
    for index, name in enumerate(BATCH_SEARCH_PROVIDERS):
        try:
            group = await _search_one_provider(
                name,
                title,
                artist_name,
                duration_ms,
                before_provider_search=before_provider_search,
            )
        except Exception as exc:
            logger.warning("Provider %s search failed: %s", name, exc)
            group = []

        if not group:
            continue

        merged.extend(group)
        # First provider (QQ): only skip the rest on a perfect hit.
        if index == 0:
            best = max(as_match_percent(item.score) for item in group)
            if best >= _BATCH_PERFECT_SCORE:
                break
    return merged


async def _search_one_provider(
    name: str,
    title: str,
    artist_name: str,
    duration_ms: int | None,
    *,
    before_provider_search: Callable[[str], Awaitable[None]] | None = None,
) -> list[TrackResult]:
    if before_provider_search is not None:
        await before_provider_search(name)
    matcher = TrackMatcher(name)
    return await matcher.find_matches(
        title=title,
        artist=artist_name,
        duration_ms=duration_ms,
        limit=_PER_PROVIDER_LIMIT,
    )


async def _search_providers(
    names: tuple[str, ...],
    title: str,
    artist_name: str,
    duration_ms: int | None,
    *,
    before_provider_search: Callable[[str], Awaitable[None]] | None = None,
) -> list[TrackResult]:
    async def search_one(name: str) -> list[TrackResult]:
        return await _search_one_provider(
            name,
            title,
            artist_name,
            duration_ms,
            before_provider_search=before_provider_search,
        )

    groups = await asyncio.gather(
        *[search_one(name) for name in names],
        return_exceptions=True,
    )
    merged: list[TrackResult] = []
    for name, group in zip(names, groups, strict=True):
        if isinstance(group, BaseException):
            logger.warning("Provider %s search failed: %s", name, group)
            continue
        merged.extend(group)
    return merged
