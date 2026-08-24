import unittest

import numpy as np
import pandas as pd

from src.backtesting.candidate_entries import CANDIDATE_COLUMNS
from src.backtesting.completed_trades import AMBIGUOUS_ENTRY_STOP, STOP, TARGET
from src.backtesting.session_trade_limit import SESSION_TRADE_LIMIT, apply_session_trade_limit
from src.experiments.orb_gate6a1_ambiguity import _simulate_after_entry_bar
from src.experiments.orb_gate6b2_ambiguity_robustness import (
    EXPECTED_CONFIGURATIONS,
    EXPECTED_SCENARIO_ROWS,
    SCENARIOS,
    _entry_first_trade,
    add_robustness_descriptors,
)


def _candidate(direction: str, minute: int, entry: float, stop: float, target: float) -> dict:
    timestamp = pd.Timestamp(f"2025-06-20 09:{minute:02d}", tz="America/New_York")
    risk = abs(entry - stop)
    row = {
        "session_date": pd.Timestamp("2025-06-20").date(), "contract": "MNQ TEST",
        "direction": direction, "or_minutes": 15, "breakout_type": "PRINT",
        "signal_time": timestamp, "entry_time": timestamp, "entry_price": entry,
        "entry_bar_open": entry, "entry_bar_high": max(entry, stop, target),
        "entry_bar_low": min(entry, stop, target), "entry_bar_close": entry,
        "or_high": 100.0, "or_low": 90.0, "or_mid": 95.0,
        "initial_stop": stop, "risk_points": risk, "initial_target": target,
        "candidate_validity": True, "invalid_reason": "",
    }
    return {column: row[column] for column in CANDIDATE_COLUMNS}


def _selection(candidate: dict, reason: str, ambiguous: bool, excluded: bool) -> dict:
    return {
        "trade_id": f"trade_{candidate['direction']}",
        "session_date": candidate["session_date"], "or_minutes": candidate["or_minutes"],
        "breakout_type": candidate["breakout_type"], "direction": candidate["direction"],
        "signal_time": candidate["signal_time"], "entry_time": candidate["entry_time"],
        "exit_reason": reason, "ambiguity_reason": reason if ambiguous else "",
        "ambiguous": ambiguous, "excluded_from_performance": excluded,
    }


class Gate6B2AmbiguityRobustnessTests(unittest.TestCase):
    def test_grid_has_75_configurations_and_225_scenario_rows(self):
        self.assertEqual(EXPECTED_CONFIGURATIONS, 75)
        self.assertEqual(SCENARIOS, ("EXCLUDED", "ENTRY_FIRST", "ADVERSE_MOVE_FIRST"))
        self.assertEqual(EXPECTED_SCENARIO_ROWS, 225)

    def test_entry_first_is_immediate_minus_one_r(self):
        candidate = pd.Series(_candidate("LONG", 46, 100.0, 97.5, 105.0))
        trade = _entry_first_trade(candidate)
        self.assertEqual(trade["exit_reason"], STOP)
        self.assertEqual(trade["exit_price"], 97.5)
        self.assertEqual(trade["result_r"], -1.0)
        self.assertEqual(trade["holding_minutes"], 0)
        self.assertFalse(trade["excluded_from_performance"])

    def test_resolved_first_candidate_consumes_session_allowance(self):
        first = _candidate("LONG", 46, 100.0, 97.5, 105.0)
        later = _candidate("SHORT", 55, 90.0, 92.5, 85.0)
        candidates = pd.DataFrame([first, later], columns=CANDIDATE_COLUMNS)
        excluded_completed = pd.DataFrame([
            _selection(first, AMBIGUOUS_ENTRY_STOP, True, True),
            _selection(later, TARGET, False, False),
        ])
        excluded, _ = apply_session_trade_limit(candidates, excluded_completed)
        self.assertEqual(excluded.iloc[0]["direction"], "SHORT")

        entry_first = excluded_completed.copy()
        entry_first.loc[0, ["exit_reason", "ambiguity_reason"]] = [STOP, ""]
        entry_first.loc[0, ["ambiguous", "excluded_from_performance"]] = [False, False]
        selected, audit = apply_session_trade_limit(candidates, entry_first)
        self.assertEqual(selected.iloc[0]["direction"], "LONG")
        later_audit = audit.loc[audit["direction"].eq("SHORT")].iloc[0]
        self.assertEqual(later_audit["rejection_reason"], SESSION_TRADE_LIMIT)

        adverse_move_first = excluded_completed.copy()
        adverse_move_first.loc[0, ["exit_reason", "ambiguity_reason"]] = [
            "ADVERSE_MOVE_FIRST_ENTRY_ACCEPTED", "",
        ]
        adverse_move_first.loc[0, ["ambiguous", "excluded_from_performance"]] = [False, False]
        selected, audit = apply_session_trade_limit(candidates, adverse_move_first)
        self.assertEqual(selected.iloc[0]["direction"], "LONG")
        later_audit = audit.loc[audit["direction"].eq("SHORT")].iloc[0]
        self.assertEqual(later_audit["rejection_reason"], SESSION_TRADE_LIMIT)

    def test_adverse_move_first_starts_on_following_bar(self):
        first = _candidate("LONG", 46, 100.0, 97.5, 105.0)
        candidate = pd.Series(first)
        index = pd.date_range("2025-06-20 09:46", periods=3, freq="min", tz="America/New_York")
        prices = pd.DataFrame({
            "open": [100.0, 100.0, 104.0], "high": [106.0, 104.0, 106.0],
            "low": [97.0, 99.0, 103.0], "close": [101.0, 103.0, 105.0],
        }, index=index)
        trade = _simulate_after_entry_bar(prices, candidate, pd.Timestamp("16:00").time())
        self.assertEqual(trade["exit_time"], index[2])
        self.assertEqual(trade["exit_reason"], TARGET)
        self.assertEqual(trade["result_r"], 2.0)

    def test_chronology_range_uses_max_minus_min(self):
        rows = []
        for scenario, avg_r, pf in (
            ("EXCLUDED", 0.2, 1.2), ("ENTRY_FIRST", -0.1, 0.9),
            ("ADVERSE_MOVE_FIRST", 0.1, 1.1),
        ):
            rows.append({"config_id": "one", "scenario": scenario, "average_r": avg_r, "profit_factor_r": pf})
        result = add_robustness_descriptors(pd.DataFrame(rows)).iloc[0]
        self.assertAlmostEqual(result["chronology_range_avg_r"], 0.3)
        self.assertFalse(bool(result["entry_first_positive"]))
        self.assertFalse(bool(result["all_scenarios_positive"]))
        self.assertFalse(bool(result["all_scenarios_pf_above_1"]))


if __name__ == "__main__":
    unittest.main()
