"""Gate 6B DEVELOPMENT-only fixed-target x static-stop study.

Signal discovery and the validated completed-trade/daily-limit layers remain
unchanged. Gate 6B derives only candidate stop and fixed target prices, while
capturing OR-width diagnostics for the later Gate 6B.1 hypothesis study.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backtesting.candidate_entries import (
    INVALID_ENTRY_RELATIVE_TO_STOP,
    build_candidate_entries,
    round_to_tick,
)
from src.backtesting.completed_trades import (
    AMBIGUOUS_ENTRY_STOP,
    SESSION_END,
    STOP,
    TARGET,
    simulate_completed_trades,
)
from src.backtesting.session_trade_limit import SESSION_TRADE_LIMIT, apply_session_trade_limit
from src.experiments.orb_gate6a_sweep import load_development_or_levels
from src.experiments.orb_v01_baseline import calculate_max_drawdown_r, max_consecutive_losses
from src.visualization.research_viewer import find_orb_signals


OR_DURATIONS = (15, 20, 30)
STOP_DEFINITIONS = (
    ("OR_MIDPOINT", "OR_FRACTION", 0.50),
    ("OR_25_RETRACEMENT", "OR_FRACTION", 0.25),
    ("FIXED_30", "FIXED_POINTS", 30.0),
    ("FIXED_40", "FIXED_POINTS", 40.0),
    ("FIXED_50", "FIXED_POINTS", 50.0),
)
TARGET_POINTS_VALUES = (40.0, 50.0, 60.0, 75.0, 100.0)
EXPECTED_CONFIGURATIONS = 75
BREAKOUT_TYPE = "PRINT"

KEY_COLUMNS = ["session_date", "or_minutes", "breakout_type", "direction", "signal_time"]
DIAGNOSTIC_COLUMNS = [
    "or_high", "or_low", "or_mid", "or_width_points", "stop_mode",
    "stop_definition_kind", "configured_stop_value", "stop_points",
    "stop_to_or_ratio", "target_points", "target_to_or_ratio",
    "initial_risk_points", "initial_reward_risk",
]

SUMMARY_COLUMNS = [
    "config_id", "research_scope", "development_start", "development_end",
    "or_minutes", "breakout_type", "stop_mode", "stop_definition_kind",
    "configured_stop_value", "target_points", "eligible_candidates",
    "signal_ambiguity_count", "entry_stop_ambiguity_count",
    "other_execution_ambiguity_count", "ambiguity_exclusion_count",
    "ambiguity_rate", "entry_stop_ambiguity_rate", "session_trade_limit_rejections",
    "executed_trades", "wins", "losses", "flat_trades", "session_end_exits",
    "win_rate", "average_r", "median_r", "total_r", "profit_factor_r",
    "max_drawdown_r", "max_consecutive_losses", "average_holding_minutes",
    "positive_month_percentage", "best_month_r", "worst_month_r",
    "rolling_50_min_average_r", "rolling_100_min_average_r",
    "rolling_100_positive_window_percentage", "target_hit_percentage",
    "stop_hit_percentage", "session_end_percentage", "average_or_width_points",
    "median_or_width_points", "average_initial_risk_points",
    "average_initial_reward_risk", "exact_prior_candidate_controls",
    "target_distance_verified", "stop_distance_verified",
    "max_one_trade_per_session_verified",
]


def configuration_grid() -> pd.DataFrame:
    rows = [
        {
            "config_id": _config_id(duration, stop_mode, target_points),
            "or_minutes": duration,
            "breakout_type": BREAKOUT_TYPE,
            "stop_mode": stop_mode,
            "stop_definition_kind": kind,
            "configured_stop_value": value,
            "target_points": target_points,
        }
        for duration in OR_DURATIONS
        for stop_mode, kind, value in STOP_DEFINITIONS
        for target_points in TARGET_POINTS_VALUES
    ]
    grid = pd.DataFrame(rows)
    if len(grid) != EXPECTED_CONFIGURATIONS:
        raise ValueError("Gate 6B grid must contain exactly 75 configurations")
    if grid["config_id"].duplicated().any():
        raise ValueError("Gate 6B configuration IDs are not unique")
    return grid


def build_gate6b_candidates(
    price_data: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    or_minutes: int,
    stop_mode: str,
    target_points: float,
) -> pd.DataFrame:
    """Derive Gate 6B prices from validated PRINT entry candidates."""
    definitions = {name: (kind, value) for name, kind, value in STOP_DEFINITIONS}
    if stop_mode not in definitions:
        raise ValueError(f"Unknown Gate 6B stop mode: {stop_mode}")
    if float(target_points) not in TARGET_POINTS_VALUES:
        raise ValueError("Target points are outside the approved Gate 6B grid")
    kind, configured_value = definitions[stop_mode]
    candidates = build_candidate_entries(
        price_data, signals, or_minutes=or_minutes,
        stop_fraction=0.5, target_r=2.0,
    ).copy()
    rows = []
    for candidate in candidates.itertuples(index=False):
        direction = str(candidate.direction)
        entry = float(candidate.entry_price)
        width = float(candidate.or_high) - float(candidate.or_low)
        if width <= 0:
            raise ValueError("OR width must be strictly positive")
        if kind == "OR_FRACTION":
            stop = round_to_tick(
                float(candidate.or_high) - configured_value * width
                if direction == "LONG"
                else float(candidate.or_low) + configured_value * width
            )
        else:
            stop = round_to_tick(
                entry - configured_value if direction == "LONG"
                else entry + configured_value
            )
        risk = round_to_tick(entry - stop if direction == "LONG" else stop - entry)
        target = round_to_tick(
            entry + target_points if direction == "LONG" else entry - target_points
        )
        invalid_reason = "" if risk > 0 else INVALID_ENTRY_RELATIVE_TO_STOP
        values = candidate._asdict()
        values.update({
            "initial_stop": stop,
            "risk_points": risk if risk > 0 else None,
            "initial_target": target if risk > 0 else None,
            "candidate_validity": risk > 0,
            "invalid_reason": invalid_reason,
            "or_width_points": width,
            "stop_mode": stop_mode,
            "stop_definition_kind": kind,
            "configured_stop_value": configured_value,
            "stop_points": risk if risk > 0 else None,
            "stop_to_or_ratio": risk / width if risk > 0 else None,
            "target_points": float(target_points),
            "target_to_or_ratio": float(target_points) / width,
            "initial_risk_points": risk if risk > 0 else None,
            "initial_reward_risk": float(target_points) / risk if risk > 0 else None,
        })
        rows.append(values)
    output = pd.DataFrame(rows)
    _validate_candidate_prices(output, stop_mode, float(target_points))
    return output


def _validate_candidate_prices(candidates, stop_mode, target_points) -> None:
    for candidate in candidates.itertuples(index=False):
        direction = candidate.direction
        target_distance = (
            candidate.initial_target - candidate.entry_price
            if direction == "LONG" else candidate.entry_price - candidate.initial_target
        )
        if not np.isclose(target_distance, target_points, rtol=0, atol=1e-12):
            raise ValueError("Fixed target distance is not exact")
        width = candidate.or_high - candidate.or_low
        if not np.isclose(candidate.or_width_points, width, rtol=0, atol=1e-12):
            raise ValueError("OR width calculation failed")
        if stop_mode.startswith("FIXED_"):
            expected = float(stop_mode.split("_")[1])
            if not np.isclose(candidate.risk_points, expected, rtol=0, atol=1e-12):
                raise ValueError("Fixed stop distance is not exact")
        if not np.isclose(candidate.target_to_or_ratio, target_points / width, rtol=0, atol=1e-12):
            raise ValueError("Target/OR ratio failed")
        if not np.isclose(candidate.stop_to_or_ratio, candidate.risk_points / width, rtol=0, atol=1e-12):
            raise ValueError("Stop/OR ratio failed")
        if not np.isclose(candidate.initial_reward_risk, target_points / candidate.risk_points, rtol=0, atol=1e-12):
            raise ValueError("Initial reward/risk failed")


def run_development_study(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
    gate6_signal_reference: pd.DataFrame,
    *,
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Run all 75 configurations through the validated execution pipeline."""
    dates = pd.to_datetime(price_data["session_date"])
    if not dates.between(development_start, development_end).all():
        raise ValueError("Gate 6B price data is not DEVELOPMENT-only")
    if dates.max() > pd.Timestamp("2025-06-30"):
        raise ValueError("Gate 6B price data extends beyond 2025-06-30")

    signal_cache, ambiguous_signal_cache = {}, {}
    baseline_candidate_cache, baseline_completed_cache = {}, {}
    for duration in OR_DURATIONS:
        signals, ambiguous = find_orb_signals(
            price_data, or_levels,
            start_date=development_start, end_date=development_end,
            or_minutes=duration, breakout_type=BREAKOUT_TYPE,
        )
        _assert_signal_reproduction(signals, gate6_signal_reference, duration)
        first_eligible_minute = {15: 46, 20: 51, 30: 1}[duration]
        if duration < 30:
            if not signals["signal_time"].map(
                lambda value: value.hour > 9 or value.minute >= first_eligible_minute
            ).all():
                raise ValueError("An ORB signal occurred before its eligible bar")
        elif not signals["signal_time"].map(
            lambda value: value.hour > 10 or (value.hour == 10 and value.minute >= 1)
        ).all():
            raise ValueError("A 30m signal occurred before 10:01")
        signal_cache[duration] = signals
        ambiguous_signal_cache[duration] = ambiguous
        baseline_candidates = build_candidate_entries(
            price_data, signals, or_minutes=duration,
            stop_fraction=0.5, target_r=2.0,
        )
        baseline_candidate_cache[duration] = baseline_candidates
        baseline_completed_cache[duration] = simulate_completed_trades(
            price_data, baseline_candidates
        )

    summary_rows, trade_frames, audit_frames, diagnostic_frames = [], [], [], []
    control_counts = {}
    for config in configuration_grid().itertuples(index=False):
        signals = signal_cache[config.or_minutes]
        candidates = build_gate6b_candidates(
            price_data, signals, or_minutes=config.or_minutes,
            stop_mode=config.stop_mode, target_points=config.target_points,
        )
        completed = simulate_completed_trades(price_data, candidates)
        _assert_completed_r_math(completed)
        executed, audit = apply_session_trade_limit(candidates, completed)
        if executed.duplicated(["session_date", "or_minutes", "breakout_type"]).any():
            raise ValueError("Gate 6B exceeds one executed trade per session")
        exact_controls = 0
        if config.stop_mode == "OR_MIDPOINT":
            exact_controls = _verify_exact_prior_candidate_controls(
                candidates, completed,
                baseline_candidate_cache[config.or_minutes],
                baseline_completed_cache[config.or_minutes],
            )
        control_counts[config.config_id] = exact_controls
        enriched_trades = _enrich_executed(executed, candidates, config)
        enriched_audit = _annotate_audit(audit, config)
        diagnostics = _build_or_width_diagnostics(
            enriched_audit, completed, config
        )
        trade_frames.append(enriched_trades)
        audit_frames.append(enriched_audit)
        diagnostic_frames.append(diagnostics)
        summary_rows.append(_configuration_metrics(
            config, candidates, completed, executed, enriched_trades,
            enriched_audit, ambiguous_signal_cache[config.or_minutes],
            development_start, development_end, exact_controls,
        ))

    summary = pd.DataFrame(summary_rows).loc[:, SUMMARY_COLUMNS]
    trades = pd.concat(trade_frames, ignore_index=True)
    audit = pd.concat(audit_frames, ignore_index=True)
    diagnostics = pd.concat(diagnostic_frames, ignore_index=True)
    _validate_outputs(summary, trades, diagnostics, development_start, development_end)
    metadata = {
        "experiment_id": "orb_gate6b_dev_fixed_target_stop",
        "research_scope": "DEVELOPMENT_ONLY",
        "development_start": development_start.date().isoformat(),
        "development_end": development_end.date().isoformat(),
        "maximum_session_date_analyzed": pd.to_datetime(trades["session_date"]).max().date().isoformat(),
        "configuration_count": len(summary),
        "or_minutes": list(OR_DURATIONS),
        "stop_definitions": [
            {"stop_mode": name, "kind": kind, "value": value}
            for name, kind, value in STOP_DEFINITIONS
        ],
        "target_points": list(TARGET_POINTS_VALUES),
        "tick_size": 0.25,
        "entry_bar_ambiguity": (
            "The unchanged validated PRINT simulator classifies an entry-bar stop "
            "touch as AMBIGUOUS_ENTRY_STOP for every stop definition."
        ),
        "or_width_is_diagnostic_only": True,
        "or_width_filter_used": False,
        "exact_prior_candidate_control_counts": control_counts,
        "validated_signal_and_execution_code_modified": False,
    }
    return summary, trades, audit, diagnostics, metadata


def _configuration_metrics(
    config, candidates, completed, executed, enriched_trades, audit,
    ambiguous_signals, start, end, exact_controls,
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
    entry_stop_count = int(completed["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP).sum())
    completed_excluded = int(completed["excluded_from_performance"].sum())
    total_excluded = len(ambiguous_signals) + completed_excluded
    return {
        "config_id": config.config_id, "research_scope": "DEVELOPMENT_ONLY",
        "development_start": start.date().isoformat(),
        "development_end": end.date().isoformat(),
        "or_minutes": int(config.or_minutes), "breakout_type": BREAKOUT_TYPE,
        "stop_mode": config.stop_mode,
        "stop_definition_kind": config.stop_definition_kind,
        "configured_stop_value": float(config.configured_stop_value),
        "target_points": float(config.target_points),
        "eligible_candidates": len(candidates),
        "signal_ambiguity_count": len(ambiguous_signals),
        "entry_stop_ambiguity_count": entry_stop_count,
        "other_execution_ambiguity_count": completed_excluded - entry_stop_count,
        "ambiguity_exclusion_count": total_excluded,
        "ambiguity_rate": total_excluded / len(candidates),
        "entry_stop_ambiguity_rate": entry_stop_count / len(candidates),
        "session_trade_limit_rejections": int(audit["rejection_reason"].eq(SESSION_TRADE_LIMIT).sum()),
        "executed_trades": len(executed), "wins": int(values.gt(0).sum()),
        "losses": int(values.lt(0).sum()), "flat_trades": int(values.eq(0).sum()),
        "session_end_exits": int(executed["exit_reason"].eq(SESSION_END).sum()),
        "win_rate": float(values.gt(0).mean()), "average_r": float(values.mean()),
        "median_r": float(values.median()), "total_r": float(values.sum()),
        "profit_factor_r": float(positive.sum()) / gross_loss if gross_loss else 0.0,
        "max_drawdown_r": calculate_max_drawdown_r(values),
        "max_consecutive_losses": max_consecutive_losses(values),
        "average_holding_minutes": float(executed["holding_minutes"].mean()),
        "positive_month_percentage": float(monthly.gt(0).mean() * 100),
        "best_month_r": float(monthly.max()), "worst_month_r": float(monthly.min()),
        "rolling_50_min_average_r": float(rolling_50.min()),
        "rolling_100_min_average_r": float(rolling_100.min()),
        "rolling_100_positive_window_percentage": float(rolling_100.gt(0).mean() * 100),
        "target_hit_percentage": float(executed["exit_reason"].eq(TARGET).mean() * 100),
        "stop_hit_percentage": float(executed["exit_reason"].eq(STOP).mean() * 100),
        "session_end_percentage": float(executed["exit_reason"].eq(SESSION_END).mean() * 100),
        "average_or_width_points": float(enriched_trades["or_width_points"].mean()),
        "median_or_width_points": float(enriched_trades["or_width_points"].median()),
        "average_initial_risk_points": float(enriched_trades["initial_risk_points"].mean()),
        "average_initial_reward_risk": float(enriched_trades["initial_reward_risk"].mean()),
        "exact_prior_candidate_controls": exact_controls,
        "target_distance_verified": True, "stop_distance_verified": True,
        "max_one_trade_per_session_verified": True,
    }


def _enrich_executed(executed, candidates, config) -> pd.DataFrame:
    diagnostics = candidates.loc[:, [*KEY_COLUMNS, *DIAGNOSTIC_COLUMNS]].copy()
    output = executed.merge(diagnostics, on=KEY_COLUMNS, validate="one_to_one")
    output.insert(0, "config_id", config.config_id)
    output.insert(1, "research_scope", "DEVELOPMENT_ONLY")
    output["ambiguity_status"] = output["ambiguous"]
    output["inclusion_exclusion_status"] = "INCLUDED_EXECUTED"
    return output


def _annotate_audit(audit, config) -> pd.DataFrame:
    output = audit.copy()
    output.insert(0, "config_id", config.config_id)
    output.insert(1, "research_scope", "DEVELOPMENT_ONLY")
    return output


def _build_or_width_diagnostics(audit, completed, config) -> pd.DataFrame:
    outcome_columns = [
        *KEY_COLUMNS, "exit_time", "exit_price", "exit_reason", "pnl_points",
        "result_r", "ambiguous", "ambiguity_reason", "excluded_from_performance",
    ]
    outcomes = completed.loc[:, outcome_columns]
    output = audit.merge(outcomes, on=KEY_COLUMNS, how="left", validate="one_to_one")
    output["inclusion_exclusion_status"] = np.where(
        output["gate4d_status"].eq("EXECUTED"), "INCLUDED_EXECUTED", "EXCLUDED"
    )
    output["ambiguity_status"] = output["ambiguous"].fillna(False)
    wanted = [
        "config_id", "research_scope", "session_date", "contract", "or_minutes",
        "breakout_type", "direction", "signal_time", "entry_time", "entry_price",
        *DIAGNOSTIC_COLUMNS, "initial_stop", "initial_target", "candidate_validity",
        "invalid_reason", "gate4d_status", "rejection_reason",
        "inclusion_exclusion_status", "exit_time", "exit_price", "exit_reason",
        "pnl_points", "result_r", "ambiguity_status", "ambiguity_reason",
        "excluded_from_performance",
    ]
    return output.loc[:, list(dict.fromkeys(wanted))]


def _assert_signal_reproduction(signals, reference, duration) -> None:
    selected = reference.loc[reference["or_minutes"].eq(duration)].copy()
    selected["session_date"] = pd.to_datetime(selected["session_date"]).dt.date
    selected["signal_time"] = pd.to_datetime(selected["signal_time"], utc=True).dt.tz_convert("America/New_York")
    selected = selected.drop_duplicates(["session_date", "direction", "signal_time"])
    left = set(signals[["session_date", "direction", "signal_time"]].itertuples(index=False, name=None))
    right = set(selected[["session_date", "direction", "signal_time"]].itertuples(index=False, name=None))
    if left != right:
        raise ValueError(f"{duration}m PRINT signals differ from Gate 6A")


def _assert_completed_r_math(completed) -> None:
    included = completed.loc[~completed["excluded_from_performance"]].copy()
    expected = included["pnl_points"].astype(float) / included["risk_points"].astype(float)
    if not np.allclose(included["result_r"], expected, rtol=0, atol=1e-12):
        raise ValueError("result_R does not equal PnL / initial risk")


def _verify_exact_prior_candidate_controls(
    fixed_candidates, fixed_completed, prior_candidates, prior_completed,
) -> int:
    prior_targets = prior_candidates.set_index(KEY_COLUMNS)["initial_target"]
    fixed_targets = fixed_candidates.set_index(KEY_COLUMNS)["initial_target"]
    exact_keys = fixed_targets.index[
        np.isclose(fixed_targets.to_numpy(), prior_targets.loc[fixed_targets.index].to_numpy(), rtol=0, atol=1e-12)
    ]
    if not len(exact_keys):
        return 0
    compare_columns = [
        "trade_id", *KEY_COLUMNS, "entry_price", "initial_stop", "initial_target",
        "risk_points", "exit_time", "exit_price", "exit_reason", "pnl_points",
        "result_r", "ambiguous", "ambiguity_reason", "excluded_from_performance",
    ]
    fixed = fixed_completed.set_index(KEY_COLUMNS).loc[exact_keys].reset_index()[compare_columns]
    prior = prior_completed.set_index(KEY_COLUMNS).loc[exact_keys].reset_index()[compare_columns]
    fixed = fixed.sort_values(KEY_COLUMNS, kind="stable").reset_index(drop=True)
    prior = prior.sort_values(KEY_COLUMNS, kind="stable").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(
            fixed, prior, check_dtype=False, check_exact=False,
            rtol=0, atol=1e-12,
        )
    except AssertionError as error:
        raise ValueError("An exactly equivalent midpoint/2R candidate did not reproduce") from error
    return len(exact_keys)


def _validate_outputs(summary, trades, diagnostics, start, end) -> None:
    if len(summary) != EXPECTED_CONFIGURATIONS or summary["config_id"].duplicated().any():
        raise ValueError("Gate 6B output does not contain 75 unique configurations")
    for frame in (trades, diagnostics):
        dates = pd.to_datetime(frame["session_date"])
        if not dates.between(start, end).all() or dates.max() > pd.Timestamp("2025-06-30"):
            raise ValueError("A reserved-period row entered Gate 6B")
    if trades.duplicated(["config_id", "session_date"]).any():
        raise ValueError("Gate 6B contains duplicate executed session/configuration rows")
    if not diagnostics["or_width_points"].gt(0).all():
        raise ValueError("Gate 6B.1 diagnostics contain invalid OR width")
    if not np.allclose(
        diagnostics["target_to_or_ratio"],
        diagnostics["target_points"] / diagnostics["or_width_points"],
        rtol=0, atol=1e-12,
    ):
        raise ValueError("Gate 6B.1 target/OR diagnostic failed")
    valid = diagnostics["candidate_validity"]
    if not np.allclose(
        diagnostics.loc[valid, "stop_to_or_ratio"],
        diagnostics.loc[valid, "initial_risk_points"] / diagnostics.loc[valid, "or_width_points"],
        rtol=0, atol=1e-12,
    ):
        raise ValueError("Gate 6B.1 stop/OR diagnostic failed")


def _config_id(duration, stop_mode, target_points) -> str:
    return f"{duration}m_PRINT_{stop_mode}_TARGET{int(target_points)}PT"


def write_outputs(summary, trades, audit, diagnostics, metadata, output_dir) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "orb_gate6b_DEV_fixed_target_stop"
    paths = {
        "summary": output_dir / f"{prefix}_summary.csv",
        "trades": output_dir / f"{prefix}_trades.csv",
        "candidate_audit": output_dir / f"{prefix}_candidate_audit.csv",
        "or_width_diagnostics": output_dir / f"{prefix}_or_width_diagnostics.csv",
        "metadata": output_dir / f"{prefix}_metadata.json",
    }
    summary.to_csv(paths["summary"], index=False)
    _csv_ready(trades).to_csv(paths["trades"], index=False)
    _csv_ready(audit).to_csv(paths["candidate_audit"], index=False)
    _csv_ready(diagnostics).to_csv(paths["or_width_diagnostics"], index=False)
    plots = {
        "average_r": ("average_r", "Average R", "RdYlGn", False),
        "profit_factor": ("profit_factor_r", "Profit Factor (R)", "RdYlGn", False),
        "max_drawdown": ("max_drawdown_r", "Maximum Drawdown (R)", "RdYlGn_r", False),
        "positive_month_percentage": (
            "positive_month_percentage", "Positive Months (%)", "RdYlGn", False
        ),
        "rolling100_positive_window_percentage": (
            "rolling_100_positive_window_percentage",
            "Rolling-100 Positive Windows (%)", "RdYlGn", False,
        ),
        "ambiguity_rate": ("ambiguity_rate", "Ambiguity / exclusion rate (%)", "YlOrRd", True),
        "session_end_percentage": (
            "session_end_percentage", "Session-end exits (%)", "YlOrRd", False
        ),
    }
    for name, (metric, label, colorscale, multiply_percentage) in plots.items():
        path = output_dir / f"{prefix}_{name}_heatmap.html"
        write_heatmap_panels(
            summary, metric, label, path,
            colorscale=colorscale, multiply_percentage=multiply_percentage,
        )
        paths[f"{name}_heatmap"] = path
    metadata = {**metadata, "artifacts": {name: str(path) for name, path in paths.items()}}
    paths["metadata"].write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return paths


def write_heatmap_panels(
    summary, metric, label, path, *, colorscale, multiply_percentage,
) -> None:
    stop_modes = [name for name, _, _ in STOP_DEFINITIONS]
    figure = make_subplots(
        rows=2, cols=3,
        subplot_titles=tuple(stop_modes) + ("",),
        horizontal_spacing=0.10, vertical_spacing=0.18,
    )
    multiplier = 100.0 if multiply_percentage else 1.0
    all_values = summary[metric].astype(float) * multiplier
    shared_min, shared_max = float(all_values.min()), float(all_values.max())
    for index, stop_mode in enumerate(stop_modes):
        row, column = index // 3 + 1, index % 3 + 1
        selected = summary.loc[summary["stop_mode"].eq(stop_mode)]
        pivot = selected.pivot(index="or_minutes", columns="target_points", values=metric).reindex(
            index=OR_DURATIONS, columns=TARGET_POINTS_VALUES
        ) * multiplier
        values = pivot.to_numpy(dtype=float)
        figure.add_trace(go.Heatmap(
            z=values, x=[f"{int(value)}pt" for value in TARGET_POINTS_VALUES],
            y=[f"{value}m" for value in OR_DURATIONS], colorscale=colorscale,
            zmin=shared_min, zmax=shared_max,
            text=np.vectorize(lambda value: f"{value:.3f}")(values),
            texttemplate="%{text}", showscale=index == len(stop_modes) - 1,
            colorbar={"title": label} if index == len(stop_modes) - 1 else None,
            hovertemplate=(
                f"Stop: {stop_mode}<br>OR: %{{y}}<br>Target: %{{x}}<br>"
                + label + ": %{z:.5f}<extra></extra>"
            ),
        ), row=row, col=column)
        figure.update_xaxes(title_text="Fixed target", row=row, col=column)
        figure.update_yaxes(title_text="OR duration", row=row, col=column)
    figure.update_layout(
        title=f"Gate 6B — {label} — DEVELOPMENT ONLY",
        template="plotly_white", height=850, width=1400,
        margin={"l": 80, "r": 130, "t": 110, "b": 80},
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
    if "session_date" in output:
        output["session_date"] = output["session_date"].astype(str)
    for column in ("signal_time", "entry_time", "exit_time"):
        if column in output:
            output[column] = output[column].map(
                lambda value: value.isoformat() if pd.notna(value) else ""
            )
    return output
