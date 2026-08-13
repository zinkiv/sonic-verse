"""Path helpers for music library vs transfer staging roots."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from sonicverse.core.config import get_settings
from sonicverse.models import Track


def transfer_root() -> Path:
    return Path(get_settings().transfer_path).resolve()


def music_root() -> Path:
    return Path(get_settings().music_path).resolve()


def allowed_scan_roots() -> list[Path]:
    """Roots the unauthenticated scan API may walk."""
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in (music_root(), transfer_root()):
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique


def is_path_under(path: Path | str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def is_transfer_path(file_path: str | Path) -> bool:
    return is_path_under(file_path, transfer_root()) or path_matches_configured_root(
        file_path, get_settings().transfer_path
    )


def is_music_path(file_path: str | Path) -> bool:
    return is_path_under(file_path, music_root()) or path_matches_configured_root(
        file_path, get_settings().music_path
    )


def path_matches_configured_root(file_path: str | Path, configured: str) -> bool:
    """True when a stored path belongs to a configured root (string-level).

    Used when ``Path.resolve()`` cannot map Docker ``/music/...`` rows onto a
    host music root (or the reverse).
    """
    text = str(file_path).split("?", 1)[0]
    if not text:
        return False
    normalized = text.replace("\\", "/")
    for prefix in _prefix_variants(configured):
        prefix_norm = prefix.replace("\\", "/")
        if normalized == prefix_norm.rstrip("/") or normalized.startswith(
            prefix_norm if prefix_norm.endswith("/") else prefix_norm + "/"
        ):
            return True
        if text.startswith(prefix):
            return True
    folder = Path(configured).name
    if folder:
        token = f"/{folder}/"
        if token in normalized or normalized.startswith(f"{folder}/"):
            return True
    return False


def _prefix_variants(configured: str) -> list[str]:
    """String prefixes that may appear in Track.file_path for files under a root."""
    configured_path = Path(configured)
    bases = {
        str(configured_path),
        configured_path.as_posix(),
        str(configured_path.resolve()),
        configured_path.resolve().as_posix(),
    }
    prefixes: set[str] = set()
    for base in bases:
        if not base:
            continue
        prefixes.add(base)
        if not base.endswith(("/", "\\")):
            prefixes.add(base + "/")
            prefixes.add(base + "\\")
    return sorted(prefixes, key=len, reverse=True)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _root_file_path_filter(configured: str) -> ColumnElement[bool]:
    """Match tracks stored under a configured library root."""
    clauses: list[ColumnElement[bool]] = [
        Track.file_path.like(f"{_escape_like(prefix)}%", escape="\\")
        for prefix in _prefix_variants(configured)
    ]
    folder_name = Path(configured).name
    if folder_name:
        for needle in (f"/{folder_name}/", f"\\{folder_name}\\"):
            clauses.append(
                Track.file_path.like(f"%{_escape_like(needle)}%", escape="\\")
            )
    if not clauses:
        return Track.id.is_(None)
    return or_(*clauses)


def transfer_file_path_filter() -> ColumnElement[bool]:
    """SQLAlchemy filter: track.file_path lives under the transfer root."""
    return _root_file_path_filter(get_settings().transfer_path)


def music_file_path_filter() -> ColumnElement[bool]:
    """SQLAlchemy filter: track.file_path lives under the music library root."""
    return _root_file_path_filter(get_settings().music_path)
