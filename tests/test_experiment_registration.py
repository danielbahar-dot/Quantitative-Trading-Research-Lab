import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.experiments.experiment_index import (
    get_experiment,
    list_artifacts,
    load_experiment_index,
    validate_experiment_record,
)
from src.experiments.experiment_registration import (
    create_experiment,
    finalize_experiment,
    refresh_experiment_index,
)
from src.visualization.research_dashboard import filter_experiment_index


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parent_record():
    return {
        "experiment_id": "parent_experiment",
        "project_id": "test_project",
        "strategy_id": "test_strategy",
        "strategy_version": "V0.1",
        "research_stage": "STAGE_0_IDEA",
        "title": "Parent experiment",
        "gate": None,
        "experiment_type": "IDEA",
        "hypothesis": "Parent hypothesis",
        "description": "Test parent",
        "scope": {
            "instrument_id": "TEST",
            "universe_id": None,
            "asset_class": "test",
            "timeframe": "1 minute",
            "partition": "NOT_APPLICABLE",
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
        "decision": "continue",
        "confirmatory": False,
        "reserved_data_exposed": False,
        "summary_metrics": {},
        "artifacts": [],
    }


class ExperimentRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        schema = self.root / "experiments" / "schema"
        project = self.root / "experiments" / "projects" / "test_project"
        schema.mkdir(parents=True)
        project.mkdir(parents=True)
        (schema / "research_lifecycle_v1.json").write_text(
            (PROJECT_ROOT / "experiments" / "schema" / "research_lifecycle_v1.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (schema / "experiment_record.schema.json").write_text(
            (PROJECT_ROOT / "experiments" / "schema" / "experiment_record.schema.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (project / "project.json").write_text(json.dumps({
            "project_id": "test_project",
            "project_name": "Test Project",
            "strategy_versions": [{"strategy_version": "V0.2"}],
        }), encoding="utf-8")
        (project / "experiment_index.json").write_text(json.dumps({
            "schema_version": "1.0",
            "project_id": "test_project",
            "records": [_parent_record()],
        }), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def _create(self, experiment_id="automatic_experiment", **overrides):
        values = {
            "experiment_id": experiment_id,
            "project_id": "test_project",
            "strategy_id": "test_strategy",
            "strategy_version": "V0.2",
            "research_stage": "STAGE_6_EXPLORATION",
            "title": "Automatic experiment",
            "experiment_type": "PARAMETER_SURFACE",
            "partition": "DEVELOPMENT",
            "confirmatory": False,
            "reserved_data_exposed": False,
            "hypothesis": "Automatic registration preserves provenance.",
            "description": "Temporary test experiment.",
            "parent_experiment_ids": ["parent_experiment"],
            "source_gates": ["TEST"],
            "dataset_id": "test_dataset",
            "dataset_version": "v1",
            "instrument_id": "TEST",
            "asset_class": "test",
            "timeframe": "1 minute",
            "project_root": self.root,
        }
        values.update(overrides)
        return create_experiment(**values)

    def _artifact(self, run, *, artifact_id="summary", required=True, exists=True):
        path = self.root / "reports" / f"{artifact_id}.csv"
        if exists:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("metric,value\naverage_r,0.1\n", encoding="utf-8")
        return run.register_artifact(
            artifact_id=artifact_id,
            artifact_type="custom_summary_bundle",
            title="Summary output",
            path=path,
            description="Canonical temporary output",
            category="data",
            metadata={"rows": 1},
            required=required,
        )

    def test_create_valid_experiment_and_schema_validation(self):
        run = self._create()
        record = run.record
        self.assertEqual(validate_experiment_record(record)["status"], "running")
        self.assertEqual(record["registration"]["api_version"], "1.0")
        self.assertIn("working_tree_dirty", record["reproducibility"])

    def test_schema_validation_rejects_unknown_lifecycle_stage(self):
        with self.assertRaisesRegex(ValueError, "Unsupported research stage"):
            self._create(research_stage="STAGE_99_UNKNOWN")

    def test_duplicate_experiment_id_is_rejected(self):
        self._create()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self._create()

    def test_artifact_registration_uses_canonical_path_and_extensible_type(self):
        run = self._create()
        artifact = self._artifact(run)
        self.assertEqual(artifact["path"], "reports/summary.csv")
        self.assertEqual(artifact["type"], "custom_summary_bundle")
        self.assertEqual(run.record["artifacts"][0]["metadata"], {"rows": 1})

    def test_missing_required_artifact_blocks_finalization(self):
        run = self._create()
        self._artifact(run, exists=False)
        with self.assertRaisesRegex(FileNotFoundError, "Required experiment artifact"):
            run.finalize()
        self.assertEqual(run.record["status"], "running")

    def test_artifact_and_index_updates_are_idempotent(self):
        run = self._create()
        self._artifact(run)
        self._artifact(run)
        refresh_experiment_index("test_project", self.root)
        refresh_experiment_index("test_project", self.root)
        self.assertEqual(len(run.record["artifacts"]), 1)
        index = load_experiment_index(self.root)
        self.assertEqual(index["experiment_id"].tolist().count(run.experiment_id), 1)

    def test_mutable_field_update_merges_metrics_and_runtime(self):
        run = self._create()
        run.update(notes="running", summary_metrics={"trades": 10}, runtime_metadata={"seconds": 2.5})
        run.update(summary_metrics={"average_r": 0.1}, decision="continue")
        record = run.record
        self.assertEqual(record["summary_metrics"], {"trades": 10, "average_r": 0.1})
        self.assertEqual(record["runtime_metadata"]["seconds"], 2.5)
        self.assertEqual(record["decision"], "continue")

    def test_immutable_identity_and_provenance_fields_are_protected(self):
        run = self._create()
        with self.assertRaisesRegex(ValueError, "Immutable"):
            run.update(project_id="another_project")
        with self.assertRaisesRegex(ValueError, "Immutable"):
            run.update(reproducibility={"git_sha": "changed"})

    def test_successful_finalization_persists_completion_and_metrics(self):
        run = self._create()
        self._artifact(run)
        completed = run.finalize(summary_metrics={"trades": 10}, decision="continue")
        self.assertEqual(completed["status"], "complete")
        self.assertIsNotNone(completed["completed_at"])
        self.assertIn("final_git_sha", completed["reproducibility"])
        self.assertIn("final_working_tree_dirty", completed["reproducibility"])
        indexed = get_experiment(run.experiment_id, self.root)
        self.assertEqual(indexed["summary_metrics"]["trades"], 10)

    def test_context_manager_failure_is_recorded_and_exception_propagates(self):
        run = self._create(experiment_id="failed_experiment")
        with self.assertRaisesRegex(RuntimeError, "intentional failure"):
            with run:
                self._artifact(run, artifact_id="partial")
                raise RuntimeError("intentional failure")
        record = run.record
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["failure"]["type"], "RuntimeError")
        self.assertIn("intentional failure", record["failure"]["message"])
        self.assertEqual(len(record["artifacts"]), 1)

    def test_creation_automatically_refreshes_the_existing_index(self):
        run = self._create()
        index = load_experiment_index(self.root)
        row = index.loc[index["experiment_id"].eq(run.experiment_id)].iloc[0]
        self.assertEqual(row.status, "running")

    def test_dashboard_discovery_includes_finalized_artifact(self):
        run = self._create()
        self._artifact(run)
        run.finalize(decision="continue")
        index = filter_experiment_index(load_experiment_index(self.root), status="complete")
        row = index.loc[index["experiment_id"].eq(run.experiment_id)].iloc[0]
        self.assertEqual(row.artifact_count, 1)
        self.assertTrue(list_artifacts(run.experiment_id, self.root)[0]["exists"])

    def test_project_and_strategy_version_filters_find_registered_run(self):
        run = self._create()
        index = load_experiment_index(
            self.root, project_id="test_project", strategy_version="V0.2"
        )
        self.assertEqual(index["experiment_id"].tolist(), [run.experiment_id])

    def test_lifecycle_stage_is_preserved_in_index(self):
        run = self._create(research_stage="STAGE_7_ROBUSTNESS")
        row = load_experiment_index(self.root).loc[
            lambda frame: frame["experiment_id"].eq(run.experiment_id)
        ].iloc[0]
        self.assertEqual(row.research_stage, "STAGE_7_ROBUSTNESS")
        self.assertEqual(row.stage_order, 7)

    def test_parent_lineage_is_preserved_and_child_is_derived(self):
        run = self._create()
        child = get_experiment(run.experiment_id, self.root)
        parent = get_experiment("parent_experiment", self.root)
        self.assertEqual(child["lineage"]["parent_experiment_ids"], ["parent_experiment"])
        self.assertIn(run.experiment_id, parent["child_experiment_ids"])

    def test_optional_missing_artifact_does_not_impose_a_global_artifact_rule(self):
        run = self._create()
        self._artifact(run, required=False, exists=False)
        completed = finalize_experiment(run.experiment_id, project_root=self.root)
        self.assertEqual(completed["status"], "complete")


if __name__ == "__main__":
    unittest.main()
