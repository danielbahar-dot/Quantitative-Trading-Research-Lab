"""Gate 7 confirmatory Validation for three frozen MNQ ORB V0.1 candidates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backtesting.completed_trades import (
    AMBIGUOUS_ENTRY_STOP,
    REGULAR_SESSION_END,
    SESSION_END,
    STOP,
    TARGET,
    simulate_completed_trades,
)
from src.backtesting.session_trade_limit import apply_session_trade_limit
from src.experiments.orb_gate6a1_ambiguity import _simulate_after_entry_bar
from src.experiments.orb_gate6b_fixed_points import (
    _annotate_audit,
    _assert_completed_r_math,
    _build_or_width_diagnostics,
    _configuration_metrics,
    _enrich_executed,
    build_gate6b_candidates,
)
from src.experiments.orb_gate6b2_ambiguity_robustness import (
    SCENARIOS,
    _assert_resolved_ambiguity_consumes_session,
    _candidate_frame,
    _enrich_scenario_trades,
    _key,
    _materialize_selected_trades,
    _scenario_metrics,
    _selection_records,
    _trade_lookup,
    add_robustness_descriptors,
)
from src.features.opening_range import calculate_opening_range
from src.visualization.research_viewer import find_orb_signals


STRATEGY_VERSION = "MNQ_ORB_V0.1"
PARTITION = "VALIDATION"
APPROVED_CANDIDATES = (
    {
        "candidate_id": "MNQ_ORB_V01_CAND_001",
        "config_id": "15m_PRINT_FIXED_50_TARGET75PT",
        "or_minutes": 15,
        "stop_mode": "FIXED_50",
        "stop_definition_kind": "FIXED_POINTS",
        "configured_stop_value": 50.0,
        "target_points": 75.0,
    },
    {
        "candidate_id": "MNQ_ORB_V01_CAND_002",
        "config_id": "20m_PRINT_OR_MIDPOINT_TARGET75PT",
        "or_minutes": 20,
        "stop_mode": "OR_MIDPOINT",
        "stop_definition_kind": "OR_FRACTION",
        "configured_stop_value": 0.5,
        "target_points": 75.0,
    },
    {
        "candidate_id": "MNQ_ORB_V01_CAND_003",
        "config_id": "30m_PRINT_FIXED_40_TARGET75PT",
        "or_minutes": 30,
        "stop_mode": "FIXED_40",
        "stop_definition_kind": "FIXED_POINTS",
        "configured_stop_value": 40.0,
        "target_points": 75.0,
    },
)
APPROVED_IDS = tuple(item["candidate_id"] for item in APPROVED_CANDIDATES)


def validate_frozen_contract(specification: dict[str, Any], protocol: dict[str, Any]) -> None:
    if specification["freeze_status"] != "FROZEN_FOR_VALIDATION":
        raise ValueError("The DEVELOPMENT package is not frozen for Validation")
    if protocol["status"] != "PREDECLARED_LOCKED" or not protocol["created_before_validation_access"]:
        raise ValueError("The Gate 7 protocol was not locked before Validation access")
    if tuple(protocol["frozen_candidate_ids"]) != APPROVED_IDS:
        raise ValueError("Protocol candidate IDs differ from the frozen three")
    observed = {
        item["candidate_id"]: (
            item["configuration_id"], int(item["or_minutes"]),
            item["stop"]["mode"], float(item["target"]["points"]),
        )
        for item in specification["candidates"]
    }
    expected = {
        item["candidate_id"]: (
            item["config_id"], item["or_minutes"], item["stop_mode"], item["target_points"]
        )
        for item in APPROVED_CANDIDATES
    }
    if observed != expected:
        raise ValueError("Frozen candidate parameters differ from the approved Gate 6C definitions")
    excluded = set(protocol["explicitly_excluded_ids"])
    if excluded != {"MNQ_ORB_V01_HYP_001", "MNQ_ORB_V01_HYP_002"}:
        raise ValueError("Gate 6C research hypotheses are not explicitly excluded")
    if tuple(protocol["chronology_scenarios"]) != SCENARIOS:
        raise ValueError("Gate 7 chronology scenarios differ from Gate 6B.2")


def build_partition_or_levels(price_data: pd.DataFrame) -> pd.DataFrame:
    """Build only the frozen-candidate OR levels from the already-isolated partition."""
    rows = []
    durations = tuple(item["or_minutes"] for item in APPROVED_CANDIDATES)
    for session_date, session in price_data.groupby("session_date", sort=True):
        contracts = session["contract"].dropna().unique() if "contract" in session else []
        contract = contracts[0] if len(contracts) == 1 else "MULTIPLE"
        for duration in durations:
            result = calculate_opening_range(session, duration)
            rows.append({
                "session_date": session_date,
                "contract": contract,
                "or_minutes": duration,
                "valid_or": result is not None,
                "or_high": result["or_high"] if result else np.nan,
                "or_low": result["or_low"] if result else np.nan,
                "or_mid": result["or_mid"] if result else np.nan,
                "or_width": result["or_width"] if result else np.nan,
            })
    output = pd.DataFrame(rows)
    if set(output["or_minutes"].unique()) != set(durations):
        raise ValueError("Validation OR levels do not cover the frozen durations")
    return output


def run_validation(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
    development_summary: pd.DataFrame,
    development_evidence: pd.DataFrame,
    protocol: dict[str, Any],
    *,
    validation_start: pd.Timestamp,
    validation_end: pd.Timestamp,
    source_git_commit: str,
    run_timestamp: str,
) -> dict[str, pd.DataFrame]:
    dates = pd.to_datetime(price_data["session_date"])
    if not dates.between(validation_start, validation_end, inclusive="both").all():
        raise ValueError("A non-Validation price row entered Gate 7")
    if dates.min() < pd.Timestamp("2025-07-01") or dates.max() > pd.Timestamp("2025-12-31"):
        raise ValueError("Gate 7 price input breaches the predefined Validation partition")
    sessions_available = int(dates.nunique())
    config_ids = {item["config_id"] for item in APPROVED_CANDIDATES}
    dev = development_summary.loc[development_summary["config_id"].isin(config_ids)].copy()
    evidence = development_evidence.loc[development_evidence["config_id"].isin(config_ids)].copy()
    if len(dev) != 3 or len(evidence) != 3:
        raise ValueError("DEVELOPMENT references do not reconcile to the frozen candidates")

    summary_rows, executed_frames, completed_frames = [], [], []
    audit_frames, ambiguity_frames, chronology_frames = [], [], []
    diagnostics_frames = []
    sessions = {session_date: group for session_date, group in price_data.groupby("session_date")}

    for definition in APPROVED_CANDIDATES:
        config = SimpleNamespace(**definition)
        signals, signal_ambiguities = find_orb_signals(
            price_data,
            or_levels,
            start_date=validation_start,
            end_date=validation_end,
            or_minutes=config.or_minutes,
            breakout_type="PRINT",
        )
        _assert_signal_scope(signals, validation_start, validation_end, config.or_minutes)
        candidates = build_gate6b_candidates(
            price_data,
            signals,
            or_minutes=config.or_minutes,
            stop_mode=config.stop_mode,
            target_points=config.target_points,
        )
        completed = simulate_completed_trades(price_data, candidates)
        _assert_completed_r_math(completed)
        executed, audit = apply_session_trade_limit(candidates, completed)
        if executed.duplicated(["session_date", "or_minutes", "breakout_type"]).any():
            raise ValueError("Gate 7 exceeds one accepted trade per session/candidate")

        enriched = _enrich_executed(executed, candidates, config)
        annotated_audit = _annotate_audit(audit, config)
        diagnostics = _build_or_width_diagnostics(annotated_audit, completed, config)
        for frame in (enriched, annotated_audit, diagnostics):
            frame["research_scope"] = "VALIDATION_ONLY"
            frame.insert(0, "candidate_id", config.candidate_id)
        completed_out = completed.copy()
        completed_out.insert(0, "candidate_id", config.candidate_id)
        completed_out.insert(1, "config_id", config.config_id)
        completed_out.insert(2, "research_scope", "VALIDATION_ONLY")
        ambiguity_out = signal_ambiguities.copy()
        ambiguity_out.insert(0, "candidate_id", config.candidate_id)
        ambiguity_out.insert(1, "config_id", config.config_id)
        ambiguity_out.insert(2, "research_scope", "VALIDATION_ONLY")

        metrics = _configuration_metrics(
            config,
            candidates,
            completed,
            executed,
            enriched,
            annotated_audit,
            signal_ambiguities,
            validation_start,
            validation_end,
            0,
        )
        metrics.update({
            "candidate_id": config.candidate_id,
            "research_scope": "VALIDATION_ONLY",
            "validation_start": validation_start.date().isoformat(),
            "validation_end": validation_end.date().isoformat(),
            "sessions_available": sessions_available,
        })
        summary_rows.append(metrics)
        chronology_frames.append(_chronology_for_config(
            config,
            candidates=annotated_audit,
            completed=completed,
            diagnostics=diagnostics,
            frozen_trades=enriched,
            sessions=sessions,
            signal_ambiguity_count=len(signal_ambiguities),
        ))
        executed_frames.append(enriched)
        completed_frames.append(completed_out)
        audit_frames.append(annotated_audit)
        ambiguity_frames.append(ambiguity_out)
        diagnostics_frames.append(diagnostics)

    summary = pd.DataFrame(summary_rows)
    executed = pd.concat(executed_frames, ignore_index=True)
    completed = pd.concat(completed_frames, ignore_index=True)
    audit = pd.concat(audit_frames, ignore_index=True)
    ambiguities = pd.concat(ambiguity_frames, ignore_index=True)
    diagnostics = pd.concat(diagnostics_frames, ignore_index=True)
    chronology = pd.concat(chronology_frames, ignore_index=True)
    monthly = calculate_monthly(executed, validation_start, validation_end)
    equity = calculate_equity(executed)
    comparison = build_dev_val_comparison(summary, dev, evidence, chronology, monthly, protocol)
    _validate_results(summary, executed, chronology, comparison, validation_start, validation_end)

    outputs = {
        "summary": summary,
        "executed_trades": executed,
        "completed_trade_audit": completed,
        "candidate_audit": audit,
        "signal_ambiguity_audit": ambiguities,
        "execution_diagnostics": diagnostics,
        "chronology": chronology,
        "monthly": monthly,
        "equity": equity,
        "dev_vs_val": comparison,
    }
    return {
        key: add_run_identity(value, source_git_commit, run_timestamp)
        for key, value in outputs.items()
    }


def _chronology_for_config(config, *, candidates, completed, diagnostics, frozen_trades, sessions, signal_ambiguity_count) -> pd.DataFrame:
    candidate_frame = _candidate_frame(candidates)
    selection = _selection_records(diagnostics)
    ambiguous_mask = selection["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP)
    ambiguous_keys = {_key(row) for row in selection.loc[ambiguous_mask].itertuples(index=False)}
    candidate_lookup = {_key(row): row for row in candidate_frame.itertuples(index=False)}
    frozen_lookup = _trade_lookup(frozen_trades)
    adverse_lookup = {
        key: _simulate_after_entry_bar(sessions.get(candidate_lookup[key].session_date), candidate_lookup[key], REGULAR_SESSION_END)
        for key in ambiguous_keys
    }
    rows = []
    for scenario in SCENARIOS:
        scenario_selection = selection.copy()
        if scenario in {"ENTRY_FIRST", "ADVERSE_MOVE_FIRST"}:
            mask = scenario_selection["exit_reason"].eq(AMBIGUOUS_ENTRY_STOP)
            scenario_selection.loc[mask, "ambiguous"] = False
            scenario_selection.loc[mask, "excluded_from_performance"] = False
            scenario_selection.loc[mask, "ambiguity_reason"] = ""
            scenario_selection.loc[mask, "exit_reason"] = STOP if scenario == "ENTRY_FIRST" else "ADVERSE_MOVE_FIRST_ENTRY_ACCEPTED"
        selected, scenario_audit = apply_session_trade_limit(candidate_frame, scenario_selection)
        selected_keys = [_key(row) for row in selected.itertuples(index=False)]
        scenario_trades = _materialize_selected_trades(
            selected_keys, scenario, candidate_lookup, frozen_lookup, adverse_lookup
        )
        scenario_trades = _enrich_scenario_trades(
            scenario_trades, diagnostics, config.config_id, scenario, ambiguous_keys
        )
        scenario_trades["research_scope"] = "VALIDATION_ONLY"
        if scenario in {"ENTRY_FIRST", "ADVERSE_MOVE_FIRST"}:
            _assert_resolved_ambiguity_consumes_session(
                candidate_frame, scenario_selection, scenario_audit, ambiguous_keys
            )
        metric = _scenario_metrics(
            config, scenario, candidate_frame, selection, scenario_trades, scenario_audit
        )
        metric.update({
            "candidate_id": config.candidate_id,
            "research_scope": "VALIDATION_ONLY",
            "signal_ambiguity_count": signal_ambiguity_count,
            "ambiguity_exclusion_count": signal_ambiguity_count + int(selection["excluded_from_performance"].sum()),
            "ambiguity_rate": (
                signal_ambiguity_count + int(selection["excluded_from_performance"].sum())
            ) / len(candidate_frame),
        })
        rows.append(metric)
    return add_robustness_descriptors(pd.DataFrame(rows))


def calculate_monthly(executed: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    months = [str(period) for period in pd.period_range(start, end, freq="M")]
    rows = []
    for candidate_id in APPROVED_IDS:
        selected = executed.loc[executed["candidate_id"].eq(candidate_id)].copy()
        selected["month"] = pd.to_datetime(selected["session_date"]).dt.to_period("M").astype(str)
        for month in months:
            values = selected.loc[selected["month"].eq(month), "result_r"].astype(float)
            rows.append({
                "candidate_id": candidate_id,
                "month": month,
                "trades": len(values),
                "total_r": float(values.sum()),
                "average_r": float(values.mean()) if len(values) else np.nan,
                "win_rate": float(values.gt(0).mean()) if len(values) else np.nan,
            })
    return pd.DataFrame(rows)


def calculate_equity(executed: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for candidate_id, group in executed.groupby("candidate_id", sort=False):
        ordered = group.sort_values(["entry_time", "signal_time", "trade_id"], kind="stable").copy()
        ordered["trade_number"] = np.arange(1, len(ordered) + 1)
        ordered["equity_r"] = ordered["result_r"].astype(float).cumsum()
        frames.append(ordered[["candidate_id", "trade_id", "session_date", "entry_time", "trade_number", "result_r", "equity_r"]])
    return pd.concat(frames, ignore_index=True)


def build_dev_val_comparison(summary, dev, evidence, chronology, monthly, protocol) -> pd.DataFrame:
    candidate_lookup = {item["config_id"]: item["candidate_id"] for item in APPROVED_CANDIDATES}
    dev = dev.copy()
    dev["candidate_id"] = dev["config_id"].map(candidate_lookup)
    evidence = evidence.copy()
    evidence["candidate_id"] = evidence["config_id"].map(candidate_lookup)
    chronology_one = chronology.drop_duplicates("candidate_id").set_index("candidate_id")
    summary_one = summary.set_index("candidate_id")
    dev_one = dev.set_index("candidate_id")
    evidence_one = evidence.set_index("candidate_id")
    rows = []
    for candidate_id in APPROVED_IDS:
        val = summary_one.loc[candidate_id]
        development = dev_one.loc[candidate_id]
        dev_obs = evidence_one.loc[candidate_id]
        chrono = chronology_one.loc[candidate_id]
        candidate_months = monthly.loc[monthly["candidate_id"].eq(candidate_id)].sort_values("month")
        temporal = temporal_consistency(candidate_months)
        avg_delta = float(val.average_r - development.average_r)
        relative = avg_delta / float(development.average_r) if float(development.average_r) > 0 else np.nan
        edge, borderline = classify_edge(
            float(val.average_r), float(val.profit_factor_r),
            float(chrono.entry_first_avg_r), float(chrono.entry_first_pf), protocol,
        )
        degradation = classify_degradation(float(val.average_r), float(development.average_r))
        observability = classify_observability(
            chrono,
            val_ambiguity=float(val.ambiguity_rate),
            dev_ambiguity=float(development.ambiguity_rate),
            dev_chronology_range=float(dev_obs.chronology_range_avg_r),
            protocol=protocol,
        )
        overall = classify_overall(edge, degradation, temporal["temporal_consistency"], observability)
        rows.append({
            "candidate_id": candidate_id,
            "config_id": val.config_id,
            "development_trades": int(development.executed_trades),
            "validation_trades": int(val.executed_trades),
            "development_average_r": float(development.average_r),
            "validation_average_r": float(val.average_r),
            "avg_r_delta": avg_delta,
            "avg_r_relative_change": relative,
            "development_profit_factor_r": float(development.profit_factor_r),
            "validation_profit_factor_r": float(val.profit_factor_r),
            "pf_delta": float(val.profit_factor_r - development.profit_factor_r),
            "development_max_drawdown_r": float(development.max_drawdown_r),
            "validation_max_drawdown_r": float(val.max_drawdown_r),
            "development_win_rate": float(development.win_rate),
            "validation_win_rate": float(val.win_rate),
            "win_rate_delta": float(val.win_rate - development.win_rate),
            "development_ambiguity_rate": float(development.ambiguity_rate),
            "validation_ambiguity_rate": float(val.ambiguity_rate),
            "ambiguity_delta": float(val.ambiguity_rate - development.ambiguity_rate),
            "validation_entry_first_average_r": float(chrono.entry_first_avg_r),
            "validation_entry_first_pf": float(chrono.entry_first_pf),
            "validation_adverse_move_first_average_r": float(chrono.adverse_move_first_avg_r),
            "validation_adverse_move_first_pf": float(chrono.adverse_move_first_pf),
            "validation_chronology_range_average_r": float(chrono.chronology_range_avg_r),
            "edge_borderline": borderline,
            "edge_survival": edge,
            "degradation": degradation,
            **temporal,
            "observability": observability,
            "overall_decision": overall,
        })
    return pd.DataFrame(rows)


def classify_edge(excluded_avg, excluded_pf, entry_avg, entry_pf, protocol) -> tuple[str, bool]:
    if excluded_avg <= 0 or excluded_pf <= 1:
        return "FAILED", False
    if entry_avg <= 0 or entry_pf <= 1:
        return "MIXED", False
    avg_margin = float(protocol["borderline_rules"]["average_r_absolute_threshold"])
    pf_margin = float(protocol["borderline_rules"]["profit_factor_distance_from_one"])
    borderline = min(excluded_avg, entry_avg) < avg_margin or min(excluded_pf, entry_pf) - 1 < pf_margin
    return ("MIXED" if borderline else "STRONG"), borderline


def classify_degradation(validation_avg: float, development_avg: float) -> str:
    if validation_avg <= 0:
        return "SIGN_REVERSAL"
    retained = validation_avg / development_avg
    if retained >= 0.75 or np.isclose(retained, 0.75, rtol=0, atol=1e-12):
        return "LOW"
    if retained >= 0.50 or np.isclose(retained, 0.50, rtol=0, atol=1e-12):
        return "MODERATE"
    return "HIGH"


def temporal_consistency(monthly: pd.DataFrame) -> dict[str, Any]:
    values = monthly["total_r"].astype(float).to_numpy()
    positive = values[values > 0]
    concentration = float(positive.max() / positive.sum()) if len(positive) else np.nan
    first_half = float(values[:3].sum())
    second_half = float(values[3:].sum())
    total = float(values.sum())
    unstable = total <= 0 or (first_half > 0 and second_half < 0 and abs(second_half) >= 0.5 * first_half)
    positive_pct = float((values > 0).mean() * 100)
    if unstable:
        label = "UNSTABLE"
    elif positive_pct >= 50 and concentration <= 0.60:
        label = "BROAD"
    else:
        label = "CONCENTRATED"
    return {
        "validation_positive_month_percentage": positive_pct,
        "positive_month_concentration": concentration,
        "first_half_total_r": first_half,
        "second_half_total_r": second_half,
        "temporal_consistency": label,
    }


def classify_observability(chrono, *, val_ambiguity, dev_ambiguity, dev_chronology_range, protocol) -> str:
    if float(chrono.entry_first_avg_r) <= 0 or float(chrono.entry_first_pf) <= 1:
        return "FAILED"
    if not bool(chrono.all_scenarios_positive and chrono.all_scenarios_pf_above_1):
        return "CAUTION"
    rules = protocol["decision_framework"]["observability"]
    material_range = max(
        float(rules["material_chronology_range_absolute_r"]),
        float(rules["material_chronology_range_multiple_of_development"]) * dev_chronology_range,
    )
    caution = (
        val_ambiguity >= float(rules["high_validation_ambiguity_rate"])
        or val_ambiguity - dev_ambiguity >= float(rules["material_ambiguity_increase_points"])
        or float(chrono.chronology_range_avg_r) > material_range
    )
    return "CAUTION" if caution else "STRONG"


def classify_overall(edge: str, degradation: str, temporal: str, observability: str) -> str:
    if edge == "FAILED" or observability == "FAILED":
        return "REJECT"
    if edge == "STRONG" and degradation in {"LOW", "MODERATE"} and temporal == "BROAD" and observability == "STRONG":
        return "PASS"
    return "REVISE"


def add_run_identity(frame: pd.DataFrame, source_git_commit: str, run_timestamp: str) -> pd.DataFrame:
    output = frame.copy()
    for position, (column, value) in enumerate((
        ("strategy_version", STRATEGY_VERSION),
        ("partition", PARTITION),
        ("source_git_commit", source_git_commit),
        ("run_timestamp_utc", run_timestamp),
    )):
        if column in output:
            output[column] = value
        else:
            output.insert(position, column, value)
    return output


def write_outputs(results: dict[str, pd.DataFrame], metadata: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary": output_dir / "orb_v01_gate7_VALIDATION_summary.csv",
        "executed_trades": output_dir / "orb_v01_gate7_VALIDATION_executed_trades.csv",
        "completed_trade_audit": output_dir / "orb_v01_gate7_VALIDATION_completed_trade_audit.csv",
        "candidate_audit": output_dir / "orb_v01_gate7_VALIDATION_candidate_audit.csv",
        "signal_ambiguity_audit": output_dir / "orb_v01_gate7_VALIDATION_signal_ambiguity_audit.csv",
        "execution_diagnostics": output_dir / "orb_v01_gate7_VALIDATION_execution_diagnostics.csv",
        "dev_vs_val": output_dir / "orb_v01_gate7_DEV_vs_VALIDATION.csv",
        "chronology": output_dir / "orb_v01_gate7_VALIDATION_chronology.csv",
        "monthly": output_dir / "orb_v01_gate7_VALIDATION_monthly.csv",
        "equity": output_dir / "orb_v01_gate7_VALIDATION_equity_curves.csv",
        "metadata": output_dir / "orb_v01_gate7_VALIDATION_metadata.json",
        "report": output_dir / "orb_v01_gate7_VALIDATION_report.md",
        "comparison_html": output_dir / "orb_v01_gate7_DEV_vs_VALIDATION.html",
        "equity_html": output_dir / "orb_v01_gate7_VALIDATION_equity_curves.html",
        "monthly_html": output_dir / "orb_v01_gate7_VALIDATION_monthly.html",
        "chronology_html": output_dir / "orb_v01_gate7_VALIDATION_chronology.html",
    }
    for key in ("summary", "executed_trades", "completed_trade_audit", "candidate_audit", "signal_ambiguity_audit", "execution_diagnostics", "dev_vs_val", "chronology", "monthly", "equity"):
        _csv_ready(results[key]).to_csv(paths[key], index=False)
    paths["report"].write_text(build_report(results["dev_vs_val"], results["monthly"], metadata), encoding="utf-8")
    write_visualizations(results, paths, metadata)
    metadata = {**metadata, "outputs": {key: str(path) for key, path in paths.items()}}
    paths["metadata"].write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return paths


def build_report(comparison: pd.DataFrame, monthly: pd.DataFrame, metadata: dict[str, Any]) -> str:
    lines = [
        "# Gate 7 — MNQ ORB V0.1 confirmatory Validation", "",
        f"Validation: {metadata['validation_start']} through {metadata['validation_end']}.",
        f"Frozen source: `{metadata['source_git_commit']}` / `{metadata['freeze_git_tag']}`.", "",
        "Validation evaluated exactly three frozen hypotheses; it did not optimize or select a winner.", "",
    ]
    for row in comparison.itertuples(index=False):
        lines.extend([
            f"## {row.candidate_id} — {row.config_id}", "",
            f"- DEVELOPMENT: {int(row.development_trades)} trades, Avg R {row.development_average_r:.3f}, PF {row.development_profit_factor_r:.2f}, max DD {row.development_max_drawdown_r:.2f}R.",
            f"- VALIDATION: {int(row.validation_trades)} trades, Avg R {row.validation_average_r:.3f}, PF {row.validation_profit_factor_r:.2f}, max DD {row.validation_max_drawdown_r:.2f}R.",
            f"- Change: Avg R {row.avg_r_delta:+.3f} ({row.avg_r_relative_change:+.1%}), PF {row.pf_delta:+.2f}, ambiguity {row.ambiguity_delta:+.1%}.",
            f"- Chronology: ENTRY_FIRST Avg R {row.validation_entry_first_average_r:.3f}, PF {row.validation_entry_first_pf:.2f}; range {row.validation_chronology_range_average_r:.3f}R.",
            f"- Temporal: {row.temporal_consistency}; {row.validation_positive_month_percentage:.1f}% positive months; first half {row.first_half_total_r:.2f}R, second half {row.second_half_total_r:.2f}R.",
            f"- Assessment: edge **{row.edge_survival}**; degradation **{row.degradation}**; observability **{row.observability}**; overall **{row.overall_decision}**.", "",
        ])
    lines.extend([
        "## Research discipline", "",
        "No target, stop, OR duration, ambiguity rule, cutoff, feature, filter, portfolio weight, or nearby parameter was changed or tested.",
        "HYP_001/HYP_002 and OOS_BURNED were not accessed. Any future idea requires a new DEVELOPMENT version and human approval.", "",
    ])
    return "\n".join(lines)


def write_visualizations(results, paths, metadata) -> None:
    comparison = results["dev_vs_val"]
    labels = comparison["candidate_id"]
    figure = make_subplots(rows=2, cols=3, subplot_titles=("Average R", "Profit Factor", "Max DD R", "Win rate", "Ambiguity rate", "Trade count"))
    pairs = (
        ("development_average_r", "validation_average_r", 1, 1, 1.0),
        ("development_profit_factor_r", "validation_profit_factor_r", 1, 2, 1.0),
        ("development_max_drawdown_r", "validation_max_drawdown_r", 1, 3, 1.0),
        ("development_win_rate", "validation_win_rate", 2, 1, 100.0),
        ("development_ambiguity_rate", "validation_ambiguity_rate", 2, 2, 100.0),
        ("development_trades", "validation_trades", 2, 3, 1.0),
    )
    for dev_col, val_col, row, col, scale in pairs:
        figure.add_trace(go.Bar(x=labels, y=comparison[dev_col] * scale, name="DEVELOPMENT", legendgroup="DEV", showlegend=(row, col) == (1, 1), marker_color="#607d8b"), row=row, col=col)
        figure.add_trace(go.Bar(x=labels, y=comparison[val_col] * scale, name="VALIDATION", legendgroup="VAL", showlegend=(row, col) == (1, 1), marker_color="#1565c0"), row=row, col=col)
    _finish_figure(figure, "Gate 7 — DEV vs VALIDATION — frozen candidates", metadata, paths["comparison_html"], 850)

    equity = results["equity"]
    figure = go.Figure()
    for candidate_id, group in equity.groupby("candidate_id", sort=False):
        figure.add_trace(go.Scatter(x=group["entry_time"], y=group["equity_r"], mode="lines", name=candidate_id))
    figure.add_hline(y=0, line_dash="dot", line_color="black")
    _finish_figure(figure, "Gate 7 — VALIDATION cumulative R", metadata, paths["equity_html"], 650)

    monthly = results["monthly"]
    figure = go.Figure()
    for candidate_id, group in monthly.groupby("candidate_id", sort=False):
        figure.add_trace(go.Bar(x=group["month"], y=group["total_r"], name=candidate_id))
    figure.add_hline(y=0, line_dash="dot", line_color="black")
    _finish_figure(figure, "Gate 7 — VALIDATION monthly R", metadata, paths["monthly_html"], 650)

    chronology = results["chronology"]
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Average R", "Profit Factor"))
    for candidate_id, group in chronology.groupby("candidate_id", sort=False):
        ordered = group.set_index("scenario").reindex(SCENARIOS)
        figure.add_trace(go.Scatter(x=list(SCENARIOS), y=ordered["average_r"], mode="lines+markers", name=candidate_id), row=1, col=1)
        figure.add_trace(go.Scatter(x=list(SCENARIOS), y=ordered["profit_factor_r"], mode="lines+markers", name=candidate_id, showlegend=False), row=1, col=2)
    figure.add_hline(y=0, line_dash="dot", line_color="black", row=1, col=1)
    figure.add_hline(y=1, line_dash="dot", line_color="black", row=1, col=2)
    _finish_figure(figure, "Gate 7 — VALIDATION chronology robustness", metadata, paths["chronology_html"], 650)


def _finish_figure(figure, title, metadata, path, height) -> None:
    figure.update_layout(title=title, template="plotly_white", barmode="group", height=height, width=1280)
    figure.add_annotation(
        text=f"{STRATEGY_VERSION} | VALIDATION | source {metadata['source_git_commit'][:12]} | run {metadata['run_timestamp_utc']}",
        xref="paper", yref="paper", x=0, y=-0.16, showarrow=False, font={"size": 10},
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def _assert_signal_scope(signals, start, end, duration) -> None:
    if len(signals):
        dates = pd.to_datetime(signals["session_date"])
        if not dates.between(start, end, inclusive="both").all():
            raise ValueError("A non-Validation signal entered Gate 7")
        first = {15: (9, 46), 20: (9, 51), 30: (10, 1)}[duration]
        if not signals["signal_time"].map(lambda value: (value.hour, value.minute) >= first).all():
            raise ValueError("A frozen candidate signaled before its eligible post-OR bar")


def _validate_results(summary, executed, chronology, comparison, start, end) -> None:
    if set(summary["candidate_id"]) != set(APPROVED_IDS) or len(summary) != 3:
        raise ValueError("Gate 7 did not produce exactly three frozen candidates")
    if set(chronology["scenario"]) != set(SCENARIOS) or len(chronology) != 9:
        raise ValueError("Gate 7 chronology output is not exactly 3 x 3")
    dates = pd.to_datetime(executed["session_date"])
    if not dates.between(start, end, inclusive="both").all():
        raise ValueError("A DEVELOPMENT or OOS trade entered Gate 7")
    if executed.duplicated(["candidate_id", "session_date"]).any():
        raise ValueError("Gate 7 contains more than one accepted trade/session/candidate")
    excluded = chronology.loc[chronology["scenario"].eq("EXCLUDED")].set_index("candidate_id")
    main = summary.set_index("candidate_id")
    for metric in ("executed_trades", "wins", "losses", "average_r", "total_r", "profit_factor_r"):
        if not np.allclose(pd.to_numeric(main[metric]), pd.to_numeric(excluded.loc[main.index, metric]), rtol=0, atol=1e-12, equal_nan=True):
            raise ValueError(f"Canonical Validation and EXCLUDED chronology disagree: {metric}")
    if len(comparison) != 3 or comparison["candidate_id"].duplicated().any():
        raise ValueError("Gate 7 decision table is incomplete")


def _csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "session_date" in output:
        output["session_date"] = output["session_date"].astype(str)
    for column in ("signal_time", "entry_time", "exit_time"):
        if column in output:
            output[column] = output[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
    return output
