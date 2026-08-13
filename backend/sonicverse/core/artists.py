"""Artist name helpers."""

from __future__ import annotations

import re

# Comma, ampersand, slash, or Chinese enumeration comma, with optional spaces.
_SPLIT_RE = re.compile(r"\s*[,&/、]\s*")


def split_artist_names(raw: str | None) -> list[str]:
    """Split a credit string into individual artist names.

    ``"Earth, Wind & Fire"`` → ``["Earth", "Wind", "Fire"]``.
    ``"浅影阿 / 汐音社"`` → ``["浅影阿", "汐音社"]``.
    """
    if raw is None:
        return []
    text = raw.strip()
    if not text:
        return []

    parts = [part.strip() for part in _SPLIT_RE.split(text) if part.strip()]
    if not parts:
        return []

    names: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(part)
    return names


def join_artist_names(
    raw: str | list[str] | None,
    *,
    sep: str = ",",
) -> str:
    """Join artist credits with an English comma (no spaces).

    ``"A / B & C"`` → ``"A,B,C"``.
    """
    if isinstance(raw, list):
        names: list[str] = []
        seen: set[str] = set()
        for part in raw:
            text = (part or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(text)
        return sep.join(names)
    return sep.join(split_artist_names(raw))
