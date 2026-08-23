import csv
import io
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest
from urllib.request import urlopen

import pandas as pd

from src.visualization.research_viewer_app import (
    ViewerDefaults,
    ViewerState,
    _handler_for,
)


class ResearchViewerAppExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index = pd.date_range(
            "2026-01-05 09:30",
            "2026-01-05 09:37",
            freq="min",
            tz="America/New_York",
        )
        prices = pd.DataFrame(
            {
                "session_date": pd.Timestamp("2026-01-05").date(),
                "contract": "MNQ TEST",
                "open": 99.5,
                "high": 100.0,
                "low": 99.0,
                "close": 99.5,
                "volume": 10,
            },
            index=index,
        )
        prices.loc["2026-01-05 09:36", ["high", "close"]] = [
            101.0,
            100.25,
        ]
        prices.loc[
            "2026-01-05 09:37", ["open", "high", "low", "close"]
        ] = [102.0, 108.0, 101.0, 107.0]
        levels = pd.DataFrame(
            {
                "session_date": [pd.Timestamp("2026-01-05").date()],
                "or_minutes": [5],
                "valid_or": [True],
                "or_high": [100.0],
                "or_low": [99.0],
                "or_mid": [99.5],
            }
        )
        defaults = ViewerDefaults(
            start_date="2026-01-05",
            end_date="2026-01-05",
            or_minutes=5,
            breakout_type="CLOSE",
        )
        state = ViewerState(prices, levels, defaults)
        cls.state = state
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(state))
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_signal_candidate_and_trade_csv_exports_are_available(self):
        query = (
            "start_date=2026-01-05&end_date=2026-01-05"
            "&or_minutes=5&breakout_type=CLOSE"
        )
        with urlopen(f"{self.base_url}/api/signals.csv?{query}") as response:
            signal_rows = list(
                csv.DictReader(io.StringIO(response.read().decode("utf-8")))
            )
        with urlopen(f"{self.base_url}/api/candidates.csv?{query}") as response:
            candidate_rows = list(
                csv.DictReader(io.StringIO(response.read().decode("utf-8")))
            )
        with urlopen(f"{self.base_url}/api/trades.csv?{query}") as response:
            trade_rows = list(
                csv.DictReader(io.StringIO(response.read().decode("utf-8")))
            )

        self.assertEqual(len(signal_rows), 1)
        self.assertEqual(len(candidate_rows), 1)
        self.assertEqual(len(trade_rows), 1)
        candidate = candidate_rows[0]
        self.assertEqual(candidate["signal_time"], "2026-01-05T09:36:00-05:00")
        self.assertEqual(candidate["entry_time"], "2026-01-05T09:37:00-05:00")
        self.assertEqual(float(candidate["entry_price"]), 102.0)
        self.assertEqual(float(candidate["initial_stop"]), 99.5)
        self.assertEqual(float(candidate["risk_points"]), 2.5)
        self.assertEqual(float(candidate["initial_target"]), 107.0)
        self.assertEqual(candidate["candidate_validity"], "True")
        self.assertEqual(candidate["invalid_reason"], "")
        trade = trade_rows[0]
        self.assertEqual(trade["exit_time"], "2026-01-05T09:37:00-05:00")
        self.assertEqual(float(trade["exit_price"]), 107.0)
        self.assertEqual(trade["exit_reason"], "TARGET")
        self.assertEqual(float(trade["result_r"]), 2.0)
        self.assertEqual(trade["ambiguous"], "False")

    def test_browser_selector_exposes_20_minutes(self):
        self.assertIn(20, self.state.browser_config["or_choices"])


if __name__ == "__main__":
    unittest.main()
