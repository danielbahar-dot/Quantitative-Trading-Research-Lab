"""Run Gate 6B.2 ambiguity robustness from frozen Gate 6B artifacts."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.partitions import load_partition_config  # noqa: E402
from src.experiments.orb_gate6b2_ambiguity_robustness import (  # noqa: E402
    EXPECTED_CONFIGURATIONS,
    EXPECTED_SCENARIO_ROWS,
    OR_DURATIONS,
    SCENARIOS,
    STOP_MODES,
    TARGET_POINTS_VALUES,
    load_gate6b_artifacts,
    run_robustness_mapping,
    sha256_files,
    write_outputs,
)
from src.experiments.orb_v01_development_diagnostics import development_bounds  # noqa: E402
from src.visualization.research_viewer import load_price_data  # noqa: E402


SWEEP_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "sweeps"
EXPERIMENT_CONFIG = PROJECT_ROOT / "config" / "experiments" / "orb_gate6b2_dev_ambiguity_robustness.json"
PARTITION_CONFIG = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
DEVELOPMENT_PRICES = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_DEVELOPMENT.csv"
GATE6B_SUMMARY = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_summary.csv"
GATE6B_TRADES = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_trades.csv"
GATE6B_AUDIT = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_candidate_audit.csv"
GATE6B_DIAGNOSTICS = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_or_width_diagnostics.csv"
GATE6B_METADATA = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_metadata.json"
PROTECTED_FILES = sorted(SWEEP_DIR.glob("orb_gate6b_DEV_*")) + sorted(
    SWEEP_DIR.glob("orb_gate6b1_DEV_*")
)


def _validate_config(config: dict) -> None:
    if config["or_minutes"] != list(OR_DURATIONS):
        raise ValueError("Gate 6B.2 config has unexpected durations")
    if config["stop_modes"] != list(STOP_MODES):
        raise ValueError("Gate 6B.2 config has unexpected stops")
    if config["target_points"] != list(TARGET_POINTS_VALUES):
        raise ValueError("Gate 6B.2 config has unexpected targets")
    if config["scenarios"] != list(SCENARIOS):
        raise ValueError("Gate 6B.2 config has unexpected scenarios")
    if config["expected_configuration_count"] != EXPECTED_CONFIGURATIONS:
        raise ValueError("Gate 6B.2 must require 75 configurations")
    if config["expected_scenario_rows"] != EXPECTED_SCENARIO_ROWS:
        raise ValueError("Gate 6B.2 must require 225 scenario rows")


def main() -> int:
    experiment_config = json.loads(EXPERIMENT_CONFIG.read_text(encoding="utf-8"))
    _validate_config(experiment_config)
    partition_config = load_partition_config(PARTITION_CONFIG)
    start, end = development_bounds(partition_config)
    before_hashes = sha256_files(PROTECTED_FILES)
    gate6 = load_gate6b_artifacts(
        GATE6B_SUMMARY, GATE6B_TRADES, GATE6B_AUDIT, GATE6B_DIAGNOSTICS,
        GATE6B_METADATA, development_start=start, development_end=end,
    )
    price_data = load_price_data(DEVELOPMENT_PRICES)
    metrics, trades, width, metadata = run_robustness_mapping(
        price_data, *gate6[:4], development_start=start, development_end=end
    )
    after_hashes = sha256_files(PROTECTED_FILES)
    if before_hashes != after_hashes:
        raise ValueError("A Gate 6B or Gate 6B.1 artifact changed during Gate 6B.2")
    metadata["experiment_config"] = experiment_config
    metadata["protected_artifact_sha256_before"] = before_hashes
    metadata["protected_artifact_sha256_after"] = after_hashes
    metadata["gate6b_and_gate6b1_artifacts_unchanged"] = True
    paths = write_outputs(metrics, trades, width, metadata, SWEEP_DIR)
    print(f"DEVELOPMENT ONLY: {start.date()} through {end.date()}")
    print(f"Configurations: {metrics['config_id'].nunique()}")
    print(f"Scenario rows: {len(metrics)}")
    print("Gate 6B and Gate 6B.1 artifacts unchanged: True")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
