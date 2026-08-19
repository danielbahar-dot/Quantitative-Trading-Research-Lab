import unittest

import pandas as pd

from src.backtesting.orb_v01 import run_orb_variant


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
        trades, _ = run_orb_variant(make_session("09:35"), 5, "CLOSE")
        self.assertEqual(len(trades), 1)
        entry_time = pd.Timestamp(trades.iloc[0]["breakout_timestamp"])
        self.assertEqual(entry_time.time(), pd.Timestamp("09:35").time())
        self.assertGreater(entry_time.time(), pd.Timestamp("09:34").time())

    def test_no_entry_after_1130_cutoff(self):
        trades, _ = run_orb_variant(make_session("11:31"), 5, "CLOSE")
        self.assertTrue(trades.empty)

    def test_1130_entry_is_included(self):
        trades, _ = run_orb_variant(make_session("11:30"), 5, "CLOSE")
        self.assertEqual(len(trades), 1)


if __name__ == "__main__":
    unittest.main()
