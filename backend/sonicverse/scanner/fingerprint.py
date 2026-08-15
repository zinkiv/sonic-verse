"""Lightweight music-library fingerprint (paths + size + mtime, no tag reads)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sonicverse.core.config import get_settings
from sonicverse.core.paths import music_root, transfer_root
from sonicverse.scanner.scanner import AudioScanner

logger = logging.getLogger(__name__)

_MUSIC_FINGERPRINT_NAME = "music_library_fingerprint.json"
_TRANSFER_FINGERPRINT_NAME = "transfer_fingerprint.json"


@dataclass(frozen=True)
class LibraryFingerprint:
    fingerprint: str
    file_count: int


def fingerprint_path() -> Path:
    return get_settings().library_path / _MUSIC_FINGERPRINT_NAME


def transfer_fingerprint_path() -> Path:
    return get_settings().library_path / _TRANSFER_FINGERPRINT_NAME


def _legacy_fingerprint_path() -> Path:
    return Path(get_settings().data_path) / _MUSIC_FINGERPRINT_NAME


def _migrate_legacy_fingerprint() -> None:
    """Move the old /data/*.json snapshot into /data/library/ if needed."""
    dest = fingerprint_path()
    if dest.is_file():
        return
    src = _legacy_fingerprint_path()
    if not src.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dest)
    except OSError:
        logger.warning("Failed to migrate music fingerprint from %s to %s", src, dest, exc_info=True)


def compute_directory_fingerprint(root: Path) -> LibraryFingerprint:
    """Hash audio files under ``root`` by relative path, size, and mtime."""
    try:
        scan_root = Path(root).resolve()
    except OSError:
        scan_root = Path(root)
    entries: list[str] = []

    if scan_root.exists():
        for path in AudioScanner(str(scan_root)).scan():
            try:
                relative = path.relative_to(scan_root).as_posix()
            except ValueError:
                relative = path.name
            try:
                stat = path.stat()
                size = int(stat.st_size)
                mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
            except OSError:
                size = -1
                mtime_ns = -1
            entries.append(f"{relative}\0{size}\0{mtime_ns}")

    entries.sort()
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.encode("utf-8"))
        digest.update(b"\n")
    return LibraryFingerprint(fingerprint=digest.hexdigest(), file_count=len(entries))


def compute_music_fingerprint(root: Path | None = None) -> LibraryFingerprint:
    """Hash audio files under the music root by relative path, size, and mtime."""
    return compute_directory_fingerprint(Path(root) if root is not None else music_root())


def compute_transfer_fingerprint(root: Path | None = None) -> LibraryFingerprint:
    """Hash audio files under the transfer inbox."""
    return compute_directory_fingerprint(Path(root) if root is not None else transfer_root())


def _load_stored_fingerprint(path: Path) -> LibraryFingerprint | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fingerprint = payload.get("fingerprint")
        file_count = payload.get("file_count")
        if not isinstance(fingerprint, str) or not fingerprint:
            return None
        count = int(file_count) if file_count is not None else 0
        return LibraryFingerprint(fingerprint=fingerprint, file_count=count)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Failed to read fingerprint at %s", path, exc_info=True)
        return None


def _save_fingerprint(path: Path, snapshot: LibraryFingerprint) -> LibraryFingerprint:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": snapshot.fingerprint,
        "file_count": snapshot.file_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def load_stored_fingerprint() -> LibraryFingerprint | None:
    _migrate_legacy_fingerprint()
    return _load_stored_fingerprint(fingerprint_path())


def load_stored_transfer_fingerprint() -> LibraryFingerprint | None:
    return _load_stored_fingerprint(transfer_fingerprint_path())


def save_music_fingerprint(snapshot: LibraryFingerprint | None = None) -> LibraryFingerprint:
    """Persist the current (or provided) music-library fingerprint."""
    snapshot = snapshot or compute_music_fingerprint()
    path = fingerprint_path()
    legacy = _legacy_fingerprint_path()
    if legacy.is_file() and legacy.resolve() != path.resolve():
        legacy.unlink(missing_ok=True)
    return _save_fingerprint(path, snapshot)


def save_transfer_fingerprint(snapshot: LibraryFingerprint | None = None) -> LibraryFingerprint:
    """Persist the current (or provided) transfer inbox fingerprint."""
    snapshot = snapshot or compute_transfer_fingerprint()
    return _save_fingerprint(transfer_fingerprint_path(), snapshot)


def music_library_changed(root: Path | None = None) -> tuple[bool, LibraryFingerprint]:
    """Return whether the music tree differs from the last successful scan."""
    current = compute_music_fingerprint(root)
    stored = load_stored_fingerprint()
    if stored is None:
        return True, current
    return stored.fingerprint != current.fingerprint, current


def transfer_library_changed(root: Path | None = None) -> tuple[bool, LibraryFingerprint]:
    """Return whether the transfer inbox differs from the last successful scan."""
    current = compute_transfer_fingerprint(root)
    stored = load_stored_transfer_fingerprint()
    if stored is None:
        return True, current
    return stored.fingerprint != current.fingerprint, current
