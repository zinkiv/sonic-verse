"""API smoke tests over the real SQLAlchemy stack."""

from sqlalchemy import select, text

from sonicverse.api.routes import scanner as scanner_routes
from sonicverse.models import Track


async def test_health(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_stats_on_empty_library(client):
    response = await client.get("/api/v1/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_tracks": 0,
        "total_albums": 0,
        "total_artists": 0,
        "missing_covers": 0,
        "unknown_artists": 0,
        "missing_albums": 0,
        "pending_review": 0,
        "transfer_pending": 0,
    }


async def test_stats_counts_the_library(client, library):
    body = (await client.get("/api/v1/stats")).json()

    assert body["total_tracks"] == 3
    assert body["total_albums"] == 1
    assert body["total_artists"] == 1
    assert body["missing_covers"] == 0
    assert body["unknown_artists"] == 0
    assert body["missing_albums"] == 0
    assert body["pending_review"] == 3
    assert body["transfer_pending"] == 0


async def test_list_tracks_embeds_artist_and_album(client, library):
    body = (await client.get("/api/v1/tracks")).json()

    assert body["total"] == 3
    assert body["items"][0]["artist"]["name"] == "周杰伦"
    assert body["items"][0]["album"]["title"] == "叶惠美"


async def test_track_pagination_covers_every_row_exactly_once(client, library):
    page1 = (
        await client.get("/api/v1/tracks", params={"page": 1, "page_size": 2})
    ).json()
    page2 = (
        await client.get("/api/v1/tracks", params={"page": 2, "page_size": 2})
    ).json()

    assert page1["total_pages"] == 2
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1

    seen = {t["id"] for t in page1["items"]} | {t["id"] for t in page2["items"]}
    assert len(seen) == 3


async def test_track_search_matches_title(client, library):
    body = (await client.get("/api/v1/tracks", params={"search": "晴天"})).json()

    assert body["total"] == 1
    assert body["items"][0]["title"] == "晴天"


async def test_track_search_matches_artist_name(client, library):
    body = (await client.get("/api/v1/tracks", params={"search": "周杰伦"})).json()

    assert body["total"] == 3


async def test_get_unknown_track_returns_404(client, library):
    assert (await client.get("/api/v1/tracks/does-not-exist")).status_code == 404


async def test_update_track(client, library):
    track_id = library["tracks"][0].id

    response = await client.put(f"/api/v1/tracks/{track_id}", json={"title": "新标题"})

    assert response.status_code == 200
    assert response.json()["title"] == "新标题"


async def test_delete_track(client, library):
    track_id = library["tracks"][0].id

    assert (await client.delete(f"/api/v1/tracks/{track_id}")).status_code == 200
    assert (await client.get(f"/api/v1/tracks/{track_id}")).status_code == 404


async def test_list_albums(client, library):
    body = (await client.get("/api/v1/albums")).json()

    assert body["total"] == 1
    assert body["items"][0]["title"] == "叶惠美"
    assert body["items"][0]["track_count"] == 3


async def test_delete_album_removes_tracks_and_artist(client, library, music_root, session):
    album_id = library["album"].id
    artist_id = library["artist"].id
    track_paths = []
    for track in library["tracks"]:
        path = music_root / f"{track.title}.flac"
        path.write_bytes(b"fake-audio")
        track.file_path = str(path)
        track_paths.append(path)
    await session.commit()

    response = await client.delete(f"/api/v1/albums/{album_id}")

    assert response.status_code == 200
    assert response.json()["deleted_tracks"] == 3
    assert (await client.get(f"/api/v1/albums/{album_id}")).status_code == 404
    assert (await client.get("/api/v1/tracks")).json()["total"] == 0
    assert (await client.get(f"/api/v1/artists/{artist_id}")).status_code == 404
    assert all(not path.exists() for path in track_paths)


async def test_delete_track_updates_album_and_keeps_siblings(client, library):
    track_id = library["tracks"][0].id
    album_id = library["album"].id

    assert (await client.delete(f"/api/v1/tracks/{track_id}")).status_code == 200
    album = (await client.get(f"/api/v1/albums/{album_id}")).json()
    assert album["track_count"] == 2
    assert (await client.get("/api/v1/tracks")).json()["total"] == 2


async def test_list_artists(client, library):
    body = (await client.get("/api/v1/artists")).json()

    assert body["total"] == 1
    assert body["items"][0]["name"] == "周杰伦"


async def test_scan_rejects_a_root_outside_the_library(client, tmp_path, monkeypatch):
    started: list[str] = []
    monkeypatch.setattr(scanner_routes, "start_scan_job", started.append)

    response = await client.post(
        "/api/v1/scanner/scan", json={"root_path": str(tmp_path)}
    )

    assert response.status_code == 400
    assert started == []


async def test_scan_rejects_traversal_out_of_the_library(
    client, music_root, monkeypatch
):
    started: list[str] = []
    monkeypatch.setattr(scanner_routes, "start_scan_job", started.append)

    response = await client.post(
        "/api/v1/scanner/scan", json={"root_path": str(music_root / ".." / "escaped")}
    )

    assert response.status_code == 400
    assert started == []


async def test_scan_accepts_a_root_inside_the_library(client, music_root, monkeypatch):
    started: list[str] = []
    monkeypatch.setattr(scanner_routes, "start_scan_job", started.append)
    sub_directory = music_root / "周杰伦"
    sub_directory.mkdir(exist_ok=True)

    response = await client.post(
        "/api/v1/scanner/scan", json={"root_path": str(sub_directory)}
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert started == [response.json()["id"]]


async def test_foreign_keys_pragma_is_enabled(session):
    result = await session.execute(text("PRAGMA foreign_keys"))

    assert result.scalar() == 1


async def test_deleting_an_album_nulls_out_track_references(session, library):
    """Guards the ondelete= rules, which SQLite ignores unless the pragma is on."""
    await session.execute(
        text("DELETE FROM albums WHERE id = :id"), {"id": library["album"].id}
    )
    await session.commit()

    album_ids = (await session.execute(select(Track.album_id))).scalars().all()
    assert set(album_ids) == {None}
