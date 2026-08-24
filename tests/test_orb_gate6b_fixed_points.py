import unittest

import pandas as pd

from src.backtesting.completed_trades import AMBIGUOUS_ENTRY_STOP, simulate_completed_trades
from src.experiments.orb_gate6b_fixed_points import (
    EXPECTED_CONFIGURATIONS,
    build_gate6b_candidates,
    configuration_grid,
)


def prices(low=69.0) -> pd.DataFrame:
    index = pd.date_range("2025-06-20 09:46", periods=2, freq="min", tz="America/New_York")
    return pd.DataFrame({
        "session_date": pd.Timestamp("2025-06-20").date(),
        "contract": "MNQ TEST", "open": [99.0, 101.0],
        "high": [101.0, 145.0], "low": [low, 99.0], "close": [100.0, 140.0],
    }, index=index)


def signal(direction="LONG") -> pd.DataFrame:
    return pd.DataFrame({
        "session_date": [pd.Timestamp("2025-06-20").date()],
        "direction": [direction], "breakout_type": ["PRINT"],
        "signal_time": [pd.Timestamp("2025-06-20 09:46", tz="America/New_York")],
        "or_high": [100.0], "or_low": [80.0], "or_mid": [90.0],
        "ambiguity_status": [False],
    })


class Gate6BFixedPointTests(unittest.TestCase):
    def test_grid_is_exactly_75_unique_cells_without_10m(self):
        grid = configuration_grid()
        self.assertEqual(len(grid), EXPECTED_CONFIGURATIONS)
        self.assertFalse(grid["config_id"].duplicated().any())
        self.assertEqual(set(grid["or_minutes"]), {15, 20, 30})
        self.assertNotIn(10, set(grid["or_minutes"]))

    def test_fixed_target_and_fixed_stop_are_exact(self):
        candidate = build_gate6b_candidates(
            prices(), signal(), or_minutes=15,
            stop_mode="FIXED_30", target_points=40.0,
        ).iloc[0]
        self.assertEqual(candidate["entry_price"], 100.0)
        self.assertEqual(candidate["initial_stop"], 70.0)
        self.assertEqual(candidate["initial_target"], 140.0)
        self.assertEqual(candidate["initial_risk_points"], 30.0)
        self.assertAlmostEqual(candidate["initial_reward_risk"], 4 / 3)
        self.assertEqual(candidate["or_width_points"], 20.0)
        self.assertEqual(candidate["target_to_or_ratio"], 2.0)
        self.assertEqual(candidate["stop_to_or_ratio"], 1.5)

    def test_midpoint_and_25pct_stops_are_directionally_correct(self):
        midpoint = build_gate6b_candidates(
            prices(), signal(), or_minutes=15,
            stop_mode="OR_MIDPOINT", target_points=40.0,
        ).iloc[0]
        retracement = build_gate6b_candidates(
            prices(), signal(), or_minutes=15,
            stop_mode="OR_25_RETRACEMENT", target_points=40.0,
        ).iloc[0]
        self.assertEqual(midpoint["initial_stop"], 90.0)
        self.assertEqual(retracement["initial_stop"], 95.0)

    def test_entry_stop_ambiguity_applies_to_fixed_stop(self):
        candidates = build_gate6b_candidates(
            prices(low=69.0), signal(), or_minutes=15,
            stop_mode="FIXED_30", target_points=40.0,
        )
        completed = simulate_completed_trades(prices(low=69.0), candidates)
        self.assertEqual(completed.iloc[0]["exit_reason"], AMBIGUOUS_ENTRY_STOP)
        self.assertTrue(bool(completed.iloc[0]["excluded_from_performance"]))


if __name__ == "__main__":
    unittest.main()
