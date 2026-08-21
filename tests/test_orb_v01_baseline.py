import unittest

import pandas as pd

from src.experiments.orb_v01_baseline import (
    build_equity_curves,
    calculate_independent_summary,
    calculate_max_drawdown_r,
    calculate_monthly_summary,
    max_consecutive_losses,
    vectorbt_crosscheck,
)


def make_trades() -> pd.DataFrame:
    result_r = [-1.0, 2.0, -1.0, -0.5, 0.5]
    directions = ["LONG", "SHORT", "LONG", "SHORT", "LONG"]
    reasons = ["STOP", "TARGET", "STOP", "SESSION_END", "SESSION_END"]
    dates = pd.date_range("2026-01-05", periods=5, freq="D")
    return pd.DataFrame(
        {
            "trade_id": [f"trade_{i}" for i in range(5)],
            "session_date": dates,
            "or_minutes": 5,
            "breakout_type": "PRINT",
            "direction": directions,
            "signal_time": dates + pd.Timedelta(hours=9, minutes=36),
            "entry_time": dates + pd.Timedelta(hours=9, minutes=36),
            "exit_reason": reasons,
            "result_r": result_r,
            "holding_minutes": [10, 20, 30, 40, 50],
        }
    )


class IndependentAnalyticsTests(unittest.TestCase):
    def test_requested_summary_metrics(self):
        summary = calculate_independent_summary(make_trades()).iloc[0]
        self.assertEqual(summary["executed_trades"], 5)
        self.assertEqual(summary["wins"], 2)
        self.assertEqual(summary["losses"], 3)
        self.assertEqual(summary["session_end_exits"], 2)
        self.assertAlmostEqual(summary["win_rate"], 0.4)
        self.assertAlmostEqual(summary["average_r"], 0.0)
        self.assertAlmostEqual(summary["median_r"], -0.5)
        self.assertAlmostEqual(summary["total_r"], 0.0)
        self.assertAlmostEqual(summary["profit_factor_r"], 1.0)
        self.assertAlmostEqual(summary["max_drawdown_r"], 1.5)
        self.assertEqual(summary["max_consecutive_losses"], 2)
        self.assertAlmostEqual(summary["average_holding_minutes"], 30.0)
        self.assertEqual(summary["long_trade_count"], 3)
        self.assertAlmostEqual(summary["long_average_r"], -0.5)
        self.assertAlmostEqual(summary["long_total_r"], -1.5)
        self.assertEqual(summary["short_trade_count"], 2)
        self.assertAlmostEqual(summary["short_average_r"], 0.75)
        self.assertAlmostEqual(summary["short_total_r"], 1.5)

    def test_drawdown_and_loss_streak_include_zero_origin(self):
        result_r = pd.Series([-1.0, -1.0, 2.0, 0.0, -1.0])
        self.assertEqual(calculate_max_drawdown_r(result_r), 2.0)
        self.assertEqual(max_consecutive_losses(result_r), 2)

    def test_monthly_and_equity_outputs_reconcile(self):
        trades = make_trades()
        monthly = calculate_monthly_summary(trades)
        equity = build_equity_curves(trades)
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly.iloc[0]["trades"], 5)
        self.assertAlmostEqual(monthly.iloc[0]["total_r"], 0.0)
        self.assertEqual(equity.iloc[0, 0], 0.0)
        self.assertAlmostEqual(equity.iloc[-1, 0], 0.0)

    def test_vectorbt_core_crosscheck(self):
        import vectorbt as vbt

        trades = make_trades()
        independent = calculate_independent_summary(trades)
        checked = vectorbt_crosscheck(
            trades, independent, vbt_module=vbt
        ).iloc[0]
        self.assertTrue(bool(checked["crosscheck_passed"]))
        self.assertEqual(checked["vectorbt_trade_count"], 5)
        self.assertAlmostEqual(checked["vectorbt_max_drawdown_r"], 1.5)


if __name__ == "__main__":
    unittest.main()
