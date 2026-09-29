"""M4 derived-timeframe persistence tests. Synthetic sources in temp dirs only."""

from datetime import date, time, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from src.data.sessions import load_session_spec, with_calendar_overrides
from src.data.timeframe_store import (
    DEFAULT_DATASET_CONFIG,
    DEFAULT_DERIVED_ROOT,
    DerivedTimeframeNotFoundError,
    StaleDerivedTimeframeError,
    TimeframeStoreError,
    derived_paths,
    load_timeframe,
    materialize_timeframe,
    session_fingerprint,
)
from src.data.timeframes import OUTPUT_COLUMNS, TIMEFRAME_BUILDER_VERSION, build_timeframe

TZ = "America/New_York"
SPEC = load_session_spec()
SESSIONS = (date(2026, 9, 24), date(2026, 9, 25))


def source_frame(sessions=SESSIONS) -> pd.DataFrame:
    frames = []
    for day in sessions:
        start = pd.Timestamp.combine(day - timedelta(days=1), time(18, 0)).tz_localize(TZ)
        end = pd.Timestamp.combine(day, time(17, 0)).tz_localize(TZ)
        labels = pd.date_range(start + pd.Timedelta(minutes=1), end, freq="min")
        base = 20000 + np.arange(len(labels)) * 0.25
        frames.append(pd.DataFrame({
            "timestamp_et": labels,
            "session_date": day.isoformat(),
            "contract": "MNQ 12-26",
            "open": base, "high": base + 1.0, "low": base - 0.5, "close": base + 0.25,
            "volume": 10,
        }))
    return pd.concat(frames, ignore_index=True)


class StoreFixture(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.root = Path(self._folder.name)
        (self.root / "data" / "processed").mkdir(parents=True)
        self.source = self.root / "data" / "processed" / "dev.csv"
        self.reserved = self.root / "data" / "processed" / "val.csv"
        self.write_source(source_frame())
        source_frame().to_csv(self.reserved, index=False)
        self.config = self.root / "dataset.json"
        self.config.write_text(json.dumps({
            "dataset_id": "TEST_1m_v1",
            "instrument_id": "MNQ",
            "timezone": TZ,
            "timestamp_semantics": "NT8 bar-end time",
            "partitions": [
                {"name": "DEVELOPMENT", "partition_role": "DEVELOPMENT",
                 "start": "2026-09-01", "end": "2026-09-30", "output_file": "data/processed/dev.csv"},
                {"name": "VALIDATION", "partition_role": "VALIDATION",
                 "start": "2026-09-01", "end": "2026-09-30", "output_file": "data/processed/val.csv"},
            ],
        }), encoding="utf-8")
        self.out = self.root / "derived"

    def tearDown(self):
        self._folder.cleanup()

    def write_source(self, frame: pd.DataFrame) -> None:
        frame.to_csv(self.source, index=False)

    def kwargs(self, **extra):
        return {"partition": "DEVELOPMENT", "dataset_config": self.config, "output_root": self.out,
                "project_root": self.root, "session_spec": SPEC, **extra}


class MaterializeTests(StoreFixture):
    def test_writes_parquet_and_manifest_with_naming_convention(self):
        result = materialize_timeframe("4H", **self.kwargs())
        self.assertTrue(result.written)
        expected_name = f"TEST_1m_v1__DEVELOPMENT__4H__tfb-v{TIMEFRAME_BUILDER_VERSION}"
        self.assertEqual(result.data_path, self.out / "TEST_1m_v1" / "DEVELOPMENT" / f"{expected_name}.parquet")
        self.assertEqual(result.manifest_path.name, f"{expected_name}.manifest.json")
        self.assertTrue(result.data_path.is_file() and result.manifest_path.is_file())
        self.assertEqual(list(result.data_path.parent.glob("*.tmp")), [])

    def test_manifest_provenance(self):
        manifest = materialize_timeframe("1D", **self.kwargs()).manifest
        on_disk = json.loads(derived_paths("TEST_1m_v1", "DEVELOPMENT", "1D", self.out)[1].read_text(encoding="utf-8"))
        self.assertEqual(manifest, on_disk)
        self.assertFalse(manifest["authoritative"])
        self.assertEqual(manifest["partition"]["name"], "DEVELOPMENT")
        self.assertEqual(manifest["instrument"], {"instrument_id": "MNQ", "contracts": ["MNQ 12-26"]})
        self.assertEqual(manifest["source"]["path"], "data/processed/dev.csv")
        self.assertEqual(manifest["source"]["row_count"], 2760)
        self.assertEqual(manifest["timeframe"], {"timeframe_id": "1D", "minutes": None})
        self.assertEqual(manifest["session"]["fingerprint_sha256"], session_fingerprint(SPEC))
        self.assertEqual(manifest["generation"]["builder_version"], TIMEFRAME_BUILDER_VERSION)
        self.assertEqual(manifest["output"]["row_count"], 2)
        self.assertEqual(manifest["output"]["columns"], OUTPUT_COLUMNS)
        self.assertEqual(manifest["conventions"]["incomplete_bar_policy"][:7], "emitted")
        text = json.dumps(manifest)
        self.assertNotIn("20000", text)  # no prices in the manifest

    def test_valid_cache_is_reused_and_rebuild_is_deterministic(self):
        first = materialize_timeframe("15m", **self.kwargs())
        second = materialize_timeframe("15m", **self.kwargs())
        self.assertFalse(second.written)
        rebuilt = materialize_timeframe("15m", **self.kwargs(rebuild=True))
        self.assertTrue(rebuilt.written)
        self.assertEqual(first.manifest["output"]["sha256"], rebuilt.manifest["output"]["sha256"])

    def test_stale_cache_is_replaced_on_materialize(self):
        materialize_timeframe("1H", **self.kwargs())
        changed = source_frame()
        changed.loc[5, "volume"] = 11
        self.write_source(changed)
        self.assertTrue(materialize_timeframe("1H", **self.kwargs()).written)
        loaded = load_timeframe("1H", **self.kwargs())
        self.assertEqual(int(loaded["volume"].iloc[0]), 601)


class LoadTests(StoreFixture):
    def test_roundtrip_matches_builder_output(self):
        materialize_timeframe("5m", **self.kwargs())
        loaded = load_timeframe("5m", **self.kwargs())
        source = source_frame()
        source["timestamp_et"] = pd.to_datetime(source["timestamp_et"], utc=True).dt.tz_convert(TZ)
        expected = build_timeframe(source.set_index("timestamp_et"), "5m", SPEC)
        pd.testing.assert_frame_equal(loaded, expected)
        self.assertEqual(list(loaded.columns), OUTPUT_COLUMNS)
        self.assertEqual(str(loaded.index.tz), TZ)
        self.assertIsInstance(loaded["trading_date"].iloc[0], date)
        self.assertTrue((loaded["available_at"] == loaded.index).all())

    def test_missing_is_not_found(self):
        with self.assertRaises(DerivedTimeframeNotFoundError):
            load_timeframe("4H", **self.kwargs())

    def test_changed_source_is_stale_unless_verification_skipped(self):
        materialize_timeframe("4H", **self.kwargs())
        changed = source_frame()
        changed.loc[0, "close"] = changed.loc[0, "close"] + 0.25
        self.write_source(changed)
        with self.assertRaisesRegex(StaleDerivedTimeframeError, "source file hash"):
            load_timeframe("4H", **self.kwargs())
        self.assertEqual(len(load_timeframe("4H", **self.kwargs(verify_source=False))), 12)

    def test_tampered_output_is_stale(self):
        result = materialize_timeframe("4H", **self.kwargs())
        with result.data_path.open("ab") as handle:
            handle.write(b"x")
        with self.assertRaisesRegex(StaleDerivedTimeframeError, "output file hash"):
            load_timeframe("4H", **self.kwargs())

    def test_changed_session_model_is_stale(self):
        materialize_timeframe("1D", **self.kwargs())
        changed = with_calendar_overrides(
            SPEC, [{"trading_date": "2026-09-24", "kind": "MODIFIED", "close_et": "16:00"}],
            coverage_start="2026-09-01", coverage_end="2026-09-30",
        )
        self.assertNotEqual(session_fingerprint(changed), session_fingerprint(SPEC))
        with self.assertRaisesRegex(StaleDerivedTimeframeError, "session model"):
            load_timeframe("1D", **self.kwargs(session_spec=changed))

    def test_builder_version_mismatch_is_stale(self):
        result = materialize_timeframe("1D", **self.kwargs())
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        manifest["generation"]["builder_version"] = TIMEFRAME_BUILDER_VERSION - 1
        result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(StaleDerivedTimeframeError, "builder version"):
            load_timeframe("1D", **self.kwargs())
        with mock.patch("src.data.timeframe_store.TIMEFRAME_BUILDER_VERSION", TIMEFRAME_BUILDER_VERSION + 1):
            with self.assertRaises(DerivedTimeframeNotFoundError):  # new version has its own file name
                load_timeframe("1D", **self.kwargs())

    def test_unreadable_manifest_is_stale(self):
        result = materialize_timeframe("1D", **self.kwargs())
        result.manifest_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(StaleDerivedTimeframeError):
            load_timeframe("1D", **self.kwargs())


class PartitionGuardTests(StoreFixture):
    def test_reserved_partition_requires_explicit_flag(self):
        with self.assertRaisesRegex(TimeframeStoreError, "allow_reserved_partition"):
            materialize_timeframe("1D", **self.kwargs(partition="VALIDATION"))
        with self.assertRaises(TimeframeStoreError):
            load_timeframe("1D", **self.kwargs(partition="VALIDATION"))
        result = materialize_timeframe("1D", **self.kwargs(partition="VALIDATION", allow_reserved_partition=True))
        self.assertEqual(result.manifest["partition"]["role"], "VALIDATION")

    def test_source_outside_partition_range_is_rejected(self):
        self.write_source(source_frame(sessions=(date(2026, 10, 1),)))
        with self.assertRaisesRegex(TimeframeStoreError, "outside partition"):
            materialize_timeframe("1D", **self.kwargs())

    def test_unknown_partition_and_missing_source(self):
        with self.assertRaises(TimeframeStoreError):
            materialize_timeframe("1D", **self.kwargs(partition="OOS"))
        self.source.unlink()
        with self.assertRaisesRegex(TimeframeStoreError, "not found"):
            materialize_timeframe("1D", **self.kwargs())

    def test_invalid_path_components(self):
        for bad in ("", "..", "a/b", "a\\b", "x:y"):
            with self.subTest(bad):
                with self.assertRaises(TimeframeStoreError):
                    derived_paths(bad, "DEVELOPMENT", "1D", self.out)


class RepositoryDefaultsTests(unittest.TestCase):
    def test_default_layout_for_the_real_dataset(self):
        data_path, manifest_path = derived_paths("MNQ_1m_actual_contract_v1", "DEVELOPMENT", "4H")
        self.assertEqual(data_path.parent, DEFAULT_DERIVED_ROOT / "MNQ_1m_actual_contract_v1" / "DEVELOPMENT")
        self.assertTrue(DEFAULT_DATASET_CONFIG.is_file())

    def test_real_reserved_partitions_are_guarded(self):
        for partition in ("VALIDATION", "OOS"):
            with self.subTest(partition):
                with self.assertRaisesRegex(TimeframeStoreError, "allow_reserved_partition"):
                    load_timeframe("1D", partition=partition)


if __name__ == "__main__":
    unittest.main()
