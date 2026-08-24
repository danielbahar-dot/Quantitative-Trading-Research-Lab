"""Build Gate 6C candidate-reduction evidence from frozen DEVELOPMENT artifacts."""

from pathlib import Path
import json
import subprocess
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.partitions import load_partition_config  # noqa: E402
from src.experiments.orb_gate6c_candidate_reduction import (  # noqa: E402
    build_candidate_evidence,
    build_candidate_specification,
    build_metadata,
    build_shortlist,
    load_frozen_evidence,
    sha256_files,
    write_outputs,
)
from src.experiments.orb_v01_development_diagnostics import development_bounds  # noqa: E402


PROJECT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1"
SWEEP_DIR = PROJECT_DIR / "sweeps"
BASELINE_DIR = PROJECT_DIR / "baselines"
OUTPUT_DIR = PROJECT_DIR / "freeze" / "dev_candidate_freeze"
EXPERIMENT_CONFIG = PROJECT_ROOT / "config" / "experiments" / "orb_gate6c_dev_candidate_reduction.json"
PARTITION_CONFIG = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
GATE6B_SUMMARY = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_summary.csv"
GATE6B1_CONDITIONAL = SWEEP_DIR / "orb_gate6b1_DEV_or_width_conditional_performance.csv"
GATE6B2_SUMMARY = SWEEP_DIR / "orb_gate6b2_DEV_ambiguity_robustness_summary.csv"
DEVELOPMENT_BASELINE = BASELINE_DIR / "orb_v01_DEV_with_20m_PRINT_summary.csv"
SOURCE_ARTIFACTS = sorted(SWEEP_DIR.glob("orb_gate6b_DEV_*")) + sorted(
    SWEEP_DIR.glob("orb_gate6b1_DEV_*")
) + sorted(SWEEP_DIR.glob("orb_gate6b2_DEV_*")) + [DEVELOPMENT_BASELINE]


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def _working_tree_status() -> list[str]:
    output = subprocess.check_output(
        ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"], text=True
    )
    return [line for line in output.splitlines() if line]


def main() -> int:
    config = json.loads(EXPERIMENT_CONFIG.read_text(encoding="utf-8"))
    partition_config = load_partition_config(PARTITION_CONFIG)
    start, end = development_bounds(partition_config)
    if end > pd.Timestamp("2025-06-30"):
        raise ValueError("Gate 6C may not use reserved-period evidence")
    if any("VALIDATION" in path.name.upper() or "OOS" in path.name.upper() for path in SOURCE_ARTIFACTS):
        raise ValueError("A reserved-period artifact was routed into Gate 6C")

    before_hashes = sha256_files(SOURCE_ARTIFACTS)
    gate6, conditional, gate6b2, baseline = load_frozen_evidence(
        GATE6B_SUMMARY,
        GATE6B1_CONDITIONAL,
        GATE6B2_SUMMARY,
        DEVELOPMENT_BASELINE,
        development_start=start,
        development_end=end,
    )
    evidence = build_candidate_evidence(gate6, conditional, gate6b2, config)
    shortlist = build_shortlist(evidence)
    after_hashes = sha256_files(SOURCE_ARTIFACTS)
    if before_hashes != after_hashes:
        raise ValueError("A frozen Gate 5B/6B/6B.1/6B.2 artifact changed during Gate 6C")

    metadata = build_metadata(
        config,
        before_hashes,
        git_commit=_git_commit(),
        working_tree_status=_working_tree_status(),
        dataset_id=partition_config["dataset_id"],
        development_start=start.date().isoformat(),
        development_end=end.date().isoformat(),
    )
    metadata["source_artifact_sha256_before"] = before_hashes
    metadata["source_artifact_sha256_after"] = after_hashes
    metadata["frozen_source_artifacts_unchanged"] = True
    metadata["baseline_rows_read"] = len(baseline)
    specification = build_candidate_specification(shortlist, config, metadata)
    paths = write_outputs(evidence, shortlist, specification, metadata, OUTPUT_DIR)

    print(f"DEVELOPMENT ONLY: {start.date()} through {end.date()}")
    print(f"Candidate universe: {len(evidence)}")
    print(f"Core candidates: {(shortlist['candidate_class'] == 'CORE_SHORTLIST').sum()}")
    print(f"Research hypotheses: {(shortlist['candidate_class'] == 'RESEARCH_HYPOTHESIS').sum()}")
    print("Frozen Gate 5B/6B/6B.1/6B.2 artifacts unchanged: True")
    print("Freeze status: PENDING_HUMAN_APPROVAL")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
