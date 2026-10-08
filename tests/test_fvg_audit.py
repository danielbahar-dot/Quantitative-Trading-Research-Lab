"""FVG-I5: independent reference, invariants and prefix equivalence on the synthetic worked examples."""

import copy
import unittest

import pandas as pd

from fvg_fixtures import W1, W2, W5, W6, W7, W8, W9A, W9C, W9D, HISTORY_OK, run
from src.fvg.audit import invariants, prefix_mismatches, reconcile, reference

SCENARIOS = {
    "W1": dict(rows=W1), "W1-mirrored": dict(rows=W1, mirrored=True), "W2-1m": dict(rows=W2, tf="1m"),
    "W5": dict(rows=W5, timeframes=("5m", "15m")), "W6": dict(rows=W6, timeframes=("5m", "15m")),
    "W7": dict(rows=W7, timeframes=("5m", "15m")), "W7-mirrored": dict(rows=W7, timeframes=("5m", "15m"), mirrored=True),
    "W8": dict(rows=W8, timeframes=("5m", "15m")), "W9A": dict(rows=W9A), "W9C": dict(rows=W9C), "W9D": dict(rows=W9D),
    "gap": dict(rows=W1, absent={5}),
    "roll": dict(rows=W1, contracts=["MNQ 09-26"] * 6 + ["MNQ 12-26"] * 7),
    "history": dict(rows=HISTORY_OK + W1),
    "all-timeframes": dict(rows=W7, timeframes=("1m", "5m", "15m", "1H", "4H", "1D")),
}


class AuditTests(unittest.TestCase):
    def test_reference_reconciles_and_invariants_hold(self):
        for name, kw in SCENARIOS.items():
            with self.subTest(name):
                r = run(**kw)
                rec = reconcile(r, reference(r))
                self.assertEqual(int(rec["missing"].sum() + rec["extra"].sum()), 0, rec.to_string())
                inv = invariants(r)
                self.assertEqual(int(inv["violations"].sum()), 0, inv.to_string())

    def test_prefix_equivalence_at_every_cutoff(self):
        for name in ("W1", "W6", "W7", "W8", "W9D", "gap", "roll"):
            kw = SCENARIOS[name]
            full = run(**kw)
            for k in range(1, len(kw["rows"])):
                if k in kw.get("absent", ()):
                    continue
                with self.subTest(name=name, k=k):
                    mm = prefix_mismatches(full, run(cutoff_k=k, **kw))
                    self.assertEqual(sum(mm.values()), 0, mm)

    def test_reference_detects_a_tampered_conversion(self):
        r = run(W1)
        tr = r.engine.zone_transitions
        r.engine.zone_transitions = tr.assign(transition_at=tr["transition_at"] + __import__("pandas").Timedelta(minutes=5))
        rec = reconcile(r, reference(r)).set_index("category")
        self.assertGreater(rec.loc["zone_transitions", "missing"], 0)


def _tampered(r, table, column, row_filter, change):
    """A deep copy of run ``r`` with ``column`` of the first ``row_filter`` row of ``table`` changed (ids kept)."""
    t = copy.deepcopy(r)
    holder = t.engine if hasattr(t.engine, table) else t
    f = getattr(holder, table).copy()
    idx = f.index[row_filter(f)][0]
    f[column] = f[column].astype(object)
    f.at[idx, column] = change(f.at[idx, column])
    setattr(holder, table, f)
    return t


class PrefixComparatorDetectsPayloadChanges(unittest.TestCase):
    """prefix_mismatches must see payload changes that keep every id, and duplicates."""

    @classmethod
    def setUpClass(cls):
        cls.full = run(W6, timeframes=("5m", "15m"))
        cls.part = run(W6, timeframes=("5m", "15m"))      # same cutoff: an exact prefix of itself

    def assert_detects(self, tampered, key):
        self.assertEqual(sum(prefix_mismatches(self.full, self.part).values()), 0)
        mm = prefix_mismatches(self.full, tampered)
        self.assertGreater(mm[key], 0, mm)

    def test_penetration_depth(self):
        self.assert_detects(_tampered(self.part, "mitigation", "penetration_depth_ticks",
                                      lambda f: f["kind"].astype(str) == "DEPTH", lambda v: int(v) + 1), "mitigation")

    def test_zone_bounds(self):
        self.assert_detects(_tampered(self.part, "zones", "lower_ticks", lambda f: f.index >= 0, lambda v: int(v) - 1),
                            "zones")

    def test_bpr_governing_timeframe(self):
        self.assert_detects(_tampered(self.part, "bprs", "governing_timeframe", lambda f: f.index >= 0,
                                      lambda v: "5m" if v != "5m" else "15m"), "bprs")

    def test_group_contribution(self):
        self.assert_detects(_tampered(self.part, "grades", "overlap_contribution",
                                      lambda f: f["overlap_contribution"] > 0, lambda v: int(v) + 1), "grades")

    def test_lifecycle_metadata(self):
        self.assert_detects(_tampered(self.part, "episodes", "end_reason", lambda f: f["ended_at"].notna(),
                                      lambda v: "PARENT_RETIRED" if v != "PARENT_RETIRED" else "PARENT_STAGE_CHANGED"),
                            "episodes")
        self.assert_detects(_tampered(self.part, "bprs", "exit_at", lambda f: f["exit_at"].notna(),
                                      lambda v: v + pd.Timedelta(minutes=5)), "bprs")
        self.assert_detects(_tampered(self.part, "stages", "end_kind", lambda f: f["end_kind"].notna(),
                                      lambda v: "RETIRED" if v != "RETIRED" else "CONVERTED"), "stages")

    def test_strategy_view_changes_with_tampered_grade(self):
        t = _tampered(self.part, "grades", "overlap_contribution", lambda f: f["overlap_contribution"] > 0,
                      lambda v: int(v) + 5)
        mm = prefix_mismatches(self.full, t)
        self.assertGreater(mm["grades"], 0)

    def test_duplicates_are_counted_separately(self):
        t = copy.deepcopy(self.part)
        t.engine.mitigation = pd.concat([t.engine.mitigation, t.engine.mitigation.iloc[[0]]], ignore_index=True)
        mm = prefix_mismatches(self.full, t)
        self.assertGreater(mm["mitigation_duplicate_ids"], 0)
        self.assertGreater(mm["mitigation_duplicate_rows"], 0)
        self.assertGreater(mm["mitigation"], 0)


if __name__ == "__main__":
    unittest.main()
