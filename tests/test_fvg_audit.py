"""FVG-I5: independent reference, invariants and prefix equivalence on the synthetic worked examples."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
