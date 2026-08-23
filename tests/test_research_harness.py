import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.research_harness import ExperimentLedger


class ExperimentLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "experiments" / "schema").mkdir(parents=True)
        source_schema = (
            Path(__file__).resolve().parents[1]
            / "experiments"
            / "schema"
            / "experiment_ledger.sql"
        )
        (self.root / "experiments" / "schema" / "experiment_ledger.sql").write_text(
            source_schema.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.root / "src").mkdir()
        (self.root / "src" / "strategy.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.ledger = ExperimentLedger(self.root)
        self.config = {
            "experiment_id": "orb_test_baseline",
            "project_id": "mnq_orb_v0_1",
            "strategy_name": "ORB", "strategy_version": "0.1.0",
            "strategy_family": "ORB", "asset_class": "futures",
            "instrument_id": "MNQ", "dataset_id": "mnq_test_v1",
            "dataset_hash": "abc123", "partition": "DEVELOPMENT",
            "hypothesis": "The opening-range break has positive expectancy.",
            "dataset": "data/processed/mnq.csv", "timeframe": "1 minute",
            "session": {"timezone": "America/New_York", "start": "09:30"},
            "parameters": {"opening_range_minutes": 15},
            "execution_model": {"engine": "custom"},
            "costs_slippage": {"slippage_ticks_per_side": 1},
            "results_summary": {}, "notes": "baseline",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initialize_creates_both_ledgers(self):
        self.ledger.initialize()
        self.assertTrue(self.ledger.db_path.exists())
        self.assertTrue(self.ledger.csv_path.exists())

    def test_create_run_records_sqlite_csv_and_snapshot(self):
        run_id, run_dir = self.ledger.create_run(self.config)
        self.assertTrue(run_id.startswith("ORB_"))
        self.assertTrue((run_dir / "config.json").exists())
        with closing(sqlite3.connect(self.ledger.db_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        self.assertEqual(count, 1)
        with self.ledger.csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["run_id"], run_id)
        self.assertEqual(rows[0]["experiment_id"], "orb_test_baseline")
        self.assertEqual(rows[0]["partition_name"], "DEVELOPMENT")
        self.assertEqual(rows[0]["dataset_hash"], "abc123")

    def test_run_ids_are_unique(self):
        first, _ = self.ledger.create_run(self.config)
        second, _ = self.ledger.create_run(self.config)
        self.assertNotEqual(first, second)

    def test_update_run_records_results_notes_and_artifacts(self):
        run_id, run_dir = self.ledger.create_run(self.config)
        updated = self.ledger.update_run(
            run_id, results_summary={"profit_factor": 1.4, "trades": 25},
            notes="completed", artifact_paths={"trades": run_dir / "trades.parquet"},
            status="COMPLETED", conclusion="Control reproduced.",
        )
        self.assertEqual(json.loads(updated["results_summary_json"])["trades"], 25)
        self.assertEqual(updated["notes"], "completed")
        self.assertEqual(updated["status"], "COMPLETED")
        self.assertEqual(updated["conclusion"], "Control reproduced.")
        self.assertIn("trades", json.loads(updated["artifact_paths_json"]))

    def test_missing_required_field_is_rejected(self):
        del self.config["hypothesis"]
        with self.assertRaises(ValueError):
            self.ledger.create_run(self.config)


if __name__ == "__main__":
    unittest.main()
