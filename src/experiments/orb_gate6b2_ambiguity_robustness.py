"""Gate 6B.2 DEVELOPMENT-only PRINT entry-bar chronology robustness.

Gate 6B artifacts are the source of truth. EXCLUDED is reconstructed from the
frozen candidate/trade audits, ENTRY_FIRST converts only AMBIGUOUS_ENTRY_STOP
records to immediate -1R trades, and ADVERSE_MOVE_FIRST evaluates only those
same candidates beginning on the following one-minute bar. Signals, candidate
prices, ordinary completed trades, and Gate 6B artifacts are not regenerated.
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

from src.backtesting.candidate_entries import CANDIDATE_COLUMNS
from src.backtesting.completed_trades import (
    AMBIGUOUS_ENTRY_STOP,
    AMBIGUOUS_STOP_TARGET,
    REGULAR_SESSION_END,
    SESSION_END,
    STOP,
    TARGET,
    TRADE_COLUMNS,
)
from src.backtesting.session_trade_limit import EXECUTED, SESSION_TRADE_LIMIT, apply_session_trade_limit
from src.experiments.orb_gate6a1_ambiguity import _simulate_after_entry_bar
from src.experiments.orb_gate6b1_width_analysis import (
    add_width_quintiles,
    assign_duration_bins,
    unique_width_observations,
)
from src.experiments.orb_gate6b_fixed_points import (
    DIAGNOSTIC_COLUMNS,
    EXPECTED_CONFIGURATIONS,
    KEY_COLUMNS,
    OR_DURATIONS,
    STOP_DEFINITIONS,
    TARGET_POINTS_VALUES,
)
from src.experiments.orb_v01_baseline import calculate_max_drawdown_r, max_consecutive_losses


SCENARIOS = ("EXCLUDED", "ENTRY_FIRST", "ADVERSE_MOVE_FIRST")
EXPECTED_SCENARIO_ROWS = EXPECTED_CONFIGURATIONS * len(SCENARIOS)
STOP_MODES = tuple(item[0] for item in STOP_DEFINITIONS)
QUINTILES = (1, 2, 3, 4, 5)

SUMMARY_METRICS = (
    "executed_trades", "wins", "losses", "session_end_exits", "win_rate",
    "average_r", "median_r", "total_r", "profit_factor_r", "max_drawdown_r",
    "max_consecutive_losses", "positive_month_percentage",
    "target_hit_percentage", "stop_hit_percentage", "session_end_percentage",
    "rolling_100_positive_window_percentage", "average_holding_minutes",
)


def load_gate6b_artifacts(
    summary_path: str | Path,
    trades_path: str | Path,
    audit_path: str | Path,
    diagnostics_path: str | Path,
    metadata_path: str | Path,
    *,
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load and reconcile only the frozen Gate 6B DEVELOPMENT artifacts."""
    summary = pd.read_csv(summary_path)
    trades = pd.read_csv(trades_path)
    audit = pd.read_csv(audit_path)
    diagnostics = pd.read_csv(diagnostics_path)
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))

    for frame in (trades, audit, diagnostics):
        frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise").dt.normalize()
        for column in ("signal_time", "entry_time", "exit_time"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True).dt.tz_convert(
                    "America/New_York"
                )
    for frame, columns in (
        (trades, ("ambiguous", "excluded_from_performance")),
        (audit, ("candidate_validity", "completed_trade_ambiguous", "completed_trade_excluded")),
        (diagnostics, ("candidate_validity", "ambiguity_status", "excluded_from_performance")),
    ):
        for column in columns:
            frame[column] = _to_boolean(frame[column], column)

    _assert_development(summary, development_start, development_end)
    for frame in (trades, audit, diagnostics):
        dates = frame["session_date"]
        if not dates.between(development_start, development_end).all() or dates.max() > pd.Timestamp(
            "2025-06-30"
        ):
            raise ValueError("A reserved-period record entered Gate 6B.2")
    if len(summary) != EXPECTED_CONFIGURATIONS or summary["config_id"].duplicated().any():
        raise ValueError("Gate 6B.2 requires exactly 75 unique Gate 6B configurations")
    if set(summary["or_minutes"].astype(int)) != set(OR_DURATIONS):
        raise ValueError("Gate 6B.2 found unexpected OR durations")
    if set(summary["stop_mode"]) != set(STOP_MODES):
        raise ValueError("Gate 6B.2 found unexpected stop modes")
    if set(summary["target_points"].astype(float)) != set(TARGET_POINTS_VALUES):
        raise ValueError("Gate 6B.2 found unexpected targets")
    if not metadata.get("gate6a_and_gate6a1_artifacts_unchanged"):
        raise ValueError("Gate 6B metadata does not confirm upstream artifact integrity")

    candidate_key = ["config_id", *KEY_COLUMNS]
    if audit.duplicated(candidate_key).any() or diagnostics.duplicated(candidate_key).any():
        raise ValueError("Gate 6B candidate artifacts contain duplicate keys")
    audit_keys = set(audit[candidate_key].itertuples(index=False, name=None))
    diagnostic_keys = set(diagnostics[candidate_key].itertuples(index=False, name=None))
    if audit_keys != diagnostic_keys:
        raise ValueError("Gate 6B candidate audit and diagnostics do not reconcile")
    if not np.allclose(
        diagnostics["or_width_points"].astype(float),
        diagnostics["or_high"].astype(float) - diagnostics["or_low"].astype(float),
        rtol=0, atol=1e-12,
    ):
        raise ValueError("Gate 6B OR width does not equal OR high minus OR low")
    return summary, trades, audit, diagnostics, metadata


def run_robustness_mapping(
    price_data: pd.DataFrame,
    gate6_summary: pd.DataFrame,
    gate6_trades: pd.DataFrame,
    gate6_audit: pd.DataFrame,
    gate6_diagnostics: pd.DataFrame,
    *,
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Evaluate three chronology conventions for all 75 Gate 6B cells."""
    price_dates = pd.to_datetime(price_data["session_date"])
    if not price_dates.between(development_start, development_end).all():
        raise ValueError("Gate 6B.2 price input is not DEVELOPMENT-only")
    if price_dates.max() > pd.Timestamp("2025-06-30"):
        raise ValueError("Gate 6B.2 price input extends beyond DEVELOPMENT")

    sessions = {session_date: group for session_date, group in price_data.groupby("session_date")}
    summary_rows: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    integrity: dict[str, Any] = {}

    for config in gate6_summary.sort_values("config_id").itertuples(index=False):
        config_id = config.config_id
        audit = gate6_audit.loc[gate6_audit["config_id"].eq(config_id)].copy()
        diagnostics = gate6_diagnostics.loc[gate6_diagnostics["config_id"].eq(config_id)].copy()
        frozen_trades = gate6_trades.loc[gate6_trades["config_id"].eq(config_id)].copy()
        candidates = _candidate_frame(audit)
        selection_completed = _selection_records(diagnostics)
        entry_ambiguity_mask = selection_completed["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP)
        ambiguous_keys = {
            _key(row)
            for row in selection_completed.loc[entry_ambiguity_mask, KEY_COLUMNS].itertuples(index=False)
        }
        if len(ambiguous_keys) != int(config.entry_stop_ambiguity_count):
            raise ValueError(f"Entry-stop ambiguity count does not reconcile for {config_id}")

        frozen_lookup = _trade_lookup(frozen_trades)
        candidate_lookup = {
            _key(row): row for row in candidates.itertuples(index=False)
        }
        adverse_lookup = {
            key: _simulate_after_entry_bar(
                sessions.get(candidate_lookup[key].session_date),
                candidate_lookup[key],
                REGULAR_SESSION_END,
            )
            for key in ambiguous_keys
        }

        for scenario in SCENARIOS:
            scenario_selection = selection_completed.copy()
            if scenario in {"ENTRY_FIRST", "ADVERSE_MOVE_FIRST"}:
                mask = scenario_selection["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP)
                scenario_selection.loc[mask, "ambiguous"] = False
                scenario_selection.loc[mask, "excluded_from_performance"] = False
                scenario_selection.loc[mask, "ambiguity_reason"] = ""
                scenario_selection.loc[mask, "exit_reason"] = (
                    STOP if scenario == "ENTRY_FIRST" else "ADVERSE_MOVE_FIRST_ENTRY_ACCEPTED"
                )

            selected_minimal, scenario_audit = apply_session_trade_limit(candidates, scenario_selection)
            selected_keys = [_key(row) for row in selected_minimal.itertuples(index=False)]
            scenario_trades = _materialize_selected_trades(
                selected_keys, scenario, candidate_lookup, frozen_lookup, adverse_lookup
            )
            scenario_trades = _enrich_scenario_trades(
                scenario_trades, diagnostics, config_id, scenario, ambiguous_keys
            )
            if scenario_trades.duplicated(["session_date", "or_minutes", "breakout_type"]).any():
                raise ValueError(f"{config_id} {scenario} exceeds one accepted entry per session")
            if scenario in {"ENTRY_FIRST", "ADVERSE_MOVE_FIRST"}:
                _assert_resolved_ambiguity_consumes_session(
                    candidates, scenario_selection, scenario_audit, ambiguous_keys
                )
            if scenario == "ENTRY_FIRST":
                resolved = scenario_trades.loc[scenario_trades["original_entry_stop_ambiguous"]]
                if not resolved["result_r"].eq(-1.0).all() or not resolved["exit_reason"].eq(STOP).all():
                    raise ValueError("ENTRY_FIRST did not resolve selected ambiguities as -1R")

            trade_frames.append(scenario_trades)
            summary_rows.append(
                _scenario_metrics(config, scenario, candidates, selection_completed, scenario_trades, scenario_audit)
            )

        integrity[config_id] = {
            "eligible_candidates": len(candidates),
            "ambiguous_entry_stop_candidates": len(ambiguous_keys),
            "frozen_excluded_trades": len(frozen_trades),
        }

    metrics = add_robustness_descriptors(pd.DataFrame(summary_rows))
    trades = pd.concat(trade_frames, ignore_index=True)
    widths = assign_duration_bins(unique_width_observations(gate6_diagnostics))
    trades = add_width_quintiles(trades, widths)
    diagnostics_with_width = add_width_quintiles(gate6_diagnostics, widths)
    width_sensitivity = calculate_width_sensitivity(metrics, trades, diagnostics_with_width)
    _validate_outputs(metrics, trades, width_sensitivity, gate6_summary, development_start, development_end)

    metadata = {
        "experiment_id": "orb_gate6b2_dev_ambiguity_robustness",
        "research_scope": "DEVELOPMENT_ONLY",
        "actual_minimum_session_date": pd.to_datetime(trades["session_date"]).min().date().isoformat(),
        "actual_maximum_session_date": pd.to_datetime(trades["session_date"]).max().date().isoformat(),
        "configuration_count": EXPECTED_CONFIGURATIONS,
        "scenario_count": len(SCENARIOS),
        "scenario_rows": EXPECTED_SCENARIO_ROWS,
        "scenarios": list(SCENARIOS),
        "gate6b_excluded_exact_reproduction": True,
        "excluded_convention": "Frozen Gate 6B behavior; AMBIGUOUS_ENTRY_STOP is excluded.",
        "entry_first_convention": (
            "Entry occurs before the same-bar adverse stop touch; the accepted trade exits "
            "immediately at its initial stop for -1R and consumes the session allowance."
        ),
        "adverse_move_first_convention": (
            "The entry-bar adverse move precedes entry. The entry bar is not reused for stop/target "
            "inference; normal evaluation begins on the immediately following one-minute bar. "
            "The accepted entry consumes the session allowance."
        ),
        "limited_replay_required": True,
        "limited_replay_scope": (
            "Only candidates already classified AMBIGUOUS_ENTRY_STOP were evaluated from the next "
            "bar for ADVERSE_MOVE_FIRST. Gate 6B artifacts do not contain their subsequent OHLC path. "
            "Signals, candidates, ordinary trades, and EXCLUDED execution were not regenerated."
        ),
        "other_ambiguity_semantics_modified": False,
        "or_width_filter_used": False,
        "winner_selected": False,
        "width_bins": "Gate 6B.1 deterministic duration-specific equal-count quintiles.",
        "input_integrity": integrity,
    }
    return metrics, trades, width_sensitivity, metadata


def _selection_records(diagnostics: pd.DataFrame) -> pd.DataFrame:
    output = diagnostics.loc[:, [*KEY_COLUMNS, "entry_time", "exit_reason", "ambiguity_reason",
                                  "ambiguity_status", "excluded_from_performance"]].copy()
    output.insert(0, "trade_id", output.apply(_trade_id_from_row, axis=1))
    output = output.rename(columns={"ambiguity_status": "ambiguous"})
    output["session_date"] = pd.to_datetime(output["session_date"]).dt.date
    return output


def _candidate_frame(audit: pd.DataFrame) -> pd.DataFrame:
    output = audit.loc[:, CANDIDATE_COLUMNS].copy()
    output["session_date"] = pd.to_datetime(output["session_date"]).dt.date
    output["or_minutes"] = output["or_minutes"].astype(int)
    output["candidate_validity"] = _to_boolean(output["candidate_validity"], "candidate_validity")
    return output


def _materialize_selected_trades(
    keys: list[tuple], scenario: str, candidate_lookup: dict, frozen_lookup: dict, adverse_lookup: dict
) -> pd.DataFrame:
    rows = []
    for key in keys:
        if key in adverse_lookup:
            if scenario == "ENTRY_FIRST":
                rows.append(_entry_first_trade(candidate_lookup[key]))
            elif scenario == "ADVERSE_MOVE_FIRST":
                rows.append(adverse_lookup[key])
            else:
                raise ValueError("EXCLUDED selected an AMBIGUOUS_ENTRY_STOP candidate")
        else:
            frozen = frozen_lookup.get(key)
            if frozen is None:
                raise ValueError("A selected nonambiguous candidate is absent from frozen Gate 6B trades")
            rows.append({column: getattr(frozen, column) for column in TRADE_COLUMNS})
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def _entry_first_trade(candidate) -> dict[str, Any]:
    risk = float(candidate.risk_points)
    return {
        "trade_id": _trade_id(candidate), "session_date": candidate.session_date,
        "contract": candidate.contract, "or_minutes": int(candidate.or_minutes),
        "breakout_type": candidate.breakout_type, "direction": candidate.direction,
        "signal_time": candidate.signal_time, "entry_time": candidate.entry_time,
        "entry_price": float(candidate.entry_price), "initial_stop": float(candidate.initial_stop),
        "initial_target": float(candidate.initial_target), "risk_points": risk,
        "exit_time": candidate.entry_time, "exit_price": float(candidate.initial_stop),
        "exit_reason": STOP, "exit_bar_close": float(candidate.entry_bar_close),
        "ambiguous": False, "ambiguity_reason": "", "holding_bars": 1,
        "holding_minutes": 0, "pnl_points": -risk, "result_r": -1.0,
        "mfe_points": np.nan, "mae_points": np.nan, "mfe_r": np.nan, "mae_r": np.nan,
        "excluded_from_performance": False,
    }


def _enrich_scenario_trades(
    trades: pd.DataFrame, diagnostics: pd.DataFrame, config_id: str, scenario: str, ambiguous_keys: set
) -> pd.DataFrame:
    trades = trades.copy()
    trades["session_date"] = pd.to_datetime(trades["session_date"]).dt.normalize()
    extra = diagnostics.loc[:, [*KEY_COLUMNS, *DIAGNOSTIC_COLUMNS]].copy()
    output = trades.merge(extra, on=KEY_COLUMNS, validate="one_to_one")
    output.insert(0, "config_id", config_id)
    output.insert(1, "research_scope", "DEVELOPMENT_ONLY")
    output.insert(2, "scenario", scenario)
    output["original_entry_stop_ambiguous"] = [
        _key(row) in ambiguous_keys for row in output[KEY_COLUMNS].itertuples(index=False)
    ]
    output["performance_included"] = ~output["excluded_from_performance"].astype(bool)
    output["scenario_source"] = np.select(
        [
            output["original_entry_stop_ambiguous"] & output["scenario"].eq("ENTRY_FIRST"),
            output["original_entry_stop_ambiguous"] & output["scenario"].eq("ADVERSE_MOVE_FIRST"),
        ],
        ["ENTRY_FIRST_MINUS_1R", "ADVERSE_MOVE_FIRST_NEXT_BAR"],
        default="GATE6B_FROZEN_TRADE",
    )
    return output


def _scenario_metrics(config, scenario, candidates, completed, accepted, scenario_audit) -> dict[str, Any]:
    included = accepted.loc[accepted["performance_included"]].copy()
    values = included["result_r"].astype(float)
    positive, negative = values.loc[values.gt(0)], values.loc[values.lt(0)]
    gross_loss = abs(float(negative.sum()))
    ordered = included.sort_values(["entry_time", "signal_time", "trade_id"], kind="stable")
    rolling_100 = ordered["result_r"].rolling(100, min_periods=100).mean().dropna()
    monthly = included.assign(
        month=pd.to_datetime(included["session_date"]).dt.to_period("M").astype(str)
    ).groupby("month", sort=True)["result_r"].sum()
    ambiguous_count = int(completed["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP).sum())
    other_count = int(
        completed["excluded_from_performance"].astype(bool).sum() - ambiguous_count
    )
    return {
        "config_id": config.config_id, "research_scope": "DEVELOPMENT_ONLY",
        "or_minutes": int(config.or_minutes), "breakout_type": "PRINT",
        "stop_mode": config.stop_mode, "stop_definition_kind": config.stop_definition_kind,
        "configured_stop_value": float(config.configured_stop_value),
        "target_points": float(config.target_points), "scenario": scenario,
        "eligible_candidates": len(candidates), "ambiguous_entry_stop_count": ambiguous_count,
        "entry_stop_ambiguity_rate": ambiguous_count / len(candidates),
        "other_execution_ambiguity_count": other_count,
        "accepted_entries": len(accepted), "executed_trades": len(included),
        "unresolved_post_entry_exits": int((~accepted["performance_included"]).sum()),
        "wins": int(values.gt(0).sum()), "losses": int(values.lt(0).sum()),
        "flat_trades": int(values.eq(0).sum()),
        "session_end_exits": int(included["exit_reason"].eq(SESSION_END).sum()),
        "win_rate": _safe_mean(values.gt(0)), "average_r": _safe_mean(values),
        "median_r": float(values.median()) if len(values) else np.nan,
        "total_r": float(values.sum()),
        "profit_factor_r": float(positive.sum()) / gross_loss if gross_loss else np.nan,
        "max_drawdown_r": calculate_max_drawdown_r(values) if len(values) else np.nan,
        "max_consecutive_losses": max_consecutive_losses(values) if len(values) else 0,
        "positive_month_percentage": _safe_mean(monthly.gt(0), multiplier=100),
        "target_hit_percentage": _safe_mean(included["exit_reason"].eq(TARGET), multiplier=100),
        "stop_hit_percentage": _safe_mean(included["exit_reason"].eq(STOP), multiplier=100),
        "session_end_percentage": _safe_mean(included["exit_reason"].eq(SESSION_END), multiplier=100),
        "rolling_100_positive_window_percentage": _safe_mean(rolling_100.gt(0), multiplier=100),
        "average_holding_minutes": _safe_mean(included["holding_minutes"]),
        "scenario_session_trade_limit_rejections": int(
            scenario_audit["rejection_reason"].eq(SESSION_TRADE_LIMIT).sum()
        ),
    }


def add_robustness_descriptors(metrics: pd.DataFrame) -> pd.DataFrame:
    keys = ["config_id"]
    avg = metrics.pivot(index=keys, columns="scenario", values="average_r")
    pf = metrics.pivot(index=keys, columns="scenario", values="profit_factor_r")
    descriptors = pd.DataFrame({
        "excluded_avg_r": avg["EXCLUDED"],
        "entry_first_avg_r": avg["ENTRY_FIRST"],
        "adverse_move_first_avg_r": avg["ADVERSE_MOVE_FIRST"],
        "chronology_range_avg_r": avg.max(axis=1) - avg.min(axis=1),
        "excluded_pf": pf["EXCLUDED"],
        "entry_first_pf": pf["ENTRY_FIRST"],
        "adverse_move_first_pf": pf["ADVERSE_MOVE_FIRST"],
        "entry_first_positive": avg["ENTRY_FIRST"].gt(0),
        "all_scenarios_positive": avg.gt(0).all(axis=1),
        "all_scenarios_pf_above_1": pf.gt(1).all(axis=1),
    }).reset_index()
    return metrics.merge(descriptors, on="config_id", validate="many_to_one")


def calculate_width_sensitivity(
    metrics: pd.DataFrame, trades: pd.DataFrame, diagnostics: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    for config in metrics.drop_duplicates("config_id").itertuples(index=False):
        candidates = diagnostics.loc[diagnostics["config_id"].eq(config.config_id)]
        config_trades = trades.loc[trades["config_id"].eq(config.config_id)]
        for quintile in QUINTILES:
            candidate_bin = candidates.loc[candidates["or_width_quintile"].eq(quintile)]
            ambiguous = candidate_bin["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP)
            row = {
                "research_scope": "DEVELOPMENT_ONLY", "config_id": config.config_id,
                "or_minutes": int(config.or_minutes), "stop_mode": config.stop_mode,
                "target_points": float(config.target_points), "or_width_quintile": quintile,
                "candidate_count": len(candidate_bin),
                "ambiguous_entry_stop_count": int(ambiguous.sum()),
                "entry_stop_ambiguity_rate": _safe_mean(ambiguous, multiplier=100),
            }
            scenario_values = []
            for scenario in SCENARIOS:
                selected = config_trades.loc[
                    config_trades["scenario"].eq(scenario)
                    & config_trades["or_width_quintile"].eq(quintile)
                    & config_trades["performance_included"]
                ]
                value = _safe_mean(selected["result_r"])
                row[f"{scenario.lower()}_executed_trades"] = len(selected)
                row[f"{scenario.lower()}_average_r"] = value
                scenario_values.append(value)
            valid_values = [value for value in scenario_values if pd.notna(value)]
            row["chronology_range_avg_r"] = max(valid_values) - min(valid_values)
            rows.append(row)
    output = pd.DataFrame(rows)
    if len(output) != EXPECTED_CONFIGURATIONS * len(QUINTILES):
        raise ValueError("Gate 6B.2 width sensitivity must contain 375 rows")
    return output


def _validate_outputs(metrics, trades, width, gate6_summary, start, end) -> None:
    if len(metrics) != EXPECTED_SCENARIO_ROWS:
        raise ValueError("Gate 6B.2 must contain exactly 225 scenario rows")
    if metrics["config_id"].nunique() != EXPECTED_CONFIGURATIONS:
        raise ValueError("Gate 6B.2 must contain exactly 75 configurations")
    if not metrics.groupby("config_id")["scenario"].nunique().eq(3).all():
        raise ValueError("Every Gate 6B.2 configuration must contain three scenarios")
    if set(metrics["scenario"]) != set(SCENARIOS):
        raise ValueError("Gate 6B.2 has unexpected scenarios")
    dates = pd.to_datetime(trades["session_date"])
    if not dates.between(start, end).all() or dates.max() > pd.Timestamp("2025-06-30"):
        raise ValueError("A reserved-period trade entered Gate 6B.2")
    if trades.duplicated(["config_id", "scenario", "session_date"]).any():
        raise ValueError("Gate 6B.2 has duplicate accepted same-session trades")
    excluded = metrics.loc[metrics["scenario"].eq("EXCLUDED")]
    merged = excluded.merge(gate6_summary, on="config_id", suffixes=("_gate6b2", "_gate6b"), validate="one_to_one")
    for metric in SUMMARY_METRICS:
        left = pd.to_numeric(merged[f"{metric}_gate6b2"])
        right = pd.to_numeric(merged[f"{metric}_gate6b"])
        if not np.allclose(left, right, rtol=0, atol=1e-12, equal_nan=True):
            raise ValueError(f"EXCLUDED does not reproduce Gate 6B: {metric}")
    if not np.array_equal(
        excluded.sort_values("config_id")["eligible_candidates"].to_numpy(),
        gate6_summary.sort_values("config_id")["eligible_candidates"].to_numpy(),
    ):
        raise ValueError("EXCLUDED eligible candidate counts do not reproduce Gate 6B")
    if len(width) != 375 or width[["config_id", "or_width_quintile"]].duplicated().any():
        raise ValueError("Gate 6B.2 width output is incomplete or duplicated")


def _assert_resolved_ambiguity_consumes_session(candidates, completed, audit, ambiguous_keys) -> None:
    selected_keys = {
        _key(row)
        for row in audit.loc[audit["gate4d_status"].eq(EXECUTED), KEY_COLUMNS].itertuples(index=False)
    }
    ordered = candidates.assign(
        _sort_time=candidates["entry_time"].where(candidates["entry_time"].notna(), candidates["signal_time"])
    ).sort_values(["session_date", "or_minutes", "breakout_type", "_sort_time", "signal_time", "direction"])
    completed_keys = {_key(row) for row in completed[KEY_COLUMNS].itertuples(index=False)}
    for _, group in ordered.groupby(["session_date", "or_minutes", "breakout_type"]):
        valid = [
            _key(row) for row in group.drop(columns="_sort_time").itertuples(index=False)
            if bool(row.candidate_validity) and _key(row) in completed_keys
        ]
        if valid and valid[0] in ambiguous_keys and valid[0] not in selected_keys:
            raise ValueError("A resolved first ambiguous candidate did not consume the session allowance")


def write_outputs(
    metrics: pd.DataFrame, trades: pd.DataFrame, width: pd.DataFrame,
    metadata: dict[str, Any], output_dir: str | Path,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "orb_gate6b2_DEV_ambiguity_robustness"
    paths = {
        "scenario_summary": output_dir / f"{prefix}_summary.csv",
        "scenario_trades": output_dir / f"{prefix}_trades.csv",
        "or_width_sensitivity": output_dir / f"{prefix}_or_width.csv",
        "metadata": output_dir / f"{prefix}_metadata.json",
        "entry_first_heatmap": output_dir / f"{prefix}_entry_first_average_r_heatmap.html",
        "all_positive_heatmap": output_dir / f"{prefix}_all_scenarios_positive_heatmap.html",
        "chronology_range_heatmap": output_dir / f"{prefix}_chronology_range_heatmap.html",
        "scenario_comparison": output_dir / f"{prefix}_scenario_comparison.html",
        "ambiguity_by_width": output_dir / f"{prefix}_ambiguity_by_or_width.html",
    }
    metrics.to_csv(paths["scenario_summary"], index=False)
    _csv_ready(trades).to_csv(paths["scenario_trades"], index=False)
    width.to_csv(paths["or_width_sensitivity"], index=False)
    _write_surface(metrics, "entry_first_avg_r", "ENTRY_FIRST Avg R", paths["entry_first_heatmap"])
    _write_surface(
        metrics, "all_scenarios_positive", "All scenarios Avg R > 0",
        paths["all_positive_heatmap"], categorical=True,
    )
    _write_surface(
        metrics, "chronology_range_avg_r", "Chronology range in Avg R",
        paths["chronology_range_heatmap"], reverse=True,
    )
    _write_scenario_comparison(metrics, paths["scenario_comparison"])
    _write_width_comparison(width, paths["ambiguity_by_width"])
    metadata = {**metadata, "artifacts": {name: str(path) for name, path in paths.items()}}
    paths["metadata"].write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return paths


def _write_surface(metrics, column, label, path, *, categorical=False, reverse=False) -> None:
    source = metrics.drop_duplicates("config_id")
    figure = make_subplots(rows=2, cols=3, subplot_titles=STOP_MODES)
    for index, stop_mode in enumerate(STOP_MODES):
        row, col = index // 3 + 1, index % 3 + 1
        selected = source.loc[source["stop_mode"].eq(stop_mode)]
        pivot = selected.pivot(index="or_minutes", columns="target_points", values=column).reindex(
            index=OR_DURATIONS, columns=TARGET_POINTS_VALUES
        )
        values = pivot.astype(float).to_numpy()
        colorscale = "RdYlGn" if categorical else ("RdYlGn_r" if reverse else "RdYlGn")
        text_values = np.vectorize(lambda value: "YES" if value else "NO")(values) if categorical else np.vectorize(
            lambda value: f"{value:.3f}"
        )(values)
        figure.add_trace(go.Heatmap(
            z=values, x=list(TARGET_POINTS_VALUES), y=[f"{d}m" for d in OR_DURATIONS],
            text=text_values, texttemplate="%{text}", colorscale=colorscale,
            zmin=0 if categorical else None, zmax=1 if categorical else None,
            showscale=index == 0, hovertemplate=(
                f"{stop_mode}<br>OR: %{{y}}<br>Target: %{{x:g}} points<br>{label}: %{{text}}<extra></extra>"
            ),
        ), row=row, col=col)
    figure.update_layout(
        title=f"Gate 6B.2 — {label} — DEVELOPMENT ONLY", template="plotly_white",
        height=760, width=1320,
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def _write_scenario_comparison(metrics, path) -> None:
    configs = list(metrics["config_id"].drop_duplicates())
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Average R", "Profit Factor"))
    for index, config_id in enumerate(configs):
        selected = metrics.loc[metrics["config_id"].eq(config_id)].set_index("scenario").reindex(SCENARIOS)
        visible = index == 0
        figure.add_trace(go.Scatter(
            x=list(SCENARIOS), y=selected["average_r"], mode="lines+markers", name=config_id,
            visible=visible, hovertemplate="%{x}<br>Avg R: %{y:.4f}<extra></extra>",
        ), row=1, col=1)
        figure.add_trace(go.Scatter(
            x=list(SCENARIOS), y=selected["profit_factor_r"], mode="lines+markers", name=config_id,
            showlegend=False, visible=visible, hovertemplate="%{x}<br>PF: %{y:.4f}<extra></extra>",
        ), row=1, col=2)
    buttons = []
    for index, config_id in enumerate(configs):
        visible = [False] * (2 * len(configs))
        visible[2 * index] = visible[2 * index + 1] = True
        buttons.append({"label": config_id, "method": "update", "args": [{"visible": visible}, {"title": f"Gate 6B.2 — {config_id} — DEVELOPMENT ONLY"}]})
    figure.update_layout(
        title=f"Gate 6B.2 — {configs[0]} — DEVELOPMENT ONLY", template="plotly_white",
        height=620, width=1200, updatemenus=[{"buttons": buttons, "x": 0, "y": 1.18}],
    )
    figure.add_hline(y=0, line_dash="dot", line_color="black", row=1, col=1)
    figure.add_hline(y=1, line_dash="dot", line_color="black", row=1, col=2)
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def _write_width_comparison(width, path) -> None:
    configs = list(width["config_id"].drop_duplicates())
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    colors = {"EXCLUDED": "#455a64", "ENTRY_FIRST": "#c62828", "ADVERSE_MOVE_FIRST": "#2e7d32"}
    for index, config_id in enumerate(configs):
        selected = width.loc[width["config_id"].eq(config_id)].sort_values("or_width_quintile")
        visible = index == 0
        figure.add_trace(go.Bar(
            x=[f"Q{q}" for q in selected["or_width_quintile"]],
            y=selected["entry_stop_ambiguity_rate"], name="Entry-stop ambiguity %",
            opacity=0.28, marker_color="#ff9800", visible=visible,
            customdata=selected[["candidate_count", "ambiguous_entry_stop_count"]],
            hovertemplate="%{x}<br>Ambiguity: %{y:.2f}%<br>Candidates: %{customdata[0]}<br>Ambiguous: %{customdata[1]}<extra></extra>",
        ), secondary_y=True)
        for scenario in SCENARIOS:
            figure.add_trace(go.Scatter(
                x=[f"Q{q}" for q in selected["or_width_quintile"]],
                y=selected[f"{scenario.lower()}_average_r"], mode="lines+markers",
                name=scenario, line={"color": colors[scenario]}, visible=visible,
                hovertemplate=f"%{{x}}<br>{scenario} Avg R: %{{y:.4f}}<extra></extra>",
            ), secondary_y=False)
    traces_per_config = 4
    buttons = []
    for index, config_id in enumerate(configs):
        visible = [False] * (traces_per_config * len(configs))
        for offset in range(traces_per_config):
            visible[traces_per_config * index + offset] = True
        buttons.append({"label": config_id, "method": "update", "args": [{"visible": visible}, {"title": f"Gate 6B.2 — OR-width chronology — {config_id} — DEVELOPMENT ONLY"}]})
    figure.update_yaxes(title_text="Average R", secondary_y=False)
    figure.update_yaxes(title_text="AMBIGUOUS_ENTRY_STOP rate (%)", secondary_y=True)
    figure.update_layout(
        title=f"Gate 6B.2 — OR-width chronology — {configs[0]} — DEVELOPMENT ONLY",
        template="plotly_white", height=680, width=1180,
        updatemenus=[{"buttons": buttons, "x": 0, "y": 1.18}], barmode="overlay",
    )
    figure.add_hline(y=0, line_dash="dot", line_color="black", secondary_y=False)
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


def _trade_lookup(trades: pd.DataFrame) -> dict[tuple, Any]:
    return {_key(row): row for row in trades.itertuples(index=False)}


def _key(row) -> tuple:
    return (
        pd.Timestamp(getattr(row, "session_date")).date(),
        int(getattr(row, "or_minutes")),
        str(getattr(row, "breakout_type")),
        str(getattr(row, "direction")),
        pd.Timestamp(getattr(row, "signal_time")),
    )


def _trade_id(candidate) -> str:
    return (
        f"{candidate.session_date.isoformat()}_{int(candidate.or_minutes)}m_"
        f"PRINT_{str(candidate.direction).upper()}_{pd.Timestamp(candidate.signal_time).strftime('%H%M')}"
    )


def _trade_id_from_row(row: pd.Series) -> str:
    date = pd.Timestamp(row["session_date"]).date().isoformat()
    return f"{date}_{int(row['or_minutes'])}m_PRINT_{str(row['direction']).upper()}_{pd.Timestamp(row['signal_time']).strftime('%H%M')}"


def _safe_mean(values, *, multiplier: float = 1.0) -> float:
    return float(pd.Series(values).mean() * multiplier) if len(values) else np.nan


def _assert_development(summary, start, end) -> None:
    if not pd.to_datetime(summary["development_start"]).eq(start).all():
        raise ValueError("Gate 6B summary has unexpected DEVELOPMENT start")
    if not pd.to_datetime(summary["development_end"]).eq(end).all():
        raise ValueError("Gate 6B summary has unexpected DEVELOPMENT end")


def _to_boolean(values: pd.Series, column: str) -> pd.Series:
    if values.dtype == bool:
        return values
    mapped = values.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise ValueError(f"{column} contains non-boolean values")
    return mapped


def _csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["session_date"] = output["session_date"].astype(str)
    for column in ("signal_time", "entry_time", "exit_time"):
        output[column] = output[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
    return output
