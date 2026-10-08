"""FVG-I4 first FVG in a directional swing leg (D-151). Synthetic, frozen 2/2 swings, mirrored."""

import unittest

import pandas as pd

from fvg_fixtures import W1, W9A, W9B, W9C, W9D, end, run, zone_at

BOTH = (False, True)


def assoc(r, zone_id):
    a = r.associations
    return a[a["zone_id"] == zone_id]


class AssociationTests(unittest.TestCase):
    def test_w9a_c2_is_the_swing_candle_and_delayed_association(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(W9A, mirrored=m)
                first = assoc(r, zone_at(r, 109.50, 110.00, m)["zone_id"]).iloc[0]
                self.assertTrue(first["is_first"])
                self.assertEqual(first["formation_available_at"], end(3))
                self.assertEqual(first["association_available_at"], end(4))
                self.assertEqual(first["deadline_rule"], "PENDING_CANDIDATE_AT_C2")
                later = assoc(r, zone_at(r, 112.50, 113.00, m)["zone_id"]).iloc[0]
                self.assertFalse(later["is_first"])
                self.assertEqual(later["association_available_at"], later["formation_available_at"])

    def test_w9b_higher_low_does_not_restart(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(W9B, mirrored=m)
                self.assertTrue(assoc(r, zone_at(r, 103.00, 103.50, m)["zone_id"]).iloc[0]["is_first"])
                fb = assoc(r, zone_at(r, 113.00, 113.25, m)["zone_id"]).iloc[0]
                self.assertFalse(fb["is_first"])

    def test_w9c_more_extreme_origin_starts_new_leg(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                r = run(W9C, mirrored=m)
                fb = assoc(r, zone_at(r, 113.00, 113.25, m)["zone_id"]).iloc[0]
                self.assertTrue(fb["is_first"])
                first_old = assoc(r, zone_at(r, 103.00, 103.50, m)["zone_id"]).iloc[0]
                self.assertNotEqual(fb["leg_origin_swing_id"], first_old["leg_origin_swing_id"])

    def test_w9d_plateau_deadline_and_cutoff(self):
        for m in BOTH:
            with self.subTest(mirrored=m):
                full = run(W9D, mirrored=m)
                z = zone_at(full, 105.00, 105.50, m)
                a = assoc(full, z["zone_id"]).iloc[0]
                self.assertEqual((a["formation_available_at"], a["association_available_at"]), (end(4), end(5)))
                early = run(W9D, cutoff_k=4, mirrored=m)
                self.assertIn(z["zone_id"], set(early.zones["zone_id"]))
                self.assertTrue(assoc(early, z["zone_id"]).empty)          # nothing provisional before the deadline
                at = run(W9D, cutoff_k=5, mirrored=m)
                self.assertEqual(assoc(at, z["zone_id"]).iloc[0]["association_available_at"], end(5))

    def test_marker_ends_at_conversion_and_never_on_ifvg(self):
        r = run(W1)
        a = r.associations
        tr = r.marker_transitions
        for row in a[a["is_first"] & ~a["marker_never_active"]].itertuples():
            ends = tr[tr["entity_id"] == row.association_id]
            conv = r.engine.zone_exits[row.zone_id]["conv_ns"]
            if conv is not None:
                self.assertEqual(ends["reason_code"].iloc[0], "CONVERTED")
                self.assertEqual(ends["transition_at"].iloc[0], pd.Timestamp(conv, tz="UTC"))
        self.assertTrue(set(a["zone_id"]) <= set(r.zones["zone_id"]))

    def test_no_promotion(self):
        r = run(W9A)
        a = r.associations
        self.assertEqual(int(a["is_first"].sum()), len(a["leg_origin_swing_id"].unique()))


if __name__ == "__main__":
    unittest.main()
