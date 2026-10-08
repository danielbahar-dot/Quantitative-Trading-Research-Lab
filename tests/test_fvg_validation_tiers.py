"""FVG validation runner tiers: fast-window selection stays inside DEVELOPMENT; full-DEV-only gates are SKIPPED."""

import unittest

import pandas as pd

from src.experiments.fvg_dev_validation import FAST_WINDOW, _gate, parse_args, select_window

NY = "America/New_York"


def _bars(start="2024-06-21", end="2025-06-30"):
    idx = pd.date_range(pd.Timestamp(start, tz=NY) + pd.Timedelta(minutes=1), pd.Timestamp(end, tz=NY) + pd.Timedelta(hours=17),
                        freq="6h")
    return pd.DataFrame({"close": 1.0}, index=idx)


class TierTests(unittest.TestCase):
    def test_default_is_full_tier(self):
        a = parse_args([])
        self.assertIsNone(a.start)
        self.assertIsNone(a.reference_max_bars)

    def test_fast_uses_default_window(self):
        a = parse_args(["--fast"])
        self.assertEqual((a.start, a.end), FAST_WINDOW)

    def test_explicit_window_requires_both_ends(self):
        with self.assertRaises(SystemExit):
            parse_args(["--start", "2024-08-05"])

    def test_window_is_inclusive_by_et_date(self):
        out = select_window(_bars(), "2024-08-05", "2024-08-09")
        self.assertGreater(out.index.min(), pd.Timestamp("2024-08-05", tz=NY))
        self.assertLessEqual(out.index.max(), pd.Timestamp("2024-08-10", tz=NY))
        self.assertEqual(sorted({t.date().isoformat() for t in out.index})[-1], "2024-08-09")

    def test_window_outside_development_is_refused(self):
        with self.assertRaises(ValueError):
            select_window(_bars(), "2025-07-01", "2025-07-07")      # after DEVELOPMENT (holdout)
        with self.assertRaises(ValueError):
            select_window(_bars(), "2024-06-01", "2024-06-30")      # starts before DEVELOPMENT
        with self.assertRaises(ValueError):
            select_window(_bars(), "2024-08-09", "2024-08-05")      # empty

    def test_gate_labels(self):
        self.assertEqual(_gate(True), "PASS")
        self.assertEqual(_gate(False), "FAIL")
        self.assertTrue(_gate(None).startswith("SKIPPED"))


if __name__ == "__main__":
    unittest.main()
