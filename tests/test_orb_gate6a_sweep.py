import unittest

import pandas as pd

from src.experiments.orb_gate6a_sweep import (
    EXPECTED_CONFIGURATION_COUNT,
    OR_DURATIONS,
    add_neighborhood_metrics,
    configuration_grid,
)


class Gate6ASweepTests(unittest.TestCase):
    def test_grid_is_exactly_the_approved_40_print_cells(self):
        grid = configuration_grid()
        self.assertEqual(len(grid), EXPECTED_CONFIGURATION_COUNT)
        self.assertEqual(set(grid["or_minutes"]), {10, 15, 20, 30})
        self.assertNotIn(5, set(grid["or_minutes"]))
        self.assertEqual(set(grid["breakout_type"]), {"PRINT"})
        self.assertEqual(set(grid["stop_fraction"]), {0.25, 0.5})
        self.assertEqual(set(grid["target_r"]), {1.0, 1.5, 2.0, 2.5, 3.0})
        self.assertFalse(
            grid.duplicated(["or_minutes", "breakout_type", "stop_fraction", "target_r"]).any()
        )

    def test_midpoint_2r_has_one_control_for_each_duration(self):
        grid = configuration_grid()
        controls = grid.loc[grid["stop_fraction"].eq(0.5) & grid["target_r"].eq(2.0)]
        self.assertEqual(len(controls), len(OR_DURATIONS))

    def test_neighborhood_is_orthogonal_and_stop_local(self):
        grid = configuration_grid()
        grid["average_r"] = grid["or_minutes"] / 100.0 + grid["target_r"]
        grid["profit_factor_r"] = 1.0 + grid["average_r"]
        result = add_neighborhood_metrics(grid)
        interior = result.loc[
            result["or_minutes"].eq(15)
            & result["stop_fraction"].eq(0.25)
            & result["target_r"].eq(2.0)
        ].iloc[0]
        self.assertEqual(interior["neighbor_count"], 4)
        self.assertAlmostEqual(
            interior["neighbor_mean_average_r"], pd.Series([2.10, 2.20, 1.65, 2.65]).mean()
        )


if __name__ == "__main__":
    unittest.main()
