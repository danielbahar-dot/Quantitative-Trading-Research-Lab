import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from src.experiments.experiment_index import (
    get_experiment,
    list_artifacts,
    load_experiment_index,
    load_experiment_records,
    preview_csv,
    resolve_artifact_path,
    validate_experiment_record,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _record(experiment_id="test_experiment"):
    return {
        "experiment_id": experiment_id,
        "project_id": "test_project",
        "strategy_version": None,
        "title": "Test experiment",
        "gate": None,
        "experiment_type": "TEST",
        "hypothesis": None,
        "description": None,
        "scope": {
            "instrument_id": None,
            "universe_id": None,
            "asset_class": None,
            "timeframe": None,
            "partition": "DEVELOPMENT",
        },
        "lineage": {"parent_experiment_ids": [], "source_gates": []},
        "reproducibility": {
            "dataset_id": None,
            "data_hash": None,
            "config_path": None,
            "git_sha": None,
            "run_timestamp": None,
        },
        "status": "complete",
        "decision": "none",
        "confirmatory": False,
        "reserved_data_exposed": False,
        "summary_metrics": {},
        "artifacts": [],
    }


def _write_index(root: Path, records):
    folder = root / "experiments" / "projects" / "test_project"
    folder.mkdir(parents=True)
    (folder / "experiment_index.json").write_text(
        json.dumps({"schema_version": "0.1", "project_id": "test_project", "records": records}),
        encoding="utf-8",
    )


class ExperimentIndexTests(unittest.TestCase):
    def test_schema_validation_requires_identity_and_research_fields(self):
        valid = _record()
        self.assertEqual(validate_experiment_record(valid)["experiment_id"], "test_experiment")
        invalid = dict(valid)
        invalid.pop("decision")
        with self.assertRaisesRegex(ValueError, "decision"):
            validate_experiment_record(invalid)

    def test_real_index_loads_unique_backfilled_experiments(self):
        records = load_experiment_records(PROJECT_ROOT)
        ids = [record["experiment_id"] for record in records]
        self.assertEqual(len(records), 12)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("mnq_orb_v0_1_gate8a_post_validation_diagnostic", ids)

    def test_project_and_version_filters_are_independent(self):
        all_records = load_experiment_index(PROJECT_ROOT)
        filtered = load_experiment_index(
            PROJECT_ROOT, project_id="mnq_orb_v0_1", strategy_version="V0.1"
        )
        self.assertEqual(len(filtered), 12)
        self.assertEqual(len(filtered), len(all_records))
        self.assertTrue(filtered["project_id"].eq("mnq_orb_v0_1").all())

    def test_artifact_paths_are_repository_relative_and_resolvable(self):
        artifacts = list_artifacts("orb_gate6b_dev_fixed_target_stop", PROJECT_ROOT)
        self.assertGreater(len(artifacts), 10)
        self.assertTrue(all(not Path(item["path"]).is_absolute() for item in artifacts))
        self.assertTrue(all(resolve_artifact_path(item["path"], PROJECT_ROOT).is_file() for item in artifacts))

    def test_missing_explicit_artifact_is_retained_for_audit(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = _record()
            record["artifacts"] = [{
                "artifact_id": "missing", "type": "report",
                "title": "Missing report", "path": "reports/missing.md",
            }]
            _write_index(root, [record])
            artifact = list_artifacts("test_experiment", root)[0]
            self.assertFalse(artifact["exists"])
            self.assertIsNone(artifact["size_bytes"])

    def test_unknown_historical_metadata_remains_null(self):
        record = get_experiment("mnq_orb_v0_1_gate5_baseline", PROJECT_ROOT)
        self.assertIsNone(record["reproducibility"]["git_sha"])
        self.assertIsNone(record["reproducibility"]["run_timestamp"])

    def test_lineage_derives_children_from_parent_relationships(self):
        record = get_experiment("orb_gate6b_dev_fixed_target_stop", PROJECT_ROOT)
        self.assertIn("orb_gate6b1_dev_or_width_analysis", record["child_experiment_ids"])
        self.assertIn("orb_gate6b2_dev_ambiguity_robustness", record["child_experiment_ids"])

    def test_duplicate_experiment_records_are_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_index(root, [_record(), _record()])
            with self.assertRaisesRegex(ValueError, "Duplicate experiment IDs"):
                load_experiment_records(root)

    def test_bounded_csv_preview_never_reads_more_than_declared_shape(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "reports" / "large.csv"
            path.parent.mkdir(parents=True)
            pd.DataFrame({f"column_{index}": range(200) for index in range(60)}).to_csv(path, index=False)
            preview = preview_csv("reports/large.csv", root, max_rows=17, max_columns=11)
            self.assertEqual(preview.shape, (17, 11))

    def test_path_escape_is_rejected(self):
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "escapes"):
                resolve_artifact_path("../outside.csv", temporary)


if __name__ == "__main__":
    unittest.main()
