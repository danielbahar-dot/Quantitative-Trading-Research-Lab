"""Causal OR-width state characterization for MNQ ORB V0.2 Stage 3A.

The analysis consumes only the DEVELOPMENT Step-1B breakout-event table and
groups the four frozen, lagged OR-width percentile fields into fixed quintile
bands.  It summarizes existing post-signal excursion outcomes; it does not
create event features, rerun strategy execution, or inspect reserved data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEVELOPMENT_START = pd.Timestamp("2024-06-21")
DEVELOPMENT_END = pd.Timestamp("2025-06-30")
EXPECTED_OR_MINUTES = (15, 20, 30)
LOOKBACKS = (5, 10, 15, 20)
HORIZONS = ("5m", "15m", "30m", "60m", "session_end")
BAND_LABELS = (
    "0.00-0.20",
    "0.20-0.40",
    "0.40-0.60",
    "0.60-0.80",
    "0.80-1.00",
)
BAND_MIDPOINTS = dict(zip(BAND_LABELS, (0.10, 0.30, 0.50, 0.70, 0.90)))
DEV_SEGMENTS = ("FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF")


def assert_development_input_path(path: str | Path) -> None:
    """Reject any path that does not explicitly identify DEVELOPMENT input."""

    text = str(path).replace("\\", "/").lower()
    if "validation" in text or "oos_burned" in text:
        raise ValueError("Reserved Validation/OOS_BURNED input is prohibited")
    if "_dev_" not in text:
        raise ValueError("Stage 3A Step 2 requires an explicitly DEV-labeled input")


def assign_percentile_band(
    values: pd.Series,
    available: pd.Series | None = None,
) -> pd.Series:
    """Assign fixed [lower, upper) quintiles, with 1.00 included in the last."""

    numeric = pd.to_numeric(values, errors="coerce")
    eligible = numeric.notna() & numeric.between(0.0, 1.0, inclusive="both")
    if available is not None:
        eligible &= _boolean_series(available)

    result = pd.Series(pd.NA, index=values.index, dtype="object")
    edges = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    for index, label in enumerate(BAND_LABELS):
        lower, upper = edges[index], edges[index + 1]
        if index == len(BAND_LABELS) - 1:
            mask = eligible & numeric.ge(lower) & numeric.le(upper)
        else:
            mask = eligible & numeric.ge(lower) & numeric.lt(upper)
        result.loc[mask] = label
    return result


def development_half_labels(session_dates: pd.Series) -> tuple[pd.Series, dict[str, Any]]:
    """Split sorted event-bearing dates at floor(n / 2), keeping dates intact."""

    parsed = pd.to_datetime(session_dates, errors="coerce").dt.normalize()
    if parsed.isna().any():
        raise ValueError("session_date contains missing or invalid dates")
    dates = sorted(parsed.unique())
    if len(dates) < 2:
        raise ValueError("At least two DEVELOPMENT dates are required for stability")
    first_count = len(dates) // 2
    first_dates = set(dates[:first_count])
    labels = pd.Series(
        np.where(parsed.isin(first_dates), "DEV_FIRST_HALF", "DEV_SECOND_HALF"),
        index=session_dates.index,
        dtype="object",
    )
    metadata = {
        "unique_event_dates": len(dates),
        "first_half_dates": first_count,
        "second_half_dates": len(dates) - first_count,
        "first_half_start": pd.Timestamp(dates[0]).date().isoformat(),
        "first_half_end": pd.Timestamp(dates[first_count - 1]).date().isoformat(),
        "second_half_start": pd.Timestamp(dates[first_count]).date().isoformat(),
        "second_half_end": pd.Timestamp(dates[-1]).date().isoformat(),
    }
    return labels, metadata


def characterize_or_width(
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return master, stability, direction, relationship, and audit tables."""

    prepared, audit = _prepare_events(events)
    master = _build_summary(
        prepared,
        or_scopes=(*EXPECTED_OR_MINUTES, "ALL"),
        segments=("FULL_DEVELOPMENT",),
        directions=("ALL",),
    )
    stability = _build_summary(
        prepared,
        or_scopes=EXPECTED_OR_MINUTES,
        segments=DEV_SEGMENTS,
        directions=("ALL", "LONG", "SHORT"),
    )
    direction = _build_summary(
        prepared,
        or_scopes=(*EXPECTED_OR_MINUTES, "ALL"),
        segments=("FULL_DEVELOPMENT",),
        directions=("LONG", "SHORT"),
    )
    relationships = summarize_relationships(master, stability)
    audit["relationship_label_counts"] = {
        str(label): int(count)
        for label, count in relationships["classification"].value_counts().items()
    }
    return master, stability, direction, relationships, audit


def summarize_relationships(
    master: pd.DataFrame,
    stability: pd.DataFrame,
) -> pd.DataFrame:
    """Create conservative descriptive labels across all five clean horizons."""

    rows: list[dict[str, Any]] = []
    for lookback in LOOKBACKS:
        for duration in EXPECTED_OR_MINUTES:
            segment_patterns: dict[str, list[tuple[str, str, float]]] = {}
            for segment, table in (
                ("FULL_DEVELOPMENT", master),
                ("DEV_FIRST_HALF", stability),
                ("DEV_SECOND_HALF", stability),
            ):
                horizon_patterns = []
                for horizon in HORIZONS:
                    frame = _ordered_band_slice(
                        table,
                        lookback=lookback,
                        duration=duration,
                        segment=segment,
                        direction="ALL",
                        horizon=horizon,
                    )
                    pattern, rho = _relationship_pattern(frame)
                    horizon_patterns.append((horizon, pattern, rho))
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
            full_30m = _pattern_at_horizon(segment_patterns["FULL_DEVELOPMENT"], "30m")
            first_30m = _pattern_at_horizon(segment_patterns["DEV_FIRST_HALF"], "30m")
            second_30m = _pattern_at_horizon(segment_patterns["DEV_SECOND_HALF"], "30m")
            full = _ordered_band_slice(
                master,
                lookback=lookback,
                duration=duration,
                segment="FULL_DEVELOPMENT",
                direction="ALL",
                horizon="30m",
            )
            first = _ordered_band_slice(
                stability,
                lookback=lookback,
                duration=duration,
                segment="DEV_FIRST_HALF",
                direction="ALL",
                horizon="30m",
            )
            second = _ordered_band_slice(
                stability,
                lookback=lookback,
                duration=duration,
                segment="DEV_SECOND_HALF",
                direction="ALL",
                horizon="30m",
            )
            min_half_band_n = int(
                min(first["event_n"].min(), second["event_n"].min())
            )
            opposite_rho = (
                np.isfinite(first_30m[1])
                and np.isfinite(second_30m[1])
                and abs(first_30m[1]) >= 0.3
                and abs(second_30m[1]) >= 0.3
                and np.sign(first_30m[1]) != np.sign(second_30m[1])
            )
            stable_pattern = (
                full_pattern != "NO_CLEAR_PATTERN"
                and full_pattern == first_pattern == second_pattern
                and min(full_support, first_support, second_support) >= 3
            )
            contradictory_halves = (
                first_support >= 3
                and second_support >= 3
                and first_pattern != second_pattern
            )
            if full_pattern == "NO_CLEAR_PATTERN" and max(
                full_support, first_support, second_support
            ) < 2:
                classification = "NO_CLEAR_RELATIONSHIP"
            elif full_pattern == "NO_CLEAR_PATTERN":
                classification = (
                    "WEAK_OR_UNSTABLE"
                    if opposite_rho or contradictory_halves or first_pattern != second_pattern
                    else "POTENTIALLY_INFORMATIVE"
                )
            elif stable_pattern and min_half_band_n >= 10:
                classification = "CONSISTENT_CANDIDATE_STATE"
            elif opposite_rho or contradictory_halves:
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
                    "lookback_sessions": lookback,
                    "or_minutes": duration,
                    "assessment_horizons": "5m|15m|30m|60m|session_end",
                    "full_pattern": full_pattern,
                    "full_supporting_horizons": full_support,
                    "first_half_pattern": first_pattern,
                    "first_half_supporting_horizons": first_support,
                    "second_half_pattern": second_pattern,
                    "second_half_supporting_horizons": second_support,
                    "full_30m_mfe_band_spearman": full_30m[1],
                    "first_half_30m_mfe_band_spearman": first_30m[1],
                    "second_half_30m_mfe_band_spearman": second_30m[1],
                    "full_median_mfe_range_pct": _numeric_range(full["median_mfe_pct"]),
                    "full_median_mae_range_pct": _numeric_range(full["median_mae_pct"]),
                    "minimum_half_band_n": min_half_band_n,
                    "temporally_opposed_mfe_ordering": bool(opposite_rho),
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
    """Render the concise, guardrailed Stage-3A Step-2 report."""

    eligibility = [
        {
            "Lookback": f"{lookback} sessions",
            "Eligible N": audit["eligible_n_by_lookback"][str(lookback)],
            "Unavailable N": audit["unavailable_n_by_lookback"][str(lookback)],
        }
        for lookback in LOOKBACKS
    ]
    relation_rows = relationships[
        [
            "lookback_sessions",
            "or_minutes",
            "full_pattern",
            "first_half_pattern",
            "second_half_pattern",
            "classification",
        ]
    ].rename(
        columns={
            "lookback_sessions": "Lookback",
            "or_minutes": "OR min",
            "full_pattern": "Full DEV",
            "first_half_pattern": "First half",
            "second_half_pattern": "Second half",
            "classification": "Assessment",
        }
    )

    clean_30m = direction[
        (direction["outcome_horizon"] == "30m")
        & (direction["or_minutes"].astype(str) != "ALL")
    ]
    direction_rows: list[dict[str, Any]] = []
    for (duration, side), group in clean_30m.groupby(
        ["or_minutes", "breakout_direction"], sort=True
    ):
        spans = []
        for lookback, lookback_group in group.groupby("lookback_sessions"):
            spans.append((lookback, _numeric_range(lookback_group["median_mfe_pct"])))
        strongest = max(spans, key=lambda item: item[1])
        direction_rows.append(
            {
                "OR min": duration,
                "Side": side,
                "Largest 30m median-MFE band span": _fmt_pct(strongest[1]),
                "Lookback at that span": strongest[0],
            }
        )

    duration_rows = []
    for duration, group in relationships.groupby("or_minutes", sort=True):
        duration_rows.append(
            {
                "OR min": duration,
                "Median MFE span across lookbacks": _fmt_pct(
                    float(group["full_median_mfe_range_pct"].median())
                ),
                "Assessments": ", ".join(
                    f"{label}={count}"
                    for label, count in group["classification"].value_counts().items()
                ),
            }
        )

    stable = relationships[
        relationships["classification"] == "CONSISTENT_CANDIDATE_STATE"
    ]
    stable_text = (
        "None met the conservative consistency rule."
        if stable.empty
        else ", ".join(
            f"{int(row.lookback_sessions)}-session / {int(row.or_minutes)}m"
            for row in stable.itertuples()
        )
    )
    split = audit["development_split"]
    return f"""# MNQ ORB V0.2 — Stage 3A Step 2 causal OR-width characterization

## Scope and chronology

This is a DEVELOPMENT-only characterization of the four frozen causal OR-width
percentiles in the 935-row Step-1B PRINT breakout-event dataset. It uses only
existing normalized post-signal-bar MFE/MAE outcomes. Signal-bar excursion is
excluded from every clean result because its within-bar chronology is unknown.
No strategy performance, threshold search, filter, preferred lookback, or other
state family is evaluated.

Fixed band boundaries are left-inclusive and right-exclusive:
`[0.00, 0.20)`, `[0.20, 0.40)`, `[0.40, 0.60)`, `[0.60, 0.80)`, with
`[0.80, 1.00]` including 1.00. A row is eligible only when its frozen
availability flag is true and its percentile is present in `[0, 1]`; warm-up
rows remain unavailable and are never backfilled.

## Eligibility

{_markdown_table(pd.DataFrame(eligibility))}

## DEVELOPMENT stability split

The input contains {split['unique_event_dates']} event-bearing session dates.
Dates are sorted chronologically and kept intact: the first
{split['first_half_dates']} dates ({split['first_half_start']} through
{split['first_half_end']}) form `DEV_FIRST_HALF`; the final
{split['second_half_dates']} dates ({split['second_half_start']} through
{split['second_half_end']}) form `DEV_SECOND_HALF`. This replaces the planning
assumption of 248 frozen calendar sessions with the 247 dates actually present
in the authorized breakout-event input.

## Descriptive relationship assessment

The assessment spans all five clean horizons. Within each horizon, extreme
deterioration requires the widest band to have lower median MFE and higher
median MAE than the median of bands 1–4; a monotonic label requires absolute
Spearman ordering of at least 0.70; middle preference requires the largest
median MFE in bands 2–4 and above both extremes. A segment-level pattern must
recur in at least three of five horizons. A state is called consistent only
when the same qualifying pattern appears in full DEV and both halves and every
30m half-band has at least 10 events. These labels are not trading filters.

{_markdown_table(relation_rows)}

Stable across both DEV halves: {stable_text}

## LONG / SHORT context

The table below reports, without selecting a winner, the largest clean 30m
median-MFE band span observed across the four fixed lookbacks for each duration
and side. Full horizon-by-band statistics are in the direction-breakdown CSV.

{_markdown_table(pd.DataFrame(direction_rows))}

## OR-duration context

{_markdown_table(pd.DataFrame(duration_rows))}

## Relation to noncausal Gate 6B.1

Gate 6B.1 used same-sample actual-width ranked quintiles and strategy R metrics,
not lagged causal percentiles and raw post-breakout excursion. It showed a
middle-quintile preference for 15m, mixed 20m behavior, and strongest
widest-quintile strategy metrics for 30m. Step 2 mostly contradicts the earlier
15m middle preference: the stable 10- and 15-session 15m views show higher MFE
with higher causal width percentile. The 20m result partly resembles the earlier
mixed picture because the shorter lookbacks are unstable, although the 15- and
20-session views are consistent. The 30m result partially resembles the earlier
widest-width strength at the 10-session lookback, but the other lookbacks are
mixed or less stable. This is a causal robustness comparison, not a direct
replication, and higher MFE must not be read as strategy expectancy.

## Artifacts and guardrail

The master CSV contains 15m/20m/30m results plus combined secondary context.
The stability CSV contains full/first-half/second-half results for ALL, LONG,
and SHORT. The direction CSV contains full-DEVELOPMENT LONG/SHORT results plus
combined secondary context. All outcome values retain the frozen fractional
percentage convention. No overall Stage 3A completion is claimed.
"""


def _prepare_events(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {
        "session_date",
        "or_minutes",
        "breakout_type",
        "breakout_direction",
    }
    for lookback in LOOKBACKS:
        required.update(
            {
                f"or_width_hist_{lookback}_percentile",
                f"or_width_hist_{lookback}_available",
            }
        )
    for horizon in HORIZONS:
        required.update(
            {
                f"post_signal_bar_{horizon}_complete",
                f"post_signal_bar_{horizon}_mfe_pct",
                f"post_signal_bar_{horizon}_mae_pct",
            }
        )
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError("Step-1B input missing required columns: " + ", ".join(missing))

    output = events.copy()
    dates = pd.to_datetime(output["session_date"], errors="coerce").dt.normalize()
    if dates.isna().any() or not dates.between(DEVELOPMENT_START, DEVELOPMENT_END).all():
        raise ValueError("Input contains rows outside the frozen DEVELOPMENT dates")
    if "partition" in output.columns and not output["partition"].astype(str).str.upper().eq(
        "DEVELOPMENT"
    ).all():
        raise ValueError("Input contains a non-DEVELOPMENT partition")
    if not output["breakout_type"].astype(str).str.upper().eq("PRINT").all():
        raise ValueError("Stage 3A Step 2 accepts PRINT events only")
    directions = set(output["breakout_direction"].astype(str).str.upper())
    if not directions <= {"LONG", "SHORT"}:
        raise ValueError("Unsupported breakout direction")
    durations = set(pd.to_numeric(output["or_minutes"], errors="coerce").dropna().astype(int))
    if durations != set(EXPECTED_OR_MINUTES):
        raise ValueError("Input must contain exactly the 15m, 20m, and 30m OR durations")

    output["or_minutes"] = pd.to_numeric(output["or_minutes"], errors="raise").astype(int)
    output["breakout_direction"] = output["breakout_direction"].astype(str).str.upper()
    output["_dev_half"], split = development_half_labels(output["session_date"])
    eligible_counts: dict[str, int] = {}
    unavailable_counts: dict[str, int] = {}
    for lookback in LOOKBACKS:
        band_column = f"_width_band_{lookback}"
        output[band_column] = assign_percentile_band(
            output[f"or_width_hist_{lookback}_percentile"],
            output[f"or_width_hist_{lookback}_available"],
        )
        eligible_counts[str(lookback)] = int(output[band_column].notna().sum())
        unavailable_counts[str(lookback)] = int(output[band_column].isna().sum())

    audit = {
        "research_scope": "DEVELOPMENT_ONLY",
        "input_rows": int(len(output)),
        "eligible_n_by_lookback": eligible_counts,
        "unavailable_n_by_lookback": unavailable_counts,
        "development_split": split,
        "signal_bar_chronology": "unknown_and_excluded",
        "validation_accessed": False,
        "oos_burned_accessed": False,
    }
    return output, audit


def _build_summary(
    events: pd.DataFrame,
    *,
    or_scopes: Iterable[int | str],
    segments: Iterable[str],
    directions: Iterable[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for lookback in LOOKBACKS:
        band_column = f"_width_band_{lookback}"
        eligible = events[events[band_column].notna()]
        for duration in or_scopes:
            duration_frame = (
                eligible if duration == "ALL" else eligible[eligible["or_minutes"] == duration]
            )
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
                    for band in BAND_LABELS:
                        band_frame = direction_frame[direction_frame[band_column] == band]
                        long_n = int(band_frame["breakout_direction"].eq("LONG").sum())
                        short_n = int(band_frame["breakout_direction"].eq("SHORT").sum())
                        for horizon in HORIZONS:
                            complete = _boolean_series(
                                band_frame[f"post_signal_bar_{horizon}_complete"]
                            )
                            complete_frame = band_frame.loc[complete]
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
                                    "lookback_sessions": lookback,
                                    "or_minutes": duration,
                                    "dev_segment": segment,
                                    "breakout_direction": direction,
                                    "percentile_band": band,
                                    "band_lower_inclusive": BAND_MIDPOINTS[band] - 0.1,
                                    "band_upper": BAND_MIDPOINTS[band] + 0.1,
                                    "upper_inclusive": band == BAND_LABELS[-1],
                                    "outcome_layer": "POST_SIGNAL_BAR_CLEAN",
                                    "outcome_horizon": horizon,
                                    "event_n": int(len(band_frame)),
                                    "share_of_eligible_events": (
                                        float(len(band_frame) / denominator)
                                        if denominator
                                        else np.nan
                                    ),
                                    "long_n": long_n,
                                    "short_n": short_n,
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


def _ordered_band_slice(
    table: pd.DataFrame,
    *,
    lookback: int,
    duration: int,
    segment: str,
    direction: str,
    horizon: str,
) -> pd.DataFrame:
    frame = table[
        (table["lookback_sessions"] == lookback)
        & (table["or_minutes"].astype(str) == str(duration))
        & (table["dev_segment"] == segment)
        & (table["breakout_direction"] == direction)
        & (table["outcome_horizon"] == horizon)
    ].copy()
    frame["_order"] = frame["percentile_band"].map(
        {band: index for index, band in enumerate(BAND_LABELS)}
    )
    return frame.sort_values("_order").reset_index(drop=True)


def _relationship_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    mfe = pd.to_numeric(frame["median_mfe_pct"], errors="coerce").to_numpy(dtype=float)
    mae = pd.to_numeric(frame["median_mae_pct"], errors="coerce").to_numpy(dtype=float)
    if len(mfe) != 5 or not np.isfinite(mfe).all() or not np.isfinite(mae).all():
        return "NO_CLEAR_PATTERN", np.nan
    rho = float(pd.Series(np.arange(5)).corr(pd.Series(mfe), method="spearman"))
    widest_deteriorates = mfe[-1] < np.median(mfe[:-1]) and mae[-1] > np.median(mae[:-1])
    if widest_deteriorates:
        return "EXTREME_WIDTH_DETERIORATION", rho
    if rho >= 0.70:
        return "MONOTONIC_HIGHER_WIDTH_MORE_MFE", rho
    if rho <= -0.70:
        return "MONOTONIC_HIGHER_WIDTH_LESS_MFE", rho
    peak = int(np.argmax(mfe))
    if peak in {1, 2, 3} and mfe[peak] > mfe[0] and mfe[peak] > mfe[-1]:
        return "MIDDLE_RANGE_PREFERENCE", rho
    return "NO_CLEAR_PATTERN", rho


def _dominant_pattern(patterns: list[tuple[str, str, float]]) -> tuple[str, int]:
    counts: dict[str, int] = {}
    for _, pattern, _ in patterns:
        if pattern != "NO_CLEAR_PATTERN":
            counts[pattern] = counts.get(pattern, 0) + 1
    if not counts:
        return "NO_CLEAR_PATTERN", 0
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    pattern, support = ordered[0]
    return (pattern, support) if support >= 2 else ("NO_CLEAR_PATTERN", support)


def _pattern_at_horizon(
    patterns: list[tuple[str, str, float]], horizon: str
) -> tuple[str, float]:
    for item_horizon, pattern, rho in patterns:
        if item_horizon == horizon:
            return pattern, rho
    raise ValueError(f"Missing horizon pattern: {horizon}")


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
