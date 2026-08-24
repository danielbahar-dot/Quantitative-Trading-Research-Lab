"""Gate 8A retrospective DEVELOPMENT/VALIDATION diagnostics for MNQ ORB V0.1.

This module deliberately reuses the validated Gate 6B execution path.  It is a
post-Validation failure diagnostic, not a confirmatory test or parameter search.
OOS data is outside its API and must never be supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backtesting.completed_trades import AMBIGUOUS_ENTRY_STOP, SESSION_END, STOP, TARGET, simulate_completed_trades
from src.backtesting.session_trade_limit import apply_session_trade_limit
from src.experiments.orb_gate6b_fixed_points import (
    EXPECTED_CONFIGURATIONS,
    _annotate_audit,
    _assert_completed_r_math,
    _build_or_width_diagnostics,
    _configuration_metrics,
    _enrich_executed,
    build_gate6b_candidates,
    configuration_grid,
)
from src.experiments.orb_gate7_validation import _chronology_for_config
from src.visualization.research_viewer import find_orb_signals


RESEARCH_LABEL = "POST-VALIDATION DIAGNOSTIC — NOT CONFIRMATORY"
DEV_START = pd.Timestamp("2024-06-21")
DEV_END = pd.Timestamp("2025-06-30")
VAL_START = pd.Timestamp("2025-07-01")
VAL_END = pd.Timestamp("2025-12-31")
OOS_START = pd.Timestamp("2026-01-01")

FROZEN_CANDIDATES = {
    "MNQ_ORB_V01_CAND_001": "15m_PRINT_FIXED_50_TARGET75PT",
    "MNQ_ORB_V01_CAND_002": "20m_PRINT_OR_MIDPOINT_TARGET75PT",
    "MNQ_ORB_V01_CAND_003": "30m_PRINT_FIXED_40_TARGET75PT",
}


@dataclass(frozen=True)
class SurfaceRun:
    summary: pd.DataFrame
    trades: pd.DataFrame
    diagnostics: pd.DataFrame
    chronology: pd.DataFrame


def assert_partition(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, label: str) -> None:
    dates = pd.to_datetime(frame["session_date"]).dt.normalize()
    if frame.empty or not dates.between(start, end, inclusive="both").all():
        raise ValueError(f"{label} input contains a row outside its declared partition")
    if dates.max() >= OOS_START:
        raise ValueError("OOS_BURNED data entered Gate 8A")


def run_validation_surface(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
    *,
    validation_start: pd.Timestamp = VAL_START,
    validation_end: pd.Timestamp = VAL_END,
) -> SurfaceRun:
    """Execute the unchanged 75-cell Gate 6B surface on VALIDATION."""
    assert_partition(price_data, validation_start, validation_end, "VALIDATION")
    grid = configuration_grid()
    if len(grid) != EXPECTED_CONFIGURATIONS or grid["config_id"].duplicated().any():
        raise ValueError("The frozen Gate 6B grid must contain 75 unique cells")

    signals_by_duration: dict[int, pd.DataFrame] = {}
    ambiguities_by_duration: dict[int, pd.DataFrame] = {}
    for duration in sorted(grid["or_minutes"].unique()):
        signals, ambiguities = find_orb_signals(
            price_data, or_levels, start_date=validation_start,
            end_date=validation_end, or_minutes=int(duration), breakout_type="PRINT",
        )
        signals_by_duration[int(duration)] = signals
        ambiguities_by_duration[int(duration)] = ambiguities

    sessions = {session_date: group for session_date, group in price_data.groupby("session_date")}
    summaries: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    diagnostic_frames: list[pd.DataFrame] = []
    chronology_frames: list[pd.DataFrame] = []
    for row in grid.itertuples(index=False):
        config = SimpleNamespace(**row._asdict(), candidate_id=row.config_id)
        candidates = build_gate6b_candidates(
            price_data, signals_by_duration[row.or_minutes],
            or_minutes=row.or_minutes, stop_mode=row.stop_mode,
            target_points=row.target_points,
        )
        completed = simulate_completed_trades(price_data, candidates)
        _assert_completed_r_math(completed)
        executed, audit = apply_session_trade_limit(candidates, completed)
        if executed.duplicated(["session_date", "or_minutes", "breakout_type"]).any():
            raise ValueError("More than one Validation trade was accepted per session/config")
        enriched = _enrich_executed(executed, candidates, config)
        annotated = _annotate_audit(audit, config)
        diagnostics = _build_or_width_diagnostics(annotated, completed, config)
        for frame in (enriched, annotated, diagnostics):
            frame["research_scope"] = RESEARCH_LABEL
            frame["partition"] = "VALIDATION"
        metric = _configuration_metrics(
            config, candidates, completed, executed, enriched, annotated,
            ambiguities_by_duration[row.or_minutes], validation_start,
            validation_end, 0,
        )
        metric.update({
            "research_scope": RESEARCH_LABEL,
            "partition": "VALIDATION",
            "validation_start": validation_start.date().isoformat(),
            "validation_end": validation_end.date().isoformat(),
        })
        chronology = _chronology_for_config(
            config, candidates=annotated, completed=completed,
            diagnostics=diagnostics, frozen_trades=enriched, sessions=sessions,
            signal_ambiguity_count=len(ambiguities_by_duration[row.or_minutes]),
        )
        chronology["research_scope"] = RESEARCH_LABEL
        chronology["partition"] = "VALIDATION"
        summaries.append(metric)
        trade_frames.append(enriched)
        diagnostic_frames.append(diagnostics)
        chronology_frames.append(chronology)

    summary = pd.DataFrame(summaries)
    trades = pd.concat(trade_frames, ignore_index=True)
    diagnostics = pd.concat(diagnostic_frames, ignore_index=True)
    chronology = pd.concat(chronology_frames, ignore_index=True)
    if len(summary) != 75 or summary["config_id"].duplicated().any():
        raise ValueError("Validation surface did not produce every Gate 6B cell exactly once")
    if len(chronology) != 225:
        raise ValueError("Validation chronology must contain 75 cells x 3 scenarios")
    assert_partition(trades, validation_start, validation_end, "VALIDATION trades")
    return SurfaceRun(summary, trades, diagnostics, chronology)


def build_surface_comparison(
    development: pd.DataFrame,
    validation: pd.DataFrame,
    development_chronology: pd.DataFrame,
    validation_chronology: pd.DataFrame,
    evidence: pd.DataFrame,
) -> pd.DataFrame:
    """Create one diagnostic comparison row per frozen Gate 6B configuration."""
    metrics = [
        "average_r", "profit_factor_r", "max_drawdown_r", "ambiguity_rate",
        "entry_stop_ambiguity_rate", "executed_trades", "win_rate",
        "session_end_percentage", "positive_month_percentage",
    ]
    keys = ["config_id", "or_minutes", "breakout_type", "stop_mode", "target_points"]
    dev = development[keys + metrics].rename(columns={name: f"dev_{name}" for name in metrics})
    val = validation[keys + metrics].rename(columns={name: f"val_{name}" for name in metrics})
    output = dev.merge(val, on=keys, validate="one_to_one")
    output["average_r_delta"] = output["val_average_r"] - output["dev_average_r"]
    output["relative_average_r_change"] = np.where(
        output["dev_average_r"].abs() > 1e-12,
        output["average_r_delta"] / output["dev_average_r"].abs(), np.nan,
    )
    output["profit_factor_delta"] = output["val_profit_factor_r"] - output["dev_profit_factor_r"]
    output["sign_persistence"] = np.select(
        [
            output["dev_average_r"].gt(0) & output["val_average_r"].gt(0),
            output["dev_average_r"].gt(0) & output["val_average_r"].le(0),
            output["dev_average_r"].le(0) & output["val_average_r"].gt(0),
        ],
        ["POSITIVE_DEV_POSITIVE_VAL", "POSITIVE_DEV_NEGATIVE_VAL", "NEGATIVE_DEV_POSITIVE_VAL"],
        default="NEGATIVE_DEV_NEGATIVE_VAL",
    )
    for prefix, chronology in (("dev", development_chronology), ("val", validation_chronology)):
        desc = chronology.drop_duplicates("config_id").loc[:, [
            "config_id", "entry_first_avg_r", "adverse_move_first_avg_r",
            "chronology_range_avg_r", "entry_first_pf", "adverse_move_first_pf",
            "all_scenarios_positive",
        ]].rename(columns=lambda name: name if name == "config_id" else f"{prefix}_{name}")
        output = output.merge(desc, on="config_id", validate="one_to_one")
    support = evidence[["config_id", "neighbor_support", "supporting_target_neighbors", "supporting_stop_neighbors"]]
    output = output.merge(support, on="config_id", how="left", validate="one_to_one")
    output.insert(0, "research_scope", RESEARCH_LABEL)
    return output.sort_values(["or_minutes", "stop_mode", "target_points"]).reset_index(drop=True)


def persistence_statistics(comparison: pd.DataFrame) -> dict[str, Any]:
    sign_counts = comparison["sign_persistence"].value_counts().to_dict()
    dev_positive = comparison["dev_average_r"].gt(0)
    flips = comparison["sign_persistence"].eq("POSITIVE_DEV_NEGATIVE_VAL")
    strong = comparison["neighbor_support"].eq("STRONG")
    return {
        "spearman_average_r": float(comparison["dev_average_r"].corr(comparison["val_average_r"], method="spearman")),
        "spearman_profit_factor": float(comparison["dev_profit_factor_r"].corr(comparison["val_profit_factor_r"], method="spearman")),
        "median_average_r_delta": float(comparison["average_r_delta"].median()),
        "dev_positive_cells": int(dev_positive.sum()),
        "dev_positive_to_val_nonpositive": int(flips.sum()),
        "dev_positive_flip_rate": float(flips.sum() / dev_positive.sum()) if dev_positive.any() else np.nan,
        "sign_counts": {str(key): int(value) for key, value in sign_counts.items()},
        "strong_dev_neighborhood_cells": int(strong.sum()),
        "strong_dev_neighborhood_val_positive": int((strong & comparison["val_average_r"].gt(0)).sum()),
    }


def parameter_migration(comparison: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (duration, stop), group in comparison.groupby(["or_minutes", "stop_mode"], sort=True):
        dev_target = float(group.loc[group["dev_average_r"].idxmax(), "target_points"])
        val_target = float(group.loc[group["val_average_r"].idxmax(), "target_points"])
        rows.append({
            "research_scope": RESEARCH_LABEL, "comparison_axis": "TARGET_REGION",
            "or_minutes": int(duration), "fixed_dimension": stop,
            "dev_descriptive_peak": dev_target, "val_descriptive_peak": val_target,
            "migration": "STABLE_REGION" if dev_target == val_target else (
                "SHIFTED_TOWARD_LARGER_TARGETS" if val_target > dev_target else "SHIFTED_TOWARD_SMALLER_TARGETS"
            ),
            "dev_surface_range_r": float(group["dev_average_r"].max() - group["dev_average_r"].min()),
            "val_surface_range_r": float(group["val_average_r"].max() - group["val_average_r"].min()),
        })
    for (duration, target), group in comparison.groupby(["or_minutes", "target_points"], sort=True):
        dev_stop = str(group.loc[group["dev_average_r"].idxmax(), "stop_mode"])
        val_stop = str(group.loc[group["val_average_r"].idxmax(), "stop_mode"])
        rows.append({
            "research_scope": RESEARCH_LABEL, "comparison_axis": "STOP_FAMILY",
            "or_minutes": int(duration), "fixed_dimension": float(target),
            "dev_descriptive_peak": dev_stop, "val_descriptive_peak": val_stop,
            "migration": "STABLE_REGION" if dev_stop == val_stop else f"SHIFTED_{dev_stop}_TO_{val_stop}",
            "dev_surface_range_r": float(group["dev_average_r"].max() - group["dev_average_r"].min()),
            "val_surface_range_r": float(group["val_average_r"].max() - group["val_average_r"].min()),
        })
    return pd.DataFrame(rows)


def candidate_neighborhoods(comparison: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    broad = persistence_statistics(comparison)
    broad_support = broad["dev_positive_flip_rate"] >= 0.60 and broad["median_average_r_delta"] < 0
    target_neighbors = config["candidate_neighborhoods"]["target_neighbors"]["75"]
    stop_peers = config["candidate_neighborhoods"]["stop_peers"]
    for candidate_id, config_id in FROZEN_CANDIDATES.items():
        candidate = comparison.loc[comparison["config_id"].eq(config_id)].iloc[0]
        neighbor_mask = (
            comparison["or_minutes"].eq(candidate["or_minutes"])
            & (
                (comparison["stop_mode"].eq(candidate["stop_mode"]) & comparison["target_points"].isin(target_neighbors))
                | (comparison["target_points"].eq(candidate["target_points"]) & comparison["stop_mode"].isin(stop_peers[candidate["stop_mode"]]))
            )
        )
        neighbors = comparison.loc[neighbor_mask]
        positive_share = float(neighbors["val_average_r"].gt(0).mean())
        if broad_support and positive_share <= 0.50:
            classification = "BROAD_SURFACE_DETERIORATION"
        elif positive_share > 0.50 and float(neighbors["val_average_r"].mean()) > 0:
            classification = "LOCAL_FAILURE"
        else:
            classification = "NEIGHBORHOOD_DETERIORATION"
        for member_type, member in [("CANDIDATE", candidate), *[("NEIGHBOR", row) for _, row in neighbors.iterrows()]]:
            rows.append({
                "research_scope": RESEARCH_LABEL, "candidate_id": candidate_id,
                "candidate_config_id": config_id, "member_type": member_type,
                "member_config_id": member["config_id"], "or_minutes": int(member["or_minutes"]),
                "stop_mode": member["stop_mode"], "target_points": float(member["target_points"]),
                "dev_average_r": float(member["dev_average_r"]), "val_average_r": float(member["val_average_r"]),
                "average_r_delta": float(member["average_r_delta"]),
                "neighborhood_val_positive_share": positive_share,
                "neighborhood_val_mean_r": float(neighbors["val_average_r"].mean()),
                "candidate_failure_classification": classification,
            })
    return pd.DataFrame(rows)


def temporal_diagnostics(
    development_trades: pd.DataFrame,
    validation_trades: pd.DataFrame,
    representative_regions: dict[str, list[str]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[pd.DataFrame] = []
    descriptions: list[dict[str, Any]] = []
    entities = {**{key: [value] for key, value in FROZEN_CANDIDATES.items()}, **representative_regions}
    for period, source in (("DEVELOPMENT", development_trades), ("VALIDATION", validation_trades)):
        source = source.copy()
        source["session_date"] = pd.to_datetime(source["session_date"]).dt.normalize()
        for entity, config_ids in entities.items():
            selected = source.loc[source["config_id"].isin(config_ids)].copy()
            if len(config_ids) > 1:
                selected = selected.groupby("session_date", as_index=False).agg(
                    result_r=("result_r", "mean"), observations=("config_id", "nunique")
                )
                selected["trade_id"] = entity + "_" + selected["session_date"].dt.strftime("%Y%m%d")
                observation_unit = "SESSION_REGION_CENTROID"
            else:
                selected["observations"] = 1
                observation_unit = "EXECUTED_TRADE"
            selected = selected.sort_values(["session_date", "trade_id"], kind="stable")
            selected["rolling_30_average_r"] = selected["result_r"].rolling(30, min_periods=30).mean()
            selected["rolling_50_average_r"] = selected["result_r"].rolling(50, min_periods=50).mean()
            selected["month"] = selected["session_date"].dt.to_period("M").astype(str)
            monthly_stats = selected.groupby("month")["result_r"].agg(
                monthly_observations="count", monthly_average_r="mean", monthly_total_r="sum"
            )
            selected = selected.merge(monthly_stats, on="month", validate="many_to_one")
            selected["entity"] = entity
            selected["partition"] = period
            selected["observation_unit"] = observation_unit
            selected["research_scope"] = RESEARCH_LABEL
            records.append(selected[[
                "research_scope", "partition", "entity", "observation_unit", "session_date",
                "trade_id", "result_r", "observations", "rolling_30_average_r",
                "rolling_50_average_r", "month",
                "monthly_observations", "monthly_average_r", "monthly_total_r",
            ]])
            monthly = selected.groupby("month", sort=True)["result_r"].agg(["count", "mean", "sum"])
            if period == "VALIDATION":
                half = max(1, len(monthly) // 2)
                first, second = monthly.iloc[:half]["sum"].sum(), monthly.iloc[half:]["sum"].sum()
                nonpositive_share = float(monthly["sum"].le(0).mean())
                pattern = (
                    "ABRUPT" if first > 0 and second < 0
                    else "PERSISTENT_WEAKNESS" if nonpositive_share >= 2 / 3
                    else "EPISODIC"
                )
                descriptions.append({
                    "research_scope": RESEARCH_LABEL, "entity": entity,
                    "validation_first_half_total_r": float(first),
                    "validation_second_half_total_r": float(second),
                    "validation_nonpositive_month_share": nonpositive_share,
                    "deterioration_pattern": pattern,
                })
    temporal = pd.concat(records, ignore_index=True)
    return temporal, pd.DataFrame(descriptions)


def _merge_width_edges(values: pd.Series, initial_edges: list[float], minimum_n: int) -> list[float]:
    edges = [-np.inf, *map(float, initial_edges), np.inf]
    clean = pd.to_numeric(values, errors="coerce").dropna()
    while len(edges) > 4:
        counts = pd.cut(clean, bins=edges, right=False, include_lowest=True).value_counts(sort=False)
        smallest = int(np.argmin(counts.to_numpy()))
        if int(counts.iloc[smallest]) >= minimum_n:
            break
        if smallest == 0:
            del edges[1]
        elif smallest == len(counts) - 1:
            del edges[-2]
        elif int(counts.iloc[smallest - 1]) <= int(counts.iloc[smallest + 1]):
            del edges[smallest]
        else:
            del edges[smallest + 1]
    return edges


def _edge_labels(edges: list[float]) -> list[str]:
    labels = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        if np.isneginf(lower):
            labels.append(f"<{upper:g}")
        elif np.isposinf(upper):
            labels.append(f">={lower:g}")
        else:
            labels.append(f"{lower:g}-{upper:g}")
    return labels


def or_width_diagnostics(
    development_trades: pd.DataFrame,
    development_diagnostics: pd.DataFrame,
    validation_trades: pd.DataFrame,
    validation_diagnostics: pd.DataFrame,
    *,
    initial_edges: list[float],
    minimum_n: int,
) -> tuple[pd.DataFrame, list[float]]:
    sources = {
        "DEVELOPMENT": (development_trades.copy(), development_diagnostics.copy()),
        "VALIDATION": (validation_trades.copy(), validation_diagnostics.copy()),
    }
    unique_widths = []
    for period, (_, diagnostics) in sources.items():
        widths = diagnostics[["session_date", "or_minutes", "or_width_points"]].drop_duplicates()
        widths["partition"] = period
        unique_widths.append(widths)
    combined_widths = pd.concat(unique_widths, ignore_index=True)
    edges = _merge_width_edges(combined_widths["or_width_points"], initial_edges, minimum_n)
    labels = _edge_labels(edges)
    rows: list[dict[str, Any]] = []
    for period, (trades, diagnostics) in sources.items():
        for frame in (trades, diagnostics):
            frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
        widths = diagnostics[["session_date", "or_minutes", "or_width_points"]].drop_duplicates()
        assigned = []
        for duration, group in widths.groupby("or_minutes", sort=True):
            ordered = group.sort_values(["or_width_points", "session_date"], kind="stable").reset_index(drop=True)
            ordered["within_period_quintile"] = pd.qcut(
                np.arange(len(ordered)), q=5, labels=[1, 2, 3, 4, 5]
            ).astype(int)
            assigned.append(ordered)
        assigned_widths = pd.concat(assigned, ignore_index=True)
        assigned_widths["absolute_width_bucket"] = pd.cut(
            assigned_widths["or_width_points"], bins=edges, labels=labels,
            right=False, include_lowest=True,
        ).astype(str)
        join = assigned_widths[["session_date", "or_minutes", "within_period_quintile", "absolute_width_bucket"]]
        for duration, distribution in assigned_widths.groupby("or_minutes", sort=True):
            values = distribution["or_width_points"].astype(float)
            rows.append({
                "research_scope": RESEARCH_LABEL, "partition": period,
                "analysis_kind": "WIDTH_DISTRIBUTION", "config_id": "ALL_CONFIGS",
                "or_minutes": int(duration), "stop_mode": "ALL",
                "target_points": np.nan, "width_cell": "ALL",
                "unique_session_count": int(distribution["session_date"].nunique()),
                "mean_or_width": float(values.mean()), "median_or_width": float(values.median()),
                "std_or_width": float(values.std(ddof=1)), "min_or_width": float(values.min()),
                "max_or_width": float(values.max()), "p10_or_width": float(values.quantile(0.10)),
                "p25_or_width": float(values.quantile(0.25)), "p75_or_width": float(values.quantile(0.75)),
                "p90_or_width": float(values.quantile(0.90)),
            })
        trades = trades.merge(join, on=["session_date", "or_minutes"], validate="many_to_one")
        diagnostics = diagnostics.merge(join, on=["session_date", "or_minutes"], validate="many_to_one")
        for kind, column, ordered_labels in (
            ("WITHIN_PERIOD_QUINTILE", "within_period_quintile", [1, 2, 3, 4, 5]),
            ("COMMON_ABSOLUTE_BUCKET", "absolute_width_bucket", labels),
        ):
            for config_id, config_trades in trades.groupby("config_id", sort=True):
                config_diag = diagnostics.loc[diagnostics["config_id"].eq(config_id)]
                first = config_trades.iloc[0]
                for bucket in ordered_labels:
                    trade_bin = config_trades.loc[config_trades[column].eq(bucket)]
                    diag_bin = config_diag.loc[config_diag[column].eq(bucket)]
                    result = trade_bin["result_r"].astype(float)
                    rows.append({
                        "research_scope": RESEARCH_LABEL, "partition": period,
                        "analysis_kind": kind, "config_id": config_id,
                        "or_minutes": int(first["or_minutes"]), "stop_mode": first["stop_mode"],
                        "target_points": float(first["target_points"]), "width_cell": str(bucket),
                        "lower_width_boundary": float(diag_bin["or_width_points"].min()) if len(diag_bin) else np.nan,
                        "upper_width_boundary": float(diag_bin["or_width_points"].max()) if len(diag_bin) else np.nan,
                        "eligible_candidates": len(diag_bin), "executed_trades": len(trade_bin),
                        "average_r": float(result.mean()) if len(result) else np.nan,
                        "total_r": float(result.sum()),
                        "ambiguity_rate": float(diag_bin["excluded_from_performance"].fillna(False).mean()) if len(diag_bin) else np.nan,
                        "target_hit_percentage": float(trade_bin["exit_reason"].eq(TARGET).mean() * 100) if len(trade_bin) else np.nan,
                        "stop_hit_percentage": float(trade_bin["exit_reason"].eq(STOP).mean() * 100) if len(trade_bin) else np.nan,
                        "session_end_percentage": float(trade_bin["exit_reason"].eq(SESSION_END).mean() * 100) if len(trade_bin) else np.nan,
                        "sample_warning": "LOW_SAMPLE" if len(trade_bin) < 10 else "OK",
                    })
    return pd.DataFrame(rows), edges


def price_normalization_diagnostic(
    development_or_levels: pd.DataFrame,
    validation_or_levels: pd.DataFrame,
) -> pd.DataFrame:
    records = []
    for period, frame in (("DEVELOPMENT", development_or_levels), ("VALIDATION", validation_or_levels)):
        selected = frame.loc[frame["or_minutes"].isin([15, 20, 30])].copy()
        selected = selected.drop_duplicates(["session_date", "or_minutes"])
        for row in selected.itertuples(index=False):
            market = float(row.or_mid)
            records.append({
                "research_scope": RESEARCH_LABEL, "record_type": "SESSION",
                "partition": period, "session_date": row.session_date,
                "or_minutes": int(row.or_minutes), "or_mid_market_level": market,
                **{f"fixed_stop_{points}_pct_price": points / market for points in (30, 40, 50)},
                **{f"target_{points}_pct_price": points / market for points in (40, 50, 60, 75, 100)},
            })
    sessions = pd.DataFrame(records)
    summaries = []
    for duration in (15, 20, 30):
        dev = sessions.loc[(sessions["partition"] == "DEVELOPMENT") & (sessions["or_minutes"] == duration)]
        val = sessions.loc[(sessions["partition"] == "VALIDATION") & (sessions["or_minutes"] == duration)]
        dev_level, val_level = dev["or_mid_market_level"].median(), val["or_mid_market_level"].median()
        summaries.append({
            "research_scope": RESEARCH_LABEL, "record_type": "SUMMARY",
            "partition": "DEV_VS_VAL", "session_date": pd.NaT, "or_minutes": duration,
            "or_mid_market_level": np.nan, "dev_median_market_level": float(dev_level),
            "val_median_market_level": float(val_level),
            "relative_market_level_change": float(val_level / dev_level - 1),
            "dev_75pt_pct_price": float(75 / dev_level),
            "val_75pt_pct_price": float(75 / val_level),
            "relative_75pt_fraction_change": float((75 / val_level) / (75 / dev_level) - 1),
        })
    return pd.concat([sessions, pd.DataFrame(summaries)], ignore_index=True, sort=False)


def observability_comparison(
    development_summary: pd.DataFrame,
    validation_summary: pd.DataFrame,
    development_chronology: pd.DataFrame,
    validation_chronology: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for stop_mode in sorted(development_summary["stop_mode"].unique()):
        row: dict[str, Any] = {"research_scope": RESEARCH_LABEL, "stop_mode": stop_mode}
        for prefix, summary, chronology in (
            ("dev", development_summary, development_chronology),
            ("val", validation_summary, validation_chronology),
        ):
            selected = summary.loc[summary["stop_mode"].eq(stop_mode)]
            chrono = chronology.loc[chronology["stop_mode"].eq(stop_mode)].drop_duplicates("config_id")
            eligible = float(selected["eligible_candidates"].sum())
            row.update({
                f"{prefix}_eligible_candidates": int(eligible),
                f"{prefix}_entry_stop_ambiguity_rate": float(selected["entry_stop_ambiguity_count"].sum() / eligible),
                f"{prefix}_total_exclusion_rate": float(selected["ambiguity_exclusion_count"].sum() / eligible),
                f"{prefix}_entry_first_sensitivity_average_r": float((chrono["entry_first_avg_r"] - chrono["excluded_avg_r"]).mean()),
                f"{prefix}_chronology_range_average_r": float(chrono["chronology_range_avg_r"].mean()),
            })
        row["entry_stop_ambiguity_rate_delta"] = row["val_entry_stop_ambiguity_rate"] - row["dev_entry_stop_ambiguity_rate"]
        row["total_exclusion_rate_delta"] = row["val_total_exclusion_rate"] - row["dev_total_exclusion_rate"]
        rows.append(row)
    return pd.DataFrame(rows)


def hypothesis_classifications(
    comparison: pd.DataFrame,
    migration: pd.DataFrame,
    neighborhoods: pd.DataFrame,
    width: pd.DataFrame,
) -> pd.DataFrame:
    persistence = persistence_statistics(comparison)
    broad_support = persistence["dev_positive_flip_rate"] >= 0.60 and persistence["median_average_r_delta"] < 0
    broad_partial = persistence["dev_positive_flip_rate"] >= 0.60 or persistence["median_average_r_delta"] < 0
    shifted = float(migration["migration"].ne("STABLE_REGION").mean())
    migration_support = persistence["spearman_average_r"] <= 0.25 and shifted >= 0.60
    migration_partial = persistence["spearman_average_r"] < 0.50 or shifted >= 0.40
    within = width.loc[width["analysis_kind"].eq("WITHIN_PERIOD_QUINTILE")]
    dev = within.loc[within["partition"].eq("DEVELOPMENT"), ["config_id", "width_cell", "average_r"]].rename(columns={"average_r": "dev"})
    val = within.loc[within["partition"].eq("VALIDATION"), ["config_id", "width_cell", "average_r", "or_minutes"]].rename(columns={"average_r": "val"})
    width_pairs = dev.merge(val, on=["config_id", "width_cell"])
    valid = width_pairs[["dev", "val"]].notna().all(axis=1)
    width_pairs = width_pairs.loc[valid]
    width_sign_change = float((width_pairs["dev"].gt(0) != width_pairs["val"].gt(0)).mean())
    duration_shift = width_pairs.assign(delta=(width_pairs["val"] - width_pairs["dev"]).abs()).groupby("or_minutes")["delta"].median()
    shifted_durations = int(duration_shift.ge(0.15).sum())
    state_support = width_sign_change >= 0.40 and shifted_durations >= 2
    state_partial = width_sign_change >= 0.40 or shifted_durations >= 1
    candidate_rows = neighborhoods.loc[neighborhoods["member_type"].eq("CANDIDATE")]
    overfit_flags = (
        (candidate_rows["dev_average_r"] > candidate_rows["neighborhood_val_mean_r"] + 0.05)
        & (candidate_rows["val_average_r"] < candidate_rows["neighborhood_val_mean_r"])
    )
    # Recalculate the DEV neighborhood mean from member rows for the selection test.
    flags = []
    for candidate_id, group in neighborhoods.groupby("candidate_id"):
        candidate = group.loc[group["member_type"].eq("CANDIDATE")].iloc[0]
        neighbors = group.loc[group["member_type"].eq("NEIGHBOR")]
        flags.append(
            candidate["dev_average_r"] > neighbors["dev_average_r"].mean() + 0.05
            and candidate["val_average_r"] < neighbors["val_average_r"].mean()
        )
    overfit_count = int(sum(flags))
    rows = [
        ("BROAD_EDGE_DETERIORATION", broad_support, broad_partial,
         f"DEV-positive flip rate={persistence['dev_positive_flip_rate']:.3f}; median Avg-R delta={persistence['median_average_r_delta']:.4f}."),
        ("PARAMETER_INSTABILITY_MIGRATION", migration_support, migration_partial,
         f"Avg-R Spearman={persistence['spearman_average_r']:.3f}; grouped descriptive-peak shift rate={shifted:.3f}."),
        ("MARKET_STATE_DEPENDENCE", state_support, state_partial,
         f"Within-period width-cell sign-change rate={width_sign_change:.3f}; durations with median absolute change >=0.15R={shifted_durations}."),
        ("SELECTION_ERROR_OVERFITTING", overfit_count >= 2, overfit_count >= 1,
         f"Frozen candidates satisfying the predeclared selection-error pattern={overfit_count}/3."),
    ]
    return pd.DataFrame([
        {"research_scope": RESEARCH_LABEL, "hypothesis": name,
         "classification": "SUPPORTS" if supports else "PARTIAL" if partial else "DOES_NOT_SUPPORT",
         "evidence": evidence}
        for name, supports, partial, evidence in rows
    ])


def write_surface_visualizations(comparison: pd.DataFrame, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    metrics = {
        "average_r": ("Average R", False),
        "profit_factor_r": ("Profit Factor", False),
        "max_drawdown_r": ("Maximum Drawdown R", True),
        "ambiguity_rate": ("Ambiguity Rate", True),
    }
    stop_modes = sorted(comparison["stop_mode"].unique())
    targets = sorted(comparison["target_points"].unique())
    durations = sorted(comparison["or_minutes"].unique())
    for metric, (label, _) in metrics.items():
        values = pd.concat([comparison[f"dev_{metric}"], comparison[f"val_{metric}"]])
        zmin, zmax = float(values.min()), float(values.max())
        figure = make_subplots(rows=len(stop_modes), cols=2, subplot_titles=[
            f"{stop} — {period}" for stop in stop_modes for period in ("DEVELOPMENT", "VALIDATION")
        ])
        for row_index, stop in enumerate(stop_modes, start=1):
            selected = comparison.loc[comparison["stop_mode"].eq(stop)]
            for col_index, prefix in enumerate(("dev", "val"), start=1):
                pivot = selected.pivot(index="or_minutes", columns="target_points", values=f"{prefix}_{metric}").reindex(index=durations, columns=targets)
                figure.add_trace(go.Heatmap(
                    z=pivot.values, x=targets, y=durations, zmin=zmin, zmax=zmax,
                    coloraxis="coloraxis", text=np.round(pivot.values, 4), texttemplate="%{text}",
                ), row=row_index, col=col_index)
        figure.update_layout(
            title=f"{RESEARCH_LABEL}<br>Paired DEVELOPMENT vs VALIDATION {label}",
            height=1150, coloraxis={"colorscale": "RdYlGn"}, showlegend=False,
        )
        path = output_dir / f"gate8a_dev_val_{metric}_heatmaps.html"
        figure.write_html(path, include_plotlyjs="cdn")
        paths[f"{metric}_heatmaps"] = path

    figure = make_subplots(rows=len(stop_modes), cols=2, subplot_titles=[
        f"{stop} — Avg-R delta" if index % 2 == 0 else f"{stop} — sign persistence"
        for stop in stop_modes for index in range(2)
    ])
    sign_code = {"NEGATIVE_DEV_NEGATIVE_VAL": 0, "POSITIVE_DEV_NEGATIVE_VAL": 1, "NEGATIVE_DEV_POSITIVE_VAL": 2, "POSITIVE_DEV_POSITIVE_VAL": 3}
    limit = float(comparison["average_r_delta"].abs().max())
    for row_index, stop in enumerate(stop_modes, start=1):
        selected = comparison.loc[comparison["stop_mode"].eq(stop)]
        delta = selected.pivot(index="or_minutes", columns="target_points", values="average_r_delta").reindex(index=durations, columns=targets)
        signs = selected.assign(sign_code=selected["sign_persistence"].map(sign_code)).pivot(index="or_minutes", columns="target_points", values="sign_code").reindex(index=durations, columns=targets)
        figure.add_trace(go.Heatmap(z=delta.values, x=targets, y=durations, zmin=-limit, zmax=limit, colorscale="RdBu", reversescale=True, text=np.round(delta.values, 4), texttemplate="%{text}"), row=row_index, col=1)
        figure.add_trace(go.Heatmap(z=signs.values, x=targets, y=durations, zmin=0, zmax=3, colorscale=[[0,"#9e9e9e"],[0.33,"#d62728"],[0.66,"#1f77b4"],[1,"#2ca02c"]], text=selected.pivot(index="or_minutes", columns="target_points", values="sign_persistence").reindex(index=durations, columns=targets).values, hovertemplate="%{text}<extra></extra>"), row=row_index, col=2)
    figure.update_layout(title=f"{RESEARCH_LABEL}<br>Avg-R change and sign persistence", height=1150, showlegend=False)
    path = output_dir / "gate8a_average_r_delta_and_sign_change.html"
    figure.write_html(path, include_plotlyjs="cdn")
    paths["delta_and_sign"] = path
    return paths


def write_temporal_visualization(temporal: pd.DataFrame, output_dir: Path) -> Path:
    figure = make_subplots(rows=2, cols=1, shared_xaxes=False, subplot_titles=["Rolling 30-observation Avg R", "Rolling 50-observation Avg R"])
    for (partition, entity), group in temporal.groupby(["partition", "entity"], sort=True):
        for row, column in ((1, "rolling_30_average_r"), (2, "rolling_50_average_r")):
            figure.add_trace(go.Scatter(x=group["session_date"], y=group[column], mode="lines", name=f"{partition} | {entity}", legendgroup=f"{partition}-{entity}", showlegend=row == 1), row=row, col=1)
    figure.add_hline(y=0, line_dash="dash", line_color="gray", row="all", col=1)
    figure.update_layout(title=f"{RESEARCH_LABEL}<br>Separate-period temporal diagnostics", height=850)
    path = output_dir / "gate8a_temporal_diagnostics.html"
    figure.write_html(path, include_plotlyjs="cdn")
    return path


def write_width_visualization(width: pd.DataFrame, output_dir: Path) -> Path:
    selected = width.loc[width["analysis_kind"].eq("WITHIN_PERIOD_QUINTILE")]
    aggregate = selected.groupby(["partition", "or_minutes", "width_cell"], as_index=False)["average_r"].mean()
    figure = make_subplots(rows=1, cols=3, subplot_titles=["15m", "20m", "30m"])
    for col, duration in enumerate((15, 20, 30), start=1):
        for partition in ("DEVELOPMENT", "VALIDATION"):
            group = aggregate.loc[(aggregate["or_minutes"] == duration) & (aggregate["partition"] == partition)]
            figure.add_trace(go.Scatter(x=group["width_cell"], y=group["average_r"], mode="lines+markers", name=partition, legendgroup=partition, showlegend=col == 1), row=1, col=col)
        figure.add_hline(y=0, line_dash="dash", line_color="gray", row=1, col=col)
    figure.update_layout(title=f"{RESEARCH_LABEL}<br>Mean surface expectancy by within-period OR-width quintile", height=520)
    path = output_dir / "gate8a_or_width_dev_val.html"
    figure.write_html(path, include_plotlyjs="cdn")
    return path


def csv_ready(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    return output


def write_outputs(
    output_dir: Path,
    *,
    validation_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    migration: pd.DataFrame,
    neighborhoods: pd.DataFrame,
    temporal: pd.DataFrame,
    temporal_findings: pd.DataFrame,
    width: pd.DataFrame,
    price: pd.DataFrame,
    observability: pd.DataFrame,
    classifications: pd.DataFrame,
    metadata: dict[str, Any],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "validation_75_config_summary": validation_summary,
        "dev_val_surface_comparison": comparison,
        "parameter_migration": migration,
        "candidate_neighborhoods": neighborhoods,
        "temporal_diagnostics": temporal,
        "temporal_findings": temporal_findings,
        "or_width_dev_val": width,
        "price_normalization_diagnostic": price,
        "observability_dev_val": observability,
        "hypothesis_classifications": classifications,
    }
    paths = {}
    for name, frame in frames.items():
        path = output_dir / f"gate8a_{name}.csv"
        csv_ready(frame).to_csv(path, index=False)
        paths[name] = path
    paths.update(write_surface_visualizations(comparison, output_dir))
    paths["temporal_html"] = write_temporal_visualization(temporal, output_dir)
    paths["width_html"] = write_width_visualization(width, output_dir)
    metadata_path = output_dir / "gate8a_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    paths["metadata"] = metadata_path
    return paths
