"""Stage library tracks from /music into /transfer before matching."""

from pathlib import Path
from unittest.mock import patch

from sonicverse.core.database import async_session_maker
from sonicverse.library.stage import stage_track_to_transfer
from sonicverse.models import Album, Artist, ProviderResult, Track
from sqlalchemy import select


async def test_stage_moves_music_file_into_transfer(
    session, library, music_root: Path, transfer_root: Path
):
    track = library["tracks"][0]
    source = music_root / "晴天.flac"
    source.write_bytes(b"fLaC")
    track.file_path = str(source)
    await session.commit()

    with patch("sonicverse.scanner.fingerprint.save_music_fingerprint"):
        destination = await stage_track_to_transfer(session, track)
        await session.commit()

    assert destination.parent.resolve() == transfer_root.resolve()
    assert destination.exists()
    assert not source.exists()
    assert track.file_path == str(destination)


async def test_stage_resets_match_metadata_and_orphans(
    session, library, music_root: Path, transfer_root: Path
):
    track = library["tracks"][0]
    album = library["album"]
    artist = library["artist"]
    album_id = album.id
    artist_id = artist.id

    # Leave this track as the only one on the album/artist.
    for other in library["tracks"][1:]:
        await session.delete(other)
    await session.flush()

    source = music_root / "solo.flac"
    source.write_bytes(b"fLaC")
    track.file_path = str(source)
    track.mbid = "ne:song:old"
    session.add(
        ProviderResult(
            track_id=track.id,
            provider="netease",
            provider_mbid="ne:song:old",
            confidence=0.9,
            metadata_json={"title": "old"},
            applied=True,
        )
    )
    await session.commit()

    with patch("sonicverse.scanner.fingerprint.save_music_fingerprint"):
        await stage_track_to_transfer(session, track)
        await session.commit()

    async with async_session_maker() as db:
        row = await db.get(Track, track.id)
        assert row is not None
        assert row.mbid is None
        assert Path(row.file_path).parent.resolve() == transfer_root.resolve()

        leftovers = (
            await db.execute(
                select(ProviderResult).where(ProviderResult.track_id == track.id)
            )
        ).scalars().all()
        assert leftovers == []

        assert await db.get(Album, album_id) is None
        assert await db.get(Artist, artist_id) is None


async def test_stage_is_noop_move_when_already_in_transfer(
    session, library, transfer_root: Path
):
    track = library["tracks"][0]
    source = transfer_root / "inbox.flac"
    source.write_bytes(b"fLaC")
    track.file_path = str(source)
    track.mbid = "local-confirmed"
    await session.commit()

    destination = await stage_track_to_transfer(session, track)
    await session.commit()

    assert destination == source.resolve() or destination == source
    assert source.exists()
    assert track.mbid is None


async def test_match_with_stage_moves_then_searches(
    client, session, library, music_root: Path, transfer_root: Path
):
    track = library["tracks"][1]
    source = music_root / "以父之名.flac"
    source.write_bytes(b"fLaC")
    track.file_path = str(source)
    track.mbid = "ne:song:keep"
    await session.commit()

    with (
        patch(
            "sonicverse.api.routes.matcher.search_and_store_candidates",
            return_value=[],
        ) as search,
        patch("sonicverse.scanner.fingerprint.save_music_fingerprint"),
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/match",
            json={"provider": "netease", "stage_to_transfer": True},
        )

    assert response.status_code == 200, response.text
    search.assert_called_once()
    assert not source.exists()

    async with async_session_maker() as db:
        row = await db.get(Track, track.id)
    assert row is not None
    staged = Path(row.file_path)
    assert staged.exists()
    assert staged.parent.resolve() == transfer_root.resolve()
    assert row.mbid is None

    listed = (
        await client.get("/api/v1/tracks", params={"issue": "transfer"})
    ).json()
    assert any(item["id"] == track.id for item in listed["items"])

    library_tracks = (await client.get("/api/v1/tracks")).json()
    assert all(item["id"] != track.id for item in library_tracks["items"])


async def test_match_without_stage_keeps_music_file(
    client, session, library, music_root: Path
):
    track = library["tracks"][2]
    source = music_root / "三年二班.flac"
    source.write_bytes(b"fLaC")
    track.file_path = str(source)
    await session.commit()

    with patch(
        "sonicverse.api.routes.matcher.search_and_store_candidates",
        return_value=[],
    ):
        response = await client.post(
            f"/api/v1/tracks/{track.id}/match",
            json={"provider": "netease"},
        )

    assert response.status_code == 200, response.text
    assert source.exists()
    async with async_session_maker() as db:
        row = await db.get(Track, track.id)
    assert row is not None
    assert Path(row.file_path) == source
