"""Internal Liquidity formation atoms (IL-I2; D-144). Synthetic only."""

import unittest

import numpy as np
import pandas as pd

from ms_fixtures import BASE, SPEC, ohlc_bars, slot_end
from src.liquidity.contract import EQ, EXTENDED, FORMED, INTERNAL, LOWER, MERGED, REQ, UPPER
from src.liquidity.internal_formation import (
    INTERNAL_CANDLE_HIGH,
    INTERNAL_CANDLE_LOW,
    INTERNAL_SWING_HIGH,
    SwingAtom,
    build_internal_formations,
    cluster_versions,
)

# 5m sequence (spec E5 / E7): S1 50.00 @2, S2 50.75 @6, S3 51.50 @10 (2/2 swing highs)
E5 = [(40, 41, 39, 40), (40, 43, 39, 42), (42, 50.00, 41, 45), (45, 46, 42, 43), (43, 44, 40, 41),
      (41, 45, 40, 44), (44, 50.75, 43, 46), (46, 47, 44, 45), (45, 46, 43, 44), (44, 48, 43, 47),
      (47, 51.50, 46, 48), (48, 49, 46, 47), (47, 48, 45, 46)]


def formations(rows, tf="5m", cutoff_k=None, **kwargs):
    bars = ohlc_bars(rows, tf, **kwargs)
    cutoff = slot_end(len(rows) - 1 if cutoff_k is None else cutoff_k, tf)
    return build_internal_formations(bars, SPEC, instrument_id="MNQ", replay_cutoff=cutoff)


def swing_member(result, price, orientation=UPPER, tf="5m"):
    m = result.members
    hit = m[(m["member_kind"] == (INTERNAL_SWING_HIGH if orientation == UPPER else "INTERNAL_SWING_LOW"))
            & (m["reference_family"] == tf) & (m["price"] == BASE + price)]
    assert len(hit) == 1, (price, len(hit))
    return hit.iloc[0]


class SwingAndClusterTests(unittest.TestCase):
    def test_e5_e7_req_formed_then_extended(self):
        r = formations(E5)
        s1, s2, s3 = (swing_member(r, p) for p in (50.00, 50.75, 51.50))
        self.assertEqual(pd.Timestamp(s2["available_at"]), slot_end(8))
        reqs = r.structures[(r.structures["structure_type"] == REQ) & (r.structures["reference_family"] == "5m")
                            & (r.structures["orientation"] == UPPER)].sort_values("available_at")
        self.assertEqual(list(reqs["change_kind"]), [FORMED, EXTENDED])
        self.assertEqual(set(reqs.iloc[0]["member_ids"]), {s1["member_id"], s2["member_id"]})
        self.assertEqual(pd.Timestamp(reqs.iloc[0]["available_at"]), slot_end(8))
        self.assertEqual(set(reqs.iloc[1]["member_ids"]), {s1["member_id"], s2["member_id"], s3["member_id"]})
        self.assertEqual(tuple(reqs.iloc[1]["supersedes"]), (reqs.iloc[0]["structure_id"],))
        self.assertTrue((r.structures["liquidity_class"] == INTERNAL).all())
        self.assertTrue((r.members["liquidity_class"] == INTERNAL).all())
        self.assertIn(s1["member_id"], r.spans)

    def test_swings_equal_frozen_detector(self):
        r = formations(E5)
        for tf in ("5m", "15m", "1H"):
            kinds = r.members[r.members["member_kind"].str.startswith("INTERNAL_SWING") & (r.members["reference_family"] == tf)]
            self.assertEqual(len(kinds), len(r.swings[tf]))

    def test_cutoff_before_confirmation_gives_no_structure(self):
        r = formations(E5, cutoff_k=7)
        self.assertTrue(r.structures.empty)
        self.assertEqual(len(r.members[r.members["member_kind"] == INTERNAL_SWING_HIGH]), 1)   # only S1 confirmed


class CandleTests(unittest.TestCase):
    def test_complete_1h_candles_only(self):
        rows = [(40, 45, 35, 42), (42, 48, 40, 44), (44, 47, 41, 45)]
        r = formations(rows, tf="1H", incomplete={1})
        candles = r.members[r.members["member_kind"].isin([INTERNAL_CANDLE_HIGH, INTERNAL_CANDLE_LOW])]
        self.assertEqual(len(candles), 4)                         # bars 0 and 2 only
        highs = candles[candles["member_kind"] == INTERNAL_CANDLE_HIGH].sort_values("available_at")
        self.assertEqual(list(highs["price"]), [BASE + 45, BASE + 47])
        self.assertTrue((pd.to_datetime(highs["source_at"]) == pd.to_datetime(highs["available_at"])).all())
        self.assertTrue(highs["source_ref"].str.startswith("HTF_BAR:MNQ|").all())

    def test_zero_output(self):
        bars = ohlc_bars([(40, 45, 35, 42)], "1H")
        r = build_internal_formations(bars, SPEC, instrument_id="MNQ",
                                      replay_cutoff=slot_end(0, "1H") - pd.Timedelta(hours=2))
        self.assertTrue(r.members.empty and r.structures.empty)


def atom(name, value, pos, k):
    return SwingAtom(name, pos, pos, value, value, pd.Timestamp("2026-09-14 10:00", tz="UTC") + pd.Timedelta(minutes=k),
                     "C")


class GrammarTests(unittest.TestCase):
    """Pure grammar core: EQ exact, REQ <= 4 ticks, barrier, distinct prices, FORMED / EXTENDED / MERGED."""

    def run_core(self, atoms, extremes):
        rows, blocks = cluster_versions(atoms, np.array(extremes), orientation=UPPER, timeframe="5m", instrument_id="MNQ")
        return rows, blocks

    def test_pure_equal_is_eq_only_then_req_formed(self):
        atoms = [atom("A", 100, 0, 1), atom("B", 100, 2, 2), atom("C", 104, 4, 3)]
        rows, _ = self.run_core(atoms, [100, 90, 100, 90, 104])
        kinds = [(r["structure_type"], r["change_kind"], r["member_ids"]) for r in rows]
        self.assertEqual(kinds, [(EQ, FORMED, ("A", "B")), (REQ, FORMED, ("A", "B", "C"))])

    def test_five_ticks_do_not_link(self):
        rows, _ = self.run_core([atom("A", 100, 0, 1), atom("B", 105, 2, 2)], [100, 90, 105])
        self.assertEqual(rows, [])

    def test_barrier_blocks_and_is_audited(self):
        rows, blocks = self.run_core([atom("A", 100, 0, 1), atom("B", 102, 2, 2)], [100, 103, 102])
        self.assertEqual(rows, [])
        self.assertEqual(blocks[0]["blocking_excess_ticks"], 1)
        rows, _ = self.run_core([atom("A", 100, 0, 1), atom("B", 102, 2, 2)], [100, 102, 102])   # equality never blocks
        self.assertEqual(rows[0]["change_kind"], FORMED)

    def test_merge(self):
        # A {106, 107} then B {100, 101}; J 104 bridges A2 and B1/B2 (the barrier between never exceeds the pair outer)
        atoms = [atom("A1", 106, 0, 1), atom("A2", 107, 2, 2), atom("B1", 100, 4, 3), atom("B2", 101, 6, 4),
                 atom("J", 104, 8, 5)]
        rows, _ = self.run_core(atoms, [106, 90, 107, 90, 100, 90, 101, 90, 104])
        reqs = [r for r in rows if r["structure_type"] == REQ]
        self.assertEqual([r["change_kind"] for r in reqs], [FORMED, FORMED, MERGED])
        self.assertEqual(len(reqs[2]["supersedes"]), 2)
        self.assertEqual(set(reqs[2]["member_ids"]), {"A1", "A2", "B1", "B2", "J"})

    def test_lower_side_mirror_via_builder(self):
        rows = [(60, 61, 59, 60), (60, 61, 57, 58), (58, 59, 50.00, 55), (55, 58, 54, 57), (57, 59, 56, 58),
                (58, 59, 55, 56), (56, 57, 49.25, 52), (52, 56, 51, 55), (55, 57, 54, 56)]
        r = formations(rows)
        req = r.structures[(r.structures["orientation"] == LOWER) & (r.structures["structure_type"] == REQ)]
        self.assertEqual(len(req), 1)                             # 50.00 and 49.25: 3 ticks


if __name__ == "__main__":
    unittest.main()
