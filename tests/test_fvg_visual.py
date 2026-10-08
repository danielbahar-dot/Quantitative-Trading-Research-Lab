"""Visual-package helpers: mover provenance of relationship episodes and labelled table caps."""

import unittest

from fvg_fixtures import W1, W7, run
from src.experiments.fvg_visual import capped, episode_provenance


class VisualHelperTests(unittest.TestCase):
    def test_admission_created_bpr(self):
        r = run(W1)
        e = r.engine.episodes
        bpr = e[e["label"] == "BPR"].iloc[0]
        self.assertEqual(episode_provenance(r, bpr), "ADMISSION")

    def test_conversion_created_mtf_bpr(self):
        r = run(W7, timeframes=("5m", "15m"))
        e = r.engine.episodes
        mtf = e[(e["label"] == "MTF_BPR") & (e["movers"].map(len) == 1)]
        kinds = {episode_provenance(r, row) for _, row in mtf.iterrows()}
        self.assertIn("CONVERSION", kinds)
        for _, row in mtf.iterrows():
            mover = row["movers"][0]
            conv = r.engine.zone_exits[mover]["conv_ns"]
            expected = "CONVERSION" if conv == row["created_at"].value else "ADMISSION"
            self.assertEqual(episode_provenance(r, row), expected)

    def test_capped_labels_counts_and_keeps_focal_rows(self):
        rows = [{"i": i, "focal": i == 57} for i in range(100)]
        caption, shown = capped("History", rows, 10, focal=lambda x: x["focal"])
        self.assertIn("showing 11 of 100", caption)
        self.assertIn("truncated", caption)
        self.assertIn(57, [x["i"] for x in shown])
        caption, shown = capped("History", rows[:5], 10)
        self.assertEqual(caption, "History (all 5)")
        self.assertEqual(len(shown), 5)


if __name__ == "__main__":
    unittest.main()
