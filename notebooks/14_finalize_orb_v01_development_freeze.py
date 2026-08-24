"""Finalize the human-approved MNQ ORB V0.1 DEVELOPMENT freeze.

This script reads DEVELOPMENT research artifacts and repository metadata only.
It must run before the Gate 7 Validation dataset is opened.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1"
FREEZE_DIR = PROJECT_DIR / "freeze" / "dev_candidate_freeze"
VALIDATION_DIR = PROJECT_DIR / "validation"
SOURCE_COMMIT = "8198f197a239e75074140ce4b2344520deff99ec"
FREEZE_TAG = "mnq-orb-v0.1-dev-freeze"
FREEZE_TIMESTAMP = "2026-08-24T12:23:11.772990Z"
APPROVED = {
    "MNQ_ORB_V01_CAND_001": "15m_PRINT_FIXED_50_TARGET75PT",
    "MNQ_ORB_V01_CAND_002": "20m_PRINT_OR_MIDPOINT_TARGET75PT",
    "MNQ_ORB_V01_CAND_003": "30m_PRINT_FIXED_40_TARGET75PT",
}
EXCLUDED_HYPOTHESES = {
    "MNQ_ORB_V01_HYP_001": "20m_PRINT_OR_25_RETRACEMENT_TARGET75PT",
    "MNQ_ORB_V01_HYP_002": "20m_PRINT_OR_25_RETRACEMENT_TARGET100PT",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(PROJECT_ROOT), *args], text=True).strip()


def _candidate_semantics(row) -> dict:
    if row.stop_mode == "OR_MIDPOINT":
        stop = {
            "mode": "OR_MIDPOINT",
            "long_formula": "round_to_tick(OR_high - 0.50 * (OR_high - OR_low))",
            "short_formula": "round_to_tick(OR_low + 0.50 * (OR_high - OR_low))",
        }
    else:
        points = float(str(row.stop_mode).split("_")[1])
        stop = {
            "mode": row.stop_mode,
            "points": points,
            "long_formula": f"round_to_tick(entry_price - {points:g})",
            "short_formula": f"round_to_tick(entry_price + {points:g})",
        }
    return {
        "candidate_id": row.stable_candidate_id,
        "configuration_id": row.config_id,
        "or_minutes": int(row.or_minutes),
        "breakout_type": "PRINT",
        "stop": stop,
        "target": {
            "mode": "FIXED_POINTS",
            "points": 75.0,
            "long_formula": "round_to_tick(entry_price + 75.0)",
            "short_formula": "round_to_tick(entry_price - 75.0)",
        },
        "development_reference": {
            "executed_trades": int(row.executed_trades),
            "average_r": float(row.average_r),
            "profit_factor_r": float(row.profit_factor_r),
            "max_drawdown_r": float(row.max_drawdown_r),
            "entry_stop_ambiguity_rate": float(row.entry_stop_ambiguity_rate),
            "entry_first_average_r": float(row.entry_first_avg_r),
            "chronology_range_average_r": float(row.chronology_range_avg_r),
            "or_width_dependency": row.or_width_dependency,
        },
    }


def main() -> int:
    if _git("rev-parse", "HEAD") != SOURCE_COMMIT:
        raise ValueError("Freeze finalization must be based on the reviewed Gate 6C source commit")
    protocol_path = VALIDATION_DIR / "gate7_validation_protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol["status"] != "PREDECLARED_LOCKED":
        raise ValueError("Gate 7 protocol is not locked before freeze finalization")

    partition = json.loads((PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json").read_text(encoding="utf-8"))
    report = json.loads((PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_partition_report.json").read_text(encoding="utf-8"))
    instrument = json.loads((PROJECT_ROOT / "config" / "instruments" / "mnq.json").read_text(encoding="utf-8"))
    shortlist = pd.read_csv(FREEZE_DIR / "orb_gate6c_DEV_candidate_shortlist.csv")
    selected = shortlist.loc[shortlist["stable_candidate_id"].isin(APPROVED)].copy()
    observed = dict(zip(selected["stable_candidate_id"], selected["config_id"]))
    if observed != APPROVED or len(selected) != 3:
        raise ValueError("Approved freeze candidates do not match the Gate 6C shortlist")
    if shortlist.loc[shortlist["stable_candidate_id"].isin(EXCLUDED_HYPOTHESES)].empty:
        raise ValueError("Research hypotheses are missing from retained Gate 6C history")

    shared_semantics = {
        "instrument": "MNQ",
        "timeframe": "1 minute",
        "timezone": "America/New_York",
        "timestamp_semantics": "timestamp_et is NinjaTrader bar_end_time; bar_start_time is timestamp_et minus one minute",
        "opening_range": "09:30 ET market open represented by bar-end stamps beginning 09:31; first eligible bar is one minute after the final OR stamp",
        "signal": "retain first LONG when intrabar high strictly exceeds OR high and first SHORT when intrabar low strictly crosses below OR low; same-bar two-sided PRINT crossing is retained as signal ambiguity; signal cutoff is 11:30 ET inclusive",
        "entry": "PRINT candidate enters at the breached OR boundary on the signal/bar timestamp",
        "signal_retention": "retain at most first long and first short signal per session",
        "daily_trade_rule": "accept the earliest valid executable non-excluded candidate; maximum one accepted trade per session per frozen candidate; ambiguous/invalid candidates do not consume allowance; later candidates remain audited as SESSION_TRADE_LIMIT",
        "exit": "evaluate stop/target from the PRINT entry bar; force SESSION_END at the 16:00 ET bar close",
        "shortened_session": "when 16:00 is absent, force SESSION_END at the last observed same-session bar whose bar-end timestamp is no later than 16:00 ET",
        "tick_handling": "MNQ tick size is 0.25 points; calculated prices use Decimal ROUND_HALF_UP to the nearest tick",
        "ambiguity": "same-bar stop-and-target is AMBIGUOUS_STOP_TARGET; PRINT entry-bar stop touch is AMBIGUOUS_ENTRY_STOP because OHLC cannot order entry versus stop; ambiguous outcomes are excluded under canonical EXCLUDED performance; invalid candidates are audited",
        "disabled": ["CLOSE", "break_even", "trailing_stop", "FVG", "EMA", "VWAP", "partial_exits", "commissions", "slippage"],
    }
    candidates = [_candidate_semantics(row) for row in selected.sort_values("stable_candidate_id").itertuples(index=False)]
    specification = {
        "project_id": "mnq_orb_v0_1",
        "strategy_version": "MNQ_ORB_V0.1",
        "freeze_status": "FROZEN_FOR_VALIDATION",
        "human_approval_recorded": True,
        "freeze_timestamp_utc": FREEZE_TIMESTAMP,
        "freeze_git_tag": FREEZE_TAG,
        "implementation_source_git_commit": SOURCE_COMMIT,
        "instrument": instrument,
        "dataset": {
            "dataset_id": partition["dataset_id"],
            "canonical_source_sha256": report["source_sha256"],
            "development_partition_sha256": report["partitions"]["DEVELOPMENT"]["sha256"],
            "validation_partition_sha256": report["partitions"]["VALIDATION"]["sha256"],
        },
        "partitions": {
            "DEVELOPMENT": {"start": "2024-06-21", "end": "2025-06-30"},
            "VALIDATION": {"start": "2025-07-01", "end": "2025-12-31"},
            "OOS_BURNED": {"start": "2026-01-01", "end": "2026-08-17", "access_authorized": False},
        },
        "shared_strategy_semantics": shared_semantics,
        "candidates": candidates,
        "excluded_research_hypotheses": [
            {"candidate_id": key, "configuration_id": value, "retained_in_research_history": True, "validation_authorized": False}
            for key, value in EXCLUDED_HYPOTHESES.items()
        ],
        "validation_protocol": str(protocol_path.relative_to(PROJECT_ROOT)),
        "post_validation_retuning_authorized": False,
    }

    source_paths = [
        PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json",
        PROJECT_ROOT / "config" / "instruments" / "mnq.json",
        FREEZE_DIR / "orb_gate6c_DEV_candidate_evidence.csv",
        FREEZE_DIR / "orb_gate6c_DEV_candidate_shortlist.csv",
        PROJECT_DIR / "sweeps" / "orb_gate6b_DEV_fixed_target_stop_summary.csv",
        PROJECT_DIR / "sweeps" / "orb_gate6b1_DEV_or_width_conditional_performance.csv",
        PROJECT_DIR / "sweeps" / "orb_gate6b2_DEV_ambiguity_robustness_summary.csv",
        protocol_path,
    ]
    metadata = {
        "project_id": "mnq_orb_v0_1",
        "strategy_version": "MNQ_ORB_V0.1",
        "freeze_status": "FROZEN_FOR_VALIDATION",
        "freeze_timestamp_utc": FREEZE_TIMESTAMP,
        "freeze_git_tag": FREEZE_TAG,
        "implementation_source_git_commit": SOURCE_COMMIT,
        "implementation_source_working_tree_clean_before_freeze_preparation": True,
        "freeze_preparation_working_tree_status": _git("status", "--porcelain").splitlines(),
        "freeze_package_changes_must_be_committed_and_tagged_before_validation": True,
        "source_gate_ids": ["GATE_6B", "GATE_6B.1", "GATE_6B.2", "GATE_6C"],
        "candidate_ids": list(APPROVED),
        "excluded_hypothesis_ids": list(EXCLUDED_HYPOTHESES),
        "development_partition": {"start": "2024-06-21", "end": "2025-06-30"},
        "dataset_id": partition["dataset_id"],
        "dataset_hashes": specification["dataset"],
        "source_artifact_sha256": {str(path.relative_to(PROJECT_ROOT)): _sha256(path) for path in source_paths},
        "validation_performance_loaded": False,
        "oos_burned_loaded": False,
        "candidate_specification": str((FREEZE_DIR / "mnq_orb_v0_1_validation_candidates.json").relative_to(PROJECT_ROOT)),
        "validation_protocol": str(protocol_path.relative_to(PROJECT_ROOT)),
    }
    (FREEZE_DIR / "mnq_orb_v0_1_validation_candidates.json").write_text(json.dumps(specification, indent=2) + "\n", encoding="utf-8")
    (FREEZE_DIR / "orb_gate6c_DEV_freeze_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (FREEZE_DIR / "orb_gate6c_DEV_shortlist_report.md").write_text(
        "# MNQ ORB V0.1 DEVELOPMENT freeze\n\n"
        "**Status: `FROZEN_FOR_VALIDATION`**\n\n"
        "Human review approved exactly three core candidates: CAND_001 (15m/fixed-50/75), "
        "CAND_002 (20m/midpoint/75), and CAND_003 (30m/fixed-40/75).\n\n"
        "HYP_001 and HYP_002 remain in Gate 6C research history and are explicitly excluded from V0.1 Validation.\n\n"
        "The machine-readable specification records every inherited signal, entry, stop, target, session, tick, "
        "timestamp, shortened-session, and ambiguity rule. Gate 7 is governed by the predeclared protocol in "
        "`experiments/projects/mnq_orb_v0_1/validation/gate7_validation_protocol.json`.\n",
        encoding="utf-8",
    )
    print("Freeze status: FROZEN_FOR_VALIDATION")
    print(f"Implementation source commit: {SOURCE_COMMIT}")
    print(f"Approved candidates: {len(candidates)}")
    print("Validation performance loaded: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
