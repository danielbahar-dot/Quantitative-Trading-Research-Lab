import unittest

import pandas as pd

from src.visualization.research_viewer import build_research_viewer, find_orb_signals


class ResearchViewerTests(unittest.TestCase):
    def setUp(self):
        first = pd.date_range("2025-01-06 09:30", periods=3, freq="min", tz="America/New_York")
        second = pd.date_range("2025-01-07 09:30", periods=3, freq="min", tz="America/New_York")
        index = first.append(second)
        self.prices = pd.DataFrame(
            {"session_date": [stamp.date() for stamp in index], "contract": "MNQ TEST", "open": [100, 101, 102, 110, 111, 112], "high": [102, 103, 104, 112, 113, 114], "low": [99, 100, 101, 109, 110, 111], "close": [101, 102, 103, 111, 112, 113], "volume": 10},
            index=index,
        )
        self.levels = pd.DataFrame(
            {"session_date": [first[0].date(), second[0].date()], "or_minutes": [5, 5], "valid_or": [True, True], "or_high": [104.0, 114.0], "or_low": [99.0, 109.0], "or_mid": [101.5, 111.5]}
        )

    def test_sessions_are_compressed_and_or_lines_do_not_connect(self):
        figure = build_research_viewer(self.prices, self.levels, start_date="2025-01-06", end_date="2025-01-07", or_minutes=5, start_time="09:30", end_time="09:32")
        self.assertEqual(list(figure.data[0].x), [0, 1, 2, 3, 4, 5])
        self.assertEqual(list(figure.data[1].x), [0, 2, None, 3, 5, None])
        self.assertFalse(figure.data[1].connectgaps)
        self.assertEqual(figure.layout.meta["sessions"], 2)
        self.assertEqual(figure.layout.meta["candles"], 6)
        self.assertEqual(list(figure.layout.xaxis.range), [-0.75, 5.75])
        self.assertTrue(figure.layout.xaxis.showticklabels)
        self.assertTrue(figure.layout.xaxis.automargin)
        self.assertGreaterEqual(figure.layout.margin.b, 90)

    def test_both_axes_remain_independently_scalable(self):
        figure = build_research_viewer(self.prices, self.levels, start_date="2025-01-06", end_date="2025-01-06", or_minutes=5, start_time="09:30", end_time="09:32")
        self.assertFalse(figure.layout.xaxis.fixedrange)
        self.assertFalse(figure.layout.yaxis.fixedrange)

    def test_or_shading_covers_true_bar_end_interval_only(self):
        index = pd.date_range(
            "2025-01-06 09:30",
            "2025-01-06 09:36",
            freq="min",
            tz="America/New_York",
        )
        prices = pd.DataFrame(
            {
                "session_date": [stamp.date() for stamp in index],
                "contract": "MNQ TEST",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 10,
            },
            index=index,
        )
        levels = pd.DataFrame(
            {
                "session_date": [index[0].date()],
                "or_minutes": [5],
                "valid_or": [True],
                "or_high": [101.0],
                "or_low": [99.0],
                "or_mid": [100.0],
            }
        )

        figure = build_research_viewer(
            prices,
            levels,
            start_date="2025-01-06",
            end_date="2025-01-06",
            or_minutes=5,
            start_time="09:30",
            end_time="09:36",
        )

        self.assertEqual(len(figure.layout.shapes), 1)
        self.assertEqual(float(figure.layout.shapes[0].x0), 0.5)
        self.assertEqual(float(figure.layout.shapes[0].x1), 5.5)


class ORBSignalVisualizationTests(unittest.TestCase):
    def setUp(self):
        self.session_date = pd.Timestamp("2025-01-06").date()
        index = pd.date_range(
            "2025-01-06 09:30",
            "2025-01-06 11:31",
            freq="min",
            tz="America/New_York",
        )
        self.prices = pd.DataFrame(
            {
                "session_date": self.session_date,
                "contract": "MNQ TEST",
                "open": 99.5,
                "high": 100.0,
                "low": 99.0,
                "close": 99.5,
                "volume": 10,
            },
            index=index,
        )
        self.levels = pd.DataFrame(
            {
                "session_date": [self.session_date],
                "or_minutes": [5],
                "valid_or": [True],
                "or_high": [100.0],
                "or_low": [99.0],
                "or_mid": [99.5],
            }
        )

    def test_print_skips_ambiguous_bar_then_fires_once_per_direction(self):
        self.prices.loc["2025-01-06 09:34", ["high", "close"]] = [101.0, 100.5]
        self.prices.loc["2025-01-06 09:35", ["high", "low"]] = [101.0, 98.0]
        self.prices.loc["2025-01-06 09:36", ["high", "low"]] = [101.0, 98.0]
        self.prices.loc["2025-01-06 09:37", "high"] = 100.25
        self.prices.loc["2025-01-06 09:38", "high"] = 100.5
        self.prices.loc["2025-01-06 09:39", "low"] = 98.75
        self.prices.loc["2025-01-06 09:40", "low"] = 98.5

        signals, ambiguous = self._find("PRINT")

        self.assertEqual(list(signals["direction"]), ["LONG", "SHORT"])
        self.assertEqual(
            [value.strftime("%H:%M") for value in signals["signal_time"]],
            ["09:37", "09:39"],
        )
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous.iloc[0]["signal_time"].strftime("%H:%M"), "09:36")
        self.assertTrue(bool(ambiguous.iloc[0]["ambiguity_status"]))

    def test_close_uses_breakout_close_and_includes_1130_cutoff(self):
        self.prices.loc["2025-01-06 09:35", ["high", "low", "close"]] = [
            101.0,
            98.0,
            99.5,
        ]
        self.prices.loc["2025-01-06 09:36", "close"] = 100.25
        self.prices.loc["2025-01-06 09:37", "close"] = 100.5
        self.prices.loc["2025-01-06 11:30", "close"] = 98.75
        self.prices.loc["2025-01-06 11:31", "close"] = 98.5

        signals, ambiguous = self._find("CLOSE")

        self.assertEqual(list(signals["direction"]), ["LONG", "SHORT"])
        self.assertEqual(
            [value.strftime("%H:%M") for value in signals["signal_time"]],
            ["09:36", "11:30"],
        )
        self.assertTrue(ambiguous.empty)

    def test_figure_adds_signal_and_ambiguity_markers_with_required_hover(self):
        self.prices.loc["2025-01-06 09:35", ["high", "low"]] = [101.0, 98.0]
        self.prices.loc["2025-01-06 09:36", ["high", "low"]] = [101.0, 98.0]
        self.prices.loc["2025-01-06 09:37", "high"] = 100.25
        figure = build_research_viewer(
            self.prices,
            self.levels,
            start_date="2025-01-06",
            end_date="2025-01-06",
            or_minutes=5,
            breakout_type="PRINT",
            start_time="09:30",
            end_time="11:31",
        )

        traces = {trace.name: trace for trace in figure.data}
        self.assertIn("Long signal", traces)
        self.assertIn("Ambiguous PRINT bar", traces)
        hover = traces["Long signal"].text[0]
        for field in (
            "session_date",
            "direction",
            "breakout_type",
            "signal_time",
            "OR high",
            "OR low",
            "OR mid",
            "ambiguity status",
        ):
            self.assertIn(field, hover)
        self.assertEqual(figure.layout.meta["long_signals"], 1)
        self.assertEqual(figure.layout.meta["ambiguous_bar_count"], 1)
        self.assertIn("signal_time: 2025-01-06 09:37 ET", hover)

    def _find(self, breakout_type):
        return find_orb_signals(
            self.prices,
            self.levels,
            start_date="2025-01-06",
            end_date="2025-01-06",
            or_minutes=5,
            breakout_type=breakout_type,
        )


if __name__ == "__main__":
    unittest.main()
