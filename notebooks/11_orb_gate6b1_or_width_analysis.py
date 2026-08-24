"""Run Gate 6B.1 analytics from immutable Gate 6B artifacts."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.orb_gate6b1_width_analysis import (  # noqa: E402
    add_width_quintiles,
    assign_duration_bins,
    calculate_ambiguity_by_width,
    calculate_conditional_performance,
    calculate_correlations,
    calculate_expectancy_bins,
    calculate_quintile_boundaries,
    calculate_ratio_analysis,
    calculate_width_distribution,
    load_gate6b_artifacts,
    sha256_files,
    unique_width_observations,
    write_outputs,
)


SWEEP_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "sweeps"
PREFIX = "orb_gate6b_DEV_fixed_target_stop"
SUMMARY = SWEEP_DIR / f"{PREFIX}_summary.csv"
TRADES = SWEEP_DIR / f"{PREFIX}_trades.csv"
CANDIDATE_AUDIT = SWEEP_DIR / f"{PREFIX}_candidate_audit.csv"
DIAGNOSTICS = SWEEP_DIR / f"{PREFIX}_or_width_diagnostics.csv"
METADATA = SWEEP_DIR / f"{PREFIX}_metadata.json"
EXPERIMENT_CONFIG = PROJECT_ROOT / "config" / "experiments" / "orb_gate6b1_dev_or_width_analysis.json"
GATE6B_FILES = sorted(SWEEP_DIR.glob(f"{PREFIX}*"))


def main() -> int:
    config = json.loads(EXPERIMENT_CONFIG.read_text(encoding="utf-8"))
    if config["constraints"]["rerun_execution"]:
        raise ValueError("Gate 6B.1 must not rerun execution")
    before_hashes = sha256_files(GATE6B_FILES)
    summary, trades, audit, diagnostics, gate6b_metadata = load_gate6b_artifacts(
        SUMMARY, TRADES, CANDIDATE_AUDIT, DIAGNOSTICS, METADATA,
        development_end=__import__("pandas").Timestamp("2025-06-30"),
    )
    widths = unique_width_observations(diagnostics)
    assigned_widths = assign_duration_bins(widths)
    trades = add_width_quintiles(trades, assigned_widths)
    diagnostics = add_width_quintiles(diagnostics, assigned_widths)
    distribution = calculate_width_distribution(widths, diagnostics)
    quintiles = calculate_quintile_boundaries(assigned_widths, diagnostics)
    conditional = calculate_conditional_performance(summary, trades, diagnostics)
    expectancy = calculate_expectancy_bins(conditional, quintiles)
    correlations = calculate_correlations(summary, trades)
    ratio_analysis = calculate_ratio_analysis(summary, trades, diagnostics)
    ambiguity = calculate_ambiguity_by_width(summary, diagnostics)
    after_hashes = sha256_files(GATE6B_FILES)
    if before_hashes != after_hashes:
        raise ValueError("A Gate 6B artifact changed during Gate 6B.1")
    minimum_date = min(trades["session_date"].min(), diagnostics["session_date"].min())
    maximum_date = max(trades["session_date"].max(), diagnostics["session_date"].max())
    metadata = {
        "experiment_id": "orb_gate6b1_dev_or_width_analysis",
        "research_scope": "DEVELOPMENT_ONLY",
        "actual_minimum_session_date": minimum_date.date().isoformat(),
        "actual_maximum_session_date": maximum_date.date().isoformat(),
        "source_experiment": gate6b_metadata["experiment_id"],
        "strategy_execution_rerun": False,
        "strategy_logic_modified": False,
        "gate6b_artifacts_unchanged": True,
        "gate6b_sha256_before": before_hashes,
        "gate6b_sha256_after": after_hashes,
        "or_width_definition": "or_high - or_low",
        "market_state_unit": "unique session_date x or_minutes",
        "configuration_performance_unit": "actual Gate 6B candidate or executed trade row within one config_id",
        "quintile_method": (
            "Independently within each OR duration, sort unique session observations "
            "by OR width then session date; assign stable ordinal ranks to five "
            "approximately equal-count bins. Width ties may span adjacent bins."
        ),
        "expectancy_curve_bins": "same five duration-specific fixed-count quintiles; deciles were avoided because per-config N would generally fall below 30",
        "low_sample_threshold": 30,
        "low_sample_rule": "executed_trades < 30; warning only, rows remain displayed",
        "or_width_filter_used": False,
        "unique_session_duration_observations": len(widths),
        "conditional_cells": len(conditional),
        "unique_width_observations": widths.to_dict("records"),
        "experiment_config": config,
    }
    paths = write_outputs(
        distribution, quintiles, conditional, expectancy, correlations,
        ratio_analysis, ambiguity, metadata, SWEEP_DIR,
    )
    print(f"DEVELOPMENT ONLY: {minimum_date.date()} through {maximum_date.date()}")
    print(f"Unique session-duration width observations: {len(widths)}")
    print(f"Conditional performance cells: {len(conditional)}")
    print("Strategy execution rerun: False")
    print("Gate 6B artifacts unchanged: True")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
