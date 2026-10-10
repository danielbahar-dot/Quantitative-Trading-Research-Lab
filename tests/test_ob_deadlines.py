"""Ownership-deadline regressions (OB review finding 1; rev 3 §6.2 / §6.3, §22).

Anchor source k2 (confirmed k3), departure FVG C2 k4 (confirmed k5), first validation close k6.  Whether the
admission waits past k6 depends only on whether bar k6 (or an equal-extreme plateau through it) can still become a
new same-side swing that would end the window before the evidence (D-154: the window ends before a new same-side
swing's span).  Each case is mirrored and compared against genuinely truncated builds at every bar.
"""

import unittest

from ob_fixtures import end, k_of, run
from src.ict_blocks.audit import canonical_rows, full_reference, reconcile
from src.ict_blocks.pipeline import active_blocks, discovery_status

HEAD = [(108, 109, 104, 105), (105, 106, 100, 101), (106, 107, 99, 100), (100, 101, 99.5, 100.5),
        (100.5, 104, 100.25, 103.5), (103.5, 106, 102, 105)]
TAIL = [(108.5, 110, 104, 109), (109, 111, 105, 110)]
CASES = {
    # k6 low 102.5 > k5 low 102: k6 can never be a swing low → ownership knowable at k6
    "not_left_qualified": (HEAD + [(105, 108, 102.5, 107.5), (107.5, 109, 103, 108.5)] + TAIL, "ADMITTED", 6),
    # k6 is a left-qualified candidate; k7 has a lower low → denied at k7 → admitted at k7
    "candidate_denied": (HEAD + [(105, 108, 101, 107.5), (107.5, 109, 100.75, 108.5)] + TAIL, "ADMITTED", 7),
    # k6 is confirmed as a new swing low at k7 → the window ends before k6 → superseded at k7 (never admitted)
    "candidate_confirmed": (HEAD + [(105, 108, 101, 107.5), (107.5, 109, 103, 108.5)] + TAIL, "SUPERSEDED", 7),
    # equal-low plateau k6..k7 (candidate); k8 lower → denied at k8 → admitted at k8
    "plateau_denied": (HEAD + [(105, 108, 101, 107.5), (107.5, 109, 101, 108.5), (108.5, 110, 100.5, 109)] + TAIL,
                       "ADMITTED", 8),
    # equal-low plateau k6..k7 confirmed at k8 → superseded at k8
    "plateau_confirmed": (HEAD + [(105, 108, 101, 107.5), (107.5, 109, 101, 108.5), (108.5, 110, 104, 109)] + TAIL,
                          "SUPERSEDED", 8),
}


def own_episode(r, mirrored):
    e = r.engine.episodes
    return e[(e["direction"] == ("BEARISH" if mirrored else "BULLISH"))].sort_values("opened_at").iloc[0]


class OwnershipDeadlineTests(unittest.TestCase):
    def test_decision_instants(self):
        for name, (rows, status, k) in CASES.items():
            for mirrored in (False, True):
                with self.subTest(name=name, mirrored=mirrored):
                    r = run(rows, mirrored=mirrored)
                    ep = own_episode(r, mirrored)
                    self.assertEqual((ep["status"], k_of(ep["decided_at"])), (status, k))
                    rec = reconcile(r, full_reference(r))
                    self.assertEqual(int(rec["missing"].sum() + rec["extra"].sum()), 0, rec.to_string())

    def test_full_run_views_equal_truncated_builds_around_deadlines(self):
        for name, (rows, _status, k_dec) in CASES.items():
            for mirrored in (False, True):
                full = run(rows, mirrored=mirrored)
                for k in range(3, len(rows)):
                    part = run(rows, mirrored=mirrored, cutoff_k=k)
                    for j in range(3, k + 1):
                        with self.subTest(name=name, mirrored=mirrored, cutoff=k, at=j):
                            for view in (discovery_status, active_blocks):
                                self.assertEqual(canonical_rows(view(full, end(j))), canonical_rows(view(part, end(j))))
                    if k == k_dec - 1:          # one bar before the decision: still waiting, nothing admitted
                        ep = own_episode(part, mirrored)
                        self.assertEqual(ep["status"], "WAITING_FOR_DEPARTURE")


if __name__ == "__main__":
    unittest.main()
