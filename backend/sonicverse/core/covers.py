"""Album cover path helpers (URL path ↔ filesystem)."""

from __future__ import annotations

from pathlib import Path

from sonicverse.core.config import get_settings


def cover_filename(cover_path: str | None) -> str | None:
    """Extract the filename from a stored ``/covers/…`` URL path."""
    if not cover_path or not cover_path.startswith("/covers/"):
        return None
    name = Path(cover_path.split("?", 1)[0]).name
    return name or None


def cover_filesystem_path(cover_path: str | None) -> Path | None:
    """Absolute path of a stored cover file, if the URL looks valid."""
    name = cover_filename(cover_path)
    if not name:
        return None
    return Path(get_settings().covers_path) / name


def cover_file_exists(cover_path: str | None) -> bool:
    path = cover_filesystem_path(cover_path)
    return bool(path and path.is_file())


def detect_cover_media_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"
