"""Parse release years from QQ / NetEase / MusicBrainz payloads."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_MIN_YEAR = 1000
_MAX_YEAR = 2100
# Unix seconds after ~1970-01-02. Smaller integers are years or empty sentinels.
_MIN_UNIX_SECONDS = 24 * 3600
# 1e10 ms ≈ 1970-04. NetEase uses millisecond timestamps (incl. negatives).
_MIN_UNIX_MS = 10_000_000_000

_DATE_YEAR_RE = re.compile(r"(19|20)\d{2}")
_YMD_RE = re.compile(r"^(19|20)\d{2}[-/.]?\d{2}[-/.]?\d{2}")


def parse_release_year(*values: object) -> int | None:
    """Return the first plausible release year from mixed provider fields.

    Accepts calendar years, ``YYYY-MM-DD`` / ``YYYYMMDD`` strings, Unix seconds,
    and Unix milliseconds. ``0`` / empty values are ignored (QQ/NetEase sentinel).
    """
    for value in values:
        year = _parse_one(value)
        if year is not None:
            return year
    return None


def _parse_one(value: object) -> int | None:
    if value is None or value is False:
        return None
    if isinstance(value, dict):
        return parse_release_year(
            value.get("time_public"),
            value.get("publicTime"),
            value.get("pubtime"),
            value.get("publishTime"),
            value.get("publish_time"),
            value.get("public_time"),
            value.get("publish_date"),
            value.get("date"),
            value.get("year"),
        )
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _year_from_number(value)

    text = str(value).strip()
    if not text or text in {"0", "0000-00-00", "0000/00/00"}:
        return None
    if re.fullmatch(r"-?\d+(\.0+)?", text):
        try:
            return _year_from_number(float(text) if "." in text else int(text))
        except (TypeError, ValueError, OverflowError):
            return None
    if _YMD_RE.match(text) or _DATE_YEAR_RE.search(text):
        match = _DATE_YEAR_RE.search(text)
        if match:
            return _valid_year(int(match.group(0)))
    return None


def _year_from_number(raw: int | float) -> int | None:
    try:
        number = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if number == 0:
        return None
    if _MIN_YEAR <= number <= _MAX_YEAR:
        return number

    seconds: float
    magnitude = abs(number)
    if magnitude >= _MIN_UNIX_MS:
        seconds = number / 1000.0
    elif magnitude >= _MIN_UNIX_SECONDS:
        seconds = float(number)
    else:
        return None
    try:
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    except OverflowError:
        return None
    return _valid_year(dt.year)


def _valid_year(year: int) -> int | None:
    if _MIN_YEAR <= year <= _MAX_YEAR:
        return year
    return None
