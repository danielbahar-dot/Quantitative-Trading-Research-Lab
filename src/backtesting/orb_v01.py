"""Lean, auditable ORB v0.1 event simulation for 1-minute OHLC data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.features.opening_range import calculate_opening_range
from src.research_harness import ExperimentLedger


OR_DURATIONS = (5, 10, 15, 30)
BREAKOUT_TYPES = ("PRINT", "CLOSE")
ENTRY_CUTOFF = time(11, 30)
REGULAR_SESSION_END = time(16, 0)


@dataclass(frozen=True)
class Breakout:
    direction: str
    timestamp: pd.Timestamp
    entry: float
    entry_at_open: bool


def load_bars(path: str | Path) -> pd.DataFrame:
    """Load and validate the columns needed by the baseline."""
    required = ["timestamp_et", "session_date", "contract", "open", "high", "low", "close"]
    bars = pd.read_csv(path, usecols=required)
    bars["timestamp_et"] = pd.to_datetime(bars["timestamp_et"], utc=True).dt.tz_convert(
        "America/New_York"
    )
    bars["session_date"] = pd.to_datetime(bars["session_date"]).dt.date
    bars = bars.sort_values(["session_date", "timestamp_et"]).set_index("timestamp_et")
    if bars.index.isna().any() or bars[required[2:]].isna().any().any():
        raise ValueError("Required input columns contain null values")
    if bars.reset_index().duplicated(["session_date", "timestamp_et"]).any():
        raise ValueError("Duplicate timestamps found within a session")
    bad_ohlc = (
        (bars["high"] < bars[["open", "close"]].max(axis=1))
        | (bars["low"] > bars[["open", "close"]].min(axis=1))
        | (bars["high"] < bars["low"])
    )
    if bad_ohlc.any():
        raise ValueError(f"Invalid OHLC rows found: {int(bad_ohlc.sum())}")
    return bars


def _find_breakouts(
    eligible: pd.DataFrame,
    or_high: float,
    or_low: float,
    breakout_type: str,
) -> tuple[list[Breakout], int]:
    found: dict[str, Breakout] = {}
    ambiguous_bars = 0
    for timestamp, bar in eligible.iterrows():
        if breakout_type == "PRINT":
            long_break = bool(bar["high"] > or_high)
            short_break = bool(bar["low"] < or_low)
            if long_break and short_break:
                ambiguous_bars += 1
                continue
            if long_break and "LONG" not in found:
                at_open = bool(bar["open"] > or_high)
                found["LONG"] = Breakout(
                    "LONG", timestamp, float(bar["open"] if at_open else or_high), at_open
                )
            if short_break and "SHORT" not in found:
                at_open = bool(bar["open"] < or_low)
                found["SHORT"] = Breakout(
                    "SHORT", timestamp, float(bar["open"] if at_open else or_low), at_open
                )
        else:
            if bar["close"] > or_high and "LONG" not in found:
                found["LONG"] = Breakout("LONG", timestamp, float(bar["close"]), False)
            if bar["close"] < or_low and "SHORT" not in found:
                found["SHORT"] = Breakout("SHORT", timestamp, float(bar["close"]), False)
        if len(found) == 2:
            break
    return list(found.values()), ambiguous_bars


def _simulate_trade(
    session_bars: pd.DataFrame,
    breakout: Breakout,
    breakout_type: str,
    or_mid: float,
) -> dict[str, Any]:
    direction = breakout.direction
    entry = breakout.entry
    stop = or_mid
    risk = entry - stop if direction == "LONG" else stop - entry
    target = entry + 2.0 * risk if direction == "LONG" else entry - 2.0 * risk
    if risk <= 0:
        raise ValueError("Non-positive entry-to-midpoint risk")

    session_exit_bars = session_bars.between_time(time(9, 30), REGULAR_SESSION_END)
    path = session_exit_bars.loc[session_exit_bars.index >= breakout.timestamp]
    if breakout_type == "CLOSE":
        path = path.loc[path.index > breakout.timestamp]

    exit_timestamp: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason = ""
    ambiguity_reason = ""

    for timestamp, bar in path.iterrows():
        stop_hit = bool(bar["low"] <= stop) if direction == "LONG" else bool(bar["high"] >= stop)
        target_hit = bool(bar["high"] >= target) if direction == "LONG" else bool(bar["low"] <= target)
        if stop_hit and target_hit:
            exit_timestamp = timestamp
            ambiguity_reason = "stop_and_target_same_bar"
            break
        is_entry_bar = timestamp == breakout.timestamp
        if is_entry_bar and breakout_type == "PRINT" and stop_hit and not breakout.entry_at_open:
            exit_timestamp = timestamp
            ambiguity_reason = "entry_and_stop_order_unknown"
            break
        if stop_hit:
            exit_timestamp, exit_price, exit_reason = timestamp, stop, "STOP"
            break
        if target_hit:
            exit_timestamp, exit_price, exit_reason = timestamp, target, "TARGET"
            break

    if exit_timestamp is None:
        if session_exit_bars.empty:
            ambiguity_reason = "no_regular_session_exit_bar"
        else:
            last_timestamp = session_exit_bars.index[-1]
            if last_timestamp < breakout.timestamp:
                ambiguity_reason = "no_exit_bar_after_entry"
            else:
                exit_timestamp = last_timestamp
                exit_price = float(session_exit_bars.iloc[-1]["close"])
                exit_reason = "SESSION_CLOSE"

    excluded = bool(ambiguity_reason)
    if excluded or exit_price is None:
        result_r = None
    else:
        pnl = exit_price - entry if direction == "LONG" else entry - exit_price
        result_r = pnl / risk

    return {
        "direction": direction,
        "breakout_timestamp": breakout.timestamp.isoformat(),
        "entry": entry,
        "stop": stop,
        "target": target,
        "exit_timestamp": exit_timestamp.isoformat() if exit_timestamp is not None else None,
        "exit_price": exit_price,
        "exit_reason": exit_reason or "AMBIGUOUS",
        "result_R": result_r,
        "breakout_ambiguous_same_bar": False,
        "exit_ambiguous": excluded,
        "ambiguity_reason": ambiguity_reason,
        "excluded_from_performance": excluded,
    }


def run_orb_variant(
    bars: pd.DataFrame,
    duration_minutes: int,
    breakout_type: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Simulate one duration/breakout variant and return trades plus counters."""
    breakout_type = breakout_type.upper()
    if breakout_type not in BREAKOUT_TYPES:
        raise ValueError(f"Unknown breakout type: {breakout_type}")

    rows: list[dict[str, Any]] = []
    valid_sessions = 0
    invalid_sessions = 0
    ambiguous_breakout_bars = 0
    for session_date, session_bars in bars.groupby("session_date", sort=True):
        opening_range = calculate_opening_range(session_bars, duration_minutes)
        if opening_range is None:
            invalid_sessions += 1
            continue
        valid_sessions += 1
        or_end = opening_range["end_timestamp"]
        eligible = session_bars.loc[
            (session_bars.index > or_end)
            & (session_bars.index.time <= ENTRY_CUTOFF)
            & (session_bars.index.time >= time(9, 30))
        ]
        breakouts, skipped = _find_breakouts(
            eligible,
            float(opening_range["or_high"]),
            float(opening_range["or_low"]),
            breakout_type,
        )
        ambiguous_breakout_bars += skipped
        contracts = session_bars["contract"].dropna().unique()
        contract = str(contracts[0]) if len(contracts) == 1 else "MULTIPLE"
        for breakout in breakouts:
            trade = _simulate_trade(
                session_bars, breakout, breakout_type, float(opening_range["or_mid"])
            )
            trade.update(
                {
                    "session_date": str(session_date),
                    "contract": contract,
                    "or_minutes": duration_minutes,
                    "breakout_type": breakout_type,
                    "or_high": opening_range["or_high"],
                    "or_low": opening_range["or_low"],
                    "or_mid": opening_range["or_mid"],
                }
            )
            rows.append(trade)

    trades = pd.DataFrame(rows)
    counters = {
        "total_sessions": int(bars["session_date"].nunique()),
        "valid_or_sessions": valid_sessions,
        "invalid_or_sessions": invalid_sessions,
        "ambiguous_breakout_bars_skipped": ambiguous_breakout_bars,
    }
    return trades, counters


def _variant_metrics(
    trades: pd.DataFrame,
    counters: dict[str, Any],
    duration: int,
    breakout_type: str,
) -> dict[str, Any]:
    included = trades.loc[~trades["excluded_from_performance"]].copy() if not trades.empty else trades
    results = included["result_R"].dropna() if not included.empty else pd.Series(dtype=float)
    wins = results.loc[results > 0]
    losses = results.loc[results < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    return {
        "or_minutes": duration,
        "breakout_type": breakout_type,
        **counters,
        "trades_triggered": int(len(trades)),
        "trades_included": int(len(results)),
        "ambiguous_trades_excluded": int(trades["excluded_from_performance"].sum()) if not trades.empty else 0,
        "wins": int((results > 0).sum()),
        "losses": int((results < 0).sum()),
        "breakeven": int((results == 0).sum()),
        "win_rate_pct": float((results > 0).mean() * 100.0) if len(results) else None,
        "average_R": float(results.mean()) if len(results) else None,
        "total_R": float(results.sum()),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "session_close_exits": int((included["exit_reason"] == "SESSION_CLOSE").sum()) if not included.empty else 0,
    }


def run_all_variants(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    trade_frames: list[pd.DataFrame] = []
    metric_rows: list[dict[str, Any]] = []
    for duration in OR_DURATIONS:
        for breakout_type in BREAKOUT_TYPES:
            trades, counters = run_orb_variant(bars, duration, breakout_type)
            trade_frames.append(trades)
            metric_rows.append(_variant_metrics(trades, counters, duration, breakout_type))
    all_trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    return all_trades, pd.DataFrame(metric_rows), metric_rows


def build_config() -> dict[str, Any]:
    return {
        "strategy_name": "ORB",
        "strategy_version": "0.1.0",
        "hypothesis": "MNQ breaks of a complete 09:30 ET opening range have positive gross expectancy.",
        "dataset": "data/MNQ_raw_cleaned_ET.csv",
        "timeframe": "1 minute OHLC",
        "session": {
            "timezone": "America/New_York",
            "opening_range_start": "09:30",
            "entry_cutoff_inclusive": "11:30",
            "position_exit": "last available bar at or before 16:00 ET",
        },
        "parameters": {
            "opening_range_minutes": list(OR_DURATIONS),
            "breakout_types": list(BREAKOUT_TYPES),
            "max_per_direction_per_session": 1,
            "stop": "opening_range_midpoint",
            "target_R": 2.0,
            "fvg_filter": False,
            "print_fill": "OR boundary; bar open when it gaps beyond boundary",
            "close_fill": "breakout bar close",
        },
        "costs_slippage": {
            "commission_usd": 0.0,
            "slippage_points": 0.0,
            "note": "Gross baseline; costs and slippage were not specified.",
        },
        "notes": (
            "Ambiguous stop/target bars and unknown PRINT entry/stop ordering are excluded. "
            "Same-bar long+short PRINT breakouts are skipped. No FVG, EMA, VWAP, or trailing stop."
        ),
    }


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    bars = load_bars(project_root / "data" / "MNQ_raw_cleaned_ET.csv")
    ledger = ExperimentLedger(project_root)
    run_id, run_dir = ledger.create_run(build_config())
    trades, summary, metrics = run_all_variants(bars)

    trades_path = run_dir / "trades.csv"
    summary_path = run_dir / "summary.csv"
    metrics_path = run_dir / "metrics.json"
    viewer_path = run_dir / "nt8_research_viewer.csv"
    trades.to_csv(trades_path, index=False)
    summary.to_csv(summary_path, index=False)

    totals = {
        "run_id": run_id,
        "variants": metrics,
        "overall": {
            "trades_triggered": int(len(trades)),
            "trades_included": int((~trades["excluded_from_performance"]).sum()),
            "ambiguous_trades_excluded": int(trades["excluded_from_performance"].sum()),
            "ambiguous_breakout_bars_skipped": int(summary["ambiguous_breakout_bars_skipped"].sum()),
        },
    }
    metrics_path.write_text(json.dumps(totals, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    viewer_columns = [
        "session_date", "contract", "or_minutes", "breakout_type", "or_high", "or_low", "or_mid",
        "direction", "breakout_timestamp", "entry", "stop", "target", "exit_timestamp", "exit_price",
        "result_R", "breakout_ambiguous_same_bar", "exit_ambiguous", "ambiguity_reason",
        "excluded_from_performance",
    ]
    trades[viewer_columns].to_csv(viewer_path, index=False)
    ledger.update_run(
        run_id,
        results_summary=totals["overall"],
        notes=build_config()["notes"],
        artifact_paths={
            "trades": trades_path,
            "metrics": metrics_path,
            "summary": summary_path,
            "nt8_research_viewer": viewer_path,
        },
    )
    print(run_dir)
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
