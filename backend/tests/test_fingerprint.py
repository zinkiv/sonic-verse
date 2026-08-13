"""Music/transfer library fingerprint and conditional sync tests."""

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from sonicverse.core.config import get_settings
from sonicverse.scanner.fingerprint import (
    compute_music_fingerprint,
    compute_transfer_fingerprint,
    fingerprint_path,
    load_stored_fingerprint,
    load_stored_transfer_fingerprint,
    music_library_changed,
    save_music_fingerprint,
    save_transfer_fingerprint,
    transfer_fingerprint_path,
    transfer_library_changed,
)
from sonicverse.scanner.pipeline import run_scan_job


@pytest.fixture(autouse=True)
def clean_music_and_fingerprint(music_root: Path):
    """Isolate fingerprint tests from leftover files across the suite."""
    for path in music_root.rglob("*"):
        if path.is_file():
            path.unlink(missing_ok=True)
    fp = fingerprint_path()
    legacy = Path(get_settings().data_path) / "music_library_fingerprint.json"
    fp.unlink(missing_ok=True)
    legacy.unlink(missing_ok=True)
    yield
    for path in music_root.rglob("*"):
        if path.is_file():
            path.unlink(missing_ok=True)
    fp.unlink(missing_ok=True)
    legacy.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def clean_transfer_fingerprint(transfer_root: Path):
    for path in transfer_root.rglob("*"):
        if path.is_file():
            path.unlink(missing_ok=True)
    transfer_fingerprint_path().unlink(missing_ok=True)
    yield
    for path in transfer_root.rglob("*"):
        if path.is_file():
            path.unlink(missing_ok=True)
    transfer_fingerprint_path().unlink(missing_ok=True)


def test_fingerprint_empty_directory(music_root: Path):
    snapshot = compute_music_fingerprint(music_root)
    assert snapshot.file_count == 0
    assert len(snapshot.fingerprint) == 64


def test_fingerprint_changes_when_file_added(music_root: Path):
    before = compute_music_fingerprint(music_root)
    song = music_root / "a.flac"
    song.write_bytes(b"fLaC")
    after = compute_music_fingerprint(music_root)
    assert after.file_count == 1
    assert after.fingerprint != before.fingerprint


def test_fingerprint_changes_when_mtime_changes(music_root: Path):
    song = music_root / "a.flac"
    song.write_bytes(b"fLaC")
    first = compute_music_fingerprint(music_root)

    import os
    import time

    later = time.time() + 10
    os.utime(song, (later, later))
    second = compute_music_fingerprint(music_root)
    assert second.fingerprint != first.fingerprint


def test_fingerprint_persist_roundtrip(music_root: Path):
    song = music_root / "b.mp3"
    song.write_bytes(b"ID3")
    saved = save_music_fingerprint(compute_music_fingerprint(music_root))
    loaded = load_stored_fingerprint()
    assert loaded is not None
    assert loaded.fingerprint == saved.fingerprint
    assert loaded.file_count == 1
    assert fingerprint_path().is_file()
    assert fingerprint_path().parent.name == "library"


def test_load_migrates_legacy_fingerprint(music_root: Path):
    (music_root / "legacy.flac").write_bytes(b"fLaC")
    snapshot = compute_music_fingerprint(music_root)
    legacy = Path(get_settings().data_path) / "music_library_fingerprint.json"
    legacy.write_text(
        '{"fingerprint": "%s", "file_count": 1}' % snapshot.fingerprint,
        encoding="utf-8",
    )

    loaded = load_stored_fingerprint()
    assert loaded is not None
    assert loaded.fingerprint == snapshot.fingerprint
    assert fingerprint_path().is_file()
    assert not legacy.is_file()


def test_music_library_changed_false_after_save(music_root: Path):
    (music_root / "c.flac").write_bytes(b"x")
    save_music_fingerprint(compute_music_fingerprint(music_root))
    changed, snapshot = music_library_changed(music_root)
    assert changed is False
    assert snapshot.file_count == 1


async def test_sync_music_skips_scan_when_unchanged(client, music_root: Path):
    (music_root / "keep.flac").write_bytes(b"fLaC")
    save_music_fingerprint(compute_music_fingerprint(music_root))

    with patch("sonicverse.api.routes.scanner.start_scan_job") as start:
        response = await client.post("/api/v1/scanner/sync-music")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is False
    assert body["job"] is None
    assert body["file_count"] == 1
    start.assert_not_called()


async def test_sync_music_starts_scan_when_changed(client, music_root: Path):
    (music_root / "new.flac").write_bytes(b"fLaC")

    with patch("sonicverse.api.routes.scanner.start_scan_job") as start:
        response = await client.post("/api/v1/scanner/sync-music")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["job"] is not None
    assert body["job"]["status"] == "pending"
    start.assert_called_once_with(body["job"]["id"])


async def test_scan_completion_persists_fingerprint(client, music_root: Path, monkeypatch):
    (music_root / "done.flac").write_bytes(b"fLaC")
    assert load_stored_fingerprint() is None

    with patch("sonicverse.api.routes.scanner.start_scan_job"):
        created = await client.post(
            "/api/v1/scanner/scan",
            json={"root_path": str(music_root)},
        )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    monkeypatch.setattr(
        "sonicverse.scanner.pipeline.MetadataReader.read",
        lambda *args, **kwargs: None,
    )
    await run_scan_job(job_id)

    stored = load_stored_fingerprint()
    assert stored is not None
    assert stored.file_count == 1

    with patch("sonicverse.api.routes.scanner.start_scan_job") as start:
        again = await client.post("/api/v1/scanner/sync-music")
    assert again.json()["changed"] is False
    start.assert_not_called()


async def test_rescan_skips_unchanged_files(client, music_root: Path, monkeypatch):
    from sonicverse.metadata.parser import AudioMetadata
    from sonicverse.models import Track
    from sonicverse.core.database import async_session_maker

    song = music_root / "keep.flac"
    song.write_bytes(b"fLaC")
    reads: list[str] = []

    def fake_read(path, include_cover=True):
        reads.append(str(path))
        return AudioMetadata(title="keep", artist="A", album="B", duration_ms=1000)

    monkeypatch.setattr("sonicverse.scanner.pipeline.MetadataReader.read", fake_read)
    monkeypatch.setattr(
        "sonicverse.scanner.pipeline.MetadataReader.read_cover",
        lambda path: None,
    )

    async def scan_once() -> None:
        with patch("sonicverse.api.routes.scanner.start_scan_job"):
            created = await client.post(
                "/api/v1/scanner/scan",
                json={"root_path": str(music_root)},
            )
        assert created.status_code == 201, created.text
        await run_scan_job(created.json()["id"])

    await scan_once()
    assert len(reads) == 1
    async with async_session_maker() as session:
        row = (
            await session.execute(select(Track).where(Track.title == "keep"))
        ).scalar_one()
        assert row.file_hash

    await scan_once()
    assert len(reads) == 1


def test_transfer_fingerprint_persist_roundtrip(transfer_root: Path):
    song = transfer_root / "inbox.flac"
    song.write_bytes(b"fLaC")
    saved = save_transfer_fingerprint(compute_transfer_fingerprint(transfer_root))
    loaded = load_stored_transfer_fingerprint()
    assert loaded is not None
    assert loaded.fingerprint == saved.fingerprint
    assert loaded.file_count == 1
    assert transfer_fingerprint_path().is_file()


def test_transfer_library_changed_false_after_save(transfer_root: Path):
    (transfer_root / "pending.flac").write_bytes(b"x")
    save_transfer_fingerprint(compute_transfer_fingerprint(transfer_root))
    changed, snapshot = transfer_library_changed(transfer_root)
    assert changed is False
    assert snapshot.file_count == 1


async def test_sync_transfer_skips_scan_when_unchanged(client, transfer_root: Path):
    (transfer_root / "keep.flac").write_bytes(b"fLaC")
    save_transfer_fingerprint(compute_transfer_fingerprint(transfer_root))

    with patch("sonicverse.api.routes.scanner.start_scan_job") as start:
        response = await client.post("/api/v1/scanner/sync-transfer")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is False
    assert body["job"] is None
    assert body["file_count"] == 1
    start.assert_not_called()


async def test_sync_transfer_starts_scan_when_changed(client, transfer_root: Path):
    (transfer_root / "new.flac").write_bytes(b"fLaC")

    with patch("sonicverse.api.routes.scanner.start_scan_job") as start:
        response = await client.post("/api/v1/scanner/sync-transfer")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["job"] is not None
    assert body["job"]["status"] == "pending"
    start.assert_called_once_with(body["job"]["id"])


async def test_transfer_scan_completion_persists_fingerprint(
    client, transfer_root: Path, monkeypatch
):
    (transfer_root / "done.flac").write_bytes(b"fLaC")
    assert load_stored_transfer_fingerprint() is None

    with patch("sonicverse.api.routes.scanner.start_scan_job"):
        created = await client.post(
            "/api/v1/scanner/scan",
            json={"root_path": str(transfer_root)},
        )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    monkeypatch.setattr(
        "sonicverse.scanner.pipeline.MetadataReader.read",
        lambda *args, **kwargs: None,
    )
    await run_scan_job(job_id)

    stored = load_stored_transfer_fingerprint()
    assert stored is not None
    assert stored.file_count == 1

    with patch("sonicverse.api.routes.scanner.start_scan_job") as start:
        again = await client.post("/api/v1/scanner/sync-transfer")
    assert again.json()["changed"] is False
    start.assert_not_called()
