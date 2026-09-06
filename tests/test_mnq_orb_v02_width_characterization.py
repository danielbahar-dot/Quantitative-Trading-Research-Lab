from __future__ import annotations

import unittest

import pandas as pd

from src.experiments.mnq_orb_v02_width_characterization import (
    BAND_LABELS,
    assign_percentile_band,
    assert_development_input_path,
    characterize_or_width,
    development_half_labels,
)


class Stage3AWidthCharacterizationTests(unittest.TestCase):
    def test_fixed_percentile_band_boundaries(self):
        values = pd.Series([0.0, 0.1999, 0.2, 0.4, 0.6, 0.8, 0.9999, 1.0])
        bands = assign_percentile_band(values, pd.Series([True] * len(values)))
        self.assertEqual(
            bands.tolist(),
            [
                BAND_LABELS[0],
                BAND_LABELS[0],
                BAND_LABELS[1],
                BAND_LABELS[2],
                BAND_LABELS[3],
                BAND_LABELS[4],
                BAND_LABELS[4],
                BAND_LABELS[4],
            ],
        )

    def test_unavailable_warmup_rows_are_not_backfilled(self):
        bands = assign_percentile_band(
            pd.Series([0.9, float("nan"), 0.1]),
            pd.Series([False, True, True]),
        )
        self.assertTrue(pd.isna(bands.iloc[0]))
        self.assertTrue(pd.isna(bands.iloc[1]))
        self.assertEqual(bands.iloc[2], BAND_LABELS[0])

    def test_dev_only_enforcement(self):
        assert_development_input_path("signals/example_DEV_input.csv")
        with self.assertRaises(ValueError):
            assert_development_input_path("Validation/example.csv")
        events = _events()
        events.loc[0, "session_date"] = "2025-07-01"
        with self.assertRaises(ValueError):
            characterize_or_width(events)

    def test_development_half_split_keeps_dates_intact(self):
        dates = pd.Series(
            ["2024-06-21", "2024-06-21", "2024-06-24", "2024-06-25", "2024-06-26", "2024-06-27"]
        )
        labels, metadata = development_half_labels(dates)
        self.assertEqual(metadata["first_half_dates"], 2)
        self.assertEqual(metadata["second_half_dates"], 3)
        self.assertEqual(labels.iloc[:3].tolist(), ["DEV_FIRST_HALF"] * 3)
        self.assertEqual(labels.iloc[3:].tolist(), ["DEV_SECOND_HALF"] * 3)

    def test_long_short_and_or_duration_grouping(self):
        master, stability, direction, relationships, audit = characterize_or_width(
            _events()
        )
        row = master[
            (master["lookback_sessions"] == 5)
            & (master["or_minutes"].astype(str) == "15")
            & (master["percentile_band"] == BAND_LABELS[0])
            & (master["outcome_horizon"] == "30m")
        ].iloc[0]
        self.assertEqual(row["event_n"], 2)
        self.assertEqual(row["long_n"], 1)
        self.assertEqual(row["short_n"], 1)
        self.assertEqual(
            set(direction["breakout_direction"].unique()), {"LONG", "SHORT"}
        )
        self.assertEqual(set(stability["dev_segment"].unique()), {
            "FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF"
        })
        self.assertEqual(len(relationships), 12)
        self.assertEqual(audit["validation_accessed"], False)


def _events() -> pd.DataFrame:
    rows = []
    dates = ["2024-06-21", "2024-06-24", "2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28"]
    for index, (date, duration) in enumerate(zip(dates, [15, 15, 20, 20, 30, 30])):
        row = {
            "session_date": date,
            "or_minutes": duration,
            "breakout_type": "PRINT",
            "breakout_direction": "LONG" if index % 2 == 0 else "SHORT",
        }
        for lookback in (5, 10, 15, 20):
            row[f"or_width_hist_{lookback}_percentile"] = 0.1
            row[f"or_width_hist_{lookback}_available"] = True
        for horizon in ("5m", "15m", "30m", "60m", "session_end"):
            row[f"post_signal_bar_{horizon}_complete"] = True
            row[f"post_signal_bar_{horizon}_mfe_pct"] = 0.001 * (index + 1)
            row[f"post_signal_bar_{horizon}_mae_pct"] = 0.0005 * (index + 1)
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
