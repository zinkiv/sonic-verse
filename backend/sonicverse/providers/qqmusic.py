"""QQ Music metadata provider (unofficial public search endpoints)."""

from __future__ import annotations

import logging
from typing import Optional

from sonicverse.core.http import http_client
from sonicverse.providers.base import AlbumResult, BaseProvider, TrackResult
from sonicverse.providers.queries import merge_query_searches

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
            artist_name = ",".join(
                s.get("name", "") for s in singers if isinstance(s, dict) and s.get("name")
            ) or "Unknown Artist"
            artist_images: list[dict[str, str]] = []
            for singer in singers:
                if not isinstance(singer, dict):
                    continue
                singer_name = (singer.get("name") or "").strip()
                singermid = singer.get("mid") or singer.get("singerMID")
                avatar = _qq_artist_url(str(singermid) if singermid else None)
                if singer_name and avatar:
                    artist_images.append({"name": singer_name, "url": avatar})
            album_name = song.get("albumname") or ""
            albummid = song.get("albummid") or ""
            song_title = song.get("songname") or song.get("title") or ""
            interval = song.get("interval") or 0
            try:
                interval = int(interval)
            except (TypeError, ValueError):
                interval = 0

            results.append(
                TrackResult(
                    title=song_title,
                    artist=artist_name,
                    album=album_name,
                    duration=interval,
                    mbid=_encode_id("song", str(songmid)),
                    confidence=self._title_confidence(title_hint, song_title),
                    album_mbid=_encode_id("album", str(albummid)) if albummid else None,
                    year=None,
                    cover_url=_qq_cover_url(albummid),
                    artist_image_url=artist_images[0]["url"] if artist_images else None,
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
                    year=None,
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
