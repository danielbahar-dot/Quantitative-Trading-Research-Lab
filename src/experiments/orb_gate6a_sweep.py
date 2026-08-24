"""Gate 6A DEVELOPMENT-only PRINT static-stop / R-target sweep.

The validated custom ORB pipeline remains authoritative. Only candidate stop
fraction and target multiple vary; reserved price partitions are never loaded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backtesting.candidate_entries import TICK_SIZE, build_candidate_entries, round_to_tick
from src.backtesting.completed_trades import simulate_completed_trades
from src.backtesting.session_trade_limit import SESSION_TRADE_LIMIT, apply_session_trade_limit
from src.experiments.orb_v01_baseline import calculate_max_drawdown_r, max_consecutive_losses
from src.experiments.orb_v01_development_diagnostics import development_bounds, load_development_trades
from src.visualization.research_viewer import find_orb_signals


OR_DURATIONS = (10, 15, 20, 30)
STOP_DEFINITIONS = (("OR_25_RETRACEMENT", 0.25), ("OR_MIDPOINT_50", 0.50))
TARGET_R_VALUES = (1.0, 1.5, 2.0, 2.5, 3.0)
BREAKOUT_TYPE = "PRINT"
EXPECTED_CONFIGURATION_COUNT = 40

SUMMARY_COLUMNS = [
    "config_id", "research_scope", "development_start", "development_end",
    "or_minutes", "breakout_type", "stop_mode", "stop_fraction", "target_r",
    "baseline_control", "signals", "signal_ambiguity_count", "candidates",
    "invalid_candidate_count", "completed_candidate_excluded_count",
    "ambiguous_excluded_count", "session_trade_limit_rejections", "trades",
    "wins", "losses", "flat_trades", "session_end_exits", "session_end_rate",
    "win_rate", "average_r", "median_r", "total_r", "profit_factor_r",
    "max_drawdown_r", "max_consecutive_losses", "average_holding_minutes",
    "positive_month_percentage", "best_month_r", "worst_month_r",
    "rolling_50_min_average_r", "rolling_50_final_average_r",
    "rolling_100_min_average_r", "rolling_100_final_average_r",
    "rolling_100_positive_window_percentage", "neighbor_count",
    "neighbor_mean_average_r", "neighbor_mean_profit_factor_r",
    "neighbor_positive_average_r_percentage", "average_r_minus_neighbor_mean",
    "baseline_reproduced", "stop_calculation_verified",
    "target_calculation_verified", "max_one_trade_per_session_verified",
]

CONTROL_COLUMNS = [
    "trade_id", "session_date", "direction", "signal_time", "entry_time",
    "entry_price", "initial_stop", "initial_target", "risk_points",
    "exit_time", "exit_price", "exit_reason", "result_r",
]


def configuration_grid() -> pd.DataFrame:
    rows = [
        {
            "config_id": _config_id(duration, stop_fraction, target_r),
            "or_minutes": duration,
            "breakout_type": BREAKOUT_TYPE,
            "stop_mode": stop_mode,
            "stop_fraction": stop_fraction,
            "target_r": target_r,
        }
        for duration in OR_DURATIONS
        for stop_mode, stop_fraction in STOP_DEFINITIONS
        for target_r in TARGET_R_VALUES
    ]
    grid = pd.DataFrame(rows)
    if len(grid) != EXPECTED_CONFIGURATION_COUNT:
        raise ValueError("Gate 6A grid does not contain exactly 40 cells")
    if grid.duplicated(["or_minutes", "breakout_type", "stop_fraction", "target_r"]).any():
        raise ValueError("Gate 6A grid contains duplicate configurations")
    return grid


def load_development_or_levels(
    path: str | Path, start: pd.Timestamp, end: pd.Timestamp, *, chunksize: int = 50_000
) -> pd.DataFrame:
    """Read and retain only DEVELOPMENT OR-level rows."""
    selected = []
    for chunk in pd.read_csv(path, chunksize=chunksize):
        dates = pd.to_datetime(chunk["session_date"], errors="raise")
        mask = dates.between(start, end, inclusive="both")
        if mask.any():
            selected.append(chunk.loc[mask].copy())
    if not selected:
        raise ValueError("No OR levels fall inside DEVELOPMENT")
    levels = pd.concat(selected, ignore_index=True)
    levels["session_date"] = pd.to_datetime(levels["session_date"], errors="raise").dt.date
    levels["or_minutes"] = pd.to_numeric(levels["or_minutes"], errors="raise").astype(int)
    levels["valid_or"] = _to_boolean(levels["valid_or"])
    dates = pd.to_datetime(levels["session_date"])
    if not dates.between(start, end, inclusive="both").all():
        raise ValueError("A reserved-period OR row entered Gate 6A")
    return levels.loc[levels["or_minutes"].isin(OR_DURATIONS)].copy()


def run_development_sweep(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
    partition_config: dict[str, Any],
    baseline_paths: tuple[str | Path, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    start, end = development_bounds(partition_config)
    _assert_development_scope(price_data, start, end)
    baseline = load_development_trades(baseline_paths, partition_config)
    baseline = baseline.loc[
        baseline["breakout_type"].eq(BREAKOUT_TYPE)
        & baseline["or_minutes"].isin(OR_DURATIONS)
    ].copy()
    observed = set(baseline[["or_minutes", "breakout_type"]].drop_duplicates().itertuples(index=False, name=None))
    if observed != {(duration, BREAKOUT_TYPE) for duration in OR_DURATIONS}:
        raise ValueError("Control baseline does not contain all four PRINT durations")

    signal_cache = {}
    for duration in OR_DURATIONS:
        signals, ambiguous = find_orb_signals(
            price_data, or_levels, start_date=start, end_date=end,
            or_minutes=duration, breakout_type=BREAKOUT_TYPE,
        )
        if len(signals) and not pd.to_datetime(signals["session_date"]).between(start, end).all():
            raise ValueError("A reserved-period signal entered Gate 6A")
        signal_cache[duration] = (signals, ambiguous)

    summary_rows, trade_frames, audit_frames = [], [], []
    baseline_checks = {}
    for config in configuration_grid().itertuples(index=False):
        signals, ambiguous = signal_cache[config.or_minutes]
        candidates = build_candidate_entries(
            price_data, signals, or_minutes=config.or_minutes,
            stop_fraction=config.stop_fraction, target_r=config.target_r,
        )
        _validate_candidate_math(candidates, config.stop_fraction, config.target_r)
        completed = simulate_completed_trades(price_data, candidates)
        executed, audit = apply_session_trade_limit(candidates, completed)
        _assert_executed(executed, start, end)
        control = bool(np.isclose(config.stop_fraction, 0.5) and np.isclose(config.target_r, 2.0))
        reproduced = False
        if control:
            _assert_control_reproduction(
                executed, baseline.loc[baseline["or_minutes"].eq(config.or_minutes)]
            )
            reproduced = True
            baseline_checks[f"{config.or_minutes}m_PRINT"] = True
        trade_frames.append(_annotate(executed, config))
        audit_frames.append(_annotate(audit, config))
        summary_rows.append(_metrics(
            config, executed, candidates, completed, audit, signals, ambiguous,
            start, end, reproduced,
        ))

    summary = add_neighborhood_metrics(pd.DataFrame(summary_rows)).loc[:, SUMMARY_COLUMNS]
    trades = pd.concat(trade_frames, ignore_index=True)
    audit = pd.concat(audit_frames, ignore_index=True)
    _validate_outputs(summary, trades, start, end, baseline_checks)
    metadata = {
        "experiment_id": "orb_gate6a_dev_print_static_r",
        "research_scope": "DEVELOPMENT_ONLY",
        "development_start": start.date().isoformat(),
        "development_end": end.date().isoformat(),
        "maximum_session_date_analyzed": pd.to_datetime(trades["session_date"]).max().date().isoformat(),
        "breakout_type": BREAKOUT_TYPE,
        "or_minutes": list(OR_DURATIONS),
        "stop_definitions": [
            {"stop_mode": name, "stop_fraction": fraction}
            for name, fraction in STOP_DEFINITIONS
        ],
        "target_r": list(TARGET_R_VALUES),
        "configuration_count": len(summary),
        "tick_size": TICK_SIZE,
        "target_rounding_note": "Theoretical R targets are rounded to the nearest 0.25 point tick, half-up.",
        "execution_source_of_truth": "validated_custom_ORB_execution_engine",
        "vectorbt_portfolio_from_signals_used": False,
        "baseline_control": {
            "stop_fraction": 0.5, "target_r": 2.0,
            "exact_trade_level_reproduction": baseline_checks,
        },
        "validation": {
            "exactly_40_configurations": True,
            "no_duplicate_configurations": True,
            "development_only": True,
            "max_one_trade_per_session_per_configuration": True,
            "stop_calculations_verified": True,
            "target_calculations_verified": True,
            "rolling_windows_use_executed_trade_chronology": True,
        },
        "neighborhood_definition": (
            "Orthogonally adjacent cells within one stop surface use the next "
            "tested OR duration or target R; diagonals are excluded."
        ),
    }
    return summary, trades, audit, metadata


def add_neighborhood_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    """Add descriptive neighbor context without ranking or scoring cells."""
    output = summary.copy()
    for column in (
        "neighbor_mean_average_r", "neighbor_mean_profit_factor_r",
        "neighbor_positive_average_r_percentage", "average_r_minus_neighbor_mean",
    ):
        output[column] = np.nan
    output["neighbor_count"] = 0
    for index, row in output.iterrows():
        dpos = OR_DURATIONS.index(int(row["or_minutes"]))
        tpos = TARGET_R_VALUES.index(float(row["target_r"]))
        keys = []
        for delta in (-1, 1):
            if 0 <= dpos + delta < len(OR_DURATIONS):
                keys.append((OR_DURATIONS[dpos + delta], float(row["target_r"])))
            if 0 <= tpos + delta < len(TARGET_R_VALUES):
                keys.append((int(row["or_minutes"]), TARGET_R_VALUES[tpos + delta]))
        mask = output["stop_fraction"].eq(row["stop_fraction"]) & pd.Series(
            [(int(d), float(t)) in keys for d, t in zip(output["or_minutes"], output["target_r"])],
            index=output.index,
        )
        neighbors = output.loc[mask]
        if len(neighbors):
            mean_r = float(neighbors["average_r"].mean())
            output.at[index, "neighbor_count"] = len(neighbors)
            output.at[index, "neighbor_mean_average_r"] = mean_r
            output.at[index, "neighbor_mean_profit_factor_r"] = float(neighbors["profit_factor_r"].mean())
            output.at[index, "neighbor_positive_average_r_percentage"] = float(neighbors["average_r"].gt(0).mean() * 100)
            output.at[index, "average_r_minus_neighbor_mean"] = float(row["average_r"] - mean_r)
    return output


def write_sweep_outputs(
    summary: pd.DataFrame,
    trades: pd.DataFrame,
    audit: pd.DataFrame,
    metadata: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write canonical tables, audit data, metadata, and five heatmaps."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "orb_gate6a_DEV_print_static_r"
    paths = {
        "summary": output_dir / f"{prefix}_sweep.csv",
        "trades": output_dir / f"{prefix}_trades.csv",
        "candidate_audit": output_dir / f"{prefix}_candidate_audit.csv",
        "metadata": output_dir / f"{prefix}_metadata.json",
    }
    summary.to_csv(paths["summary"], index=False)
    _csv_ready(trades).to_csv(paths["trades"], index=False)
    _csv_ready(audit).to_csv(paths["candidate_audit"], index=False)
    specifications = {
        "average_r": ("average_r", "Average R", ".4f", "RdYlGn"),
        "profit_factor": ("profit_factor_r", "Profit Factor (R)", ".3f", "RdYlGn"),
        "max_drawdown": ("max_drawdown_r", "Maximum Drawdown (R)", ".2f", "RdYlGn_r"),
        "positive_month_percentage": (
            "positive_month_percentage", "Positive Months (%)", ".1f", "RdYlGn"
        ),
        "rolling100_positive_window_percentage": (
            "rolling_100_positive_window_percentage",
            "Rolling-100 Positive Windows (%)", ".1f", "RdYlGn",
        ),
    }
    for key, (metric, label, text_format, colorscale) in specifications.items():
        path = output_dir / f"{prefix}_{key}_heatmap.html"
        write_heatmap(summary, metric, label, path, text_format, colorscale)
        paths[f"{key}_heatmap"] = path
    metadata = {**metadata, "artifacts": {key: str(value) for key, value in paths.items()}}
    paths["metadata"].write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return paths


def write_heatmap(
    summary: pd.DataFrame,
    metric: str,
    label: str,
    path: str | Path,
    text_format: str,
    colorscale: str,
) -> None:
    """Render two stop-definition panels with a shared color range."""
    figure = make_subplots(
        rows=1, cols=2,
        subplot_titles=("25% OR retracement stop", "50% midpoint stop"),
        horizontal_spacing=0.12,
    )
    shared_min, shared_max = float(summary[metric].min()), float(summary[metric].max())
    for column, (_, stop_fraction) in enumerate(STOP_DEFINITIONS, start=1):
        selected = summary.loc[summary["stop_fraction"].eq(stop_fraction)]
        pivot = selected.pivot(index="or_minutes", columns="target_r", values=metric).reindex(
            index=OR_DURATIONS, columns=TARGET_R_VALUES
        )
        hover = np.empty(pivot.shape, dtype=object)
        for row_index, duration in enumerate(OR_DURATIONS):
            for target_index, target_r in enumerate(TARGET_R_VALUES):
                record = selected.loc[
                    selected["or_minutes"].eq(duration) & selected["target_r"].eq(target_r)
                ].iloc[0]
                hover[row_index, target_index] = (
                    f"{duration}m PRINT<br>Stop fraction: {stop_fraction:.2f}"
                    f"<br>Target: {target_r:g}R<br>{label}: {record[metric]:.6g}"
                    f"<br>Trades: {int(record['trades'])}"
                    f"<br>Neighbor mean Avg R: {record['neighbor_mean_average_r']:.4f}"
                )
        values = pivot.to_numpy(dtype=float)
        figure.add_trace(
            go.Heatmap(
                z=values,
                x=[f"{value:g}R" for value in TARGET_R_VALUES],
                y=[f"{value}m" for value in OR_DURATIONS],
                text=np.vectorize(lambda value: format(value, text_format))(values),
                texttemplate="%{text}", customdata=hover,
                hovertemplate="%{customdata}<extra></extra>",
                colorscale=colorscale, zmin=shared_min, zmax=shared_max,
                colorbar={"title": label} if column == 2 else None,
                showscale=column == 2,
            ),
            row=1, col=column,
        )
        figure.update_xaxes(title_text="Target R", row=1, col=column)
        figure.update_yaxes(title_text="OR duration", row=1, col=column)
    figure.update_layout(
        title=f"Gate 6A — {label} response surface — DEVELOPMENT ONLY",
        template="plotly_white", height=620, width=1200,
        margin={"l": 80, "r": 130, "t": 110, "b": 80},
    )
    figure.write_html(
        path, include_plotlyjs="cdn", config={"responsive": True},
        default_width="100%", default_height="620px",
    )


def _metrics(
    config, executed: pd.DataFrame, candidates: pd.DataFrame,
    completed: pd.DataFrame, audit: pd.DataFrame, signals: pd.DataFrame,
    ambiguous: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
    reproduced: bool,
) -> dict[str, Any]:
    result_r = executed["result_r"].astype(float)
    positive, negative = result_r.loc[result_r.gt(0)], result_r.loc[result_r.lt(0)]
    gross_loss = abs(float(negative.sum()))
    ordered = executed.sort_values(["entry_time", "signal_time", "trade_id"], kind="stable")
    rolling_50 = ordered["result_r"].astype(float).rolling(50, min_periods=50).mean().dropna()
    rolling_100 = ordered["result_r"].astype(float).rolling(100, min_periods=100).mean().dropna()
    monthly = (
        executed.assign(month=pd.to_datetime(executed["session_date"]).dt.to_period("M").astype(str))
        .groupby("month", sort=True)["result_r"].sum()
    )
    excluded = int(completed["excluded_from_performance"].sum())
    return {
        "config_id": config.config_id,
        "research_scope": "DEVELOPMENT_ONLY",
        "development_start": start.date().isoformat(),
        "development_end": end.date().isoformat(),
        "or_minutes": int(config.or_minutes), "breakout_type": BREAKOUT_TYPE,
        "stop_mode": config.stop_mode, "stop_fraction": float(config.stop_fraction),
        "target_r": float(config.target_r),
        "baseline_control": bool(np.isclose(config.stop_fraction, 0.5) and np.isclose(config.target_r, 2.0)),
        "signals": len(signals), "signal_ambiguity_count": len(ambiguous),
        "candidates": len(candidates),
        "invalid_candidate_count": int((~candidates["candidate_validity"]).sum()),
        "completed_candidate_excluded_count": excluded,
        "ambiguous_excluded_count": len(ambiguous) + excluded,
        "session_trade_limit_rejections": int(audit["rejection_reason"].eq(SESSION_TRADE_LIMIT).sum()),
        "trades": len(executed), "wins": int(result_r.gt(0).sum()),
        "losses": int(result_r.lt(0).sum()), "flat_trades": int(result_r.eq(0).sum()),
        "session_end_exits": int(executed["exit_reason"].eq("SESSION_END").sum()),
        "session_end_rate": float(executed["exit_reason"].eq("SESSION_END").mean()),
        "win_rate": float(result_r.gt(0).mean()), "average_r": float(result_r.mean()),
        "median_r": float(result_r.median()), "total_r": float(result_r.sum()),
        "profit_factor_r": float(positive.sum()) / gross_loss if gross_loss else 0.0,
        "max_drawdown_r": calculate_max_drawdown_r(result_r),
        "max_consecutive_losses": max_consecutive_losses(result_r),
        "average_holding_minutes": float(executed["holding_minutes"].mean()),
        "positive_month_percentage": float(monthly.gt(0).mean() * 100),
        "best_month_r": float(monthly.max()), "worst_month_r": float(monthly.min()),
        "rolling_50_min_average_r": float(rolling_50.min()),
        "rolling_50_final_average_r": float(rolling_50.iloc[-1]),
        "rolling_100_min_average_r": float(rolling_100.min()),
        "rolling_100_final_average_r": float(rolling_100.iloc[-1]),
        "rolling_100_positive_window_percentage": float(rolling_100.gt(0).mean() * 100),
        "baseline_reproduced": reproduced, "stop_calculation_verified": True,
        "target_calculation_verified": True, "max_one_trade_per_session_verified": True,
    }


def _validate_candidate_math(candidates: pd.DataFrame, stop_fraction: float, target_r: float) -> None:
    for candidate in candidates.itertuples(index=False):
        width = float(candidate.or_high) - float(candidate.or_low)
        stop = round_to_tick(
            float(candidate.or_high) - stop_fraction * width
            if candidate.direction == "LONG"
            else float(candidate.or_low) + stop_fraction * width
        )
        if not np.isclose(candidate.initial_stop, stop, rtol=0, atol=1e-12):
            raise ValueError("Directional stop calculation failed")
        if not candidate.candidate_validity:
            continue
        risk = round_to_tick(
            float(candidate.entry_price) - stop
            if candidate.direction == "LONG" else stop - float(candidate.entry_price)
        )
        if risk <= 0 or not np.isclose(candidate.risk_points, risk, rtol=0, atol=1e-12):
            raise ValueError("Directional risk calculation failed")
        target = round_to_tick(
            float(candidate.entry_price) + target_r * risk
            if candidate.direction == "LONG"
            else float(candidate.entry_price) - target_r * risk
        )
        if not np.isclose(candidate.initial_target, target, rtol=0, atol=1e-12):
            raise ValueError("R-based target calculation failed")


def _assert_control_reproduction(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    try:
        pd.testing.assert_frame_equal(
            _control_frame(actual), _control_frame(expected),
            check_dtype=False, check_exact=False, rtol=0, atol=1e-12,
        )
    except AssertionError as error:
        raise ValueError("Midpoint/2R control failed exact baseline reproduction") from error


def _control_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.loc[:, CONTROL_COLUMNS].copy()
    output["session_date"] = pd.to_datetime(output["session_date"]).dt.normalize()
    for column in ("signal_time", "entry_time", "exit_time"):
        output[column] = pd.to_datetime(output[column], utc=True)
    return output.sort_values(["entry_time", "signal_time", "trade_id"], kind="stable").reset_index(drop=True)


def _validate_outputs(summary, trades, start, end, baseline_checks) -> None:
    if len(summary) != 40 or summary.duplicated(["or_minutes", "stop_fraction", "target_r"]).any():
        raise ValueError("Sweep configuration validation failed")
    if baseline_checks != {f"{duration}m_PRINT": True for duration in OR_DURATIONS}:
        raise ValueError("Not all midpoint/2R controls reproduced")
    dates = pd.to_datetime(trades["session_date"])
    if not dates.between(start, end).all() or dates.max() > pd.Timestamp("2025-06-30"):
        raise ValueError("A reserved-period trade entered Gate 6A")
    if not trades["breakout_type"].eq(BREAKOUT_TYPE).all():
        raise ValueError("A non-PRINT trade entered Gate 6A")
    if trades.duplicated(["config_id", "session_date"]).any():
        raise ValueError("A configuration executed more than one trade per session")


def _assert_development_scope(price_data, start, end) -> None:
    dates = pd.to_datetime(price_data["session_date"])
    if not dates.between(start, end).all() or dates.max() > pd.Timestamp("2025-06-30"):
        raise ValueError("Gate 6A price input is not DEVELOPMENT-only")


def _assert_executed(executed, start, end) -> None:
    dates = pd.to_datetime(executed["session_date"])
    if not dates.between(start, end).all():
        raise ValueError("A reserved-period execution entered Gate 6A")
    if executed.duplicated(["session_date", "or_minutes", "breakout_type"]).any():
        raise ValueError("One-trade-per-session rule was violated")


def _annotate(frame, config) -> pd.DataFrame:
    output = frame.copy()
    for position, (name, value) in enumerate((
        ("config_id", config.config_id), ("research_scope", "DEVELOPMENT_ONLY"),
        ("stop_mode", config.stop_mode), ("stop_fraction", config.stop_fraction),
        ("target_r", config.target_r),
    )):
        output.insert(position, name, value)
    return output


def _config_id(duration, stop_fraction, target_r) -> str:
    return f"{duration}m_PRINT_STOP{int(stop_fraction * 100)}_TARGET{str(target_r).replace('.', 'p')}R"


def _csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "session_date" in output:
        output["session_date"] = output["session_date"].astype(str)
    for column in ("signal_time", "entry_time", "exit_time"):
        if column in output:
            output[column] = output[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
    return output


def _to_boolean(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values
    mapped = values.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise ValueError("valid_or contains non-boolean values")
    return mapped
