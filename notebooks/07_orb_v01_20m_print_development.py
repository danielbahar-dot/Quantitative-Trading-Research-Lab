"""Generate the DEVELOPMENT-only 20-minute PRINT Gate 4D supplement.

This driver reuses the validated signal, candidate, completed-trade, and daily
limit layers. It does not implement separate 20-minute strategy semantics and
does not load Validation or OOS price partitions.
"""

from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backtesting.candidate_entries import build_candidate_entries  # noqa: E402
from src.backtesting.completed_trades import simulate_completed_trades  # noqa: E402
from src.backtesting.session_trade_limit import (  # noqa: E402
    SESSION_TRADE_LIMIT,
    apply_session_trade_limit,
)
from src.data.partitions import load_partition_config  # noqa: E402
from src.experiments.orb_v01_development_diagnostics import (  # noqa: E402
    development_bounds,
)
from src.visualization.research_viewer import (  # noqa: E402
    find_orb_signals,
    load_or_levels,
    load_price_data,
)


OR_MINUTES = 20
BREAKOUT_TYPE = "PRINT"
DEVELOPMENT_DATA_FILE = (
    PROJECT_ROOT / "data" / "processed" / "MNQ_raw_cleaned_ET_DEVELOPMENT.csv"
)
OR_FILE = PROJECT_ROOT / "data" / "processed" / "mnq_or_levels.csv"
PARTITION_CONFIG_FILE = (
    PROJECT_ROOT
    / "config"
    / "datasets"
    / "mnq_1m_actual_contract_v1.partitions.json"
)
COMPLETED_TRADES_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "orb_v01_20m_print_DEV_completed_trades.csv"
)
CANDIDATE_AUDIT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "orb_v01_20m_print_DEV_candidate_audit.csv"
)


def build_development_20m_print(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Run 20m PRINT through the existing validated Gate 4D layers."""
    normalized_dates = pd.to_datetime(price_data["session_date"]).dt.normalize()
    if not normalized_dates.between(start, end, inclusive="both").all():
        raise ValueError("20m PRINT input contains a non-DEVELOPMENT price row")

    signals, ambiguous_bars = find_orb_signals(
        price_data,
        or_levels,
        start_date=start,
        end_date=end,
        or_minutes=OR_MINUTES,
        breakout_type=BREAKOUT_TYPE,
    )
    first_eligible = signals["signal_time"].map(
        lambda value: value.hour > 9 or (value.hour == 9 and value.minute >= 51)
    )
    if not first_eligible.all():
        raise ValueError("A 20m PRINT signal occurred before 09:51 ET")

    candidates = build_candidate_entries(
        price_data,
        signals,
        or_minutes=OR_MINUTES,
    )
    completed_candidates = simulate_completed_trades(price_data, candidates)
    executed, audit = apply_session_trade_limit(candidates, completed_candidates)

    if executed.duplicated(
        ["session_date", "or_minutes", "breakout_type"]
    ).any():
        raise ValueError("20m PRINT exceeds one executed trade per session")
    executed_dates = pd.to_datetime(executed["session_date"]).dt.normalize()
    if not executed_dates.between(start, end, inclusive="both").all():
        raise ValueError("20m PRINT output contains a non-DEVELOPMENT trade")

    valid_levels = or_levels.loc[
        or_levels["or_minutes"].eq(OR_MINUTES)
        & or_levels["valid_or"]
        & pd.to_datetime(or_levels["session_date"])
        .dt.normalize()
        .between(start, end, inclusive="both")
    ]
    counts = {
        "valid_or_sessions": int(len(valid_levels)),
        "signals": int(len(signals)),
        "long_signals": int(signals["direction"].eq("LONG").sum()),
        "short_signals": int(signals["direction"].eq("SHORT").sum()),
        "ambiguous_print_bars": int(len(ambiguous_bars)),
        "candidates": int(len(candidates)),
        "valid_candidates": int(candidates["candidate_validity"].sum()),
        "invalid_candidates": int((~candidates["candidate_validity"]).sum()),
        "ambiguous_completed_candidates": int(
            completed_candidates["ambiguous"].sum()
        ),
        "completed_candidates": int(len(completed_candidates)),
        "executed_trades": int(len(executed)),
        "session_trade_limit_rejections": int(
            audit["rejection_reason"].eq(SESSION_TRADE_LIMIT).sum()
        ),
    }
    return executed, audit, counts


def _csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    export = frame.copy()
    if "session_date" in export:
        export["session_date"] = export["session_date"].astype(str)
    for column in ("signal_time", "entry_time", "exit_time"):
        if column in export:
            export[column] = export[column].map(
                lambda value: value.isoformat() if pd.notna(value) else ""
            )
    return export


def main() -> int:
    config = load_partition_config(PARTITION_CONFIG_FILE)
    start, end = development_bounds(config)
    price_data = load_price_data(DEVELOPMENT_DATA_FILE)
    or_levels = load_or_levels(OR_FILE)
    executed, audit, counts = build_development_20m_print(
        price_data, or_levels, start, end
    )

    COMPLETED_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _csv_ready(executed).to_csv(COMPLETED_TRADES_FILE, index=False)
    _csv_ready(audit).to_csv(CANDIDATE_AUDIT_FILE, index=False)

    print(f"DEVELOPMENT ONLY: {start.date()} through {end.date()}")
    print(f"20m PRINT counts: {counts}")
    print(f"Completed trades: {COMPLETED_TRADES_FILE}")
    print(f"Candidate audit: {CANDIDATE_AUDIT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
