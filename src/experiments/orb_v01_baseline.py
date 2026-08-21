"""Baseline analytics for the canonical ORB V0.1 completed-trade table.

The completed-trade CSV is the source of truth.  This module never rebuilds
signals, entries, stops, targets, or exits.  Canonical statistics are computed
with pandas; VectorBT is loaded only for an independent aggregation/drawdown
cross-check and for plotting the already-validated R series.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


VARIANTS = tuple(
    (or_minutes, breakout_type)
    for or_minutes in (5, 10, 15, 30)
    for breakout_type in ("PRINT", "CLOSE")
)

REQUIRED_COLUMNS = {
    "trade_id",
    "session_date",
    "contract",
    "or_minutes",
    "breakout_type",
    "direction",
    "signal_time",
    "entry_time",
    "exit_time",
    "exit_reason",
    "result_r",
    "holding_minutes",
    "ambiguous",
    "excluded_from_performance",
}

SUMMARY_COLUMNS = [
    "or_minutes",
    "breakout_type",
    "variant",
    "executed_trades",
    "wins",
    "losses",
    "flat_trades",
    "session_end_exits",
    "win_rate",
    "average_r",
    "median_r",
    "total_r",
    "profit_factor_r",
    "max_drawdown_r",
    "max_consecutive_losses",
    "average_holding_minutes",
    "long_trade_count",
    "long_average_r",
    "long_total_r",
    "short_trade_count",
    "short_average_r",
    "short_total_r",
]

MONTHLY_COLUMNS = [
    "or_minutes",
    "breakout_type",
    "variant",
    "month",
    "trades",
    "total_r",
    "average_r",
    "win_rate",
]


def variant_name(or_minutes: int, breakout_type: str) -> str:
    return f"{int(or_minutes)}m {str(breakout_type).upper()}"


def load_completed_trades(path: str | Path) -> pd.DataFrame:
    """Load and validate the canonical Gate 4D completed-trade dataset."""
    trades = pd.read_csv(path)
    missing = REQUIRED_COLUMNS.difference(trades.columns)
    if missing:
        raise ValueError(
            "Completed trades are missing required columns: "
            + ", ".join(sorted(missing))
        )

    trades = trades.copy()
    trades["session_date"] = pd.to_datetime(
        trades["session_date"], errors="raise"
    ).dt.normalize()
    for column in ("signal_time", "entry_time", "exit_time"):
        trades[column] = pd.to_datetime(
            trades[column], errors="raise", utc=True
        ).dt.tz_convert("America/New_York")

    trades["or_minutes"] = pd.to_numeric(
        trades["or_minutes"], errors="raise"
    ).astype(int)
    trades["breakout_type"] = trades["breakout_type"].str.upper()
    trades["direction"] = trades["direction"].str.upper()
    trades["result_r"] = pd.to_numeric(trades["result_r"], errors="raise")
    trades["holding_minutes"] = pd.to_numeric(
        trades["holding_minutes"], errors="raise"
    )
    trades["ambiguous"] = _to_boolean(trades["ambiguous"], "ambiguous")
    trades["excluded_from_performance"] = _to_boolean(
        trades["excluded_from_performance"], "excluded_from_performance"
    )

    if trades["trade_id"].duplicated().any():
        raise ValueError("Completed trades contain duplicate trade_id values")
    variant_session = ["session_date", "or_minutes", "breakout_type"]
    if trades.duplicated(variant_session).any():
        raise ValueError(
            "Completed trades violate the one-trade-per-session/variant rule"
        )
    if trades["result_r"].isna().any():
        raise ValueError("Canonical completed trades contain missing result_r")
    if trades["ambiguous"].any() or trades["excluded_from_performance"].any():
        raise ValueError(
            "Canonical completed trades must not contain ambiguous/excluded rows"
        )

    observed = set(
        trades[["or_minutes", "breakout_type"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    expected = set(VARIANTS)
    if observed != expected:
        missing_variants = sorted(expected.difference(observed))
        unexpected = sorted(observed.difference(expected))
        raise ValueError(
            f"Baseline variants differ from ORB V0.1; missing={missing_variants}, "
            f"unexpected={unexpected}"
        )
    return _sort_trades(trades)


def calculate_independent_summary(trades: pd.DataFrame) -> pd.DataFrame:
    """Calculate canonical trade statistics directly with pandas."""
    rows: list[dict[str, Any]] = []
    for or_minutes, breakout_type in _observed_variants(trades):
        group = _variant_trades(trades, or_minutes, breakout_type)
        result_r = group["result_r"].astype(float)
        positive = result_r[result_r > 0.0]
        negative = result_r[result_r < 0.0]
        gross_profit = float(positive.sum())
        gross_loss = abs(float(negative.sum()))
        long_r = result_r.loc[group["direction"].eq("LONG")]
        short_r = result_r.loc[group["direction"].eq("SHORT")]

        rows.append(
            {
                "or_minutes": or_minutes,
                "breakout_type": breakout_type,
                "variant": variant_name(or_minutes, breakout_type),
                "executed_trades": int(len(group)),
                "wins": int((result_r > 0.0).sum()),
                "losses": int((result_r < 0.0).sum()),
                "flat_trades": int((result_r == 0.0).sum()),
                "session_end_exits": int(
                    group["exit_reason"].eq("SESSION_END").sum()
                ),
                "win_rate": float((result_r > 0.0).mean()),
                "average_r": float(result_r.mean()),
                "median_r": float(result_r.median()),
                "total_r": float(result_r.sum()),
                "profit_factor_r": (
                    gross_profit / gross_loss if gross_loss else np.inf
                ),
                "max_drawdown_r": calculate_max_drawdown_r(result_r),
                "max_consecutive_losses": max_consecutive_losses(result_r),
                "average_holding_minutes": float(
                    group["holding_minutes"].mean()
                ),
                "long_trade_count": int(len(long_r)),
                "long_average_r": _mean_or_nan(long_r),
                "long_total_r": float(long_r.sum()),
                "short_trade_count": int(len(short_r)),
                "short_average_r": _mean_or_nan(short_r),
                "short_total_r": float(short_r.sum()),
            }
        )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def calculate_monthly_summary(trades: pd.DataFrame) -> pd.DataFrame:
    """Aggregate each variant by session month, using session_date as authority."""
    working = trades.copy()
    working["month"] = working["session_date"].dt.to_period("M").astype(str)
    rows: list[dict[str, Any]] = []
    for (or_minutes, breakout_type, month), group in working.groupby(
        ["or_minutes", "breakout_type", "month"], sort=False
    ):
        result_r = group["result_r"].astype(float)
        rows.append(
            {
                "or_minutes": int(or_minutes),
                "breakout_type": str(breakout_type),
                "variant": variant_name(or_minutes, breakout_type),
                "month": month,
                "trades": int(len(group)),
                "total_r": float(result_r.sum()),
                "average_r": float(result_r.mean()),
                "win_rate": float((result_r > 0.0).mean()),
            }
        )
    monthly = pd.DataFrame(rows, columns=MONTHLY_COLUMNS)
    monthly["_variant_order"] = monthly.apply(
        lambda row: VARIANTS.index(
            (int(row["or_minutes"]), str(row["breakout_type"]))
        ),
        axis=1,
    )
    return (
        monthly.sort_values(["month", "_variant_order"], kind="stable")
        .drop(columns="_variant_order")
        .reset_index(drop=True)
    )


def build_equity_curves(trades: pd.DataFrame) -> pd.DataFrame:
    """Return date-aligned cumulative-R curves with an explicit zero origin."""
    curves: list[pd.Series] = []
    for or_minutes, breakout_type in _observed_variants(trades):
        group = _variant_trades(trades, or_minutes, breakout_type)
        curve = group.set_index("session_date")["result_r"].astype(float).cumsum()
        curve.name = variant_name(or_minutes, breakout_type)
        curves.append(curve)
    equity = pd.concat(curves, axis=1).sort_index().ffill().fillna(0.0)
    zero_date = equity.index.min() - pd.Timedelta(days=1)
    zero = pd.DataFrame(0.0, index=[zero_date], columns=equity.columns)
    equity = pd.concat([zero, equity]).sort_index()
    equity.index.name = "session_date"
    return equity


def vectorbt_crosscheck(
    trades: pd.DataFrame,
    independent: pd.DataFrame,
    *,
    vbt_module=None,
) -> pd.DataFrame:
    """Cross-check core pandas results with VectorBT generic accessors.

    No ``Portfolio`` is built.  R is not a percentage return and is therefore
    intentionally handled as a generic numeric series.
    """
    if vbt_module is None:
        import vectorbt as vbt_module  # type: ignore[import-not-found]

    rows: list[dict[str, Any]] = []
    for independent_row in independent.itertuples(index=False):
        group = _variant_trades(
            trades,
            int(independent_row.or_minutes),
            str(independent_row.breakout_type),
        )
        result_r = group["result_r"].astype(float).reset_index(drop=True)
        vbt_cumulative = result_r.vbt.cumsum()
        pandas_cumulative = result_r.cumsum()
        vbt_drawdown = _vectorbt_absolute_drawdown(
            vbt_cumulative, vbt_module
        )

        values = {
            "or_minutes": int(independent_row.or_minutes),
            "breakout_type": str(independent_row.breakout_type),
            "vectorbt_trade_count": int(result_r.vbt.count()),
            "vectorbt_total_r": float(result_r.vbt.sum()),
            "vectorbt_average_r": float(result_r.vbt.mean()),
            "vectorbt_median_r": float(result_r.vbt.median()),
            "vectorbt_wins": int((result_r > 0.0).astype(int).vbt.sum()),
            "vectorbt_losses": int((result_r < 0.0).astype(int).vbt.sum()),
            "vectorbt_max_drawdown_r": vbt_drawdown,
            "vectorbt_cumulative_r_matches": bool(
                np.allclose(
                    vbt_cumulative.to_numpy(),
                    pandas_cumulative.to_numpy(),
                    rtol=0.0,
                    atol=1e-12,
                )
            ),
        }
        values["crosscheck_passed"] = bool(
            values["vectorbt_trade_count"] == independent_row.executed_trades
            and values["vectorbt_wins"] == independent_row.wins
            and values["vectorbt_losses"] == independent_row.losses
            and _close(values["vectorbt_total_r"], independent_row.total_r)
            and _close(values["vectorbt_average_r"], independent_row.average_r)
            and _close(values["vectorbt_median_r"], independent_row.median_r)
            and _close(
                values["vectorbt_max_drawdown_r"],
                independent_row.max_drawdown_r,
            )
            and values["vectorbt_cumulative_r_matches"]
        )
        rows.append(values)
    return pd.DataFrame(rows)


def merge_crosscheck(
    independent: pd.DataFrame, crosscheck: pd.DataFrame
) -> pd.DataFrame:
    return independent.merge(
        crosscheck,
        on=["or_minutes", "breakout_type"],
        how="left",
        validate="one_to_one",
    )


def write_baseline_outputs(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    equity: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary": output_dir / "orb_v01_summary.csv",
        "monthly": output_dir / "orb_v01_monthly.csv",
        "equity_data": output_dir / "orb_v01_equity_curves.csv",
        "equity_chart": output_dir / "orb_v01_equity_curves.html",
        "monthly_chart": output_dir / "orb_v01_monthly_r.html",
    }
    summary.to_csv(paths["summary"], index=False)
    monthly.to_csv(paths["monthly"], index=False)
    equity.to_csv(paths["equity_data"])
    return paths


def write_vectorbt_visualizations(
    equity: pd.DataFrame,
    monthly: pd.DataFrame,
    equity_path: str | Path,
    monthly_path: str | Path,
) -> None:
    """Render interactive HTML using VectorBT''s generic plotting accessors."""
    import vectorbt  # noqa: F401  # registers the pandas ``.vbt`` accessor

    equity_figure = equity.vbt.lineplot()
    equity_figure.update_layout(
        title="ORB V0.1 cumulative R by variant",
        xaxis_title="Session date",
        yaxis_title="Cumulative R",
        hovermode="x unified",
        template="plotly_white",
        width=None,
        height=650,
        autosize=True,
        legend={"orientation": "v", "x": 1.02, "y": 1.0},
        margin={"l": 70, "r": 170, "t": 80, "b": 70},
    )
    equity_figure.write_html(
        equity_path,
        include_plotlyjs="cdn",
        config={"responsive": True},
        default_width="100%",
        default_height="650px",
    )

    monthly_pivot = monthly.pivot(
        index="month", columns="variant", values="total_r"
    )
    monthly_pivot = monthly_pivot.reindex(
        columns=[variant_name(*variant) for variant in VARIANTS]
    )
    monthly_figure = monthly_pivot.vbt.barplot()
    monthly_figure.update_layout(
        title="ORB V0.1 monthly R by variant",
        xaxis_title="Month",
        yaxis_title="Total R",
        barmode="group",
        template="plotly_white",
        width=None,
        height=650,
        autosize=True,
        legend={"orientation": "v", "x": 1.02, "y": 1.0},
        margin={"l": 70, "r": 170, "t": 80, "b": 70},
    )
    monthly_figure.write_html(
        monthly_path,
        include_plotlyjs="cdn",
        config={"responsive": True},
        default_width="100%",
        default_height="650px",
    )


def calculate_max_drawdown_r(result_r: pd.Series) -> float:
    equity = np.concatenate(([0.0], result_r.astype(float).cumsum().to_numpy()))
    running_peak = np.maximum.accumulate(equity)
    return float(np.max(running_peak - equity))


def max_consecutive_losses(result_r: pd.Series) -> int:
    longest = 0
    current = 0
    for is_loss in result_r.astype(float).lt(0.0):
        current = current + 1 if is_loss else 0
        longest = max(longest, current)
    return longest


def _vectorbt_absolute_drawdown(cumulative_r, vbt_module) -> float:
    equity = pd.Series(
        np.concatenate(([0.0], cumulative_r.to_numpy(dtype=float))),
        name="equity_R",
    )
    records = vbt_module.Drawdowns.from_ts(equity).records_readable
    if records.empty:
        return 0.0
    return float((records["Peak Value"] - records["Valley Value"]).max())


def _variant_trades(
    trades: pd.DataFrame, or_minutes: int, breakout_type: str
) -> pd.DataFrame:
    return _sort_trades(
        trades.loc[
            trades["or_minutes"].eq(or_minutes)
            & trades["breakout_type"].eq(breakout_type)
        ]
    )


def _observed_variants(trades: pd.DataFrame) -> list[tuple[int, str]]:
    observed = set(
        trades[["or_minutes", "breakout_type"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    return [variant for variant in VARIANTS if variant in observed]


def _sort_trades(trades: pd.DataFrame) -> pd.DataFrame:
    return trades.sort_values(
        ["entry_time", "signal_time", "trade_id"], kind="stable"
    ).reset_index(drop=True)


def _mean_or_nan(values: pd.Series) -> float:
    return float(values.mean()) if len(values) else np.nan


def _close(left: float, right: float) -> bool:
    return bool(np.isclose(left, right, rtol=0.0, atol=1e-12))


def _to_boolean(values: pd.Series, column: str) -> pd.Series:
    if values.dtype == bool:
        return values
    mapped = values.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise ValueError(f"Column {column} contains non-boolean values")
    return mapped.astype(bool)
