import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.data.partitions import (
    assign_partitions,
    execute_partitioning,
    load_partition_config,
    sha256_file,
    validate_partition_integrity,
)


def make_config() -> dict:
    return {
        "dataset_id": "TEST",
        "source_file": "data/source.csv",
        "partition_column": "session_date",
        "timestamp_column": "timestamp_et",
        "report_file": "data/processed/report.json",
        "partitions": [
            {
                "name": "DEVELOPMENT",
                "start": "2024-06-21",
                "end": "2025-06-30",
                "output_file": "data/processed/development.csv",
            },
            {
                "name": "VALIDATION",
                "start": "2025-07-01",
                "end": "2025-12-31",
                "output_file": "data/processed/validation.csv",
            },
            {
                "name": "OOS",
                "start": "2026-01-01",
                "end": "2026-08-17",
                "output_file": "data/processed/oos.csv",
            },
        ],
    }


def make_canonical() -> pd.DataFrame:
    dates = [
        "2024-06-21",
        "2024-06-21",
        "2025-06-30",
        "2025-07-01",
        "2025-12-31",
        "2026-01-01",
        "2026-08-17",
    ]
    timestamps = [
        f"{date}T09:{31 + index:02d}:00-04:00"
        for index, date in enumerate(dates)
    ]
    return pd.DataFrame(
        {
            "timestamp_et": timestamps,
            "session_date": dates,
            "contract": ["MNQ TEST"] * len(dates),
            "open": [100.0 + index for index in range(len(dates))],
            "high": [101.0 + index for index in range(len(dates))],
            "low": [99.0 + index for index in range(len(dates))],
            "close": [100.5 + index for index in range(len(dates))],
            "volume": [100 + index for index in range(len(dates))],
            "source_file": ["test.txt"] * len(dates),
        }
    )


class DataPartitionTests(unittest.TestCase):
    def test_partitions_are_mutually_exclusive_and_cover_all_rows(self):
        canonical = make_canonical()
        partitions, assignments = assign_partitions(canonical, make_config())
        self.assertFalse(assignments.isna().any())
        self.assertEqual(sum(len(frame) for frame in partitions.values()), 7)
        partition_indexes = [set(frame.index) for frame in partitions.values()]
        for index, left in enumerate(partition_indexes):
            for right in partition_indexes[index + 1 :]:
                self.assertTrue(left.isdisjoint(right))

    def test_no_session_is_split_and_recombination_is_exact(self):
        canonical = make_canonical()
        config = make_config()
        partitions, assignments = assign_partitions(canonical, config)
        session_labels = pd.DataFrame(
            {
                "session_date": canonical["session_date"],
                "partition": assignments,
            }
        ).groupby("session_date")["partition"].nunique()
        self.assertTrue(session_labels.eq(1).all())
        recombined = pd.concat(partitions.values()).reset_index(drop=True)
        assert_frame_equal(recombined, canonical)
        integrity = validate_partition_integrity(
            canonical, partitions, assignments, config
        )
        self.assertTrue(integrity["integrity_passed"])

    def test_boundary_dates_are_inclusive_and_exact(self):
        canonical = make_canonical()
        config = make_config()
        partitions, assignments = assign_partitions(canonical, config)
        integrity = validate_partition_integrity(
            canonical, partitions, assignments, config
        )
        for boundary in integrity["boundaries"].values():
            self.assertEqual(boundary["start_status"], "EXACT")
            self.assertEqual(boundary["end_status"], "EXACT")

    def test_overlapping_configuration_is_rejected(self):
        with TemporaryDirectory() as temp_dir:
            config = make_config()
            config["partitions"][1]["start"] = "2025-06-30"
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overlap"):
                load_partition_config(path)

    def test_execution_writes_exact_round_trip_and_preserves_source_hash(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "data" / "source.csv"
            source.parent.mkdir(parents=True)
            make_canonical().to_csv(source, index=False)
            source_hash = sha256_file(source)
            config = make_config()
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            report = execute_partitioning(config_path, project_root=root)

            self.assertTrue(report["integrity"]["passed"])
            self.assertEqual(report["totals"]["canonical_rows"], 7)
            self.assertEqual(report["totals"]["sum_partition_rows"], 7)
            self.assertEqual(report["totals"]["outside_rows"], 0)
            self.assertEqual(sha256_file(source), source_hash)
            self.assertTrue((root / config["report_file"]).exists())


if __name__ == "__main__":
    unittest.main()
