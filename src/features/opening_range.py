"""Minimal, reusable opening-range calculation."""

from __future__ import annotations

from datetime import time

import pandas as pd


def calculate_opening_range(
    session_df: pd.DataFrame,
    duration_minutes: int,
) -> dict[str, float | int | pd.Timestamp] | None:
    """Return a complete 09:30 ET opening range, or ``None`` if invalid.

    Timestamp labels follow the existing research convention: a 5-minute OR
    contains the bars labelled 09:30 through 09:34, inclusive.
    """
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    if not isinstance(session_df.index, pd.DatetimeIndex):
        raise TypeError("session_df must use a DatetimeIndex")

    start = time(9, 30)
    end = (
        pd.Timestamp("2000-01-01 09:30")
        + pd.Timedelta(minutes=duration_minutes - 1)
    ).time()
    opening_range = session_df.between_time(start, end, inclusive="both")

    expected_times = pd.date_range(
        pd.Timestamp("2000-01-01 09:30"),
        periods=duration_minutes,
        freq="min",
    ).time
    actual_times = opening_range.index.time
    if len(opening_range) != duration_minutes or not all(actual_times == expected_times):
        return None

    or_high = float(opening_range["high"].max())
    or_low = float(opening_range["low"].min())
    if pd.isna(or_high) or pd.isna(or_low) or or_high <= or_low:
        return None

    return {
        "or_high": or_high,
        "or_low": or_low,
        "or_mid": (or_high + or_low) / 2.0,
        "or_width": or_high - or_low,
        "bars_found": len(opening_range),
        "start_timestamp": opening_range.index[0],
        "end_timestamp": opening_range.index[-1],
    }
