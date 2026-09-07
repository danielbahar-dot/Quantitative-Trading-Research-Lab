from __future__ import annotations

import json
from pathlib import Path
import unittest

import pandas as pd

from src.experiments.mnq_orb_v02_combined_state_hypothesis import (
    EXPERIMENT_ID,
    HORIZONS,
    STATE_GROUPS,
    assert_development_input_path,
    assign_combined_states,
    characterize_combined_state,
    efficiency_intervals_from_step3,
    required_input_columns,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CombinedStateHypothesisTests(unittest.TestCase):
    def test_fixed_q4_q5_width_definition(self):
        assigned = assign_combined_states(
            pd.Series([0.599999, 0.6, 0.799999, 0.8, 1.0]),
            pd.Series([True] * 5),
            pd.Series([0.5] * 5),
            _efficiency_intervals(),
        )
        self.assertEqual(
            assigned["width_band"].tolist(),
            ["0.40-0.60", "0.60-0.80", "0.60-0.80", "0.80-1.00", "0.80-1.00"],
        )
        self.assertEqual(
            assigned["combined_state"].tolist(),
            [
                "WIDTH_NOT_ELEVATED",
                "WIDTH_ELEVATED_NOT_MAX_EFFICIENCY",
                "WIDTH_ELEVATED_NOT_MAX_EFFICIENCY",
                "WIDTH_ELEVATED_NOT_MAX_EFFICIENCY",
                "WIDTH_ELEVATED_NOT_MAX_EFFICIENCY",
            ],
        )

    def test_efficiency_q5_is_excluded_from_primary_state(self):
        assigned = assign_combined_states(
            pd.Series([0.7, 0.7]),
            pd.Series([True, True]),
            pd.Series([0.79, 0.8]),
            _efficiency_intervals(),
        )
        self.assertEqual(
            assigned["combined_state"].tolist(),
            [
                "WIDTH_ELEVATED_NOT_MAX_EFFICIENCY",
                "WIDTH_ELEVATED_MAX_EFFICIENCY",
            ],
        )

    def test_unavailable_lookback_is_not_backfilled(self):
        assigned = assign_combined_states(
            pd.Series([0.9, 0.9, None]),
            pd.Series([False, True, True]),
            pd.Series([0.5, None, 0.5]),
            _efficiency_intervals(),
        )
        self.assertTrue(assigned["combined_state"].isna().all())

    def test_step3_efficiency_intervals_are_reused_exactly(self):
        intervals = efficiency_intervals_from_step3(_step3_source())
        self.assertEqual([item["state_label"] for item in intervals], ["Q1", "Q2", "Q3", "Q4", "Q5"])
        self.assertEqual(intervals[3]["upper"], 0.8)
        self.assertTrue(intervals[4]["upper_inclusive"])

    def test_combined_state_grouping_and_only_20m_scope(self):
        master, _, _, _, audit = characterize_combined_state(
            _events(), _efficiency_intervals()
        )
        self.assertEqual(audit["or_20m_rows"], 60)
        self.assertEqual(set(master["or_minutes"]), {20})
        self.assertEqual(set(master["state_group"]), set(STATE_GROUPS))
        row = master.loc[
            master["lookback_sessions"].eq(5)
            & master["outcome_horizon"].eq("30m")
            & master["state_group"].eq("WIDTH_ELEVATED_NOT_MAX_EFFICIENCY")
        ].iloc[0]
        self.assertEqual(row["event_n"], 12)

    def test_dev_split_and_long_short_grouping(self):
        _, stability, direction, _, audit = characterize_combined_state(
            _events(), _efficiency_intervals()
        )
        self.assertEqual(
            set(stability["dev_segment"]),
            {"FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF"},
        )
        self.assertEqual(set(direction["breakout_direction"]), {"LONG", "SHORT"})
        self.assertEqual(
            audit["development_split"]["first_half_dates"]
            + audit["development_split"]["second_half_dates"],
            60,
        )

    def test_reserved_paths_and_out_of_dev_rows_are_rejected(self):
        assert_development_input_path("signals/example_DEV_input.csv")
        with self.assertRaises(ValueError):
            assert_development_input_path("signals/reserved.csv")
        with self.assertRaises(ValueError):
            assert_development_input_path("Validation/example_DEV.csv")
        events = _events()
        events.loc[0, "session_date"] = "2025-07-01"
        with self.assertRaises(ValueError):
            characterize_combined_state(events, _efficiency_intervals())

    def test_signal_bar_and_other_feature_families_are_not_loaded(self):
        columns = required_input_columns()
        self.assertFalse(any(column.startswith("signal_bar_") for column in columns))
        self.assertFalse(any("london" in column for column in columns))
        self.assertFalse(any("room_to" in column for column in columns))

    def test_registered_experiment_is_complete_dev_only_and_unvalidated(self):
        record_path = (
            PROJECT_ROOT
            / "experiments"
            / "projects"
            / "mnq_orb_v0_2"
            / "records"
            / f"{EXPERIMENT_ID}.json"
        )
        self.assertTrue(record_path.is_file())
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["scope"]["partition"], "DEVELOPMENT")
        self.assertEqual(record["status"], "complete")
        self.assertFalse(record["reserved_data_exposed"])
        self.assertFalse(record["confirmatory"])
        self.assertFalse(record["summary_metrics"]["hypothesis_validated"])
        self.assertEqual(record["summary_metrics"]["hypothesis_id"], "HYP-ORB-STATE-01")


def _efficiency_intervals():
    edges = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    return [
        {
            "state_label": f"Q{index + 1}",
            "state_order": index + 1,
            "lower": edges[index],
            "upper": edges[index + 1],
            "upper_inclusive": index == 4,
        }
        for index in range(5)
    ]


def _step3_source():
    rows = []
    for interval in _efficiency_intervals():
        rows.append(
            {
                "source_feature": "or_efficiency",
                "or_minutes": 20,
                "dev_segment": "FULL_DEVELOPMENT",
                "breakout_direction": "ALL",
                "state_label": interval["state_label"],
                "state_order": interval["state_order"],
                "state_lower_inclusive": interval["lower"],
                "state_upper": interval["upper"],
                "state_upper_inclusive": interval["upper_inclusive"],
            }
        )
    return pd.DataFrame(rows)


def _events():
    rows = []
    dates = pd.date_range("2024-06-21", periods=60, freq="B")
    width_values = (0.1, 0.3, 0.5, 0.7, 0.9)
    efficiency_values = (0.1, 0.3, 0.5, 0.7, 0.9)
    for index, date in enumerate(dates):
        width = width_values[index % 5]
        efficiency = efficiency_values[index % 5]
        if width >= 0.6 and efficiency < 0.8:
            mfe_add, mae_add = 0.0010, 0.0002
        elif width >= 0.6:
            mfe_add, mae_add = -0.0002, 0.0006
        else:
            mfe_add, mae_add = 0.0, 0.0
        row = {
            "session_date": date.date().isoformat(),
            "contract": "MNQ TEST",
            "or_minutes": 20,
            "breakout_type": "PRINT",
            "breakout_direction": "LONG" if index % 2 == 0 else "SHORT",
            "or_efficiency": efficiency,
        }
        for lookback in (5, 10, 15, 20):
            row[f"or_width_hist_{lookback}_percentile"] = width
            row[f"or_width_hist_{lookback}_available"] = True
        for horizon_index, horizon in enumerate(HORIZONS, 1):
            row[f"post_signal_bar_{horizon}_complete"] = True
            row[f"post_signal_bar_{horizon}_mfe_pct"] = 0.001 * horizon_index + mfe_add
            row[f"post_signal_bar_{horizon}_mae_pct"] = 0.0005 * horizon_index + mae_add
        rows.append(row)
    extra = rows[0].copy()
    extra["or_minutes"] = 15
    extra["session_date"] = "2024-06-21"
    rows.append(extra)
    return pd.DataFrame(rows)[required_input_columns()]


if __name__ == "__main__":
    unittest.main()
