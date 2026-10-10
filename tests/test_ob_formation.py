"""Order Block formation and discovery (OB-I1; rev 3 §5, §6, §15.1 – §15.3, §22). Both directions via mirroring."""

import sys
import unittest

from ob_fixtures import (EX151, HIGHER_LOW_ROWS, PLATEAU_DOJI_ROWS, PLATEAU_OK_ROWS, RALLY_ROWS, k_of, run, tk,
                         with_source)
from src.fvg.association import SWING_REFERENCE


def bull_or_bear(mirrored):
    return "BEARISH" if mirrored else "BULLISH"


class SourceAndGeometryTests(unittest.TestCase):
    def test_worked_example_geometry_both_directions(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                r = run(EX151, mirrored=mirrored)
                b = r.engine.blocks
                self.assertEqual(len(b), 1)
                self.assertEqual(b.iloc[0]["ordinary_direction"], bull_or_bear(mirrored))
                self.assertEqual(k_of(b.iloc[0]["ordinary_available_at"]), 6)
                g = r.engine.regions.iloc[0]
                lo, up = (tk(102, True), tk(99, True)) if mirrored else (tk(99), tk(102))
                self.assertEqual((g["lower_ticks"], g["upper_ticks"]), (lo, up))      # low→open / open→high
                self.assertEqual(g["zone_midpoint_half_ticks"], lo + up)               # 100.5, exact half tick
                self.assertNotEqual(g["zone_midpoint_half_ticks"], g["source_body_midpoint_half_ticks"])
                self.assertEqual(g["body_ticks"], 8)
                # the departure FVG's C2 lies entirely beyond the region (no adjacency / overlap required)
                fvg = r.fvg_zones.set_index("zone_id").loc[b.iloc[0]["formation_fvg_id"]]
                self.assertTrue(fvg["lower_ticks"] > up if not mirrored else fvg["upper_ticks"] < lo)
                self.assertEqual(k_of(fvg["c2_end"]), 5)

    def test_body_threshold_and_no_fallback(self):
        cases = {(100, 100): 0, (100.25, 100): 1, (101, 100.25): 3}
        for mirrored in (False, True):
            for (o, c), ticks in cases.items():
                with self.subTest(mirrored=mirrored, body=ticks):
                    r = run(with_source(o, c), mirrored=mirrored)
                    self.assertEqual(len(r.engine.blocks), 0)      # k1 (a valid larger candle) is never substituted
                    ep = r.engine.episodes
                    own = ep[ep["direction"] == bull_or_bear(mirrored)].iloc[0]
                    self.assertEqual(own["reason"], "SOURCE_BODY_LT_4_TICKS")
            with self.subTest(mirrored=mirrored, body=4):
                r = run(with_source(101, 100), mirrored=mirrored)
                g = r.engine.regions.iloc[0]
                self.assertEqual(g["body_ticks"], 4)
                lo, up = (tk(101, True), tk(99, True)) if mirrored else (tk(99), tk(101))
                self.assertEqual((g["lower_ticks"], g["upper_ticks"]), (lo, up))

    def test_direction_mismatch(self):
        r = run(with_source(100, 101))          # bullish candle at a swing low cannot source a bullish OB
        ep = r.engine.episodes
        self.assertEqual(ep[ep["direction"] == "BULLISH"].iloc[0]["reason"], "SOURCE_DIRECTION_MISMATCH")
        self.assertEqual(len(r.engine.blocks), 0)

    def test_terminal_plateau_source_and_delayed_confirmation(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                r = run(PLATEAU_OK_ROWS, mirrored=mirrored)
                g = r.engine.regions.iloc[0]
                self.assertEqual(k_of(g["source_bar_end"]), 3)                 # terminal member, not k2
                own = r.engine.episodes[r.engine.episodes["direction"] == bull_or_bear(mirrored)].iloc[0]
                self.assertEqual(k_of(own["opened_at"]), 4)                     # plateau k2..k3 confirms at k4
                d = run(PLATEAU_DOJI_ROWS, mirrored=mirrored)
                self.assertEqual(len(d.engine.blocks), 0)                       # terminal doji: no fallback to k2
                own = d.engine.episodes[d.engine.episodes["direction"] == bull_or_bear(mirrored)].iloc[0]
                self.assertEqual(own["reason"], "SOURCE_BODY_LT_4_TICKS")


class DiscoveryTests(unittest.TestCase):
    def test_consecutive_fvgs_do_not_rearm(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                r = run(RALLY_ROWS, mirrored=mirrored)
                E = r.engine
                self.assertGreaterEqual(E.counters["fvg_facts_offered"], 3)
                self.assertEqual(len(E.blocks), 1)
                own = E.episodes[E.episodes["direction"] == bull_or_bear(mirrored)]
                self.assertEqual(len(own), 1)                                  # one swing → one source search
                self.assertEqual(E.counters["source_searches"], len(E.episodes))

    def test_new_same_side_swing_opens_a_new_episode(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                r = run(HIGHER_LOW_ROWS, mirrored=mirrored)
                b = r.engine.blocks
                self.assertEqual(list(b["ordinary_direction"]), [bull_or_bear(mirrored)] * 2)
                self.assertEqual(sorted(k_of(t) for t in b["ordinary_available_at"]), [6, 10])
                self.assertEqual(b["source_region_id"].nunique(), 2)

    def test_swing_depth_is_explicit_and_frozen_consumers_unchanged(self):
        r1, r2 = run(EX151), run(EX151, depth=2)
        self.assertEqual((r1.manifest["left_depth"], r1.manifest["right_depth"]), (1, 1))
        self.assertEqual(r1.engine.blocks.iloc[0]["left_depth"], 1)
        self.assertEqual(set(r1.swing_frames["5m"]["left_depth"]), {1})
        if len(r2.engine.blocks):
            self.assertNotEqual(r1.engine.blocks.iloc[0]["block_id"], r2.engine.blocks.iloc[0]["block_id"])
        self.assertEqual((SWING_REFERENCE.left_depth, SWING_REFERENCE.right_depth), (2, 2))

    def test_no_liquidity_or_structure_dependency(self):
        import src.ict_blocks.audit  # noqa: F401
        import src.ict_blocks.pipeline  # noqa: F401
        mods = [m for m in sys.modules if m.startswith("src.ict_blocks")]
        for m in mods:
            src = open(sys.modules[m].__file__, encoding="utf-8").read()
            self.assertNotIn("src.liquidity", src, m)
            self.assertNotIn("swing_breaks import classify", src, m)
        r1, r2 = run(EX151), run(EX151)
        self.assertEqual(r1.run_id, r2.run_id)
        self.assertFalse(any("liquidity" in k for k in r1.manifest))

    def test_empty_input_fixed_schemas(self):
        r = run(EX151[:2])
        for name in ("regions", "episodes", "blocks", "stages", "lifecycle", "motifs", "visits", "interactions",
                     "depth_versions", "warnings", "pending"):
            with self.subTest(name):
                f = getattr(r.engine, name)
                self.assertEqual(len(f), 0)
                self.assertGreater(len(f.columns), 0)
        self.assertIn("run_id", r.manifest)


if __name__ == "__main__":
    unittest.main()
