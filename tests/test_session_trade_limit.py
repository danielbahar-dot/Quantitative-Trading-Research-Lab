import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.backtesting.session_trade_limit import (
    EXECUTED,
    REJECTED,
    SESSION_TRADE_LIMIT,
    apply_session_trade_limit,
)


TZ = "America/New_York"
SESSION_DATE = pd.Timestamp("2026-01-05").date()


def candidate_row(
    direction: str,
    signal_time: str,
    *,
    valid: bool = True,
    invalid_reason: str = "",
    or_minutes: int = 5,
    breakout_type: str = "PRINT",
) -> dict:
    timestamp = pd.Timestamp(signal_time, tz=TZ)
    return {
        "session_date": SESSION_DATE,
        "contract": "MNQ TEST",
        "or_minutes": or_minutes,
        "breakout_type": breakout_type,
        "direction": direction,
        "signal_time": timestamp,
        "entry_time": timestamp if valid else pd.NaT,
        "entry_price": 100.0,
        "initial_stop": 95.0,
        "initial_target": 110.0,
        "risk_points": 5.0,
        "candidate_validity": valid,
        "invalid_reason": invalid_reason,
    }


def trade_row(
    candidate: dict,
    *,
    ambiguous: bool = False,
    exit_reason: str = "TARGET",
    result_r: float | None = 2.0,
) -> dict:
    return {
        "trade_id": (
            f"{candidate['session_date']}_{candidate['or_minutes']}m_"
            f"{candidate['breakout_type']}_{candidate['direction']}_"
            f"{candidate['signal_time'].strftime('%H%M')}"
        ),
        "session_date": candidate["session_date"],
        "contract": candidate["contract"],
        "or_minutes": candidate["or_minutes"],
        "breakout_type": candidate["breakout_type"],
        "direction": candidate["direction"],
        "signal_time": candidate["signal_time"],
        "entry_time": candidate["entry_time"],
        "entry_price": candidate["entry_price"],
        "initial_stop": candidate["initial_stop"],
        "initial_target": candidate["initial_target"],
        "risk_points": candidate["risk_points"],
        "exit_time": candidate["entry_time"] + pd.Timedelta(minutes=3),
        "exit_price": 110.0 if not ambiguous else None,
        "exit_reason": exit_reason,
        "ambiguity_reason": exit_reason if ambiguous else "",
        "ambiguous": ambiguous,
        "excluded_from_performance": ambiguous,
        "result_r": result_r,
        "pnl_points": 10.0 if not ambiguous else None,
    }


class SessionTradeLimitTests(unittest.TestCase):
    def test_earliest_valid_trade_executes_and_later_candidate_is_retained(self):
        first = candidate_row("LONG", "2026-01-05 09:42")
        second = candidate_row("SHORT", "2026-01-05 10:05")
        candidates = pd.DataFrame([second, first])
        trades = pd.DataFrame([trade_row(second), trade_row(first)])

        executed, audit = apply_session_trade_limit(candidates, trades)

        self.assertEqual(len(executed), 1)
        self.assertEqual(executed.iloc[0]["direction"], "LONG")
        self.assertEqual(
            audit.loc[audit["direction"] == "LONG", "gate4d_status"].iloc[0],
            EXECUTED,
        )
        rejected = audit.loc[audit["direction"] == "SHORT"].iloc[0]
        self.assertEqual(rejected["gate4d_status"], REJECTED)
        self.assertEqual(rejected["rejection_reason"], SESSION_TRADE_LIMIT)

    def test_ambiguous_first_candidate_does_not_consume_allowance(self):
        first = candidate_row("LONG", "2026-01-05 09:42")
        second = candidate_row("SHORT", "2026-01-05 10:05")
        candidates = pd.DataFrame([first, second])
        trades = pd.DataFrame(
            [
                trade_row(
                    first,
                    ambiguous=True,
                    exit_reason="AMBIGUOUS_ENTRY_STOP",
                    result_r=None,
                ),
                trade_row(second),
            ]
        )

        executed, audit = apply_session_trade_limit(candidates, trades)

        self.assertEqual(list(executed["direction"]), ["SHORT"])
        first_audit = audit.loc[audit["direction"] == "LONG"].iloc[0]
        self.assertEqual(
            first_audit["rejection_reason"], "AMBIGUOUS_ENTRY_STOP"
        )
        self.assertFalse(bool(first_audit["session_trade_taken"]))

    def test_invalid_first_candidate_does_not_consume_allowance(self):
        first = candidate_row(
            "LONG",
            "2026-01-05 09:42",
            valid=False,
            invalid_reason="INVALID_ENTRY_RELATIVE_TO_STOP",
        )
        second = candidate_row("SHORT", "2026-01-05 10:05")
        candidates = pd.DataFrame([first, second])
        trades = pd.DataFrame([trade_row(second)])

        executed, audit = apply_session_trade_limit(candidates, trades)

        self.assertEqual(list(executed["direction"]), ["SHORT"])
        self.assertEqual(
            audit.iloc[0]["rejection_reason"],
            "INVALID_ENTRY_RELATIVE_TO_STOP",
        )

    def test_variants_have_independent_session_allowances(self):
        five = candidate_row("LONG", "2026-01-05 09:42", or_minutes=5)
        ten = candidate_row("LONG", "2026-01-05 09:45", or_minutes=10)
        candidates = pd.DataFrame([five, ten])
        trades = pd.DataFrame([trade_row(five), trade_row(ten)])

        executed, _ = apply_session_trade_limit(candidates, trades)

        self.assertEqual(len(executed), 2)
        self.assertEqual(set(executed["or_minutes"]), {5, 10})

    def test_selected_exit_record_is_preserved_and_inputs_are_not_mutated(self):
        first = candidate_row("LONG", "2026-01-05 09:42")
        candidates = pd.DataFrame([first])
        trades = pd.DataFrame([trade_row(first)])
        original_candidates = candidates.copy(deep=True)
        original_trades = trades.copy(deep=True)

        executed, _ = apply_session_trade_limit(candidates, trades)

        assert_frame_equal(candidates, original_candidates)
        assert_frame_equal(trades, original_trades)
        self.assertEqual(executed.iloc[0]["exit_reason"], "TARGET")
        self.assertEqual(executed.iloc[0]["result_r"], 2.0)
        self.assertEqual(executed.iloc[0]["pnl_points"], 10.0)

    def test_no_duplicate_executions_within_session_variant(self):
        rows = [
            candidate_row("LONG", "2026-01-05 09:42"),
            candidate_row("SHORT", "2026-01-05 10:05"),
        ]
        executed, _ = apply_session_trade_limit(
            pd.DataFrame(rows),
            pd.DataFrame([trade_row(row) for row in rows]),
        )
        duplicates = executed.duplicated(
            ["session_date", "or_minutes", "breakout_type"],
            keep=False,
        )
        self.assertFalse(bool(duplicates.any()))


if __name__ == "__main__":
    unittest.main()
