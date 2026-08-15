"""QQ Music metadata provider (unofficial public search endpoints)."""

from __future__ import annotations

import logging
from typing import Optional

from sonicverse.core.artists import split_artist_names
from sonicverse.core.http import http_client
from sonicverse.providers.base import AlbumResult, BaseProvider, TrackResult
from sonicverse.providers.queries import merge_query_searches
from sonicverse.providers.year import parse_release_year

logger = logging.getLogger(__name__)


_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
_HEADERS = {
    "Referer": "https://y.qq.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _qq_cover_url(albummid: str | None) -> str | None:
    if not albummid:
        return None
    return f"https://y.gtimg.cn/music/photo_new/T002R500x500M000{albummid}.jpg"


def _qq_artist_url(singermid: str | None) -> str | None:
    if not singermid:
        return None
    return f"https://y.gtimg.cn/music/photo_new/T001R300x300M000{singermid}.jpg"


def _encode_id(kind: str, value: str) -> str:
    return f"qq:{kind}:{value}"


def _decode_album_id(value: str) -> str | None:
    # Accept qq:album:{mid} or legacy bare mid.
    if value.startswith("qq:album:"):
        return value.removeprefix("qq:album:")
    if value.startswith("qq:"):
        return value.split(":", 1)[1]
    return value or None


def _singer_credits(singers: list) -> tuple[str, list[dict[str, str]]]:
    """Normalize QQ singer blobs into individual names + optional avatar URLs.

    QQ often packs multi-artist credits into one singer object::
        {"mid": "...", "name": "侯明昊;陈都灵;田嘉瑞;…"}
    That mid belongs to at most one person, so only single-name singers keep a
    direct avatar URL; combined names are split for later per-artist lookup.
    """
    names: list[str] = []
    images: list[dict[str, str]] = []
    seen: set[str] = set()

    for singer in singers:
        if not isinstance(singer, dict):
            continue
        raw_name = (singer.get("name") or "").strip()
        if not raw_name:
            continue
        parts = split_artist_names(raw_name)
        if not parts:
            parts = [raw_name]
        mid = singer.get("mid") or singer.get("singerMID")
        avatar = _qq_artist_url(str(mid) if mid else None)
        # Only trust the mid when this blob is a single person.
        attach_url = avatar if len(parts) == 1 else None
        for part in parts:
            key = part.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(part)
            if attach_url:
                images.append({"name": part, "url": attach_url})
            else:
                images.append({"name": part, "url": ""})

    artist_name = ",".join(names) if names else "Unknown Artist"
    # Drop empty URLs from the payload; apply will resolve missing ones.
    artist_images = [item for item in images if item.get("url")]
    # Keep name placeholders when we split a group credit but have no URLs yet,
    # so callers know how many people were credited.
    if not artist_images and names:
        artist_images = [{"name": name, "url": ""} for name in names]
    return artist_name, artist_images


class QQMusicProvider(BaseProvider):
    """Search QQ Music and resolve album covers by albummid."""

    name = "qqmusic"

    async def search_track(
        self,
        title: str,
        artist: str,
        duration: Optional[int] = None,
    ) -> list[TrackResult]:
        title = (title or "").strip()
        artist = (artist or "").strip()
        if not title and not artist:
            return []

        return await merge_query_searches(
            lambda query: self._search_songs(query, title_hint=title),
            title,
            artist,
        )

    async def _search_songs(self, query: str, title_hint: str) -> list[TrackResult]:
        try:
            response = await http_client().get(
                _SEARCH_URL,
                params={
                    "w": query,
                    "p": 1,
                    "n": 30,
                    "format": "json",
                    "t": 0,
                    "aggr": 1,
                    "cr": 1,
                    "lossless": 0,
                    "flag_qc": 0,
                    "platform": "yqq",
                },
                headers=_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.warning("QQ Music search failed: %s", query, exc_info=True)
            return []

        songs = (
            ((payload.get("data") or {}).get("song") or {}).get("list") or []
        )
        results: list[TrackResult] = []
        for song in songs:
            songmid = song.get("songmid") or song.get("mid")
            if not songmid:
                continue
            singers = song.get("singer") or []
            artist_name, artist_images = _singer_credits(singers)
            album_name = song.get("albumname") or ""
            albummid = song.get("albummid") or ""
            song_title = song.get("songname") or song.get("title") or ""
            interval = song.get("interval") or 0
            try:
                interval = int(interval)
            except (TypeError, ValueError):
                interval = 0

            first_avatar = next(
                (item["url"] for item in artist_images if item.get("url")),
                None,
            )
            album_blob = song.get("album") if isinstance(song.get("album"), dict) else {}
            results.append(
                TrackResult(
                    title=song_title,
                    artist=artist_name,
                    album=album_name,
                    duration=interval,
                    mbid=_encode_id("song", str(songmid)),
                    confidence=self._title_confidence(title_hint, song_title),
                    album_mbid=_encode_id("album", str(albummid)) if albummid else None,
                    year=parse_release_year(
                        song.get("pubtime"),
                        song.get("publicTime"),
                        song.get("time_public"),
                        song.get("public_time"),
                        album_blob,
                    ),
                    cover_url=_qq_cover_url(albummid),
                    artist_image_url=first_avatar,
                    artist_images=artist_images or None,
                )
            )
        return results

    async def search_album(
        self,
        album: str,
        artist: str,
    ) -> list[AlbumResult]:
        query = " ".join(p for p in [(album or "").strip(), (artist or "").strip()] if p)
        if not query:
            return []
        try:
            response = await http_client().get(
                _SEARCH_URL,
                params={
                    "w": query,
                    "p": 1,
                    "n": 10,
                    "format": "json",
                    "t": 8,  # album
                    "aggr": 0,
                    "cr": 1,
                    "platform": "yqq",
                },
                headers=_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.warning("QQ Music album search failed: %s", query, exc_info=True)
            return []

        albums = (
            ((payload.get("data") or {}).get("album") or {}).get("list") or []
        )
        results: list[AlbumResult] = []
        for item in albums:
            albummid = item.get("albumMID") or item.get("albummid") or item.get("mid")
            if not albummid:
                continue
            results.append(
                AlbumResult(
                    title=item.get("albumName") or item.get("name") or "",
                    artist=item.get("singerName") or "",
                    year=parse_release_year(
                        item.get("publicTime"),
                        item.get("pubtime"),
                        item.get("publish_date"),
                        item.get("time_public"),
                    ),
                    mbid=_encode_id("album", str(albummid)),
                    cover_url=_qq_cover_url(str(albummid)),
                )
            )
        return results

    async def get_cover(self, mbid: str) -> Optional[bytes]:
        albummid = _decode_album_id(mbid)
        url = _qq_cover_url(albummid)
        if not url:
            return None
        try:
            response = await http_client().get(url, headers=_HEADERS)
            if response.status_code == 200 and response.content:
                return response.content
        except Exception:
            logger.warning("QQ Music cover fetch failed: %s", mbid, exc_info=True)
        return None

    async def lookup_artist_image(self, artist_name: str) -> Optional[str]:
        """Resolve a singer avatar via QQ's dedicated singer search (t=1)."""
        hits = await self.lookup_artist_images(artist_name)
        return hits[0]["url"] if hits else None

    async def lookup_artist_images(self, artist_name: str) -> list[dict[str, str]]:
        """Return QQ singer-search avatars, exact name matches first."""
        name = (artist_name or "").strip()
        if not name:
            return []
        try:
            response = await http_client().get(
                _SEARCH_URL,
                params={
                    "w": name,
                    "p": 1,
                    "n": 10,
                    "format": "json",
                    "t": 1,  # singer
                    "aggr": 0,
                    "cr": 1,
                    "platform": "yqq",
                },
                headers=_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.warning("QQ Music singer search failed: %s", name, exc_info=True)
            return []

        singers = ((payload.get("data") or {}).get("singer") or {}).get("list") or []
        target = name.casefold()
        exact: list[dict[str, str]] = []
        close: list[dict[str, str]] = []
        seen: set[str] = set()
        for singer in singers:
            if not isinstance(singer, dict):
                continue
            singer_name = (
                singer.get("singerName")
                or singer.get("name")
                or singer.get("title")
                or ""
            ).strip()
            if not singer_name:
                continue
            mid = (
                singer.get("singerMID")
                or singer.get("singer_mid")
                or singer.get("mid")
            )
            url = _qq_artist_url(str(mid) if mid else None)
            if not url or url in seen:
                continue
            key = singer_name.casefold()
            if key != target and target not in key:
                continue
            seen.add(url)
            item = {"name": singer_name, "url": url}
            if key == target:
                exact.append(item)
            else:
                close.append(item)
        return exact + close

    @staticmethod
    def _title_confidence(query: str, result: str) -> float:
        q = (query or "").lower().strip()
        r = (result or "").lower().strip()
        if not q:
            return 0.5
        if q == r:
            return 1.0
        if q in r or r in q:
            return 0.8
        return 0.3
