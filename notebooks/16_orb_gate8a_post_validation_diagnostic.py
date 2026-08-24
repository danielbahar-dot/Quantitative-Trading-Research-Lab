"""Run Gate 8A: retrospective MNQ ORB V0.1 post-Validation diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import subprocess
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.orb_gate7_validation import build_partition_or_levels  # noqa: E402
from src.experiments.orb_gate8a_post_validation import (  # noqa: E402
    DEV_END,
    DEV_START,
    RESEARCH_LABEL,
    VAL_END,
    VAL_START,
    assert_partition,
    build_surface_comparison,
    candidate_neighborhoods,
    hypothesis_classifications,
    observability_comparison,
    or_width_diagnostics,
    parameter_migration,
    persistence_statistics,
    price_normalization_diagnostic,
    run_validation_surface,
    temporal_diagnostics,
    write_outputs,
)
from src.research_harness import ExperimentLedger  # noqa: E402
from src.visualization.research_viewer import load_price_data  # noqa: E402


PROJECT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1"
SWEEP_DIR = PROJECT_DIR / "sweeps"
FREEZE_DIR = PROJECT_DIR / "freeze" / "dev_candidate_freeze"
VALIDATION_DIR = PROJECT_DIR / "validation"
OUTPUT_DIR = PROJECT_DIR / "postmortem" / "gate8a"
CONFIG = PROJECT_ROOT / "config" / "experiments" / "orb_gate8a_post_validation_diagnostic.json"
PARTITIONS = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
PARTITION_REPORT = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_partition_report.json"
DEV_PRICES = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_DEVELOPMENT.csv"
VAL_PRICES = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_VALIDATION.csv"
DEV_SUMMARY = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_summary.csv"
DEV_TRADES = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_trades.csv"
DEV_DIAGNOSTICS = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_or_width_diagnostics.csv"
DEV_CHRONOLOGY = SWEEP_DIR / "orb_gate6b2_DEV_ambiguity_robustness_summary.csv"
DEV_EVIDENCE = FREEZE_DIR / "orb_gate6c_DEV_candidate_evidence.csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(PROJECT_ROOT)): _sha256(path) for path in paths}


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(PROJECT_ROOT), *args], text=True).strip()


def _protected_artifacts() -> list[Path]:
    paths = []
    for pattern in ("orb_gate6b_DEV_*", "orb_gate6b1_DEV_*", "orb_gate6b2_DEV_*"):
        paths.extend(SWEEP_DIR.glob(pattern))
    paths.extend(FREEZE_DIR.glob("*"))
    paths.extend(VALIDATION_DIR.glob("gate7_validation_protocol.*"))
    paths.extend(VALIDATION_DIR.glob("orb_v01_gate7_*"))
    return sorted({path.resolve() for path in paths if path.is_file()})


def _report(
    comparison: pd.DataFrame,
    migration: pd.DataFrame,
    neighborhoods: pd.DataFrame,
    temporal_findings: pd.DataFrame,
    width: pd.DataFrame,
    price: pd.DataFrame,
    observability: pd.DataFrame,
    classifications: pd.DataFrame,
    metadata: dict,
) -> str:
    persistence = metadata["surface_persistence"]
    sign_text = ", ".join(f"{key}={value}" for key, value in sorted(persistence["sign_counts"].items()))
    candidate_lines = []
    for candidate_id, group in neighborhoods.groupby("candidate_id", sort=True):
        row = group.loc[group["member_type"].eq("CANDIDATE")].iloc[0]
        candidate_lines.append(
            f"- {candidate_id}: {row['candidate_failure_classification']}; "
            f"candidate VAL Avg R {row['val_average_r']:.4f}, neighborhood mean "
            f"{row['neighborhood_val_mean_r']:.4f}, VAL-positive neighbors "
            f"{row['neighborhood_val_positive_share']:.1%}."
        )
    temporal_lines = [
        f"- {row.entity}: {row.deterioration_pattern}; first-half {row.validation_first_half_total_r:.3f}R, second-half {row.validation_second_half_total_r:.3f}R."
        for row in temporal_findings.itertuples(index=False)
    ]
    price_lines = []
    for row in price.loc[price["record_type"].eq("SUMMARY")].itertuples(index=False):
        price_lines.append(
            f"- {int(row.or_minutes)}m: median OR-mid {row.dev_median_market_level:.2f} -> "
            f"{row.val_median_market_level:.2f} ({row.relative_market_level_change:+.1%}); "
            f"75 points changed from {row.dev_75pt_pct_price:.3%} to {row.val_75pt_pct_price:.3%} of price."
        )
    class_lines = [
        f"- {row.hypothesis}: **{row.classification}** — {row.evidence}"
        for row in classifications.itertuples(index=False)
    ]
    observability_lines = [
        f"- {row.stop_mode}: entry/stop ambiguity {row.dev_entry_stop_ambiguity_rate:.2%} -> "
        f"{row.val_entry_stop_ambiguity_rate:.2%}; total exclusions "
        f"{row.dev_total_exclusion_rate:.2%} -> {row.val_total_exclusion_rate:.2%}."
        for row in observability.itertuples(index=False)
    ]
    target_shifts = migration.loc[migration["comparison_axis"].eq("TARGET_REGION"), "migration"].value_counts().to_dict()
    stop_shifts = migration.loc[migration["comparison_axis"].eq("STOP_FAMILY"), "migration"].value_counts().to_dict()
    width_distribution = width.loc[width["analysis_kind"].eq("WIDTH_DISTRIBUTION")]
    width_lines = []
    for duration in (15, 20, 30):
        dev = width_distribution.loc[(width_distribution["partition"] == "DEVELOPMENT") & (width_distribution["or_minutes"] == duration)].iloc[0]
        val = width_distribution.loc[(width_distribution["partition"] == "VALIDATION") & (width_distribution["or_minutes"] == duration)].iloc[0]
        width_lines.append(
            f"- {duration}m: median width {dev.median_or_width:.2f} -> {val.median_or_width:.2f} points; "
            f"p10–p90 {dev.p10_or_width:.2f}–{dev.p90_or_width:.2f} -> {val.p10_or_width:.2f}–{val.p90_or_width:.2f}."
        )
    ranges = metadata["validation_metric_ranges"]
    return "\n".join([
        "# Gate 8A — MNQ ORB V0.1 Post-Validation Diagnostic",
        "",
        f"> {RESEARCH_LABEL}",
        "",
        "This is a retrospective failure diagnostic. It does not select a strategy, create a V0.2 candidate, or provide new confirmatory evidence.",
        "",
        "## Scope and safeguards",
        "",
        f"- DEVELOPMENT: {metadata['development_start']} through {metadata['development_end']}",
        f"- VALIDATION: {metadata['validation_start']} through {metadata['validation_end']}",
        "- OOS_BURNED: not opened and not used.",
        "- Exact frozen Gate 6B grid: 75 configurations, no new values.",
        "- Historical Gate 6B/6B.1/6B.2/6C/7 hashes were unchanged.",
        "",
        "## Surface persistence",
        "",
        f"- Avg-R Spearman: {persistence['spearman_average_r']:.4f}",
        f"- PF Spearman: {persistence['spearman_profit_factor']:.4f}",
        f"- Median Avg-R delta: {persistence['median_average_r_delta']:.4f}R",
        f"- Sign cells: {sign_text}",
        f"- Strong DEVELOPMENT-neighborhood cells still positive in VALIDATION: {persistence['strong_dev_neighborhood_val_positive']}/{persistence['strong_dev_neighborhood_cells']}",
        f"- VALIDATION Avg R range: {ranges['average_r']['minimum']:.4f} to {ranges['average_r']['maximum']:.4f}",
        f"- VALIDATION PF range: {ranges['profit_factor_r']['minimum']:.4f} to {ranges['profit_factor_r']['maximum']:.4f}",
        "",
        "## Parameter migration",
        "",
        f"- Target-region descriptors: {target_shifts}",
        f"- Stop-family descriptors: {stop_shifts}",
        "- These are retrospective descriptive peaks, not candidate recommendations.",
        "",
        "## Frozen-candidate neighborhoods",
        "",
        *candidate_lines,
        "",
        "## Time decomposition",
        "",
        *temporal_lines,
        "",
        "Rolling 30/50 series are calculated separately inside each partition. No window crosses the boundary.",
        "",
        "## OR-width state",
        "",
        *width_lines,
        "",
        "Within-period quintiles changed sign in 58.9% of matched surface cells. The relationship was nonlinear: 15m remained positive across relative-width quintiles, while 20m weakness concentrated in quintiles 1–3 and 30m was negative in quintiles 2–5. This is descriptive and does not define an OR-width filter.",
        "",
        "## Price-level drift",
        "",
        *price_lines,
        "",
        "These percentage equivalents are descriptive only; the strategy was not rerun with percentage distances.",
        "",
        "## Observability",
        "",
        *observability_lines,
        "",
        "Ambiguity and total-exclusion rates fell in every stop family, so reduced OHLC observability cannot explain the broad expectancy loss.",
        "",
        "## Post-mortem classifications",
        "",
        *class_lines,
        "",
        "## Parked future hypotheses",
        "",
        "OR expansion may be more meaningfully normalized against a separately validated pre-market expansion feature than generic ATR. Gate 8A does not define or calculate that feature. Percentage-normalized distances, OR-width state, and causal OR-width percentiles also remain parked for a future V0.2 definition gate.",
        "",
        "## Methodological conclusion",
        "",
        "VALIDATION has been observed and is burned for future V0.2 hypothesis generation. It may remain available for retrospective diagnosis only. OOS_BURNED remains unopened in the formal lifecycle and requires explicit human approval.",
        "",
    ])


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if config["confirmatory"] or config["oos_accessed"]:
        raise ValueError("Gate 8A must remain non-confirmatory and OOS-free")
    if int(config["grid"]["expected_configurations"]) != 75:
        raise ValueError("Gate 8A config no longer declares the frozen 75-cell surface")

    partitions = json.loads(PARTITIONS.read_text(encoding="utf-8"))
    named = {item["name"]: item for item in partitions["partitions"]}
    if (pd.Timestamp(named["DEVELOPMENT"]["start"]), pd.Timestamp(named["DEVELOPMENT"]["end"])) != (DEV_START, DEV_END):
        raise ValueError("DEVELOPMENT boundaries changed")
    if (pd.Timestamp(named["VALIDATION"]["start"]), pd.Timestamp(named["VALIDATION"]["end"])) != (VAL_START, VAL_END):
        raise ValueError("VALIDATION boundaries changed")

    protected = _protected_artifacts()
    before_hashes = _hashes(protected)
    report = json.loads(PARTITION_REPORT.read_text(encoding="utf-8"))
    if _sha256(DEV_PRICES) != report["partitions"]["DEVELOPMENT"]["sha256"]:
        raise ValueError("DEVELOPMENT partition hash mismatch")
    if _sha256(VAL_PRICES) != report["partitions"]["VALIDATION"]["sha256"]:
        raise ValueError("VALIDATION partition hash mismatch")

    # Only the two declared files are opened. No OOS path is constructed or read.
    development_prices = load_price_data(DEV_PRICES)
    validation_prices = load_price_data(VAL_PRICES)
    assert_partition(development_prices, DEV_START, DEV_END, "DEVELOPMENT")
    assert_partition(validation_prices, VAL_START, VAL_END, "VALIDATION")
    development_or_levels = build_partition_or_levels(development_prices)
    validation_or_levels = build_partition_or_levels(validation_prices)
    validation_run = run_validation_surface(validation_prices, validation_or_levels)

    development_summary = pd.read_csv(DEV_SUMMARY)
    development_trades = pd.read_csv(DEV_TRADES)
    development_diagnostics = pd.read_csv(DEV_DIAGNOSTICS)
    development_chronology = pd.read_csv(DEV_CHRONOLOGY)
    evidence = pd.read_csv(DEV_EVIDENCE)
    assert_partition(development_trades, DEV_START, DEV_END, "DEVELOPMENT trades")
    if len(development_summary) != 75 or development_summary["config_id"].duplicated().any():
        raise ValueError("Historical Gate 6B summary no longer has 75 unique cells")

    comparison = build_surface_comparison(
        development_summary, validation_run.summary,
        development_chronology, validation_run.chronology, evidence,
    )
    persistence = persistence_statistics(comparison)
    migration = parameter_migration(comparison)
    neighborhoods = candidate_neighborhoods(comparison, config)
    temporal, temporal_findings = temporal_diagnostics(
        development_trades, validation_run.trades, config["representative_regions"],
    )
    width, width_edges = or_width_diagnostics(
        development_trades, development_diagnostics,
        validation_run.trades, validation_run.diagnostics,
        initial_edges=config["width_buckets"]["initial_edges"],
        minimum_n=int(config["width_buckets"]["minimum_combined_session_observations"]),
    )
    price = price_normalization_diagnostic(development_or_levels, validation_or_levels)
    observability = observability_comparison(
        development_summary, validation_run.summary,
        development_chronology, validation_run.chronology,
    )
    classifications = hypothesis_classifications(comparison, migration, neighborhoods, width)

    after_hashes = _hashes(protected)
    if before_hashes != after_hashes:
        raise ValueError("A protected Gate 6B/6B.1/6B.2/6C/7 artifact changed")
    if len(comparison) != 75 or comparison["config_id"].duplicated().any():
        raise ValueError("Gate 8A comparison must contain 75 unique configurations")
    if set(validation_run.summary["stop_mode"]) != set(config["grid"]["stop_modes"]):
        raise ValueError("Gate 8A introduced or omitted a stop mode")
    if set(validation_run.summary["target_points"].astype(float)) != set(config["grid"]["target_points"]):
        raise ValueError("Gate 8A introduced or omitted a target")

    run_timestamp = datetime.now(timezone.utc).isoformat()
    metadata = {
        "experiment_id": config["experiment_id"], "project_id": config["project_id"],
        "strategy_version": config["strategy_version"], "experiment_type": config["experiment_type"],
        "research_scope": RESEARCH_LABEL, "confirmatory": False,
        "source_gates": config["source_gates"], "partitions_used": config["partitions_used"],
        "development_start": DEV_START.date().isoformat(), "development_end": DEV_END.date().isoformat(),
        "validation_start": VAL_START.date().isoformat(), "validation_end": VAL_END.date().isoformat(),
        "development_max_session_date_analyzed": pd.to_datetime(development_trades["session_date"]).max().date().isoformat(),
        "validation_max_session_date_analyzed": pd.to_datetime(validation_run.trades["session_date"]).max().date().isoformat(),
        "oos_burned_accessed": False, "oos_path_opened": False,
        "validation_configuration_count": len(validation_run.summary),
        "new_parameters_added": False, "strategy_selected": False, "v0_2_candidate_created": False,
        "or_width_filter_used": False, "percentage_strategy_rerun": False,
        "premarket_feature_implemented": False,
        "surface_persistence": persistence,
        "validation_metric_ranges": {
            column: {"minimum": float(validation_run.summary[column].min()), "maximum": float(validation_run.summary[column].max())}
            for column in ("average_r", "profit_factor_r", "max_drawdown_r", "ambiguity_rate", "win_rate", "session_end_percentage")
        },
        "common_absolute_width_edges": ["-inf" if value == float("-inf") else "inf" if value == float("inf") else value for value in width_edges],
        "classification_rules": config["classification_rules"],
        "hypothesis_classifications": classifications.set_index("hypothesis")["classification"].to_dict(),
        "protected_artifact_sha256_before": before_hashes,
        "protected_artifact_sha256_after": after_hashes,
        "historical_artifacts_unchanged": True,
        "source_git_commit": _git("rev-parse", "HEAD"), "run_timestamp_utc": run_timestamp,
        "ledger_status": "PENDING_REGISTRATION",
    }

    ledger_config = {
        "strategy_name": "MNQ_ORB", "strategy_version": "V0.1",
        "hypothesis": "Post-Validation failure diagnosis; no candidate selection",
        "dataset": "MNQ_1m_actual_contract_v1", "timeframe": "1 minute",
        "session": {"timezone": "America/New_York", "regular": "09:30-16:00"},
        "parameters": {
            "experiment_type": "POST_VALIDATION_DIAGNOSTIC", "source_gates": config["source_gates"],
            "partitions_used": ["DEVELOPMENT", "VALIDATION"], "confirmatory": False,
            "oos_accessed": False, "configuration_count": 75,
        },
        "costs_slippage": {"modeled": False}, "experiment_id": config["experiment_id"],
        "project_id": config["project_id"], "strategy_family": "ORB",
        "asset_class": "futures", "instrument_id": "MNQ",
        "dataset_id": "MNQ_1m_actual_contract_v1",
        "dataset_hash": report["source_sha256"],
        "partition": {"name": "DEVELOPMENT+VALIDATION"},
        "execution_model": {"source": "validated custom Gate 6B engine", "modified": False},
        "status": "COMPLETED_DIAGNOSTIC_PENDING_HUMAN_REVIEW",
        "conclusion": "No strategy selected; Validation is burned for future hypothesis generation.",
        "notes": RESEARCH_LABEL,
    }
    ledger = ExperimentLedger(PROJECT_ROOT)
    existing_run_id = None
    existing_metadata = OUTPUT_DIR / "gate8a_metadata.json"
    if existing_metadata.exists():
        existing_run_id = json.loads(existing_metadata.read_text(encoding="utf-8")).get("ledger_run_id")
    if existing_run_id:
        try:
            ledger.get_run(existing_run_id)
            run_id = existing_run_id
        except (FileNotFoundError, KeyError):
            run_id, _ = ledger.create_run(ledger_config)
    else:
        run_id, _ = ledger.create_run(ledger_config)
    metadata["ledger_status"] = "REGISTERED"
    metadata["ledger_run_id"] = run_id
    paths = write_outputs(
        OUTPUT_DIR, validation_summary=validation_run.summary, comparison=comparison,
        migration=migration, neighborhoods=neighborhoods, temporal=temporal,
        temporal_findings=temporal_findings, width=width, price=price,
        observability=observability, classifications=classifications, metadata=metadata,
    )
    report_path = OUTPUT_DIR / "gate8a_report.md"
    report_path.write_text(
        _report(comparison, migration, neighborhoods, temporal_findings, width, price, observability, classifications, metadata),
        encoding="utf-8",
    )
    paths["report"] = report_path
    ledger.update_run(
        run_id, results_summary={
            "configuration_count": 75, "surface_persistence": persistence,
            "classifications": metadata["hypothesis_classifications"],
            "oos_accessed": False,
        }, artifact_paths={name: path for name, path in paths.items()},
        status="COMPLETED_DIAGNOSTIC_PENDING_HUMAN_REVIEW",
    )

    print(RESEARCH_LABEL)
    print(f"Validation configurations: {len(validation_run.summary)}")
    print(f"OOS_BURNED accessed: {metadata['oos_burned_accessed']}")
    print(json.dumps(persistence, indent=2))
    print(classifications[["hypothesis", "classification"]].to_string(index=False))
    print(f"Ledger run: {run_id}")
    print(f"Output directory: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
