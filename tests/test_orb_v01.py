import unittest

import pandas as pd

from src.backtesting.orb_v01 import run_orb_variant
from src.features.opening_range import calculate_opening_range


def make_session(breakout_time: str | None) -> pd.DataFrame:
    index = pd.date_range("2026-01-05 09:30", "2026-01-05 16:00", freq="min", tz="America/New_York")
    frame = pd.DataFrame(
        {
            "session_date": pd.Timestamp("2026-01-05").date(),
            "contract": "MNQ TEST",
            "open": 99.5,
            "high": 100.0,
            "low": 99.0,
            "close": 99.5,
        },
        index=index,
    )
    if breakout_time:
        timestamp = pd.Timestamp(f"2026-01-05 {breakout_time}", tz="America/New_York")
        frame.loc[timestamp, ["open", "high", "low", "close"]] = [99.75, 100.25, 99.5, 100.25]
    return frame


class ORBV01TimingTests(unittest.TestCase):
    def test_entry_is_after_opening_range_completion(self):
        market_open = pd.Timestamp("2026-01-05 09:30", tz="America/New_York")
        for duration in (5, 10, 15, 30):
            with self.subTest(duration=duration):
                session = make_session(None)
                final_or_stamp = market_open + pd.Timedelta(minutes=duration)
                first_eligible_stamp = final_or_stamp + pd.Timedelta(minutes=1)
                session.loc[
                    final_or_stamp, ["open", "high", "low", "close"]
                ] = [99.75, 100.25, 99.5, 100.25]
                session.loc[
                    first_eligible_stamp, ["open", "high", "low", "close"]
                ] = [100.25, 100.5, 100.0, 100.5]

                trades, _ = run_orb_variant(session, duration, "CLOSE")
                self.assertEqual(len(trades), 1)
                entry_time = pd.Timestamp(trades.iloc[0]["breakout_timestamp"])
                self.assertEqual(entry_time, first_eligible_stamp)
                self.assertGreater(entry_time, final_or_stamp)

    def test_no_entry_after_1130_cutoff(self):
        trades, _ = run_orb_variant(make_session("11:31"), 5, "CLOSE")
        self.assertTrue(trades.empty)

    def test_1130_entry_is_included(self):
        trades, _ = run_orb_variant(make_session("11:30"), 5, "CLOSE")
        self.assertEqual(len(trades), 1)


class OpeningRangeBarEndTests(unittest.TestCase):
    def test_all_durations_use_exact_nt8_bar_end_timestamps(self):
        index = pd.date_range(
            "2026-01-05 09:30",
            "2026-01-05 10:01",
            freq="min",
            tz="America/New_York",
        )
        offsets = pd.Series(range(len(index)), index=index, dtype=float)
        session = pd.DataFrame(
            {
                "high": 100.0 + offsets,
                "low": 100.0 - offsets,
            },
            index=index,
        )
        session.loc["2026-01-05 09:30", ["high", "low"]] = [1000.0, -1000.0]

        for duration in (5, 10, 15, 30):
            with self.subTest(duration=duration):
                opening_range = calculate_opening_range(session, duration)
                self.assertIsNotNone(opening_range)
                self.assertEqual(
                    opening_range["start_timestamp"],
                    pd.Timestamp("2026-01-05 09:31", tz="America/New_York"),
                )
                self.assertEqual(
                    opening_range["end_timestamp"],
                    pd.Timestamp("2026-01-05 09:30", tz="America/New_York")
                    + pd.Timedelta(minutes=duration),
                )
                self.assertEqual(opening_range["or_high"], 100.0 + duration)
                self.assertEqual(opening_range["or_low"], 100.0 - duration)
                self.assertEqual(opening_range["or_mid"], 100.0)


if __name__ == "__main__":
    unittest.main()
