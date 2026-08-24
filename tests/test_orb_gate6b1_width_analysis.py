import unittest

import pandas as pd

from src.experiments.orb_gate6b1_width_analysis import (
    assign_duration_bins,
    calculate_width_distribution,
    unique_width_observations,
)


class Gate6B1WidthAnalysisTests(unittest.TestCase):
    def test_unique_width_observations_remove_parameter_and_direction_repeats(self):
        rows = []
        for config in ("A", "B"):
            for direction in ("LONG", "SHORT"):
                rows.append({
                    "config_id": config, "session_date": pd.Timestamp("2025-06-20"),
                    "or_minutes": 15, "direction": direction,
                    "signal_time": pd.Timestamp("2025-06-20 10:00"),
                    "or_width_points": 50.0,
                })
        frame = pd.DataFrame(rows)
        widths = unique_width_observations(frame)
        self.assertEqual(len(widths), 1)

    def test_duration_specific_quintiles_are_deterministic_and_balanced(self):
        rows = []
        for duration in (15, 20, 30):
            for index in range(10):
                rows.append({
                    "session_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=index),
                    "or_minutes": duration,
                    "or_width_points": float(index // 2 + duration),
                })
        frame = pd.DataFrame(rows)
        first = assign_duration_bins(frame)
        second = assign_duration_bins(frame.sample(frac=1, random_state=7))
        keys = ["session_date", "or_minutes"]
        first = first.sort_values(keys).reset_index(drop=True)
        second = second.sort_values(keys).reset_index(drop=True)
        pd.testing.assert_series_equal(
            first["or_width_quintile"], second["or_width_quintile"]
        )
        counts = first.groupby(["or_minutes", "or_width_quintile"]).size()
        self.assertTrue(counts.eq(2).all())

    def test_distribution_uses_unique_sessions_but_reports_unique_candidates(self):
        widths = pd.DataFrame({
            "session_date": [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02")],
            "or_minutes": [15, 15], "or_width_points": [40.0, 60.0],
        })
        diagnostics = pd.DataFrame({
            "session_date": [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02")],
            "or_minutes": [15, 15, 15], "direction": ["LONG", "SHORT", "LONG"],
            "signal_time": pd.to_datetime(["2025-01-01 10:00", "2025-01-01 10:05", "2025-01-02 10:00"]),
        })
        # Supply empty duration frames so the public function's three-duration contract remains intact.
        for duration in (20, 30):
            widths.loc[len(widths)] = [pd.Timestamp("2025-01-01"), duration, 70.0]
            diagnostics.loc[len(diagnostics)] = [pd.Timestamp("2025-01-01"), duration, "LONG", pd.Timestamp("2025-01-01 10:00")]
        result = calculate_width_distribution(widths, diagnostics)
        fifteen = result.loc[result["or_minutes"].eq(15)].iloc[0]
        self.assertEqual(fifteen["unique_session_count"], 2)
        self.assertEqual(fifteen["unique_candidate_count"], 3)
        self.assertEqual(fifteen["mean_or_width"], 50.0)


if __name__ == "__main__":
    unittest.main()
