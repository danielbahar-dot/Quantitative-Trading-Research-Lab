"""Reproducible session-date partitions for canonical research datasets.

This module only filters canonical rows into configured date ranges.  It does
not repair sessions, transform timestamps, adjust prices, or alter columns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "data_partitions.json"


def load_partition_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Load and structurally validate the dependency-free JSON config."""
    path = Path(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "dataset_id",
        "source_file",
        "partition_column",
        "timestamp_column",
        "report_file",
        "partitions",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(
            "Partition config is missing fields: " + ", ".join(sorted(missing))
        )
    if not isinstance(config["partitions"], list) or not config["partitions"]:
        raise ValueError("Partition config must define a non-empty partitions list")

    names: list[str] = []
    previous_end: pd.Timestamp | None = None
    for partition in config["partitions"]:
        partition_missing = {"name", "start", "end", "output_file"}.difference(
            partition
        )
        if partition_missing:
            raise ValueError(
                "Partition entry is missing fields: "
                + ", ".join(sorted(partition_missing))
            )
        name = str(partition["name"]).upper()
        partition["name"] = name
        if name in names:
            raise ValueError(f"Duplicate partition name: {name}")
        names.append(name)
        start = pd.Timestamp(partition["start"])
        end = pd.Timestamp(partition["end"])
        if start > end:
            raise ValueError(f"Partition {name} starts after it ends")
        if previous_end is not None and start <= previous_end:
            raise ValueError("Configured partition date ranges overlap or are unsorted")
        previous_end = end
    return config


def load_canonical_dataset(path: str | Path) -> pd.DataFrame:
    """Load the source CSV without changing its stored column values."""
    return pd.read_csv(path).reset_index(drop=True)


def assign_partitions(
    canonical: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    """Assign each complete session to at most one configured partition."""
    partition_column = str(config["partition_column"])
    if partition_column not in canonical:
        raise ValueError(f"Canonical dataset has no {partition_column} column")
    session_dates = pd.to_datetime(
        canonical[partition_column], errors="raise"
    ).dt.normalize()
    assignments = pd.Series(pd.NA, index=canonical.index, dtype="string")
    membership_count = pd.Series(0, index=canonical.index, dtype="int8")
    partitions: dict[str, pd.DataFrame] = {}

    for specification in config["partitions"]:
        name = str(specification["name"])
        start = pd.Timestamp(specification["start"])
        end = pd.Timestamp(specification["end"])
        mask = session_dates.between(start, end, inclusive="both")
        membership_count.loc[mask] += 1
        assignments.loc[mask] = name
        partitions[name] = canonical.loc[mask].copy()

    if membership_count.gt(1).any():
        raise ValueError("At least one canonical row belongs to multiple partitions")

    session_assignment_count = (
        pd.DataFrame(
            {
                "session_date": canonical[partition_column],
                "partition": assignments.fillna("UNASSIGNED"),
            }
        )
        .groupby("session_date", sort=False)["partition"]
        .nunique()
    )
    if session_assignment_count.gt(1).any():
        raise ValueError("At least one session_date is split across partitions")
    return partitions, assignments


def validate_partition_integrity(
    canonical: pd.DataFrame,
    partitions: dict[str, pd.DataFrame],
    assignments: pd.Series,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Validate coverage, exclusivity, ordering, schema, and boundaries."""
    ordered_names = [str(item["name"]) for item in config["partitions"]]
    recombined = pd.concat(
        [partitions[name] for name in ordered_names], axis=0
    ).reset_index(drop=True)
    canonical_reset = canonical.reset_index(drop=True)

    exact_recombination = _frames_equal(canonical_reset, recombined)
    canonical_duplicates = int(
        canonical[str(config["timestamp_column"])].duplicated().sum()
    )
    recombined_duplicates = int(
        recombined[str(config["timestamp_column"])].duplicated().sum()
    )
    outside_mask = assignments.isna()
    outside_sessions = sorted(
        canonical.loc[outside_mask, str(config["partition_column"])]
        .astype(str)
        .unique()
        .tolist()
    )

    boundary_results: dict[str, dict[str, Any]] = {}
    source_session_dates = set(
        pd.to_datetime(canonical[str(config["partition_column"])]).dt.normalize()
    )
    boundaries_valid = True
    for specification in config["partitions"]:
        name = str(specification["name"])
        partition = partitions[name]
        observed = pd.to_datetime(partition[str(config["partition_column"])])
        configured_start = pd.Timestamp(specification["start"])
        configured_end = pd.Timestamp(specification["end"])
        observed_start = observed.min().normalize() if len(observed) else pd.NaT
        observed_end = observed.max().normalize() if len(observed) else pd.NaT
        within_range = bool(
            len(observed)
            and observed_start >= configured_start
            and observed_end <= configured_end
        )
        boundaries_valid = boundaries_valid and within_range
        boundary_results[name] = {
            "configured_start": configured_start.date().isoformat(),
            "configured_end": configured_end.date().isoformat(),
            "first_observed_session": (
                observed_start.date().isoformat() if pd.notna(observed_start) else None
            ),
            "last_observed_session": (
                observed_end.date().isoformat() if pd.notna(observed_end) else None
            ),
            "start_status": _boundary_status(
                configured_start, observed_start, source_session_dates, "START"
            ),
            "end_status": _boundary_status(
                configured_end, observed_end, source_session_dates, "END"
            ),
            "all_rows_within_configured_range": within_range,
        }

    session_split = (
        pd.DataFrame(
            {
                "session_date": canonical[str(config["partition_column"])],
                "partition": assignments.fillna("UNASSIGNED"),
            }
        )
        .groupby("session_date", sort=False)["partition"]
        .nunique()
        .gt(1)
        .any()
    )
    checks = {
        "every_row_assigned_exactly_once": bool(assignments.notna().all()),
        "no_session_date_split": not bool(session_split),
        "recombined_row_count_matches": len(recombined) == len(canonical_reset),
        "recombined_values_and_order_match": exact_recombination,
        "columns_preserved": list(recombined.columns) == list(canonical.columns),
        "dtypes_preserved_in_memory": recombined.dtypes.equals(canonical.dtypes),
        "no_duplicate_timestamps_introduced": (
            recombined_duplicates == canonical_duplicates
        ),
        "contract_identifiers_unchanged": (
            recombined["contract"].equals(canonical_reset["contract"])
        ),
        "partition_rows_within_configured_boundaries": boundaries_valid,
        "no_rows_repaired_or_removed": exact_recombination,
    }
    return {
        "integrity_passed": all(checks.values()),
        "checks": checks,
        "canonical_rows": int(len(canonical)),
        "partition_rows": int(sum(len(frame) for frame in partitions.values())),
        "outside_rows": int(outside_mask.sum()),
        "outside_sessions": outside_sessions,
        "canonical_duplicate_timestamps": canonical_duplicates,
        "recombined_duplicate_timestamps": recombined_duplicates,
        "boundaries": boundary_results,
    }


def execute_partitioning(
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Create configured CSVs and a deterministic integrity report."""
    root = Path(project_root)
    config = load_partition_config(config_path)
    source_path = root / str(config["source_file"])
    source_sha_before = sha256_file(source_path)
    canonical = load_canonical_dataset(source_path)
    partitions, assignments = assign_partitions(canonical, config)
    integrity = validate_partition_integrity(
        canonical, partitions, assignments, config
    )
    if not integrity["integrity_passed"]:
        raise ValueError(f"Partition integrity failed before writing: {integrity}")

    output_details: dict[str, dict[str, Any]] = {}
    for specification in config["partitions"]:
        name = str(specification["name"])
        output_path = root / str(specification["output_file"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
        partitions[name].to_csv(temporary_path, index=False, lineterminator="\n")
        temporary_path.replace(output_path)

        reloaded = pd.read_csv(output_path)
        if not _frames_equal(partitions[name].reset_index(drop=True), reloaded):
            raise ValueError(f"CSV round-trip changed values or dtypes for {name}")
        dates = pd.to_datetime(reloaded[str(config["partition_column"])])
        output_details[name] = {
            **integrity["boundaries"][name],
            "rows": int(len(reloaded)),
            "sessions": int(dates.nunique()),
            "contracts": sorted(reloaded["contract"].astype(str).unique().tolist()),
            "output_file": str(specification["output_file"]).replace("\\", "/"),
            "file_size_bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        }

    source_sha_after = sha256_file(source_path)
    source_unchanged = source_sha_after == source_sha_before
    integrity["checks"]["canonical_source_sha256_unchanged"] = source_unchanged
    integrity["integrity_passed"] = (
        integrity["integrity_passed"] and source_unchanged
    )
    source_dates = pd.to_datetime(canonical[str(config["partition_column"])])
    report = {
        "dataset_id": config["dataset_id"],
        "source_file": config["source_file"],
        "source_sha256": source_sha_before,
        "timestamp_semantics": config.get("timestamp_semantics"),
        "timezone": config.get("timezone"),
        "current_orb_v01_oos_status": config.get(
            "current_orb_v01_oos_status"
        ),
        "research_notes": config.get("research_notes", []),
        "canonical": {
            "rows": int(len(canonical)),
            "sessions": int(source_dates.nunique()),
            "first_session_date": source_dates.min().date().isoformat(),
            "last_session_date": source_dates.max().date().isoformat(),
            "columns": list(canonical.columns),
            "dtypes": {column: str(dtype) for column, dtype in canonical.dtypes.items()},
            "contracts": sorted(canonical["contract"].astype(str).unique().tolist()),
            "file_size_bytes": source_path.stat().st_size,
        },
        "partitions": output_details,
        "totals": {
            "canonical_rows": integrity["canonical_rows"],
            "sum_partition_rows": integrity["partition_rows"],
            "outside_rows": integrity["outside_rows"],
            "outside_sessions": integrity["outside_sessions"],
        },
        "integrity": {
            "passed": integrity["integrity_passed"],
            "checks": integrity["checks"],
        },
    }
    report_path = root / str(config["report_file"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _frames_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(
            left,
            right,
            check_dtype=True,
            check_exact=True,
            check_like=False,
        )
    except AssertionError:
        return False
    return True


def _boundary_status(
    configured: pd.Timestamp,
    observed: pd.Timestamp,
    source_sessions: set[pd.Timestamp],
    label: str,
) -> str:
    if pd.notna(observed) and observed == configured:
        return "EXACT"
    if configured not in source_sessions:
        return f"{label}_BOUNDARY_HAS_NO_SOURCE_SESSION"
    return f"{label}_BOUNDARY_MISMATCH"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create configured session-date research partitions"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    arguments = parser.parse_args()
    report = execute_partitioning(arguments.config)
    for name, details in report["partitions"].items():
        print(
            f"{name}: {details['rows']:,} rows, {details['sessions']} sessions, "
            f"{details['first_observed_session']} to "
            f"{details['last_observed_session']}"
        )
    print(
        f"Total: {report['totals']['sum_partition_rows']:,} / "
        f"{report['totals']['canonical_rows']:,} canonical rows"
    )
    print(f"Integrity passed: {report['integrity']['passed']}")
    return 0 if report["integrity"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
