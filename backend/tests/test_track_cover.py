"""Track cover endpoint and stale cover-path repair."""

from pathlib import Path

from sonicverse.core.config import get_settings
from sonicverse.models import Album, Track


async def test_track_cover_reads_embedded_art(client, session, transfer_root: Path):
    # Minimal JPEG (1x1) so media-type sniffing succeeds.
    jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    audio = transfer_root / "cover-song.flac"
    audio.write_bytes(b"fLaC")

    album = Album(title="Cover Album", cover_path="/covers/missing-file.png")
    session.add(album)
    await session.flush()
    track = Track(
        title="Cover Song",
        file_path=str(audio),
        album_id=album.id,
    )
    session.add(track)
    await session.commit()

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "sonicverse.api.routes.tracks.MetadataReader.read_cover",
        return_value=jpeg,
    ):
        response = await client.get(f"/api/v1/tracks/{track.id}/cover")

    assert response.status_code == 200
    assert response.content.startswith(b"\xff\xd8")
    assert response.headers["content-type"].startswith("image/")

    # Stale cover_path should be cleared so missing-cover stats can see it.
    await session.refresh(album)
    assert album.cover_path is None


async def test_stats_clear_stale_cover_paths(client, session, transfer_root: Path):
    audio = transfer_root / "stale-cover.flac"
    audio.write_bytes(b"fLaC")
    album = Album(title="Stale", cover_path="/covers/does-not-exist.png")
    session.add(album)
    await session.flush()
    session.add(
        Track(title="Stale Track", file_path=str(audio), album_id=album.id)
    )
    await session.commit()

    stats = (await client.get("/api/v1/stats")).json()
    assert stats["missing_covers"] >= 1

    await session.refresh(album)
    assert album.cover_path is None


async def test_track_cover_serves_saved_file(client, session, library, tmp_path: Path):
    settings = get_settings()
    covers = Path(settings.covers_path)
    covers.mkdir(parents=True, exist_ok=True)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    track = library["tracks"][0]
    album = library["album"]
    file_name = f"{album.id}.png"
    (covers / file_name).write_bytes(png)
    album.cover_path = f"/covers/{file_name}"
    await session.commit()

    response = await client.get(f"/api/v1/tracks/{track.id}/cover")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


async def test_track_cover_file_source_ignores_album_art(client, session, transfer_root: Path):
    jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    audio = transfer_root / "own-cover.flac"
    audio.write_bytes(b"fLaC")

    settings = get_settings()
    covers = Path(settings.covers_path)
    covers.mkdir(parents=True, exist_ok=True)
    file_name = "album-cover.png"
    (covers / file_name).write_bytes(png)

    album = Album(title="Shared Album", cover_path=f"/covers/{file_name}")
    session.add(album)
    await session.flush()
    track = Track(title="Own Cover", file_path=str(audio), album_id=album.id)
    session.add(track)
    await session.commit()

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "sonicverse.api.routes.tracks.MetadataReader.read_cover",
        return_value=jpeg,
    ):
        embedded = await client.get(f"/api/v1/tracks/{track.id}/cover?source=file")
        album_art = await client.get(f"/api/v1/tracks/{track.id}/cover?source=album")

    assert embedded.status_code == 200
    assert embedded.content.startswith(b"\xff\xd8")
    assert album_art.status_code == 200
    assert album_art.content.startswith(b"\x89PNG")
