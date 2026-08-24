"""Run confirmatory Gate 7 after verifying the committed/tagged DEVELOPMENT freeze."""

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

from src.experiments.orb_gate7_validation import (  # noqa: E402
    APPROVED_IDS,
    build_partition_or_levels,
    run_validation,
    validate_frozen_contract,
    write_outputs,
)
from src.visualization.research_viewer import load_price_data  # noqa: E402


PROJECT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1"
VALIDATION_DIR = PROJECT_DIR / "validation"
FREEZE_DIR = PROJECT_DIR / "freeze" / "dev_candidate_freeze"
SWEEP_DIR = PROJECT_DIR / "sweeps"
PARTITION_CONFIG = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
PARTITION_REPORT = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_partition_report.json"
VALIDATION_PRICES = PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_VALIDATION.csv"
PROTOCOL = VALIDATION_DIR / "gate7_validation_protocol.json"
FROZEN_SPEC = FREEZE_DIR / "mnq_orb_v0_1_validation_candidates.json"
FROZEN_METADATA = FREEZE_DIR / "orb_gate6c_DEV_freeze_metadata.json"
DEV_SUMMARY = SWEEP_DIR / "orb_gate6b_DEV_fixed_target_stop_summary.csv"
DEV_EVIDENCE = FREEZE_DIR / "orb_gate6c_DEV_candidate_evidence.csv"
FREEZE_TAG = "mnq-orb-v0.1-dev-freeze"
PROTECTED_DEVELOPMENT = sorted(SWEEP_DIR.glob("orb_gate6b_DEV_*")) + sorted(
    SWEEP_DIR.glob("orb_gate6b1_DEV_*")
) + sorted(SWEEP_DIR.glob("orb_gate6b2_DEV_*")) + sorted(FREEZE_DIR.glob("*"))


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(PROJECT_ROOT), *args], text=True).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(PROJECT_ROOT)): _sha256(path) for path in paths}


def main() -> int:
    # This entire block executes before the Validation CSV is opened.
    if _git("status", "--porcelain"):
        raise ValueError("Gate 7 requires the committed DEVELOPMENT freeze and a clean working tree")
    source_commit = _git("rev-parse", "HEAD")
    freeze_commit = _git("rev-list", "-n", "1", FREEZE_TAG)
    ancestor_check = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "merge-base", "--is-ancestor", freeze_commit, source_commit],
        check=False,
    )
    if ancestor_check.returncode != 0:
        raise ValueError("The DEVELOPMENT freeze tag is not an ancestor of the Gate 7 source commit")
    specification = json.loads(FROZEN_SPEC.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze_metadata = json.loads(FROZEN_METADATA.read_text(encoding="utf-8"))
    validate_frozen_contract(specification, protocol)
    if freeze_metadata["freeze_status"] != "FROZEN_FOR_VALIDATION":
        raise ValueError("Freeze metadata is not finalized")
    partition = json.loads(PARTITION_CONFIG.read_text(encoding="utf-8"))
    validation_partition = next(item for item in partition["partitions"] if item["name"] == "VALIDATION")
    start = pd.Timestamp(validation_partition["start"])
    end = pd.Timestamp(validation_partition["end"])
    if (start, end) != (pd.Timestamp("2025-07-01"), pd.Timestamp("2025-12-31")):
        raise ValueError("VALIDATION boundaries changed after protocol declaration")
    protocol_time = pd.Timestamp(protocol["protocol_created_at_utc"])
    run_timestamp = datetime.now(timezone.utc).isoformat()
    if protocol_time >= pd.Timestamp(run_timestamp):
        raise ValueError("Protocol timestamp does not precede Validation execution")

    before_hashes = _hashes(PROTECTED_DEVELOPMENT)
    partition_report = json.loads(PARTITION_REPORT.read_text(encoding="utf-8"))
    expected_validation_hash = partition_report["partitions"]["VALIDATION"]["sha256"]
    actual_validation_hash = _sha256(VALIDATION_PRICES)
    if actual_validation_hash != expected_validation_hash:
        raise ValueError("Validation partition hash differs from the predefined dataset report")

    # First actual reserved-period data access occurs only after every assertion above.
    price_data = load_price_data(VALIDATION_PRICES)
    dates = pd.to_datetime(price_data["session_date"])
    if not dates.between(start, end, inclusive="both").all():
        raise ValueError("Validation source contains a DEVELOPMENT or OOS_BURNED row")
    or_levels = build_partition_or_levels(price_data)
    development_summary = pd.read_csv(DEV_SUMMARY)
    development_evidence = pd.read_csv(DEV_EVIDENCE)
    results = run_validation(
        price_data,
        or_levels,
        development_summary,
        development_evidence,
        protocol,
        validation_start=start,
        validation_end=end,
        source_git_commit=source_commit,
        run_timestamp=run_timestamp,
    )
    after_hashes = _hashes(PROTECTED_DEVELOPMENT)
    if before_hashes != after_hashes:
        raise ValueError("A frozen DEVELOPMENT artifact changed during Gate 7")

    comparison = results["dev_vs_val"]
    metadata = {
        "experiment_id": "mnq_orb_v0_1_gate7_validation",
        "strategy_version": "MNQ_ORB_V0.1",
        "partition": "VALIDATION",
        "validation_start": start.date().isoformat(),
        "validation_end": end.date().isoformat(),
        "actual_minimum_session_date": dates.min().date().isoformat(),
        "actual_maximum_session_date": dates.max().date().isoformat(),
        "sessions_available": int(dates.nunique()),
        "candidate_ids": list(APPROVED_IDS),
        "candidate_count": len(APPROVED_IDS),
        "research_hypotheses_evaluated": False,
        "parameter_sweep_performed": False,
        "source_git_commit": source_commit,
        "freeze_git_commit": freeze_commit,
        "freeze_git_tag": FREEZE_TAG,
        "working_tree_clean_before_validation": True,
        "run_timestamp_utc": run_timestamp,
        "protocol_created_at_utc": protocol["protocol_created_at_utc"],
        "protocol_sha256": _sha256(PROTOCOL),
        "protocol_existed_before_validation_access": True,
        "freeze_existed_before_validation_access": True,
        "validation_partition_sha256": actual_validation_hash,
        "development_artifact_sha256_before": before_hashes,
        "development_artifact_sha256_after": after_hashes,
        "development_artifacts_unchanged": True,
        "oos_burned_accessed": False,
        "validated_signal_semantics_modified": False,
        "validated_execution_semantics_modified": False,
        "initial_execution_attempt": "Stopped after Validation load and before metric/output creation because chronology session_date required dtype normalization; no strategy rule changed.",
        "decision_counts": comparison["overall_decision"].value_counts().to_dict(),
        "human_review_required": True,
    }
    paths = write_outputs(results, metadata, VALIDATION_DIR)
    print(f"Protocol declared: {protocol['protocol_created_at_utc']}")
    print(f"Validation execution started: {run_timestamp}")
    print(f"VALIDATION ONLY: {start.date()} through {end.date()}")
    print(f"Candidates evaluated: {len(APPROVED_IDS)}")
    print("Research hypotheses evaluated: False")
    print("OOS_BURNED accessed: False")
    print(comparison[["candidate_id", "validation_trades", "validation_average_r", "validation_profit_factor_r", "overall_decision"]].to_string(index=False))
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
