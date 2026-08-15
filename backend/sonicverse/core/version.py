"""Resolve the running app version (prefer image/git tag)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _read_version_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


@lru_cache
def resolve_app_version() -> str:
    """Return APP_VERSION env, then baked ``/app/VERSION``, else ``dev``.

    Docker builds should pass ``--build-arg APP_VERSION=$(git describe --tags --always)``.
    """
    env = (os.environ.get("APP_VERSION") or "").strip()
    if env:
        return env

    for candidate in (
        Path("/app/VERSION"),
        Path(__file__).resolve().parents[2] / "VERSION",
        Path.cwd() / "VERSION",
    ):
        value = _read_version_file(candidate)
        if value:
            return value

    return "dev"
