"""Neutral swing_breaks tests (MS-I1; MARKET_STRUCTURE_SPEC §C.2, §E.9, D-139). Synthetic data only."""

from decimal import Decimal
import unittest

import pandas as pd

from ms_fixtures import BASE, EX_A, SPEC, ohlc_bars, segments, slot_end
from src.market_structure.swing import LOWER, UPPER, SwingDefinitionSpec, bar_span_ref
from src.market_structure.swing_breaks import (
    SWING_BREAK_COLUMNS,
    SwingBreakError,
    break_id,
    swing_breaks_from_segments,
    validate_swing_breaks,
)
from src.market_structure.swing_detector import build_swing_points

REF22 = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2)
VERSION = "swing-break-v1"
TICK = Decimal("0.25")


def run(rows, tf="5m", **kwargs):
    bars = ohlc_bars(rows, tf, **kwargs)
    swings = build_swing_points(bars, tf, SPEC, REF22, instrument_id="MNQ")
    _, segs, _ = segments(bars, tf)
    breaks = swing_breaks_from_segments(swings, segs, timeframe=tf, break_definition_version=VERSION,
                                        instrument_id="MNQ", tick_size=TICK)
    return swings, breaks


def by_price(swings, orientation, price):
    hit = swings[(swings["orientation"] == orientation) & (swings["price"] == BASE + price)]
    assert len(hit) == 1, (orientation, price, len(hit))
    return hit.iloc[0]


def row_for(breaks, swing):
    hit = breaks[breaks["swing_id"] == swing["swing_id"]]
    return None if hit.empty else hit.iloc[0]


# Swing High 110 at observation 2 (L=R=2), confirmed by observation 4.
HIGH_110 = [(100, 101, 99, 100), (100, 103, 99, 102), (102, 110, 101, 105), (105, 106, 103, 104), (104, 105, 102, 103)]


class FirstStrictCloseTests(unittest.TestCase):
    def test_ex_a_breaks_match_spec(self):
        swings, breaks = run(EX_A)
        expected = {(UPPER, 110): 10, (UPPER, 118): 18, (UPPER, 126): 26}
        self.assertEqual(len(breaks), 3)
        for (orientation, price), position in expected.items():
            row = row_for(breaks, by_price(swings, orientation, price))
            self.assertEqual(pd.Timestamp(row["bar_end"]), slot_end(position))
        lows = set(swings.loc[swings["orientation"] == LOWER, "swing_id"])
        self.assertEqual(len(lows), 4)  # A0 100, P 104, Q1 104, Q2 112: never closed below in EX-A
        self.assertFalse(lows & set(breaks["swing_id"]))

    def test_equality_and_wick_never_break(self):
        rows = HIGH_110 + [(104, 112, 103, 110), (110, 111, 108, 109)]
        swings, breaks = run(rows)
        self.assertIsNone(row_for(breaks, by_price(swings, UPPER, 110)))

    def test_one_tick_beyond_breaks_and_only_first_is_kept(self):
        rows = HIGH_110 + [(104, 111, 103, 110.25), (110, 115, 109, 114)]
        swings, breaks = run(rows)
        row = row_for(breaks, by_price(swings, UPPER, 110))
        self.assertEqual(pd.Timestamp(row["bar_end"]), slot_end(5))
        self.assertEqual(row["close_excess_ticks"], 1)
        self.assertEqual(row["level_ticks"], int((BASE + 110) / 0.25))
        self.assertEqual((breaks["swing_id"] == row["swing_id"]).sum(), 1)

    def test_gap_open_close_beyond_is_a_break(self):
        rows = HIGH_110 + [(110.5, 111.25, 110.25, 111)]
        swings, breaks = run(rows)
        row = row_for(breaks, by_price(swings, UPPER, 110))
        self.assertEqual(pd.Timestamp(row["bar_end"]), slot_end(5))
        self.assertEqual(row["close_excess_ticks"], 4)

    def test_lower_mirror(self):
        rows = [(100, 101, 99, 100), (99, 100, 97, 98), (98, 99, 90, 95), (95, 97, 94, 96), (96, 98, 95, 97),
                (97, 98, 89, 90), (90, 91, 88, 89.75)]
        swings, breaks = run(rows)
        low = by_price(swings, LOWER, 90)
        row = row_for(breaks, low)
        self.assertEqual(pd.Timestamp(row["bar_end"]), slot_end(6))  # 90 close at 5 is equality
        self.assertEqual(row["close_ticks"], int((BASE + 89.75) / 0.25))

    def test_first_eligible_observation_is_after_confirmation(self):
        swings, breaks = run(HIGH_110 + [(104, 112, 103, 111)])
        swing = by_price(swings, UPPER, 110)
        row = row_for(breaks, swing)
        self.assertGreaterEqual(pd.Timestamp(row["bar_start"]), pd.Timestamp(swing["available_at"]))
        self.assertEqual(pd.Timestamp(row["bar_start"]), slot_end(4))  # bar_start == available_at is eligible

    def test_schema_and_identity(self):
        swings, breaks = run(EX_A)
        self.assertEqual(tuple(breaks.columns), SWING_BREAK_COLUMNS)
        row = breaks.iloc[0]
        ref = bar_span_ref(instrument_id="MNQ", contract=row["contract"], timeframe="5m",
                           first_bar_end=row["bar_end"], last_bar_end=row["bar_end"])
        self.assertEqual(row["observation_ref"], ref)
        self.assertEqual(row["break_id"], break_id(break_definition_version=VERSION, swing_id=row["swing_id"],
                                                   observation_ref=ref))
        self.assertTrue(row["break_id"].startswith("sb_"))
        again = run(EX_A)[1]
        pd.testing.assert_frame_equal(breaks, again)

    def test_iteration_order_independent(self):
        bars = ohlc_bars(EX_A)
        swings = build_swing_points(bars, "5m", SPEC, REF22, instrument_id="MNQ")
        _, segs, _ = segments(bars)
        a = swing_breaks_from_segments(swings, segs, timeframe="5m", break_definition_version=VERSION,
                                       instrument_id="MNQ", tick_size=TICK)
        b = swing_breaks_from_segments(swings.sample(frac=1, random_state=7), segs, timeframe="5m",
                                       break_definition_version=VERSION, instrument_id="MNQ", tick_size=TICK)
        pd.testing.assert_frame_equal(a, b)

    def test_one_minute_timeframe(self):
        swings, breaks = run(HIGH_110 + [(104, 112, 103, 111)], tf="1m")
        row = row_for(breaks, by_price(swings, UPPER, 110))
        self.assertEqual(pd.Timestamp(row["bar_end"]), slot_end(5, "1m"))


class SegmentIsolationTests(unittest.TestCase):
    def test_close_beyond_after_a_gap_is_not_a_break(self):
        rows = HIGH_110 + [(104, 106, 103, 105), None, (105, 115, 104, 114)]
        swings, breaks = run(rows)
        self.assertIsNone(row_for(breaks, by_price(swings, UPPER, 110)))

    def test_close_beyond_on_a_new_contract_is_not_a_break(self):
        rows = HIGH_110 + [(104, 106, 103, 105), (105, 115, 104, 114)]
        contracts = ["MNQ 09-26"] * 6 + ["MNQ 12-26"]
        swings, breaks = run(rows, contracts=contracts)
        self.assertIsNone(row_for(breaks, by_price(swings, UPPER, 110)))

    def test_incomplete_observation_ends_the_segment(self):
        rows = HIGH_110 + [(104, 106, 103, 105), (105, 115, 104, 114), (114, 116, 113, 115)]
        swings, breaks = run(rows, incomplete={6})
        self.assertIsNone(row_for(breaks, by_price(swings, UPPER, 110)))

    def test_inconsistent_segments_fail_closed(self):
        bars = ohlc_bars(HIGH_110 + [(104, 112, 103, 111)])
        swings = build_swing_points(bars, "5m", SPEC, REF22, instrument_id="MNQ")
        _, segs, _ = segments(bars)
        with self.assertRaises(SwingBreakError):
            swing_breaks_from_segments(swings, [segs[0].iloc[:3]], timeframe="5m", break_definition_version=VERSION,
                                       instrument_id="MNQ", tick_size=TICK)
        with self.assertRaises(SwingBreakError):
            swing_breaks_from_segments(swings, segs, timeframe="4H", break_definition_version=VERSION,
                                       instrument_id="MNQ", tick_size=TICK)


class ValidationNegativeTests(unittest.TestCase):
    def setUp(self):
        self.breaks = run(EX_A)[1]

    def test_tampered_id_rejected(self):
        bad = self.breaks.copy()
        bad.loc[0, "break_id"] = "sb_" + "0" * 64
        with self.assertRaises(SwingBreakError):
            validate_swing_breaks(bad)

    def test_equality_row_rejected(self):
        bad = self.breaks.copy()
        bad.loc[0, "close_ticks"] = bad.loc[0, "level_ticks"]
        bad.loc[0, "close_excess_ticks"] = 0
        with self.assertRaises(SwingBreakError):
            validate_swing_breaks(bad)

    def test_duplicate_swing_rejected(self):
        bad = pd.concat([self.breaks, self.breaks.iloc[[0]]], ignore_index=True)
        with self.assertRaises(SwingBreakError):
            validate_swing_breaks(bad)

    def test_schema_mismatch_rejected(self):
        with self.assertRaises(SwingBreakError):
            validate_swing_breaks(self.breaks.drop(columns=["fact_hash"]))


if __name__ == "__main__":
    unittest.main()
