"""Causal pre-open and opening-auction feature primitives.

All timestamps are Eastern Time NinjaTrader bar-end labels.  A conceptual
window ``07:00-09:00`` therefore contains one-minute bars stamped 07:01
through 09:00.  Functions in this module operate only on rows owned by the
requested trading ``session_date`` and never infer unavailable observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


ET_TIMEZONE = "America/New_York"
OR_DURATIONS = (15, 20, 30)
HISTORICAL_LOOKBACKS = (5, 10, 15, 20)


@dataclass(frozen=True)
class WindowDefinition:
    """Conceptual market-time window represented by end-labelled bars."""

    window_id: str
    start_time: time
    end_time: time
    start_day_offset: int = 0
    approval_status: str = "validated"

    @property
    def expected_minutes(self) -> int:
        anchor = pd.Timestamp("2000-01-02")
        start = pd.Timestamp.combine(anchor.date(), self.start_time)
        end = pd.Timestamp.combine(anchor.date(), self.end_time)
        start += pd.Timedelta(days=self.start_day_offset)
        if end <= start:
            end += pd.Timedelta(days=1)
        return int((end - start).total_seconds() // 60)


def load_context_windows(config: Mapping[str, Any]) -> dict[str, WindowDefinition]:
    """Parse explicit feature-window configuration without hidden defaults."""
    output: dict[str, WindowDefinition] = {}
    for item in config["windows"]:
        definition = WindowDefinition(
            window_id=item["window_id"],
            start_time=time.fromisoformat(item["start_time_et"]),
            end_time=time.fromisoformat(item["end_time_et"]),
            start_day_offset=int(item.get("start_day_offset", 0)),
            approval_status=item.get("approval_status", "validated"),
        )
        output[definition.window_id] = definition
    return output


def expected_bar_end_index(
    session_date: date,
    window: WindowDefinition,
) -> pd.DatetimeIndex:
    """Return exact one-minute bar-end labels for a conceptual window."""
    start = pd.Timestamp.combine(session_date, window.start_time).tz_localize(ET_TIMEZONE)
    start += pd.Timedelta(days=window.start_day_offset)
    end = pd.Timestamp.combine(session_date, window.end_time).tz_localize(ET_TIMEZONE)
    if end <= start:
        end += pd.Timedelta(days=1)
    return pd.date_range(
        start + pd.Timedelta(minutes=1),
        end,
        freq="min",
    )


def summarize_window(
    session_rows: pd.DataFrame,
    session_date: date,
    window: WindowDefinition,
) -> dict[str, Any]:
    """Summarize a complete causal window or return explicit unavailability."""
    expected = expected_bar_end_index(session_date, window)
    selected = session_rows.loc[session_rows.index.intersection(expected)].sort_index()
    complete = len(selected) == len(expected) and selected.index.equals(expected)
    available_at = expected[-1] if len(expected) else pd.NaT
    base = {
        "window_id": window.window_id,
        "feature_available": bool(complete),
        "expected_bars": int(len(expected)),
        "observed_bars": int(len(selected)),
        "available_at": available_at,
        "missing_reason": "" if complete else "INCOMPLETE_WINDOW",
        "first_bar_end": expected[0] if len(expected) else pd.NaT,
        "last_bar_end": available_at,
    }
    if not complete:
        return {
            **base,
            "open": np.nan,
            "high": np.nan,
            "low": np.nan,
            "close": np.nan,
            "range_points": np.nan,
            "reference_price": np.nan,
            "range_pct": np.nan,
            "net_move_points": np.nan,
            "net_move_pct": np.nan,
            "direction": None,
            "efficiency": np.nan,
            "high_timestamp": pd.NaT,
            "low_timestamp": pd.NaT,
        }
    open_price = float(selected.iloc[0]["open"])
    high = float(selected["high"].max())
    low = float(selected["low"].min())
    close = float(selected.iloc[-1]["close"])
    width = high - low
    net = close - open_price
    return {
        **base,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "range_points": width,
        "reference_price": open_price,
        "range_pct": _safe_divide(width, open_price),
        "net_move_points": net,
        "net_move_pct": _safe_divide(net, open_price),
        "direction": _direction(net),
        "efficiency": _safe_divide(abs(net), width),
        "high_timestamp": selected["high"].idxmax(),
        "low_timestamp": selected["low"].idxmin(),
    }


def calculate_or_context(
    session_rows: pd.DataFrame,
    session_date: date,
    duration_minutes: int,
) -> dict[str, Any]:
    """Calculate complete OR context from 09:31 through its final bar-end."""
    if duration_minutes not in OR_DURATIONS:
        raise ValueError(f"duration_minutes must be one of {OR_DURATIONS}")
    window = WindowDefinition(
        window_id=f"or_{duration_minutes}m",
        start_time=time(9, 30),
        end_time=(pd.Timestamp("2000-01-01 09:30") + pd.Timedelta(minutes=duration_minutes)).time(),
    )
    summary = summarize_window(session_rows, session_date, window)
    width = summary["range_points"]
    close = summary["close"]
    low = summary["low"]
    return {
        "or_feature_available": summary["feature_available"],
        "or_expected_bars": summary["expected_bars"],
        "or_observed_bars": summary["observed_bars"],
        "or_available_at": summary["available_at"],
        "or_missing_reason": summary["missing_reason"],
        "or_first_bar_end": summary["first_bar_end"],
        "or_last_bar_end": summary["last_bar_end"],
        "or_minutes": duration_minutes,
        "or_high": summary["high"],
        "or_low": summary["low"],
        "or_open": summary["open"],
        "or_close": close,
        "or_mid": (summary["range_points"] / 2.0 + low) if summary["feature_available"] else np.nan,
        "or_width_points": width,
        "or_width_pct": summary["range_pct"],
        "or_reference_price": summary["reference_price"],
        "or_net_move_points": summary["net_move_points"],
        "or_net_move_pct": summary["net_move_pct"],
        "or_direction": summary["direction"],
        "or_efficiency": summary["efficiency"],
        "or_clv": _safe_divide(close - low, width) if summary["feature_available"] else np.nan,
        "or_high_timestamp": summary["high_timestamp"],
        "or_low_timestamp": summary["low_timestamp"],
    }


def add_causal_width_history(
    frame: pd.DataFrame,
    *,
    lookbacks: Iterable[int] = HISTORICAL_LOOKBACKS,
) -> pd.DataFrame:
    """Add prior-session-only midrank percentiles and population z-scores."""
    output = frame.sort_values(["or_minutes", "session_date"]).copy()
    for lookback in lookbacks:
        prefix = f"or_width_hist_{lookback}"
        output[f"{prefix}_sample_count"] = 0
        output[f"{prefix}_percentile"] = np.nan
        output[f"{prefix}_zscore"] = np.nan
        output[f"{prefix}_available"] = False
        for _, positions in output.groupby("or_minutes", sort=False).groups.items():
            ordered = list(positions)
            values = output.loc[ordered, "or_width_points"]
            for offset, position in enumerate(ordered):
                prior = values.iloc[max(0, offset - lookback):offset].dropna()
                output.at[position, f"{prefix}_sample_count"] = len(prior)
                current = output.at[position, "or_width_points"]
                if len(prior) < lookback or pd.isna(current):
                    continue
                less = int((prior < current).sum())
                equal = int((prior == current).sum())
                percentile = (less + 0.5 * equal) / len(prior)
                std = float(prior.std(ddof=0))
                output.at[position, f"{prefix}_percentile"] = percentile
                output.at[position, f"{prefix}_zscore"] = (
                    (float(current) - float(prior.mean())) / std if std > 0 else np.nan
                )
                output.at[position, f"{prefix}_available"] = True
    return output.sort_values(["session_date", "or_minutes"]).reset_index(drop=True)


def gap_context(
    prior_session_rows: pd.DataFrame | None,
    current_session_rows: pd.DataFrame,
    session_date: date,
) -> dict[str, Any]:
    """Describe the 17:00 close to 18:01 reopen and fill state by 09:30."""
    reopen_stamp = pd.Timestamp.combine(session_date, time(18, 1)).tz_localize(ET_TIMEZONE) - pd.Timedelta(days=1)
    observation_end = pd.Timestamp.combine(session_date, time(9, 30)).tz_localize(ET_TIMEZONE)
    expected_observation = pd.date_range(reopen_stamp, observation_end, freq="min")
    unavailable = {
        "globex_reopen_gap_feature_available": False,
        "globex_reopen_gap_prior_1700_close": np.nan,
        "globex_reopen_price": np.nan,
        "globex_reopen_gap_points": np.nan,
        "globex_reopen_gap_pct": np.nan,
        "globex_reopen_gap_direction": None,
        "globex_reopen_gap_fill_state_at_0930": None,
        "globex_reopen_gap_filled_before_0930": False,
        "globex_reopen_gap_partially_filled_before_0930": False,
        "globex_reopen_gap_still_open_at_0930": False,
        "globex_reopen_gap_available_at": observation_end,
        "globex_reopen_gap_expected_bars": int(len(expected_observation)),
        "globex_reopen_gap_observed_bars": 0,
        "globex_reopen_gap_missing_reason": "MISSING_PRIOR_1700_CLOSE_OR_1801_REOPEN",
    }
    if prior_session_rows is None or prior_session_rows.empty:
        return unavailable
    prior_close_stamp = pd.Timestamp.combine(
        prior_session_rows["session_date"].iloc[0], time(17, 0)
    ).tz_localize(ET_TIMEZONE)
    if prior_close_stamp not in prior_session_rows.index or reopen_stamp not in current_session_rows.index:
        return unavailable
    prior_close = float(prior_session_rows.loc[prior_close_stamp, "close"])
    reopen = float(current_session_rows.loc[reopen_stamp, "open"])
    gap = reopen - prior_close
    through_0930 = current_session_rows.loc[
        current_session_rows.index.intersection(expected_observation)
    ].sort_index()
    if len(through_0930) != len(expected_observation) or not through_0930.index.equals(expected_observation):
        return {
            **unavailable,
            "globex_reopen_gap_observed_bars": int(len(through_0930)),
            "globex_reopen_gap_missing_reason": "INCOMPLETE_GAP_OBSERVATION_WINDOW",
        }
    if gap > 0:
        filled = bool(through_0930["low"].min() <= prior_close)
        partial = bool(not filled and through_0930["low"].min() < reopen)
    elif gap < 0:
        filled = bool(through_0930["high"].max() >= prior_close)
        partial = bool(not filled and through_0930["high"].max() > reopen)
    else:
        filled, partial = True, False
    state = "NO_GAP" if gap == 0 else ("FILLED" if filled else ("PARTIAL" if partial else "OPEN"))
    return {
        **unavailable,
        "globex_reopen_gap_feature_available": True,
        "globex_reopen_gap_prior_1700_close": prior_close,
        "globex_reopen_price": reopen,
        "globex_reopen_gap_points": gap,
        "globex_reopen_gap_pct": _safe_divide(gap, prior_close),
        "globex_reopen_gap_direction": _direction(gap),
        "globex_reopen_gap_fill_state_at_0930": state,
        "globex_reopen_gap_filled_before_0930": filled,
        "globex_reopen_gap_partially_filled_before_0930": partial,
        "globex_reopen_gap_still_open_at_0930": bool(not filled),
        "globex_reopen_gap_observed_bars": int(len(through_0930)),
        "globex_reopen_gap_missing_reason": "",
    }


def ny_open_gap_context(
    prior_session_rows: pd.DataFrame | None,
    current_session_rows: pd.DataFrame,
    session_date: date,
) -> dict[str, Any]:
    """Describe the prior 16:14 close to the 09:30 New York opening price.

    ``timestamp_et`` is a bar-end label.  The prior reference is therefore the
    close of the bar stamped 16:14 ET.  The current New York opening reference
    is the open of the bar stamped 09:31 ET, which represents the 09:30:00
    market open.  Missing reference bars are never substituted.
    """
    open_stamp = pd.Timestamp.combine(session_date, time(9, 31)).tz_localize(ET_TIMEZONE)
    unavailable = {
        "ny_open_gap_feature_available": False,
        "ny_open_gap_prior_1614_timestamp": pd.NaT,
        "ny_open_gap_prior_1614_close": np.nan,
        "ny_open_reference_timestamp": open_stamp,
        "ny_open_reference_price": np.nan,
        "ny_open_gap_points": np.nan,
        "ny_open_gap_pct": np.nan,
        "ny_open_gap_direction": None,
        "ny_open_gap_available_at": open_stamp,
        "ny_open_gap_missing_reason": "NO_PRIOR_SESSION",
    }
    if prior_session_rows is None or prior_session_rows.empty:
        return unavailable
    prior_date = prior_session_rows["session_date"].iloc[0]
    prior_stamp = pd.Timestamp.combine(prior_date, time(16, 14)).tz_localize(ET_TIMEZONE)
    unavailable["ny_open_gap_prior_1614_timestamp"] = prior_stamp
    if prior_stamp not in prior_session_rows.index:
        return {**unavailable, "ny_open_gap_missing_reason": "MISSING_PRIOR_1614_BAR"}
    if open_stamp not in current_session_rows.index:
        return {**unavailable, "ny_open_gap_missing_reason": "MISSING_CURRENT_0931_BAR"}
    prior_close = float(prior_session_rows.loc[prior_stamp, "close"])
    open_price = float(current_session_rows.loc[open_stamp, "open"])
    gap = open_price - prior_close
    return {
        **unavailable,
        "ny_open_gap_feature_available": True,
        "ny_open_gap_prior_1614_close": prior_close,
        "ny_open_reference_price": open_price,
        "ny_open_gap_points": gap,
        "ny_open_gap_pct": _safe_divide(gap, prior_close),
        "ny_open_gap_direction": _direction(gap),
        "ny_open_gap_missing_reason": "",
    }


def level_interaction(
    *,
    level: float,
    or_open: float,
    or_high: float,
    or_low: float,
    or_close: float,
    or_mid: float,
) -> dict[str, Any]:
    """Deterministic OR relationship to a price known before OR completion."""
    if any(pd.isna(value) for value in (level, or_open, or_high, or_low, or_close, or_mid)):
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
    start_side = "BELOW" if or_open < level else ("ABOVE" if or_open > level else "AT")
    touched = bool(or_low <= level <= or_high)
    if start_side == "BELOW":
        traded_through = bool(or_high > level)
        closed_through = bool(or_close > level)
        swept = bool(traded_through and or_close <= level)
        rejected = bool(touched and or_close <= level)
    elif start_side == "ABOVE":
        traded_through = bool(or_low < level)
        closed_through = bool(or_close < level)
        swept = bool(traded_through and or_close >= level)
        rejected = bool(touched and or_close >= level)
    else:
        # With no original side, directional through/reject/sweep states are
        # intentionally undefined and represented as false primitive flags.
        traded_through = False
        closed_through = False
        swept = False
        rejected = False
    return {
        "available": True,
        "start_side": start_side,
        "distance_from_or_high_points": level - or_high,
        "distance_from_or_low_points": level - or_low,
        "distance_from_or_mid_points": level - or_mid,
        "distance_from_or_high_pct": _safe_divide(level - or_high, or_mid),
        "distance_from_or_low_pct": _safe_divide(level - or_low, or_mid),
        "distance_from_or_mid_pct": _safe_divide(level - or_mid, or_mid),
        "touched": touched,
        "traded_through": traded_through,
        "swept": swept,
        "closed_through": closed_through,
        "rejected": rejected,
    }


def interaction_state(took_high: bool, took_low: bool) -> str:
    if took_high and took_low:
        return "BOTH"
    if took_high:
        return "HIGH_ONLY"
    if took_low:
        return "LOW_ONLY"
    return "NEITHER"


def _safe_divide(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or abs(float(denominator)) < 1e-12:
        return np.nan
    return float(numerator) / float(denominator)


def _direction(value: float) -> str:
    if value > 0:
        return "UP"
    if value < 0:
        return "DOWN"
    return "FLAT"
