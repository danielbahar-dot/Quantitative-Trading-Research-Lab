"""Generate canonical ORB V0.1 Gate 4D completed trades and candidate audit."""

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
from src.visualization.research_viewer import (  # noqa: E402
    find_orb_signals,
    load_or_levels,
    load_price_data,
)


OR_DURATIONS = (5, 10, 15, 30)
BREAKOUT_TYPES = ("PRINT", "CLOSE")

DATA_FILE = PROJECT_ROOT / "data" / "MNQ_raw_cleaned_ET.csv"
OR_FILE = PROJECT_ROOT / "data" / "processed" / "mnq_or_levels.csv"
COMPLETED_TRADES_FILE = (
    PROJECT_ROOT / "data" / "processed" / "orb_v01_completed_trades.csv"
)
CANDIDATE_AUDIT_FILE = (
    PROJECT_ROOT / "data" / "processed" / "orb_v01_candidate_audit.csv"
)


def build_gate4d_outputs(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build all eight baseline variants without changing upstream records."""
    start_date = price_data["session_date"].min()
    end_date = price_data["session_date"].max()
    executed_frames: list[pd.DataFrame] = []
    audit_frames: list[pd.DataFrame] = []

    for or_minutes in OR_DURATIONS:
        for breakout_type in BREAKOUT_TYPES:
            signals, _ = find_orb_signals(
                price_data,
                or_levels,
                start_date=start_date,
                end_date=end_date,
                or_minutes=or_minutes,
                breakout_type=breakout_type,
            )
            candidates = build_candidate_entries(
                price_data,
                signals,
                or_minutes=or_minutes,
            )
            completed = simulate_completed_trades(price_data, candidates)
            executed, audit = apply_session_trade_limit(candidates, completed)
            executed_frames.append(executed)
            audit_frames.append(audit)

    executed_all = pd.concat(executed_frames, ignore_index=True)
    audit_all = pd.concat(audit_frames, ignore_index=True)
    return executed_all, audit_all


def write_gate4d_outputs(
    completed_trades: pd.DataFrame,
    candidate_audit: pd.DataFrame,
) -> None:
    COMPLETED_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _csv_ready(completed_trades).to_csv(COMPLETED_TRADES_FILE, index=False)
    _csv_ready(candidate_audit).to_csv(CANDIDATE_AUDIT_FILE, index=False)


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
    price_data = load_price_data(DATA_FILE)
    or_levels = load_or_levels(OR_FILE)
    completed, audit = build_gate4d_outputs(price_data, or_levels)
    write_gate4d_outputs(completed, audit)

    group_columns = ["or_minutes", "breakout_type"]
    executed_counts = completed.groupby(group_columns).size()
    rejected_counts = (
        audit.loc[audit["rejection_reason"] == SESSION_TRADE_LIMIT]
        .groupby(group_columns)
        .size()
    )
    for key in executed_counts.index:
        print(
            f"{key[0]}m {key[1]}: {int(executed_counts[key])} executed, "
            f"{int(rejected_counts.get(key, 0))} session-limit rejections"
        )
    print(f"Completed trades: {COMPLETED_TRADES_FILE}")
    print(f"Candidate audit: {CANDIDATE_AUDIT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
