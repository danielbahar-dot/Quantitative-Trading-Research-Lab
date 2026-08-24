"""Gate 6C DEVELOPMENT-only candidate reduction and freeze preparation.

This module reads frozen Gate 6B/6B.1/6B.2 evidence. It does not regenerate
signals, candidates, trades, parameters, or reserved-period performance. The
proposed shortlist is explicit and remains pending human approval.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.experiments.orb_gate6b_fixed_points import (
    EXPECTED_CONFIGURATIONS,
    OR_DURATIONS,
    STOP_DEFINITIONS,
    TARGET_POINTS_VALUES,
)


CORE_CLASS = "CORE_SHORTLIST"
HYPOTHESIS_CLASS = "RESEARCH_HYPOTHESIS"
ROBUST_CLASS = "ROBUST_BUT_NOT_SHORTLISTED"
AMBIGUITY_CLASS = "AMBIGUITY_SENSITIVE"
WEAK_CLASS = "WEAK"
VALID_CLASSES = (CORE_CLASS, HYPOTHESIS_CLASS, ROBUST_CLASS, AMBIGUITY_CLASS, WEAK_CLASS)
STOP_MODES = tuple(item[0] for item in STOP_DEFINITIONS)
TARGETS = tuple(float(value) for value in TARGET_POINTS_VALUES)


def load_frozen_evidence(
    gate6_summary_path: str | Path,
    gate6b1_conditional_path: str | Path,
    gate6b2_summary_path: str | Path,
    baseline_summary_path: str | Path,
    *,
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load only DEVELOPMENT summaries from already-completed gates."""
    gate6 = pd.read_csv(gate6_summary_path)
    conditional = pd.read_csv(gate6b1_conditional_path)
    gate6b2 = pd.read_csv(gate6b2_summary_path)
    baseline = pd.read_csv(baseline_summary_path)

    if len(gate6) != EXPECTED_CONFIGURATIONS or gate6["config_id"].duplicated().any():
        raise ValueError("Gate 6C requires exactly 75 unique Gate 6B configurations")
    expected_grid = {
        (duration, stop, target)
        for duration in OR_DURATIONS
        for stop in STOP_MODES
        for target in TARGETS
    }
    actual_grid = set(
        gate6[["or_minutes", "stop_mode", "target_points"]]
        .assign(or_minutes=lambda frame: frame["or_minutes"].astype(int))
        .itertuples(index=False, name=None)
    )
    if actual_grid != expected_grid:
        raise ValueError("Gate 6C candidate universe differs from the frozen 75-cell grid")
    if not gate6["breakout_type"].eq("PRINT").all():
        raise ValueError("Gate 6C candidate universe is not PRINT-only")
    if not pd.to_datetime(gate6["development_start"]).eq(development_start).all():
        raise ValueError("Gate 6C found an unexpected DEVELOPMENT start")
    if not pd.to_datetime(gate6["development_end"]).eq(development_end).all():
        raise ValueError("Gate 6C found an unexpected DEVELOPMENT end")
    if pd.to_datetime(gate6["development_end"]).max() > pd.Timestamp("2025-06-30"):
        raise ValueError("Reserved-period evidence entered Gate 6C")
    if conditional["config_id"].nunique() != EXPECTED_CONFIGURATIONS or len(conditional) != 375:
        raise ValueError("Gate 6B.1 conditional evidence must contain 375 cells")
    excluded = gate6b2.loc[gate6b2["scenario"].eq("EXCLUDED")]
    if len(excluded) != EXPECTED_CONFIGURATIONS or gate6b2["config_id"].nunique() != EXPECTED_CONFIGURATIONS:
        raise ValueError("Gate 6B.2 evidence does not cover the frozen universe")
    if not gate6b2.groupby("config_id")["scenario"].nunique().eq(3).all():
        raise ValueError("Gate 6B.2 evidence lacks three scenarios per configuration")
    if "research_scope" not in baseline.columns or not baseline["research_scope"].eq(
        "DEVELOPMENT_ONLY"
    ).all():
        raise ValueError("Baseline evidence is not DEVELOPMENT-only")
    if not pd.to_datetime(baseline["development_start"]).eq(development_start).all():
        raise ValueError("Baseline evidence has an unexpected DEVELOPMENT start")
    if not pd.to_datetime(baseline["development_end"]).eq(development_end).all():
        raise ValueError("Baseline evidence has an unexpected DEVELOPMENT end")
    return gate6, conditional, gate6b2, baseline


def build_candidate_evidence(
    gate6: pd.DataFrame,
    conditional: pd.DataFrame,
    gate6b2: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Build the transparent 75-row reduction table without a composite score."""
    thresholds = config["transparent_thresholds"]
    excluded = gate6b2.loc[gate6b2["scenario"].eq("EXCLUDED")].copy()
    robustness_columns = [
        "config_id", "entry_first_avg_r", "adverse_move_first_avg_r",
        "chronology_range_avg_r", "entry_first_pf", "adverse_move_first_pf",
        "entry_first_positive", "all_scenarios_positive", "all_scenarios_pf_above_1",
    ]
    evidence = gate6.merge(
        excluded[robustness_columns], on="config_id", validate="one_to_one"
    )
    width = calculate_width_descriptors(conditional, thresholds)
    evidence = evidence.merge(width, on="config_id", validate="one_to_one")

    evidence["high_ambiguity"] = evidence["entry_stop_ambiguity_rate"].ge(
        float(thresholds["high_ambiguity_rate"])
    )
    evidence["high_chronology_sensitivity"] = evidence["chronology_range_avg_r"].ge(
        float(thresholds["high_chronology_sensitivity_avg_r"])
    )
    evidence["low_sample_warning"] = (
        evidence["executed_trades"].lt(int(thresholds["low_overall_executed_trades"]))
        | evidence["width_low_sample_warning"]
    )
    evidence["boundary_target"] = evidence["target_points"].eq(max(TARGETS))
    evidence["boundary_target_caution"] = np.where(
        evidence["boundary_target"],
        "BOUNDARY_TARGET: upper tested edge; no interior optimum demonstrated", "",
    )
    evidence = add_neighbor_support(evidence, config)

    core = {item["configuration_id"]: item for item in config["proposed_core_candidates"]}
    hypotheses = {
        item["configuration_id"]: item for item in config["proposed_research_hypotheses"]
    }
    _validate_proposed_sets(evidence, core, hypotheses)
    evidence["stable_candidate_id"] = evidence["config_id"].map(
        {key: value["candidate_id"] for key, value in {**core, **hypotheses}.items()}
    ).fillna("")
    evidence["selection_role"] = evidence["config_id"].map(
        {key: value["selection_role"] for key, value in {**core, **hypotheses}.items()}
    ).fillna("")
    evidence["validation_question"] = evidence["config_id"].map(
        {key: value["validation_question"] for key, value in {**core, **hypotheses}.items()}
    ).fillna("")
    evidence["candidate_class"] = [
        _candidate_class(row.config_id, row, core, hypotheses)
        for row in evidence.itertuples(index=False)
    ]
    evidence["stop_family_tier"] = evidence["stop_mode"].map({
        "OR_MIDPOINT": "PRIMARY", "FIXED_40": "PRIMARY", "FIXED_50": "PRIMARY",
        "FIXED_30": "SECONDARY", "OR_25_RETRACEMENT": "PARKED_HYPOTHESIS",
    })
    output_columns = [
        "config_id", "stable_candidate_id", "or_minutes", "breakout_type", "stop_mode",
        "stop_family_tier", "target_points", "executed_trades", "average_r",
        "profit_factor_r", "total_r", "max_drawdown_r", "max_consecutive_losses",
        "positive_month_percentage", "rolling_100_positive_window_percentage",
        "ambiguity_rate", "entry_stop_ambiguity_rate", "entry_first_avg_r",
        "adverse_move_first_avg_r", "entry_first_pf", "adverse_move_first_pf",
        "entry_first_positive", "all_scenarios_positive", "all_scenarios_pf_above_1",
        "chronology_range_avg_r", "session_end_percentage", "high_ambiguity",
        "high_chronology_sensitivity", "low_sample_warning", "boundary_target",
        "boundary_target_caution", "neighbor_support", "supporting_target_neighbors",
        "supporting_stop_neighbors", "or_width_dependency", "width_dependence_warning",
        "width_extreme_weakness", "width_avg_r_range", "width_positive_quintiles",
        "width_best_quintile", "width_worst_quintile", "width_top_two_positive_r_share",
        "width_low_sample_warning", "candidate_class", "selection_role",
        "validation_question",
    ]
    output = evidence.loc[:, output_columns].sort_values(
        ["or_minutes", "stop_mode", "target_points"], kind="stable"
    ).reset_index(drop=True)
    if len(output) != EXPECTED_CONFIGURATIONS or output["config_id"].duplicated().any():
        raise ValueError("Gate 6C evidence table is not exactly 75 unique rows")
    return output


def calculate_width_descriptors(
    conditional: pd.DataFrame, thresholds: dict[str, Any]
) -> pd.DataFrame:
    """Summarize Gate 6B.1 quintiles without constructing a width filter."""
    rows = []
    for config_id, group in conditional.groupby("config_id", sort=True):
        ordered = group.sort_values("or_width_quintile")
        if list(ordered["or_width_quintile"].astype(int)) != [1, 2, 3, 4, 5]:
            raise ValueError(f"{config_id} lacks five OR-width quintiles")
        values = ordered["average_r"].astype(float).to_numpy()
        total_r = ordered["total_r"].astype(float).to_numpy()
        width_range = float(values.max() - values.min())
        positive_count = int((values > 0).sum())
        extremes = float(np.mean([values[0], values[4]]))
        middle = float(np.mean(values[1:4]))
        positive_total = float(total_r[total_r > 0].sum())
        top_two_share = (
            float(np.sort(total_r[total_r > 0])[-2:].sum()) / positive_total
            if positive_total > 0 else np.nan
        )
        if width_range <= float(thresholds["width_stable_avg_r_range"]) and positive_count >= 4:
            dependency = "RELATIVELY_STABLE"
        elif extremes > middle + 0.10:
            dependency = "U_SHAPED"
        elif middle > extremes + 0.10 and int(np.argmax(values) + 1) in {2, 3, 4}:
            dependency = "HUMP_SHAPED"
        else:
            dependency = "MIXED_NONLINEAR"
        concentrated = bool(
            pd.notna(top_two_share)
            and top_two_share >= float(thresholds["width_top_two_positive_r_share_warning"])
        )
        if concentrated:
            dependency += "_CONCENTRATED"
        low_sample = ordered["sample_warning"].astype(str).eq("LOW_SAMPLE").any()
        extreme_weakness = bool(values[0] <= 0 or values[4] <= 0)
        warning = bool(
            width_range >= float(thresholds["width_warning_avg_r_range"])
            or positive_count <= 3 or concentrated or low_sample
        )
        rows.append({
            "config_id": config_id, "or_width_dependency": dependency,
            "width_dependence_warning": warning, "width_extreme_weakness": extreme_weakness,
            "width_avg_r_range": width_range, "width_positive_quintiles": positive_count,
            "width_best_quintile": int(np.argmax(values) + 1),
            "width_worst_quintile": int(np.argmin(values) + 1),
            "width_top_two_positive_r_share": top_two_share,
            "width_low_sample_warning": bool(low_sample),
        })
    return pd.DataFrame(rows)


def add_neighbor_support(evidence: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Apply the documented adjacent-target and economic stop-peer rule."""
    output = evidence.copy()
    tolerance = float(config["transparent_thresholds"]["neighbor_avg_r_similarity_tolerance"])
    stop_peers = config["neighbor_rules"]["stop_peers"]
    lookup = {
        (int(row.or_minutes), row.stop_mode, float(row.target_points)): row
        for row in output.itertuples(index=False)
    }
    target_list = list(TARGETS)
    descriptors, target_names, stop_names = [], [], []
    for row in output.itertuples(index=False):
        target_index = target_list.index(float(row.target_points))
        neighboring_targets = []
        if target_index > 0:
            neighboring_targets.append(target_list[target_index - 1])
        if target_index < len(target_list) - 1:
            neighboring_targets.append(target_list[target_index + 1])
        target_support = [
            lookup[(int(row.or_minutes), row.stop_mode, value)]
            for value in neighboring_targets
            if _supports(lookup[(int(row.or_minutes), row.stop_mode, value)], row, tolerance)
        ]
        stop_support = [
            lookup[(int(row.or_minutes), peer, float(row.target_points))]
            for peer in stop_peers[row.stop_mode]
            if _supports(lookup[(int(row.or_minutes), peer, float(row.target_points))], row, tolerance)
        ]
        robust = bool(row.all_scenarios_positive and row.all_scenarios_pf_above_1)
        if robust and target_support and stop_support:
            descriptor = "STRONG"
        elif robust and (target_support or stop_support):
            descriptor = "MODERATE"
        else:
            descriptor = "WEAK"
        descriptors.append(descriptor)
        target_names.append("|".join(item.config_id for item in target_support))
        stop_names.append("|".join(item.config_id for item in stop_support))
    output["neighbor_support"] = descriptors
    output["supporting_target_neighbors"] = target_names
    output["supporting_stop_neighbors"] = stop_names
    return output


def build_shortlist(evidence: pd.DataFrame) -> pd.DataFrame:
    shortlist = evidence.loc[evidence["candidate_class"].isin([CORE_CLASS, HYPOTHESIS_CLASS])].copy()
    class_order = pd.Categorical(
        shortlist["candidate_class"], categories=[CORE_CLASS, HYPOTHESIS_CLASS], ordered=True
    )
    shortlist = shortlist.assign(_class_order=class_order).sort_values(
        ["_class_order", "stable_candidate_id"], kind="stable"
    ).drop(columns="_class_order")
    core_count = int(shortlist["candidate_class"].eq(CORE_CLASS).sum())
    hypothesis_count = int(shortlist["candidate_class"].eq(HYPOTHESIS_CLASS).sum())
    if not 3 <= core_count <= 5:
        raise ValueError("Gate 6C core shortlist must contain 3 to 5 candidates")
    if not 0 <= hypothesis_count <= 2:
        raise ValueError("Gate 6C hypothesis list must contain at most 2 candidates")
    if shortlist["stable_candidate_id"].eq("").any() or shortlist["stable_candidate_id"].duplicated().any():
        raise ValueError("Gate 6C shortlisted candidates need unique stable IDs")
    return shortlist.reset_index(drop=True)


def build_candidate_specification(
    shortlist: pd.DataFrame, config: dict[str, Any], metadata: dict[str, Any]
) -> dict[str, Any]:
    candidates = []
    for row in shortlist.itertuples(index=False):
        candidates.append({
            "candidate_id": row.stable_candidate_id,
            "candidate_class": row.candidate_class,
            "configuration_id": row.config_id,
            "parameters": {
                "or_minutes": int(row.or_minutes), "breakout_type": "PRINT",
                "stop_mode": row.stop_mode, "target_points": float(row.target_points),
            },
            "selection_role": row.selection_role,
            "validation_question": row.validation_question,
            "development_evidence": {
                "executed_trades": int(row.executed_trades), "average_r": float(row.average_r),
                "profit_factor_r": float(row.profit_factor_r),
                "entry_stop_ambiguity_rate": float(row.entry_stop_ambiguity_rate),
                "entry_first_average_r": float(row.entry_first_avg_r),
                "adverse_move_first_average_r": float(row.adverse_move_first_avg_r),
                "chronology_range_average_r": float(row.chronology_range_avg_r),
                "neighbor_support": row.neighbor_support,
                "or_width_dependency": row.or_width_dependency,
                "boundary_target": bool(row.boundary_target),
            },
        })
    return {
        "project_id": "mnq_orb_v0_1", "strategy_version": "ORB_V0.1",
        "freeze_status": config["freeze_status"],
        "human_approval_required": True,
        "validation_access_authorized": False,
        "validation_acceptance_criteria_status": "NOT_YET_APPROVED",
        "development_partition": metadata["development_partition"],
        "dataset_id": metadata["dataset_id"],
        "source_gate_ids": metadata["source_gate_ids"],
        "source_git_commit": metadata["source_git_commit"],
        "inherited_strategy_semantics": metadata["inherited_strategy_semantics"],
        "candidates": candidates,
    }


def build_metadata(
    config: dict[str, Any], source_hashes: dict[str, str], *,
    git_commit: str, working_tree_status: list[str], dataset_id: str,
    development_start: str, development_end: str,
) -> dict[str, Any]:
    return {
        "experiment_id": config["experiment_id"], "project_id": config["project_id"],
        "freeze_status": config["freeze_status"], "human_approval_required": True,
        "validation_accessed": False, "oos_burned_accessed": False,
        "performance_inputs": ["GATE_5B_DEVELOPMENT", "GATE_6B", "GATE_6B.1", "GATE_6B.2"],
        "source_gate_ids": ["GATE_5B", "GATE_6B", "GATE_6B.1", "GATE_6B.2"],
        "development_partition": {"start": development_start, "end": development_end},
        "dataset_id": dataset_id, "source_git_commit": git_commit,
        "working_tree_clean_at_generation": not bool(working_tree_status),
        "working_tree_status_at_generation": working_tree_status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_artifact_sha256": source_hashes,
        "thresholds": config["transparent_thresholds"],
        "flag_definitions": config["flag_definitions"],
        "neighbor_rules": config["neighbor_rules"],
        "candidate_universe_count": EXPECTED_CONFIGURATIONS,
        "core_shortlist_count": len(config["proposed_core_candidates"]),
        "research_hypothesis_count": len(config["proposed_research_hypotheses"]),
        "new_parameters_created": False, "strategy_execution_rerun": False,
        "or_width_filter_created": False, "final_freeze_activated": False,
        "inherited_strategy_semantics": {
            "timestamp_semantics": "NT8 one-minute timestamp_et is bar_end_time",
            "breakout_type": "PRINT", "entry": "OR boundary on signal bar",
            "signal_cutoff": "11:30 ET inclusive", "maximum_trades_per_session": 1,
            "ambiguity": "validated PRINT ambiguity plus Gate 6B.2 chronology evidence",
            "session_exit": "validated SESSION_END and shortened-session behavior",
            "disabled_features": ["break_even", "trailing", "FVG", "EMA", "VWAP", "partial_exits"],
        },
    }


def write_outputs(
    evidence: pd.DataFrame, shortlist: pd.DataFrame, specification: dict[str, Any],
    metadata: dict[str, Any], output_dir: str | Path,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "evidence": output_dir / "orb_gate6c_DEV_candidate_evidence.csv",
        "shortlist": output_dir / "orb_gate6c_DEV_candidate_shortlist.csv",
        "specification": output_dir / "mnq_orb_v0_1_validation_candidates.json",
        "report": output_dir / "orb_gate6c_DEV_shortlist_report.md",
        "metadata": output_dir / "orb_gate6c_DEV_freeze_metadata.json",
        "comparison": output_dir / "orb_gate6c_DEV_candidate_comparison.html",
    }
    evidence.to_csv(paths["evidence"], index=False)
    shortlist.to_csv(paths["shortlist"], index=False)
    paths["specification"].write_text(
        json.dumps(specification, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    paths["report"].write_text(shortlist_report(shortlist, metadata), encoding="utf-8")
    write_comparison_chart(shortlist, paths["comparison"])
    metadata = {**metadata, "outputs": {key: str(value) for key, value in paths.items()}}
    paths["metadata"].write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return paths


def shortlist_report(shortlist: pd.DataFrame, metadata: dict[str, Any]) -> str:
    core = shortlist.loc[shortlist["candidate_class"].eq(CORE_CLASS)]
    hypotheses = shortlist.loc[shortlist["candidate_class"].eq(HYPOTHESIS_CLASS)]
    lines = [
        "# Gate 6C — DEVELOPMENT candidate shortlist",
        "", "**Freeze status: PENDING_HUMAN_APPROVAL**", "",
        "This report proposes a small, diverse candidate set from the frozen 75-cell Gate 6B universe.",
        "It does not authorize Validation access and does not identify a ‘best’ configuration.", "",
        f"DEVELOPMENT evidence: {metadata['development_partition']['start']} through {metadata['development_partition']['end']}.",
        "", "## Transparent reduction rules", "",
        "Hard-flag definitions and thresholds are recorded in the experiment config and freeze metadata.",
        "Neighbor support requires chronology robustness, PF above 1 in all scenarios, and an adjacent",
        "target or economically meaningful stop peer within 0.15R of ENTRY_FIRST average R. STRONG",
        "requires support on both dimensions; MODERATE requires either; otherwise support is WEAK.",
        "No composite optimization score is used.", "", "## Core shortlist", "",
    ]
    for row in core.itertuples(index=False):
        lines.extend(_candidate_report_lines(row, research=False))
    lines.extend(["## Research hypotheses", ""])
    for row in hypotheses.itertuples(index=False):
        lines.extend(_candidate_report_lines(row, research=True))
    lines.extend([
        "## Why other robust cells were not shortlisted", "",
        "Many cells remain chronology-robust. They are retained in the 75-row evidence table but omitted",
        "to avoid carrying near-duplicate target/stop hypotheses into Validation. The core set intentionally",
        "represents 15m/20m/30m, midpoint/fixed-40/fixed-50 stops, and an interior 75-point target with",
        "supporting target and stop-family neighbors. Fixed-30 remains documented but adds materially more",
        "entry-bar ambiguity. Most 25%-retracement cells fail conservative chronology; its two surviving",
        "20m exceptions remain separate research hypotheses.", "",
        "## Approval boundary", "",
        "Human approval must confirm the shortlist and predeclare Validation acceptance criteria before",
        "the package can become FINAL. No Validation or OOS_BURNED data was loaded for this report.", "",
    ])
    return "\n".join(lines)


def _candidate_report_lines(row, *, research: bool) -> list[str]:
    role = "Higher-risk research candidate" if research else "Representative candidate"
    caveats = []
    if row.high_ambiguity:
        caveats.append("high entry-bar ambiguity")
    if row.high_chronology_sensitivity:
        caveats.append("high chronology sensitivity")
    if row.width_dependence_warning:
        caveats.append(f"OR-width dependence: {row.or_width_dependency}")
    if row.boundary_target:
        caveats.append("BOUNDARY_TARGET; no interior optimum demonstrated")
    if not caveats:
        caveats.append(f"OR-width behavior: {row.or_width_dependency}")
    return [
        f"### {row.stable_candidate_id} — {row.config_id}", "",
        f"- Role: {role}; {row.selection_role}.",
        f"- DEVELOPMENT: {int(row.executed_trades)} trades, Avg R {row.average_r:.3f}, "
        f"PF {row.profit_factor_r:.2f}, max DD {row.max_drawdown_r:.2f}R.",
        f"- Observability: entry-stop ambiguity {row.entry_stop_ambiguity_rate * 100:.1f}%; "
        f"ENTRY_FIRST Avg R {row.entry_first_avg_r:.3f}; chronology range {row.chronology_range_avg_r:.3f}R.",
        f"- Stability: neighbor support {row.neighbor_support}; all-scenario PF > 1 = "
        f"{bool(row.all_scenarios_pf_above_1)}.",
        f"- Cautions: {'; '.join(caveats)}.",
        f"- Validation must confirm: {row.validation_question}", "",
    ]


def write_comparison_chart(shortlist: pd.DataFrame, path: str | Path) -> None:
    labels = shortlist["stable_candidate_id"]
    figure = make_subplots(
        rows=1, cols=2, subplot_titles=("Average R under chronology conventions", "Observability / sensitivity")
    )
    for metric, name, color in (
        ("average_r", "EXCLUDED", "#455a64"),
        ("entry_first_avg_r", "ENTRY_FIRST", "#c62828"),
        ("adverse_move_first_avg_r", "ADVERSE_MOVE_FIRST", "#2e7d32"),
    ):
        figure.add_trace(go.Bar(
            x=labels, y=shortlist[metric], name=name, marker_color=color,
            hovertemplate="%{x}<br>" + name + " Avg R: %{y:.4f}<extra></extra>",
        ), row=1, col=1)
    figure.add_trace(go.Bar(
        x=labels, y=shortlist["entry_stop_ambiguity_rate"] * 100,
        name="Entry-stop ambiguity %", marker_color="#ff9800",
        hovertemplate="%{x}<br>Ambiguity: %{y:.2f}%<extra></extra>",
    ), row=1, col=2)
    figure.add_trace(go.Bar(
        x=labels, y=shortlist["chronology_range_avg_r"] * 100,
        name="Chronology range (R ×100)", marker_color="#7e57c2",
        hovertemplate="%{x}<br>Chronology range (R ×100): %{y:.2f}<extra></extra>",
    ), row=1, col=2)
    figure.add_hline(y=0, line_dash="dot", line_color="black", row=1, col=1)
    figure.update_layout(
        title="Gate 6C — proposed candidates — DEVELOPMENT ONLY — PENDING HUMAN APPROVAL",
        template="plotly_white", barmode="group", height=680, width=1320,
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def sha256_files(paths: list[str | Path]) -> dict[str, str]:
    hashes = {}
    for path in paths:
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        hashes[str(Path(path))] = digest.hexdigest()
    return hashes


def _supports(neighbor, current, tolerance: float) -> bool:
    return bool(
        neighbor.all_scenarios_positive and neighbor.all_scenarios_pf_above_1
        and abs(float(neighbor.entry_first_avg_r) - float(current.entry_first_avg_r)) <= tolerance
    )


def _candidate_class(config_id: str, row, core: dict, hypotheses: dict) -> str:
    if config_id in core:
        return CORE_CLASS
    if config_id in hypotheses:
        return HYPOTHESIS_CLASS
    if bool(row.all_scenarios_positive and row.all_scenarios_pf_above_1):
        return ROBUST_CLASS
    if bool(row.high_ambiguity or row.high_chronology_sensitivity or not row.all_scenarios_positive):
        return AMBIGUITY_CLASS
    return WEAK_CLASS


def _validate_proposed_sets(evidence: pd.DataFrame, core: dict, hypotheses: dict) -> None:
    universe = set(evidence["config_id"])
    selected = set(core) | set(hypotheses)
    if not selected.issubset(universe):
        raise ValueError("A proposed Gate 6C candidate is not in Gate 6B")
    if set(core) & set(hypotheses):
        raise ValueError("Core and research-hypothesis candidates overlap")
    if not 3 <= len(core) <= 5 or len(hypotheses) > 2:
        raise ValueError("Gate 6C proposed shortlist sizes violate the research contract")
    stable_ids = [item["candidate_id"] for item in [*core.values(), *hypotheses.values()]]
    if len(stable_ids) != len(set(stable_ids)):
        raise ValueError("Gate 6C stable candidate IDs are not unique")
    selected_rows = evidence.loc[evidence["config_id"].isin(selected)]
    if not selected_rows["all_scenarios_positive"].all() or not selected_rows[
        "all_scenarios_pf_above_1"
    ].all():
        raise ValueError("A proposed Gate 6C candidate is not chronology-robust")
