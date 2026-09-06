from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_stage3a import (
    DIRECTIONAL_FIELDS,
    ROOM_LEVEL_ORDER,
    build_directional_state_events,
)


class Stage3ADirectionalStateTests(unittest.TestCase):
    def test_long_aligned_and_opposed(self):
        output, _ = _build(
            _event("LONG", "UP"),
            _event("LONG", "DOWN", session_date="2024-06-25"),
        )
        self.assertEqual(
            output["or_breakout_alignment"].tolist(), ["ALIGNED", "OPPOSED"]
        )

    def test_short_aligned_and_opposed(self):
        output, _ = _build(
            _event("SHORT", "DOWN"),
            _event("SHORT", "UP", session_date="2024-06-25"),
        )
        self.assertEqual(
            output["or_breakout_alignment"].tolist(), ["ALIGNED", "OPPOSED"]
        )

    def test_flat_handling(self):
        output, audit = _build(_event("LONG", "FLAT", or_open=95.0, or_close=95.0))
        self.assertEqual(output.iloc[0]["or_breakout_alignment"], "FLAT")
        self.assertEqual(audit["alignment_counts"]["FLAT"], 1)
        self.assertEqual(audit["missing_alignment_count"], 0)

    def test_directional_clv_long(self):
        output, _ = _build(_event("LONG", "UP", or_clv=0.8))
        self.assertAlmostEqual(output.iloc[0]["directional_clv"], 0.8)

    def test_directional_clv_short(self):
        output, _ = _build(_event("SHORT", "DOWN", or_clv=0.8))
        self.assertAlmostEqual(output.iloc[0]["directional_clv"], 0.2)

    def test_directional_net_move_sign_convention(self):
        output, _ = _build(
            _event("LONG", "UP", or_open=90.0, or_close=95.0),
            _event(
                "SHORT",
                "UP",
                or_open=90.0,
                or_close=95.0,
                session_date="2024-06-25",
            ),
        )
        self.assertEqual(
            output["directional_or_net_move_points"].tolist(), [5.0, -5.0]
        )
        self.assertAlmostEqual(output.iloc[0]["directional_or_net_move_pct"], 5 / 90)
        self.assertAlmostEqual(output.iloc[1]["directional_or_net_move_pct"], -5 / 90)

    def test_preserves_rows_columns_values_and_efficiency(self):
        step1a = pd.DataFrame(
            [
                _event("LONG", "UP", custom_field="kept", or_efficiency=0.75),
                _event(
                    "SHORT",
                    "DOWN",
                    session_date="2024-06-25",
                    custom_field="also kept",
                    or_efficiency=0.4,
                ),
            ]
        )
        output, audit = build_directional_state_events(step1a)

        self.assertEqual(len(output), len(step1a))
        self.assertEqual(audit["input_rows"], audit["output_rows"])
        pd.testing.assert_frame_equal(step1a, output[step1a.columns])
        self.assertEqual(output["or_efficiency"].tolist(), [0.75, 0.4])
        self.assertEqual(list(output.columns[-4:]), list(DIRECTIONAL_FIELDS))


def _event(
    breakout_direction: str,
    or_direction: str,
    *,
    session_date: str = "2024-06-24",
    or_open: float = 94.0,
    or_close: float = 96.0,
    or_clv: float = 0.7,
    or_efficiency: float = 0.6,
    **extra,
) -> dict[str, object]:
    net_points = or_close - or_open
    row: dict[str, object] = {
        "session_date": session_date,
        "contract": "MNQ 09-24",
        "or_minutes": 15,
        "breakout_type": "PRINT",
        "breakout_direction": breakout_direction,
        "breakout_timestamp": f"{session_date} 10:01:00-04:00",
        "or_direction": or_direction,
        "or_open": or_open,
        "or_close": or_close,
        "or_high": 100.0,
        "or_low": 90.0,
        "or_net_move_points": net_points,
        "or_net_move_pct": net_points / or_open,
        "or_clv": or_clv,
        "or_efficiency": or_efficiency,
        "next_level_type": None,
        "next_level_price": np.nan,
    }
    for level_name in ROOM_LEVEL_ORDER:
        row[level_name] = np.nan
        row[f"level_{level_name}_available"] = False
    row.update(extra)
    return row


def _build(*rows: dict[str, object]):
    return build_directional_state_events(pd.DataFrame(rows))


if __name__ == "__main__":
    unittest.main()
