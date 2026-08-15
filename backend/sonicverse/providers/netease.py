"""NetEase Cloud Music metadata provider (unofficial public endpoints)."""

from __future__ import annotations

import logging
from typing import Optional

from sonicverse.core.http import http_client
from sonicverse.providers.base import AlbumResult, BaseProvider, TrackResult
from sonicverse.providers.queries import merge_query_searches
from sonicverse.providers.year import parse_release_year

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://music.163.com/api/cloudsearch/pc"
_SONG_DETAIL_URL = "https://music.163.com/api/song/detail"
_HEADERS = {
    "Referer": "https://music.163.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _encode_id(kind: str, value: str | int) -> str:
    return f"ne:{kind}:{value}"


def _decode_song_id(value: str) -> str | None:
    if value.startswith("ne:song:"):
        return value.removeprefix("ne:song:")
    if value.startswith("ne:"):
        return value.split(":", 1)[1]
    return value or None


class NeteaseProvider(BaseProvider):
    """Search NetEase Cloud Music and fetch covers from album artwork URLs."""

    name = "netease"

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
            response = await http_client().post(
                _SEARCH_URL,
                data={
                    "s": query,
                    "type": 1,
                    "limit": 30,
                    "offset": 0,
                },
                headers=_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.warning("NetEase search failed: %s", query, exc_info=True)
            return []

        songs = ((payload.get("result") or {}).get("songs") or [])
        results: list[TrackResult] = []
        for song in songs:
            song_id = song.get("id")
            if song_id is None:
                continue
            artists = song.get("artists") or song.get("ar") or []
            artist_name = ",".join(
                a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")
            ) or "Unknown Artist"
            artist_images: list[dict[str, str]] = []
            for person in artists:
                if not isinstance(person, dict):
                    continue
                person_name = (person.get("name") or "").strip()
                avatar = person.get("img1v1Url") or person.get("picUrl")
                if person_name and avatar:
                    artist_images.append({"name": person_name, "url": str(avatar)})
            album = song.get("album") or song.get("al") or {}
            album_name = album.get("name") or ""
            album_id = album.get("id")
            pic_url = album.get("picUrl") or album.get("pic_url")
            song_title = song.get("name") or ""
            duration_ms = song.get("duration") or song.get("dt") or 0
            try:
                duration_sec = int(duration_ms) // 1000
            except (TypeError, ValueError):
                duration_sec = 0

            results.append(
                TrackResult(
                    title=song_title,
                    artist=artist_name,
                    album=album_name,
                    duration=duration_sec,
                    mbid=_encode_id("song", song_id),
                    confidence=self._title_confidence(title_hint, song_title),
                    album_mbid=_encode_id("album", album_id) if album_id is not None else None,
                    year=parse_release_year(
                        song.get("publishTime"),
                        song.get("publish_time"),
                        album,
                    ),
                    cover_url=pic_url,
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
            response = await http_client().post(
                _SEARCH_URL,
                data={"s": query, "type": 10, "limit": 10, "offset": 0},
                headers=_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.warning("NetEase album search failed: %s", query, exc_info=True)
            return []

        albums = ((payload.get("result") or {}).get("albums") or [])
        results: list[AlbumResult] = []
        for item in albums:
            album_id = item.get("id")
            if album_id is None:
                continue
            artist_obj = item.get("artist") or {}
            results.append(
                AlbumResult(
                    title=item.get("name") or "",
                    artist=artist_obj.get("name") or "",
                    year=parse_release_year(
                        item.get("publishTime"),
                        item.get("publish_time"),
                        item.get("pubTime"),
                    ),
                    mbid=_encode_id("album", album_id),
                    cover_url=item.get("picUrl"),
                )
            )
        return results

    async def get_cover(self, mbid: str) -> Optional[bytes]:
        """Resolve cover via song detail when mbid is a song id; album ids unsupported here."""
        song_id = _decode_song_id(mbid)
        if not song_id:
            return None
        try:
            client = http_client()
            response = await client.get(
                _SONG_DETAIL_URL,
                params={"ids": f"[{song_id}]"},
                headers=_HEADERS,
            )
            response.raise_for_status()
            songs = (response.json().get("songs") or [])
            if not songs:
                return None
            album = songs[0].get("album") or {}
            pic_url = album.get("picUrl")
            if not pic_url:
                return None
            cover = await client.get(pic_url, headers=_HEADERS)
            if cover.status_code == 200 and cover.content:
                return cover.content
        except Exception:
            logger.warning("NetEase cover fetch failed: %s", mbid, exc_info=True)
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
