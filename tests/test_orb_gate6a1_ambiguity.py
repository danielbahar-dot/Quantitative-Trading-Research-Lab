import unittest

import pandas as pd

from src.backtesting.candidate_entries import build_candidate_entries
from src.backtesting.completed_trades import AMBIGUOUS_ENTRY_STOP, simulate_completed_trades
from src.backtesting.session_trade_limit import SESSION_TRADE_LIMIT, apply_session_trade_limit
from src.experiments.orb_gate6a1_ambiguity import (
    EXPECTED_CONFIGURATIONS,
    EXPECTED_SCENARIO_ROWS,
    OR_DURATIONS,
    SCENARIOS,
    TARGET_R_VALUES,
    resolve_optimistic,
    resolve_pessimistic,
)


def prices() -> pd.DataFrame:
    index = pd.date_range("2025-06-20 09:41", periods=4, freq="min", tz="America/New_York")
    return pd.DataFrame({
        "session_date": pd.Timestamp("2025-06-20").date(),
        "contract": "MNQ TEST",
        "open": [99.0, 100.0, 100.0, 101.0],
        "high": [101.0, 101.0, 103.0, 102.0],
        "low": [97.0, 98.0, 99.0, 100.0],
        "close": [100.0, 100.0, 102.0, 101.0],
    }, index=index)


def signals() -> pd.DataFrame:
    timestamp = pd.Timestamp("2025-06-20 09:41", tz="America/New_York")
    return pd.DataFrame({
        "session_date": [pd.Timestamp("2025-06-20").date()],
        "direction": ["LONG"], "breakout_type": ["PRINT"],
        "signal_time": [timestamp], "or_high": [100.0], "or_low": [90.0],
        "or_mid": [95.0], "ambiguity_status": [False],
    })


class Gate6A1AmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.candidates = build_candidate_entries(
            prices(), signals(), or_minutes=10, stop_fraction=0.25, target_r=1.0
        )
        self.observed = simulate_completed_trades(prices(), self.candidates)
        self.assertEqual(self.observed.iloc[0]["exit_reason"], AMBIGUOUS_ENTRY_STOP)

    def test_grid_dimensions_are_exactly_20_cells_and_60_rows(self):
        self.assertEqual(len(OR_DURATIONS) * len(TARGET_R_VALUES), EXPECTED_CONFIGURATIONS)
        self.assertEqual(EXPECTED_CONFIGURATIONS * len(SCENARIOS), EXPECTED_SCENARIO_ROWS)

    def test_pessimistic_resolution_is_executed_minus_one_r(self):
        resolved = resolve_pessimistic(self.observed)
        trade = resolved.iloc[0]
        self.assertFalse(bool(trade["ambiguous"]))
        self.assertFalse(bool(trade["excluded_from_performance"]))
        self.assertEqual(trade["result_r"], -1.0)
        self.assertEqual(trade["exit_price"], trade["initial_stop"])

    def test_optimistic_resolution_skips_entry_bar(self):
        resolved = resolve_optimistic(prices(), self.candidates, self.observed)
        trade = resolved.iloc[0]
        self.assertEqual(trade["exit_reason"], "TARGET")
        self.assertEqual(
            trade["exit_time"],
            pd.Timestamp("2025-06-20 09:43", tz="America/New_York"),
        )
        self.assertEqual(trade["result_r"], 1.0)

    def test_resolved_first_candidate_consumes_daily_allowance(self):
        later = self.candidates.copy()
        later["direction"] = "SHORT"
        later["signal_time"] = later["signal_time"] + pd.Timedelta(minutes=2)
        later["entry_time"] = later["entry_time"] + pd.Timedelta(minutes=2)
        later["entry_price"] = 90.0
        later["initial_stop"] = 92.5
        later["initial_target"] = 87.5
        later["risk_points"] = 2.5
        combined_candidates = pd.concat([self.candidates, later], ignore_index=True)
        later_trade = resolve_pessimistic(self.observed).copy()
        later_trade["direction"] = "SHORT"
        later_trade["signal_time"] = later["signal_time"].iloc[0]
        later_trade["entry_time"] = later["entry_time"].iloc[0]
        later_trade["trade_id"] = "later"
        combined_completed = pd.concat(
            [resolve_pessimistic(self.observed), later_trade], ignore_index=True
        )
        executed, audit = apply_session_trade_limit(combined_candidates, combined_completed)
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed.iloc[0]["direction"], "LONG")
        self.assertEqual(audit.iloc[1]["rejection_reason"], SESSION_TRADE_LIMIT)


if __name__ == "__main__":
    unittest.main()
