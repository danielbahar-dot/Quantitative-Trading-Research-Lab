"""Gate 5B: descriptive ORB V0.1 diagnostics on DEVELOPMENT only.

The completed-trade CSV is read in chunks and reserved-period rows are dropped
before any performance field is parsed or analyzed.  No strategy parameters or
validated trade outcomes are reconstructed or changed.
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.partitions import load_partition_config  # noqa: E402
from src.experiments.orb_v01_baseline import (  # noqa: E402
    build_equity_curves,
    calculate_independent_summary,
    calculate_monthly_summary,
    merge_crosscheck,
    vectorbt_crosscheck,
)
from src.experiments.orb_v01_development_diagnostics import (  # noqa: E402
    add_development_scope,
    assert_development_only,
    calculate_month_statistics,
    calculate_r_distribution,
    calculate_rolling_expectancy,
    development_bounds,
    load_development_trades,
    validate_development_diagnostics,
    write_development_outputs,
    write_development_visualizations,
)


COMPLETED_TRADES_FILES = (
    PROJECT_ROOT / "data" / "processed" / "orb_v01_completed_trades.csv",
    PROJECT_ROOT
    / "data"
    / "processed"
    / "orb_v01_20m_print_DEV_completed_trades.csv",
)
PARTITION_CONFIG_FILE = (
    PROJECT_ROOT
    / "config"
    / "datasets"
    / "mnq_1m_actual_contract_v1.partitions.json"
)
OUTPUT_DIR = (
    PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "baselines"
)


def main() -> int:
    import vectorbt as vbt

    config = load_partition_config(PARTITION_CONFIG_FILE)
    start, end = development_bounds(config)
    trades = load_development_trades(COMPLETED_TRADES_FILES, config)
    assert_development_only(trades, start, end)

    independent = calculate_independent_summary(trades)
    crosscheck = vectorbt_crosscheck(
        trades, independent, vbt_module=vbt
    )
    summary = add_development_scope(
        merge_crosscheck(independent, crosscheck), start, end
    )
    monthly = add_development_scope(
        calculate_monthly_summary(trades), start, end
    )
    equity = build_equity_curves(trades)
    rolling = calculate_rolling_expectancy(trades)
    distribution = calculate_r_distribution(trades)
    month_statistics = calculate_month_statistics(monthly)

    if monthly["month"].max() > end.strftime("%Y-%m"):
        raise ValueError("Monthly output extends beyond DEVELOPMENT")
    if equity.index.max() > end:
        raise ValueError("Equity output extends beyond DEVELOPMENT")
    if rolling["session_date"].max() > end:
        raise ValueError("Rolling output extends beyond DEVELOPMENT")

    checks = validate_development_diagnostics(
        trades,
        summary,
        monthly,
        equity,
        rolling,
        distribution,
        month_statistics,
        start,
        end,
    )
    paths = write_development_outputs(
        summary,
        monthly,
        equity,
        rolling,
        distribution,
        month_statistics,
        OUTPUT_DIR,
    )
    write_development_visualizations(trades, equity, monthly, rolling, paths)

    disagreements = summary.loc[~summary["crosscheck_passed"]]
    print(
        f"DEVELOPMENT ONLY: {start.date()} through {end.date()} | "
        f"{len(trades):,} executed trades"
    )
    print(f"Maximum analyzed session_date: {trades['session_date'].max().date()}")
    print(
        summary[
            [
                "variant",
                "executed_trades",
                "wins",
                "losses",
                "total_r",
                "average_r",
                "max_drawdown_r",
                "crosscheck_passed",
            ]
        ].to_string(index=False)
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    print(f"Development-only reconciliation: {checks}")
    if not disagreements.empty:
        print("Development-only cross-check disagreements:")
        print(disagreements.to_string(index=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
