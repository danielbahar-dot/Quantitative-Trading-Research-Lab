import unittest

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_room_to_level_characterization import (
    CONTINUOUS_REPRESENTATIONS,
    NO_LEVEL_REPRESENTATION,
    NO_LEVEL_STATE,
    ROOM_LEVEL_ORDER,
    assert_development_input_path,
    assign_fixed_quintiles,
    characterize_room_to_level,
    fixed_quintile_intervals,
    identify_equal_price_nearest_ties,
    required_input_columns,
)


class RoomToLevelCharacterizationTests(unittest.TestCase):
    def test_quintile_boundaries_are_left_inclusive(self):
        intervals = fixed_quintile_intervals(pd.Series(range(101), dtype=float))
        assigned = assign_fixed_quintiles(
            pd.Series([0.0, 19.999, 20.0, 100.0]), intervals
        )
        self.assertEqual(assigned.tolist(), ["Q1", "Q1", "Q2", "Q5"])
        self.assertFalse(intervals[0]["upper_inclusive"])
        self.assertTrue(intervals[-1]["upper_inclusive"])

    def test_no_level_ahead_is_separate_from_quintiles(self):
        events = _events()
        master, _, _, _, _, audit = characterize_room_to_level(events)
        quintiles = master[
            master["source_feature"].eq("room_to_next_level_pct")
            & master["or_minutes"].astype(str).eq("15")
            & master["outcome_horizon"].eq("30m")
        ]
        categorical = master[
            master["source_feature"].eq(NO_LEVEL_REPRESENTATION)
            & master["or_minutes"].astype(str).eq("15")
            & master["outcome_horizon"].eq("30m")
        ]
        self.assertNotIn(NO_LEVEL_STATE, set(quintiles["state_label"]))
        self.assertIn(NO_LEVEL_STATE, set(categorical["state_label"]))
        expected = int(
            events[events["or_minutes"].eq(15)][NO_LEVEL_REPRESENTATION].sum()
        )
        self.assertEqual(int(quintiles["event_n"].sum()), 20 - expected)
        self.assertEqual(int(quintiles["eligible_event_n"].iloc[0]), 20 - expected)
        observed = int(
            categorical.loc[categorical["state_label"].eq(NO_LEVEL_STATE), "event_n"].iloc[0]
        )
        self.assertEqual(observed, expected)
        self.assertEqual(audit["input_rows"], 60)

    def test_equal_price_tie_flag_preserves_frozen_type(self):
        events = _events()
        before = events["next_level_type"].copy()
        flags = identify_equal_price_nearest_ties(events)
        self.assertEqual(int(flags.sum()), 1)
        self.assertTrue(flags.iloc[1])
        pd.testing.assert_series_equal(events["next_level_type"], before)

        changed = events.copy()
        changed.loc[1, "overnight_low"] -= 1.0
        self.assertFalse(identify_equal_price_nearest_ties(changed).iloc[1])

    def test_full_dev_edges_are_reused_for_halves(self):
        master, stability, _, _, _, _ = characterize_room_to_level(_events())
        master_edges = master[
            master["source_feature"].eq("room_to_next_level_or_widths")
            & master["or_minutes"].astype(str).eq("15")
            & master["outcome_horizon"].eq("30m")
            & master["state_label"].str.startswith("Q")
        ][["state_label", "state_lower_inclusive", "state_upper"]].reset_index(drop=True)
        half_edges = stability[
            stability["source_feature"].eq("room_to_next_level_or_widths")
            & stability["or_minutes"].astype(str).eq("15")
            & stability["dev_segment"].eq("DEV_FIRST_HALF")
            & stability["breakout_direction"].eq("ALL")
            & stability["outcome_horizon"].eq("30m")
            & stability["state_label"].str.startswith("Q")
        ][["state_label", "state_lower_inclusive", "state_upper"]].reset_index(drop=True)
        pd.testing.assert_frame_equal(master_edges, half_edges)

    def test_dev_only_enforcement(self):
        assert_development_input_path("signals/example_DEV_input.csv")
        with self.assertRaises(ValueError):
            assert_development_input_path("reserved/example.csv")
        events = _events()
        events.loc[0, "session_date"] = "2025-07-01"
        with self.assertRaises(ValueError):
            characterize_room_to_level(events)

    def test_no_other_state_family_columns_are_required(self):
        required = required_input_columns()
        prohibited = {
            "or_efficiency",
            "directional_clv",
            "or_breakout_alignment",
            "directional_or_net_move_pct",
        }
        self.assertFalse(prohibited.intersection(required))
        self.assertFalse(any("or_width_hist_" in column for column in required))
        _, _, _, _, relationships, audit = characterize_room_to_level(_events())
        self.assertEqual(len(relationships), 9)
        self.assertFalse(audit["other_state_family_columns_loaded"])

    def test_long_short_duration_and_type_tie_scopes(self):
        master, stability, direction, type_description, _, audit = (
            characterize_room_to_level(_events())
        )
        row = master[
            master["source_feature"].eq(NO_LEVEL_REPRESENTATION)
            & master["or_minutes"].astype(str).eq("15")
            & master["state_label"].eq(NO_LEVEL_STATE)
            & master["outcome_horizon"].eq("30m")
        ].iloc[0]
        self.assertEqual(row["event_n"], row["long_n"] + row["short_n"])
        self.assertEqual(set(direction["breakout_direction"]), {"LONG", "SHORT"})
        self.assertEqual(
            set(stability["dev_segment"]),
            {"FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF"},
        )
        all_scope = type_description[
            type_description["or_minutes"].astype(str).eq("ALL")
            & type_description["outcome_horizon"].eq("30m")
        ]
        all_labels = all_scope[all_scope["tie_scope"].eq("ALL_FROZEN_LABELS")]
        untied = all_scope[all_scope["tie_scope"].eq("UNTIED_ONLY_SENSITIVITY")]
        self.assertEqual(int(all_labels["event_n"].sum()), 60)
        self.assertEqual(int(untied["event_n"].sum()), 59)
        self.assertEqual(audit["equal_price_tie_n"], 1)
        self.assertFalse(any("signal_bar_" in column for column in master.columns))


def _events() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-06-21", periods=60, freq="B")
    for index, date in enumerate(dates):
        duration = (15, 20, 30)[index // 20]
        direction = "LONG" if index % 2 == 0 else "SHORT"
        no_level = index % 9 == 0
        distance = float(index % 5 + 1)
        row = {
            "session_date": date.date().isoformat(),
            "or_minutes": duration,
            "breakout_type": "PRINT",
            "breakout_direction": direction,
            "or_high": 100.0,
            "or_low": 100.0,
            "next_level_type": np.nan,
            "next_level_price": np.nan,
            "room_to_next_level_points": np.nan if no_level else distance,
            "room_to_next_level_pct": np.nan if no_level else distance / 100.0,
            "room_to_next_level_or_widths": np.nan if no_level else distance / 5.0,
            "no_level_ahead": no_level,
        }
        for level_name in ROOM_LEVEL_ORDER:
            row[level_name] = np.nan
            row[f"level_{level_name}_available"] = False
        if not no_level:
            if direction == "LONG":
                row["previous_day_high"] = 100.0 + distance
                row["level_previous_day_high_available"] = True
                row["next_level_type"] = "previous_day_high"
                row["next_level_price"] = 100.0 + distance
            else:
                row["previous_day_low"] = 100.0 - distance
                row["level_previous_day_low_available"] = True
                row["next_level_type"] = "previous_day_low"
                row["next_level_price"] = 100.0 - distance
        if index == 1:
            row["overnight_low"] = row["previous_day_low"]
            row["level_overnight_low_available"] = True
        for horizon_index, horizon in enumerate(
            ("5m", "15m", "30m", "60m", "session_end"), 1
        ):
            row[f"post_signal_bar_{horizon}_complete"] = True
            row[f"post_signal_bar_{horizon}_mfe_pct"] = (
                0.0004 * horizon_index + 0.0001 * distance
            )
            row[f"post_signal_bar_{horizon}_mae_pct"] = (
                0.0002 * horizon_index + 0.00004 * distance
            )
        rows.append(row)
    frame = pd.DataFrame(rows)
    return frame[required_input_columns()]


if __name__ == "__main__":
    unittest.main()
