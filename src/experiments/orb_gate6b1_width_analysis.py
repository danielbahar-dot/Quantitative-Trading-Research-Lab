"""Gate 6B.1 DEVELOPMENT-only OR-width relationship diagnostics.

All inputs are immutable Gate 6B artifacts. No signal, candidate, or execution
function is imported or called. Market-state statistics deduplicate to one
session x OR-duration observation to avoid parameter-grid pseudo-replication.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


OR_DURATIONS = (15, 20, 30)
STOP_MODES = (
    "OR_MIDPOINT", "OR_25_RETRACEMENT", "FIXED_30", "FIXED_40", "FIXED_50"
)
TARGET_POINTS = (40.0, 50.0, 60.0, 75.0, 100.0)
QUINTILES = (1, 2, 3, 4, 5)
LOW_SAMPLE_THRESHOLD = 30
ENTRY_STOP = "AMBIGUOUS_ENTRY_STOP"
STOP_TARGET = "AMBIGUOUS_STOP_TARGET"


def load_gate6b_artifacts(
    summary_path: str | Path,
    trades_path: str | Path,
    candidate_audit_path: str | Path,
    diagnostics_path: str | Path,
    metadata_path: str | Path,
    *,
    development_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load and reconcile canonical Gate 6B outputs without reconstruction."""
    summary = pd.read_csv(summary_path)
    trades = pd.read_csv(trades_path)
    audit = pd.read_csv(candidate_audit_path)
    diagnostics = pd.read_csv(diagnostics_path)
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    required_summary = {
        "config_id", "or_minutes", "stop_mode", "target_points",
        "executed_trades", "average_r", "total_r",
    }
    required_trades = {
        "config_id", "session_date", "or_minutes", "stop_mode", "target_points",
        "or_high", "or_low", "or_width_points", "target_to_or_ratio",
        "stop_to_or_ratio", "initial_reward_risk", "result_r", "exit_reason",
        "holding_minutes", "initial_risk_points",
    }
    required_diagnostics = {
        "config_id", "session_date", "or_minutes", "stop_mode", "target_points",
        "direction", "signal_time", "or_high", "or_low", "or_width_points",
        "target_to_or_ratio", "stop_to_or_ratio", "initial_reward_risk",
        "gate4d_status", "rejection_reason", "exit_reason", "ambiguity_reason",
        "excluded_from_performance", "inclusion_exclusion_status",
    }
    for name, frame, required in (
        ("summary", summary, required_summary),
        ("trades", trades, required_trades),
        ("OR-width diagnostics", diagnostics, required_diagnostics),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Gate 6B {name} is missing: {sorted(missing)}")
    if len(summary) != 75 or summary["config_id"].duplicated().any():
        raise ValueError("Gate 6B summary is not the canonical 75-cell table")
    for frame in (trades, audit, diagnostics):
        frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise").dt.normalize()
        if not frame["session_date"].le(development_end).all():
            raise ValueError("A reserved-period row entered Gate 6B.1")
        for column in ("signal_time", "entry_time", "exit_time"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True).dt.tz_convert("America/New_York")
    diagnostics["excluded_from_performance"] = _to_boolean(
        diagnostics["excluded_from_performance"], "excluded_from_performance"
    )
    if not np.allclose(
        diagnostics["or_width_points"], diagnostics["or_high"] - diagnostics["or_low"],
        rtol=0, atol=1e-12,
    ):
        raise ValueError("Gate 6B OR width does not reconcile to high - low")
    if not np.allclose(
        diagnostics["target_to_or_ratio"],
        diagnostics["target_points"] / diagnostics["or_width_points"],
        rtol=0, atol=1e-12,
    ):
        raise ValueError("Gate 6B target/OR ratios do not reconcile")
    valid_risk = diagnostics["initial_risk_points"].notna()
    if not np.allclose(
        diagnostics.loc[valid_risk, "stop_to_or_ratio"],
        diagnostics.loc[valid_risk, "initial_risk_points"]
        / diagnostics.loc[valid_risk, "or_width_points"],
        rtol=0, atol=1e-12,
    ):
        raise ValueError("Gate 6B stop/OR ratios do not reconcile")
    _reconcile_trade_and_diagnostic_rows(trades, diagnostics)
    _reconcile_summary(summary, trades)
    if not metadata.get("gate6a_and_gate6a1_artifacts_unchanged"):
        raise ValueError("Gate 6B metadata lacks protected-artifact confirmation")
    return summary, trades, audit, diagnostics, metadata


def unique_width_observations(diagnostics: pd.DataFrame) -> pd.DataFrame:
    """Return one market-state observation per session and OR duration."""
    widths = diagnostics[["session_date", "or_minutes", "or_width_points"]].drop_duplicates()
    if widths.duplicated(["session_date", "or_minutes"]).any():
        raise ValueError("One session/duration has multiple OR-width values")
    return widths.sort_values(["or_minutes", "session_date"], kind="stable").reset_index(drop=True)


def assign_duration_bins(
    widths: pd.DataFrame, *, bins: int = 5, label_column: str = "or_width_quintile"
) -> pd.DataFrame:
    """Assign deterministic equal-count bins independently by duration.

    Width ties are ordered by session date and may span adjacent bins. This is
    deterministic, keeps bins approximately equal, and avoids dropping rows.
    """
    frames = []
    for duration, group in widths.groupby("or_minutes", sort=True):
        ordered = group.sort_values(["or_width_points", "session_date"], kind="stable").reset_index(drop=True)
        ordinal = pd.Series(np.arange(len(ordered)), index=ordered.index)
        ordered[label_column] = pd.qcut(
            ordinal, q=bins, labels=list(range(1, bins + 1))
        ).astype(int)
        frames.append(ordered)
    return pd.concat(frames, ignore_index=True)


def calculate_width_distribution(
    widths: pd.DataFrame, diagnostics: pd.DataFrame
) -> pd.DataFrame:
    base_candidates = diagnostics.drop_duplicates(
        ["session_date", "or_minutes", "direction", "signal_time"]
    )
    rows = []
    for duration in OR_DURATIONS:
        values = widths.loc[widths["or_minutes"].eq(duration), "or_width_points"].astype(float)
        rows.append({
            "research_scope": "DEVELOPMENT_ONLY", "or_minutes": duration,
            "unique_session_count": len(values),
            "unique_candidate_count": int(base_candidates["or_minutes"].eq(duration).sum()),
            "mean_or_width": float(values.mean()), "median_or_width": float(values.median()),
            "std_or_width": float(values.std(ddof=1)), "min_or_width": float(values.min()),
            "max_or_width": float(values.max()), "p10_or_width": float(values.quantile(0.10)),
            "p25_or_width": float(values.quantile(0.25)), "p50_or_width": float(values.quantile(0.50)),
            "p75_or_width": float(values.quantile(0.75)), "p90_or_width": float(values.quantile(0.90)),
        })
    return pd.DataFrame(rows)


def calculate_quintile_boundaries(
    assigned_widths: pd.DataFrame, diagnostics: pd.DataFrame
) -> pd.DataFrame:
    base_candidates = diagnostics.drop_duplicates(
        ["session_date", "or_minutes", "direction", "signal_time"]
    ).copy()
    if "or_width_quintile" not in base_candidates:
        base_candidates = base_candidates.merge(
            assigned_widths[["session_date", "or_minutes", "or_width_quintile"]],
            on=["session_date", "or_minutes"], validate="many_to_one",
        )
    rows = []
    for (duration, quintile), group in assigned_widths.groupby(
        ["or_minutes", "or_width_quintile"], sort=True
    ):
        rows.append({
            "research_scope": "DEVELOPMENT_ONLY", "or_minutes": int(duration),
            "or_width_quintile": int(quintile),
            "lower_width_boundary": float(group["or_width_points"].min()),
            "upper_width_boundary": float(group["or_width_points"].max()),
            "median_width": float(group["or_width_points"].median()),
            "unique_session_count": int(group["session_date"].nunique()),
            "unique_candidate_count": int(
                len(base_candidates.loc[
                    base_candidates["or_minutes"].eq(duration)
                    & base_candidates["or_width_quintile"].eq(quintile)
                ])
            ),
            "tie_method": "stable ordinal rank after sorting width, then session_date",
        })
    return pd.DataFrame(rows)


def add_width_quintiles(
    frame: pd.DataFrame, assigned_widths: pd.DataFrame
) -> pd.DataFrame:
    return frame.merge(
        assigned_widths[["session_date", "or_minutes", "or_width_quintile"]],
        on=["session_date", "or_minutes"], how="left", validate="many_to_one",
    )


def calculate_conditional_performance(
    summary: pd.DataFrame,
    trades: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for config in summary.itertuples(index=False):
        candidates = diagnostics.loc[diagnostics["config_id"].eq(config.config_id)]
        config_trades = trades.loc[trades["config_id"].eq(config.config_id)]
        for quintile in QUINTILES:
            candidate_bin = candidates.loc[candidates["or_width_quintile"].eq(quintile)]
            trade_bin = config_trades.loc[config_trades["or_width_quintile"].eq(quintile)]
            result_r = trade_bin["result_r"].astype(float)
            positive, negative = result_r.loc[result_r.gt(0)], result_r.loc[result_r.lt(0)]
            gross_loss = abs(float(negative.sum()))
            execution_ambiguity = candidate_bin["excluded_from_performance"]
            rows.append({
                "research_scope": "DEVELOPMENT_ONLY", "config_id": config.config_id,
                "or_minutes": int(config.or_minutes), "stop_mode": config.stop_mode,
                "target_points": float(config.target_points), "or_width_quintile": quintile,
                "eligible_candidates": len(candidate_bin),
                "unique_sessions": int(candidate_bin["session_date"].nunique()),
                "executed_trades": len(trade_bin),
                "ambiguity_exclusion_count": int(execution_ambiguity.sum()),
                "ambiguity_exclusion_percentage": float(execution_ambiguity.mean() * 100),
                "session_trade_limit_count": int(
                    candidate_bin["rejection_reason"].eq("SESSION_TRADE_LIMIT").sum()
                ),
                "wins": int(result_r.gt(0).sum()), "losses": int(result_r.lt(0).sum()),
                "flat_trades": int(result_r.eq(0).sum()),
                "session_end_exits": int(trade_bin["exit_reason"].eq("SESSION_END").sum()),
                "win_rate": _mean_bool(result_r.gt(0)),
                "average_r": _mean(result_r), "median_r": _median(result_r),
                "total_r": float(result_r.sum()),
                "profit_factor_r": float(positive.sum()) / gross_loss if gross_loss else np.nan,
                "target_hit_percentage": _mean_bool(trade_bin["exit_reason"].eq("TARGET"), 100),
                "stop_hit_percentage": _mean_bool(trade_bin["exit_reason"].eq("STOP"), 100),
                "session_end_percentage": _mean_bool(trade_bin["exit_reason"].eq("SESSION_END"), 100),
                "average_holding_minutes": _mean(trade_bin["holding_minutes"]),
                "average_initial_risk_points": _mean(trade_bin["initial_risk_points"]),
                "average_initial_reward_risk": _mean(trade_bin["initial_reward_risk"]),
                "median_target_to_or_ratio": _median(trade_bin["target_to_or_ratio"]),
                "median_stop_to_or_ratio": _median(trade_bin["stop_to_or_ratio"]),
                "sample_warning": "LOW_SAMPLE" if len(trade_bin) < LOW_SAMPLE_THRESHOLD else "OK",
                "minimum_n_threshold": LOW_SAMPLE_THRESHOLD,
            })
    conditional = pd.DataFrame(rows)
    if len(conditional) != 75 * 5:
        raise ValueError("Conditional output must contain 375 configuration/quintile cells")
    _reconcile_conditional(summary, conditional)
    return conditional


def calculate_correlations(
    summary: pd.DataFrame, trades: pd.DataFrame
) -> pd.DataFrame:
    """Calculate descriptive Pearson and rank associations per configuration."""
    rows = []
    for config in summary.itertuples(index=False):
        group = trades.loc[trades["config_id"].eq(config.config_id)].copy()
        group["target_hit"] = group["exit_reason"].eq("TARGET").astype(float)
        group["stop_hit"] = group["exit_reason"].eq("STOP").astype(float)
        group["session_end_hit"] = group["exit_reason"].eq("SESSION_END").astype(float)
        row = {
            "research_scope": "DEVELOPMENT_ONLY", "config_id": config.config_id,
            "or_minutes": int(config.or_minutes), "stop_mode": config.stop_mode,
            "target_points": float(config.target_points), "executed_trades": len(group),
        }
        for outcome in (
            "result_r", "target_hit", "stop_hit", "session_end_hit", "holding_minutes"
        ):
            row[f"or_width_pearson_{outcome}"] = _correlation(
                group["or_width_points"], group[outcome], method="pearson"
            )
            row[f"or_width_spearman_{outcome}"] = _correlation(
                group["or_width_points"], group[outcome], method="spearman"
            )
        rows.append(row)
    return pd.DataFrame(rows)


def calculate_ambiguity_by_width(
    summary: pd.DataFrame, diagnostics: pd.DataFrame
) -> pd.DataFrame:
    """Keep target-specific candidate units to avoid pooling repeated rows."""
    rows = []
    for config in summary.itertuples(index=False):
        group = diagnostics.loc[diagnostics["config_id"].eq(config.config_id)]
        for quintile in QUINTILES:
            selected = group.loc[group["or_width_quintile"].eq(quintile)]
            entry = selected["exit_reason"].eq(ENTRY_STOP)
            stop_target = selected["exit_reason"].eq(STOP_TARGET)
            excluded = selected["excluded_from_performance"]
            other = excluded & ~entry & ~stop_target
            rows.append({
                "research_scope": "DEVELOPMENT_ONLY", "config_id": config.config_id,
                "or_minutes": int(config.or_minutes), "stop_mode": config.stop_mode,
                "target_points": float(config.target_points), "or_width_quintile": quintile,
                "eligible_candidates": len(selected),
                "unique_sessions": int(selected["session_date"].nunique()),
                "median_or_width": _median(selected["or_width_points"]),
                "ambiguous_entry_stop_count": int(entry.sum()),
                "ambiguous_entry_stop_percentage": _mean_bool(entry, 100),
                "ambiguous_stop_target_count": int(stop_target.sum()),
                "ambiguous_stop_target_percentage": _mean_bool(stop_target, 100),
                "other_execution_exclusion_count": int(other.sum()),
                "other_execution_exclusion_percentage": _mean_bool(other, 100),
                "total_execution_ambiguity_count": int(excluded.sum()),
                "total_execution_ambiguity_percentage": _mean_bool(excluded, 100),
            })
    return pd.DataFrame(rows)


def calculate_expectancy_bins(
    conditional: pd.DataFrame, quintiles: pd.DataFrame
) -> pd.DataFrame:
    medians = quintiles[["or_minutes", "or_width_quintile", "median_width"]]
    return conditional[[
        "config_id", "or_minutes", "stop_mode", "target_points",
        "or_width_quintile", "executed_trades", "average_r", "sample_warning",
    ]].merge(
        medians, on=["or_minutes", "or_width_quintile"], validate="many_to_one"
    )


def calculate_ratio_analysis(
    summary: pd.DataFrame, trades: pd.DataFrame, diagnostics: pd.DataFrame
) -> pd.DataFrame:
    """Build transparent within-configuration ratio bins and associations."""
    ratio_variables = (
        "target_to_or_ratio", "stop_to_or_ratio", "initial_reward_risk"
    )
    rows = []
    for config in summary.itertuples(index=False):
        candidate_config = diagnostics.loc[diagnostics["config_id"].eq(config.config_id)].copy()
        trade_config = trades.loc[trades["config_id"].eq(config.config_id)].copy()
        for ratio in ratio_variables:
            session_values = (
                candidate_config.groupby("session_date", sort=True)[ratio].median().reset_index()
            )
            if session_values[ratio].nunique(dropna=True) <= 1:
                session_values["ratio_bin"] = "ALL_CONSTANT"
            else:
                ordered = session_values.sort_values([ratio, "session_date"], kind="stable").reset_index(drop=True)
                ordered["ratio_bin"] = (
                    pd.qcut(pd.Series(np.arange(len(ordered))), q=5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
                    .astype(str)
                )
                session_values = ordered
            candidate_ratio = candidate_config.merge(
                session_values[["session_date", "ratio_bin"]], on="session_date", validate="many_to_one"
            )
            trade_ratio = trade_config.merge(
                session_values[["session_date", "ratio_bin"]], on="session_date", validate="many_to_one"
            )
            trade_ratio["target_hit"] = trade_ratio["exit_reason"].eq("TARGET").astype(float)
            trade_ratio["stop_hit"] = trade_ratio["exit_reason"].eq("STOP").astype(float)
            trade_ratio["session_end_hit"] = trade_ratio["exit_reason"].eq("SESSION_END").astype(float)
            trade_ratio["win"] = trade_ratio["result_r"].gt(0).astype(float)
            ambiguity = candidate_ratio["excluded_from_performance"].astype(float)
            associations = {
                "ratio_pearson_result_r": _correlation(trade_ratio[ratio], trade_ratio["result_r"], "pearson"),
                "ratio_spearman_result_r": _correlation(trade_ratio[ratio], trade_ratio["result_r"], "spearman"),
                "ratio_pearson_target_hit": _correlation(trade_ratio[ratio], trade_ratio["target_hit"], "pearson"),
                "ratio_spearman_target_hit": _correlation(trade_ratio[ratio], trade_ratio["target_hit"], "spearman"),
                "ratio_pearson_stop_hit": _correlation(trade_ratio[ratio], trade_ratio["stop_hit"], "pearson"),
                "ratio_spearman_stop_hit": _correlation(trade_ratio[ratio], trade_ratio["stop_hit"], "spearman"),
                "ratio_pearson_session_end": _correlation(trade_ratio[ratio], trade_ratio["session_end_hit"], "pearson"),
                "ratio_spearman_session_end": _correlation(trade_ratio[ratio], trade_ratio["session_end_hit"], "spearman"),
                "ratio_pearson_win": _correlation(trade_ratio[ratio], trade_ratio["win"], "pearson"),
                "ratio_spearman_win": _correlation(trade_ratio[ratio], trade_ratio["win"], "spearman"),
                "ratio_pearson_ambiguity": _correlation(candidate_ratio[ratio], ambiguity, "pearson"),
                "ratio_spearman_ambiguity": _correlation(candidate_ratio[ratio], ambiguity, "spearman"),
            }
            bin_order = ["Q1", "Q2", "Q3", "Q4", "Q5", "ALL_CONSTANT"]
            for bin_label in bin_order:
                candidate_bin = candidate_ratio.loc[candidate_ratio["ratio_bin"].eq(bin_label)]
                trade_bin = trade_ratio.loc[trade_ratio["ratio_bin"].eq(bin_label)]
                if candidate_bin.empty:
                    continue
                rows.append({
                    "research_scope": "DEVELOPMENT_ONLY", "config_id": config.config_id,
                    "or_minutes": int(config.or_minutes), "stop_mode": config.stop_mode,
                    "target_points": float(config.target_points), "ratio_variable": ratio,
                    "ratio_bin": bin_label, "candidate_count": len(candidate_bin),
                    "executed_trades": len(trade_bin), "median_ratio": _median(candidate_bin[ratio]),
                    "average_r": _mean(trade_bin["result_r"]),
                    "win_rate": _mean_bool(trade_bin["win"]),
                    "target_hit_percentage": _mean_bool(trade_bin["target_hit"], 100),
                    "stop_hit_percentage": _mean_bool(trade_bin["stop_hit"], 100),
                    "session_end_percentage": _mean_bool(trade_bin["session_end_hit"], 100),
                    "ambiguity_percentage": _mean_bool(
                        candidate_bin["excluded_from_performance"], 100
                    ),
                    "sample_warning": "LOW_SAMPLE" if len(trade_bin) < LOW_SAMPLE_THRESHOLD else "OK",
                    **associations,
                })
    return pd.DataFrame(rows)


def _reconcile_trade_and_diagnostic_rows(trades, diagnostics) -> None:
    included = diagnostics.loc[diagnostics["inclusion_exclusion_status"].eq("INCLUDED_EXECUTED")]
    keys = ["config_id", "session_date", "or_minutes", "direction", "signal_time"]
    if included.duplicated(keys).any() or trades.duplicated(keys).any():
        raise ValueError("Gate 6B executed audit keys are not unique")
    left = included[keys + ["result_r", "exit_reason"]].sort_values(keys).reset_index(drop=True)
    right = trades[keys + ["result_r", "exit_reason"]].sort_values(keys).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False, rtol=0, atol=1e-12)
    except AssertionError as error:
        raise ValueError("Gate 6B trade and diagnostic artifacts do not reconcile") from error


def _reconcile_summary(summary, trades) -> None:
    grouped = trades.groupby("config_id", sort=False)["result_r"].agg(["size", "mean", "sum"])
    merged = summary.merge(grouped, left_on="config_id", right_index=True, validate="one_to_one")
    if not merged["executed_trades"].eq(merged["size"]).all():
        raise ValueError("Gate 6B summary trade counts do not reconcile")
    for left, right in (("average_r", "mean"), ("total_r", "sum")):
        if not np.allclose(merged[left], merged[right], rtol=0, atol=1e-12):
            raise ValueError(f"Gate 6B summary {left} does not reconcile")


def _reconcile_conditional(summary, conditional) -> None:
    grouped = conditional.groupby("config_id", sort=False).agg(
        trades=("executed_trades", "sum"), total_r=("total_r", "sum")
    )
    merged = summary.merge(grouped, left_on="config_id", right_index=True, validate="one_to_one")
    if not merged["executed_trades"].eq(merged["trades"]).all():
        raise ValueError("Conditional quintile trade counts do not reconcile")
    if not np.allclose(merged["total_r_x"], merged["total_r_y"], rtol=0, atol=1e-12):
        raise ValueError("Conditional quintile total R does not reconcile")


def _correlation(left, right, method: str) -> float:
    frame = pd.DataFrame({"left": pd.to_numeric(left), "right": pd.to_numeric(right)}).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return np.nan
    if method == "spearman":
        return float(frame["left"].rank(method="average").corr(frame["right"].rank(method="average")))
    return float(frame["left"].corr(frame["right"]))


def _mean(values) -> float:
    return float(pd.to_numeric(values).mean()) if len(values) else np.nan


def _median(values) -> float:
    return float(pd.to_numeric(values).median()) if len(values) else np.nan


def _mean_bool(values, multiplier: float = 1.0) -> float:
    return float(pd.Series(values).astype(float).mean() * multiplier) if len(values) else np.nan


def _to_boolean(values: pd.Series, column: str) -> pd.Series:
    if values.dtype == bool:
        return values
    mapped = values.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise ValueError(f"{column} contains non-boolean values")
    return mapped


def write_outputs(
    distribution, quintiles, conditional, expectancy, correlations,
    ratio_analysis, ambiguity, metadata, output_dir,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "orb_gate6b1_DEV"
    paths = {
        "distribution": output_dir / f"{prefix}_or_width_distribution.csv",
        "quintiles": output_dir / f"{prefix}_or_width_quintiles.csv",
        "conditional_performance": output_dir / f"{prefix}_or_width_conditional_performance.csv",
        "expectancy_bins": output_dir / f"{prefix}_or_width_expectancy_bins.csv",
        "correlations": output_dir / f"{prefix}_or_width_correlations.csv",
        "ratio_analysis": output_dir / f"{prefix}_ratio_analysis.csv",
        "ambiguity_by_width": output_dir / f"{prefix}_ambiguity_by_or_width.csv",
        "metadata": output_dir / f"{prefix}_metadata.json",
        "distribution_chart": output_dir / f"{prefix}_or_width_distribution.html",
        "average_r_heatmap": output_dir / f"{prefix}_average_r_heatmap.html",
        "profit_factor_heatmap": output_dir / f"{prefix}_profit_factor_heatmap.html",
        "target_hit_heatmap": output_dir / f"{prefix}_target_hit_heatmap.html",
        "ambiguity_heatmap": output_dir / f"{prefix}_ambiguity_exclusion_heatmap.html",
        "expectancy_curve": output_dir / f"{prefix}_expectancy_curve.html",
        "ambiguity_curve": output_dir / f"{prefix}_ambiguity_by_width.html",
    }
    distribution.to_csv(paths["distribution"], index=False)
    quintiles.to_csv(paths["quintiles"], index=False)
    conditional.to_csv(paths["conditional_performance"], index=False)
    expectancy.to_csv(paths["expectancy_bins"], index=False)
    correlations.to_csv(paths["correlations"], index=False)
    ratio_analysis.to_csv(paths["ratio_analysis"], index=False)
    ambiguity.to_csv(paths["ambiguity_by_width"], index=False)
    write_distribution_chart(distribution, metadata["unique_width_observations"], paths["distribution_chart"])
    write_conditional_heatmap(conditional, "average_r", "Average R", paths["average_r_heatmap"])
    write_conditional_heatmap(conditional, "profit_factor_r", "Profit Factor (R)", paths["profit_factor_heatmap"])
    write_conditional_heatmap(conditional, "target_hit_percentage", "Target-hit rate (%)", paths["target_hit_heatmap"])
    write_conditional_heatmap(
        conditional, "ambiguity_exclusion_percentage", "Execution ambiguity / exclusion (%)",
        paths["ambiguity_heatmap"],
    )
    write_expectancy_curve(expectancy, paths["expectancy_curve"])
    write_ambiguity_curve(ambiguity, paths["ambiguity_curve"])
    for ratio in ("target_to_or_ratio", "stop_to_or_ratio", "initial_reward_risk"):
        name = ratio.replace("_ratio", "")
        path = output_dir / f"{prefix}_{name}_relationship.html"
        write_ratio_curve(ratio_analysis, ratio, path)
        paths[f"{name}_relationship"] = path
    metadata = {**metadata, "artifacts": {name: str(path) for name, path in paths.items()}}
    # The unique observations are stored in metadata only long enough to plot.
    metadata.pop("unique_width_observations", None)
    paths["metadata"].write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return paths


def write_distribution_chart(distribution, width_records, path) -> None:
    widths = pd.DataFrame(width_records)
    figure = make_subplots(rows=3, cols=1, subplot_titles=tuple(f"{d}m PRINT" for d in OR_DURATIONS))
    for row, duration in enumerate(OR_DURATIONS, start=1):
        values = widths.loc[widths["or_minutes"].eq(duration), "or_width_points"]
        figure.add_trace(go.Histogram(
            x=values, nbinsx=25, name=f"{duration}m", showlegend=False,
            hovertemplate="OR width: %{x:.2f}<br>Sessions: %{y}<extra></extra>",
        ), row=row, col=1)
        figure.update_xaxes(title_text="OR width (points)", row=row, col=1)
        figure.update_yaxes(title_text="Unique sessions", row=row, col=1)
    figure.update_layout(
        title="Gate 6B.1 — OR-width distributions — DEVELOPMENT ONLY",
        template="plotly_white", height=900, width=1050, bargap=0.04,
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def write_conditional_heatmap(conditional, metric, label, path) -> None:
    selections = [(duration, stop) for duration in OR_DURATIONS for stop in STOP_MODES]
    figure = go.Figure()
    for index, (duration, stop) in enumerate(selections):
        selected = conditional.loc[
            conditional["or_minutes"].eq(duration) & conditional["stop_mode"].eq(stop)
        ]
        pivot = selected.pivot(index="or_width_quintile", columns="target_points", values=metric).reindex(
            index=QUINTILES, columns=TARGET_POINTS
        )
        counts = selected.pivot(index="or_width_quintile", columns="target_points", values="executed_trades").reindex(
            index=QUINTILES, columns=TARGET_POINTS
        )
        custom = np.dstack((counts.to_numpy(), pivot.to_numpy()))
        figure.add_trace(go.Heatmap(
            z=pivot.to_numpy(dtype=float), x=[f"{int(v)}pt" for v in TARGET_POINTS],
            y=[f"Q{q}" for q in QUINTILES], visible=index == 0,
            colorscale="RdYlGn" if metric != "ambiguity_exclusion_percentage" else "YlOrRd",
            text=np.vectorize(lambda value: f"{value:.3f}")(pivot.to_numpy(dtype=float)),
            texttemplate="%{text}", customdata=custom,
            hovertemplate=(
                "Width: %{y}<br>Target: %{x}<br>" + label
                + ": %{z:.5f}<br>Executed N: %{customdata[0]:.0f}<extra></extra>"
            ), colorbar={"title": label},
        ))
    buttons = []
    for index, (duration, stop) in enumerate(selections):
        visible = [False] * len(selections)
        visible[index] = True
        buttons.append({
            "label": f"{duration}m | {stop}", "method": "update",
            "args": [{"visible": visible}, {"title": f"Gate 6B.1 — {label} — {duration}m {stop} — DEVELOPMENT ONLY"}],
        })
    first_duration, first_stop = selections[0]
    figure.update_layout(
        title=f"Gate 6B.1 — {label} — {first_duration}m {first_stop} — DEVELOPMENT ONLY",
        xaxis_title="Fixed target", yaxis_title="Duration-specific OR-width quintile",
        template="plotly_white", height=650, width=1000,
        updatemenus=[{"buttons": buttons, "direction": "down", "x": 0, "y": 1.15}],
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def write_expectancy_curve(expectancy, path) -> None:
    config_ids = expectancy["config_id"].drop_duplicates().tolist()
    figure = go.Figure()
    for index, config_id in enumerate(config_ids):
        selected = expectancy.loc[expectancy["config_id"].eq(config_id)].sort_values("median_width")
        figure.add_trace(go.Scatter(
            x=selected["median_width"], y=selected["average_r"], mode="lines+markers+text",
            text=selected["executed_trades"].map(lambda value: f"N={value}"),
            textposition="top center", name=config_id, visible=index == 0,
            customdata=selected[["or_width_quintile", "executed_trades", "sample_warning"]],
            hovertemplate=(
                "Median OR width: %{x:.2f}<br>Avg R: %{y:.4f}<br>"
                "Quintile: Q%{customdata[0]}<br>N: %{customdata[1]}<br>"
                "%{customdata[2]}<extra></extra>"
            ),
        ))
    buttons = []
    for index, config_id in enumerate(config_ids):
        visible = [False] * len(config_ids)
        visible[index] = True
        buttons.append({"label": config_id, "method": "update", "args": [
            {"visible": visible},
            {"title": f"Gate 6B.1 — OR-width expectancy — {config_id} — DEVELOPMENT ONLY"},
        ]})
    figure.add_hline(y=0, line_dash="dot", line_color="black")
    figure.update_layout(
        title=f"Gate 6B.1 — OR-width expectancy — {config_ids[0]} — DEVELOPMENT ONLY",
        xaxis_title="Median OR width (points)", yaxis_title="Average R",
        template="plotly_white", height=680, width=1100,
        updatemenus=[{"buttons": buttons, "direction": "down", "x": 0, "y": 1.15}],
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def write_ambiguity_curve(ambiguity, path) -> None:
    config_ids = ambiguity["config_id"].drop_duplicates().tolist()
    figure = go.Figure()
    components = (
        ("ambiguous_entry_stop_percentage", "Entry/stop", "#c62828"),
        ("ambiguous_stop_target_percentage", "Stop/target", "#ef6c00"),
        ("other_execution_exclusion_percentage", "Other exclusion", "#455a64"),
    )
    trace_count = len(config_ids) * len(components)
    for config_index, config_id in enumerate(config_ids):
        selected = ambiguity.loc[ambiguity["config_id"].eq(config_id)].sort_values("or_width_quintile")
        for metric, label, color in components:
            figure.add_trace(go.Scatter(
                x=[f"Q{value}" for value in selected["or_width_quintile"]],
                y=selected[metric], mode="lines+markers", name=label,
                legendgroup=label, line={"color": color}, visible=config_index == 0,
                customdata=selected[["eligible_candidates", "median_or_width"]],
                hovertemplate=(
                    f"{label}<br>Width: %{{x}}<br>Rate: %{{y:.2f}}%<br>"
                    "Candidate N: %{customdata[0]}<br>Median width: %{customdata[1]:.2f}<extra></extra>"
                ),
            ))
    buttons = []
    for config_index, config_id in enumerate(config_ids):
        visible = [False] * trace_count
        start = config_index * len(components)
        for offset in range(len(components)):
            visible[start + offset] = True
        buttons.append({"label": config_id, "method": "update", "args": [
            {"visible": visible},
            {"title": f"Gate 6B.1 — Ambiguity by OR width — {config_id} — DEVELOPMENT ONLY"},
        ]})
    figure.update_layout(
        title=f"Gate 6B.1 — Ambiguity by OR width — {config_ids[0]} — DEVELOPMENT ONLY",
        xaxis_title="Duration-specific OR-width quintile", yaxis_title="Candidate rate (%)",
        template="plotly_white", height=680, width=1100,
        updatemenus=[{"buttons": buttons, "direction": "down", "x": 0, "y": 1.15}],
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def write_ratio_curve(ratio_analysis, ratio_variable, path) -> None:
    selected_ratio = ratio_analysis.loc[ratio_analysis["ratio_variable"].eq(ratio_variable)]
    config_ids = selected_ratio["config_id"].drop_duplicates().tolist()
    figure = go.Figure()
    for index, config_id in enumerate(config_ids):
        selected = selected_ratio.loc[selected_ratio["config_id"].eq(config_id)].copy()
        selected["_order"] = selected["ratio_bin"].map(
            {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "Q5": 5, "ALL_CONSTANT": 1}
        )
        selected = selected.sort_values("_order")
        figure.add_trace(go.Scatter(
            x=selected["median_ratio"], y=selected["average_r"], mode="lines+markers+text",
            text=selected["executed_trades"].map(lambda value: f"N={value}"),
            textposition="top center", name=config_id, visible=index == 0,
            customdata=selected[["ratio_bin", "target_hit_percentage", "stop_hit_percentage", "ambiguity_percentage"]],
            hovertemplate=(
                "Median ratio: %{x:.4f}<br>Avg R: %{y:.4f}<br>Bin: %{customdata[0]}"
                "<br>Target hit: %{customdata[1]:.2f}%<br>Stop hit: %{customdata[2]:.2f}%"
                "<br>Ambiguity: %{customdata[3]:.2f}%<extra></extra>"
            ),
        ))
    buttons = []
    for index, config_id in enumerate(config_ids):
        visible = [False] * len(config_ids)
        visible[index] = True
        buttons.append({"label": config_id, "method": "update", "args": [
            {"visible": visible},
            {"title": f"Gate 6B.1 — {ratio_variable} relationship — {config_id} — DEVELOPMENT ONLY"},
        ]})
    figure.add_hline(y=0, line_dash="dot", line_color="black")
    figure.update_layout(
        title=f"Gate 6B.1 — {ratio_variable} relationship — {config_ids[0]} — DEVELOPMENT ONLY",
        xaxis_title=f"Median {ratio_variable}", yaxis_title="Average R",
        template="plotly_white", height=680, width=1100,
        updatemenus=[{"buttons": buttons, "direction": "down", "x": 0, "y": 1.15}],
    )
    figure.write_html(path, include_plotlyjs="cdn", config={"responsive": True})


def sha256_files(paths: list[str | Path]) -> dict[str, str]:
    hashes = {}
    for path in paths:
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        hashes[Path(path).name] = digest.hexdigest()
    return hashes
