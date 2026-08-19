import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.research_harness import ExperimentLedger


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    run_id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL,
    strategy_name TEXT NOT NULL, strategy_version TEXT NOT NULL,
    hypothesis TEXT NOT NULL, dataset TEXT NOT NULL, timeframe TEXT NOT NULL,
    session TEXT NOT NULL, parameters_json TEXT NOT NULL,
    costs_slippage_json TEXT NOT NULL, results_summary_json TEXT NOT NULL,
    notes TEXT NOT NULL, code_version TEXT NOT NULL, code_hash TEXT NOT NULL,
    artifact_paths_json TEXT NOT NULL, config_path TEXT NOT NULL
);
"""


class ExperimentLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "experiments").mkdir()
        (self.root / "experiments" / "schema.sql").write_text(SCHEMA, encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "strategy.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.ledger = ExperimentLedger(self.root)
        self.config = {
            "strategy_name": "ORB", "strategy_version": "0.1.0",
            "hypothesis": "The opening-range break has positive expectancy.",
            "dataset": "data/processed/mnq.csv", "timeframe": "1 minute",
            "session": {"timezone": "America/New_York", "start": "09:30"},
            "parameters": {"opening_range_minutes": 15},
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

    def test_run_ids_are_unique(self):
        first, _ = self.ledger.create_run(self.config)
        second, _ = self.ledger.create_run(self.config)
        self.assertNotEqual(first, second)

    def test_update_run_records_results_notes_and_artifacts(self):
        run_id, run_dir = self.ledger.create_run(self.config)
        updated = self.ledger.update_run(
            run_id, results_summary={"profit_factor": 1.4, "trades": 25},
            notes="completed", artifact_paths={"trades": run_dir / "trades.parquet"},
        )
        self.assertEqual(json.loads(updated["results_summary_json"])["trades"], 25)
        self.assertEqual(updated["notes"], "completed")
        self.assertIn("trades", json.loads(updated["artifact_paths_json"]))

    def test_missing_required_field_is_rejected(self):
        del self.config["hypothesis"]
        with self.assertRaises(ValueError):
            self.ledger.create_run(self.config)


if __name__ == "__main__":
    unittest.main()
