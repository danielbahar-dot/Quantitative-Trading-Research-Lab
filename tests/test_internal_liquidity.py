"""Internal Liquidity engine (IL-I3; D-145 - D-147): levels, grades, ranges, assignments, membership. Synthetic only."""

import json
import unittest

import pandas as pd

from il_fixtures import EQ, EXTENDED, FLAT, LOWER, REQ, UPPER, Scenario, at, flat_rows, ticks
from src.liquidity.consumption import ACTIVE, CONSUMED, TERMINATED
from src.liquidity.internal_liquidity import (
    BOTH_ADVANCED,
    COINCIDES_WITH_BOUNDARY,
    ESTABLISHED,
    EVIDENCE_SUPERSEDED,
    INSUFFICIENT_BOUNDARY_DATA,
    LEVEL_CONSUMED,
    NO_DATA,
    NOT_GENUINELY_NEW,
    PRE_GAP_SOURCE,
    RANGE_VERSION_EXCLUDES,
    UNBOUNDED,
    active_internal_levels,
)


def level(run, price, side=UPPER, *, last=True):
    rows = run.levels[(run.levels["price_ticks"] == ticks(price)) & (run.levels["side"] == side)]
    assert len(rows), price
    return rows.iloc[-1] if last else rows


def status(run, object_id):
    tr = run.consumption_transitions
    hit = tr[tr["entity_id"] == object_id]
    if hit.empty:
        return ACTIVE, None, None
    row = hit.iloc[0]
    return row["new_state"], row["reason_code"], row["transition_at"]


def members(run, range_version_id=None):
    m = run.memberships
    return m if range_version_id is None else m[m["range_version_id"] == range_version_id]


def e23(bar, *, extend=True):
    rows = flat_rows(16, {8: bar})
    s = Scenario(rows)
    s.daily("DL", LOWER, -100, 1)
    s.daily("DH", UPPER, 180, 1)
    s.htf("H1", UPPER, 99.00, 1)
    s.htf("H2", UPPER, 100.00, 1)
    s.cluster("C1", REQ, UPPER, ["H1", "H2"], 1)
    if extend:
        s.htf("H3", UPPER, 101.00, 5)
        s.cluster("C2", REQ, UPPER, ["H1", "H2", "H3"], 5, change=EXTENDED, supersedes=["C1"])
    return s


class LevelTests(unittest.TestCase):
    def e5(self, k7_bar=(50, 51.50, 49.75, 50)):
        s = Scenario(flat_rows(14, {7: k7_bar}))
        s.swing("S1", UPPER, 50.00, 3)
        s.swing("S2", UPPER, 50.75, 5)
        s.structure("R1", REQ, UPPER, ["S1", "S2"], 5)
        s.swing("S3", UPPER, 51.50, 9)
        s.structure("R2", REQ, UPPER, ["S1", "S2", "S3"], 9, change=EXTENDED, supersedes=["R1"])
        return s.run()

    def test_e5_e6_e7_consolidation_supersede_and_consumption(self):
        run = self.e5()
        l50, l5075, l5150 = (level(run, p) for p in (50.00, 50.75, 51.50))
        self.assertEqual(l5075["evidence_member_ids"], ("S2",))
        self.assertEqual(l5075["change_kind"], EVIDENCE_SUPERSEDED)          # REQ v1 moved to the new outermost
        self.assertEqual(l5075["superseded_evidence_ids"], ("R1",))
        first = level(run, 50.75, last=False).iloc[0]
        self.assertEqual(first["evidence_structure_ids"], ("R1",))
        self.assertEqual(first["consumption_threshold_ticks"], ticks(51.75))
        self.assertEqual(l5150["evidence_structure_ids"], ("R2",))
        self.assertEqual(l5150["grade_tier"], "5m REQ")
        self.assertEqual(l5150["grade_rank"], 2)
        self.assertEqual(l50["grade_tier"], "5m SWING")
        # E6: 20,051.50 consumes 20,050.00 (θ 20,051.00) but not 20,050.75 (θ 20,051.75)
        self.assertEqual(status(run, l50["level_id"])[:2], (CONSUMED, CONSUMED))
        self.assertEqual(status(run, l50["level_id"])[2], at(7))
        self.assertEqual(status(run, l5075["level_id"])[0], ACTIVE)
        # IL-INV-10: level_available_at constant, versions prospective
        for _, g in run.levels.groupby("level_id"):
            self.assertEqual(g["level_available_at"].nunique(), 1)
            self.assertTrue(g["available_at"].is_monotonic_increasing)

    def test_e8_variant_consumes_req_level(self):
        run = self.e5((50, 52.00, 49.75, 50))
        self.assertEqual(status(run, level(run, 50.75)["level_id"])[0], CONSUMED)
        ev = run.consumption_evidence.set_index("object_id").loc[level(run, 50.75)["level_id"]]
        self.assertEqual(ev["excess_ticks"], 1)

    def test_e4_same_close_admission_not_consumed_by_its_bar(self):
        s = Scenario(flat_rows(10, {5: (50, 60, 49.75, 50)}))
        s.swing("S", UPPER, 51.00, 5)
        run = s.run()
        self.assertEqual(status(run, level(run, 51.00)["level_id"])[0], ACTIVE)

    def test_e16_new_level_after_consumption_and_not_genuinely_new(self):
        s = Scenario(flat_rows(16, {6: (50, 51.25, 49.75, 50)}))
        s.swing("S1", UPPER, 50.00, 3)
        s.swing("S1b", UPPER, 50.00, 4)
        s.structure("E1", EQ, UPPER, ["S1", "S1b"], 9)                  # only terminated evidence: no revival
        s.swing("S5", UPPER, 50.00, 12)                                   # genuinely new
        run = s.run()
        rows = level(run, 50.00, last=False)
        ids = list(dict.fromkeys(rows["level_id"]))
        self.assertEqual(len(ids), 2)
        self.assertEqual(status(run, ids[0])[0], CONSUMED)
        self.assertEqual(rows["price_record_id"].nunique(), 1)
        self.assertNotIn("E1", set(x for t in rows["evidence_structure_ids"] for x in t))
        self.assertIn(NOT_GENUINELY_NEW, set(run.audit["kind"]))

    def test_e15_grading_order_and_candle_swing_one_extreme(self):
        s = Scenario(flat_rows(14))
        s.swing("A", UPPER, 70, 4)
        s.swing("B", UPPER, 70, 6)
        s.structure("EQ1", EQ, UPPER, ["A", "B"], 6)
        s.candle("C", UPPER, 80, 8, span=(4, 8))
        s.swing("H", UPPER, 80, 8, tf="1H", span=(4, 8))
        run = s.run()
        eq, one_h = level(run, 70), level(run, 80)
        self.assertEqual((eq["grade_tier"], eq["grade_rank"], eq["confluence"]), ("5m EQ", 3, 2))
        self.assertEqual((one_h["grade_tier"], one_h["grade_rank"], one_h["confluence"]), ("1H SWING", 8, 1))
        self.assertTrue(json.loads(one_h["grade_profile"])["candle_and_swing_coincide"])


class RangeTests(unittest.TestCase):
    def base(self, rows, *, extra=None):
        s = Scenario(rows)
        s.daily("DL", LOWER, -100, 1)
        s.daily("DH", UPPER, 100, 1)
        if extra:
            extra(s)
        return s

    def test_e9_e10_advance_with_opposite_reselection_and_membership_changes(self):
        def extra(s):
            s.htf("L1", LOWER, -40, 3); s.htf("L2", LOWER, -40, 3); s.cluster("EQL", EQ, LOWER, ["L1", "L2"], 3)
            s.htf("U1", UPPER, 180, 3); s.htf("U2", UPPER, 180, 3); s.cluster("EQH", EQ, UPPER, ["U1", "U2"], 3)
            s.swing("IL70", LOWER, -70, 4)
            s.swing("IL40", LOWER, -40, 4)
            s.swing("IU150", UPPER, 150, 4)
            s.swing("IU60", UPPER, 60, 4)
        run = self.base(flat_rows(12, {6: (50, 101.75, 49.75, 98)}), extra=extra).run()
        v1, v2 = run.ranges.iloc[0], run.ranges.iloc[1]
        self.assertEqual((v1["change_kind"], v1["lower_pinned_price_ticks"], v1["upper_pinned_price_ticks"]),
                         (ESTABLISHED, ticks(-100), ticks(100)))
        self.assertEqual(v2["change_kind"], "UPPER_ADVANCED+OPPOSITE_RESELECTED")
        self.assertEqual((v2["lower_pinned_price_ticks"], v2["upper_pinned_price_ticks"]), (ticks(-40), ticks(180)))
        self.assertEqual(v2["available_at"], at(6))
        a = run.assignments.set_index("boundary_assignment_id")
        self.assertEqual(status(run, v1["upper_assignment_id"])[:2], (CONSUMED, CONSUMED))
        self.assertEqual(status(run, v1["lower_assignment_id"])[:2], (TERMINATED, "RELEASED"))
        self.assertEqual(a.loc[v2["lower_assignment_id"], "replaces_assignment_id"], v1["lower_assignment_id"])
        self.assertEqual(status(run, "DL")[0], ACTIVE)                    # the live object is untouched
        m = run.memberships.merge(run.levels.groupby("level_id").tail(1)[["level_id", "price_ticks"]], on="level_id")
        by_price = {p: g for p, g in m.groupby("price_ticks")}
        self.assertEqual(by_price[ticks(-70)].iloc[0]["end_reason"], RANGE_VERSION_EXCLUDES)
        self.assertEqual(by_price[ticks(-70)].iloc[0]["until_at"], at(6))
        self.assertEqual(by_price[ticks(60)].iloc[0]["end_reason"], LEVEL_CONSUMED)
        self.assertEqual(by_price[ticks(150)].iloc[0]["from_at"], at(6))
        self.assertTrue(pd.isna(by_price[ticks(150)].iloc[0]["until_at"]))
        # E13: equality with the active lower boundary excludes; the level stays a member in v1 only
        self.assertEqual(by_price[ticks(-40)].iloc[0]["until_at"], at(6))
        self.assertIn(COINCIDES_WITH_BOUNDARY, set(run.audit["kind"]))

    def test_e11_unbounded_upper_retains_opposite(self):
        run = self.base(flat_rows(10, {6: (50, 101.75, 49.75, 98)}),
                        extra=lambda s: s.swing("IU150", UPPER, 150, 4)).run()
        v2 = run.ranges.iloc[1]
        self.assertEqual((v2["change_kind"], v2["upper_assignment_id"]), ("UPPER_ADVANCED", UNBOUNDED))
        self.assertEqual(v2["lower_assignment_id"], run.ranges.iloc[0]["lower_assignment_id"])
        view = active_internal_levels(run, at(7))
        self.assertEqual(list(view["price_ticks"]), [ticks(150)])
        self.assertTrue(pd.isna(view.iloc[0]["upper_pinned_price"]))

    def test_e12_both_boundaries_in_one_bar(self):
        bar = (50, 102.00, -101.75, 0)
        def farther(s):
            s.daily("DL2", LOWER, -180, 3); s.daily("DH2", UPPER, 180, 3); s.swing("IN", UPPER, 20, 4)
        run = self.base(flat_rows(10, {6: bar}), extra=farther).run()
        v2 = run.ranges.iloc[1]
        self.assertEqual(v2["change_kind"], BOTH_ADVANCED)
        self.assertEqual((v2["lower_pinned_price_ticks"], v2["upper_pinned_price_ticks"]), (ticks(-180), ticks(180)))
        self.assertEqual(status(run, level(run, 20)["level_id"])[0], CONSUMED)
        run = self.base(flat_rows(10, {6: bar}), extra=lambda s: s.daily("DH2", UPPER, 180, 3)).run()
        self.assertEqual(len(run.ranges), 1)
        self.assertEqual(run.range_transitions.iloc[0]["reason_code"], INSUFFICIENT_BOUNDARY_DATA)
        self.assertEqual(run.range_status.iloc[-1]["status"], INSUFFICIENT_BOUNDARY_DATA)

    def test_e20_lower_consumed_no_farther_lower_terminates(self):
        run = self.base(flat_rows(10, {6: (0, 0, -101.75, -90)})).run()
        self.assertEqual(run.range_transitions.iloc[0]["reason_code"], INSUFFICIENT_BOUNDARY_DATA)
        upper = run.ranges.iloc[0]["upper_assignment_id"]
        self.assertEqual(status(run, upper)[:2], (TERMINATED, "RANGE_TERMINATED"))
        self.assertEqual(len(run.assignments), 2)                           # nothing new assigned at e(m)
        self.assertTrue(run.memberships.empty or (run.memberships["until_at"] <= at(6)).all())

    def test_e21_unbounded_then_newer_upper_waits_for_an_event(self):
        rows = flat_rows(12, {7: (-100, -99, -106, -105)})
        s = Scenario(rows)
        s.daily("DL", LOWER, -100, 1)
        s.daily("DH3", UPPER, 300, 3)
        s.daily("DL2", LOWER, -180, 3)
        run = s.run()
        v1, v2 = run.ranges.iloc[0], run.ranges.iloc[1]
        self.assertEqual(v1["upper_assignment_id"], UNBOUNDED)
        self.assertEqual(v2["change_kind"], "LOWER_ADVANCED+OPPOSITE_RESELECTED")
        self.assertEqual((v2["lower_pinned_price_ticks"], v2["upper_pinned_price_ticks"]), (ticks(-180), ticks(300)))
        a = run.assignments.set_index("boundary_assignment_id")
        self.assertTrue(pd.isna(a.loc[v2["upper_assignment_id"], "replaces_assignment_id"]))

    def test_e19_coincident_internal_and_external_separate_statuses(self):
        rows = flat_rows(12, {6: (50, 76.25, 49.75, 50), 9: (50, 76.75, 49.75, 50)})
        s = Scenario(rows)
        s.daily("DL", LOWER, -100, 1)
        s.daily("DH", UPPER, 180, 1)
        s.daily("D75", UPPER, 75, 3, source_k=2)                          # after establishment: non-boundary
        s.swing("S75", UPPER, 75, 4)
        run = s.run()
        lv = level(run, 75)
        self.assertEqual(run.assignments["external_object_id"].tolist().count("D75"), 0)
        self.assertEqual(status(run, lv["level_id"])[2], at(6))
        self.assertEqual(status(run, "D75")[:3], (CONSUMED, CONSUMED, at(9)))
        links = run.price_record_links
        self.assertEqual(set(links.loc[links["price_ticks"] == ticks(75), "object_id"]), {lv["level_id"], "D75"})
        self.assertEqual(links.loc[links["price_ticks"] == ticks(75), "price_record_id"].nunique(), 1)
        self.assertEqual(lv["confluence"], 1)                              # the swing printed the Daily high
        self.assertEqual(lv["external_coincidence"], ("D75",))
        self.assertEqual(lv["grade_tier"], "5m SWING")                    # tier unchanged by External evidence
        self.assertEqual(len(members(run)), 1)


class TieBreakTests(unittest.TestCase):
    """§3.6.4 ties at an equal price: first available_at, then first source_at, then id (all ascending)."""

    def reselect(self, extra):
        # established [-150, 100] at k1; the upper is consumed at k6 (c = 98); the lower is reselected among ties at -100
        s = Scenario(flat_rows(10, {6: (50, 101.75, 49.75, 98)}))
        s.daily("DL", LOWER, -150, 1)
        s.daily("DH", UPPER, 100, 1)
        extra(s)
        run = s.run()
        from src.liquidity.internal_liquidity_audit import reconcile, reference_internal_liquidity
        rec = reconcile(run, reference_internal_liquidity(run))
        self.assertEqual(int(rec["missing"].sum() + rec["extra"].sum()), 0, rec.to_string())
        v2 = run.ranges.iloc[1]
        a = run.assignments.set_index("boundary_assignment_id")
        self.assertEqual(v2["lower_pinned_price_ticks"], ticks(-100))
        tie = run.audit[run.audit["kind"] == "BOUNDARY_TIE_BROKEN"]
        return a.loc[v2["lower_assignment_id"], "external_object_id"], tie

    def test_earlier_available_at_wins_over_id(self):
        def extra(s):
            s.daily("ZZ_early", LOWER, -100, 3)
            s.daily("AA_late", LOWER, -100, 4)
        winner, tie = self.reselect(extra)
        self.assertEqual(winner, "ZZ_early")
        self.assertEqual(tie.iloc[-1]["decided_by"], "available_at")

    def test_earlier_source_at_wins_when_available_at_ties(self):
        def extra(s):
            s.daily("ZZ_src1", LOWER, -100, 3, source_k=1)
            s.daily("AA_src2", LOWER, -100, 3, source_k=2)
        winner, tie = self.reselect(extra)
        self.assertEqual(winner, "ZZ_src1")
        self.assertEqual(tie.iloc[-1]["decided_by"], "source_at")

    def test_cluster_source_at_is_its_earliest_member(self):
        # cluster members sourced at k0 and k2; Daily sourced at k1: the cluster's first source (k0) wins.
        # (a latest-member reading would give k2 and pick the Daily.)
        def extra(s):
            s.htf("L1", LOWER, -100, 3, source_k=0)
            s.htf("L2", LOWER, -100, 3, source_k=2)
            s.cluster("EQL", EQ, LOWER, ["L1", "L2"], 3)
            s.daily("D_src1", LOWER, -100, 3, source_k=1)
        winner, tie = self.reselect(extra)
        self.assertTrue(winner.startswith("xc_"))
        self.assertEqual(tie.iloc[-1]["decided_by"], "source_at")

    def test_id_breaks_a_full_tie(self):
        def extra(s):
            s.daily("ZZ", LOWER, -100, 3, source_k=2)
            s.daily("AA", LOWER, -100, 3, source_k=2)
        winner, tie = self.reselect(extra)
        self.assertEqual(winner, "AA")
        self.assertEqual(tie.iloc[-1]["decided_by"], "id")


class AssignmentTests(unittest.TestCase):
    """E23 / E24 / E25: pinned assignments vs. the live cluster (A-19)."""

    def test_e23_extension_never_moves_assignment(self):
        run = e23((50, 101.75, 49.75, 60)).run()
        ba1, ba2 = run.assignments.iloc[0], run.assignments.iloc[2]
        lineage = ba1["external_object_id"]
        self.assertEqual((ba1["pinned_formation_ref"], ba1["pinned_price_ticks"], ba1["pinned_threshold_ticks"]),
                         ("C1", ticks(100), ticks(101.50)))
        self.assertEqual(ba1["pinned_member_ids"], ("H1", "H2"))
        self.assertEqual(len(run.ranges), 2)                                # no version at the 10:00 extension
        self.assertEqual(status(run, ba1["boundary_assignment_id"])[:3], (CONSUMED, CONSUMED, at(8)))
        self.assertEqual(status(run, lineage)[0], ACTIVE)
        self.assertEqual((ba2["external_object_id"], ba2["pinned_formation_ref"], ba2["pinned_price_ticks"],
                          ba2["selection_kind"], ba2["replaces_assignment_id"]),
                         (lineage, "C2", ticks(101.00), "ADVANCED_OUTWARD", ba1["boundary_assignment_id"]))
        links = run.price_record_links
        cl = links[links["object_id"] == lineage].sort_values("linked_from")
        self.assertEqual(list(cl["price_ticks"]), [ticks(100), ticks(101)])
        self.assertEqual(cl.iloc[0]["unlink_reason"], "VERSION_MOVED")

    def test_e24_both_consumed_advance_skips_cluster(self):
        run = e23((50, 102.75, 49.75, 60)).run()
        ba1, ba2 = run.assignments.iloc[0], run.assignments.iloc[2]
        self.assertEqual(status(run, ba1["external_object_id"])[:3], (CONSUMED, CONSUMED, at(8)))
        self.assertEqual((ba2["external_object_id"], ba2["pinned_price_ticks"]), ("DH", ticks(180)))

    def test_e25_no_extension_both_consumed(self):
        run = e23((50, 101.75, 49.75, 60), extend=False).run()
        ba1, ba2 = run.assignments.iloc[0], run.assignments.iloc[2]
        self.assertEqual(status(run, ba1["boundary_assignment_id"])[2], at(8))
        self.assertEqual(status(run, ba1["external_object_id"])[2], at(8))
        self.assertEqual(ba2["external_object_id"], "DH")


class ContinuityTests(unittest.TestCase):
    def test_e14_e22_gap_terminates_everything_and_reestablishes_post_gap(self):
        s = Scenario(flat_rows(16), absent={8})
        s.daily("DL", LOWER, -100, 1)
        s.daily("DH", UPPER, 100, 1)
        s.swing("PRE", UPPER, 60, 4)
        s.swing("LEAK", UPPER, 70, 12, span=(5, 6))                       # sources before the onset
        s.daily("DL3", LOWER, -80, 11, source_k=11)
        s.daily("DH3", UPPER, 140, 11, source_k=11)
        s.swing("POST", UPPER, 65, 12, span=(10, 11))
        run = s.run()
        for oid in (level(run, 60)["level_id"], "DL", "DH", run.ranges.iloc[0]["upper_assignment_id"]):
            self.assertEqual(status(run, oid)[:3], (TERMINATED, "DATA_GAP", at(8)))
        self.assertEqual(run.range_transitions.iloc[0]["reason_code"], "DATA_GAP")
        second = run.ranges[run.ranges["range_id"] != run.ranges.iloc[0]["range_id"]].iloc[0]
        self.assertTrue(second["post_gap_restricted"])
        self.assertEqual((second["lower_pinned_price_ticks"], second["upper_pinned_price_ticks"]),
                         (ticks(-80), ticks(140)))
        self.assertIn(PRE_GAP_SOURCE, set(run.audit["kind"]))
        self.assertFalse((run.levels["price_ticks"] == ticks(70)).any())
        post = members(run, second["range_version_id"])
        self.assertEqual(set(post["level_id"]), {level(run, 65)["level_id"]})
        st = run.range_status
        self.assertEqual(st.loc[st["status"] == NO_DATA].iloc[0]["from_at"], at(8))
        self.assertIn(INSUFFICIENT_BOUNDARY_DATA, set(st["status"]))

    def test_e17_contract_change_isolates(self):
        contracts = ["MNQ 12-26"] * 8 + ["MNQ 03-27"] * 8
        s = Scenario(flat_rows(16), contracts=contracts)
        s.daily("DL", LOWER, -100, 1)
        s.swing("OLD", UPPER, 60, 4)
        s.daily("DLn", LOWER, -90, 11)
        run = s.run()
        self.assertEqual(status(run, "DL")[:3], (TERMINATED, "CONTRACT_CHANGE", at(8)))
        self.assertEqual(status(run, level(run, 60)["level_id"])[1], "CONTRACT_CHANGE")
        self.assertEqual(list(run.ranges["contract"]), ["MNQ 12-26", "MNQ 03-27"])
        self.assertEqual(run.ranges.iloc[1]["available_at"], at(11))
        self.assertFalse(run.ranges.iloc[1]["post_gap_restricted"])

    def test_trailing_missing_minutes_and_zero_output(self):
        s = Scenario(flat_rows(10), absent={8, 9})
        s.daily("DL", LOWER, -100, 1)
        run = s.run()
        self.assertEqual(status(run, "DL")[1], "DATA_GAP")
        self.assertEqual(run.range_status.iloc[-1]["status"], NO_DATA)
        self.assertTrue(pd.isna(run.range_status.iloc[-1]["until_at"]))
        empty = Scenario(flat_rows(6)).run()
        self.assertTrue(empty.levels.empty and empty.ranges.empty and empty.assignments.empty)
        self.assertEqual(list(empty.range_status["status"]), [INSUFFICIENT_BOUNDARY_DATA])


class PrefixTests(unittest.TestCase):
    """E18 / IL-INV-15: a run at cutoff k equals the full run restricted to facts available by k."""

    def check(self, scenario, cutoffs):
        full = scenario.run()
        for k in cutoffs:
            part = scenario.run(cutoff_k=k)
            cut = at(k)
            for name, key, time in (("levels", "level_version_id", "available_at"),
                                    ("ranges", "range_version_id", "available_at"),
                                    ("assignments", "boundary_assignment_id", "assigned_at")):
                a, b = getattr(full, name), getattr(part, name)
                expected = set(a.loc[a[time] <= cut, key]) if len(a) else set()
                self.assertEqual(set(b[key]) if len(b) else set(), expected, (name, k))
            a, b = full.consumption_transitions, part.consumption_transitions
            self.assertEqual(set(b["transition_id"]), set(a.loc[a["transition_at"] <= cut, "transition_id"]), k)

    def test_prefix_around_admission_consumption_and_range_change(self):
        s = e23((50, 101.75, 49.75, 60))
        s.swing("IU", UPPER, 100.75, 3)
        self.check(s, [1, 4, 5, 7, 8, 9, 15])

    def test_prefix_around_gap(self):
        s = Scenario(flat_rows(16), absent={8})
        s.daily("DL", LOWER, -100, 1)
        s.daily("DL3", LOWER, -80, 11)
        s.swing("PRE", UPPER, 60, 4)
        self.check(s, [7, 9, 10, 11, 15])


if __name__ == "__main__":
    unittest.main()
