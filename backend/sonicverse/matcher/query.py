"""Helpers for deriving match queries from local files."""

from __future__ import annotations

from pathlib import Path

from sonicverse.core.titles import core_title

# Separators commonly used in "Artist - Title.ext" / "Artist-Title.ext" filenames.
_SEPARATORS = (" - ", " – ", " — ", "_-_", "-")


def parse_filename_hints(file_path: str | None) -> tuple[str | None, str | None]:
    """Return (title, artist) guessed from a filename stem.

    Accepts the common ``Artist - Title`` pattern. When no separator is found,
    the whole stem is treated as a title hint.
    """
    if not file_path:
        return None, None
    stem = Path(file_path).stem.strip()
    if not stem:
        return None, None

    for sep in _SEPARATORS:
        if sep in stem:
            left, right = stem.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return right, left
    return stem, None


def resolve_match_query(
    *,
    title: str | None,
    artist: str | None,
    file_path: str | None,
) -> tuple[str, str]:
    """Pick title/artist for provider search.

    Filename artist wins over a tagged artist when they disagree — tags are
    often polluted by a previous bad match, while ``Artist - Title.ext`` is
    usually what the user named the file.
    """
    fn_title, fn_artist = parse_filename_hints(file_path)
    tagged_title = (title or "").strip()
    file_title = (fn_title or "").strip()
    tagged_core = core_title(tagged_title)
    file_core = core_title(file_title)
    resolved_title = tagged_core or file_core or tagged_title or file_title

    tagged_artist = (artist or "").strip()
    file_artist = (fn_artist or "").strip()

    if file_artist and tagged_artist and file_artist != tagged_artist:
        resolved_artist = file_artist
    else:
        resolved_artist = tagged_artist or file_artist

    return resolved_title, resolved_artist
