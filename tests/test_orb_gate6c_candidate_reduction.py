import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.experiments.orb_gate6c_candidate_reduction import (
    CORE_CLASS,
    HYPOTHESIS_CLASS,
    _supports,
    build_shortlist,
    calculate_width_descriptors,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "experiments" / "orb_gate6c_dev_candidate_reduction.json"


def _thresholds() -> dict:
    return {
        "width_stable_avg_r_range": 0.35,
        "width_warning_avg_r_range": 0.50,
        "width_top_two_positive_r_share_warning": 0.70,
    }


def _width_rows(config_id: str, values: list[float], warning: str = "") -> list[dict]:
    return [
        {
            "config_id": config_id,
            "or_width_quintile": index,
            "average_r": value,
            "total_r": value * 40,
            "sample_warning": warning,
        }
        for index, value in enumerate(values, start=1)
    ]


class Gate6CCandidateReductionTests(unittest.TestCase):
    def test_config_freezes_only_the_existing_75_cell_universe(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        universe = config["candidate_universe"]
        self.assertEqual(universe["or_minutes"], [15, 20, 30])
        self.assertEqual(universe["breakout_type"], "PRINT")
        self.assertEqual(universe["expected_configurations"], 75)
        self.assertEqual(universe["target_points"], [40.0, 50.0, 60.0, 75.0, 100.0])
        self.assertEqual(len(config["proposed_core_candidates"]), 3)
        self.assertEqual(len(config["proposed_research_hypotheses"]), 2)
        self.assertEqual(config["freeze_status"], "FROZEN_FOR_VALIDATION")
        self.assertFalse(config["constraints"]["inspect_validation"])
        self.assertFalse(config["constraints"]["inspect_oos_burned"])

    def test_width_descriptors_surface_stable_hump_and_u_shapes(self):
        rows = []
        rows.extend(_width_rows("stable", [0.10, 0.15, 0.20, 0.18, 0.12]))
        rows.extend(_width_rows("hump", [-0.20, 0.70, 0.80, 0.60, -0.10]))
        rows.extend(_width_rows("u", [0.70, 0.10, 0.00, 0.15, 0.80]))
        result = calculate_width_descriptors(pd.DataFrame(rows), _thresholds()).set_index("config_id")
        self.assertEqual(result.loc["stable", "or_width_dependency"], "RELATIVELY_STABLE")
        self.assertTrue(result.loc["hump", "or_width_dependency"].startswith("HUMP_SHAPED"))
        self.assertTrue(result.loc["u", "or_width_dependency"].startswith("U_SHAPED"))
        self.assertFalse(bool(result.loc["stable", "width_dependence_warning"]))
        self.assertTrue(bool(result.loc["hump", "width_extreme_weakness"]))

    def test_neighbor_support_requires_robust_and_similar_entry_first_result(self):
        current = SimpleNamespace(entry_first_avg_r=0.20)
        robust_close = SimpleNamespace(
            all_scenarios_positive=True,
            all_scenarios_pf_above_1=True,
            entry_first_avg_r=0.30,
        )
        robust_far = SimpleNamespace(
            all_scenarios_positive=True,
            all_scenarios_pf_above_1=True,
            entry_first_avg_r=0.40,
        )
        fragile = SimpleNamespace(
            all_scenarios_positive=False,
            all_scenarios_pf_above_1=False,
            entry_first_avg_r=0.20,
        )
        self.assertTrue(_supports(robust_close, current, 0.15))
        self.assertFalse(_supports(robust_far, current, 0.15))
        self.assertFalse(_supports(fragile, current, 0.15))

    def test_shortlist_enforces_stable_ids_and_required_sizes(self):
        evidence = pd.DataFrame([
            {"stable_candidate_id": f"CAND_{index}", "candidate_class": CORE_CLASS,
             "config_id": f"core_{index}"}
            for index in range(3)
        ] + [
            {"stable_candidate_id": f"HYP_{index}", "candidate_class": HYPOTHESIS_CLASS,
             "config_id": f"hyp_{index}"}
            for index in range(2)
        ])
        shortlist = build_shortlist(evidence)
        self.assertEqual(len(shortlist), 5)
        self.assertEqual((shortlist["candidate_class"] == CORE_CLASS).sum(), 3)
        self.assertEqual((shortlist["candidate_class"] == HYPOTHESIS_CLASS).sum(), 2)


if __name__ == "__main__":
    unittest.main()
