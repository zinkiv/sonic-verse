"""Transfer inbox scan / filter / pagination tests."""

from pathlib import Path

from sonicverse.models import Track


async def test_settings_exposes_transfer_path(client):
    body = (await client.get("/api/v1/settings")).json()
    assert "transfer_path" in body
    assert body["transfer_path"]
    assert body["match_confidence_threshold"] == 100


async def test_scan_accepts_transfer_root(client, transfer_root: Path):
    response = await client.post(
        "/api/v1/scanner/scan",
        json={"root_path": str(transfer_root)},
    )
    assert response.status_code == 201, response.text
    assert Path(response.json()["root_path"]).resolve() == transfer_root.resolve()


async def test_scan_rejects_outside_roots(client, tmp_path: Path):
    outsider = tmp_path / "elsewhere"
    outsider.mkdir()
    response = await client.post(
        "/api/v1/scanner/scan",
        json={"root_path": str(outsider)},
    )
    assert response.status_code == 400


async def test_transfer_issue_filter_and_pagination(client, session, transfer_root: Path):
    tracks = []
    for index in range(5):
        path = transfer_root / f"song-{index}.flac"
        path.write_bytes(b"fLaC")
        tracks.append(
            Track(
                title=f"中转曲目{index}",
                track_number=index + 1,
                file_path=str(path),
            )
        )
    # One track outside transfer should not appear in transfer filter.
    session.add(
        Track(
            title="正式库曲目",
            track_number=99,
            file_path="/music/library-only.flac",
        )
    )
    session.add_all(tracks)
    await session.commit()

    page1 = (
        await client.get(
            "/api/v1/tracks",
            params={"issue": "transfer", "page": 1, "page_size": 2},
        )
    ).json()
    page2 = (
        await client.get(
            "/api/v1/tracks",
            params={"issue": "transfer", "page": 2, "page_size": 2},
        )
    ).json()
    page3 = (
        await client.get(
            "/api/v1/tracks",
            params={"issue": "transfer", "page": 3, "page_size": 2},
        )
    ).json()

    assert page1["total"] == 5
    assert page1["total_pages"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert len(page3["items"]) == 1

    ids = {item["id"] for item in page1["items"] + page2["items"] + page3["items"]}
    assert len(ids) == 5
    assert all("中转曲目" in item["title"] for item in page1["items"])

    stats = (await client.get("/api/v1/stats")).json()
    assert stats["transfer_pending"] == 5


async def test_library_lists_exclude_transfer_tracks(
    client, session, library, transfer_root: Path
):
    inbox = transfer_root / "pending.flac"
    inbox.write_bytes(b"fLaC")
    session.add(Track(title="中转待入库", file_path=str(inbox)))
    await session.commit()

    library_tracks = (await client.get("/api/v1/tracks")).json()
    assert library_tracks["total"] == 3
    assert all(item["title"] != "中转待入库" for item in library_tracks["items"])

    pending = (
        await client.get(
            "/api/v1/tracks",
            params={"issue": "transfer", "page_size": 20},
        )
    ).json()
    assert pending["total"] == 1
    assert pending["items"][0]["title"] == "中转待入库"

    stats = (await client.get("/api/v1/stats")).json()
    assert stats["total_tracks"] == 3
    assert stats["transfer_pending"] == 1


async def test_transfer_filter_matches_container_style_paths(client, session):
    """Rows stored as /transfer/... still show up in the pending queue."""
    session.add(
        Track(title="容器中转", file_path="/data/transfer/inbox/song.flac")
    )
    session.add(
        Track(title="正式库", file_path="/music/library.flac")
    )
    await session.commit()

    body = (
        await client.get(
            "/api/v1/tracks",
            params={"issue": "transfer", "page": 1, "page_size": 20},
        )
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "容器中转"

    stats = (await client.get("/api/v1/stats")).json()
    assert stats["transfer_pending"] == 1


async def test_missing_album_issue_filter_and_stats(client, session, transfer_root: Path):
    path = transfer_root / "no-album.flac"
    path.write_bytes(b"fLaC")
    session.add(
        Track(
            title="无专辑曲目",
            file_path=str(path),
            album_id=None,
            artist_id=None,
        )
    )
    await session.commit()

    body = (
        await client.get(
            "/api/v1/tracks",
            params={"issue": "missing_album", "page": 1, "page_size": 20},
        )
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "无专辑曲目"

    stats = (await client.get("/api/v1/stats")).json()
    assert stats["missing_albums"] >= 1
    assert stats["unknown_artists"] >= 1
    assert stats["transfer_pending"] >= 1


async def test_track_cover_file_source_reads_embedded(
    client, session, transfer_root: Path, library
):
    """Queue covers use embedded art (source=file), independent of /covers."""
    from unittest.mock import patch

    path = transfer_root / "with-art.flac"
    path.write_bytes(b"fLaCfake")
    track = library["tracks"][0]
    track.file_path = str(path)
    track.tag_title = "Departures"
    track.tag_artist = "EGOIST"
    track.tag_album = "FAN BEST"
    track.tag_has_cover = True
    await session.commit()

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with patch(
        "sonicverse.api.routes.tracks.MetadataReader.read_cover",
        return_value=png,
    ):
        response = await client.get(
            f"/api/v1/tracks/{track.id}/cover",
            params={"source": "file"},
        )

    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")

    track.tag_has_cover = False
    await session.commit()
    stats = (await client.get("/api/v1/stats")).json()
    assert stats["missing_covers"] >= 1


async def test_batch_match_scope_transfer_creates_job(client, session, transfer_root: Path):
    path = transfer_root / "a.flac"
    path.write_bytes(b"fLaC")
    track = Track(title="中转待整理", file_path=str(path))
    session.add(track)
    await session.commit()

    from unittest.mock import patch

    with patch("sonicverse.api.routes.matcher.start_match_job"):
        response = await client.post(
            "/api/v1/tracks/batch-match",
            json={"provider": "qqmusic", "scope": "transfer", "auto_apply": True},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["scope"] == "transfer"
    assert body["status"] == "pending"
