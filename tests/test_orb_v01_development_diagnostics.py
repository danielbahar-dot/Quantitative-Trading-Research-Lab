from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from src.experiments.orb_v01_baseline import VARIANTS, build_equity_curves
from src.experiments.orb_v01_development_diagnostics import (
    calculate_month_statistics,
    calculate_r_distribution,
    calculate_rolling_expectancy,
    load_development_trades,
)


def make_config() -> dict:
    return {
        "partitions": [
            {
                "name": "DEVELOPMENT",
                "start": "2024-06-21",
                "end": "2025-06-30",
            },
            {
                "name": "VALIDATION",
                "start": "2025-07-01",
                "end": "2025-12-31",
            },
            {
                "name": "OOS",
                "start": "2026-01-01",
                "end": "2026-08-17",
            },
        ]
    }


def make_trade(
    trade_number: int,
    or_minutes: int = 5,
    breakout_type: str = "PRINT",
    *,
    session_date: str | None = None,
    result_r: float = -1.0,
) -> dict:
    date = pd.Timestamp(session_date or "2024-07-01") + pd.Timedelta(
        days=trade_number
    )
    signal = date + pd.Timedelta(hours=9, minutes=36)
    return {
        "trade_id": f"{date.date()}_{or_minutes}_{breakout_type}_{trade_number}",
        "session_date": date.date().isoformat(),
        "contract": "MNQ TEST",
        "or_minutes": or_minutes,
        "breakout_type": breakout_type,
        "direction": "LONG" if trade_number % 2 == 0 else "SHORT",
        "signal_time": signal.isoformat(),
        "entry_time": signal.isoformat(),
        "exit_time": (signal + pd.Timedelta(minutes=10)).isoformat(),
        "exit_reason": "STOP" if result_r < 0 else "TARGET",
        "result_r": result_r,
        "holding_minutes": 10,
        "ambiguous": False,
        "excluded_from_performance": False,
    }


class DevelopmentDiagnosticsTests(unittest.TestCase):
    def test_loader_discards_reserved_periods_before_analytics(self):
        historical_rows = []
        twenty_minute_rows = []
        for index, (or_minutes, breakout_type) in enumerate(VARIANTS):
            destination = (
                twenty_minute_rows
                if (or_minutes, breakout_type) == (20, "PRINT")
                else historical_rows
            )
            destination.append(
                make_trade(
                    index,
                    or_minutes,
                    breakout_type,
                    session_date="2025-06-20",
                    result_r=1.0,
                )
            )
            destination.append(
                make_trade(
                    index,
                    or_minutes,
                    breakout_type,
                    session_date="2025-07-01",
                    result_r=999.0,
                )
            )
            destination.append(
                make_trade(
                    index,
                    or_minutes,
                    breakout_type,
                    session_date="2026-01-02",
                    result_r=999.0,
                )
            )
        with TemporaryDirectory() as temp_dir:
            historical_path = Path(temp_dir) / "historical.csv"
            twenty_minute_path = Path(temp_dir) / "twenty_minute.csv"
            pd.DataFrame(historical_rows).to_csv(historical_path, index=False)
            pd.DataFrame(twenty_minute_rows).to_csv(
                twenty_minute_path, index=False
            )
            selected = load_development_trades(
                (historical_path, twenty_minute_path),
                make_config(),
                chunksize=5,
            )
        self.assertEqual(len(selected), len(VARIANTS))
        self.assertTrue(selected["result_r"].eq(1.0).all())
        self.assertLessEqual(
            selected["session_date"].max(), pd.Timestamp("2025-06-30")
        )

    def test_current_research_variants_add_only_20m_print(self):
        self.assertIn((20, "PRINT"), VARIANTS)
        self.assertNotIn((20, "CLOSE"), VARIANTS)

    def test_rolling_windows_do_not_manufacture_early_values(self):
        trades = pd.DataFrame(
            [make_trade(index, result_r=float(index + 1)) for index in range(100)]
        )
        for column in ("session_date", "signal_time", "entry_time"):
            trades[column] = pd.to_datetime(trades[column])
        rolling = calculate_rolling_expectancy(trades)
        subset = rolling.loc[rolling["variant"].eq("5m PRINT")].reset_index(
            drop=True
        )
        self.assertTrue(subset.loc[:48, "rolling_50_avg_r"].isna().all())
        self.assertAlmostEqual(subset.loc[49, "rolling_50_avg_r"], 25.5)
        self.assertEqual(subset.loc[49, "rolling_50_trade_count"], 50)
        self.assertTrue(subset.loc[:98, "rolling_100_avg_r"].isna().all())
        self.assertAlmostEqual(subset.loc[99, "rolling_100_avg_r"], 50.5)
        self.assertEqual(subset.loc[99, "rolling_100_trade_count"], 100)

    def test_distribution_uses_tolerance_for_nominal_outcomes(self):
        values = [-1.0, -1.0 + 5e-10, 2.0, 2.0 - 5e-10, 0.0, 0.5]
        trades = pd.DataFrame(
            [make_trade(index, result_r=value) for index, value in enumerate(values)]
        )
        for column in ("session_date", "signal_time", "entry_time"):
            trades[column] = pd.to_datetime(trades[column])
        distribution = calculate_r_distribution(trades).iloc[0]
        self.assertEqual(distribution["count"], 6)
        self.assertEqual(distribution["minus_1r_count"], 2)
        self.assertEqual(distribution["plus_2r_count"], 2)
        self.assertEqual(distribution["zero_r_count"], 1)
        self.assertAlmostEqual(distribution["std_r"], np.std(values, ddof=1))

    def test_month_statistics_reconcile_positive_negative_and_flat_months(self):
        monthly = pd.DataFrame(
            {
                "variant": ["5m PRINT"] * 5,
                "total_r": [3.0, -2.0, 0.0, 1.0, -1.0],
            }
        )
        statistics = calculate_month_statistics(monthly).iloc[0]
        self.assertEqual(statistics["months"], 5)
        self.assertEqual(statistics["positive_months"], 2)
        self.assertEqual(statistics["negative_months"], 2)
        self.assertEqual(statistics["flat_months"], 1)
        self.assertAlmostEqual(statistics["percentage_positive_months"], 0.4)
        self.assertEqual(statistics["best_month_r"], 3.0)
        self.assertEqual(statistics["worst_month_r"], -2.0)

    def test_equity_curve_cannot_extend_beyond_input_scope(self):
        trades = []
        for index, (or_minutes, breakout_type) in enumerate(VARIANTS):
            trades.append(
                make_trade(
                    index,
                    or_minutes,
                    breakout_type,
                    session_date="2025-06-20",
                    result_r=1.0,
                )
            )
        frame = pd.DataFrame(trades)
        for column in ("session_date", "signal_time", "entry_time"):
            frame[column] = pd.to_datetime(frame[column])
        equity = build_equity_curves(frame)
        self.assertLessEqual(equity.index.max(), pd.Timestamp("2025-06-30"))


if __name__ == "__main__":
    unittest.main()
