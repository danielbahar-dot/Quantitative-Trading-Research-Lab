"""FVG-I2 / FVG-I3: interaction, lifecycle, resets, relationships, BPR and grading (D-149, D-150, D-152).

Synthetic worked examples of the design (§5), mirrored where the rule is directional.
"""

import unittest

import pandas as pd

from fvg_fixtures import W1, W2, W5, W6, W7, W8, ZONE3, end, events, mirror, run, tk, zone_at
from ms_fixtures import SPEC, ohlc_bars
from src.fvg.engine import (
    BPR,
    FVG_OVERLAP,
    MTF_BPR,
    UNDEFINED,
    _groups,
    relationships,
)
from src.fvg.formation import BEARISH, BULLISH
from src.fvg.pipeline import active_bprs, active_fvg_zones, build_fvg, rank_zones

BOTH = (False, True)


def t1(k, minute):
    """UTC instant of minute ``minute`` (1..5) inside 5m observation k."""
    return end(k) - pd.Timedelta(minutes=5 - minute)


def transitions(r, zone_id):
    tr = r.engine.zone_transitions
    tr = tr[tr["entity_id"] == zone_id].sort_values("transition_at")
    return [(x.new_state, x.transition_at, x.reason_code) for x in tr.itertuples()]


class MitigationLifecycleTests(unittest.TestCase):
    def test_w1_milestones_conversion_retirement(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(W1, mirrored=m)
                z = zone_at(r, 101.00, 102.25, m)
                fvg = events(r, z["zone_id"], "FVG")
                self.assertEqual(fvg["PENETRATION"], t1(4, 1))   # k3 touches the near boundary only
                self.assertEqual(fvg["MIDPOINT"], t1(5, 1))
                self.assertEqual(fvg["FULL"], t1(6, 1))
                self.assertNotIn("GAP_THROUGH", fvg)
                self.assertEqual(transitions(r, z["zone_id"]),
                                 [("IFVG", end(8), "CONVERTED"), ("RETIRED", end(12), "RETIRED")])
                ifvg = events(r, z["zone_id"], "IFVG")
                self.assertEqual(ifvg["PENETRATION"], t1(10, 1))   # 18:46 near contact is not mitigation
                self.assertEqual(ifvg["FULL"], t1(11, 1))
                spanning = r.engine.mitigation[(r.engine.mitigation["object_id"] == z["zone_id"])
                                               & (r.engine.mitigation["kind"] == "FULL")]
                self.assertEqual(spanning["observation_class"].iloc[0], "SPANNING")

    def test_w2_conversion_bar_ordering_1m(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(W2, tf="1m", mirrored=m)
                z = zone_at(r, 101.00, 102.25, m)
                fvg, ifvg = events(r, z["zone_id"], "FVG"), events(r, z["zone_id"], "IFVG")
                conv = end(3, "1m")
                self.assertEqual((fvg["PENETRATION"], fvg["MIDPOINT"], fvg["FULL"]), (conv, conv, conv))
                self.assertEqual(transitions(r, z["zone_id"])[0], ("IFVG", conv, "CONVERTED"))
                self.assertEqual(ifvg["PENETRATION"], end(4, "1m"))    # the conversion bar is not an IFVG retest

    def test_w4_observation_classes(self):
        base = ZONE3 + [(104.5, 104.75, 103, 103.0)]
        cases = {
            "beyond": ((100.0, 100.75, 99.5, 100.25), {"GAP_THROUGH"}, [("IFVG", end(4), "CONVERTED")]),
            "far contact": ((100.5, 101.0, 100.0, 101.0), {"PENETRATION", "MIDPOINT", "FULL", "DEPTH"}, []),
            "spanning": ((103.0, 103.25, 100.75, 101.5), {"PENETRATION", "MIDPOINT", "FULL", "DEPTH"}, []),
        }
        for name, (bar, kinds, trs) in cases.items():
            for m in BOTH:
                with self.subTest(case=name, mirrored=m):
                    r = run(base + [bar], mirrored=m)
                    z = zone_at(r, 101.00, 102.25, m)
                    fvg = events(r, z["zone_id"], "FVG")
                    self.assertEqual(set(fvg), kinds)
                    self.assertTrue(all(v == t1(4, 1) for v in fvg.values()))
                    self.assertEqual(transitions(r, z["zone_id"]), trs)

    def test_wick_beyond_far_bound_without_close_does_not_convert(self):
        r = run(W1[:8])
        z = zone_at(r, 101.00, 102.25)
        self.assertEqual(transitions(r, z["zone_id"]), [])     # k6 wick below; k7 close == lower


class ResetTests(unittest.TestCase):
    def test_data_gap_terminates_without_inference(self):
        r = run(W1, absent={5})
        z = zone_at(r, 101.00, 102.25, tf="5m")
        onset = t1(5, 1)
        self.assertEqual(transitions(r, z["zone_id"]), [("TERMINATED", onset, "DATA_GAP")])
        self.assertEqual(set(events(r, z["zone_id"])), {"PENETRATION", "DEPTH"})
        self.assertEqual(len(r.engine.warnings), 1)
        self.assertEqual(r.engine.warnings["at"].iloc[0], onset)
        later = r.zones[r.zones["available_at"] > onset]
        self.assertTrue(len(later) >= 1)

    def test_pure_contract_change_guard_and_pending(self):
        contracts = ["MNQ 09-26"] * 6 + ["MNQ 12-26"] * 7
        r = run(W1, contracts=contracts)
        z = zone_at(r, 101.00, 102.25, tf="5m")
        first_new_bar = t1(6, 1)
        self.assertEqual(transitions(r, z["zone_id"]), [("PENDING_ADJUSTMENT", first_new_bar, "CONTRACT_CHANGE")])
        fvg = events(r, z["zone_id"])
        self.assertNotIn("FULL", fvg)                           # the 18:31 bar never evaluates the old zone
        self.assertTrue(all(v < first_new_bar for v in fvg.values()))
        self.assertIn(z["zone_id"], set(r.engine.pending["object_id"]))
        self.assertTrue(r.engine.warnings.empty)
        trig = r.engine.zone_transitions["trigger_ref"].iloc[0]
        self.assertTrue(trig.startswith("BAR_SPAN:MNQ|MNQ 12-26|1m|"))

    def test_trailing_missing_data(self):
        r = run(W1[:6] + [None, None], absent={6, 7})
        z = zone_at(r, 101.00, 102.25)
        self.assertEqual(transitions(r, z["zone_id"])[0][2], "DATA_GAP")


class RelationshipTests(unittest.TestCase):
    def test_w5_group_contribution(self):
        r = run(W5, timeframes=("5m", "15m"))
        ep = r.engine.episodes
        self.assertEqual(sorted(ep["label"]), [FVG_OVERLAP] * 3)
        z15 = r.zones[r.zones["timeframe"] == "15m"]["zone_id"].iloc[0]
        g = r.engine.grades[r.engine.grades["zone_id"] == z15].iloc[-1]
        self.assertEqual((len(g["partner_zone_ids"]), g["overlap_contribution"]), (3, 1))
        for z5 in r.zones[r.zones["timeframe"] == "5m"]["zone_id"]:
            self.assertEqual(r.engine.grades[r.engine.grades["zone_id"] == z5].iloc[-1]["overlap_contribution"], 1)

    def test_w1_bpr_survives_opposite_direction_parent_retirement(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(W1, mirrored=m)
                b = r.engine.bprs
                self.assertEqual(len(b), 1)
                self.assertEqual(b["label"].iloc[0], BPR)
                self.assertEqual(b["direction"].iloc[0], BEARISH if m else BULLISH)
                self.assertEqual(b["available_at"].iloc[0], end(11))
                self.assertTrue(pd.isna(b["exit_at"].iloc[0]))       # parent retired at 19:05; the BPR survives
                parent = zone_at(r, 101.00, 102.25, m)
                self.assertEqual(transitions(r, parent["zone_id"])[-1][0], "RETIRED")
                self.assertEqual(len(active_bprs(r, end(12))), 1)

    def test_w6_mtf_bpr_parent_inversion_and_own_retirement(self):
        r = run(W6, timeframes=("5m", "15m"))
        b = r.engine.bprs
        b = b[b["label"] == MTF_BPR].sort_values("available_at").iloc[0]
        self.assertEqual((b["direction"], b["governing_timeframe"], b["available_at"]), (BEARISH, "15m", end(14)))
        self.assertEqual((b["lower_ticks"], b["upper_ticks"]), (tk(101.75), tk(102.25)))
        self.assertEqual((b["exit_state"], b["exit_at"]), ("RETIRED", end(20)))
        a = zone_at(r, 101.00, 102.25, tf="5m")
        ep = r.engine.episodes
        pair = ep[(ep["zone_a"].isin([a["zone_id"]])) | (ep["zone_b"].isin([a["zone_id"]]))]
        labels = list(pair.sort_values("created_at")["label"])
        self.assertIn(FVG_OVERLAP, labels[1:])                    # after A's inversion the pair is same-direction

    def test_w7_conversion_created_mtf_bpr(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(W7, timeframes=("5m", "15m"), mirrored=m)
                b = r.engine.bprs
                conv = b[b["available_at"] == end(9)]
                self.assertEqual(len(conv), 1)
                c = conv.iloc[0]
                self.assertEqual((c["label"], c["direction"], c["governing_timeframe"]),
                                 (MTF_BPR, BULLISH if m else BEARISH, "5m"))
                ep = r.engine.episodes
                e = ep[ep["relationship_id"] == c["relationship_id"]].iloc[0]
                self.assertEqual(len(e["movers"]), 1)
                self.assertTrue(pd.isna(c["exit_at"]) or c["exit_at"] > end(9))

    def test_w8_simultaneous_conversions_no_transient_bpr(self):
        r = run(W8, timeframes=("5m", "15m"))
        b = r.engine.bprs
        self.assertEqual(sorted(b["available_at"]), [end(9), end(10)])   # only the 18:50 and 18:55 BPRs
        ep = r.engine.episodes
        at19 = ep[ep["created_at"] == end(11)]
        self.assertTrue((at19["label"] == FVG_OVERLAP).all())
        self.assertTrue(((at19["stage_a"] == "IFVG") | (at19["stage_b"] == "IFVG")).all())
        for key, g in ep.groupby(["zone_a", "zone_b"]):
            self.assertLessEqual(len(g), 3)

    def test_undefined_direction_logic_isolated(self):
        """Synthetic logic-only fixture (unreachable on the frozen schedule, §3.7.5): two opposite parents
        admitted at the same instant on different timeframes, overlapping."""
        t = pd.Timestamp("2026-09-14 14:00", tz="UTC")
        zones = pd.DataFrame([
            {"zone_id": "fz_a", "timeframe": "5m", "contract": "C", "lower_ticks": 100, "upper_ticks": 110,
             "original_direction": BULLISH, "width_ticks": 10, "available_at": t, "span_start": t - pd.Timedelta("15min"),
             "normalization_status": "OK", "normalized_gap_strength": 1.0, "strength_num": 1, "strength_den": 1},
            {"zone_id": "fz_b", "timeframe": "15m", "contract": "C", "lower_ticks": 105, "upper_ticks": 120,
             "original_direction": BEARISH, "width_ticks": 15, "available_at": t, "span_start": t - pd.Timedelta("45min"),
             "normalization_status": "OK", "normalized_gap_strength": 1.0, "strength_num": 1, "strength_den": 1}])
        exits = {z: {"conv_ns": None, "exit_ns": None, "exit_kind": None, "episode": 0} for z in ("fz_a", "fz_b")}
        episodes, _, _, _ = relationships(zones, exits, instrument_id="MNQ")
        self.assertEqual(len(episodes), 1)
        self.assertEqual((episodes[0]["label"], episodes[0]["direction"], episodes[0]["governing_timeframe"]),
                         (MTF_BPR, UNDEFINED, None))


class GradingTests(unittest.TestCase):
    def test_grouping_partial_transitive_and_contact(self):
        def p(zid, a, b):
            return {"zone_id": zid, "span": (a, b), "timeframe": "5m", "width": 1, "available_ns": b}
        chain = _groups([p("x", 0, 10), p("y", 5, 15), p("z", 12, 20)])           # x–y–z transitive
        self.assertEqual(len(chain), 1)
        contact = _groups([p("x", 0, 10), p("y", 10, 20)])                         # end-to-start contact
        self.assertEqual(len(contact), 2)

    def test_rank_nulls_below_values_and_tiebreaks(self):
        v = pd.DataFrame([
            {"zone_id": "a", "timeframe_rank": 2, "overlap_contribution": 1, "normalization_status": "OK",
             "normalized_gap_strength": 0.5, "original_width_ticks": 4, "available_at": pd.Timestamp(1, tz="UTC")},
            {"zone_id": "b", "timeframe_rank": 2, "overlap_contribution": 1, "normalization_status": "INSUFFICIENT_HISTORY",
             "normalized_gap_strength": None, "original_width_ticks": 40, "available_at": pd.Timestamp(1, tz="UTC")},
            {"zone_id": "c", "timeframe_rank": 2, "overlap_contribution": 2, "normalization_status": "ZERO_BASELINE",
             "normalized_gap_strength": None, "original_width_ticks": 1, "available_at": pd.Timestamp(1, tz="UTC")},
            {"zone_id": "d", "timeframe_rank": 3, "overlap_contribution": 0, "normalization_status": "OK",
             "normalized_gap_strength": 0.1, "original_width_ticks": 1, "available_at": pd.Timestamp(1, tz="UTC")}])
        self.assertEqual(list(rank_zones(v)["zone_id"]), ["d", "c", "a", "b"])

    def test_view_marks_rank_and_stage_scoped_mitigation(self):
        r = run(W1)
        view = active_fvg_zones(r, end(12))
        self.assertTrue((view["stage"] == "FVG").all())
        self.assertEqual(list(view["priority_rank"]), list(range(1, len(view) + 1)))


if __name__ == "__main__":
    unittest.main()
