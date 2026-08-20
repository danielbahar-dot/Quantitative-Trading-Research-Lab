"""Turn validated ORB signals into entry, stop, and target candidates.

This module deliberately does not inspect bars after entry and does not assign
trade outcomes. Signal detection remains owned by the validated signal layer.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd


TARGET_R = 2.0
TICK_SIZE = 0.25
INVALID_ENTRY_RELATIVE_TO_STOP = "INVALID_ENTRY_RELATIVE_TO_STOP"
MISSING_IMMEDIATE_NEXT_BAR = "MISSING_IMMEDIATE_NEXT_BAR"

CANDIDATE_COLUMNS = [
    "session_date",
    "contract",
    "direction",
    "or_minutes",
    "breakout_type",
    "signal_time",
    "entry_time",
    "entry_price",
    "entry_bar_open",
    "entry_bar_high",
    "entry_bar_low",
    "entry_bar_close",
    "or_high",
    "or_low",
    "or_mid",
    "initial_stop",
    "risk_points",
    "initial_target",
    "candidate_validity",
    "invalid_reason",
]


def build_candidate_entries(
    price_data: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    or_minutes: int,
) -> pd.DataFrame:
    """Build Gate 4 candidates from already-validated ORB signal rows.

    PRINT candidates enter at the breached OR boundary on the signal timestamp.
    CLOSE candidates enter at the open of the exact next 1-minute bar. No signal
    bar high/low value is used when constructing a CLOSE candidate.
    """
    if not isinstance(price_data.index, pd.DatetimeIndex):
        raise TypeError("price_data must use a DatetimeIndex")
    required_signal_columns = {
        "session_date",
        "direction",
        "breakout_type",
        "signal_time",
        "or_high",
        "or_low",
        "or_mid",
    }
    missing = required_signal_columns.difference(signals.columns)
    if missing:
        raise ValueError(
            "Signals are missing required columns: "
            + ", ".join(sorted(missing))
        )
    required_price_columns = {"session_date", "open", "high", "low", "close"}
    missing_prices = required_price_columns.difference(price_data.columns)
    if missing_prices:
        raise ValueError(
            "Price data is missing required columns: "
            + ", ".join(sorted(missing_prices))
        )

    rows: list[dict] = []
    for signal in signals.itertuples(index=False):
        direction = str(signal.direction).upper()
        breakout_type = str(signal.breakout_type).upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError(f"Unknown signal direction: {direction}")
        if breakout_type not in {"PRINT", "CLOSE"}:
            raise ValueError(f"Unknown breakout type: {breakout_type}")

        session_date = signal.session_date
        signal_time = pd.Timestamp(signal.signal_time)
        signal_bar = _bar_at(price_data, signal_time, session_date)
        contract = _contract_from_bar(signal_bar)
        initial_stop = round_to_tick(float(signal.or_mid))
        invalid_reason = ""

        if breakout_type == "PRINT":
            entry_time = signal_time
            entry_bar = signal_bar
            raw_entry_price = (
                float(signal.or_high)
                if direction == "LONG"
                else float(signal.or_low)
            )
            entry_price = round_to_tick(raw_entry_price)
        else:
            expected_entry_time = signal_time + pd.Timedelta(minutes=1)
            entry_bar = _bar_at(price_data, expected_entry_time, session_date)
            if entry_bar is None:
                entry_time = pd.NaT
                entry_price = None
                invalid_reason = MISSING_IMMEDIATE_NEXT_BAR
            else:
                entry_time = expected_entry_time
                entry_price = round_to_tick(float(entry_bar["open"]))
                if contract == "" or contract is None:
                    contract = _contract_from_bar(entry_bar)

        risk_points: float | None = None
        initial_target: float | None = None
        if entry_price is not None:
            directional_risk = (
                entry_price - initial_stop
                if direction == "LONG"
                else initial_stop - entry_price
            )
            if directional_risk <= 0:
                invalid_reason = INVALID_ENTRY_RELATIVE_TO_STOP
            else:
                risk_points = round_to_tick(float(directional_risk))
                raw_target = (
                    entry_price + TARGET_R * risk_points
                    if direction == "LONG"
                    else entry_price - TARGET_R * risk_points
                )
                initial_target = round_to_tick(raw_target)

        rows.append(
            {
                "session_date": session_date,
                "contract": contract,
                "direction": direction,
                "or_minutes": int(or_minutes),
                "breakout_type": breakout_type,
                "signal_time": signal_time,
                "entry_time": entry_time,
                "entry_price": entry_price,
                # Diagnostic-only entry-bar values. For CLOSE candidates these
                # come from the immediately following bar and are not used to
                # infer execution, ambiguity, stops, or targets.
                "entry_bar_open": _bar_price(entry_bar, "open"),
                "entry_bar_high": _bar_price(entry_bar, "high"),
                "entry_bar_low": _bar_price(entry_bar, "low"),
                "entry_bar_close": _bar_price(entry_bar, "close"),
                "or_high": float(signal.or_high),
                "or_low": float(signal.or_low),
                "or_mid": float(signal.or_mid),
                "initial_stop": initial_stop,
                "risk_points": risk_points,
                "initial_target": initial_target,
                "candidate_validity": invalid_reason == "",
                "invalid_reason": invalid_reason,
            }
        )

    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)


def _bar_at(
    price_data: pd.DataFrame,
    timestamp: pd.Timestamp,
    session_date: date,
) -> pd.Series | None:
    try:
        match = price_data.loc[timestamp]
    except KeyError:
        return None
    if isinstance(match, pd.Series):
        return match if match["session_date"] == session_date else None
    session_match = match.loc[match["session_date"] == session_date]
    return session_match.iloc[0] if not session_match.empty else None


def _contract_from_bar(bar: pd.Series | None) -> str:
    if bar is None or "contract" not in bar.index or pd.isna(bar["contract"]):
        return ""
    return str(bar["contract"])


def _bar_price(bar: pd.Series | None, column: str) -> float | None:
    if bar is None or column not in bar.index or pd.isna(bar[column]):
        return None
    return float(bar[column])


def round_to_tick(value: float, tick_size: float = TICK_SIZE) -> float:
    """Round a calculated price/point value to the nearest tradable tick.

    Exact half-ticks use conventional half-up rounding so the result is
    deterministic and does not depend on Python's binary floating-point round.
    """
    tick = Decimal(str(tick_size))
    if tick <= 0:
        raise ValueError("tick_size must be strictly positive")
    ticks = (Decimal(str(value)) / tick).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return float(ticks * tick)
