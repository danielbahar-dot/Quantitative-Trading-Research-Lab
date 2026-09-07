import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_london_interaction_event_characterization import (
    EXPERIMENT_ID,
    HORIZONS,
    _anchor_outcomes,
    assert_development_input_path,
    build_london_interaction_events,
    build_stability_table,
    build_timestamp_audit,
    derive_frozen_interaction_state,
    first_interaction_timestamps,
    map_level_directions,
    required_feature_columns,
    required_outcome_columns,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LondonInteractionEventCharacterizationTests(unittest.TestCase):
    def test_london_high_low_direction_mapping(self):
        self.assertEqual(map_level_directions("LONDON_HIGH"), ("UP", "DOWN"))
        self.assertEqual(map_level_directions("LONDON_LOW"), ("DOWN", "UP"))

    def test_first_trade_through_timestamp_is_strict_and_side_aware(self):
        index = pd.date_range(
            "2024-07-01 09:31", periods=4, freq="min", tz="America/New_York"
        )
        bars = pd.DataFrame(
            {
                "high": [99.5, 100.0, 100.25, 100.5],
                "low": [99.0, 99.25, 99.5, 99.75],
            },
            index=index,
        )
        first_touch, first_trade = first_interaction_timestamps(
            bars, level_price=100.0, start_side="BELOW"
        )
        self.assertEqual(first_touch, index[1])
        self.assertEqual(first_trade, index[2])

    def test_close_through_and_sweep_use_frozen_precedence(self):
        close = _primitive_row(
            available=True,
            touched=True,
            traded_through=True,
            closed_through=True,
            rejected=False,
            swept=False,
        )
        sweep = _primitive_row(
            available=True,
            touched=True,
            traded_through=True,
            closed_through=False,
            rejected=True,
            swept=True,
        )
        self.assertEqual(
            derive_frozen_interaction_state(close, "london_high"),
            "CLOSE_THROUGH",
        )
        self.assertEqual(
            derive_frozen_interaction_state(sweep, "london_high"), "SWEEP"
        )

    def test_acceptance_is_not_known_before_or_close(self):
        events, _ = _synthetic_events()
        audit = build_timestamp_audit(events)
        close = events.loc[events["interaction_state"].eq("CLOSE_THROUGH")].iloc[0]
        self.assertEqual(
            close["acceptance_confirmation_timestamp"],
            close["30m_or_close_timestamp"],
        )
        self.assertGreater(
            close["acceptance_confirmation_timestamp"],
            close["first_trade_through_timestamp"],
        )
        self.assertFalse(audit["eventual_state_known_at_first_trade_through"].any())
        self.assertTrue(audit["chronology_valid"].all())

    def test_sweep_direction_returns_to_original_side(self):
        events, _ = _synthetic_events()
        sweep = events.loc[events["interaction_state"].eq("SWEEP")].iloc[0]
        self.assertEqual(sweep["london_level_type"], "LONDON_LOW")
        self.assertEqual(sweep["frozen_start_side"], "ABOVE")
        self.assertEqual(sweep["frozen_trade_through_direction"], "DOWN")
        self.assertEqual(sweep["interaction_direction"], "UP")
        self.assertTrue(sweep["hypothesis_directional_context"])

    def test_event_anchor_excursion_starts_after_anchor_bar(self):
        index = pd.date_range(
            "2024-07-01 10:00", periods=7, freq="min", tz="America/New_York"
        )
        bars = pd.DataFrame(
            {
                "high": [500.0, 101.0, 102.0, 103.0, 104.0, 105.0, 999.0],
                "low": [1.0, 99.5, 99.0, 98.5, 98.0, 97.5, 0.0],
            },
            index=index,
        )
        result = _anchor_outcomes(
            bars,
            anchor_timestamp=index[0],
            direction="UP",
            reference_price=100.0,
            or_width_points=10.0,
            prefix="test_anchor",
        )
        self.assertTrue(result["test_anchor_5m_complete"])
        self.assertEqual(result["test_anchor_5m_mfe_points"], 5.0)
        self.assertEqual(result["test_anchor_5m_mae_points"], 2.5)
        self.assertEqual(result["test_anchor_5m_end_timestamp"], index[5])

    def test_orb_and_no_orb_grouping(self):
        events, _ = _synthetic_events()
        close = events.loc[events["interaction_state"].eq("CLOSE_THROUGH")].iloc[0]
        sweep = events.loc[events["interaction_state"].eq("SWEEP")].iloc[0]
        self.assertEqual(close["orb_confirmation_group"], "SAME_DIRECTION_ORB")
        self.assertTrue(close["existing_print_orb_present"])
        self.assertEqual(sweep["orb_confirmation_group"], "NO_ORB")
        self.assertFalse(sweep["existing_print_orb_present"])
        self.assertTrue(pd.isna(sweep["orb_signal_timestamp"]))

    def test_dev_only_enforcement_and_fixed_split(self):
        assert_development_input_path("data/example_DEVELOPMENT.csv")
        assert_development_input_path("features/example_DEV_features.csv")
        with self.assertRaises(ValueError):
            assert_development_input_path("data/reserved.csv")
        features, prices, outcomes = _synthetic_inputs()
        features.loc[0, "session_date"] = "2025-07-01"
        with self.assertRaises(ValueError):
            build_london_interaction_events(features, prices, outcomes)

    def test_stability_classification_uses_all_dev_segments(self):
        rows = []
        for segment in (
            "FULL_DEVELOPMENT",
            "DEV_FIRST_HALF",
            "DEV_SECOND_HALF",
        ):
            for level_scope in ("ALL", "LONDON_HIGH", "LONDON_LOW"):
                for horizon in HORIZONS:
                    for state, mfe, mae in (
                        ("CLOSE_THROUGH", 0.003, 0.0015),
                        ("SWEEP", 0.002, 0.0012),
                    ):
                        rows.append(
                            {
                                "analysis_population": "HYPOTHESIS_DIRECTIONAL_CONTEXT",
                                "dev_segment": segment,
                                "level_scope": level_scope,
                                "outcome_horizon": horizon,
                                "interaction_state": state,
                                "event_n": 12,
                                "median_mfe_pct": mfe,
                                "median_mae_pct": mae,
                            }
                        )
        stability, classification = build_stability_table(pd.DataFrame(rows))
        self.assertEqual(
            classification["classification"],
            "CONSISTENT_HYPOTHESIS_CANDIDATE",
        )
        self.assertEqual(set(stability["dev_segment"]), set((
            "FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF"
        )))

    def test_registered_experiment_is_development_only_and_unvalidated(self):
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
        self.assertFalse(record["reserved_data_exposed"])
        self.assertFalse(record["confirmatory"])
        self.assertFalse(record["summary_metrics"]["hypothesis_validated"])
        self.assertFalse(record["summary_metrics"]["human_review_complete"])
        self.assertEqual(record["status"], "running")


def _primitive_row(**flags):
    row = {}
    for level in ("london_high", "london_low"):
        for name, value in flags.items():
            row[f"level_{level}_{name}"] = value
    return row


def _synthetic_events():
    features, prices, outcomes = _synthetic_inputs()
    return build_london_interaction_events(features, prices, outcomes)


def _synthetic_inputs():
    feature_rows = []
    price_rows = []
    dates = [pd.Timestamp("2024-07-01"), pd.Timestamp("2025-01-02")]
    for offset, stamp in enumerate(dates):
        session_date = stamp.date()
        index = pd.date_range(
            f"{session_date.isoformat()} 09:31",
            f"{session_date.isoformat()} 16:00",
            freq="min",
            tz="America/New_York",
        )
        for timestamp in index:
            if offset == 0:
                open_price = 99.0
                high, low, close = 99.5, 98.8, 99.0
                if timestamp >= pd.Timestamp(
                    f"{session_date.isoformat()} 09:40", tz="America/New_York"
                ):
                    high = 101.2
                if timestamp == pd.Timestamp(
                    f"{session_date.isoformat()} 10:00", tz="America/New_York"
                ):
                    close = 101.0
            else:
                open_price = 101.0
                high, low, close = 101.2, 100.5, 101.0
                if timestamp >= pd.Timestamp(
                    f"{session_date.isoformat()} 09:45", tz="America/New_York"
                ):
                    low = 99.0
            price_rows.append(
                {
                    "timestamp_et": timestamp,
                    "session_date": session_date,
                    "contract": "MNQ TEST",
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1,
                }
            )
        row = {
            "session_date": session_date,
            "contract": "MNQ TEST",
            "or_minutes": 30,
            "or_feature_available": True,
            "or_available_at": pd.Timestamp(
                f"{session_date.isoformat()} 10:00", tz="America/New_York"
            ),
            "or_last_bar_end": pd.Timestamp(
                f"{session_date.isoformat()} 10:00", tz="America/New_York"
            ),
            "or_high": 101.2,
            "or_low": 98.8 if offset == 0 else 99.0,
            "or_open": 99.0 if offset == 0 else 101.0,
            "or_close": 101.0,
            "or_width_points": 2.4 if offset == 0 else 2.2,
        }
        if offset == 0:
            row.update(_level_fields("london_high", 100.0, "BELOW", "CLOSE_THROUGH"))
            row.update(_level_fields("london_low", 90.0, "ABOVE", "NO_INTERACTION"))
        else:
            row.update(_level_fields("london_high", 110.0, "BELOW", "NO_INTERACTION"))
            row.update(_level_fields("london_low", 100.0, "ABOVE", "SWEEP"))
        feature_rows.append(row)

    outcome = {
        "session_date": dates[0].date(),
        "contract": "MNQ TEST",
        "or_minutes": 30,
        "breakout_type": "PRINT",
        "breakout_direction": "LONG",
        "breakout_timestamp": pd.Timestamp(
            "2024-07-01 10:05", tz="America/New_York"
        ),
        "breakout_price": 101.2,
        "feature_row_key": "2024-07-01_30m",
        "outcome_definition": "synthetic clean post-signal bars",
    }
    for horizon in HORIZONS:
        outcome.update(
            {
                f"post_signal_bar_{horizon}_complete": True,
                f"post_signal_bar_{horizon}_bars": 5,
                f"post_signal_bar_{horizon}_end_timestamp": pd.Timestamp(
                    "2024-07-01 10:10", tz="America/New_York"
                ),
                f"post_signal_bar_{horizon}_mfe_points": 1.0,
                f"post_signal_bar_{horizon}_mae_points": 0.5,
                f"post_signal_bar_{horizon}_mfe_pct": 0.01,
                f"post_signal_bar_{horizon}_mae_pct": 0.005,
            }
        )
    features = pd.DataFrame(feature_rows)[required_feature_columns()]
    outcomes = pd.DataFrame([outcome])[required_outcome_columns()]
    prices = pd.DataFrame(price_rows)
    return features, prices, outcomes


def _level_fields(level, price, start_side, state):
    flags = {
        "NO_INTERACTION": (False, False, False, False, False),
        "CLOSE_THROUGH": (True, True, True, False, False),
        "SWEEP": (True, True, False, True, True),
    }[state]
    touched, traded, closed, rejected, swept = flags
    return {
        f"{level}_price": price,
        f"level_{level}_available": True,
        f"level_{level}_start_side": start_side,
        f"level_{level}_touched": touched,
        f"level_{level}_traded_through": traded,
        f"level_{level}_closed_through": closed,
        f"level_{level}_rejected": rejected,
        f"level_{level}_swept": swept,
    }


if __name__ == "__main__":
    unittest.main()
