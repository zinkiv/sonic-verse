"""Batch match threshold routing and apply rollback tests."""

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from sonicverse.core.database import async_session_maker
from sonicverse.matcher.apply import ApplyError, ApplyPayload, apply_match_to_track
from sonicverse.matcher.batch import run_match_job
from sonicverse.models import MatchJob, MatchJobStatus, ProviderResult, Track
from dataclasses import replace

from sonicverse.providers.base import AlbumResult, BaseProvider, TrackResult


class FakeProvider(BaseProvider):
    name = "qqmusic"

    def __init__(self, by_title: dict[str, list[TrackResult]]):
        self.by_title = by_title

    async def search_track(self, title, artist, duration=None) -> list[TrackResult]:
        return [replace(item) for item in self.by_title.get(title, [])]

    async def search_album(self, album, artist) -> list[AlbumResult]:
        return []

    async def get_cover(self, mbid) -> bytes | None:
        return None


def _result(
    title: str,
    artist: str = "周杰伦",
    album: str = "叶惠美",
    *,
    mbid: str,
) -> TrackResult:
    return TrackResult(
        title=title,
        artist=artist,
        album=album,
        duration=200,
        mbid=mbid,
        album_mbid=f"album-{mbid}",
        year=2003,
        confidence=0.5,
    )


class _Meta:
    def __init__(self, title: str, duration_ms: int = 200_000, cover_data=None):
        self.title = title
        self.duration_ms = duration_ms
        self.cover_data = cover_data
        self.artist = None
        self.album = None
        self.album_artist = None
        self.year = None
        self.track_number = None
        self.disc_number = None


@pytest.fixture
async def audio_files(music_root: Path, library, session):
    """Point library tracks at real paths under the test music root."""
    for track in library["tracks"]:
        path = music_root / f"{track.title}.flac"
        path.write_bytes(b"fLaC")
        track.file_path = str(path)
    await session.commit()
    return library


async def _load_job(job_id: str) -> MatchJob:
    async with async_session_maker() as session:
        job = await session.get(MatchJob, job_id)
        assert job is not None
        # Detach values we care about before session closes.
        session.expunge(job)
        return job


async def test_batch_match_auto_applies_above_threshold(client, audio_files):
    high = audio_files["tracks"][0]  # 以父之名 — exact provider hit
    low = audio_files["tracks"][1]  # 晴天 — junk / unrelated hit

    provider = FakeProvider(
        {
            "以父之名": [_result("以父之名", mbid="qq:song:high")],
            # Junk title markers force score well below the auto-import threshold.
            "晴天": [_result("晴天哄睡节目电台", artist="未知", mbid="qq:song:low")],
        }
    )

    def read_meta(path: str):
        return _Meta(Path(path).stem)

    with (
        patch("sonicverse.matcher.batch.start_match_job"),
        patch("sonicverse.api.routes.matcher.start_match_job"),
        patch("sonicverse.matcher.matcher.get_provider", return_value=provider),
        patch("sonicverse.matcher.search.MetadataReader.read", side_effect=read_meta),
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch("sonicverse.matcher.apply.MetadataReader.read", side_effect=read_meta),
        patch("sonicverse.matcher.batch._PROVIDER_PAUSE_SEC", 0),
    ):
        # Re-patch create endpoint's start so POST only inserts the row.
        response = await client.post(
            "/api/v1/tracks/batch-match",
            json={
                "provider": "qqmusic",
                "threshold": 70,
                "auto_apply": True,
                "track_ids": [high.id, low.id],
            },
        )
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        await run_match_job(job_id)
        job = await _load_job(job_id)

    assert job.status == MatchJobStatus.COMPLETED.value
    assert job.auto_applied == 1
    assert job.needs_review == 1
    assert job.failed == 0
    assert job.unmatched == 0
    assert job.tracks_processed == 2

    async with async_session_maker() as s:
        high_row = await s.get(Track, high.id)
        low_row = await s.get(Track, low.id)
        assert high_row is not None and high_row.mbid == "qq:song:high"
        assert low_row is not None and low_row.mbid is None

        low_candidates = (
            await s.execute(
                select(ProviderResult).where(
                    ProviderResult.track_id == low.id,
                    ProviderResult.applied.is_(False),
                )
            )
        ).scalars().all()
        assert {row.provider_mbid for row in low_candidates} == {"qq:song:low"}


async def test_batch_match_write_failure_keeps_candidates_and_counts_failed(
    client, audio_files
):
    track = audio_files["tracks"][0]
    provider = FakeProvider(
        {"以父之名": [_result("以父之名", mbid="qq:song:fail")]}
    )

    def read_meta(path: str):
        return _Meta(Path(path).stem)

    with (
        patch("sonicverse.api.routes.matcher.start_match_job"),
        patch("sonicverse.matcher.matcher.get_provider", return_value=provider),
        patch("sonicverse.matcher.search.MetadataReader.read", side_effect=read_meta),
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=False),
        patch("sonicverse.matcher.batch._PROVIDER_PAUSE_SEC", 0),
    ):
        response = await client.post(
            "/api/v1/tracks/batch-match",
            json={
                "provider": "qqmusic",
                "threshold": 70,
                "auto_apply": True,
                "track_ids": [track.id],
            },
        )
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        await run_match_job(job_id)
        job = await _load_job(job_id)

    assert job.status == MatchJobStatus.COMPLETED.value
    assert job.auto_applied == 0
    assert job.failed == 1
    assert job.needs_review == 0
    assert job.tracks_processed == 1

    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        assert row.mbid is None
        assert row.title == "以父之名"

        candidates = (
            await s.execute(
                select(ProviderResult).where(ProviderResult.track_id == track.id)
            )
        ).scalars().all()
        assert candidates
        assert all(row.applied is False for row in candidates)
        assert {row.provider_mbid for row in candidates} == {"qq:song:fail"}


async def test_apply_match_rolls_back_db_when_tag_write_fails(session, audio_files):
    track = audio_files["tracks"][0]
    original_title = track.title
    track_id = track.id

    payload = ApplyPayload(
        title="新标题",
        artist="新歌手",
        album="新专辑",
        mbid="qq:song:x",
        album_mbid="qq:album:x",
        year=2020,
        provider="qqmusic",
        fetch_cover=False,
    )

    with patch(
        "sonicverse.matcher.apply.Tagger.write_metadata",
        return_value=False,
    ):
        with pytest.raises(ApplyError):
            await apply_match_to_track(session, track, payload)
        await session.rollback()

    async with async_session_maker() as s:
        row = await s.get(Track, track_id)
        assert row is not None
        assert row.title == original_title
        assert row.mbid is None


async def test_apply_imports_transfer_file_into_music(
    session, library, transfer_root: Path, music_root: Path
):
    track = library["tracks"][0]
    source = transfer_root / "inbox" / "raw.flac"
    source.parent.mkdir()
    source.write_bytes(b"fLaC")
    track.file_path = str(source)
    await session.commit()

    payload = ApplyPayload(
        title="千里之外",
        artist="周杰伦, 费玉清",
        album="依然范特西",
        mbid="qq:song:duet",
        fetch_cover=False,
        provider="qqmusic",
    )

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("千里之外"),
        ),
    ):
        await apply_match_to_track(session, track, payload)
        await session.commit()

    destination = music_root / "周杰伦,费玉清-千里之外.flac"
    assert destination.exists()
    assert not source.exists()
    assert not (transfer_root / "inbox").exists()

    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        assert row.file_path == str(destination)


async def test_apply_reuses_album_when_mbid_already_taken(
    session, library, music_root: Path
):
    """Regression: assigning album_mbid that another album already owns must not
    UniqueViolation on ix_albums_mbid (especially with cover_path in same flush).
    """
    from sonicverse.models import Album

    artist = library["artist"]
    owner = Album(title="七里香", artist_id=artist.id, year=2004, mbid="ne:album:3233528")
    session.add(owner)
    await session.flush()

    solo = Album(title="杂项", artist_id=artist.id)
    session.add(solo)
    await session.flush()

    path = music_root / "七里香.flac"
    path.write_bytes(b"fLaC")
    track = Track(
        title="七里香",
        artist_id=artist.id,
        album_id=solo.id,
        file_path=str(path),
        duration_ms=200_000,
    )
    session.add(track)
    await session.commit()
    await session.refresh(track)

    payload = ApplyPayload(
        title="七里香",
        artist="周杰伦",
        album="七里香",
        mbid="ne:song:7",
        album_mbid="ne:album:3233528",
        year=2004,
        fetch_cover=False,
        provider="netease",
    )
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("七里香"),
        ),
    ):
        await apply_match_to_track(session, track, payload, cover_data=png)
        await session.commit()

    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        assert row.album_id == owner.id
        album = await s.get(Album, owner.id)
        assert album is not None
        assert album.mbid == "ne:album:3233528"
        assert album.cover_path is not None
        orphan = await s.get(Album, solo.id)
        assert orphan is None


async def test_apply_overwrites_existing_library_file(
    session, library, transfer_root: Path, music_root: Path
):
    track = library["tracks"][0]
    source = transfer_root / "incoming.flac"
    source.write_bytes(b"new-audio")
    track.file_path = str(source)

    existing = music_root / "周杰伦-晴天.flac"
    existing.write_bytes(b"old-audio")
    await session.commit()

    payload = ApplyPayload(
        title="晴天",
        artist="周杰伦",
        album="叶惠美",
        mbid="qq:song:overwrite",
        fetch_cover=False,
        provider="qqmusic",
    )

    with (
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            return_value=_Meta("晴天"),
        ),
    ):
        await apply_match_to_track(session, track, payload)
        await session.commit()

    assert existing.read_bytes() == b"new-audio"
    assert not source.exists()
    assert not list(music_root.glob("周杰伦-晴天 (2).flac"))

    async with async_session_maker() as s:
        row = await s.get(Track, track.id)
        assert row is not None
        assert row.file_path == str(existing)


async def test_batch_match_imports_high_score_transfer_tracks(
    client, session, library, transfer_root: Path, music_root: Path
):
    high = library["tracks"][0]
    low = library["tracks"][1]
    for leftover in music_root.glob("周杰伦-以父之名*.flac"):
        leftover.unlink()

    high_src = transfer_root / "high.flac"
    low_src = transfer_root / "low.flac"
    high_src.write_bytes(b"fLaC")
    low_src.write_bytes(b"fLaC")
    high.file_path = str(high_src)
    low.file_path = str(low_src)
    await session.commit()

    provider = FakeProvider(
        {
            "以父之名": [_result("以父之名", mbid="qq:song:high")],
            "晴天": [_result("晴天哄睡节目电台", artist="未知", mbid="qq:song:low")],
        }
    )

    with (
        patch("sonicverse.api.routes.matcher.start_match_job"),
        patch("sonicverse.matcher.matcher.get_provider", return_value=provider),
        patch(
            "sonicverse.matcher.search.MetadataReader.read",
            side_effect=lambda path: _Meta(Path(path).stem),
        ),
        patch("sonicverse.matcher.apply.Tagger.write_metadata", return_value=True),
        patch(
            "sonicverse.matcher.apply.MetadataReader.read",
            side_effect=lambda path: _Meta("以父之名"),
        ),
        patch("sonicverse.matcher.batch._PROVIDER_PAUSE_SEC", 0),
    ):
        response = await client.post(
            "/api/v1/tracks/batch-match",
            json={
                "provider": "qqmusic",
                "scope": "transfer",
                "auto_apply": True,
                "threshold": 80,
            },
        )
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        assert response.json()["threshold"] == 80
        assert response.json()["scope"] == "transfer"
        await run_match_job(job_id)
        job = await _load_job(job_id)

    assert job.status == MatchJobStatus.COMPLETED.value
    assert job.auto_applied == 1
    assert job.needs_review == 1
    assert job.tracks_processed == 2
    imported = music_root / "周杰伦-以父之名.flac"
    assert imported.exists()
    assert not high_src.exists()
    assert low_src.exists()

    async with async_session_maker() as s:
        high_row = await s.get(Track, high.id)
        low_row = await s.get(Track, low.id)
        assert high_row is not None and high_row.file_path == str(imported)
        assert low_row is not None and low_row.file_path == str(low_src)


async def test_get_stored_candidates_and_confirm_local(client, session, library):
    track = library["tracks"][0]
    session.add(
        ProviderResult(
            track_id=track.id,
            provider="qqmusic",
            provider_mbid="qq:song:1",
            confidence=0.55,
            metadata_json={
                "title": "以父之名",
                "artist": "周杰伦",
                "album": "叶惠美",
                "mbid": "qq:song:1",
                "score": 55,
                "confidence": 55,
                "provider": "qqmusic",
                "duration": 200,
            },
            applied=False,
        )
    )
    await session.commit()

    body = (await client.get(f"/api/v1/tracks/{track.id}/candidates")).json()
    assert body["track_id"] == track.id
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["mbid"] == "qq:song:1"

    confirmed = await client.post(f"/api/v1/tracks/{track.id}/confirm-local")
    assert confirmed.status_code == 200
    assert confirmed.json()["mbid"] == "local-confirmed"

    stats = (await client.get("/api/v1/stats")).json()
    assert stats["pending_review"] == 2
