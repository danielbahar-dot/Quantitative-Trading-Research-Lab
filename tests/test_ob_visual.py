"""Visual-package helper regressions (OB review finding 4)."""

import re
import unittest

import pandas as pd

from ob_fixtures import BREAKER_ROWS, CONCURRENT_ROWS, EX151, LONG_VISIT_ROWS, end, run
from src.experiments.ob_visual import (Case, Facts, block_tables, build_cases, cell, chart, concurrent_pairs,
                                       focal_observation, plan_panels, render_panel, visit_table, _block_items)

# a long gap between formation and the break: the break is far outside a formation-sized window
LONG_ROWS = BREAKER_ROWS[:9] + [(121, 121.5, 115, 116)] + [(116, 117, 114, 116.5), (116.5, 118, 115, 117)] * 40 + \
    [(117, 117.5, 108, 109), (109, 110, 98, 98.5), (98.5, 101, 97, 100)]


def html_of(f, case):
    return chart(f, case) + "".join(str(t) for t in case.tables)


class ChartPlanningTests(unittest.TestCase):
    def test_focus_is_inside_a_plotted_panel(self):
        r = run(LONG_ROWS)
        f = Facts(r)
        for c in build_cases(r):
            if c.block_id is None and c.episode_id is None:
                continue
            with self.subTest(c.case_id):
                panels, _tf, _si = plan_panels(f, c)
                self.assertTrue(any(p.ts < c.focus.value <= p.te for p in panels), c.case_id)
        bb = [c for c in build_cases(r) if c.category in ("successor", "failure")]
        self.assertTrue(bb)
        panels, _, _ = plan_panels(f, bb[0])
        self.assertEqual([p.title for p in panels], ["formation", "lifecycle"])     # far focus → separate panel

    def test_out_of_window_items_are_omitted_and_listed_not_clamped(self):
        r = run(LONG_ROWS)
        f = Facts(r)
        c = [c for c in build_cases(r) if c.category in ("successor", "failure")][0]
        panels, tf, si = plan_panels(f, c)
        form = panels[0]
        svg = render_panel(f, c, form, tf, si, _block_items(f, c.block_id))
        self.assertTrue(form.omitted)                       # the later failure / successor markers are not in this panel
        for it in form.omitted:
            self.assertTrue(it.start > form.te or (it.end is not None and it.end < form.ts))
        self.assertIn("Omitted context outside this panel", svg)

    def test_simultaneous_markers_are_merged(self):
        r = run(CONCURRENT_ROWS)
        f = Facts(r)
        c = [c for c in build_cases(r) if c.category == "independence"][0]
        h = chart(f, c)
        self.assertRegex(h, r"▲ [^<]* / [^<]*")             # at least one merged marker label


class ConcurrentSelectionTests(unittest.TestCase):
    def test_pair_relationship_is_asserted(self):
        r = run(CONCURRENT_ROWS)
        pairs = concurrent_pairs(r)
        self.assertEqual(len(pairs), 1)
        p = pairs.iloc[0]
        self.assertNotEqual(p["block_id_ord"], p["block_id_succ"])
        self.assertEqual(p["direction"], "BEARISH")
        self.assertEqual(p["ordinary_direction_succ"], "BULLISH")
        c = [c for c in build_cases(r) if c.category == "independence"][0]
        self.assertEqual((c.block_id, c.partner_block_id), (p["block_id_ord"], p["block_id_succ"]))
        captions = [cap for cap, _ in c.tables]
        self.assertTrue(any(cap.startswith("Parent block — ") for cap in captions))

    def test_unrelated_same_time_objects_are_not_paired(self):
        r = run(BREAKER_ROWS)
        self.assertEqual(len(concurrent_pairs(r)), 0)


class EvidenceTableTests(unittest.TestCase):
    def test_missing_values_render_as_dash(self):
        for v in (None, float("nan"), pd.NaT, "nan", "None"):
            self.assertEqual(cell(v), "—")
        r = run(BREAKER_ROWS)
        f = Facts(r)
        html_all = "".join(chart(f, c) + "".join(f"{rows}" for _, rows in c.tables) for c in build_cases(r))
        from src.experiments.ob_visual import table
        rendered = "".join(table(cap, rows) for c in build_cases(r) for cap, rows in c.tables)
        self.assertIsNone(re.search(r">\s*(nan|NaN|NaT|None)\s*<", rendered))
        self.assertTrue(html_all)

    def test_fvg_metric_names_and_c2_claim(self):
        r = run(EX151)
        f = Facts(r)
        c = build_cases(r)[0]
        fvg = dict(c.tables)[[cap for cap, _ in c.tables if cap.startswith("Formation FVG")][0]][0]
        self.assertIn("FVG gap entirely beyond the OB zone", fvg)
        self.assertIn("C2 range entirely beyond the OB zone", fvg)
        self.assertNotIn("C2 beyond zone", fvg)
        self.assertTrue(fvg["C2 range entirely beyond the OB zone"])            # §15.1: C2 low 110 > upper 102

    def test_focal_observation_identifies_bar_and_reset_instant(self):
        r = run(BREAKER_ROWS, absent={9})
        f = Facts(r)
        o = focal_observation(f, "5m", end(5))
        self.assertEqual(o["observation"], "5m bar")
        self.assertEqual(o["bar_start"], end(4))
        reset = r.engine.lifecycle[r.engine.lifecycle["to_state"] == "TERMINATED_DATA_GAP"].iloc[0]["at"]
        self.assertTrue(focal_observation(f, "5m", reset)["observation"].startswith(("reset instant", "1m bar")))

    def test_visit_cap_keeps_the_visit_containing_the_focus(self):
        r = run(LONG_VISIT_ROWS)
        v = r.engine.visits
        many = pd.concat([v.iloc[[0]].assign(started_at=v.iloc[0]["started_at"] - pd.Timedelta(minutes=10 * i),
                                             ended_at=v.iloc[0]["started_at"] - pd.Timedelta(minutes=10 * i))
                          for i in range(1, 15)] + [v], ignore_index=True)
        focus_visit = v.iloc[1]
        t = focus_visit["started_at"] + (focus_visit["ended_at"] - focus_visit["started_at"]) / 2
        caption, rows = visit_table("visits", many, t)
        self.assertIn("showing", caption)
        self.assertTrue(any(r_["contains focus"] for r_ in rows))

    def test_close_tests_and_raid_evidence_are_numerical(self):
        r = run(BREAKER_ROWS)
        f = Facts(r)
        c = [c for c in build_cases(r) if c.category == "successor"][0]
        tabs = dict(c.tables)
        closes = tabs["Close tests (numerical)"]
        self.assertTrue(any(row["test"].startswith("validation close") for row in closes))
        self.assertTrue(any("ORDINARY close beyond" in row["test"] for row in closes))
        raid = tabs["Raid evidence (numerical)"][0]
        self.assertIn("A price", raid)
        self.assertTrue(raid["raid (strictly beyond A)"])


if __name__ == "__main__":
    unittest.main()
