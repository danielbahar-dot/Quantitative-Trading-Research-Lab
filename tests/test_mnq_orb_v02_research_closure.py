from __future__ import annotations

import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2"


class MNQORBV02ResearchClosureTests(unittest.TestCase):
    def test_final_note_records_parked_unvalidated_scope(self):
        path = PROJECT_DIR / "notes" / "mnq_orb_v0_2_final_development_research_conclusion.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn("MNQ ORB V0.2 — Final DEVELOPMENT Research Conclusion", text)
        self.assertIn("PARKED_AS_RESEARCH_CANDIDATE", text)
        self.assertIn("POTENTIALLY_INFORMATIVE", text)
        self.assertIn("UNVALIDATED", text)
        self.assertIn("post-hoc optimization", text)
        self.assertIn("15m/20m/30m", text)

    def test_stage3c_record_is_complete_and_all_artifacts_exist(self):
        record = _record("mnq_orb_v0_2_stage3c_combined_state_hypothesis")
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["scope"]["partition"], "DEVELOPMENT")
        self.assertEqual(record["decision"], "revise")
        self.assertFalse(record["reserved_data_exposed"])
        self.assertFalse(record["summary_metrics"]["hypothesis_validated"])
        self.assertEqual(
            record["summary_metrics"]["hypothesis_classification"],
            "POTENTIALLY_INFORMATIVE",
        )
        for artifact in record["artifacts"]:
            if artifact.get("required", True):
                self.assertTrue((PROJECT_ROOT / artifact["path"]).is_file())

    def test_stage3a_ledger_is_closed_with_conclusion_registered(self):
        record = _record("mnq_orb_v0_2_stage3a_conditional_state_characterization")
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["decision"], "revise")
        self.assertTrue(record["summary_metrics"]["research_cycle_closed"])
        self.assertEqual(
            record["summary_metrics"]["five_session_result_status"],
            "POST_HOC_OBSERVATION_NOT_SELECTED",
        )
        artifacts = {item["artifact_id"]: item for item in record["artifacts"]}
        self.assertIn("final_development_research_conclusion", artifacts)

    def test_project_manifest_is_parked_without_next_phase_approval(self):
        project = json.loads((PROJECT_DIR / "project.json").read_text(encoding="utf-8"))
        version = project["strategy_versions"][0]
        self.assertEqual(version["lifecycle_status"], "RESEARCH_PARKED")
        self.assertEqual(version["current_research_stage"], "STAGE_3_SIGNALS")
        self.assertFalse(version["approved_for_next_phase"])
        self.assertIn("PARKED_AS_RESEARCH_CANDIDATE", version["decision"])


def _record(experiment_id: str):
    path = PROJECT_DIR / "records" / f"{experiment_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
