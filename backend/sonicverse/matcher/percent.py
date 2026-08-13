"""Integer match scores and thresholds on a 0–100 percent scale."""

from __future__ import annotations

import math

MATCH_PERCENT_MIN = 0
MATCH_PERCENT_MAX = 100
# Auto-apply threshold UI / API bounds.
MATCH_THRESHOLD_MIN = 50
MATCH_THRESHOLD_MAX = 100
MATCH_THRESHOLD_DEFAULT = 100


def as_match_percent(value: float | int | None) -> int:
    """Normalize a score/threshold to 0–100.

    Accepts the current integer percent scale and legacy 0–1 fractions
    (including ``1.0`` → 100). Values already above 1 are treated as percent.
    """
    if value is None:
        return 0
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(raw) or raw <= 0:
        return 0
    if raw <= 1.0:
        return max(MATCH_PERCENT_MIN, min(MATCH_PERCENT_MAX, int(round(raw * 100))))
    return max(MATCH_PERCENT_MIN, min(MATCH_PERCENT_MAX, int(round(raw))))


def clamp_match_threshold(value: float | int | None) -> int:
    """Clamp an auto-apply threshold to 50–100 percent."""
    return max(
        MATCH_THRESHOLD_MIN,
        min(MATCH_THRESHOLD_MAX, as_match_percent(value if value is not None else MATCH_THRESHOLD_DEFAULT)),
    )
