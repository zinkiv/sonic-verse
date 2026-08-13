"""Persisted UI-editable settings (overrides env defaults)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from sonicverse.core.config import get_settings
from sonicverse.matcher.percent import (
    MATCH_THRESHOLD_DEFAULT,
    MATCH_THRESHOLD_MAX,
    MATCH_THRESHOLD_MIN,
    clamp_match_threshold,
)

logger = logging.getLogger(__name__)

_USER_SETTINGS_NAME = "user_settings.json"
_LOCK = threading.Lock()

# Re-export for schemas / callers.
__all__ = [
    "MATCH_THRESHOLD_DEFAULT",
    "MATCH_THRESHOLD_MAX",
    "MATCH_THRESHOLD_MIN",
    "clamp_match_threshold",
    "get_match_confidence_threshold",
    "load_user_settings",
    "save_user_settings",
    "set_match_confidence_threshold",
    "user_settings_path",
]


def user_settings_path() -> Path:
    return Path(get_settings().data_path) / _USER_SETTINGS_NAME


def load_user_settings() -> dict[str, Any]:
    path = user_settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read user settings %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_user_settings(updates: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = load_user_settings()
        data.update(updates)
        path = user_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return data


def get_match_confidence_threshold() -> int:
    """Effective auto-apply threshold (50–100 percent)."""
    stored = load_user_settings().get("match_confidence_threshold")
    if stored is None:
        return clamp_match_threshold(get_settings().match_confidence_threshold)
    try:
        return clamp_match_threshold(stored)
    except (TypeError, ValueError):
        return clamp_match_threshold(get_settings().match_confidence_threshold)


def set_match_confidence_threshold(value: float | int) -> int:
    threshold = clamp_match_threshold(value)
    save_user_settings({"match_confidence_threshold": threshold})
    return threshold
