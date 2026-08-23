"""Gate 5B diagnostics restricted to the configured DEVELOPMENT partition.

Reserved-period rows are discarded immediately while reading the completed-
trade CSV.  All calculations and plots receive DEVELOPMENT rows only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.experiments.orb_v01_baseline import (
    REQUIRED_COLUMNS,
    VARIANTS,
    variant_name,
)


ROLLING_COLUMNS = [
    "research_scope",
    "session_date",
    "trade_id",
    "trade_number",
    "or_minutes",
    "breakout_type",
    "variant",
    "direction",
    "result_r",
    "rolling_50_trade_count",
    "rolling_50_avg_r",
    "rolling_100_trade_count",
    "rolling_100_avg_r",
]

DISTRIBUTION_COLUMNS = [
    "research_scope",
    "or_minutes",
    "breakout_type",
    "variant",
    "count",
    "mean_r",
    "median_r",
    "std_r",
    "min_r",
    "max_r",
    "p10_r",
    "p25_r",
    "p75_r",
    "p90_r",
    "minus_1r_count",
    "plus_2r_count",
    "session_end_exits",
    "zero_r_count",
]

MONTH_STATISTICS_COLUMNS = [
    "research_scope",
    "or_minutes",
    "breakout_type",
    "variant",
    "months",
    "positive_months",
    "negative_months",
    "flat_months",
    "percentage_positive_months",
    "best_month_r",
    "worst_month_r",
    "average_monthly_r",
    "median_monthly_r",
]


def development_bounds(config: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp]:
    matches = [
        item
        for item in config["partitions"]
        if str(item["name"]).upper() == "DEVELOPMENT"
    ]
    if len(matches) != 1:
        raise ValueError("Partition config must define exactly one DEVELOPMENT range")
    start = pd.Timestamp(matches[0]["start"]).normalize()
    end = pd.Timestamp(matches[0]["end"]).normalize()
    return start, end


def load_development_trades(
    completed_trades_path: str | Path,
    config: dict[str, Any],
    *,
    chunksize: int = 50_000,
) -> pd.DataFrame:
    """Load only DEVELOPMENT trades and validate the selected records.

    Each CSV chunk is filtered using raw ``session_date`` before result fields
    are converted or analyzed.  Validation and OOS rows are never passed to an
    analytics function.
    """
    start, end = development_bounds(config)
    selected_chunks: list[pd.DataFrame] = []
    observed_columns: set[str] | None = None
    for chunk in pd.read_csv(completed_trades_path, chunksize=chunksize):
        if observed_columns is None:
            observed_columns = set(chunk.columns)
            missing = REQUIRED_COLUMNS.difference(observed_columns)
            if missing:
                raise ValueError(
                    "Completed trades are missing required columns: "
                    + ", ".join(sorted(missing))
                )
        session_dates = pd.to_datetime(chunk["session_date"], errors="raise")
        in_development = session_dates.between(start, end, inclusive="both")
        if in_development.any():
            selected_chunks.append(chunk.loc[in_development].copy())

    if not selected_chunks:
        raise ValueError("No completed trades fall inside DEVELOPMENT")
    trades = pd.concat(selected_chunks, ignore_index=True)
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

    if not trades["session_date"].between(start, end, inclusive="both").all():
        raise ValueError("A reserved-period row entered DEVELOPMENT analytics")
    if trades["trade_id"].duplicated().any():
        raise ValueError("DEVELOPMENT trades contain duplicate trade_id values")
    if trades.duplicated(
        ["session_date", "or_minutes", "breakout_type"]
    ).any():
        raise ValueError("DEVELOPMENT violates one trade per session/variant")
    if trades["result_r"].isna().any():
        raise ValueError("DEVELOPMENT contains missing result_r")
    if trades["ambiguous"].any() or trades["excluded_from_performance"].any():
        raise ValueError("DEVELOPMENT contains ambiguous/excluded rows")
    observed_variants = set(
        trades[["or_minutes", "breakout_type"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    if observed_variants != set(VARIANTS):
        raise ValueError(
            "DEVELOPMENT does not contain all eight ORB V0.1 variants"
        )
    return _sort_trades(trades)


def add_development_scope(
    frame: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    scoped = frame.copy()
    scoped.insert(0, "research_scope", "DEVELOPMENT_ONLY")
    scoped.insert(1, "development_start", start.date().isoformat())
    scoped.insert(2, "development_end", end.date().isoformat())
    return scoped


def calculate_rolling_expectancy(trades: pd.DataFrame) -> pd.DataFrame:
    """Calculate 50- and 100-trade rolling averages per variant."""
    frames: list[pd.DataFrame] = []
    for or_minutes, breakout_type in VARIANTS:
        group = _variant_trades(trades, or_minutes, breakout_type)
        result_r = group["result_r"].astype(float)
        rolling_50_count = result_r.rolling(window=50, min_periods=1).count()
        rolling_100_count = result_r.rolling(window=100, min_periods=1).count()
        rolling = pd.DataFrame(
            {
                "research_scope": "DEVELOPMENT_ONLY",
                "session_date": group["session_date"],
                "trade_id": group["trade_id"],
                "trade_number": np.arange(1, len(group) + 1),
                "or_minutes": or_minutes,
                "breakout_type": breakout_type,
                "variant": variant_name(or_minutes, breakout_type),
                "direction": group["direction"],
                "result_r": result_r,
                "rolling_50_trade_count": rolling_50_count,
                "rolling_50_avg_r": result_r.rolling(
                    window=50, min_periods=50
                ).mean(),
                "rolling_100_trade_count": rolling_100_count,
                "rolling_100_avg_r": result_r.rolling(
                    window=100, min_periods=100
                ).mean(),
            }
        )
        frames.append(rolling)
    return pd.concat(frames, ignore_index=True)[ROLLING_COLUMNS]


def calculate_r_distribution(
    trades: pd.DataFrame,
    *,
    nominal_tolerance: float = 1e-9,
) -> pd.DataFrame:
    """Describe DEVELOPMENT trade outcomes without changing their values."""
    rows: list[dict[str, Any]] = []
    for or_minutes, breakout_type in VARIANTS:
        group = _variant_trades(trades, or_minutes, breakout_type)
        result_r = group["result_r"].astype(float)
        rows.append(
            {
                "research_scope": "DEVELOPMENT_ONLY",
                "or_minutes": or_minutes,
                "breakout_type": breakout_type,
                "variant": variant_name(or_minutes, breakout_type),
                "count": int(len(result_r)),
                "mean_r": float(result_r.mean()),
                "median_r": float(result_r.median()),
                "std_r": float(result_r.std(ddof=1)),
                "min_r": float(result_r.min()),
                "max_r": float(result_r.max()),
                "p10_r": float(result_r.quantile(0.10)),
                "p25_r": float(result_r.quantile(0.25)),
                "p75_r": float(result_r.quantile(0.75)),
                "p90_r": float(result_r.quantile(0.90)),
                "minus_1r_count": int(
                    np.isclose(
                        result_r.to_numpy(),
                        -1.0,
                        rtol=0.0,
                        atol=nominal_tolerance,
                    ).sum()
                ),
                "plus_2r_count": int(
                    np.isclose(
                        result_r.to_numpy(),
                        2.0,
                        rtol=0.0,
                        atol=nominal_tolerance,
                    ).sum()
                ),
                "session_end_exits": int(
                    group["exit_reason"].eq("SESSION_END").sum()
                ),
                "zero_r_count": int(
                    np.isclose(
                        result_r.to_numpy(),
                        0.0,
                        rtol=0.0,
                        atol=nominal_tolerance,
                    ).sum()
                ),
            }
        )
    return pd.DataFrame(rows, columns=DISTRIBUTION_COLUMNS)


def calculate_month_statistics(
    monthly: pd.DataFrame,
    *,
    flat_tolerance: float = 1e-12,
) -> pd.DataFrame:
    """Summarize positive, negative, and flat DEVELOPMENT months."""
    rows: list[dict[str, Any]] = []
    for or_minutes, breakout_type in VARIANTS:
        variant = variant_name(or_minutes, breakout_type)
        result_r = monthly.loc[monthly["variant"].eq(variant), "total_r"].astype(
            float
        )
        positive = result_r > flat_tolerance
        negative = result_r < -flat_tolerance
        flat = ~(positive | negative)
        rows.append(
            {
                "research_scope": "DEVELOPMENT_ONLY",
                "or_minutes": or_minutes,
                "breakout_type": breakout_type,
                "variant": variant,
                "months": int(len(result_r)),
                "positive_months": int(positive.sum()),
                "negative_months": int(negative.sum()),
                "flat_months": int(flat.sum()),
                "percentage_positive_months": float(positive.mean()),
                "best_month_r": float(result_r.max()),
                "worst_month_r": float(result_r.min()),
                "average_monthly_r": float(result_r.mean()),
                "median_monthly_r": float(result_r.median()),
            }
        )
    return pd.DataFrame(rows, columns=MONTH_STATISTICS_COLUMNS)


def development_output_paths(output_dir: str | Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    return {
        "summary": output_dir / "orb_v01_DEV_summary.csv",
        "monthly": output_dir / "orb_v01_DEV_monthly.csv",
        "month_statistics": output_dir / "orb_v01_DEV_month_statistics.csv",
        "equity_data": output_dir / "orb_v01_DEV_equity_curves.csv",
        "equity_chart": output_dir / "orb_v01_DEV_equity_curves.html",
        "monthly_chart": output_dir / "orb_v01_DEV_monthly.html",
        "rolling_data": output_dir / "orb_v01_DEV_rolling_expectancy.csv",
        "rolling_chart": output_dir / "orb_v01_DEV_rolling_expectancy.html",
        "distribution_data": output_dir / "orb_v01_DEV_r_distribution.csv",
        "distribution_chart": output_dir / "orb_v01_DEV_r_distribution.html",
    }


def write_development_outputs(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    equity: pd.DataFrame,
    rolling: pd.DataFrame,
    distribution: pd.DataFrame,
    month_statistics: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Path]:
    paths = development_output_paths(output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    summary.to_csv(paths["summary"], index=False)
    monthly.to_csv(paths["monthly"], index=False)
    month_statistics.to_csv(paths["month_statistics"], index=False)
    equity.to_csv(paths["equity_data"])
    rolling.to_csv(paths["rolling_data"], index=False)
    distribution.to_csv(paths["distribution_data"], index=False)
    return paths


def write_development_visualizations(
    trades: pd.DataFrame,
    equity: pd.DataFrame,
    monthly: pd.DataFrame,
    rolling: pd.DataFrame,
    paths: dict[str, Path],
) -> None:
    """Write four interactive charts, all explicitly DEVELOPMENT-only."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import vectorbt  # noqa: F401  # registers pandas ``.vbt`` accessors

    equity_figure = equity.vbt.lineplot()
    _apply_layout(
        equity_figure,
        "ORB V0.1 cumulative R by variant — DEVELOPMENT ONLY",
        "Session date",
        "Cumulative R",
    )
    _write_html(equity_figure, paths["equity_chart"], height=650)

    monthly_pivot = monthly.pivot(
        index="month", columns="variant", values="total_r"
    ).reindex(columns=[variant_name(*variant) for variant in VARIANTS])
    monthly_figure = monthly_pivot.vbt.barplot()
    _apply_layout(
        monthly_figure,
        "ORB V0.1 monthly R by variant — DEVELOPMENT ONLY",
        "Month",
        "Total R",
        barmode="group",
    )
    _write_html(monthly_figure, paths["monthly_chart"], height=650)

    colors = [
        "#636EFA",
        "#EF553B",
        "#00CC96",
        "#AB63FA",
        "#FFA15A",
        "#19D3F3",
        "#FF6692",
        "#B6E880",
    ]
    rolling_figure = go.Figure()
    for index, (or_minutes, breakout_type) in enumerate(VARIANTS):
        name = variant_name(or_minutes, breakout_type)
        subset = rolling.loc[rolling["variant"].eq(name)]
        common = {
            "x": subset["session_date"],
            "legendgroup": name,
            "line": {"color": colors[index]},
            "connectgaps": False,
        }
        rolling_figure.add_trace(
            go.Scatter(
                y=subset["rolling_50_avg_r"],
                name=name,
                mode="lines",
                **common,
            )
        )
        rolling_figure.add_trace(
            go.Scatter(
                y=subset["rolling_100_avg_r"],
                name=name,
                mode="lines",
                showlegend=False,
                **{**common, "line": {"color": colors[index], "dash": "dot"}},
            )
        )
    rolling_figure.add_hline(
        y=0.0,
        line_dash="dash",
        line_color="#444",
        annotation_text="Zero expectancy",
        annotation_position="bottom right",
    )
    _apply_layout(
        rolling_figure,
        "ORB V0.1 rolling expectancy — DEVELOPMENT ONLY"
        "<br><sup>Solid = 50 trades; dotted = 100 trades. "
        "Click a variant to toggle both.</sup>",
        "Session date",
        "Average R",
    )
    rolling_figure.update_layout(legend={"groupclick": "togglegroup"})
    _write_html(rolling_figure, paths["rolling_chart"], height=700)

    distribution_figure = make_subplots(
        rows=4,
        cols=2,
        subplot_titles=[variant_name(*variant) for variant in VARIANTS],
        vertical_spacing=0.08,
    )
    for index, (or_minutes, breakout_type) in enumerate(VARIANTS):
        row = index // 2 + 1
        column = index % 2 + 1
        result_r = _variant_trades(
            trades, or_minutes, breakout_type
        )["result_r"].astype(float)
        distribution_figure.add_trace(
            go.Histogram(
                x=result_r,
                nbinsx=30,
                name=variant_name(or_minutes, breakout_type),
                marker_color=colors[index],
                showlegend=False,
                hovertemplate="R=%{x}<br>Trades=%{y}<extra></extra>",
            ),
            row=row,
            col=column,
        )
    distribution_figure.update_xaxes(title_text="Result R")
    distribution_figure.update_yaxes(title_text="Trades")
    distribution_figure.update_layout(
        title="ORB V0.1 trade R distributions — DEVELOPMENT ONLY",
        template="plotly_white",
        height=1050,
        width=None,
        autosize=True,
        bargap=0.05,
        margin={"l": 70, "r": 50, "t": 100, "b": 70},
    )
    _write_html(
        distribution_figure, paths["distribution_chart"], height=1050
    )


def assert_development_only(
    trades: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    if trades.empty or not trades["session_date"].between(
        start, end, inclusive="both"
    ).all():
        raise ValueError("Gate 5B analytics contain rows outside DEVELOPMENT")


def validate_development_diagnostics(
    trades: pd.DataFrame,
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    equity: pd.DataFrame,
    rolling: pd.DataFrame,
    distribution: pd.DataFrame,
    month_statistics: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, bool]:
    """Reconcile every Gate 5B output back to DEVELOPMENT completed trades."""
    checks: dict[str, bool] = {
        "every_trade_is_development": bool(
            trades["session_date"].between(start, end, inclusive="both").all()
        ),
        "maximum_session_date_within_development": bool(
            trades["session_date"].max() <= end
        ),
        "rolling_50_windows_have_50_trades": bool(
            rolling.loc[
                rolling["rolling_50_avg_r"].notna(),
                "rolling_50_trade_count",
            ].eq(50).all()
        ),
        "rolling_100_windows_have_100_trades": bool(
            rolling.loc[
                rolling["rolling_100_avg_r"].notna(),
                "rolling_100_trade_count",
            ].eq(100).all()
        ),
    }
    counts_match = True
    monthly_match = True
    distribution_match = True
    ending_equity_match = True
    month_classification_match = True
    for row in summary.itertuples(index=False):
        variant = str(row.variant)
        variant_trades = trades.loc[
            trades["or_minutes"].eq(int(row.or_minutes))
            & trades["breakout_type"].eq(str(row.breakout_type))
        ]
        counts_match = counts_match and len(variant_trades) == int(
            row.executed_trades
        )
        variant_monthly = monthly.loc[monthly["variant"].eq(variant)]
        monthly_match = monthly_match and bool(
            np.isclose(
                variant_monthly["total_r"].sum(),
                float(row.total_r),
                rtol=0.0,
                atol=1e-12,
            )
        )
        distribution_row = distribution.loc[
            distribution["variant"].eq(variant)
        ].iloc[0]
        distribution_match = distribution_match and bool(
            np.isclose(
                float(distribution_row["mean_r"]),
                float(row.average_r),
                rtol=0.0,
                atol=1e-12,
            )
            and np.isclose(
                float(distribution_row["median_r"]),
                float(row.median_r),
                rtol=0.0,
                atol=1e-12,
            )
        )
        ending_equity_match = ending_equity_match and bool(
            np.isclose(
                float(equity[variant].iloc[-1]),
                float(row.total_r),
                rtol=0.0,
                atol=1e-12,
            )
        )
        month_row = month_statistics.loc[
            month_statistics["variant"].eq(variant)
        ].iloc[0]
        month_classification_match = month_classification_match and (
            int(month_row["positive_months"])
            + int(month_row["negative_months"])
            + int(month_row["flat_months"])
            == int(month_row["months"])
            == len(variant_monthly)
        )
    checks.update(
        {
            "trade_counts_reconcile": counts_match,
            "monthly_totals_equal_total_r": monthly_match,
            "distribution_mean_median_match_summary": distribution_match,
            "ending_equity_equals_total_r": ending_equity_match,
            "month_classifications_reconcile": month_classification_match,
        }
    )
    if not all(checks.values()):
        raise ValueError(f"Gate 5B diagnostic reconciliation failed: {checks}")
    return checks


def _variant_trades(
    trades: pd.DataFrame, or_minutes: int, breakout_type: str
) -> pd.DataFrame:
    return _sort_trades(
        trades.loc[
            trades["or_minutes"].eq(or_minutes)
            & trades["breakout_type"].eq(breakout_type)
        ]
    )


def _sort_trades(trades: pd.DataFrame) -> pd.DataFrame:
    return trades.sort_values(
        ["entry_time", "signal_time", "trade_id"], kind="stable"
    ).reset_index(drop=True)


def _apply_layout(figure, title: str, x_title: str, y_title: str, **kwargs) -> None:
    figure.update_layout(
        title=title,
        xaxis_title=x_title,
        yaxis_title=y_title,
        template="plotly_white",
        hovermode="x unified",
        width=None,
        height=650,
        autosize=True,
        legend={"orientation": "v", "x": 1.02, "y": 1.0},
        margin={"l": 70, "r": 190, "t": 90, "b": 70},
        **kwargs,
    )


def _write_html(figure, path: str | Path, *, height: int) -> None:
    figure.write_html(
        path,
        include_plotlyjs="cdn",
        config={"responsive": True},
        default_width="100%",
        default_height=f"{height}px",
    )


def _to_boolean(values: pd.Series, column: str) -> pd.Series:
    if values.dtype == bool:
        return values
    mapped = values.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise ValueError(f"Column {column} contains non-boolean values")
    return mapped.astype(bool)
