import unittest

import numpy as np
import pandas as pd

from src.experiments.orb_gate8a_post_validation import (
    DEV_END,
    DEV_START,
    RESEARCH_LABEL,
    VAL_END,
    VAL_START,
    _merge_width_edges,
    assert_partition,
    build_surface_comparison,
    persistence_statistics,
)


class Gate8APostValidationTests(unittest.TestCase):
    def test_partition_guard_rejects_oos_and_cross_partition_rows(self):
        valid = pd.DataFrame({"session_date": ["2025-07-01", "2025-12-31"]})
        assert_partition(valid, VAL_START, VAL_END, "VALIDATION")
        with self.assertRaisesRegex(ValueError, "outside"):
            assert_partition(pd.DataFrame({"session_date": ["2026-01-02"]}), VAL_START, VAL_END, "VALIDATION")
        with self.assertRaisesRegex(ValueError, "outside"):
            assert_partition(pd.DataFrame({"session_date": ["2025-06-30", "2025-07-01"]}), VAL_START, VAL_END, "VALIDATION")

    def test_surface_comparison_is_one_to_one_and_sign_labeled(self):
        keys = {
            "config_id": ["A", "B", "C", "D"], "or_minutes": [15] * 4,
            "breakout_type": ["PRINT"] * 4, "stop_mode": ["FIXED_40"] * 4,
            "target_points": [40.0, 50.0, 60.0, 75.0],
        }
        metric_names = [
            "average_r", "profit_factor_r", "max_drawdown_r", "ambiguity_rate",
            "entry_stop_ambiguity_rate", "executed_trades", "win_rate",
            "session_end_percentage", "positive_month_percentage",
        ]
        dev = pd.DataFrame(keys)
        val = pd.DataFrame(keys)
        for metric in metric_names:
            dev[metric] = [0.2, 0.1, -0.1, -0.2]
            val[metric] = [0.1, -0.1, 0.1, -0.1]
        chronology_rows = []
        for config_id in keys["config_id"]:
            chronology_rows.append({
                "config_id": config_id, "entry_first_avg_r": 0.1,
                "adverse_move_first_avg_r": 0.2, "chronology_range_avg_r": 0.1,
                "entry_first_pf": 1.1, "adverse_move_first_pf": 1.2,
                "all_scenarios_positive": True,
            })
        chronology = pd.DataFrame(chronology_rows)
        evidence = pd.DataFrame({
            "config_id": keys["config_id"], "neighbor_support": ["STRONG", "WEAK", "WEAK", "WEAK"],
            "supporting_target_neighbors": ["", "", "", ""],
            "supporting_stop_neighbors": ["", "", "", ""],
        })
        result = build_surface_comparison(dev, val, chronology, chronology, evidence)
        self.assertEqual(len(result), 4)
        self.assertEqual(result["research_scope"].unique().tolist(), [RESEARCH_LABEL])
        self.assertEqual(set(result["sign_persistence"]), {
            "POSITIVE_DEV_POSITIVE_VAL", "POSITIVE_DEV_NEGATIVE_VAL",
            "NEGATIVE_DEV_POSITIVE_VAL", "NEGATIVE_DEV_NEGATIVE_VAL",
        })
        stats = persistence_statistics(result)
        self.assertEqual(stats["dev_positive_cells"], 2)
        self.assertEqual(stats["dev_positive_to_val_nonpositive"], 1)

    def test_width_bucket_merging_is_value_only_and_meets_global_threshold(self):
        values = pd.Series([50.0] * 2 + [70.0] * 40 + [90.0] * 40 + [110.0] * 40 + [140.0] * 40 + [170.0] * 40 + [220.0] * 2)
        edges = _merge_width_edges(values, [60, 80, 100, 125, 150, 200], 30)
        counts = pd.cut(values, bins=edges, right=False).value_counts(sort=False)
        self.assertTrue((counts >= 30).all())
        self.assertLess(len(edges), 8)

    def test_declared_partition_boundaries_remain_frozen(self):
        self.assertEqual((DEV_START, DEV_END), (pd.Timestamp("2024-06-21"), pd.Timestamp("2025-06-30")))
        self.assertEqual((VAL_START, VAL_END), (pd.Timestamp("2025-07-01"), pd.Timestamp("2025-12-31")))


if __name__ == "__main__":
    unittest.main()

