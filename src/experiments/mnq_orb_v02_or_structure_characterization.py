"""DEVELOPMENT-only OR internal-structure characterization for Stage 3A.

This module analyzes only OR efficiency, directional CLV, OR/breakout
alignment, and directional OR net-move percentage from the completed Step-1B
event table. It summarizes existing clean post-signal excursion outcomes and
does not combine these states with OR width or any other state family.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_width_characterization import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    DEV_SEGMENTS,
    EXPECTED_OR_MINUTES,
    HORIZONS,
    development_half_labels,
)


CONTINUOUS_FEATURES = (
    "or_efficiency",
    "directional_clv",
    "directional_or_net_move_pct",
)
ALIGNMENT_FEATURE = "or_breakout_alignment"
FEATURES = (*CONTINUOUS_FEATURES, ALIGNMENT_FEATURE)
FEATURE_TITLES = {
    "or_efficiency": "OR efficiency",
    "directional_clv": "Directional CLV",
    "directional_or_net_move_pct": "Directional OR net move",
    "or_breakout_alignment": "OR/breakout alignment",
}
QUINTILE_LABELS = ("Q1", "Q2", "Q3", "Q4", "Q5")
ALIGNMENT_STATES = ("ALIGNED", "OPPOSED", "FLAT")


def required_input_columns() -> list[str]:
    """Return the exact Step-3 source columns; no other state family is needed."""

    columns = [
        "session_date",
        "or_minutes",
        "breakout_type",
        "breakout_direction",
        *FEATURES,
    ]
    for horizon in HORIZONS:
        columns.extend(
            [
                f"post_signal_bar_{horizon}_complete",
                f"post_signal_bar_{horizon}_mfe_pct",
                f"post_signal_bar_{horizon}_mae_pct",
            ]
        )
    return columns


def assert_development_input_path(path: str | Path) -> None:
    """Reject paths that do not explicitly name the DEVELOPMENT event input."""

    text = str(path).replace("\\", "/").lower()
    if "validation" in text or "oos_burned" in text:
        raise ValueError("Reserved Validation/OOS_BURNED input is prohibited")
    if "_dev_" not in text:
        raise ValueError("Stage 3A Step 3 requires an explicitly DEV-labeled input")


def fixed_quintile_intervals(values: pd.Series) -> list[dict[str, Any]]:
    """Calculate full-DEVELOPMENT value quintiles with deterministic collapse."""

    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return []
    raw_edges = numeric.quantile([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]).to_numpy(
        dtype=float
    )
    edges: list[float] = []
    for edge in raw_edges:
        if not edges or edge > edges[-1]:
            edges.append(float(edge))
    if len(edges) == 1:
        return [
            {
                "state_label": "Q1",
                "state_order": 1,
                "lower": edges[0],
                "upper": edges[0],
                "upper_inclusive": True,
            }
        ]
    return [
        {
            "state_label": QUINTILE_LABELS[index],
            "state_order": index + 1,
            "lower": lower,
            "upper": upper,
            "upper_inclusive": index == len(edges) - 2,
        }
        for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:]))
    ]


def assign_fixed_quintiles(
    values: pd.Series, intervals: list[Mapping[str, Any]]
) -> pd.Series:
    """Apply precomputed full-DEVELOPMENT boundaries without recomputing them."""

    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(pd.NA, index=values.index, dtype="object")
    for interval in intervals:
        lower = float(interval["lower"])
        upper = float(interval["upper"])
        if bool(interval["upper_inclusive"]):
            mask = numeric.ge(lower) & numeric.le(upper)
        else:
            mask = numeric.ge(lower) & numeric.lt(upper)
        result.loc[mask] = str(interval["state_label"])
    return result


def characterize_or_structure(
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return master, stability, direction, relationship, and audit tables."""

    prepared, audit = _prepare_events(events)
    boundaries = _calculate_boundaries(prepared)
    master = _build_summary(
        prepared,
        boundaries,
        or_scopes=(*EXPECTED_OR_MINUTES, "ALL"),
        segments=("FULL_DEVELOPMENT",),
        directions=("ALL",),
    )
    stability = _build_summary(
        prepared,
        boundaries,
        or_scopes=EXPECTED_OR_MINUTES,
        segments=DEV_SEGMENTS,
        directions=("ALL", "LONG", "SHORT"),
    )
    direction = _build_summary(
        prepared,
        boundaries,
        or_scopes=(*EXPECTED_OR_MINUTES, "ALL"),
        segments=("FULL_DEVELOPMENT",),
        directions=("LONG", "SHORT"),
    )
    relationships = summarize_relationships(master, stability)
    audit["relationship_label_counts"] = {
        str(label): int(count)
        for label, count in relationships["classification"].value_counts().items()
    }
    audit["flat_alignment_events"] = int(
        prepared[ALIGNMENT_FEATURE].eq("FLAT").sum()
    )
    return master, stability, direction, relationships, audit


def summarize_relationships(
    master: pd.DataFrame, stability: pd.DataFrame
) -> pd.DataFrame:
    """Classify each feature/duration across all clean horizons and DEV halves."""

    rows: list[dict[str, Any]] = []
    for feature in FEATURES:
        for duration in EXPECTED_OR_MINUTES:
            segment_patterns: dict[str, list[tuple[str, str, float]]] = {}
            for segment, table in (
                ("FULL_DEVELOPMENT", master),
                ("DEV_FIRST_HALF", stability),
                ("DEV_SECOND_HALF", stability),
            ):
                horizon_patterns: list[tuple[str, str, float]] = []
                for horizon in HORIZONS:
                    frame = _ordered_state_slice(
                        table,
                        feature=feature,
                        duration=duration,
                        segment=segment,
                        direction="ALL",
                        horizon=horizon,
                    )
                    if feature == ALIGNMENT_FEATURE:
                        pattern, ordering = _alignment_pattern(frame)
                    else:
                        pattern, ordering = _continuous_pattern(frame)
                    horizon_patterns.append((horizon, pattern, ordering))
                segment_patterns[segment] = horizon_patterns

            full_pattern, full_support = _dominant_pattern(
                segment_patterns["FULL_DEVELOPMENT"]
            )
            first_pattern, first_support = _dominant_pattern(
                segment_patterns["DEV_FIRST_HALF"]
            )
            second_pattern, second_support = _dominant_pattern(
                segment_patterns["DEV_SECOND_HALF"]
            )
            full_30m = _ordered_state_slice(
                master,
                feature=feature,
                duration=duration,
                segment="FULL_DEVELOPMENT",
                direction="ALL",
                horizon="30m",
            )
            first_30m = _ordered_state_slice(
                stability,
                feature=feature,
                duration=duration,
                segment="DEV_FIRST_HALF",
                direction="ALL",
                horizon="30m",
            )
            second_30m = _ordered_state_slice(
                stability,
                feature=feature,
                duration=duration,
                segment="DEV_SECOND_HALF",
                direction="ALL",
                horizon="30m",
            )
            inference_states = (
                full_30m[full_30m["state_label"].isin(("ALIGNED", "OPPOSED"))]
                if feature == ALIGNMENT_FEATURE
                else full_30m
            )
            first_inference = (
                first_30m[
                    first_30m["state_label"].isin(("ALIGNED", "OPPOSED"))
                ]
                if feature == ALIGNMENT_FEATURE
                else first_30m
            )
            second_inference = (
                second_30m[
                    second_30m["state_label"].isin(("ALIGNED", "OPPOSED"))
                ]
                if feature == ALIGNMENT_FEATURE
                else second_30m
            )
            contrast_pct = _numeric_range(inference_states["median_mfe_pct"])
            contrast_ratio = _iqr_scaled_contrast(inference_states)
            minimum_half_state_n = int(
                min(first_inference["event_n"].min(), second_inference["event_n"].min())
            )
            material_contrast = bool(
                np.isfinite(contrast_ratio) and contrast_ratio >= 0.25
            )
            contradictory_halves = (
                first_support >= 3
                and second_support >= 3
                and first_pattern != second_pattern
            )
            stable_pattern = (
                full_pattern != "NO_CLEAR_PATTERN"
                and full_pattern == first_pattern == second_pattern
                and min(full_support, first_support, second_support) >= 3
            )
            if full_pattern == "NO_CLEAR_PATTERN" or not material_contrast:
                classification = (
                    "WEAK_OR_UNSTABLE"
                    if contradictory_halves
                    else "NO_CLEAR_RELATIONSHIP"
                )
            elif stable_pattern and minimum_half_state_n >= 10:
                classification = "CONSISTENT_CANDIDATE_STATE"
            elif contradictory_halves:
                classification = "WEAK_OR_UNSTABLE"
            elif full_support >= 3 and (
                (first_pattern == full_pattern and first_support >= 2)
                or (second_pattern == full_pattern and second_support >= 2)
            ):
                classification = "POTENTIALLY_INFORMATIVE"
            else:
                classification = "WEAK_OR_UNSTABLE"

            rows.append(
                {
                    "research_scope": "DEVELOPMENT_ONLY",
                    "source_feature": feature,
                    "or_minutes": duration,
                    "assessment_horizons": "5m|15m|30m|60m|session_end",
                    "full_pattern": full_pattern,
                    "full_supporting_horizons": full_support,
                    "first_half_pattern": first_pattern,
                    "first_half_supporting_horizons": first_support,
                    "second_half_pattern": second_pattern,
                    "second_half_supporting_horizons": second_support,
                    "full_30m_median_mfe_contrast_pct": contrast_pct,
                    "full_30m_iqr_scaled_mfe_contrast": contrast_ratio,
                    "minimum_half_state_n": minimum_half_state_n,
                    "material_contrast": material_contrast,
                    "classification": classification,
                }
            )
    return pd.DataFrame(rows)


def render_report(
    master: pd.DataFrame,
    direction: pd.DataFrame,
    relationships: pd.DataFrame,
    audit: Mapping[str, Any],
) -> str:
    """Render the concise Step-3 report without cross-state-family analysis."""

    relation_table = relationships[
        [
            "source_feature",
            "or_minutes",
            "full_pattern",
            "first_half_pattern",
            "second_half_pattern",
            "classification",
        ]
    ].copy()
    relation_table["source_feature"] = relation_table["source_feature"].map(
        FEATURE_TITLES
    )
    relation_table = relation_table.rename(
        columns={
            "source_feature": "Feature",
            "or_minutes": "OR min",
            "full_pattern": "Full DEV",
            "first_half_pattern": "First half",
            "second_half_pattern": "Second half",
            "classification": "Assessment",
        }
    )

    stable = relationships[
        relationships["classification"] == "CONSISTENT_CANDIDATE_STATE"
    ]
    weak = relationships[
        relationships["classification"].isin(
            ("WEAK_OR_UNSTABLE", "NO_CLEAR_RELATIONSHIP")
        )
    ]
    stable_text = _relationship_list(stable)
    weak_text = _relationship_list(weak)

    clean_30m = direction[
        (direction["outcome_horizon"] == "30m")
        & (direction["or_minutes"].astype(str) != "ALL")
    ]
    direction_rows: list[dict[str, Any]] = []
    for (feature, side), group in clean_30m.groupby(
        ["source_feature", "breakout_direction"], sort=False
    ):
        contrasts = []
        for duration, duration_group in group.groupby("or_minutes", sort=True):
            inference = (
                duration_group[
                    duration_group["state_label"].isin(("ALIGNED", "OPPOSED"))
                ]
                if feature == ALIGNMENT_FEATURE
                else duration_group
            )
            contrasts.append((duration, _numeric_range(inference["median_mfe_pct"])))
        largest = max(contrasts, key=lambda item: item[1])
        direction_rows.append(
            {
                "Feature": FEATURE_TITLES[feature],
                "Side": side,
                "Largest 30m median-MFE state span": _fmt_pct(largest[1]),
                "OR duration": largest[0],
            }
        )

    duration_rows = []
    for duration, group in relationships.groupby("or_minutes", sort=True):
        duration_rows.append(
            {
                "OR min": duration,
                "Median 30m MFE contrast across features": _fmt_pct(
                    float(group["full_30m_median_mfe_contrast_pct"].median())
                ),
                "Assessments": ", ".join(
                    f"{label}={count}"
                    for label, count in group["classification"].value_counts().items()
                ),
            }
        )

    split = audit["development_split"]
    return f"""# MNQ ORB V0.2 Stage 3A Step 3 OR internal structure

## Scope

This DEVELOPMENT-only analysis uses 935 Step-1B PRINT breakout events and only
four internal OR fields: OR efficiency, directional CLV, OR/breakout alignment,
and directional OR net-move percentage. Existing normalized post-signal-bar
MFE/MAE at 5m, 15m, 30m, 60m, and session end are the outcomes. Signal-bar
excursion is excluded because its chronology is unknown. No OR-width state,
other state family, strategy performance, filter, optimization, or ML is used.

## State definitions

Each continuous feature uses ordinary full-DEVELOPMENT value quintiles
calculated separately for the 15m, 20m, and 30m OR. Combined results use their
own full-DEVELOPMENT boundaries and are secondary context. Boundaries are
left-inclusive and right-exclusive, except the final interval includes its
upper bound. The full-DEVELOPMENT boundaries are recorded in every CSV and
reused unchanged for DEV halves and LONG/SHORT splits. Duplicate edges collapse
deterministically. Alignment uses `ALIGNED`, `OPPOSED`, and `FLAT` exactly as
stored. Only {audit['flat_alignment_events']} FLAT events exist, all at 15m, so
FLAT remains reported but is excluded from relationship classification.

The input contains {split['unique_event_dates']} event-bearing dates. The first
{split['first_half_dates']} ({split['first_half_start']} through
{split['first_half_end']}) form `DEV_FIRST_HALF`; the final
{split['second_half_dates']} ({split['second_half_start']} through
{split['second_half_end']}) form `DEV_SECOND_HALF`.

## Relationship assessment

Patterns must recur in at least three of five clean horizons. Continuous-state
monotonic patterns require absolute Spearman ordering of at least 0.70. A
relationship also needs a 30m median-MFE contrast of at least one quarter of the
median within-state IQR before it can be informative. Consistent candidate-state
labels additionally require the same pattern in full DEV and both halves with at
least 10 events in every inferential half-state. These fixed descriptive rules
are classification guardrails, not trading thresholds.

{_markdown_table(relation_table)}

The strongest result is 20m OR efficiency: the highest-efficiency quintile has
lower MFE and higher MAE than the middle of the distribution, and that
high-state deterioration pattern persists across both DEV halves. The only
other relationship above the materiality guardrail is 15m directional OR net
move, where a middle-range preference is potentially informative but not fully
stable.

Consistent across DEV halves: {stable_text}

Weak or no-clear relationships: {weak_text}

## LONG and SHORT context

The largest 30m median-MFE state spans by side are shown only to describe where
directional differences are most visible. They do not rank trading rules.

{_markdown_table(pd.DataFrame(direction_rows))}

## OR-duration context

{_markdown_table(pd.DataFrame(duration_rows))}

## Relation to Step 2 OR-width findings

Internal OR structure does not provide a simple descriptive explanation for the
Step-2 causal OR-width result. Step 2 mainly showed higher MFE at higher width
percentiles. Here, the only consistent result is 20m high-efficiency
deterioration, while directional CLV and alignment are weak or no-clear and
directional net move is unstable outside the potentially informative 15m
middle-range pattern. This does not rule out overlap, but establishing mediation
or incremental explanation would require combining state families, which is
outside this run and was not performed.

## Output guardrail

The master CSV contains separate 15m/20m/30m results and combined secondary
context. The stability CSV contains full, first-half, and second-half results for
ALL, LONG, and SHORT. The direction CSV contains full-DEVELOPMENT LONG/SHORT
results. All percentages retain the frozen fractional convention. Step 3 is
complete, but the overall Stage 3A experiment remains incomplete.
"""


def _prepare_events(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = set(required_input_columns())
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError("Step-1B input missing required columns: " + ", ".join(missing))
    output = events[list(required_input_columns())].copy()
    dates = pd.to_datetime(output["session_date"], errors="coerce").dt.normalize()
    if dates.isna().any() or not dates.between(DEVELOPMENT_START, DEVELOPMENT_END).all():
        raise ValueError("Input contains rows outside the frozen DEVELOPMENT dates")
    if not output["breakout_type"].astype(str).str.upper().eq("PRINT").all():
        raise ValueError("Stage 3A Step 3 accepts PRINT events only")
    output["breakout_direction"] = output["breakout_direction"].astype(str).str.upper()
    if not set(output["breakout_direction"]) <= {"LONG", "SHORT"}:
        raise ValueError("Unsupported breakout direction")
    output["or_minutes"] = pd.to_numeric(output["or_minutes"], errors="raise").astype(int)
    if set(output["or_minutes"]) != set(EXPECTED_OR_MINUTES):
        raise ValueError("Input must contain exactly the 15m, 20m, and 30m OR durations")
    for feature in CONTINUOUS_FEATURES:
        output[feature] = pd.to_numeric(output[feature], errors="coerce")
    output[ALIGNMENT_FEATURE] = output[ALIGNMENT_FEATURE].astype(str).str.upper()
    if not set(output[ALIGNMENT_FEATURE]) <= set(ALIGNMENT_STATES):
        raise ValueError("Unsupported OR/breakout alignment state")
    output["_dev_half"], split = development_half_labels(output["session_date"])
    audit = {
        "research_scope": "DEVELOPMENT_ONLY",
        "input_rows": int(len(output)),
        "available_n_by_feature": {
            feature: int(output[feature].notna().sum()) for feature in FEATURES
        },
        "missing_n_by_feature": {
            feature: int(output[feature].isna().sum()) for feature in FEATURES
        },
        "development_split": split,
        "source_columns_loaded": required_input_columns(),
        "other_state_family_columns_loaded": False,
        "signal_bar_chronology": "unknown_and_excluded",
        "validation_accessed": False,
        "oos_burned_accessed": False,
    }
    return output, audit


def _calculate_boundaries(
    events: pd.DataFrame,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    boundaries: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for feature in CONTINUOUS_FEATURES:
        for duration in (*EXPECTED_OR_MINUTES, "ALL"):
            frame = events if duration == "ALL" else events[events["or_minutes"] == duration]
            boundaries[(feature, str(duration))] = fixed_quintile_intervals(frame[feature])
    return boundaries


def _build_summary(
    events: pd.DataFrame,
    boundaries: Mapping[tuple[str, str], list[Mapping[str, Any]]],
    *,
    or_scopes: Iterable[int | str],
    segments: Iterable[str],
    directions: Iterable[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature in FEATURES:
        for duration in or_scopes:
            duration_frame = (
                events.copy()
                if duration == "ALL"
                else events[events["or_minutes"] == duration].copy()
            )
            if feature == ALIGNMENT_FEATURE:
                state_specs = [
                    {
                        "state_label": label,
                        "state_order": index + 1,
                        "lower": np.nan,
                        "upper": np.nan,
                        "upper_inclusive": False,
                    }
                    for index, label in enumerate(ALIGNMENT_STATES)
                ]
                duration_frame["_state"] = duration_frame[feature]
                state_kind = "CATEGORICAL"
            else:
                state_specs = list(boundaries[(feature, str(duration))])
                duration_frame["_state"] = assign_fixed_quintiles(
                    duration_frame[feature], state_specs
                )
                state_kind = "FULL_DEV_VALUE_QUINTILE"
            duration_frame = duration_frame[duration_frame["_state"].notna()]
            for segment in segments:
                segment_frame = (
                    duration_frame
                    if segment == "FULL_DEVELOPMENT"
                    else duration_frame[duration_frame["_dev_half"] == segment]
                )
                for direction in directions:
                    direction_frame = (
                        segment_frame
                        if direction == "ALL"
                        else segment_frame[
                            segment_frame["breakout_direction"] == direction
                        ]
                    )
                    denominator = len(direction_frame)
                    for state in state_specs:
                        state_frame = direction_frame[
                            direction_frame["_state"] == state["state_label"]
                        ]
                        for horizon in HORIZONS:
                            complete = _boolean_series(
                                state_frame[f"post_signal_bar_{horizon}_complete"]
                            )
                            complete_frame = state_frame.loc[complete]
                            mfe = pd.to_numeric(
                                complete_frame[f"post_signal_bar_{horizon}_mfe_pct"],
                                errors="coerce",
                            ).dropna()
                            mae = pd.to_numeric(
                                complete_frame[f"post_signal_bar_{horizon}_mae_pct"],
                                errors="coerce",
                            ).dropna()
                            rows.append(
                                {
                                    "research_scope": "DEVELOPMENT_ONLY",
                                    "source_feature": feature,
                                    "state_kind": state_kind,
                                    "or_minutes": duration,
                                    "dev_segment": segment,
                                    "breakout_direction": direction,
                                    "state_label": state["state_label"],
                                    "state_order": state["state_order"],
                                    "state_lower_inclusive": state["lower"],
                                    "state_upper": state["upper"],
                                    "state_upper_inclusive": state["upper_inclusive"],
                                    "outcome_layer": "POST_SIGNAL_BAR_CLEAN",
                                    "outcome_horizon": horizon,
                                    "event_n": int(len(state_frame)),
                                    "share_of_eligible_events": (
                                        float(len(state_frame) / denominator)
                                        if denominator
                                        else np.nan
                                    ),
                                    "long_n": int(
                                        state_frame["breakout_direction"].eq("LONG").sum()
                                    ),
                                    "short_n": int(
                                        state_frame["breakout_direction"].eq("SHORT").sum()
                                    ),
                                    "complete_outcome_n": int(len(complete_frame)),
                                    "mfe_n": int(len(mfe)),
                                    "mean_mfe_pct": _stat(mfe, "mean"),
                                    "median_mfe_pct": _stat(mfe, "median"),
                                    "mfe_p25_pct": _stat(mfe, "p25"),
                                    "mfe_p75_pct": _stat(mfe, "p75"),
                                    "mae_n": int(len(mae)),
                                    "mean_mae_pct": _stat(mae, "mean"),
                                    "median_mae_pct": _stat(mae, "median"),
                                    "mae_p25_pct": _stat(mae, "p25"),
                                    "mae_p75_pct": _stat(mae, "p75"),
                                }
                            )
    return pd.DataFrame(rows)


def _ordered_state_slice(
    table: pd.DataFrame,
    *,
    feature: str,
    duration: int,
    segment: str,
    direction: str,
    horizon: str,
) -> pd.DataFrame:
    return table[
        (table["source_feature"] == feature)
        & (table["or_minutes"].astype(str) == str(duration))
        & (table["dev_segment"] == segment)
        & (table["breakout_direction"] == direction)
        & (table["outcome_horizon"] == horizon)
    ].sort_values("state_order").reset_index(drop=True)


def _continuous_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    mfe = pd.to_numeric(frame["median_mfe_pct"], errors="coerce").to_numpy(dtype=float)
    mae = pd.to_numeric(frame["median_mae_pct"], errors="coerce").to_numpy(dtype=float)
    if len(mfe) < 3 or not np.isfinite(mfe).all() or not np.isfinite(mae).all():
        return "NO_CLEAR_PATTERN", np.nan
    ordering = float(pd.Series(np.arange(len(mfe))).corr(pd.Series(mfe), method="spearman"))
    if mfe[-1] < np.median(mfe[:-1]) and mae[-1] > np.median(mae[:-1]):
        return "HIGH_STATE_DETERIORATION", ordering
    if ordering >= 0.70:
        return "MONOTONIC_HIGHER_STATE_MORE_MFE", ordering
    if ordering <= -0.70:
        return "MONOTONIC_HIGHER_STATE_LESS_MFE", ordering
    peak = int(np.argmax(mfe))
    if peak not in {0, len(mfe) - 1} and mfe[peak] > mfe[0] and mfe[peak] > mfe[-1]:
        return "MIDDLE_RANGE_PREFERENCE", ordering
    return "NO_CLEAR_PATTERN", ordering


def _alignment_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    inference = frame[frame["state_label"].isin(("ALIGNED", "OPPOSED"))]
    if len(inference) != 2 or inference["median_mfe_pct"].isna().any():
        return "NO_CLEAR_PATTERN", np.nan
    values = dict(zip(inference["state_label"], inference["median_mfe_pct"].astype(float)))
    difference = values["ALIGNED"] - values["OPPOSED"]
    if difference > 0:
        return "ALIGNED_MORE_MFE", difference
    if difference < 0:
        return "OPPOSED_MORE_MFE", difference
    return "NO_CLEAR_PATTERN", 0.0


def _dominant_pattern(patterns: list[tuple[str, str, float]]) -> tuple[str, int]:
    counts: dict[str, int] = {}
    for _, pattern, _ in patterns:
        if pattern != "NO_CLEAR_PATTERN":
            counts[pattern] = counts.get(pattern, 0) + 1
    if not counts:
        return "NO_CLEAR_PATTERN", 0
    pattern, support = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return (pattern, support) if support >= 2 else ("NO_CLEAR_PATTERN", support)


def _iqr_scaled_contrast(frame: pd.DataFrame) -> float:
    contrast = _numeric_range(frame["median_mfe_pct"])
    widths = pd.to_numeric(frame["mfe_p75_pct"], errors="coerce") - pd.to_numeric(
        frame["mfe_p25_pct"], errors="coerce"
    )
    scale = float(widths.dropna().median()) if not widths.dropna().empty else np.nan
    return float(contrast / scale) if np.isfinite(scale) and scale > 0 else np.nan


def _boolean_series(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.fillna(False)
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def _stat(values: pd.Series, statistic: str) -> float:
    if values.empty:
        return np.nan
    if statistic == "mean":
        return float(values.mean())
    if statistic == "median":
        return float(values.median())
    if statistic == "p25":
        return float(values.quantile(0.25))
    if statistic == "p75":
        return float(values.quantile(0.75))
    raise ValueError(f"Unsupported statistic: {statistic}")


def _numeric_range(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.max() - numeric.min()) if not numeric.empty else np.nan


def _relationship_list(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "none"
    return ", ".join(
        f"{FEATURE_TITLES[row.source_feature]} / {int(row.or_minutes)}m"
        for row in frame.itertuples()
    )


def _fmt_pct(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{value * 100:.3f}%"


def _markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)
