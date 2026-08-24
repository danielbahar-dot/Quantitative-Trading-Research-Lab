"""Run Gate 6A.1's DEVELOPMENT-only 25% stop ambiguity sensitivity."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.partitions import load_partition_config  # noqa: E402
from src.experiments.orb_gate6a1_ambiguity import (  # noqa: E402
    load_gate6a_inputs,
    run_sensitivity,
    sha256_files,
    write_outputs,
)
from src.experiments.orb_v01_development_diagnostics import development_bounds  # noqa: E402
from src.visualization.research_viewer import load_price_data  # noqa: E402


SWEEP_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "sweeps"
GATE6_SUMMARY = SWEEP_DIR / "orb_gate6a_DEV_print_static_r_sweep.csv"
GATE6_AUDIT = SWEEP_DIR / "orb_gate6a_DEV_print_static_r_candidate_audit.csv"
GATE6_FILES = sorted(SWEEP_DIR.glob("orb_gate6a_DEV_print_static_r*"))
PARTITION_CONFIG = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
EXPERIMENT_CONFIG = PROJECT_ROOT / "config" / "experiments" / "orb_gate6a1_dev_25pct_ambiguity.json"
DEVELOPMENT_PRICES = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_DEVELOPMENT.csv"


def main() -> int:
    configuration = json.loads(EXPERIMENT_CONFIG.read_text(encoding="utf-8"))
    if configuration["expected_configuration_count"] != 20:
        raise ValueError("Gate 6A.1 configuration must contain exactly 20 cells")
    partition_config = load_partition_config(PARTITION_CONFIG)
    start, end = development_bounds(partition_config)
    before_hashes = sha256_files(GATE6_FILES)
    price_data = load_price_data(DEVELOPMENT_PRICES)
    audit, summary = load_gate6a_inputs(GATE6_AUDIT, GATE6_SUMMARY, development_end=end)
    metrics, trades, metadata = run_sensitivity(
        price_data, audit, summary,
        development_start=start, development_end=end,
    )
    after_hashes = sha256_files(GATE6_FILES)
    if before_hashes != after_hashes:
        raise ValueError("A Gate 6A artifact changed during Gate 6A.1")
    metadata["experiment_config"] = configuration
    metadata["gate6a_artifact_sha256_before"] = before_hashes
    metadata["gate6a_artifact_sha256_after"] = after_hashes
    metadata["gate6a_artifacts_unchanged"] = True
    paths = write_outputs(metrics, trades, metadata, SWEEP_DIR)
    print(f"DEVELOPMENT ONLY: {start.date()} through {end.date()}")
    print(f"Configurations: {metrics[['or_minutes', 'target_r']].drop_duplicates().shape[0]}")
    print(f"Scenario rows: {len(metrics)}")
    print("Gate 6A artifacts unchanged: True")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
