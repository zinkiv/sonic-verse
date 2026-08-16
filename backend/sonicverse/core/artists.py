"""Artist name helpers."""

from __future__ import annotations

import re
import unicodedata

# Semicolon, slash, 顿号. English comma only when the next name starts.
# Ampersand stays inside band names like "MYTH & ROID".
_SPLIT_RE = re.compile(
    r"\s*[;；/、]\s*"
    r"|,\s*(?=[A-Z\u4e00-\u9fff])"
)
_FULLWIDTH_COMMA = "\uff0c"
_COMMA_HOLD = "\ue000"


def normalize_artist_name(raw: str | None) -> str:
    """Strip invisible / compatibility junk so the same person is one name."""
    # NFKC would fold 「，」 into ASCII comma and then split credits wrongly.
    text = (raw or "").replace(_FULLWIDTH_COMMA, _COMMA_HOLD)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", text).strip().replace(_COMMA_HOLD, _FULLWIDTH_COMMA)


def normalize_album_title(raw: str | None) -> str:
    """Same cleanup as artist names, applied to album titles."""
    return normalize_artist_name(raw)


def artist_name_key(raw: str | None) -> str:
    """Case-insensitive identity used to merge duplicate artist rows."""
    return normalize_artist_name(raw).casefold()


def split_artist_names(raw: str | None) -> list[str]:
    """Split a credit string into individual artist names.

    ``"Earth, Wind & Fire"`` → ``["Earth", "Wind & Fire"]``.
    ``"MYTH & ROID"`` stays one credit.
    ``"Fear,and Loathing in Las Vegas"`` → ``["Fear,and Loathing in Las Vegas"]``.
    ``"浅影阿 / 汐音社"`` → ``["浅影阿", "汐音社"]``.
    ``"侯明昊;陈都灵;田嘉瑞"`` → ``["侯明昊", "陈都灵", "田嘉瑞"]``.
    Chinese comma 「，」 is part of the name, not a separator.
    ``&`` is part of the name. An English comma is a separator only when the
    following token looks like a new name (uppercase Latin or CJK).
    """
    if raw is None:
        return []
    text = normalize_artist_name(raw)
    if not text:
        return []

    parts = [normalize_artist_name(part) for part in _SPLIT_RE.split(text)]
    parts = [
        part
        for part in parts
        if part and not re.fullmatch(r"[\s,;&/、；]+", part)
    ]
    if not parts:
        return []

    names: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = artist_name_key(part)
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

    ``"A / B"`` → ``"A,B"``.
    """
    if isinstance(raw, list):
        names: list[str] = []
        seen: set[str] = set()
        for part in raw:
            text = normalize_artist_name(part)
            if not text:
                continue
            key = artist_name_key(text)
            if key in seen:
                continue
            seen.add(key)
            names.append(text)
        return sep.join(names)
    return sep.join(split_artist_names(raw))
