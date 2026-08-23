import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.backtesting.completed_trades import (
    AMBIGUOUS_ENTRY_STOP,
    AMBIGUOUS_STOP_TARGET,
    ENTRY_AND_STOP_ORDER_UNKNOWN,
    SESSION_END,
    STOP,
    STOP_TARGET_ORDER_UNKNOWN,
    TARGET,
    simulate_completed_trades,
)


SESSION_DATE = pd.Timestamp("2026-01-05").date()
TZ = "America/New_York"


def make_candidate(
    direction: str,
    breakout_type: str = "CLOSE",
    or_minutes: int = 5,
) -> pd.DataFrame:
    long_trade = direction == "LONG"
    signal_time = pd.Timestamp("2026-01-05 09:36", tz=TZ)
    entry_time = (
        signal_time
        if breakout_type == "PRINT"
        else pd.Timestamp("2026-01-05 09:37", tz=TZ)
    )
    return pd.DataFrame(
        {
            "session_date": [SESSION_DATE],
            "contract": ["MNQ TEST"],
            "or_minutes": [or_minutes],
            "breakout_type": [breakout_type],
            "direction": [direction],
            "signal_time": [signal_time],
            "entry_time": [entry_time],
            "entry_price": [100.0 if long_trade else 90.0],
            "initial_stop": [95.0],
            "initial_target": [110.0 if long_trade else 80.0],
            "risk_points": [5.0],
            "candidate_validity": [True],
        }
    )


def make_prices(rows: list[tuple]) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [pd.Timestamp(timestamp, tz=TZ) for timestamp, *_ in rows]
    )
    return pd.DataFrame(
        {
            "session_date": SESSION_DATE,
            "contract": "MNQ TEST",
            "open": [values[0] for _, *values in rows],
            "high": [values[1] for _, *values in rows],
            "low": [values[2] for _, *values in rows],
            "close": [values[3] for _, *values in rows],
        },
        index=index,
    )


class CompletedTradeTests(unittest.TestCase):
    def test_long_target_only_exits_at_target(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [("2026-01-05 09:37", 100, 111, 99, 108)],
        )
        self.assertEqual(trade["exit_reason"], TARGET)
        self.assertEqual(trade["exit_price"], 110.0)
        self.assertEqual(trade["result_r"], 2.0)

    def test_long_stop_only_exits_at_stop(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [("2026-01-05 09:37", 100, 104, 94, 96)],
        )
        self.assertEqual(trade["exit_reason"], STOP)
        self.assertEqual(trade["exit_price"], 95.0)
        self.assertEqual(trade["result_r"], -1.0)

    def test_short_target_only_exits_at_target(self):
        trade = self._simulate(
            make_candidate("SHORT"),
            [("2026-01-05 09:37", 90, 92, 79, 82)],
        )
        self.assertEqual(trade["exit_reason"], TARGET)
        self.assertEqual(trade["exit_price"], 80.0)
        self.assertEqual(trade["result_r"], 2.0)

    def test_short_stop_only_exits_at_stop(self):
        trade = self._simulate(
            make_candidate("SHORT"),
            [("2026-01-05 09:37", 90, 96, 85, 94)],
        )
        self.assertEqual(trade["exit_reason"], STOP)
        self.assertEqual(trade["exit_price"], 95.0)
        self.assertEqual(trade["result_r"], -1.0)

    def test_same_bar_stop_and_target_is_ambiguous(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [("2026-01-05 09:37", 100, 111, 94, 100)],
        )
        self.assertEqual(trade["exit_reason"], AMBIGUOUS_STOP_TARGET)
        self.assertTrue(bool(trade["ambiguous"]))
        self.assertEqual(trade["ambiguity_reason"], STOP_TARGET_ORDER_UNKNOWN)
        self.assertTrue(pd.isna(trade["exit_price"]))
        self.assertTrue(pd.isna(trade["result_r"]))

    def test_close_signal_bar_can_never_exit_trade(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [
                ("2026-01-05 09:36", 100, 1000, 0, 100),
                ("2026-01-05 09:37", 100, 105, 99, 103),
                ("2026-01-05 09:38", 103, 111, 101, 110),
            ],
        )
        self.assertEqual(
            trade["exit_time"], pd.Timestamp("2026-01-05 09:38", tz=TZ)
        )
        self.assertEqual(trade["exit_reason"], TARGET)
        self.assertEqual(trade["holding_bars"], 2)

    def test_close_simulation_includes_entry_bar(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [("2026-01-05 09:37", 100, 111, 99, 108)],
        )
        self.assertEqual(
            trade["exit_time"], pd.Timestamp("2026-01-05 09:37", tz=TZ)
        )
        self.assertEqual(trade["holding_bars"], 1)
        self.assertEqual(trade["holding_minutes"], 0)

    def test_print_entry_bar_stop_touch_is_conservatively_ambiguous(self):
        trade = self._simulate(
            make_candidate("LONG", "PRINT", or_minutes=20),
            [("2026-01-05 09:36", 99, 105, 94, 101)],
        )
        self.assertEqual(trade["or_minutes"], 20)
        self.assertEqual(trade["exit_reason"], AMBIGUOUS_ENTRY_STOP)
        self.assertEqual(
            trade["ambiguity_reason"], ENTRY_AND_STOP_ORDER_UNKNOWN
        )
        self.assertTrue(bool(trade["excluded_from_performance"]))

    def test_session_end_uses_1600_close_and_ignores_1601(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [
                ("2026-01-05 09:37", 100, 104, 98, 101),
                ("2026-01-05 16:00", 103, 106, 99, 103),
                ("2026-01-05 16:01", 103, 111, 102, 110),
            ],
        )
        self.assertEqual(trade["exit_reason"], SESSION_END)
        self.assertEqual(
            trade["exit_time"], pd.Timestamp("2026-01-05 16:00", tz=TZ)
        )
        self.assertEqual(trade["exit_price"], 103.0)
        self.assertEqual(trade["result_r"], 0.6)

    def test_shortened_session_uses_last_observed_bar_before_1600(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [
                ("2026-01-05 09:37", 100, 104, 98, 101),
                ("2026-01-05 13:15", 103, 106, 99, 102),
                ("2026-01-05 18:00", 102, 111, 101, 110),
            ],
        )
        self.assertEqual(trade["exit_reason"], SESSION_END)
        self.assertEqual(
            trade["exit_time"], pd.Timestamp("2026-01-05 13:15", tz=TZ)
        )
        self.assertEqual(trade["exit_price"], 102.0)

    def test_mfe_mae_stop_at_exit_bar(self):
        trade = self._simulate(
            make_candidate("LONG"),
            [
                ("2026-01-05 09:37", 100, 105, 98, 103),
                ("2026-01-05 09:38", 103, 111, 97, 110),
                ("2026-01-05 09:39", 110, 1000, 0, 500),
            ],
        )
        self.assertEqual(trade["mfe_points"], 11.0)
        self.assertEqual(trade["mae_points"], 3.0)
        self.assertAlmostEqual(trade["mfe_r"], 2.2)
        self.assertAlmostEqual(trade["mae_r"], 0.6)

    def test_simulation_does_not_mutate_candidates(self):
        candidates = make_candidate("LONG")
        original = candidates.copy(deep=True)
        simulate_completed_trades(
            make_prices(
                [("2026-01-05 09:37", 100, 111, 99, 108)]
            ),
            candidates,
        )
        assert_frame_equal(candidates, original)

    def _simulate(self, candidates, rows):
        trades = simulate_completed_trades(make_prices(rows), candidates)
        self.assertEqual(len(trades), 1)
        return trades.iloc[0]


if __name__ == "__main__":
    unittest.main()
