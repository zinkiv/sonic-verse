"""Normalize track titles for search and scoring."""

from __future__ import annotations

import re

# Trailing version / remix / speed suffixes in () or （）.
_TRAILING_PARENS = re.compile(r"\s*[\(（][^()（）]*[\)）]\s*$")


def core_title(title: str | None) -> str:
    """Keep the primary song name, dropping trailing parenthetical extras.

    ``青花瓷 (Tanii1.2x变速版)`` → ``青花瓷``.
    """
    text = (title or "").strip()
    if not text:
        return ""
    while True:
        stripped = _TRAILING_PARENS.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text or (title or "").strip()
