"""Generate the first analytics cross-check for validated ORB V0.1 trades.

Educational workflow
--------------------
1. Load the canonical Gate 4D completed-trade table.  Nothing upstream is run.
2. Calculate all requested statistics directly from ``result_r`` with pandas.
3. Ask VectorBT''s generic accessors to calculate the same core aggregations and
   cumulative series.  No Portfolio or generic signal model is constructed.
4. Save readable CSV tables and VectorBT-powered interactive HTML charts.
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.orb_v01_baseline import (  # noqa: E402
    build_equity_curves,
    calculate_independent_summary,
    calculate_monthly_summary,
    load_completed_trades,
    merge_crosscheck,
    vectorbt_crosscheck,
    write_baseline_outputs,
    write_vectorbt_visualizations,
)


COMPLETED_TRADES_FILE = (
    PROJECT_ROOT / "data" / "processed" / "orb_v01_completed_trades.csv"
)
OUTPUT_DIR = (
    PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "baselines"
)


def main() -> int:
    import vectorbt as vbt

    trades = load_completed_trades(COMPLETED_TRADES_FILE)

    # These are the canonical statistics: direct calculations from result_r.
    independent = calculate_independent_summary(trades)
    monthly = calculate_monthly_summary(trades)
    equity = build_equity_curves(trades)

    # VectorBT is deliberately limited to generic numeric-series operations.
    crosscheck = vectorbt_crosscheck(
        trades, independent, vbt_module=vbt
    )
    summary = merge_crosscheck(independent, crosscheck)
    paths = write_baseline_outputs(summary, monthly, equity, OUTPUT_DIR)
    write_vectorbt_visualizations(
        equity,
        monthly,
        paths["equity_chart"],
        paths["monthly_chart"],
    )

    disagreements = summary.loc[~summary["crosscheck_passed"]]
    print(f"VectorBT version: {vbt.__version__}")
    print(f"Canonical completed trades: {len(trades):,}")
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
    if not disagreements.empty:
        print("VectorBT cross-check disagreements:")
        print(disagreements.to_string(index=False))
        return 1
    print("VectorBT cross-check: exact agreement within 1e-12 tolerance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
