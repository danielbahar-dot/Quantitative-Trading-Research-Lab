"""Full-run independent recomputation reconciles on the synthetic worked examples and detects tampering."""

import copy
import unittest

from fvg_fixtures import HISTORY_OK, W1, W5, W6, W7, W8, W9A, W9C, W9D, run
from src.fvg.audit_full import full_reconcile, full_reference, subset_coverage

SCENARIOS = {
    "W1": dict(rows=W1), "W1-mirrored": dict(rows=W1, mirrored=True),
    "W5": dict(rows=W5, timeframes=("5m", "15m")), "W6": dict(rows=W6, timeframes=("5m", "15m")),
    "W7": dict(rows=W7, timeframes=("5m", "15m")), "W7-mirrored": dict(rows=W7, timeframes=("5m", "15m"), mirrored=True),
    "W8": dict(rows=W8, timeframes=("5m", "15m")), "W9A": dict(rows=W9A), "W9C": dict(rows=W9C), "W9D": dict(rows=W9D),
    "gap": dict(rows=W1, absent={5}),
    "roll": dict(rows=W1, contracts=["MNQ 09-26"] * 6 + ["MNQ 12-26"] * 7),
    "history": dict(rows=HISTORY_OK + W1),
    "all-timeframes": dict(rows=W7, timeframes=("1m", "5m", "15m", "1H", "4H", "1D")),
}
QUIET = lambda *_: None  # noqa: E731


class FullReferenceTests(unittest.TestCase):
    def test_full_reference_reconciles(self):
        for name, kw in SCENARIOS.items():
            with self.subTest(name):
                r = run(**kw)
                ref = full_reference(r, log=QUIET)
                rec = full_reconcile(r, ref)
                self.assertEqual(int(rec["missing"].sum() + rec["extra"].sum()), 0, rec.to_string())
                self.assertEqual(ref["off_grid_closes"], 0)

    def test_categories_are_exercised(self):
        r = run(W6, timeframes=("5m", "15m"))
        rec = full_reconcile(r, full_reference(r, log=QUIET)).groupby("category")["reference"].sum()
        for cat in ("zones", "zone_transitions", "zone_mitigation", "bpr_mitigation", "episodes", "bprs", "grades",
                    "groups", "associations"):
            self.assertGreater(rec.get(cat, 0), 0, cat)

    def test_detects_tampered_grade_and_episode(self):
        r = run(W6, timeframes=("5m", "15m"))
        ref = full_reference(r, log=QUIET)
        t = copy.deepcopy(r)
        g = t.engine.grades.copy()
        i = g.index[g["overlap_contribution"] > 0][0]
        g.at[i, "overlap_contribution"] = int(g.at[i, "overlap_contribution"]) + 1
        t.engine.grades = g
        e = t.engine.episodes.copy()
        e["governing_timeframe"] = e["governing_timeframe"].astype(object)
        j = e.index[e["label"] != "FVG_OVERLAP"][0]
        e.at[j, "governing_timeframe"] = "1D"
        t.engine.episodes = e
        rec = full_reconcile(t, ref).groupby("category")[["missing", "extra"]].sum()
        self.assertGreater(rec.loc["grades"].sum(), 0)
        self.assertGreater(rec.loc["episodes"].sum(), 0)

    def test_subset_coverage_reports_zero_covered_rows(self):
        r = run(W6, timeframes=("5m", "15m"))
        cov = subset_coverage(r, [])
        self.assertTrue((cov["covered"] == 0).all())
        self.assertIn("zones", set(cov["category"]))


if __name__ == "__main__":
    unittest.main()
