import unittest

import pandas as pd

from src.experiments.mnq_orb_v02_key_level_interaction_characterization import (
    INTERACTION_STATES,
    LEVEL_FAMILIES,
    assert_development_input_path,
    characterize_key_level_interactions,
    derive_interaction_category,
    required_input_columns,
)


class KeyLevelInteractionCharacterizationTests(unittest.TestCase):
    def test_deterministic_precedence(self):
        base = {
            "available": True,
            "touched": True,
            "traded_through": True,
            "closed_through": True,
            "rejected": True,
            "swept": True,
        }
        self.assertEqual(derive_interaction_category(**base), "SWEEP")
        self.assertEqual(
            derive_interaction_category(**{**base, "swept": False}), "REJECTION"
        )
        self.assertEqual(
            derive_interaction_category(
                available=True,
                touched=True,
                traded_through=True,
                closed_through=True,
                rejected=False,
                swept=False,
            ),
            "CLOSE_THROUGH",
        )
        self.assertEqual(
            derive_interaction_category(
                available=True,
                touched=True,
                traded_through=False,
                closed_through=False,
                rejected=False,
                swept=False,
            ),
            "TOUCH_ONLY",
        )
        self.assertEqual(
            derive_interaction_category(
                available=True,
                touched=False,
                traded_through=False,
                closed_through=False,
                rejected=False,
                swept=False,
            ),
            "NO_INTERACTION",
        )
        self.assertTrue(
            pd.isna(
                derive_interaction_category(
                    available=False,
                    touched=False,
                    traded_through=False,
                    closed_through=False,
                    rejected=False,
                    swept=False,
                )
            )
        )

    def test_invalid_frozen_primitive_combination_is_rejected(self):
        events = _events()
        events.loc[0, "level_asia_high_touched"] = False
        events.loc[0, "level_asia_high_traded_through"] = True
        with self.assertRaises(ValueError):
            characterize_key_level_interactions(events)

    def test_unavailable_family_is_excluded_from_no_interaction(self):
        events = _events()
        master, _, _, _, audit = characterize_key_level_interactions(events)
        rows = master[
            master["level_family"].eq("previous_day")
            & master["or_minutes"].astype(str).eq("15")
            & master["outcome_horizon"].eq("30m")
        ]
        available = events[events["or_minutes"].eq(15)][
            "level_previous_day_high_available"
        ].sum()
        self.assertEqual(int(rows["event_n"].sum()), int(available))
        self.assertEqual(int(rows["eligible_event_n"].iloc[0]), int(available))
        self.assertGreater(audit["unavailable_n_by_family"]["previous_day"], 0)

    def test_primitive_counts_remain_under_exclusive_state(self):
        master, _, _, _, _ = characterize_key_level_interactions(_events())
        row = master[
            master["level_family"].eq("asia")
            & master["or_minutes"].astype(str).eq("15")
            & master["state_label"].eq("SWEEP")
            & master["outcome_horizon"].eq("30m")
        ].iloc[0]
        self.assertEqual(row["event_n"], row["primitive_touch_n"])
        self.assertEqual(row["event_n"], row["primitive_trade_through_n"])
        self.assertEqual(row["event_n"], row["primitive_rejection_n"])
        self.assertEqual(row["event_n"], row["primitive_sweep_n"])
        self.assertEqual(row["primitive_close_through_n"], 0)

    def test_dev_only_enforcement(self):
        assert_development_input_path("signals/example_DEV_input.csv")
        with self.assertRaises(ValueError):
            assert_development_input_path("reserved/example.csv")
        events = _events()
        events.loc[0, "session_date"] = "2025-07-01"
        with self.assertRaises(ValueError):
            characterize_key_level_interactions(events)

    def test_no_other_state_family_columns_are_required(self):
        required = required_input_columns()
        prohibited = {
            "room_to_next_level_pct",
            "or_efficiency",
            "directional_clv",
            "ny_open_gap_pct",
            "asia_range_pct",
        }
        self.assertFalse(prohibited.intersection(required))
        self.assertFalse(any("or_width_hist_" in column for column in required))
        _, _, _, relationships, audit = characterize_key_level_interactions(_events())
        self.assertEqual(len(relationships), 12)
        self.assertFalse(audit["other_state_family_columns_loaded"])

    def test_long_short_duration_and_half_grouping(self):
        master, stability, direction, _, _ = characterize_key_level_interactions(
            _events()
        )
        row = master[
            master["level_family"].eq("ny_premarket")
            & master["or_minutes"].astype(str).eq("15")
            & master["state_label"].eq("CLOSE_THROUGH")
            & master["outcome_horizon"].eq("30m")
        ].iloc[0]
        self.assertEqual(row["event_n"], row["long_n"] + row["short_n"])
        self.assertEqual(set(direction["breakout_direction"]), {"LONG", "SHORT"})
        self.assertEqual(
            set(stability["dev_segment"]),
            {"FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF"},
        )
        self.assertEqual(set(master["or_minutes"].astype(str)), {"15", "20", "30", "ALL"})
        self.assertEqual(set(master["state_label"]), set(INTERACTION_STATES))
        self.assertFalse(any("signal_bar_" in column for column in master.columns))

    def test_acceptance_sweep_relationship_fields_are_present(self):
        _, _, _, relationships, _ = characterize_key_level_interactions(_events())
        self.assertEqual(
            set(relationships["classification"]),
            {"NO_CLEAR_RELATIONSHIP"},
        )
        self.assertTrue(
            relationships["full_30m_acceptance_minus_sweep_mfe_pct"].notna().all()
        )
        self.assertTrue(
            relationships["full_30m_acceptance_minus_sweep_mae_pct"].notna().all()
        )


def _events() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-06-21", periods=60, freq="B")
    state_flags = {
        "NO_INTERACTION": (False, False, False, False, False),
        "TOUCH_ONLY": (True, False, False, False, False),
        "CLOSE_THROUGH": (True, True, True, False, False),
        "REJECTION": (True, False, False, True, False),
        "SWEEP": (True, True, False, True, True),
    }
    for index, date in enumerate(dates):
        duration = (15, 20, 30)[index // 20]
        row = {
            "session_date": date.date().isoformat(),
            "or_minutes": duration,
            "breakout_type": "PRINT",
            "breakout_direction": "LONG" if index % 2 == 0 else "SHORT",
        }
        for family_index, (family, levels) in enumerate(LEVEL_FAMILIES.items()):
            available = not (family == "previous_day" and index % 11 == 0)
            state = INTERACTION_STATES[(index + family_index) % len(INTERACTION_STATES)]
            flags = state_flags[state] if available else (False,) * 5
            for level_index, level in enumerate(levels):
                row[f"level_{level}_available"] = available
                for primitive, value in zip(
                    ("touched", "traded_through", "closed_through", "rejected", "swept"),
                    flags if level_index == 0 else (False,) * 5,
                ):
                    row[f"level_{level}_{primitive}"] = value
        state_index = index % len(INTERACTION_STATES)
        for horizon_index, horizon in enumerate(
            ("5m", "15m", "30m", "60m", "session_end"), 1
        ):
            row[f"post_signal_bar_{horizon}_complete"] = True
            row[f"post_signal_bar_{horizon}_mfe_pct"] = (
                0.0005 * horizon_index + 0.0001 * state_index
            )
            row[f"post_signal_bar_{horizon}_mae_pct"] = (
                0.0003 * horizon_index + 0.00005 * state_index
            )
        rows.append(row)
    return pd.DataFrame(rows)[required_input_columns()]


if __name__ == "__main__":
    unittest.main()
