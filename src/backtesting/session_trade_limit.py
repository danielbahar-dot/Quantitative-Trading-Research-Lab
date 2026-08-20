"""Gate 4D one-trade-per-session eligibility for ORB V0.1.

This layer consumes validated candidate and completed-trade records. It does
not alter signal detection, candidate construction, or exit calculations.
"""

from __future__ import annotations

import pandas as pd


SESSION_TRADE_LIMIT = "SESSION_TRADE_LIMIT"
EXECUTED = "EXECUTED"
REJECTED = "REJECTED"
INVALID_CANDIDATE = "INVALID_CANDIDATE"
MISSING_COMPLETED_TRADE = "MISSING_COMPLETED_TRADE"

GROUP_COLUMNS = ["session_date", "or_minutes", "breakout_type"]
KEY_COLUMNS = [*GROUP_COLUMNS, "direction", "signal_time"]

AUDIT_COLUMNS = [
    "gate4d_status",
    "rejection_reason",
    "session_trade_taken",
    "selected_trade_id",
    "completed_trade_exit_reason",
    "completed_trade_ambiguous",
    "completed_trade_excluded",
]


def apply_session_trade_limit(
    candidates: pd.DataFrame,
    completed_trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return canonical executed trades and a candidate-level eligibility audit.

    Within each session/duration/breakout variant, candidates are processed by
    executable time (falling back to signal time for invalid candidates). An
    invalid or ambiguous candidate never consumes the daily allowance.
    """
    _validate_inputs(candidates, completed_trades)
    if candidates.empty:
        return (
            completed_trades.iloc[0:0].copy(),
            pd.DataFrame(columns=[*candidates.columns, *AUDIT_COLUMNS]),
        )

    trade_lookup = {}
    for trade in completed_trades.itertuples(index=False):
        key = _record_key(trade)
        if key in trade_lookup:
            raise ValueError(f"Duplicate completed trade key: {key}")
        trade_lookup[key] = trade

    candidate_keys = {
        _record_key(candidate)
        for candidate in candidates.itertuples(index=False)
    }
    orphaned = set(trade_lookup).difference(candidate_keys)
    if orphaned:
        raise ValueError("Completed trades contain records without candidates")

    ordered = candidates.copy()
    ordered["_gate4d_sort_time"] = ordered["entry_time"].where(
        ordered["entry_time"].notna(),
        ordered["signal_time"],
    )
    ordered = ordered.sort_values(
        [*GROUP_COLUMNS, "_gate4d_sort_time", "signal_time", "direction"],
        kind="stable",
    )

    executed_rows: list[dict] = []
    audit_rows: list[dict] = []
    for _, session_candidates in ordered.groupby(GROUP_COLUMNS, sort=False):
        selected_trade_id = ""
        for candidate in session_candidates.drop(
            columns="_gate4d_sort_time"
        ).itertuples(index=False):
            key = _record_key(candidate)
            trade = trade_lookup.get(key)
            candidate_valid = bool(candidate.candidate_validity)
            trade_ambiguous = (
                bool(trade.ambiguous) if trade is not None else False
            )
            trade_excluded = (
                bool(trade.excluded_from_performance)
                if trade is not None
                else False
            )

            status = REJECTED
            rejection_reason = ""
            if not candidate_valid:
                rejection_reason = (
                    str(candidate.invalid_reason)
                    if getattr(candidate, "invalid_reason", "")
                    else INVALID_CANDIDATE
                )
            elif trade is None:
                rejection_reason = MISSING_COMPLETED_TRADE
            elif trade_ambiguous or trade_excluded:
                rejection_reason = str(
                    trade.exit_reason or trade.ambiguity_reason
                )
            elif selected_trade_id:
                rejection_reason = SESSION_TRADE_LIMIT
            else:
                status = EXECUTED
                selected_trade_id = str(trade.trade_id)
                executed_rows.append(trade._asdict())

            audit_rows.append(
                {
                    **candidate._asdict(),
                    "gate4d_status": status,
                    "rejection_reason": rejection_reason,
                    "session_trade_taken": bool(selected_trade_id),
                    "selected_trade_id": selected_trade_id,
                    "completed_trade_exit_reason": (
                        str(trade.exit_reason) if trade is not None else ""
                    ),
                    "completed_trade_ambiguous": trade_ambiguous,
                    "completed_trade_excluded": trade_excluded,
                }
            )

    executed = pd.DataFrame(executed_rows, columns=completed_trades.columns)
    audit = pd.DataFrame(
        audit_rows,
        columns=[*candidates.columns, *AUDIT_COLUMNS],
    )
    if not executed.empty:
        executed = executed.sort_values(
            [*GROUP_COLUMNS, "entry_time", "signal_time"],
            kind="stable",
        ).reset_index(drop=True)
    audit = audit.sort_values(
        [*GROUP_COLUMNS, "signal_time", "entry_time", "direction"],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)
    return executed, audit


def _record_key(record) -> tuple:
    return tuple(getattr(record, column) for column in KEY_COLUMNS)


def _validate_inputs(
    candidates: pd.DataFrame,
    completed_trades: pd.DataFrame,
) -> None:
    candidate_required = {
        *KEY_COLUMNS,
        "entry_time",
        "candidate_validity",
        "invalid_reason",
    }
    missing_candidates = candidate_required.difference(candidates.columns)
    if missing_candidates:
        raise ValueError(
            "Candidates are missing required columns: "
            + ", ".join(sorted(missing_candidates))
        )

    trade_required = {
        *KEY_COLUMNS,
        "trade_id",
        "entry_time",
        "exit_reason",
        "ambiguity_reason",
        "ambiguous",
        "excluded_from_performance",
    }
    missing_trades = trade_required.difference(completed_trades.columns)
    if missing_trades:
        raise ValueError(
            "Completed trades are missing required columns: "
            + ", ".join(sorted(missing_trades))
        )
