import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.backtesting.candidate_entries import (
    INVALID_ENTRY_RELATIVE_TO_STOP,
    MISSING_IMMEDIATE_NEXT_BAR,
    build_candidate_entries,
)


def make_prices(
    *,
    next_open: float = 101.0,
    include_next_bar: bool = True,
) -> pd.DataFrame:
    index = pd.date_range(
        "2026-01-05 09:36",
        periods=3 if include_next_bar else 1,
        freq="min",
        tz="America/New_York",
    )
    frame = pd.DataFrame(
        {
            "session_date": pd.Timestamp("2026-01-05").date(),
            "contract": "MNQ TEST",
            "open": [96.0, next_open, 100.0][: len(index)],
            "high": [1000.0, 103.0, 102.0][: len(index)],
            "low": [0.0, 98.0, 97.0][: len(index)],
            "close": [101.0, 100.0, 99.0][: len(index)],
        },
        index=index,
    )
    return frame


def signal_row(
    direction: str,
    breakout_type: str,
    signal_time: str = "2026-01-05 09:36",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": [pd.Timestamp("2026-01-05").date()],
            "direction": [direction],
            "breakout_type": [breakout_type],
            "signal_time": [
                pd.Timestamp(signal_time, tz="America/New_York")
            ],
            "or_high": [100.0],
            "or_low": [90.0],
            "or_mid": [95.0],
            "ambiguity_status": [False],
        }
    )


class CandidateEntryTests(unittest.TestCase):
    def test_print_long_enters_at_or_high_on_signal_bar(self):
        candidates = build_candidate_entries(
            make_prices(), signal_row("LONG", "PRINT"), or_minutes=20
        )
        candidate = candidates.iloc[0]
        self.assertEqual(candidate["or_minutes"], 20)
        self.assertEqual(candidate["entry_price"], 100.0)
        self.assertEqual(candidate["entry_time"], candidate["signal_time"])
        self.assertEqual(candidate["initial_stop"], 95.0)
        self.assertEqual(candidate["risk_points"], 5.0)
        self.assertEqual(candidate["initial_target"], 110.0)
        self.assertTrue(bool(candidate["candidate_validity"]))

    def test_print_short_enters_at_or_low_on_signal_bar(self):
        candidates = build_candidate_entries(
            make_prices(), signal_row("SHORT", "PRINT"), or_minutes=5
        )
        candidate = candidates.iloc[0]
        self.assertEqual(candidate["entry_price"], 90.0)
        self.assertEqual(candidate["entry_time"], candidate["signal_time"])
        self.assertEqual(candidate["initial_stop"], 95.0)
        self.assertEqual(candidate["risk_points"], 5.0)
        self.assertEqual(candidate["initial_target"], 80.0)
        self.assertTrue(bool(candidate["candidate_validity"]))

    def test_close_uses_exact_next_bar_open_and_ignores_signal_bar_range(self):
        prices = make_prices(next_open=102.0)
        candidates = build_candidate_entries(
            prices, signal_row("LONG", "CLOSE"), or_minutes=5
        )
        candidate = candidates.iloc[0]
        self.assertEqual(
            candidate["entry_time"],
            pd.Timestamp("2026-01-05 09:37", tz="America/New_York"),
        )
        self.assertNotEqual(candidate["entry_time"], candidate["signal_time"])
        self.assertEqual(candidate["entry_price"], 102.0)
        self.assertEqual(candidate["risk_points"], 7.0)
        self.assertEqual(candidate["initial_target"], 116.0)
        self.assertTrue(bool(candidate["candidate_validity"]))

    def test_invalid_entry_relative_to_stop_is_explicit(self):
        candidates = build_candidate_entries(
            make_prices(next_open=95.0),
            signal_row("LONG", "CLOSE"),
            or_minutes=5,
        )
        candidate = candidates.iloc[0]
        self.assertFalse(bool(candidate["candidate_validity"]))
        self.assertEqual(
            candidate["invalid_reason"], INVALID_ENTRY_RELATIVE_TO_STOP
        )
        self.assertTrue(pd.isna(candidate["risk_points"]))
        self.assertTrue(pd.isna(candidate["initial_target"]))
        self.assertEqual(candidate["initial_stop"], 95.0)

    def test_missing_immediate_next_bar_is_explicit(self):
        candidates = build_candidate_entries(
            make_prices(include_next_bar=False),
            signal_row("LONG", "CLOSE"),
            or_minutes=5,
        )
        candidate = candidates.iloc[0]
        self.assertFalse(bool(candidate["candidate_validity"]))
        self.assertEqual(candidate["invalid_reason"], MISSING_IMMEDIATE_NEXT_BAR)
        self.assertTrue(pd.isna(candidate["entry_time"]))
        self.assertTrue(pd.isna(candidate["entry_price"]))

    def test_candidate_build_does_not_mutate_validated_signals(self):
        signals = signal_row("LONG", "CLOSE")
        original = signals.copy(deep=True)
        build_candidate_entries(make_prices(), signals, or_minutes=5)
        assert_frame_equal(signals, original)


if __name__ == "__main__":
    unittest.main()
