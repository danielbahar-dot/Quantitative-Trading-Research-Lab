"""FVG-I1 formation and immutable facts (D-148). Synthetic, mirrored."""

import unittest
from fractions import Fraction

import pandas as pd

from fvg_fixtures import HISTORY_FLAT, HISTORY_OK, W1, ZONE3, end, mirror, run, tk, zone_at
from ms_fixtures import SPEC, ohlc_bars
from src.fvg.formation import (
    BEARISH,
    BULLISH,
    C2_BODY_NOT_SPANNING,
    C2_NOT_DIRECTIONAL,
    INSUFFICIENT_HISTORY,
    OK,
    REJECTION_COLUMNS,
    ZERO_BASELINE,
    ZONE_COLUMNS,
)
from src.fvg.pipeline import build_fvg

BOTH = (False, True)


class ShapeTests(unittest.TestCase):
    def test_bullish_and_mirrored_bearish_values(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(ZONE3, mirrored=m)
                z = zone_at(r, 101.00, 102.25, m)
                self.assertEqual(z["original_direction"], BEARISH if m else BULLISH)
                self.assertEqual(z["width_ticks"], 5)
                self.assertEqual(z["midpoint_half_ticks"], z["lower_ticks"] + z["upper_ticks"])
                self.assertEqual(z["midpoint"], 20101.625 if not m else 20098.375)   # half-tick, never rounded
                self.assertEqual(z["available_at"], end(2))
                self.assertEqual(z["source_at"], end(0))
                self.assertTrue(z["source_ref"].startswith("BAR_SPAN:MNQ|"))
                self.assertTrue(z["zone_id"].startswith("fz_"))

    def test_not_visible_before_c3_close_and_ids_stable(self):
        early = run(ZONE3 + [(104.5, 105, 104, 104.5)], cutoff_k=1)
        self.assertTrue(early.zones.empty)
        a = run(ZONE3)
        b = run(ZONE3 + [(104.5, 105, 104, 104.5)] * 3)
        self.assertEqual(set(a.zones["zone_id"]), set(b.zones["zone_id"]) & set(a.zones["zone_id"]))
        self.assertIn(a.zones["zone_id"].iloc[0], set(b.zones["zone_id"]))

    def test_schemas(self):
        r = run(ZONE3)
        self.assertEqual(tuple(r.zones.columns), ZONE_COLUMNS)
        self.assertEqual(tuple(r.rejections.columns), REJECTION_COLUMNS)


class RuleTests(unittest.TestCase):
    CASES = {
        "one tick": ([(100, 101.00, 99, 100.75), (100.75, 104, 100.5, 103.75), (103.75, 105, 101.25, 104.5)], (101.00, 101.25), None),
        "equality": ([(100, 101.00, 99, 100.75), (100.75, 104, 100.5, 103.75), (103.75, 105, 101.00, 104.5)], None, None),
        "C2 bearish": ([(100, 101, 99, 100.25), (103.75, 104, 100.5, 100.75), (104, 105, 102.25, 104.5)], None, C2_NOT_DIRECTIONAL),
        "doji C2": ([(100, 101, 99, 100.75), (102, 104, 100.5, 102), (102.5, 105, 102.25, 104.5)], None, C2_NOT_DIRECTIONAL),
        "close short of low(C3)": ([(100, 101, 99, 100.75), (100.75, 104, 100.5, 102.0), (102.5, 105, 102.25, 104.5)], None, C2_BODY_NOT_SPANNING),
        "open above high(C1)": ([(100, 101, 99, 100.75), (101.25, 104, 100.5, 103.75), (103.75, 105, 102.25, 104.5)], None, C2_BODY_NOT_SPANNING),
        "mixed colours": ([(101.0, 101.00, 99, 99.5), (99.5, 104, 99.25, 103.75), (104.5, 105, 102.25, 103.0)], (101.00, 102.25), None),
        "body on gap bounds": ([(100, 101, 99, 100.75), (101.00, 104, 100.5, 102.25), (102.25, 105, 102.25, 104.5)], (101.00, 102.25), None),
    }

    def test_rules_both_directions(self):
        for name, (rows, bounds, reason) in self.CASES.items():
            for m in BOTH:
                with self.subTest(case=name, mirrored=m):
                    r = run(rows, mirrored=m)
                    if bounds is None:
                        self.assertTrue(r.zones.empty)
                    else:
                        z = zone_at(r, *bounds, mirrored=m)
                        self.assertEqual(z["original_direction"], BEARISH if m else BULLISH)
                    if reason is None:
                        self.assertTrue(r.rejections.empty)
                    else:
                        self.assertEqual(list(r.rejections["reason"]), [reason])
                        self.assertEqual(r.rejections["wick_gap_direction"].iloc[0], BEARISH if m else BULLISH)
                    if name == "equality":
                        self.assertEqual(r.counts["5m"]["equality"], 1)

    def test_triple_across_gap_is_invalid(self):
        rows = ZONE3[:2] + [None] + ZONE3
        r = run(rows, absent={2})
        self.assertEqual(len(r.zones), 1)                         # only the post-gap triple
        self.assertEqual(r.zones["available_at"].iloc[0], end(5))


class NormalizationTests(unittest.TestCase):
    def test_statuses(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                ok = run(HISTORY_OK + ZONE3, mirrored=m)
                z = zone_at(ok, 101.00, 102.25, m)
                self.assertEqual(z["normalization_status"], OK)
                self.assertEqual(Fraction(int(z["strength_num"]), int(z["strength_den"])), Fraction(5, 4))
                self.assertEqual(z["baseline_tr_sum_ticks"], 56)        # 14 TRs of 4 ticks
                flat = zone_at(run(HISTORY_FLAT + ZONE3, mirrored=m), 101.00, 102.25, m)
                self.assertEqual(flat["normalization_status"], ZERO_BASELINE)
                self.assertTrue(pd.isna(flat["normalized_gap_strength"]))
                short = zone_at(run(HISTORY_OK[:14] + ZONE3, mirrored=m), 101.00, 102.25, m)
                self.assertEqual(short["normalization_status"], INSUFFICIENT_HISTORY)

    def test_gap_before_c1_is_not_bridged(self):
        rows = HISTORY_OK + [None] + HISTORY_OK[:3] + ZONE3
        z = run(rows, absent={15}).zones
        self.assertEqual(z["normalization_status"].iloc[-1], INSUFFICIENT_HISTORY)


class TimeframeTests(unittest.TestCase):
    def test_six_timeframes_independently(self):
        r = run(W1, timeframes=("1m", "5m", "15m", "1H", "4H", "1D"))
        self.assertEqual(set(r.counts), {"1m", "5m", "15m", "1H", "4H", "1D"})
        self.assertGreaterEqual(r.counts["5m"]["zones"], 3)
        one = run(ZONE3, tf="1m")
        self.assertEqual(one.zones["timeframe"].tolist(), ["1m"])

    def test_empty_input(self):
        bars = ohlc_bars(ZONE3, "5m")
        r = build_fvg(bars, SPEC, instrument_id="MNQ", replay_cutoff=end(0) - pd.Timedelta(hours=1), timeframes=("5m",))
        self.assertTrue(r.zones.empty and r.rejections.empty and r.engine.mitigation.empty and r.engine.episodes.empty)
        self.assertEqual(tuple(r.zones.columns), ZONE_COLUMNS)
        self.assertIn("run_id", r.manifest)




class CanonicalRefTests(unittest.TestCase):
    def test_fast_refs_equal_frozen_format(self):
        from src.fvg.formation import bar_ref, ctime
        from src.market_structure.swing import bar_span_ref
        from src.state.contract import canonical_time
        for ns in (pd.Timestamp("2024-06-21 13:31", tz="UTC").value, pd.Timestamp("2025-01-01 00:00:00.000000001", tz="UTC").value):
            t = pd.Timestamp(ns, tz="UTC")
            self.assertEqual(ctime(ns), canonical_time(t))
            self.assertEqual(bar_ref("MNQ", "MNQ 12-26", "5m", ns, ns + 300_000_000_000),
                             bar_span_ref(instrument_id="MNQ", contract="MNQ 12-26", timeframe="5m", first_bar_end=t,
                                          last_bar_end=t + pd.Timedelta(minutes=5)))


if __name__ == "__main__":
    unittest.main()
