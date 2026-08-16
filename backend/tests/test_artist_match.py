"""Artist avatar search / apply."""

from pathlib import Path
from unittest.mock import patch

from sonicverse.core.config import get_settings
from sonicverse.matcher.artist_match import _artist_name_matches, _looks_like_image
from sonicverse.providers.base import BaseProvider, TrackResult


class ImageProvider(BaseProvider):
    name = "qqmusic"

    async def search_track(self, title, artist, duration=None):
        return [
            TrackResult(
                title="晴天",
                artist=artist or "周杰伦",
                album="叶惠美",
                duration=200,
                mbid="qq:song:1",
                artist_image_url="https://img.example/from-track.jpg",
                artist_images=[
                    {"name": artist or "周杰伦", "url": "https://img.example/from-track.jpg"}
                ],
            )
        ]

    async def search_album(self, album, artist):
        return []

    async def get_cover(self, mbid):
        return None

    async def lookup_artist_images(self, artist_name: str):
        return [
            {"name": artist_name, "url": "https://img.example/jay.jpg"},
            {"name": artist_name, "url": "https://img.example/dead.jpg"},
            {"name": "王一博", "url": "https://img.example/unrelated.jpg"},
        ]


async def test_artist_match_returns_candidates_without_saving(client, library, session):
    artist = library["artist"]

    async def url_has_image(url: str) -> bool:
        return "dead" not in url

    with (
        patch(
            "sonicverse.matcher.artist_match.get_provider",
            return_value=ImageProvider(),
        ),
        patch(
            "sonicverse.matcher.artist_match._url_has_image",
            new=url_has_image,
        ),
    ):
        response = await client.post(f"/api/v1/artists/{artist.id}/match")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artist_id"] == artist.id
    names = {item["name"] for item in body["candidates"]}
    urls = [item["url"] for item in body["candidates"]]
    assert "王一博" not in names
    assert urls[0] == "https://img.example/jay.jpg"
    assert "https://img.example/from-track.jpg" in urls
    assert "https://img.example/unrelated.jpg" not in urls
    assert "https://img.example/dead.jpg" not in urls

    await session.refresh(artist)
    assert artist.avatar_path is None


async def test_artist_match_queries_qq_and_netease(client, library):
    calls: list[str] = []

    class QQ(ImageProvider):
        name = "qqmusic"

        async def lookup_artist_images(self, artist_name: str):
            calls.append("qqmusic")
            return [{"name": artist_name, "url": "https://img.example/qq.jpg"}]

        async def search_track(self, title, artist, duration=None):
            return []

    class Netease(ImageProvider):
        name = "netease"

        async def lookup_artist_images(self, artist_name: str):
            calls.append("netease")
            return [{"name": artist_name, "url": "https://img.example/ne.jpg"}]

        async def search_track(self, title, artist, duration=None):
            return []

    def get(name: str):
        return QQ() if name == "qqmusic" else Netease()

    async def url_has_image(url: str) -> bool:
        return True

    with (
        patch("sonicverse.matcher.artist_match.get_provider", side_effect=get),
        patch("sonicverse.matcher.artist_match._url_has_image", new=url_has_image),
    ):
        response = await client.post(f"/api/v1/artists/{library['artist'].id}/match")

    assert response.status_code == 200, response.text
    assert set(calls) == {"qqmusic", "netease"}
    urls = [item["url"] for item in response.json()["candidates"]]
    assert urls[0] == "https://img.example/qq.jpg"
    assert "https://img.example/ne.jpg" in urls


async def test_artist_match_drops_junk_tracks_and_placeholder_avatars(client, library):
    class Mixed(ImageProvider):
        name = "qqmusic"

        async def lookup_artist_images(self, artist_name: str):
            return [
                {
                    "name": artist_name,
                    "url": "https://p1.music.126.net/x/109951163799671647.jpg",
                }
            ]

        async def search_track(self, title, artist, duration=None):
            from sonicverse.providers.base import TrackResult

            return [
                TrackResult(
                    title="晴天哄睡节目电台",
                    artist=artist or "周杰伦",
                    album="杂",
                    duration=200,
                    mbid="qq:song:junk",
                    artist_images=[
                        {
                            "name": artist or "周杰伦",
                            "url": "https://img.example/from-junk.jpg",
                        }
                    ],
                ),
                TrackResult(
                    title="晴天",
                    artist=artist or "周杰伦",
                    album="叶惠美",
                    duration=200,
                    mbid="qq:song:ok",
                    artist_images=[
                        {
                            "name": artist or "周杰伦",
                            "url": "https://img.example/from-song.jpg",
                        }
                    ],
                ),
            ]

    async def url_has_image(url: str) -> bool:
        return True

    with (
        patch(
            "sonicverse.matcher.artist_match.get_provider",
            return_value=Mixed(),
        ),
        patch("sonicverse.matcher.artist_match._url_has_image", new=url_has_image),
    ):
        response = await client.post(
            f"/api/v1/artists/{library['artist'].id}/match",
            params={"provider": "qqmusic"},
        )

    assert response.status_code == 200, response.text
    urls = [item["url"] for item in response.json()["candidates"]]
    assert "https://img.example/from-song.jpg" in urls
    assert "https://img.example/from-junk.jpg" not in urls
    assert "109951163799671647" not in "".join(urls)


async def test_artist_avatar_from_url(client, library, session):
    artist = library["artist"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    with patch("sonicverse.matcher.artist_match._download_image", return_value=png):
        response = await client.post(
            f"/api/v1/artists/{artist.id}/avatar",
            data={"image_url": "https://img.example/jay.jpg"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["avatar_path"].startswith("/covers/")
    await session.refresh(artist)
    assert artist.avatar_path is not None


async def test_artist_avatar_from_upload(client, library):
    artist = library["artist"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    response = await client.post(
        f"/api/v1/artists/{artist.id}/avatar",
        files={"image": ("avatar.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text
    relative = response.json()["avatar_path"].split("?", 1)[0]
    filename = relative.rsplit("/", 1)[-1]
    stored = Path(get_settings().covers_path) / filename
    assert stored.is_file()
    assert stored.read_bytes().startswith(b"\x89PNG")


def test_artist_name_filter_keeps_self_and_drops_others():
    assert _artist_name_matches("程潇", "程潇")
    assert _artist_name_matches("程潇", "程潇 Xiao Cheng")
    assert _artist_name_matches(
        "Fear,and Loathing in Las Vegas",
        "Fear, and Loathing in Las Vegas",
    )
    assert not _artist_name_matches("程潇", "王一博")
    assert not _artist_name_matches("程潇", "王者荣耀")
    assert not _artist_name_matches("程潇", "")
    assert not _artist_name_matches("林", "林俊杰")


def test_looks_like_image_rejects_empty_and_html():
    jpeg = b"\xff\xd8\xff" + b"\x00" * 600
    assert _looks_like_image(jpeg)
    assert not _looks_like_image(b"")
    assert not _looks_like_image(b"<!DOCTYPE html>")
    assert not _looks_like_image(b"\xff\xd8\xff" + b"\x00" * 10)
