"""Expected-schedule continuity segments over timeframe observations (D-137).

Generic data-layer utility: splits ``build_timeframe``-shaped observations
of one timeframe into fail-closed continuity segments along the M3
**expected** schedule (``expected_timeframe_schedule``).  A segment holds
consecutive expected buckets that are all present, all complete and of one
contract; a missing expected session, a missing expected bucket, an
incomplete observation or a contract change ends it.  Complete
session-truncated observations are ordinary members of a segment.

Extracted unchanged from External Liquidity (D-134), which remains its
frozen behavioural oracle.  No feature, liquidity or strategy concepts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from src.data.sessions import SessionSpec
from src.data.timeframes import expected_timeframe_schedule

# Break audit reasons, in precedence order when one boundary has several causes.
MISSING_EXPECTED_SESSION = "MISSING_EXPECTED_SESSION"
MISSING_EXPECTED_BUCKET = "MISSING_EXPECTED_BUCKET"
INCOMPLETE_BAR = "INCOMPLETE_BAR"
CONTRACT_CHANGE = "CONTRACT_CHANGE"
BREAK_PRECEDENCE = (MISSING_EXPECTED_SESSION, MISSING_EXPECTED_BUCKET, INCOMPLETE_BAR, CONTRACT_CHANGE)
BREAK_COLUMNS = ["timeframe", "break_index", "previous_bar_end", "next_bar_end", "reason",
                 "missing_buckets", "missing_sessions", "incomplete_bars", "contract_changed"]


class ContinuityError(ValueError):
    """Raised when observations cannot be placed on the expected schedule."""


def continuity_segments(
    tf_bars: pd.DataFrame,
    timeframe: Any,
    session_spec: SessionSpec,
    *,
    source_interval: Any = "1min",
) -> tuple[list[pd.DataFrame], pd.DataFrame]:
    """Split ``build_timeframe`` output into fail-closed continuity segments.

    Walks the M3 **expected** schedule (``expected_timeframe_schedule``) from
    the first to the last observed bucket.  A segment holds consecutive
    expected buckets that are all present, all complete and of one contract.
    A missing expected session, a missing expected bucket, an incomplete bar
    or a contract change ends it.  Returns the segments (complete bars only)
    and one audit row per break boundary (reason by ``BREAK_PRECEDENCE``;
    the contract flag is always recorded).  Raises ``ContinuityError`` when
    an observed bar is not an expected bucket.
    """
    if tf_bars.empty:
        return [], pd.DataFrame(columns=BREAK_COLUMNS)
    observed = tf_bars.sort_values("bar_start", kind="mergesort").reset_index(drop=True)
    first_date, last_date = min(observed["trading_date"]), max(observed["trading_date"])
    dates = [first_date + timedelta(days=offset) for offset in range((last_date - first_date).days + 1)]
    schedule = expected_timeframe_schedule(dates, timeframe, session_spec, source_interval=source_interval).reset_index(drop=True)
    key = list(zip(schedule["trading_date"], schedule["bar_start"]))
    position = {k: i for i, k in enumerate(key)}
    observed_pos = [position.get((d, s)) for d, s in zip(observed["trading_date"], observed["bar_start"])]
    if any(p is None for p in observed_pos):
        raise ContinuityError(f"{timeframe}: an observed bar is not in the expected M3 schedule")
    by_pos = dict(zip(observed_pos, observed.itertuples(index=False)))
    dates_observed = set(observed["trading_date"])

    segments, current, breaks = [], [], []
    pending = {"missing_buckets": 0, "missing_sessions": set(), "incomplete_bars": 0}
    last_bar = None

    def close_segment():
        nonlocal current
        if current:
            segments.append(pd.DataFrame(current))
        current = []

    def record_break(next_bar, contract_changed):
        reasons = set()
        if pending["missing_sessions"]:
            reasons.add(MISSING_EXPECTED_SESSION)
        if pending["missing_buckets"]:
            reasons.add(MISSING_EXPECTED_BUCKET)
        if pending["incomplete_bars"]:
            reasons.add(INCOMPLETE_BAR)
        if contract_changed:
            reasons.add(CONTRACT_CHANGE)
        reason = next(r for r in BREAK_PRECEDENCE if r in reasons)
        breaks.append({
            "timeframe": timeframe, "break_index": len(breaks),
            "previous_bar_end": None if last_bar is None else last_bar.bar_end,
            "next_bar_end": None if next_bar is None else next_bar.bar_end, "reason": reason,
            "missing_buckets": pending["missing_buckets"], "missing_sessions": len(pending["missing_sessions"]),
            "incomplete_bars": pending["incomplete_bars"], "contract_changed": contract_changed,
        })

    for pos in range(min(observed_pos), max(observed_pos) + 1):
        bar = by_pos.get(pos)
        if bar is None or not bar.is_complete:
            close_segment()
            if bar is None:
                pending["missing_buckets"] += 1
                if schedule["trading_date"].iloc[pos] not in dates_observed:
                    pending["missing_sessions"].add(schedule["trading_date"].iloc[pos])
            else:
                pending["incomplete_bars"] += 1
            continue
        gap = pending["missing_buckets"] or pending["incomplete_bars"]
        contract_changed = last_bar is not None and bar.contract != last_bar.contract
        if last_bar is not None and (gap or contract_changed):
            close_segment()
            record_break(bar, contract_changed)
        current.append(bar._asdict())
        last_bar = bar
        pending = {"missing_buckets": 0, "missing_sessions": set(), "incomplete_bars": 0}
    close_segment()
    return segments, pd.DataFrame(breaks, columns=BREAK_COLUMNS)
