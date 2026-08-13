"""ensure_file_writable helpers."""

import os
import stat
from pathlib import Path

from sonicverse.core.fs import ensure_file_writable


def test_ensure_file_writable_adds_owner_write(tmp_path: Path):
    path = tmp_path / "song.flac"
    path.write_bytes(b"fLaC")
    path.chmod(0o444)
    assert not os.access(path, os.W_OK)

    ensure_file_writable(path)

    assert os.access(path, os.W_OK)
    assert path.stat().st_mode & stat.S_IWUSR


def test_ensure_file_writable_noop_when_already_writable(tmp_path: Path):
    path = tmp_path / "song.flac"
    path.write_bytes(b"fLaC")
    path.chmod(0o644)

    ensure_file_writable(path)

    assert os.access(path, os.W_OK)
