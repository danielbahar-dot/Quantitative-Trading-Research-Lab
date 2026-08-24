"""Run Gate 6B's DEVELOPMENT-only fixed-point target x stop study."""

from pathlib import Path
import json
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.partitions import load_partition_config  # noqa: E402
from src.experiments.orb_gate6a_sweep import load_development_or_levels  # noqa: E402
from src.experiments.orb_gate6b_fixed_points import (  # noqa: E402
    EXPECTED_CONFIGURATIONS,
    OR_DURATIONS,
    STOP_DEFINITIONS,
    TARGET_POINTS_VALUES,
    run_development_study,
    sha256_files,
    write_outputs,
)
from src.experiments.orb_v01_development_diagnostics import development_bounds  # noqa: E402
from src.visualization.research_viewer import load_price_data  # noqa: E402


SWEEP_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "sweeps"
EXPERIMENT_CONFIG = PROJECT_ROOT / "config" / "experiments" / "orb_gate6b_dev_fixed_target_stop.json"
PARTITION_CONFIG = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
DEVELOPMENT_PRICES = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_DEVELOPMENT.csv"
OR_LEVELS = PROJECT_ROOT / "data" / "processed" / "mnq_or_levels.csv"
GATE6_SIGNAL_REFERENCE = SWEEP_DIR / "orb_gate6a_DEV_print_static_r_candidate_audit.csv"
PROTECTED_FILES = sorted(SWEEP_DIR.glob("orb_gate6a_DEV_print_static_r*")) + sorted(
    SWEEP_DIR.glob("orb_gate6a1_DEV_25pct_ambiguity*")
)


def _validate_config(config: dict) -> None:
    if config["or_minutes"] != list(OR_DURATIONS):
        raise ValueError("Gate 6B config has unexpected durations")
    if config["target_points"] != list(TARGET_POINTS_VALUES):
        raise ValueError("Gate 6B config has unexpected fixed targets")
    if [item["name"] for item in config["stop_modes"]] != [item[0] for item in STOP_DEFINITIONS]:
        raise ValueError("Gate 6B config has unexpected stops")
    if config["expected_configuration_count"] != EXPECTED_CONFIGURATIONS:
        raise ValueError("Gate 6B config must require exactly 75 cells")


def main() -> int:
    experiment_config = json.loads(EXPERIMENT_CONFIG.read_text(encoding="utf-8"))
    _validate_config(experiment_config)
    partition_config = load_partition_config(PARTITION_CONFIG)
    start, end = development_bounds(partition_config)
    before_hashes = sha256_files(PROTECTED_FILES)
    price_data = load_price_data(DEVELOPMENT_PRICES)
    or_levels = load_development_or_levels(OR_LEVELS, start, end)
    signal_reference = pd.read_csv(GATE6_SIGNAL_REFERENCE)
    signal_reference = signal_reference.loc[signal_reference["or_minutes"].isin(OR_DURATIONS)]
    if not pd.to_datetime(signal_reference["session_date"]).le(end).all():
        raise ValueError("Signal reference contains a reserved-period row")
    summary, trades, audit, diagnostics, metadata = run_development_study(
        price_data, or_levels, signal_reference,
        development_start=start, development_end=end,
    )
    after_hashes = sha256_files(PROTECTED_FILES)
    if before_hashes != after_hashes:
        raise ValueError("A Gate 6A or Gate 6A.1 artifact changed during Gate 6B")
    metadata["experiment_config"] = experiment_config
    metadata["protected_artifact_sha256_before"] = before_hashes
    metadata["protected_artifact_sha256_after"] = after_hashes
    metadata["gate6a_and_gate6a1_artifacts_unchanged"] = True
    paths = write_outputs(summary, trades, audit, diagnostics, metadata, SWEEP_DIR)
    print(f"DEVELOPMENT ONLY: {start.date()} through {end.date()}")
    print(f"Configurations: {len(summary)}")
    print("Gate 6A and Gate 6A.1 artifacts unchanged: True")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
