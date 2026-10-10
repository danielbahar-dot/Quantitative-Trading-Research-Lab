"""Order Block lifecycle, Breaker / Mitigation successors and interactions (OB-I2 / OB-I3; rev 3 §7 – §11, §15.4)."""

import unittest

import pandas as pd

from ob_fixtures import (BREAKER_ROWS, CONCURRENT_ROWS, EARLY_RAID_ROWS, EQUAL_ROWS, INTERACT_ROWS, MITIGATION_ROWS,
                         N2_DELAYED_ROWS, N2_INVALID_ROWS, NO_PRIOR_ROWS, RAID_LOWER_C_ROWS, end, k_of, run)
from src.ict_blocks.pipeline import active_blocks, first_return_candidates

FLIP = {"BULLISH": "BEARISH", "BEARISH": "BULLISH"}


def changes(r, block_id=None):
    lc = r.engine.lifecycle
    if block_id is not None:
        lc = lc[lc["block_id"] == block_id]
    return [(x.to_state, x.reason, k_of(x.at)) for x in lc.itertuples()]


def parent(r, direction):
    b = r.engine.blocks
    return b[b["ordinary_direction"] == direction].iloc[0]


class SuccessorTests(unittest.TestCase):
    def test_breaker_inherits_interval_and_retires_on_its_own_close(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                r = run(BREAKER_ROWS, mirrored=mirrored)
                d0 = "BEARISH" if mirrored else "BULLISH"
                p = parent(r, d0)
                self.assertEqual(changes(r, p["block_id"]),
                                 [("BREAKER", "BREAKER_MOTIF", 10), ("RETIRED", "SUCCESSOR_CLOSE_BEYOND", 12)])
                st = r.engine.stages[r.engine.stages["block_id"] == p["block_id"]].set_index("stage_kind")
                self.assertEqual(st.loc["BREAKER", "direction"], FLIP[d0])
                self.assertEqual(st.loc["BREAKER", "predecessor_stage_id"], st.loc["ORDINARY", "stage_id"])
                # retirement at close 105.5 > inherited upper 105 (not the source high 106): inherited interval
                self.assertEqual(k_of(st.loc["BREAKER", "ended_at"]), 12)
                m = r.engine.motifs.iloc[0]
                self.assertTrue(m["raid_observed"])
                self.assertEqual(r.engine.regions.iloc[0]["source_region_id"], p["source_region_id"])

    def test_mitigation_failure_swing(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                r = run(MITIGATION_ROWS, mirrored=mirrored)
                p = parent(r, "BEARISH" if mirrored else "BULLISH")
                self.assertEqual(changes(r, p["block_id"])[0], ("MITIGATION", "MITIGATION_MOTIF", 10))
                self.assertFalse(r.engine.motifs.iloc[0]["raid_observed"])

    def test_failures_without_successor(self):
        expected = {"EQUAL": (EQUAL_ROWS, "EQUAL_EXTREME"), "RAID_LOWER_C": (RAID_LOWER_C_ROWS, "RAID_WITH_LESS_EXTREME_C"),
                    "NO_PRIOR": (NO_PRIOR_ROWS, "NO_PRIOR_EXTREME"), "EARLY_RAID": (EARLY_RAID_ROWS, "NO_REVERSAL_SWING")}
        for name, (rows, reason) in expected.items():
            for mirrored in (False, True):
                with self.subTest(name=name, mirrored=mirrored):
                    r = run(rows, mirrored=mirrored)
                    p = parent(r, "BEARISH" if mirrored else "BULLISH")
                    ch = changes(r, p["block_id"])
                    self.assertEqual(ch, [("FAILED_FINAL", reason, ch[0][2])])
                    self.assertEqual(len(r.engine.stages[r.engine.stages["block_id"] == p["block_id"]]), 1)
                    # ordinary actionability ends at the failure close
                    at = end(ch[0][2])
                    self.assertNotIn(p["block_id"], set(active_blocks(r, at)["block_id"]))
                    self.assertIn(p["block_id"], set(active_blocks(r, at - pd.Timedelta(minutes=1))["block_id"]))
        r = run(EARLY_RAID_ROWS)
        self.assertEqual(k_of(r.engine.motifs.iloc[0]["first_raid_at"]), 9)        # the earlier raid is kept

    def test_independent_opposing_ordinary_versus_parent_linked_breaker(self):
        r = run(CONCURRENT_ROWS)
        st = r.engine.stages
        bear = st[st["direction"] == "BEARISH"]
        self.assertEqual(sorted(bear["stage_kind"]), ["BREAKER", "ORDINARY"])
        self.assertEqual(bear["block_id"].nunique(), 2)                          # two different objects
        ordinary = bear[bear["stage_kind"] == "ORDINARY"].iloc[0]
        breaker = bear[bear["stage_kind"] == "BREAKER"].iloc[0]
        self.assertTrue(pd.isna(ordinary["predecessor_stage_id"]))              # not a successor of anything
        self.assertFalse(pd.isna(breaker["predecessor_stage_id"]))
        self.assertEqual(k_of(ordinary["available_at"]), k_of(breaker["available_at"]))   # same close, both kept

    def test_delayed_successor_availability_n2(self):
        r = run(N2_DELAYED_ROWS, depth=2)
        p = r.engine.motifs[r.engine.motifs["outcome"] == "BREAKER"].iloc[0]
        self.assertEqual(changes(r, p["block_id"]),
                         [("FAILED_AWAITING_CLASSIFICATION", "ORDINARY_FAILED", 11), ("BREAKER", "BREAKER_MOTIF", 12),
                          ("RETIRED", "SUCCESSOR_CLOSE_BEYOND", 14)])
        # neither stage is actionable while classification is pending
        self.assertNotIn(p["block_id"], set(active_blocks(r, end(11))["block_id"]))
        self.assertIn(p["block_id"], set(active_blocks(r, end(12))["block_id"]))
        self.assertEqual(k_of(p["break_observed_at"]), 11)
        self.assertEqual(k_of(p["successor_available_at"]), 12)
        r = run(N2_INVALID_ROWS, depth=2)
        bad = r.engine.motifs[r.engine.motifs["reason"] == "QUALIFIED_BUT_INVALID_BEFORE_ADMISSION"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(len(r.engine.stages[r.engine.stages["block_id"] == bad.iloc[0]["block_id"]]), 1)

    def test_no_repeated_inversion(self):
        r = run(BREAKER_ROWS)
        kinds = r.engine.stages.groupby("block_id")["stage_kind"].apply(list)
        for v in kinds:
            self.assertLessEqual(sum(k in ("BREAKER", "MITIGATION") for k in v), 1)


class InteractionTests(unittest.TestCase):
    def test_touch_penetration_midpoint_gap_and_visits(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                r = run(INTERACT_ROWS, mirrored=mirrored)
                p = parent(r, "BEARISH" if mirrored else "BULLISH")
                sid = r.engine.stages[r.engine.stages["block_id"] == p["block_id"]].iloc[0]["stage_id"]
                it = r.engine.interactions
                it = it[it["stage_id"] == sid]
                five = {x.kind: k_of(x.at.ceil("5min")) for x in it.itertuples()}
                self.assertEqual(five, {"FIRST_TOUCH": 8, "FIRST_PENETRATION": 9, "FIRST_MIDPOINT": 10,
                                        "GAP_BEYOND_REGION": 11})
                v = r.engine.visits[r.engine.visits["stage_id"] == sid]
                self.assertEqual(list(v["penetrated"]), [False, True, True])    # endpoint-only contact first
                self.assertEqual(list(v["midpoint_observed"]), [False, False, True])
                self.assertEqual(changes(r, p["block_id"])[0][0], "FAILED_FINAL")

    def test_no_formation_or_conversion_bar_retest(self):
        r = run(BREAKER_ROWS)
        st = r.engine.stages.set_index("stage_id")
        for x in r.engine.interactions.itertuples():
            self.assertGreater(x.at - pd.Timedelta(minutes=1), st.loc[x.stage_id, "available_at"] - pd.Timedelta(seconds=1))
        brk = r.engine.stages[r.engine.stages["stage_kind"] == "BREAKER"].iloc[0]
        it = r.engine.interactions[r.engine.interactions["stage_id"] == brk["stage_id"]]
        self.assertTrue((it["at"] > end(10)).all())                             # nothing from the conversion bar

    def test_first_return_candidates_view(self):
        r = run(INTERACT_ROWS)
        p = parent(r, "BULLISH")
        self.assertIn(p["block_id"], set(first_return_candidates(r, end(7))["block_id"]))
        self.assertNotIn(p["block_id"], set(first_return_candidates(r, end(8))["block_id"]))


class DataTests(unittest.TestCase):
    def test_gap_terminates_and_roll_pends(self):
        g = run(BREAKER_ROWS, absent={9})
        self.assertEqual(changes(g)[-1][:2], ("TERMINATED_DATA_GAP", "DATA_GAP"))
        self.assertGreater(int(g.engine.warnings["terminated_blocks"].sum()), 0)
        roll = run(BREAKER_ROWS, contracts=["MNQ 09-26"] * 9 + ["MNQ 12-26"] * 5)
        self.assertEqual(changes(roll)[-1][:2], ("PENDING_ADJUSTMENT", "CONTRACT_CHANGE"))
        self.assertEqual(len(roll.engine.pending), 1)
        self.assertEqual(roll.engine.pending.iloc[0]["contract"], "MNQ 09-26")


if __name__ == "__main__":
    unittest.main()
