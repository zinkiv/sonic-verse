"""Manual metadata save (no provider match) → library import."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sonicverse.core.database import async_session_maker
from sonicverse.models import Album, Track


class _Meta:
    def __init__(self, title: str, cover_data=None):
        self.title = title
        self.duration_ms = 200_000
        self.cover_data = cover_data
        self.artist = None
        self.album = None
        self.album_artist = None
        self.year = None
        self.track_number = None
        self.disc_number = None


@pytest.fixture
async def transfer_track(session, library, transfer_root: Path):
    track = library["tracks"][0]
    source = transfer_root / "manual-inbox" / "raw.flac"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fLaC")
    track.file_path = str(source)
    track.tag_title = "原标题"
    track.tag_artist = "原歌手"
    track.tag_album = "原专辑"
    track.tag_has_cover = False
    await session.commit()
    return track


async def test_manual_save_without_cover(
    client, transfer_track, transfer_root: Path, music_root: Path
):
    track = transfer_track
    source = Path(track.file_path)

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("手改标题"),
        ),
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/manual-save",
            data={
                "title": "手改标题",
                "artist": "手改歌手",
                "album": "手改专辑",
                "year": "2024",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "手改标题"
    assert body["mbid"] == f"manual:{track.id}"

    destination = music_root / "手改歌手-手改标题.flac"
    assert destination.exists()
    assert not source.exists()

    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        assert row.file_path == str(destination)
        assert row.mbid == f"manual:{track.id}"
        album = await s.get(Album, row.album_id)
        assert album is not None
        assert album.title == "手改专辑"
        assert album.year == 2024
        assert album.cover_path is None


async def test_manual_save_keeps_comma_in_artist_name(
    client, transfer_track, music_root: Path
):
    track = transfer_track
    band = "Fear,and Loathing in Las Vegas"

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("Let Me Hear"),
        ),
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/manual-save",
            data={
                "title": "Let Me Hear",
                "artist": band,
                "artist_names": json.dumps([band]),
                "album": "Feeling of Unity",
            },
        )

    assert response.status_code == 200, response.text
    async with async_session_maker() as s:
        from sonicverse.models import Artist

        row = await s.get(Track, track.id)
        assert row is not None
        await s.refresh(row, attribute_names=["artists"])
        assert [artist.name for artist in row.artists] == [band]
        primary = await s.get(Artist, row.artist_id)
        assert primary is not None
        assert primary.name == band


async def test_manual_save_keeps_ampersand_in_artist_name(
    client, transfer_track, music_root: Path
):
    track = transfer_track
    band = "MYTH & ROID"

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("HYDRA"),
        ),
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/manual-save",
            data={
                "title": "HYDRA",
                "artist": band,
                "artist_names": json.dumps([band]),
                "album": "Overlord II ED",
            },
        )

    assert response.status_code == 200, response.text
    async with async_session_maker() as s:
        from sonicverse.models import Artist

        row = await s.get(Track, track.id)
        assert row is not None
        await s.refresh(row, attribute_names=["artist", "artists"])
        assert [artist.name for artist in row.artists] == [band]
        assert row.artist is not None
        assert row.artist.name == band


async def test_manual_save_with_cover_upload(
    client, transfer_track, transfer_root: Path, music_root: Path
):
    track = transfer_track
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("有封面", cover_data=png),
        ),
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/manual-save",
            data={
                "title": "有封面",
                "artist": "封面歌手",
                "album": "封面专辑",
            },
            files={"cover": ("cover.png", png, "image/png")},
        )

    assert response.status_code == 200, response.text
    destination = music_root / "封面歌手-有封面.flac"
    assert destination.exists()

    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        album = await s.get(Album, row.album_id)
        assert album is not None
        assert album.cover_path is not None
        assert album.cover_path.startswith("/covers/")
        cover_name = album.cover_path.split("?", 1)[0].rsplit("/", 1)[-1]
        from sonicverse.core.config import get_settings

        cover_file = Path(get_settings().covers_path) / cover_name
        assert cover_file.exists()
        assert cover_file.read_bytes().startswith(b"\x89PNG")


async def test_manual_save_rejects_non_image(client, transfer_track):
    response = await client.post(
        f"/api/v1/tracks/{transfer_track.id}/manual-save",
        data={"title": "x", "artist": "y", "album": "z"},
        files={"cover": ("cover.bin", b"not-an-image", "application/octet-stream")},
    )
    assert response.status_code == 400


async def test_manual_save_cover_source_file(
    client, transfer_track, music_root: Path
):
    track = transfer_track
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("文件封面", cover_data=png),
        ),
        patch(
            "sonicverse.api.routes.matcher.MetadataReader.read_cover",
            return_value=png,
        ),
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/manual-save",
            data={
                "title": "文件封面",
                "artist": "文件歌手",
                "album": "文件专辑",
                "cover_source": "file",
            },
        )

    assert response.status_code == 200, response.text
    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        album = await s.get(Album, row.album_id)
        assert album is not None
        assert album.cover_path is not None


async def test_manual_save_refreshes_multi_artist_avatars(
    client, transfer_track, music_root: Path
):
    track = transfer_track
    images = [
        {"name": "甲", "url": "https://example.com/a.jpg"},
        {"name": "乙", "url": "https://example.com/b.jpg"},
    ]

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("合唱"),
        ),
        patch(
            "sonicverse.matcher.apply._download_image",
            new_callable=AsyncMock,
            side_effect=[b"\xff\xd8\xff" + b"a" * 20, b"\xff\xd8\xff" + b"b" * 20],
        ) as download,
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/manual-save",
            data={
                "title": "合唱",
                "artist": "甲,乙",
                "album": "合辑",
                "artist_image_url": images[0]["url"],
                "artist_images": json.dumps(images),
            },
        )

    assert response.status_code == 200, response.text
    assert download.await_count == 2

    async with async_session_maker() as s:
        from sonicverse.models import Artist

        row = await s.get(Track, track.id)
        assert row is not None
        await s.refresh(row, attribute_names=["artists"])
        assert {a.name for a in row.artists} == {"甲", "乙"}
        for artist in row.artists:
            loaded = await s.get(Artist, artist.id)
            assert loaded is not None
            assert loaded.avatar_path is not None
            assert loaded.avatar_path.startswith("/covers/")


async def test_manual_save_clears_cover(
    client, transfer_track, music_root: Path
):
    track = transfer_track

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True) as write_meta,
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("无封面", cover_data=None),
        ),
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/manual-save",
            data={
                "title": "无封面",
                "artist": "清空歌手",
                "album": "清空专辑",
                "cover_source": "none",
            },
        )

    assert response.status_code == 200, response.text
    written = write_meta.call_args.args[-1]
    assert written.clear_cover is True
    assert written.cover_data is None

    destination = music_root / "清空歌手-无封面.flac"
    assert destination.exists()

    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        album = await s.get(Album, row.album_id)
        assert album is not None
        assert album.cover_path is None
