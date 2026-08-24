"""Run the controlled Gate 6A PRINT sweep on DEVELOPMENT only."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.partitions import load_partition_config  # noqa: E402
from src.experiments.orb_gate6a_sweep import (  # noqa: E402
    EXPECTED_CONFIGURATION_COUNT,
    OR_DURATIONS,
    STOP_DEFINITIONS,
    TARGET_R_VALUES,
    development_bounds,
    load_development_or_levels,
    run_development_sweep,
    write_sweep_outputs,
)
from src.visualization.research_viewer import load_price_data  # noqa: E402


EXPERIMENT_CONFIG_FILE = PROJECT_ROOT / "config" / "experiments" / "orb_gate6a_dev_print_static_r.json"
PARTITION_CONFIG_FILE = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
DEVELOPMENT_DATA_FILE = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_DEVELOPMENT.csv"
OR_LEVEL_FILE = PROJECT_ROOT / "data" / "processed" / "mnq_or_levels.csv"
BASELINE_FILES = (
    PROJECT_ROOT / "data" / "processed" / "orb_v01_completed_trades.csv",
    PROJECT_ROOT / "data" / "processed" / "orb_v01_20m_print_DEV_completed_trades.csv",
)
OUTPUT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "sweeps"


def _validate_config(config: dict) -> None:
    if config["or_minutes"] != list(OR_DURATIONS):
        raise ValueError("Experiment config does not match approved OR durations")
    if config["breakout_type"] != ["PRINT"]:
        raise ValueError("Experiment config must contain PRINT only")
    if config["stop_retracement_fraction"] != [value for _, value in STOP_DEFINITIONS]:
        raise ValueError("Experiment config does not match approved stops")
    if config["target_r"] != list(TARGET_R_VALUES):
        raise ValueError("Experiment config does not match approved targets")
    if config["expected_configuration_count"] != EXPECTED_CONFIGURATION_COUNT:
        raise ValueError("Experiment config must require exactly 40 cells")


def main() -> int:
    experiment_config = json.loads(EXPERIMENT_CONFIG_FILE.read_text(encoding="utf-8"))
    _validate_config(experiment_config)
    partition_config = load_partition_config(PARTITION_CONFIG_FILE)
    start, end = development_bounds(partition_config)
    price_data = load_price_data(DEVELOPMENT_DATA_FILE)
    or_levels = load_development_or_levels(OR_LEVEL_FILE, start, end)
    summary, trades, audit, metadata = run_development_sweep(
        price_data, or_levels, partition_config, BASELINE_FILES
    )
    metadata["experiment_config"] = experiment_config
    paths = write_sweep_outputs(summary, trades, audit, metadata, OUTPUT_DIR)
    print(f"DEVELOPMENT ONLY: {start.date()} through {end.date()}")
    print(f"Configurations: {len(summary)}")
    print(
        "Midpoint/2R controls reproduced: "
        f"{summary.loc[summary['baseline_control'], 'baseline_reproduced'].all()}"
    )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
