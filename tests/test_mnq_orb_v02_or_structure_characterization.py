from __future__ import annotations

import unittest

import pandas as pd

from src.experiments.mnq_orb_v02_or_structure_characterization import (
    ALIGNMENT_STATES,
    assign_fixed_quintiles,
    assert_development_input_path,
    characterize_or_structure,
    fixed_quintile_intervals,
    required_input_columns,
)


class Stage3AORStructureCharacterizationTests(unittest.TestCase):
    def test_quintile_boundaries_are_left_inclusive_and_final_upper_inclusive(self):
        values = pd.Series(range(10), dtype=float)
        intervals = fixed_quintile_intervals(values)
        boundary = intervals[1]["lower"]
        assigned = assign_fixed_quintiles(
            pd.Series([intervals[0]["lower"], boundary, intervals[-1]["upper"]]),
            intervals,
        )
        self.assertEqual(assigned.tolist(), ["Q1", "Q2", "Q5"])

    def test_full_dev_boundaries_are_reused_for_halves(self):
        master, stability, _, _, _ = characterize_or_structure(_events())
        master_edges = master[
            (master["source_feature"] == "or_efficiency")
            & (master["or_minutes"].astype(str) == "15")
            & (master["outcome_horizon"] == "30m")
        ][["state_label", "state_lower_inclusive", "state_upper"]].reset_index(drop=True)
        half_edges = stability[
            (stability["source_feature"] == "or_efficiency")
            & (stability["or_minutes"].astype(str) == "15")
            & (stability["dev_segment"] == "DEV_FIRST_HALF")
            & (stability["breakout_direction"] == "ALL")
            & (stability["outcome_horizon"] == "30m")
        ][["state_label", "state_lower_inclusive", "state_upper"]].reset_index(drop=True)
        pd.testing.assert_frame_equal(master_edges, half_edges)

    def test_alignment_uses_only_declared_states(self):
        master, _, _, _, audit = characterize_or_structure(_events())
        states = set(
            master[master["source_feature"] == "or_breakout_alignment"]["state_label"]
        )
        self.assertEqual(states, set(ALIGNMENT_STATES))
        self.assertGreater(audit["flat_alignment_events"], 0)

    def test_dev_only_enforcement(self):
        assert_development_input_path("signals/example_DEV_input.csv")
        with self.assertRaises(ValueError):
            assert_development_input_path("OOS_BURNED/example.csv")
        events = _events()
        events.loc[0, "session_date"] = "2025-07-01"
        with self.assertRaises(ValueError):
            characterize_or_structure(events)

    def test_no_other_state_family_columns_are_required(self):
        events = _events()
        self.assertFalse(any("or_width_hist" in column for column in events.columns))
        self.assertFalse(any("or_width_hist" in column for column in required_input_columns()))
        _, _, _, relationships, audit = characterize_or_structure(events)
        self.assertEqual(len(relationships), 12)
        self.assertFalse(audit["other_state_family_columns_loaded"])

    def test_long_short_and_duration_grouping(self):
        master, stability, direction, _, _ = characterize_or_structure(_events())
        row = master[
            (master["source_feature"] == "or_efficiency")
            & (master["or_minutes"].astype(str) == "15")
            & (master["state_label"] == "Q1")
            & (master["outcome_horizon"] == "30m")
        ].iloc[0]
        self.assertEqual(row["event_n"], row["long_n"] + row["short_n"])
        self.assertEqual(set(direction["breakout_direction"]), {"LONG", "SHORT"})
        self.assertEqual(
            set(stability["dev_segment"]),
            {"FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF"},
        )
        self.assertEqual(set(master["or_minutes"].astype(str)), {"15", "20", "30", "ALL"})
        self.assertFalse(any("signal_bar_" in column for column in master.columns))


def _events() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-06-21", periods=30, freq="B")
    for index, date in enumerate(dates):
        within_duration = index % 10
        duration = (15, 20, 30)[index // 10]
        row = {
            "session_date": date.date().isoformat(),
            "or_minutes": duration,
            "breakout_type": "PRINT",
            "breakout_direction": "LONG" if index % 2 == 0 else "SHORT",
            "or_efficiency": (within_duration + 1) / 11,
            "directional_clv": (10 - within_duration) / 11,
            "directional_or_net_move_pct": (within_duration - 4.5) / 1000,
            "or_breakout_alignment": ALIGNMENT_STATES[index % 3],
        }
        for horizon_index, horizon in enumerate(("5m", "15m", "30m", "60m", "session_end"), 1):
            row[f"post_signal_bar_{horizon}_complete"] = True
            row[f"post_signal_bar_{horizon}_mfe_pct"] = (
                0.0005 * horizon_index + 0.0001 * within_duration
            )
            row[f"post_signal_bar_{horizon}_mae_pct"] = (
                0.0003 * horizon_index + 0.00005 * within_duration
            )
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
