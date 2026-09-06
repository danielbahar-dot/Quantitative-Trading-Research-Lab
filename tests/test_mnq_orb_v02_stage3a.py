from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_stage3a import (
    ROOM_LEVEL_ORDER,
    build_stage3a_breakout_events,
)


class Stage3ARoomToNextLevelTests(unittest.TestCase):
    def test_long_uses_nearest_level_strictly_above_or_high(self):
        feature = _feature_row(
            previous_day_high=105.0,
            asia_low=102.0,
            london_high=100.0,
        )
        output, audit = _build(feature, "LONG")

        row = output.iloc[0]
        self.assertEqual(row["next_level_type"], "asia_low")
        self.assertEqual(row["next_level_price"], 102.0)
        self.assertEqual(row["room_to_next_level_points"], 2.0)
        self.assertAlmostEqual(row["room_to_next_level_pct"], 2.0 / 95.0)
        self.assertAlmostEqual(row["room_to_next_level_or_widths"], 0.2)
        self.assertFalse(row["no_level_ahead"])
        self.assertEqual(audit["unmatched_joins"], 0)

    def test_short_uses_nearest_level_strictly_below_or_low(self):
        feature = _feature_row(
            previous_day_low=85.0,
            london_high=89.0,
            ny_premarket_low=90.0,
        )
        output, _ = _build(feature, "SHORT")

        row = output.iloc[0]
        self.assertEqual(row["next_level_type"], "london_high")
        self.assertEqual(row["next_level_price"], 89.0)
        self.assertEqual(row["room_to_next_level_points"], 1.0)
        self.assertAlmostEqual(row["room_to_next_level_pct"], 1.0 / 95.0)
        self.assertAlmostEqual(row["room_to_next_level_or_widths"], 0.1)

    def test_no_level_ahead_sets_null_fields(self):
        feature = _feature_row(previous_day_high=100.0, asia_high=99.0)
        output, audit = _build(feature, "LONG")

        row = output.iloc[0]
        self.assertTrue(row["no_level_ahead"])
        self.assertIsNone(row["next_level_type"])
        self.assertTrue(pd.isna(row["next_level_price"]))
        self.assertTrue(pd.isna(row["room_to_next_level_points"]))
        self.assertTrue(pd.isna(row["room_to_next_level_pct"]))
        self.assertTrue(pd.isna(row["room_to_next_level_or_widths"]))
        self.assertEqual(audit["no_level_ahead_count"], 1)

    def test_equal_price_uses_documented_source_order(self):
        feature = _feature_row(previous_day_low=104.0, overnight_high=104.0)
        output, _ = _build(feature, "LONG")

        self.assertEqual(ROOM_LEVEL_ORDER[1:3], ("previous_day_low", "overnight_high"))
        self.assertEqual(output.iloc[0]["next_level_type"], "previous_day_low")

    def test_future_level_columns_are_not_candidates(self):
        feature = _feature_row(previous_day_high=105.0)
        feature["current_session_high"] = 100.25
        feature["post_signal_bar_high"] = 100.5
        output, _ = _build(feature, "LONG")

        row = output.iloc[0]
        self.assertEqual(row["next_level_type"], "previous_day_high")
        self.assertEqual(row["next_level_price"], 105.0)
        self.assertIn("current_session_high", output.columns)
        self.assertIn("post_signal_bar_high", output.columns)


def _feature_row(**levels: float) -> pd.DataFrame:
    row: dict[str, object] = {
        "session_date": "2024-06-24",
        "contract": "MNQ 09-24",
        "or_minutes": 15,
        "or_high": 100.0,
        "or_low": 90.0,
        "or_mid": 95.0,
        "or_width_points": 10.0,
    }
    for level_name in ROOM_LEVEL_ORDER:
        row[level_name] = levels.get(level_name, np.nan)
        row[f"level_{level_name}_available"] = level_name in levels
    return pd.DataFrame([row])


def _build(feature: pd.DataFrame, direction: str):
    outcomes = pd.DataFrame(
        [
            {
                "session_date": "2024-06-24",
                "contract": "MNQ 09-24",
                "or_minutes": 15,
                "breakout_type": "PRINT",
                "breakout_direction": direction,
                "breakout_timestamp": "2024-06-24 10:01:00-04:00",
                "breakout_price": 100.25 if direction == "LONG" else 89.75,
            }
        ]
    )
    return build_stage3a_breakout_events(feature, outcomes)


if __name__ == "__main__":
    unittest.main()
