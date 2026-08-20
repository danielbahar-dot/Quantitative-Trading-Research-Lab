"""Gate 4C forward simulation for validated ORB candidate trades.

This module consumes Gate 4A/4B candidate rows. It does not discover signals,
change entries, or recalculate initial stops and targets.

The validated source uses NinjaTrader bar-end timestamps. A bar stamped 16:00
ET is therefore the final normal RTH minute (approximately 15:59:00-15:59:59).
For shortened sessions the forced exit uses the last observed same-session bar
whose bar-end timestamp is no later than 16:00 ET.
"""

from __future__ import annotations

from datetime import time

import pandas as pd

from src.backtesting.candidate_entries import round_to_tick


REGULAR_SESSION_END = time(16, 0)

TARGET = "TARGET"
STOP = "STOP"
SESSION_END = "SESSION_END"
AMBIGUOUS_STOP_TARGET = "AMBIGUOUS_STOP_TARGET"
AMBIGUOUS_ENTRY_STOP = "AMBIGUOUS_ENTRY_STOP"
MISSING_SESSION_EXIT_BAR = "MISSING_SESSION_EXIT_BAR"

STOP_TARGET_ORDER_UNKNOWN = "STOP_TARGET_ORDER_UNKNOWN"
ENTRY_AND_STOP_ORDER_UNKNOWN = "ENTRY_AND_STOP_ORDER_UNKNOWN"

TRADE_COLUMNS = [
    "trade_id",
    "session_date",
    "contract",
    "or_minutes",
    "breakout_type",
    "direction",
    "signal_time",
    "entry_time",
    "entry_price",
    "initial_stop",
    "initial_target",
    "risk_points",
    "exit_time",
    "exit_price",
    "exit_reason",
    "exit_bar_close",
    "ambiguous",
    "ambiguity_reason",
    "holding_bars",
    "holding_minutes",
    "pnl_points",
    "result_r",
    "mfe_points",
    "mae_points",
    "mfe_r",
    "mae_r",
    "excluded_from_performance",
]


def simulate_completed_trades(
    price_data: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    session_end: time = REGULAR_SESSION_END,
) -> pd.DataFrame:
    """Simulate valid candidates through their first exit event.

    CLOSE paths begin at the candidate entry bar, so their signal bar is never
    inspected. PRINT paths include the signal/entry bar; a stop touch there is
    conservatively ambiguous because OHLC cannot order entry versus stop.
    """
    if not isinstance(price_data.index, pd.DatetimeIndex):
        raise TypeError("price_data must use a DatetimeIndex")

    required_prices = {"session_date", "high", "low", "close"}
    missing_prices = required_prices.difference(price_data.columns)
    if missing_prices:
        raise ValueError(
            "Price data is missing required columns: "
            + ", ".join(sorted(missing_prices))
        )

    required_candidates = {
        "session_date",
        "contract",
        "or_minutes",
        "breakout_type",
        "direction",
        "signal_time",
        "entry_time",
        "entry_price",
        "initial_stop",
        "initial_target",
        "risk_points",
        "candidate_validity",
    }
    missing_candidates = required_candidates.difference(candidates.columns)
    if missing_candidates:
        raise ValueError(
            "Candidates are missing required columns: "
            + ", ".join(sorted(missing_candidates))
        )

    rows: list[dict] = []
    valid_candidates = candidates.loc[candidates["candidate_validity"]]
    wanted_sessions = set(valid_candidates["session_date"])
    session_lookup = {
        session_date: session_prices
        for session_date, session_prices in price_data.loc[
            price_data["session_date"].isin(wanted_sessions)
        ].groupby("session_date", sort=False)
    }
    for candidate in valid_candidates.itertuples(index=False):
        session_prices = session_lookup.get(candidate.session_date)
        rows.append(_simulate_candidate(session_prices, candidate, session_end))
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def _simulate_candidate(
    session_prices: pd.DataFrame | None,
    candidate,
    session_end: time,
) -> dict:
    direction = str(candidate.direction).upper()
    breakout_type = str(candidate.breakout_type).upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Unknown candidate direction: {direction}")
    if breakout_type not in {"PRINT", "CLOSE"}:
        raise ValueError(f"Unknown breakout type: {breakout_type}")

    entry_time = pd.Timestamp(candidate.entry_time)
    signal_time = pd.Timestamp(candidate.signal_time)
    entry_price = float(candidate.entry_price)
    initial_stop = float(candidate.initial_stop)
    initial_target = float(candidate.initial_target)
    risk_points = float(candidate.risk_points)
    if risk_points <= 0:
        raise ValueError("Valid candidates must have strictly positive risk")

    deadline = pd.Timestamp.combine(candidate.session_date, session_end)
    if entry_time.tzinfo is not None:
        deadline = deadline.tz_localize(entry_time.tzinfo)
    path = (
        session_prices.loc[
            (session_prices.index >= entry_time)
            & (session_prices.index <= deadline)
        ]
        if session_prices is not None
        else pd.DataFrame()
    )

    trade_id = (
        f"{candidate.session_date.isoformat()}_{int(candidate.or_minutes)}m_"
        f"{breakout_type}_{direction}_{signal_time.strftime('%H%M')}"
    )
    common = {
        "trade_id": trade_id,
        "session_date": candidate.session_date,
        "contract": candidate.contract,
        "or_minutes": int(candidate.or_minutes),
        "breakout_type": breakout_type,
        "direction": direction,
        "signal_time": signal_time,
        "entry_time": entry_time,
        "entry_price": entry_price,
        "initial_stop": initial_stop,
        "initial_target": initial_target,
        "risk_points": risk_points,
    }

    if path.empty or path.index[0] != entry_time:
        return {
            **common,
            "exit_time": pd.NaT,
            "exit_price": None,
            "exit_reason": MISSING_SESSION_EXIT_BAR,
            "exit_bar_close": None,
            "ambiguous": True,
            "ambiguity_reason": MISSING_SESSION_EXIT_BAR,
            "holding_bars": 0,
            "holding_minutes": None,
            "pnl_points": None,
            "result_r": None,
            "mfe_points": None,
            "mae_points": None,
            "mfe_r": None,
            "mae_r": None,
            "excluded_from_performance": True,
        }

    scanned: list[pd.Series] = []
    exit_time = None
    exit_price = None
    exit_reason = ""
    ambiguity_reason = ""
    exit_bar_close = None

    for timestamp, bar in path.iterrows():
        scanned.append(bar)
        stop_hit = (
            bool(bar["low"] <= initial_stop)
            if direction == "LONG"
            else bool(bar["high"] >= initial_stop)
        )
        target_hit = (
            bool(bar["high"] >= initial_target)
            if direction == "LONG"
            else bool(bar["low"] <= initial_target)
        )

        if stop_hit and target_hit:
            exit_time = timestamp
            exit_reason = AMBIGUOUS_STOP_TARGET
            ambiguity_reason = STOP_TARGET_ORDER_UNKNOWN
            exit_bar_close = round_to_tick(float(bar["close"]))
            break

        if (
            breakout_type == "PRINT"
            and timestamp == entry_time
            and stop_hit
        ):
            exit_time = timestamp
            exit_reason = AMBIGUOUS_ENTRY_STOP
            ambiguity_reason = ENTRY_AND_STOP_ORDER_UNKNOWN
            exit_bar_close = round_to_tick(float(bar["close"]))
            break

        if target_hit:
            exit_time = timestamp
            exit_price = initial_target
            exit_reason = TARGET
            exit_bar_close = round_to_tick(float(bar["close"]))
            break
        if stop_hit:
            exit_time = timestamp
            exit_price = initial_stop
            exit_reason = STOP
            exit_bar_close = round_to_tick(float(bar["close"]))
            break

    if exit_time is None:
        final_bar = path.iloc[-1]
        exit_time = path.index[-1]
        exit_price = round_to_tick(float(final_bar["close"]))
        exit_reason = SESSION_END
        exit_bar_close = exit_price

    ambiguous = bool(ambiguity_reason)
    holding_bars = len(scanned)
    holding_minutes = int(
        (exit_time - entry_time) / pd.Timedelta(minutes=1)
    )

    pnl_points = None
    result_r = None
    mfe_points = None
    mae_points = None
    mfe_r = None
    mae_r = None
    if not ambiguous and exit_price is not None:
        pnl_points = round_to_tick(
            exit_price - entry_price
            if direction == "LONG"
            else entry_price - exit_price
        )
        result_r = pnl_points / risk_points
        observed = pd.DataFrame(scanned)
        if direction == "LONG":
            mfe_points = round_to_tick(
                max(0.0, float(observed["high"].max()) - entry_price)
            )
            mae_points = round_to_tick(
                max(0.0, entry_price - float(observed["low"].min()))
            )
        else:
            mfe_points = round_to_tick(
                max(0.0, entry_price - float(observed["low"].min()))
            )
            mae_points = round_to_tick(
                max(0.0, float(observed["high"].max()) - entry_price)
            )
        mfe_r = mfe_points / risk_points
        mae_r = mae_points / risk_points

    return {
        **common,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "exit_bar_close": exit_bar_close,
        "ambiguous": ambiguous,
        "ambiguity_reason": ambiguity_reason,
        "holding_bars": holding_bars,
        "holding_minutes": holding_minutes,
        "pnl_points": pnl_points,
        "result_r": result_r,
        "mfe_points": mfe_points,
        "mae_points": mae_points,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "excluded_from_performance": ambiguous,
    }
