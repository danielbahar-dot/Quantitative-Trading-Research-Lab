"""Internal Liquidity reference replay, invariants and prefix equivalence (IL-I4). Synthetic only."""

import unittest

import pandas as pd

from il_fixtures import EQ, EXTENDED, LOWER, REQ, UPPER, Scenario, flat_rows
from ms_fixtures import SPEC, ohlc_bars, slot_end
from src.liquidity.internal_liquidity import build_internal_liquidity
from src.liquidity.internal_liquidity_audit import (
    internal_liquidity_invariants,
    prefix_mismatches,
    reconcile,
    reference_internal_liquidity,
)
from test_internal_formation import E5


def scenarios():
    out = {}
    s = Scenario(flat_rows(18, {6: (50, 101.75, 49.75, 98), 12: (50, 60, -41.75, -30)}))
    s.daily("DL", LOWER, -100, 1)
    s.daily("DH", UPPER, 100, 1)
    s.htf("L1", LOWER, -40, 3); s.htf("L2", LOWER, -40, 3); s.cluster("EQL", EQ, LOWER, ["L1", "L2"], 3)
    s.htf("U1", UPPER, 180, 3); s.htf("U2", UPPER, 180, 3); s.cluster("EQH", EQ, UPPER, ["U1", "U2"], 3)
    s.swing("A", LOWER, -70, 4); s.swing("B", LOWER, -40, 4); s.swing("C", UPPER, 150, 4); s.swing("D", UPPER, 60, 4)
    s.swing("E", UPPER, 30, 9); s.swing("F", UPPER, 30, 10); s.structure("EQ30", EQ, UPPER, ["E", "F"], 10)
    out["advance_reselect_terminate"] = s
    for name, bar, extend in (("e23", (50, 101.75, 49.75, 60), True), ("e24", (50, 102.75, 49.75, 60), True),
                              ("e25", (50, 101.75, 49.75, 60), False)):
        s = Scenario(flat_rows(16, {8: bar}))
        s.daily("DL", LOWER, -100, 1); s.daily("DH", UPPER, 180, 1)
        s.htf("H1", UPPER, 99.00, 1); s.htf("H2", UPPER, 100.00, 1); s.cluster("C1", REQ, UPPER, ["H1", "H2"], 1)
        if extend:
            s.htf("H3", UPPER, 101.00, 5)
            s.cluster("C2", REQ, UPPER, ["H1", "H2", "H3"], 5, change=EXTENDED, supersedes=["C1"])
        s.swing("S", UPPER, 100.50, 3)
        out[name] = s
    s = Scenario(flat_rows(16, {6: (50, 102.00, -101.75, 0)}), absent={10})
    s.daily("DL", LOWER, -100, 1); s.daily("DH", UPPER, 100, 1)
    s.daily("DL2", LOWER, -180, 3); s.daily("DH2", UPPER, 180, 3)
    s.swing("IN", UPPER, 20, 4); s.swing("OUT", LOWER, -150, 4)
    s.daily("DL3", LOWER, -80, 12); s.swing("POST", UPPER, 65, 14, span=(13, 13))
    out["both_sides_then_gap"] = s
    s = Scenario(flat_rows(16), contracts=["MNQ 12-26"] * 8 + ["MNQ 03-27"] * 8)
    s.daily("DL", LOWER, -100, 1); s.swing("OLD", UPPER, 60, 4); s.daily("DLn", LOWER, -90, 11)
    out["contract_change"] = s
    return out


class ReferenceAndInvariantTests(unittest.TestCase):
    def test_reference_reconciles_and_invariants_hold(self):
        for name, s in scenarios().items():
            with self.subTest(name):
                run = s.run()
                rec = reconcile(run, reference_internal_liquidity(run))
                self.assertEqual(int(rec["missing"].sum() + rec["extra"].sum()), 0, rec.to_string())
                inv = internal_liquidity_invariants(run)
                self.assertEqual(int(inv["violations"].sum()), 0, inv.to_string())

    def test_prefix_equivalence_at_every_cutoff(self):
        for name, s in scenarios().items():
            full = s.run()
            for k in range(1, len(s.rows)):
                if k in s.absent:
                    continue
                with self.subTest(name=name, k=k):
                    self.assertEqual(sum(prefix_mismatches(full, s.run(cutoff_k=k)).values()), 0)

    def test_reference_detects_a_tampered_assignment(self):
        run = scenarios()["e23"].run()
        run.assignments.loc[2, "pinned_price_ticks"] += 1
        rec = reconcile(run, reference_internal_liquidity(run)).set_index("category")
        self.assertGreater(rec.loc["assignments", "missing"], 0)
        inv = internal_liquidity_invariants(run).set_index("invariant")
        self.assertGreater(inv.loc["IL-INV-19 boundary immutability", "violations"], 0)

    def test_invariant_detects_membership_on_boundary(self):
        run = scenarios()["advance_reselect_terminate"].run()
        m = run.memberships
        lower_level = run.levels[run.levels["price_ticks"] == run.ranges.iloc[1]["lower_pinned_price_ticks"]]
        bad = m.iloc[[0]].copy()
        bad["level_id"] = lower_level["level_id"].iloc[0]
        bad["range_version_id"] = run.ranges.iloc[1]["range_version_id"]
        bad["from_at"] = run.ranges.iloc[1]["available_at"]
        bad["until_at"] = None
        run.memberships = pd.concat([m, bad], ignore_index=True)
        inv = internal_liquidity_invariants(run).set_index("invariant")
        self.assertGreater(inv.loc["IL-INV-8 strict membership", "violations"], 0)


class EndToEndTests(unittest.TestCase):
    def test_pipeline_from_canonical_bars_with_grammar_recomputation(self):
        bars = ohlc_bars(E5, "5m")
        run = build_internal_liquidity(bars, SPEC, instrument_id="MNQ", replay_cutoff=slot_end(len(E5) - 1, "5m"))
        self.assertGreater(len(run.levels), 0)
        rec = reconcile(run, reference_internal_liquidity(run))
        self.assertEqual(int(rec["missing"].sum() + rec["extra"].sum()), 0, rec.to_string())
        inv = internal_liquidity_invariants(run, SPEC).set_index("invariant")
        self.assertEqual(int(inv["violations"].sum()), 0, inv.to_string())
        self.assertGreater(inv.loc["IL-INV-16 internal D-134 grammar (4-tick link)", "checked"], 0)


if __name__ == "__main__":
    unittest.main()
