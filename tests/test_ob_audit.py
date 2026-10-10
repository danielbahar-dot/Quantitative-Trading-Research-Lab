"""Order Block independent reference, invariants, prefix equivalence and determinism (OB-I4 / OB-I5)."""

import copy
import unittest

import pandas as pd

from ob_fixtures import (BREAKER_ROWS, CONCURRENT_ROWS, EARLY_RAID_ROWS, EQUAL_ROWS, EX151, HIGHER_LOW_ROWS,
                         INTERACT_ROWS, LONG_VISIT_ROWS, MITIGATION_ROWS, N2_DELAYED_ROWS, N2_INVALID_ROWS, NO_PRIOR_ROWS,
                         PLATEAU_OK_ROWS, RAID_LOWER_C_ROWS, RALLY_ROWS, run)
from src.ict_blocks.audit import canonical_rows, full_reference, invariants, prefix_mismatches, reconcile

SCENARIOS = {
    "EX151": dict(rows=EX151), "EX151-m": dict(rows=EX151, mirrored=True), "BREAKER": dict(rows=BREAKER_ROWS),
    "BREAKER-m": dict(rows=BREAKER_ROWS, mirrored=True), "MITIGATION": dict(rows=MITIGATION_ROWS),
    "EQUAL": dict(rows=EQUAL_ROWS), "RAID_LOWER_C": dict(rows=RAID_LOWER_C_ROWS), "NO_PRIOR": dict(rows=NO_PRIOR_ROWS),
    "EARLY_RAID": dict(rows=EARLY_RAID_ROWS), "CONCURRENT": dict(rows=CONCURRENT_ROWS),
    "PLATEAU": dict(rows=PLATEAU_OK_ROWS), "RALLY": dict(rows=RALLY_ROWS), "HIGHER_LOW": dict(rows=HIGHER_LOW_ROWS),
    "INTERACT": dict(rows=INTERACT_ROWS), "LONG_VISIT": dict(rows=LONG_VISIT_ROWS),
    "LONG_VISIT-m": dict(rows=LONG_VISIT_ROWS, mirrored=True), "N2_DELAYED": dict(rows=N2_DELAYED_ROWS, depth=2),
    "N2_INVALID": dict(rows=N2_INVALID_ROWS, depth=2), "gap": dict(rows=BREAKER_ROWS, absent={9}),
    "roll": dict(rows=BREAKER_ROWS, contracts=["MNQ 09-26"] * 9 + ["MNQ 12-26"] * 5),
    "all-timeframes": dict(rows=BREAKER_ROWS, timeframes=("1m", "5m", "15m", "1H", "4H", "1D")),
}
TABLES = ("regions", "episodes", "evidence", "blocks", "stages", "lifecycle", "motifs", "visits", "interactions",
          "depth_versions", "transitions", "warnings", "pending")


class AuditTests(unittest.TestCase):
    def test_reference_reconciles_and_invariants_hold(self):
        for name, kw in SCENARIOS.items():
            with self.subTest(name):
                r = run(**kw)
                rec = reconcile(r, full_reference(r))
                self.assertEqual(int(rec["missing"].sum() + rec["extra"].sum()), 0, rec.to_string())
                inv = invariants(r)
                self.assertEqual(int(inv["violations"].sum()), 0, inv.to_string())

    def test_prefix_equivalence_at_every_cutoff(self):
        for name in ("BREAKER", "BREAKER-m", "MITIGATION", "CONCURRENT", "INTERACT", "LONG_VISIT", "LONG_VISIT-m",
                     "N2_DELAYED", "N2_INVALID", "gap",
                     "roll", "HIGHER_LOW", "PLATEAU"):
            kw = SCENARIOS[name]
            full = run(**kw)
            for k in range(1, len(kw["rows"])):
                if k in kw.get("absent", ()):
                    continue
                with self.subTest(name=name, k=k):
                    mm = prefix_mismatches(full, run(cutoff_k=k, **kw))
                    self.assertEqual(sum(mm.values()), 0, {a: b for a, b in mm.items() if b})

    def test_shuffled_dependency_rows_are_deterministic(self):
        for name in ("BREAKER", "CONCURRENT", "N2_DELAYED"):
            kw = SCENARIOS[name]
            base = run(**kw)
            for seed in (1, 7, 99):
                with self.subTest(name=name, seed=seed):
                    other = run(shuffle_seed=seed, **kw)
                    for t in TABLES:
                        self.assertEqual(canonical_rows(getattr(base.engine, t)), canonical_rows(getattr(other.engine, t)), t)

    def test_reference_detects_tampering(self):
        r = run(BREAKER_ROWS)
        ref = full_reference(r)
        t = copy.deepcopy(r)
        lc = t.engine.lifecycle.copy()
        lc.loc[lc["to_state"] == "BREAKER", "to_state"] = "MITIGATION"
        t.engine.lifecycle = lc
        rec = reconcile(t, ref).groupby("category")[["missing", "extra"]].sum()
        self.assertGreater(rec.loc["lifecycle", "missing"], 0)
        t = copy.deepcopy(r)
        reg = t.engine.regions.copy()
        reg["upper_ticks"] = reg["upper_ticks"] + 1
        t.engine.regions = reg
        self.assertGreater(reconcile(t, ref).groupby("category")["missing"].sum().loc["blocks"], 0)
        self.assertGreater(int(invariants(t)["violations"].sum()), 0)

    def test_reconciliation_rows_per_category_and_timeframe(self):
        r = run(BREAKER_ROWS, timeframes=("1m", "5m", "15m", "1H", "4H", "1D"))
        rec = reconcile(r, full_reference(r))
        self.assertEqual(len(rec), 8 * 6)                        # zero-covered cells are kept
        self.assertTrue((rec["compared_fields"].str.len() > 0).all())
        self.assertGreater(int((rec["reference"] == 0).sum()), 0)

    def test_prefix_detects_payload_change(self):
        full = run(BREAKER_ROWS)
        part = run(BREAKER_ROWS)
        t = copy.deepcopy(part)
        m = t.engine.motifs.copy()
        m["raid_observed"] = ~m["raid_observed"]
        t.engine.motifs = m
        self.assertEqual(sum(prefix_mismatches(full, part).values()), 0)
        self.assertGreater(prefix_mismatches(full, t)["motifs"], 0)



class VisitPrefixTests(unittest.TestCase):
    """Finding 2: ongoing visits are compared through the cutoff (causal reconstruction), never excluded."""

    @classmethod
    def setUpClass(cls):
        from ob_fixtures import end
        cls.full = run(LONG_VISIT_ROWS)
        cls.k = 10                              # the visit started at k9 continues into k11
        cls.part = run(LONG_VISIT_ROWS, cutoff_k=cls.k)
        cls.cut = end(cls.k)

    def test_cutoff_falls_inside_a_visit(self):
        v = self.full.engine.visits
        ongoing = v[(v["started_at"] <= self.cut) & (v["ended_at"] > self.cut)]
        self.assertEqual(len(ongoing), 1)
        pv = self.part.engine.visits.set_index("visit_id").loc[ongoing.iloc[0]["visit_id"]]
        self.assertLess(pv["bars"], ongoing.iloc[0]["bars"])           # the cutoff run reports the partial visit
        self.assertEqual(sum(prefix_mismatches(self.full, self.part).values()), 0)

    def _tampered(self, mask_fn, col, value):
        t = copy.deepcopy(self.part)
        v = t.engine.visits.copy()
        i = v.index[mask_fn(v)][0]
        v[col] = v[col].astype(object)
        v.at[i, col] = value
        t.engine.visits = v
        return t

    def test_detects_ongoing_visit_payload_change(self):
        ongoing = lambda v: v["ended_at"] == self.cut                    # noqa: E731 — last bar at the cutoff
        row = self.part.engine.visits[ongoing(self.part.engine.visits)].iloc[0]
        for col, value in (("max_interior_depth_ticks", 999), ("bars", 99),
                           ("midpoint_observed", not row["midpoint_observed"]), ("penetrated", not row["penetrated"]),
                           ("max_adverse_excursion_ticks", int(row["max_adverse_excursion_ticks"]) + 7)):
            with self.subTest(col):
                self.assertGreater(prefix_mismatches(self.full, self._tampered(ongoing, col, value))["visits"], 0)

    def test_detects_completed_visit_payload_change(self):
        done = lambda v: v["ended_at"] < self.cut                        # noqa: E731
        row = self.part.engine.visits[done(self.part.engine.visits)].iloc[0]
        self.assertGreater(prefix_mismatches(self.full, self._tampered(done, "penetrated", not row["penetrated"]))["visits"], 0)

    def test_duplicates_and_future_rows_are_counted(self):
        t = copy.deepcopy(self.part)
        t.engine.visits = pd.concat([t.engine.visits, t.engine.visits.iloc[[0]]], ignore_index=True)
        mm = prefix_mismatches(self.full, t)
        self.assertGreater(mm["visits_duplicate_ids"], 0)
        self.assertGreater(mm["visits"], 0)
        t = copy.deepcopy(self.part)
        fut = self.full.engine.visits[self.full.engine.visits["started_at"] > self.cut].iloc[[0]]
        t.engine.visits = pd.concat([t.engine.visits, fut], ignore_index=True)
        mm = prefix_mismatches(self.full, t)
        self.assertGreater(mm["visits_future_rows"], 0)


if __name__ == "__main__":
    unittest.main()
