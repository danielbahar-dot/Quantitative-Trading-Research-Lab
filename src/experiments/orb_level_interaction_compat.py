"""ORB compatibility layer over the generic Level Interaction catalog (M6B).

``src/features/level_interactions.py`` (M6A) is the authority for level
interactions.  Frozen ORB V0.2 research consumes it here; this module does
not reimplement the interaction mathematics.

ORB consumer pattern (not the generic primitive definition):

- **Aggregated window.**  ORB evaluates each opening range as one aggregated
  OHLC bar (``or_open/high/low/close`` over [09:30, 09:30 + duration)).  The
  adapter builds that bar explicitly and evaluates it with
  ``evaluate_level_interactions`` using ``bar_interval = duration``.
- **Applicability.**  Each level is scoped to its own window with
  ``valid_from = window_start`` and ``valid_until = window_end``.  ORB's
  historical contract is that its key levels are known before OR completion;
  the adapter declares ``available_at = window_start`` on the caller's
  behalf and does not re-verify it.  Contract scope is ``AGNOSTIC``: ORB never
  compared contracts.
- **Approach side.**  The legacy ``start_side`` is the generic geometric
  ``approach_side`` (BELOW / ABOVE / AT); no second orientation system.
  Orientation stays semantic (highs UPPER, lows LOWER, closes / reference
  prices NEUTRAL) and does not affect the ORB output.

Compatibility rule (the only one):

- **Open at level.**  When the window opens exactly at the level
  (``approach_side == AT``), frozen ORB reports ``touched = True`` and
  ``traded_through``, ``closed_through``, ``rejected`` and ``swept`` all
  ``False``.  Generic M6A instead evaluates directional levels on their
  original side and marks NEUTRAL levels ``AMBIGUOUS_APPROACH``.  The adapter
  overrides the four directional flags to ``False`` for AT rows only.

ORB-specific fields kept here: ``available`` and the six OR distance fields
(``level - or_high/low/mid`` in points and as a fraction of ``or_mid``).
The historical 13-field schema and its column order are preserved exactly.
New work must use the generic API, not this module.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.features.level_interactions import (
    AGNOSTIC,
    AMBIGUOUS_APPROACH,
    AT,
    EVALUATED,
    LOWER,
    NEUTRAL,
    UPPER,
    evaluate_level_interactions,
)
from src.features.market_context import ET_TIMEZONE, _safe_divide

ORB_INSTRUMENT_ID = "MNQ"

# Semantic orientation of the 18 frozen ORB key levels.
ORB_LEVEL_ORIENTATION: dict[str, str] = {
    "previous_day_high": UPPER,
    "previous_day_low": LOWER,
    "previous_day_close": NEUTRAL,
    "previous_rth_high": UPPER,
    "previous_rth_low": LOWER,
    "previous_rth_close": NEUTRAL,
    "overnight_high": UPPER,
    "overnight_low": LOWER,
    "asia_high": UPPER,
    "asia_low": LOWER,
    "london_high": UPPER,
    "london_low": LOWER,
    "ny_premarket_high": UPPER,
    "ny_premarket_low": LOWER,
    "globex_reopen": NEUTRAL,
    "globex_reopen_prior_1700_close": NEUTRAL,
    "ny_open_prior_1614_close": NEUTRAL,
    "ny_open_reference": NEUTRAL,
}

# Historical ORB interaction schema (13 fields per level), in frozen order.
ORB_INTERACTION_FIELDS = (
    "available",
    "start_side",
    "distance_from_or_high_points",
    "distance_from_or_low_points",
    "distance_from_or_mid_points",
    "distance_from_or_high_pct",
    "distance_from_or_low_pct",
    "distance_from_or_mid_pct",
    "touched",
    "traded_through",
    "swept",
    "closed_through",
    "rejected",
)
DIRECTIONAL_FLAGS = ("traded_through", "swept", "closed_through", "rejected")
WINDOW_COLUMNS = (
    "level", "orientation", "or_open", "or_high", "or_low", "or_close", "or_mid",
    "window_start", "window_end",
)
# A scalar legacy call carries no time context; its single aggregated bar is
# placed on this nominal anchor.  Window primitives do not depend on time.
_NOMINAL_WINDOW_START = pd.Timestamp("2000-01-03 09:30", tz=ET_TIMEZONE)


def unavailable_interaction() -> dict[str, Any]:
    """Frozen ORB output when the level or the OR values are missing."""
    return {
        "available": False,
        "start_side": None,
        "distance_from_or_high_points": np.nan,
        "distance_from_or_low_points": np.nan,
        "distance_from_or_mid_points": np.nan,
        "distance_from_or_high_pct": np.nan,
        "distance_from_or_low_pct": np.nan,
        "distance_from_or_mid_pct": np.nan,
        "touched": False,
        "traded_through": False,
        "swept": False,
        "closed_through": False,
        "rejected": False,
    }


def orb_window_interactions(windows: pd.DataFrame, *, apply_open_at_level_compat: bool = True) -> list[dict[str, Any]]:
    """Evaluate (aggregated OR window, level) records through M6A in ORB schema.

    ``windows`` has one row per record with ``WINDOW_COLUMNS``.  Returns one
    13-field dict per input row, in input order.  ``apply_open_at_level_compat``
    exists only so tests can prove the compatibility rule is load-bearing.
    """
    missing = [column for column in WINDOW_COLUMNS if column not in windows.columns]
    if missing:
        raise ValueError(f"ORB interaction windows missing columns {missing}")
    frame = windows.reset_index(drop=True)
    values = frame[["level", "or_open", "or_high", "or_low", "or_close", "or_mid"]].astype(float)
    available = values.notna().all(axis=1).to_numpy()
    results: list[dict[str, Any]] = [unavailable_interaction() for _ in range(len(frame))]
    if not available.any():
        return results

    usable = frame.loc[available].copy()
    usable["level_id"] = usable.index.astype(str)
    duration = pd.DatetimeIndex(usable["window_end"]) - pd.DatetimeIndex(usable["window_start"])
    generic_parts = []
    for interval in sorted(set(duration)):
        group = usable.loc[np.asarray(duration == interval)]
        bars = (
            group.drop_duplicates("window_end")
            .set_index("window_end")
            .rename(columns={"or_open": "open", "or_high": "high", "or_low": "low", "or_close": "close"})
            [["open", "high", "low", "close"]]
        )
        bars["contract"] = "ORB_AGGREGATED_WINDOW"
        consistent = group.merge(bars, left_on="window_end", right_index=True)
        if not (consistent[["or_open", "or_high", "or_low", "or_close"]].to_numpy()
                == consistent[["open", "high", "low", "close"]].to_numpy()).all():
            raise ValueError("ORB windows sharing a window_end disagree on OHLC")
        bars.index = pd.DatetimeIndex(bars.index, name="timestamp_et")
        levels = pd.DataFrame({
            "level_id": group["level_id"],
            "level_value": group["level"].astype(float),
            "orientation": group["orientation"],
            "available_at": group["window_start"],
            "valid_from": group["window_start"],
            "valid_until": group["window_end"],
            "instrument_id": ORB_INSTRUMENT_ID,
            "contract_scope": AGNOSTIC,
            "contract": None,
        })
        generic_parts.append(evaluate_level_interactions(bars, levels, bar_interval=interval))
    generic = pd.concat(generic_parts).set_index("level_id")
    if len(generic) != len(usable) or not generic.index.is_unique:
        raise AssertionError("each ORB window record must map to exactly one aggregated bar")
    unexpected = set(generic["status"]) - {EVALUATED, AMBIGUOUS_APPROACH}
    if unexpected:
        raise AssertionError(f"unexpected generic statuses for ORB windows: {sorted(unexpected)}")

    for position, record in usable.iterrows():
        row = generic.loc[record["level_id"]]
        side = row["approach_side"]
        flags = {
            "touched": bool(row["touch"]),
            "traded_through": row["trade_through"],
            "swept": row["sweep"],
            "closed_through": row["close_through"],
            "rejected": row["reject"],
        }
        if side == AT and apply_open_at_level_compat:
            flags.update({name: False for name in DIRECTIONAL_FLAGS})
        # After the AT override no flag is <NA>; without it a NEUTRAL AT row keeps <NA> (None).
        flags = {name: (None if pd.isna(value) else bool(value)) for name, value in flags.items()}
        level, or_high, or_low, or_mid = (float(record[name]) for name in ("level", "or_high", "or_low", "or_mid"))
        results[position] = {
            "available": True,
            "start_side": side,
            "distance_from_or_high_points": level - or_high,
            "distance_from_or_low_points": level - or_low,
            "distance_from_or_mid_points": level - or_mid,
            "distance_from_or_high_pct": _safe_divide(level - or_high, or_mid),
            "distance_from_or_low_pct": _safe_divide(level - or_low, or_mid),
            "distance_from_or_mid_pct": _safe_divide(level - or_mid, or_mid),
            "touched": flags["touched"],
            "traded_through": flags["traded_through"],
            "swept": flags["swept"],
            "closed_through": flags["closed_through"],
            "rejected": flags["rejected"],
        }
    return results


def level_interaction(
    *,
    level: float,
    or_open: float,
    or_high: float,
    or_low: float,
    or_close: float,
    or_mid: float,
    orientation: str = NEUTRAL,
) -> dict[str, Any]:
    """Legacy scalar ORB signature: one OR window x one level, via M6A.

    Replaces the former ``src.features.market_context.level_interaction`` with
    identical output.  The window is placed on a nominal 1-minute anchor
    because a scalar call carries no time context.
    """
    window = pd.DataFrame([{
        "level": level, "orientation": orientation, "or_open": or_open, "or_high": or_high,
        "or_low": or_low, "or_close": or_close, "or_mid": or_mid,
        "window_start": _NOMINAL_WINDOW_START,
        "window_end": _NOMINAL_WINDOW_START + pd.Timedelta(minutes=1),
    }])
    return orb_window_interactions(window)[0]


def orb_level_window_records(
    levels: Mapping[str, float],
    or_context: Mapping[str, Any],
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> list[dict[str, Any]]:
    """Window records for one session x OR duration, in ``levels`` order."""
    return [
        {
            "level": level,
            "orientation": ORB_LEVEL_ORIENTATION[level_id],
            "or_open": or_context["or_open"],
            "or_high": or_context["or_high"],
            "or_low": or_context["or_low"],
            "or_close": or_context["or_close"],
            "or_mid": or_context["or_mid"],
            "window_start": window_start,
            "window_end": window_end,
        }
        for level_id, level in levels.items()
    ]
