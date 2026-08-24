import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.experiments.orb_gate6b2_ambiguity_robustness import SCENARIOS
from src.experiments.orb_gate7_validation import (
    APPROVED_CANDIDATES,
    APPROVED_IDS,
    build_partition_or_levels,
    classify_degradation,
    classify_edge,
    classify_observability,
    classify_overall,
    temporal_consistency,
    validate_frozen_contract,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "validation" / "gate7_validation_protocol.json"
SPEC = ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "freeze" / "dev_candidate_freeze" / "mnq_orb_v0_1_validation_candidates.json"


class Gate7ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        cls.spec = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_exact_three_frozen_candidates_and_no_hypotheses(self):
        self.assertEqual(len(APPROVED_CANDIDATES), 3)
        self.assertEqual(APPROVED_IDS, (
            "MNQ_ORB_V01_CAND_001", "MNQ_ORB_V01_CAND_002", "MNQ_ORB_V01_CAND_003"
        ))
        self.assertEqual({item["or_minutes"] for item in APPROVED_CANDIDATES}, {15, 20, 30})
        self.assertEqual({item["target_points"] for item in APPROVED_CANDIDATES}, {75.0})
        self.assertEqual(set(self.protocol["explicitly_excluded_ids"]), {
            "MNQ_ORB_V01_HYP_001", "MNQ_ORB_V01_HYP_002"
        })
        validate_frozen_contract(self.spec, self.protocol)

    def test_protocol_predeclares_gate6b2_chronology_and_decisions(self):
        self.assertEqual(tuple(self.protocol["chronology_scenarios"]), SCENARIOS)
        self.assertEqual(self.protocol["status"], "PREDECLARED_LOCKED")
        self.assertTrue(self.protocol["created_before_validation_access"])
        self.assertIn("PASS", self.protocol["decision_framework"]["overall"])
        self.assertIn("REVISE", self.protocol["decision_framework"]["overall"])
        self.assertIn("REJECT", self.protocol["decision_framework"]["overall"])

    def test_degradation_bands_are_exact(self):
        self.assertEqual(classify_degradation(0.15, 0.20), "LOW")
        self.assertEqual(classify_degradation(0.10, 0.20), "MODERATE")
        self.assertEqual(classify_degradation(0.05, 0.20), "HIGH")
        self.assertEqual(classify_degradation(0.0, 0.20), "SIGN_REVERSAL")

    def test_temporal_rule_is_predeclared_and_deterministic(self):
        broad = pd.DataFrame({"total_r": [2.0, 1.0, -0.5, 1.5, -0.25, 1.0]})
        concentrated = pd.DataFrame({"total_r": [8.0, -1.0, -1.0, 0.5, 0.25, 0.25]})
        unstable = pd.DataFrame({"total_r": [3.0, 2.0, 1.0, -1.0, -1.0, -2.0]})
        self.assertEqual(temporal_consistency(broad)["temporal_consistency"], "BROAD")
        self.assertEqual(temporal_consistency(concentrated)["temporal_consistency"], "CONCENTRATED")
        self.assertEqual(temporal_consistency(unstable)["temporal_consistency"], "UNSTABLE")

    def test_edge_observability_and_overall_rules(self):
        edge, borderline = classify_edge(0.20, 1.3, 0.10, 1.2, self.protocol)
        self.assertEqual(edge, "STRONG")
        self.assertFalse(borderline)
        mixed, borderline = classify_edge(0.20, 1.3, 0.01, 1.02, self.protocol)
        self.assertEqual(mixed, "MIXED")
        self.assertTrue(borderline)
        chrono = SimpleNamespace(
            entry_first_avg_r=0.10, entry_first_pf=1.2,
            all_scenarios_positive=True, all_scenarios_pf_above_1=True,
            chronology_range_avg_r=0.05,
        )
        observability = classify_observability(
            chrono, val_ambiguity=0.06, dev_ambiguity=0.05,
            dev_chronology_range=0.04, protocol=self.protocol,
        )
        self.assertEqual(observability, "STRONG")
        self.assertEqual(classify_overall("STRONG", "LOW", "BROAD", "STRONG"), "PASS")
        self.assertEqual(classify_overall("MIXED", "LOW", "BROAD", "STRONG"), "REVISE")
        self.assertEqual(classify_overall("FAILED", "SIGN_REVERSAL", "UNSTABLE", "FAILED"), "REJECT")

    def test_partition_or_features_use_exact_nt8_bar_end_windows(self):
        index = pd.date_range("2025-07-01 09:31", "2025-07-01 10:00", freq="min", tz="America/New_York")
        prices = pd.DataFrame({
            "session_date": [pd.Timestamp("2025-07-01").date()] * len(index),
            "contract": ["MNQ TEST"] * len(index),
            "high": range(100, 100 + len(index)),
            "low": range(90, 90 + len(index)),
        }, index=index)
        levels = build_partition_or_levels(prices).set_index("or_minutes")
        self.assertTrue(levels["valid_or"].all())
        self.assertEqual(levels.loc[15, "or_high"], 114)
        self.assertEqual(levels.loc[20, "or_high"], 119)
        self.assertEqual(levels.loc[30, "or_high"], 129)


if __name__ == "__main__":
    unittest.main()
