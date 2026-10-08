"""Strategy-facing FVG views are causal: a full-run historical query equals a genuinely truncated run."""

import unittest

from fvg_fixtures import W1, W6, W7, W8, end, run
from src.fvg.audit import canonical_rows
from src.fvg.pipeline import (FUTURE_LIFECYCLE, active_bprs, active_fvg_zones, active_overlaps, bprs_as_of,
                              episodes_as_of, stages_as_of)

SCENARIOS = {
    "W1": dict(rows=W1), "W6": dict(rows=W6, timeframes=("5m", "15m")),
    "W7": dict(rows=W7, timeframes=("5m", "15m")), "W8": dict(rows=W8, timeframes=("5m", "15m")),
    "W6-mirrored": dict(rows=W6, timeframes=("5m", "15m"), mirrored=True),
    "gap": dict(rows=W1, absent={5}),
}
VIEWS = {
    "zones": active_fvg_zones,
    "bprs": active_bprs,
    "bprs_undefined": lambda r, t: active_bprs(r, t, include_undefined=True),
    "overlaps": active_overlaps,
    "bprs_as_of": bprs_as_of, "episodes_as_of": episodes_as_of, "stages_as_of": stages_as_of,
}


def _views(r, t):
    return {name: canonical_rows(f(r, t)) for name, f in VIEWS.items()}


class CausalViewTests(unittest.TestCase):
    def test_full_run_query_equals_truncated_run_before_at_and_after_exits(self):
        """For every cutoff k and every query time j <= k: full-run view at e(j) == cutoff-k run view at e(j)."""
        for name, kw in SCENARIOS.items():
            full = run(**kw)
            n = len(kw["rows"])
            full_views = {j: _views(full, end(j)) for j in range(n) if j not in kw.get("absent", ())}
            for k in range(n):
                if k in kw.get("absent", ()):
                    continue
                part = run(cutoff_k=k, **kw)
                for j, expected in full_views.items():
                    if j > k:
                        continue
                    for view, rows in _views(part, end(j)).items():
                        with self.subTest(name=name, cutoff=k, at=j, view=view):
                            self.assertEqual(rows, expected[view])

    def test_scenarios_exercise_lifecycle_exits(self):
        """The regression covers objects that exit after the query time (otherwise it would be vacuous)."""
        full = run(W6, timeframes=("5m", "15m"))
        exited = full.engine.bprs.dropna(subset=["exit_at"])
        self.assertGreater(len(exited), 0)
        ended = full.engine.episodes.dropna(subset=["ended_at"])
        self.assertGreater(len(ended), 0)
        b = exited.iloc[0]
        before = b["exit_at"] - (end(1) - end(0))
        live = active_bprs(full, before)
        self.assertIn(b["bpr_id"], set(live["bpr_id"]))
        projected = bprs_as_of(full, before).set_index("bpr_id").loc[b["bpr_id"]]
        self.assertTrue(all(projected[c] is None or projected[c] != projected[c] for c in FUTURE_LIFECYCLE["bprs"][1]))
        at_exit = bprs_as_of(full, b["exit_at"]).set_index("bpr_id").loc[b["bpr_id"]]
        self.assertEqual(at_exit["exit_state"], b["exit_state"])
        self.assertNotIn(b["bpr_id"], set(active_bprs(full, b["exit_at"])["bpr_id"]))

    def test_active_views_expose_no_exit_metadata(self):
        full = run(W6, timeframes=("5m", "15m"))
        for column in FUTURE_LIFECYCLE["bprs"][1]:
            self.assertNotIn(column, active_bprs(full, end(5)).columns)
            self.assertNotIn(column, active_bprs(full, end(5), include_undefined=True).columns)
        for column in FUTURE_LIFECYCLE["episodes"][1]:
            self.assertNotIn(column, active_overlaps(full, end(5)).columns)

    def test_audit_history_is_preserved(self):
        full = run(W6, timeframes=("5m", "15m"))
        self.assertTrue(full.engine.bprs["exit_at"].notna().any())
        self.assertTrue(full.engine.episodes["ended_at"].notna().any())


if __name__ == "__main__":
    unittest.main()
