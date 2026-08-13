"""Scan reconcile: missing files under the scan root are dropped from the library."""

from pathlib import Path

from sqlalchemy import func, select

from sonicverse.library.delete import clear_library_catalog
from sonicverse.models import Album, Artist, Track
from sonicverse.scanner.pipeline import (
    _is_full_music_library_scan,
    prune_tracks_absent_from_scan,
)


async def test_empty_scan_clears_tracks_under_root(session, library, music_root: Path):
    for track in library["tracks"]:
        track.file_path = str(music_root / f"{track.title}.flac")
    await session.commit()

    removed = await prune_tracks_absent_from_scan(session, music_root, [])
    await session.commit()

    assert removed == 3
    assert (await session.scalar(select(func.count(Track.id)))) == 0
    assert (await session.scalar(select(func.count(Album.id)))) == 0
    assert (await session.scalar(select(func.count(Artist.id)))) == 0


async def test_scan_keeps_files_still_on_disk(session, library, music_root: Path):
    kept = music_root / "晴天.flac"
    kept.write_bytes(b"fake")
    for track in library["tracks"]:
        track.file_path = str(music_root / f"{track.title}.flac")
    await session.commit()

    removed = await prune_tracks_absent_from_scan(session, music_root, [kept])
    await session.commit()

    titles = set((await session.execute(select(Track.title))).scalars().all())
    assert removed == 2
    assert titles == {"晴天"}


async def test_scan_does_not_touch_tracks_outside_root(
    session, library, music_root: Path, transfer_root: Path
):
    outside = library["tracks"][0]
    outside.file_path = str(transfer_root / "inbox.flac")
    for track in library["tracks"][1:]:
        track.file_path = str(music_root / f"{track.title}.flac")
    await session.commit()

    await prune_tracks_absent_from_scan(session, music_root, [])
    await session.commit()

    remaining = (await session.execute(select(Track.title))).scalars().all()
    assert remaining == [outside.title]


async def test_empty_music_root_scan_wipes_catalog_with_mismatched_paths(
    session, library, music_root: Path
):
    """Settings scan of an empty library must clear homepage rows even when
    stored file_path values (e.g. Docker /music/…) are not under this host's
    music root — prune-by-prefix would otherwise leave them behind.
    """
    assert not _is_full_music_library_scan(Path("/not-the-library"))
    assert _is_full_music_library_scan(music_root)

    removed = await clear_library_catalog(session)
    await session.commit()

    assert removed == 3
    assert (await session.scalar(select(func.count(Track.id)))) == 0
    assert (await session.scalar(select(func.count(Album.id)))) == 0
    assert (await session.scalar(select(func.count(Artist.id)))) == 0


async def test_music_scan_prunes_docker_style_paths_when_empty(
    session, library, music_root: Path
):
    """Empty /music scan drops rows stored as /music/... even if resolve differs."""
    for track in library["tracks"]:
        track.file_path = f"/music/{track.title}.flac"
    await session.commit()

    removed = await prune_tracks_absent_from_scan(session, music_root, [])
    await session.commit()

    assert removed == 3
    assert (await session.scalar(select(func.count(Track.id)))) == 0


async def test_clear_library_catalog_keeps_transfer_tracks(
    session, library, transfer_root: Path
):
    inbox = library["tracks"][0]
    inbox.file_path = str(transfer_root / "inbox.flac")
    (transfer_root / "inbox.flac").write_bytes(b"fLaC")
    await session.commit()

    removed = await clear_library_catalog(session)
    await session.commit()

    remaining = list((await session.execute(select(Track))).scalars().all())
    assert removed == 2
    assert [track.id for track in remaining] == [inbox.id]
