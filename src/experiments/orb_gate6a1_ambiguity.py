"""Gate 6A.1 DEVELOPMENT-only PRINT entry-bar ambiguity sensitivity.

This module does not alter Gate 6A or the validated execution engine. It
resolves only existing AMBIGUOUS_ENTRY_STOP records under two explicit bounds:
entry-first (-1R) and adverse-excursion-first (scan from the next bar).
"""

from __future__ import annotations

import hashlib
import json
from datetime import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backtesting.candidate_entries import CANDIDATE_COLUMNS, round_to_tick
from src.backtesting.completed_trades import (
    AMBIGUOUS_ENTRY_STOP,
    AMBIGUOUS_STOP_TARGET,
    MISSING_SESSION_EXIT_BAR,
    REGULAR_SESSION_END,
    SESSION_END,
    STOP,
    STOP_TARGET_ORDER_UNKNOWN,
    TARGET,
    TRADE_COLUMNS,
    simulate_completed_trades,
)
from src.backtesting.session_trade_limit import EXECUTED, SESSION_TRADE_LIMIT, apply_session_trade_limit
from src.experiments.orb_v01_baseline import calculate_max_drawdown_r, max_consecutive_losses


OR_DURATIONS = (10, 15, 20, 30)
TARGET_R_VALUES = (1.0, 1.5, 2.0, 2.5, 3.0)
SCENARIOS = ("PESSIMISTIC", "OBSERVED", "OPTIMISTIC")
STOP_FRACTION = 0.25
EXPECTED_CONFIGURATIONS = 20
EXPECTED_SCENARIO_ROWS = 60

KEY_COLUMNS = ["session_date", "or_minutes", "breakout_type", "direction", "signal_time"]
METRIC_COLUMNS = [
    "or_minutes", "target_r", "scenario", "total_eligible_candidates",
    "ambiguous_entry_stop_candidates", "ambiguity_rate", "executed_trades",
    "wins", "losses", "flat_trades", "session_end_exits", "win_rate",
    "average_r", "median_r", "total_r", "profit_factor_r", "max_drawdown_r",
    "max_consecutive_losses", "positive_month_percentage",
    "rolling_50_min_average_r", "rolling_100_min_average_r",
    "rolling_100_positive_window_percentage", "average_holding_minutes",
    "scenario_session_trade_limit_rejections",
]


def load_gate6a_inputs(
    candidate_audit_path: str | Path,
    sweep_summary_path: str | Path,
    *,
    development_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load only the 20 Gate 6A 25%-stop DEVELOPMENT configurations."""
    audit = pd.read_csv(candidate_audit_path)
    summary = pd.read_csv(sweep_summary_path)
    audit = audit.loc[np.isclose(audit["stop_fraction"], STOP_FRACTION)].copy()
    summary = summary.loc[np.isclose(summary["stop_fraction"], STOP_FRACTION)].copy()
    audit["session_date"] = pd.to_datetime(audit["session_date"], errors="raise").dt.normalize()
    for column in ("signal_time", "entry_time"):
        audit[column] = pd.to_datetime(audit[column], errors="coerce", utc=True).dt.tz_convert("America/New_York")
    audit["candidate_validity"] = _to_boolean(audit["candidate_validity"], "candidate_validity")
    if not audit["session_date"].le(development_end).all():
        raise ValueError("A reserved-period candidate entered Gate 6A.1")
    if set(audit["or_minutes"].astype(int)) != set(OR_DURATIONS):
        raise ValueError("Gate 6A.1 candidate audit has unexpected durations")
    if len(summary) != EXPECTED_CONFIGURATIONS:
        raise ValueError("Gate 6A.1 requires exactly 20 Gate 6A configurations")
    if summary.duplicated(["or_minutes", "target_r"]).any():
        raise ValueError("Gate 6A.1 inputs contain duplicate configurations")
    return audit, summary


def run_sensitivity(
    price_data: pd.DataFrame,
    gate6_audit: pd.DataFrame,
    gate6_summary: pd.DataFrame,
    *,
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Calculate observed and chronology-bound scenarios for all 20 cells."""
    price_dates = pd.to_datetime(price_data["session_date"])
    if not price_dates.between(development_start, development_end).all():
        raise ValueError("Gate 6A.1 price input is not DEVELOPMENT-only")
    rows, trade_frames = [], []
    integrity = {}
    for (duration, target_r), config_audit in gate6_audit.groupby(
        ["or_minutes", "target_r"], sort=True
    ):
        duration, target_r = int(duration), float(target_r)
        candidates = _candidate_frame(config_audit)
        observed_completed = simulate_completed_trades(price_data, candidates)
        ambiguity_mask = observed_completed["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP)
        ambiguous_keys = set(
            observed_completed.loc[ambiguity_mask, KEY_COLUMNS].itertuples(index=False, name=None)
        )
        audit_count = int(config_audit["completed_trade_exit_reason"].eq(AMBIGUOUS_ENTRY_STOP).sum())
        if len(ambiguous_keys) != audit_count:
            raise ValueError("AMBIGUOUS_ENTRY_STOP count does not reconcile with Gate 6A")

        completed_by_scenario = {
            "OBSERVED": observed_completed,
            "PESSIMISTIC": resolve_pessimistic(observed_completed),
            "OPTIMISTIC": resolve_optimistic(
                price_data, candidates, observed_completed, session_end=REGULAR_SESSION_END
            ),
        }
        for scenario in SCENARIOS:
            completed = completed_by_scenario[scenario]
            executed, scenario_audit = apply_session_trade_limit(candidates, completed)
            _assert_daily_selection(candidates, completed, executed, scenario_audit)
            if executed.duplicated(["session_date", "or_minutes", "breakout_type"]).any():
                raise ValueError("A Gate 6A.1 scenario exceeds one trade per session")
            if scenario == "PESSIMISTIC":
                resolved = completed.loc[completed["trade_id"].isin(
                    observed_completed.loc[ambiguity_mask, "trade_id"]
                )]
                if not resolved["result_r"].eq(-1.0).all():
                    raise ValueError("A pessimistic entry-stop record is not -1R")
            annotated = executed.copy()
            annotated.insert(0, "scenario", scenario)
            annotated.insert(0, "config_id", config_audit.iloc[0]["config_id"])
            annotated.insert(2, "stop_fraction", STOP_FRACTION)
            annotated.insert(3, "target_r", target_r)
            trade_frames.append(annotated)
            rows.append(_scenario_metrics(
                duration, target_r, scenario, candidates, executed,
                len(ambiguous_keys), scenario_audit,
            ))
        integrity[f"{duration}m_{target_r:g}R"] = {
            "eligible_candidates": len(candidates),
            "ambiguous_entry_stop_candidates": len(ambiguous_keys),
        }

    metrics = add_sensitivity_bounds(pd.DataFrame(rows))
    trades = pd.concat(trade_frames, ignore_index=True)
    _validate_sensitivity(metrics, trades, gate6_summary, development_start, development_end)
    metadata = {
        "experiment_id": "orb_gate6a1_dev_25pct_ambiguity_sensitivity",
        "research_scope": "DEVELOPMENT_ONLY",
        "development_start": development_start.date().isoformat(),
        "development_end": development_end.date().isoformat(),
        "maximum_session_date_analyzed": pd.to_datetime(trades["session_date"]).max().date().isoformat(),
        "configuration_count": EXPECTED_CONFIGURATIONS,
        "scenario_rows": EXPECTED_SCENARIO_ROWS,
        "scenarios": list(SCENARIOS),
        "pessimistic_convention": "Entry first, then same-bar stop: executed -1R trade.",
        "optimistic_convention": (
            "The adverse entry-bar excursion occurs before entry. The entry bar is "
            "not used for any further stop/target inference; evaluation begins at "
            "the immediately following one-minute bar."
        ),
        "gate6a_inputs": integrity,
        "validated_execution_engine_modified": False,
        "signal_generation_modified": False,
    }
    return metrics, trades, metadata


def resolve_pessimistic(observed: pd.DataFrame) -> pd.DataFrame:
    """Resolve every entry-bar stop ambiguity as a definite -1R stop."""
    output = observed.copy()
    mask = output["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP)
    output.loc[mask, "exit_price"] = output.loc[mask, "initial_stop"]
    output.loc[mask, "exit_reason"] = STOP
    output.loc[mask, "ambiguous"] = False
    output.loc[mask, "ambiguity_reason"] = ""
    output.loc[mask, "holding_bars"] = 1
    output.loc[mask, "holding_minutes"] = 0
    output.loc[mask, "pnl_points"] = -output.loc[mask, "risk_points"]
    output.loc[mask, "result_r"] = -1.0
    output.loc[mask, ["mfe_points", "mae_points", "mfe_r", "mae_r"]] = np.nan
    output.loc[mask, "excluded_from_performance"] = False
    return output.loc[:, TRADE_COLUMNS]


def resolve_optimistic(
    price_data: pd.DataFrame,
    candidates: pd.DataFrame,
    observed: pd.DataFrame,
    *,
    session_end: time = REGULAR_SESSION_END,
) -> pd.DataFrame:
    """Resolve entry-bar ambiguity by beginning evaluation on the next bar."""
    candidate_lookup = {
        tuple(getattr(candidate, column) for column in KEY_COLUMNS): candidate
        for candidate in candidates.itertuples(index=False)
    }
    session_lookup = {
        session_date: group
        for session_date, group in price_data.groupby("session_date", sort=False)
    }
    rows = []
    for trade in observed.itertuples(index=False):
        if trade.exit_reason != AMBIGUOUS_ENTRY_STOP:
            rows.append(trade._asdict())
            continue
        key = tuple(getattr(trade, column) for column in KEY_COLUMNS)
        candidate = candidate_lookup[key]
        rows.append(
            _simulate_after_entry_bar(
                session_lookup.get(candidate.session_date), candidate, session_end
            )
        )
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def _simulate_after_entry_bar(session_prices, candidate, session_end: time) -> dict:
    """Sensitivity-only simulation that deliberately skips the PRINT entry bar."""
    direction = str(candidate.direction).upper()
    entry_time = pd.Timestamp(candidate.entry_time)
    signal_time = pd.Timestamp(candidate.signal_time)
    entry_price = float(candidate.entry_price)
    stop = float(candidate.initial_stop)
    target = float(candidate.initial_target)
    risk = float(candidate.risk_points)
    deadline = pd.Timestamp.combine(candidate.session_date, session_end)
    if entry_time.tzinfo is not None:
        deadline = deadline.tz_localize(entry_time.tzinfo)
    next_bar_time = entry_time + pd.Timedelta(minutes=1)
    path = (
        session_prices.loc[
            (session_prices.index >= next_bar_time) & (session_prices.index <= deadline)
        ]
        if session_prices is not None else pd.DataFrame()
    )
    common = {
        "trade_id": (
            f"{candidate.session_date.isoformat()}_{int(candidate.or_minutes)}m_"
            f"PRINT_{direction}_{signal_time.strftime('%H%M')}"
        ),
        "session_date": candidate.session_date,
        "contract": candidate.contract,
        "or_minutes": int(candidate.or_minutes),
        "breakout_type": "PRINT",
        "direction": direction,
        "signal_time": signal_time,
        "entry_time": entry_time,
        "entry_price": entry_price,
        "initial_stop": stop,
        "initial_target": target,
        "risk_points": risk,
    }
    if path.empty or path.index[0] != next_bar_time:
        return {
            **common, "exit_time": pd.NaT, "exit_price": None,
            "exit_reason": MISSING_SESSION_EXIT_BAR, "exit_bar_close": None,
            "ambiguous": True, "ambiguity_reason": MISSING_SESSION_EXIT_BAR,
            "holding_bars": 0, "holding_minutes": None, "pnl_points": None,
            "result_r": None, "mfe_points": None, "mae_points": None,
            "mfe_r": None, "mae_r": None, "excluded_from_performance": True,
        }

    scanned, exit_time, exit_price, exit_reason = [], None, None, ""
    ambiguity_reason, exit_bar_close = "", None
    for timestamp, bar in path.iterrows():
        scanned.append(bar)
        stop_hit = bool(bar["low"] <= stop) if direction == "LONG" else bool(bar["high"] >= stop)
        target_hit = bool(bar["high"] >= target) if direction == "LONG" else bool(bar["low"] <= target)
        if stop_hit and target_hit:
            exit_time, exit_reason = timestamp, AMBIGUOUS_STOP_TARGET
            ambiguity_reason = STOP_TARGET_ORDER_UNKNOWN
            exit_bar_close = round_to_tick(float(bar["close"]))
            break
        if target_hit:
            exit_time, exit_price, exit_reason = timestamp, target, TARGET
            exit_bar_close = round_to_tick(float(bar["close"]))
            break
        if stop_hit:
            exit_time, exit_price, exit_reason = timestamp, stop, STOP
            exit_bar_close = round_to_tick(float(bar["close"]))
            break
    if exit_time is None:
        exit_time = path.index[-1]
        exit_price = round_to_tick(float(path.iloc[-1]["close"]))
        exit_reason = SESSION_END
        exit_bar_close = exit_price

    ambiguous = bool(ambiguity_reason)
    holding_minutes = int((exit_time - entry_time) / pd.Timedelta(minutes=1))
    pnl, result_r, mfe, mae, mfe_r, mae_r = (None,) * 6
    if not ambiguous and exit_price is not None:
        pnl = round_to_tick(
            exit_price - entry_price if direction == "LONG" else entry_price - exit_price
        )
        result_r = pnl / risk
        observed_bars = pd.DataFrame(scanned)
        if direction == "LONG":
            mfe = round_to_tick(max(0.0, float(observed_bars["high"].max()) - entry_price))
            mae = round_to_tick(max(0.0, entry_price - float(observed_bars["low"].min())))
        else:
            mfe = round_to_tick(max(0.0, entry_price - float(observed_bars["low"].min())))
            mae = round_to_tick(max(0.0, float(observed_bars["high"].max()) - entry_price))
        mfe_r, mae_r = mfe / risk, mae / risk
    return {
        **common, "exit_time": exit_time, "exit_price": exit_price,
        "exit_reason": exit_reason, "exit_bar_close": exit_bar_close,
        "ambiguous": ambiguous, "ambiguity_reason": ambiguity_reason,
        "holding_bars": len(scanned), "holding_minutes": holding_minutes,
        "pnl_points": pnl, "result_r": result_r, "mfe_points": mfe,
        "mae_points": mae, "mfe_r": mfe_r, "mae_r": mae_r,
        "excluded_from_performance": ambiguous,
    }


def _candidate_frame(config_audit: pd.DataFrame) -> pd.DataFrame:
    output = config_audit.loc[:, CANDIDATE_COLUMNS].copy()
    output["session_date"] = pd.to_datetime(output["session_date"]).dt.date
    output["or_minutes"] = output["or_minutes"].astype(int)
    output["candidate_validity"] = _to_boolean(output["candidate_validity"], "candidate_validity")
    return output


def _scenario_metrics(
    duration: int, target_r: float, scenario: str, candidates: pd.DataFrame,
    executed: pd.DataFrame, ambiguous_count: int, audit: pd.DataFrame,
) -> dict[str, Any]:
    values = executed["result_r"].astype(float)
    positive, negative = values.loc[values.gt(0)], values.loc[values.lt(0)]
    gross_loss = abs(float(negative.sum()))
    ordered = executed.sort_values(["entry_time", "signal_time", "trade_id"], kind="stable")
    rolling_50 = ordered["result_r"].astype(float).rolling(50, min_periods=50).mean().dropna()
    rolling_100 = ordered["result_r"].astype(float).rolling(100, min_periods=100).mean().dropna()
    monthly = (
        executed.assign(month=pd.to_datetime(executed["session_date"]).dt.to_period("M").astype(str))
        .groupby("month", sort=True)["result_r"].sum()
    )
    return {
        "or_minutes": duration, "target_r": target_r, "scenario": scenario,
        "total_eligible_candidates": len(candidates),
        "ambiguous_entry_stop_candidates": ambiguous_count,
        "ambiguity_rate": ambiguous_count / len(candidates),
        "executed_trades": len(executed), "wins": int(values.gt(0).sum()),
        "losses": int(values.lt(0).sum()), "flat_trades": int(values.eq(0).sum()),
        "session_end_exits": int(executed["exit_reason"].eq(SESSION_END).sum()),
        "win_rate": float(values.gt(0).mean()), "average_r": float(values.mean()),
        "median_r": float(values.median()), "total_r": float(values.sum()),
        "profit_factor_r": float(positive.sum()) / gross_loss if gross_loss else 0.0,
        "max_drawdown_r": calculate_max_drawdown_r(values),
        "max_consecutive_losses": max_consecutive_losses(values),
        "positive_month_percentage": float(monthly.gt(0).mean() * 100),
        "rolling_50_min_average_r": float(rolling_50.min()),
        "rolling_100_min_average_r": float(rolling_100.min()),
        "rolling_100_positive_window_percentage": float(rolling_100.gt(0).mean() * 100),
        "average_holding_minutes": float(executed["holding_minutes"].mean()),
        "scenario_session_trade_limit_rejections": int(
            audit["rejection_reason"].eq(SESSION_TRADE_LIMIT).sum()
        ),
    }


def add_sensitivity_bounds(metrics: pd.DataFrame) -> pd.DataFrame:
    pivot_avg = metrics.pivot(index=["or_minutes", "target_r"], columns="scenario", values="average_r")
    pivot_pf = metrics.pivot(index=["or_minutes", "target_r"], columns="scenario", values="profit_factor_r")
    bounds = pd.DataFrame({
        "pessimistic_average_r": pivot_avg["PESSIMISTIC"],
        "observed_average_r": pivot_avg["OBSERVED"],
        "optimistic_average_r": pivot_avg["OPTIMISTIC"],
        "average_r_sensitivity_width": pivot_avg["OPTIMISTIC"] - pivot_avg["PESSIMISTIC"],
        "pessimistic_profit_factor_r": pivot_pf["PESSIMISTIC"],
        "observed_profit_factor_r": pivot_pf["OBSERVED"],
        "optimistic_profit_factor_r": pivot_pf["OPTIMISTIC"],
        "profit_factor_sensitivity_width": pivot_pf["OPTIMISTIC"] - pivot_pf["PESSIMISTIC"],
    }).reset_index()
    return metrics.merge(bounds, on=["or_minutes", "target_r"], validate="many_to_one")


def _assert_daily_selection(candidates, completed, executed, audit) -> None:
    completed_lookup = {
        tuple(getattr(row, column) for column in KEY_COLUMNS): row
        for row in completed.itertuples(index=False)
    }
    ordered = candidates.assign(
        _sort_time=candidates["entry_time"].where(
            candidates["entry_time"].notna(), candidates["signal_time"]
        )
    ).sort_values(
        ["session_date", "or_minutes", "breakout_type", "_sort_time", "signal_time", "direction"],
        kind="stable",
    )
    expected_keys = []
    for _, group in ordered.groupby(["session_date", "or_minutes", "breakout_type"], sort=False):
        selected = None
        for candidate in group.drop(columns="_sort_time").itertuples(index=False):
            key = tuple(getattr(candidate, column) for column in KEY_COLUMNS)
            trade = completed_lookup.get(key)
            if (
                candidate.candidate_validity and trade is not None
                and not trade.ambiguous and not trade.excluded_from_performance
            ):
                selected = key
                break
        if selected is not None:
            expected_keys.append(selected)
    actual_keys = [
        tuple(getattr(row, column) for column in KEY_COLUMNS)
        for row in executed.itertuples(index=False)
    ]
    if set(actual_keys) != set(expected_keys):
        raise ValueError("Scenario daily selection is not the earliest executable candidate")
    executed_audit = audit.loc[audit["gate4d_status"].eq(EXECUTED)]
    if len(executed_audit) != len(expected_keys):
        raise ValueError("Scenario audit does not reconcile with executed trades")


def _validate_sensitivity(metrics, trades, gate6_summary, start, end) -> None:
    if len(metrics) != EXPECTED_SCENARIO_ROWS:
        raise ValueError("Gate 6A.1 must contain exactly 60 scenario rows")
    if metrics[["or_minutes", "target_r"]].drop_duplicates().shape[0] != EXPECTED_CONFIGURATIONS:
        raise ValueError("Gate 6A.1 must contain exactly 20 configurations")
    scenario_counts = metrics.groupby(["or_minutes", "target_r"])["scenario"].nunique()
    if not scenario_counts.eq(3).all():
        raise ValueError("Every Gate 6A.1 configuration must contain three scenarios")
    if set(metrics["scenario"]) != set(SCENARIOS):
        raise ValueError("Gate 6A.1 has unexpected scenarios")
    dates = pd.to_datetime(trades["session_date"])
    if not dates.between(start, end).all() or dates.max() > pd.Timestamp("2025-06-30"):
        raise ValueError("A reserved-period trade entered Gate 6A.1")
    if trades.duplicated(["config_id", "scenario", "session_date"]).any():
        raise ValueError("A scenario executed duplicate same-session trades")
    observed = metrics.loc[metrics["scenario"].eq("OBSERVED")]
    comparisons = {
        "executed_trades": "trades", "wins": "wins", "losses": "losses",
        "session_end_exits": "session_end_exits", "win_rate": "win_rate",
        "average_r": "average_r", "median_r": "median_r", "total_r": "total_r",
        "profit_factor_r": "profit_factor_r", "max_drawdown_r": "max_drawdown_r",
        "max_consecutive_losses": "max_consecutive_losses",
        "positive_month_percentage": "positive_month_percentage",
        "rolling_50_min_average_r": "rolling_50_min_average_r",
        "rolling_100_min_average_r": "rolling_100_min_average_r",
        "rolling_100_positive_window_percentage": "rolling_100_positive_window_percentage",
        "average_holding_minutes": "average_holding_minutes",
    }
    left_columns = ["or_minutes", "target_r", *comparisons.keys()]
    right_columns = ["or_minutes", "target_r", *comparisons.values()]
    left = observed.loc[:, left_columns].rename(
        columns={column: f"sensitivity_{column}" for column in comparisons}
    )
    right = gate6_summary.loc[:, right_columns].rename(
        columns={column: f"gate6_{column}" for column in comparisons.values()}
    )
    merged = left.merge(right, on=["or_minutes", "target_r"], validate="one_to_one")
    for sensitivity_column, gate6_column in comparisons.items():
        sensitivity_values = pd.to_numeric(merged[f"sensitivity_{sensitivity_column}"])
        gate6_values = pd.to_numeric(merged[f"gate6_{gate6_column}"])
        if not np.allclose(
            sensitivity_values, gate6_values,
            rtol=0, atol=1e-12, equal_nan=True,
        ):
            raise ValueError(f"OBSERVED does not reproduce Gate 6A: {sensitivity_column}")


def write_outputs(
    metrics: pd.DataFrame,
    trades: pd.DataFrame,
    metadata: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "orb_gate6a1_DEV_25pct_ambiguity"
    paths = {
        "sensitivity": output_dir / f"{prefix}_sensitivity.csv",
        "trades": output_dir / f"{prefix}_trades.csv",
        "metadata": output_dir / f"{prefix}_metadata.json",
        "ambiguity_heatmap": output_dir / f"{prefix}_rate_heatmap.html",
        "average_r_bounds": output_dir / f"{prefix}_average_r_bounds.html",
        "sensitivity_width_heatmap": output_dir / f"{prefix}_sensitivity_width_heatmap.html",
        "profit_factor_bounds": output_dir / f"{prefix}_profit_factor_bounds.html",
    }
    metrics.to_csv(paths["sensitivity"], index=False)
    _csv_ready(trades).to_csv(paths["trades"], index=False)
    _write_metric_heatmap(
        metrics.loc[metrics["scenario"].eq("OBSERVED")], "ambiguity_rate",
        "Entry-bar ambiguity rate", paths["ambiguity_heatmap"], percentage=True,
    )
    _write_scenario_lines(metrics, "average_r", "Average R", paths["average_r_bounds"])
    _write_metric_heatmap(
        metrics.loc[metrics["scenario"].eq("OBSERVED")],
        "average_r_sensitivity_width", "Optimistic Avg R - Pessimistic Avg R",
        paths["sensitivity_width_heatmap"], percentage=False,
    )
    _write_scenario_lines(
        metrics, "profit_factor_r", "Profit Factor (R)", paths["profit_factor_bounds"]
    )
    metadata = {**metadata, "artifacts": {key: str(value) for key, value in paths.items()}}
    paths["metadata"].write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return paths


def _write_metric_heatmap(frame, metric, label, path, *, percentage: bool) -> None:
    pivot = frame.pivot(index="or_minutes", columns="target_r", values=metric).reindex(
        index=OR_DURATIONS, columns=TARGET_R_VALUES
    )
    values = pivot.to_numpy(dtype=float) * (100 if percentage else 1)
    suffix = "%" if percentage else ""
    figure = go.Figure(go.Heatmap(
        z=values, x=[f"{value:g}R" for value in TARGET_R_VALUES],
        y=[f"{value}m" for value in OR_DURATIONS], colorscale="YlOrRd",
        text=np.vectorize(lambda value: f"{value:.2f}{suffix}")(values),
        texttemplate="%{text}", hovertemplate=(
            "OR: %{y}<br>Target: %{x}<br>" + label + ": %{text}<extra></extra>"
        ), colorbar={"title": label},
    ))
    figure.update_layout(
        title=f"Gate 6A.1 — {label} — DEVELOPMENT ONLY",
        xaxis_title="Target R", yaxis_title="OR duration", template="plotly_white",
        height=580, width=940,
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def _write_scenario_lines(metrics, metric, label, path) -> None:
    figure = make_subplots(
        rows=2, cols=2, subplot_titles=tuple(f"{value}m PRINT" for value in OR_DURATIONS)
    )
    colors = {"PESSIMISTIC": "#c62828", "OBSERVED": "#455a64", "OPTIMISTIC": "#2e7d32"}
    for index, duration in enumerate(OR_DURATIONS):
        row, column = index // 2 + 1, index % 2 + 1
        subset = metrics.loc[metrics["or_minutes"].eq(duration)]
        for scenario in SCENARIOS:
            selected = subset.loc[subset["scenario"].eq(scenario)].sort_values("target_r")
            figure.add_trace(go.Scatter(
                x=selected["target_r"], y=selected[metric], mode="lines+markers",
                name=scenario, legendgroup=scenario, showlegend=index == 0,
                line={"color": colors[scenario]},
                hovertemplate=(
                    f"{duration}m {scenario}<br>Target: %{{x:g}}R<br>"
                    + label + ": %{y:.4f}<extra></extra>"
                ),
            ), row=row, col=column)
        if metric == "average_r":
            figure.add_hline(y=0, line_dash="dot", line_color="black", row=row, col=column)
        figure.update_xaxes(title_text="Target R", row=row, col=column)
        figure.update_yaxes(title_text=label, row=row, col=column)
    figure.update_layout(
        title=f"Gate 6A.1 — Pessimistic / Observed / Optimistic {label} — DEVELOPMENT ONLY",
        template="plotly_white", height=820, width=1200,
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def sha256_files(paths: list[str | Path]) -> dict[str, str]:
    hashes = {}
    for path in paths:
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        hashes[Path(path).name] = digest.hexdigest()
    return hashes


def _csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["session_date"] = output["session_date"].astype(str)
    for column in ("signal_time", "entry_time", "exit_time"):
        output[column] = output[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
    return output


def _to_boolean(values: pd.Series, column: str) -> pd.Series:
    if values.dtype == bool:
        return values
    mapped = values.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise ValueError(f"{column} contains non-boolean values")
    return mapped
