"""Stage 3C predeclared 20-minute ORB combined-state hypothesis test.

This module consumes only the canonical DEVELOPMENT Stage-3A PRINT-event
dataset.  It combines the already-frozen causal OR-width percentile bands with
the full-DEVELOPMENT 20-minute OR-efficiency quintiles recorded in Stage 3A
Step 3.  It does not alter signals, execution, or reserved partitions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_or_structure_characterization import (
    assign_fixed_quintiles,
)
from src.experiments.mnq_orb_v02_width_characterization import (
    BAND_LABELS,
    HORIZONS,
    LOOKBACKS,
    assign_percentile_band,
    development_half_labels,
)


EXPERIMENT_ID = "mnq_orb_v0_2_stage3c_combined_state_hypothesis"
HYPOTHESIS_ID = "HYP-ORB-STATE-01"
DEVELOPMENT_START = pd.Timestamp("2024-06-21")
DEVELOPMENT_END = pd.Timestamp("2025-06-30")
EXPECTED_OR_MINUTES = 20
STATE_GROUPS = (
    "WIDTH_ELEVATED_NOT_MAX_EFFICIENCY",
    "WIDTH_ELEVATED_MAX_EFFICIENCY",
    "WIDTH_NOT_ELEVATED",
)
STATE_ORDER = {state: index + 1 for index, state in enumerate(STATE_GROUPS)}
PRIMARY_HORIZONS = ("30m", "60m")
DEV_SEGMENTS = ("FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF")
MIN_REPORTING_N = 10


def assert_development_input_path(path: str | Path) -> None:
    """Reject reserved or non-DEVELOPMENT input paths."""

    text = str(path).replace("\\", "/").lower()
    if "validation" in text or "oos_burned" in text:
        raise ValueError("Reserved Validation/OOS_BURNED input is prohibited")
    if "_dev_" not in text and "development" not in text:
        raise ValueError("Stage 3C requires an explicitly DEVELOPMENT-labeled input")


def required_input_columns() -> list[str]:
    """Return the narrow canonical input projection used by this test."""

    columns = [
        "session_date",
        "contract",
        "or_minutes",
        "breakout_type",
        "breakout_direction",
        "or_efficiency",
    ]
    for lookback in LOOKBACKS:
        columns.extend(
            [
                f"or_width_hist_{lookback}_percentile",
                f"or_width_hist_{lookback}_available",
            ]
        )
    for horizon in HORIZONS:
        columns.extend(
            [
                f"post_signal_bar_{horizon}_complete",
                f"post_signal_bar_{horizon}_mfe_pct",
                f"post_signal_bar_{horizon}_mae_pct",
            ]
        )
    return columns


def efficiency_intervals_from_step3(step3: pd.DataFrame) -> list[dict[str, Any]]:
    """Extract the exact 20m full-DEV OR-efficiency quintiles from Step 3."""

    required = {
        "source_feature",
        "or_minutes",
        "dev_segment",
        "breakout_direction",
        "state_label",
        "state_order",
        "state_lower_inclusive",
        "state_upper",
        "state_upper_inclusive",
    }
    missing = sorted(required - set(step3.columns))
    if missing:
        raise ValueError("Step-3 boundary source missing columns: " + ", ".join(missing))
    frame = step3.loc[
        step3["source_feature"].eq("or_efficiency")
        & step3["or_minutes"].astype(str).eq("20")
        & step3["dev_segment"].eq("FULL_DEVELOPMENT")
        & step3["breakout_direction"].eq("ALL")
    ].copy()
    fields = [
        "state_label",
        "state_order",
        "state_lower_inclusive",
        "state_upper",
        "state_upper_inclusive",
    ]
    unique = frame[fields].drop_duplicates().sort_values("state_order")
    if unique["state_label"].tolist() != ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        raise ValueError("Step-3 source does not contain exactly Q1-Q5 for 20m efficiency")
    intervals = []
    for row in unique.itertuples(index=False):
        intervals.append(
            {
                "state_label": str(row.state_label),
                "state_order": int(row.state_order),
                "lower": float(row.state_lower_inclusive),
                "upper": float(row.state_upper),
                "upper_inclusive": _as_bool(row.state_upper_inclusive),
            }
        )
    if intervals[-1]["upper_inclusive"] is not True:
        raise ValueError("Step-3 Q5 upper boundary must be inclusive")
    if any(item["upper_inclusive"] for item in intervals[:-1]):
        raise ValueError("Only Step-3 Q5 may include its upper boundary")
    return intervals


def assign_combined_states(
    width_percentile: pd.Series,
    width_available: pd.Series,
    efficiency: pd.Series,
    efficiency_intervals: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Assign the three and only three predeclared combined-state groups."""

    width_band = assign_percentile_band(width_percentile, width_available)
    efficiency_quintile = assign_fixed_quintiles(
        pd.to_numeric(efficiency, errors="coerce"), list(efficiency_intervals)
    )
    state = pd.Series(pd.NA, index=width_percentile.index, dtype="object")
    not_elevated = width_band.isin(BAND_LABELS[:3])
    elevated = width_band.isin(BAND_LABELS[3:])
    state.loc[not_elevated] = "WIDTH_NOT_ELEVATED"
    state.loc[elevated & efficiency_quintile.eq("Q5")] = (
        "WIDTH_ELEVATED_MAX_EFFICIENCY"
    )
    state.loc[elevated & efficiency_quintile.isin(("Q1", "Q2", "Q3", "Q4"))] = (
        "WIDTH_ELEVATED_NOT_MAX_EFFICIENCY"
    )
    return pd.DataFrame(
        {
            "width_band": width_band,
            "efficiency_quintile": efficiency_quintile,
            "combined_state": state,
        }
    )


def characterize_combined_state(
    events: pd.DataFrame,
    efficiency_intervals: Iterable[Mapping[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return master, stability, direction, assessment, and audit outputs."""

    prepared, audit = _prepare_events(events, list(efficiency_intervals))
    master = _build_summary(
        prepared,
        segments=("FULL_DEVELOPMENT",),
        directions=("ALL",),
    )
    stability = _build_summary(
        prepared,
        segments=DEV_SEGMENTS,
        directions=("ALL", "LONG", "SHORT"),
    )
    direction = _build_summary(
        prepared,
        segments=("FULL_DEVELOPMENT",),
        directions=("LONG", "SHORT"),
    )
    assessment, classification, recommendation = assess_hypothesis(
        prepared, master, stability, direction
    )
    audit.update(
        {
            "hypothesis_classification": classification,
            "orb_research_disposition": recommendation,
            "promotion_ready_lookbacks": int(assessment["promotion_ready"].sum()),
            "combined_more_interpretable_lookbacks": int(
                assessment["combined_more_interpretable_than_width_alone"].sum()
            ),
        }
    )
    return master, stability, direction, assessment, audit


def assess_hypothesis(
    prepared: pd.DataFrame,
    master: pd.DataFrame,
    stability: pd.DataFrame,
    direction: pd.DataFrame,
) -> tuple[pd.DataFrame, str, str]:
    """Apply fixed, conservative promotion guardrails across the four lookbacks."""

    rows: list[dict[str, Any]] = []
    for lookback in LOOKBACKS:
        horizon_metrics: dict[str, dict[str, float]] = {}
        for horizon in PRIMARY_HORIZONS:
            values = {}
            for state in STATE_GROUPS:
                row = _summary_row(
                    master,
                    lookback=lookback,
                    segment="FULL_DEVELOPMENT",
                    direction="ALL",
                    horizon=horizon,
                    state=state,
                )
                values[state] = row
            primary = values[STATE_GROUPS[0]]
            max_efficiency = values[STATE_GROUPS[1]]
            comparison = values[STATE_GROUPS[2]]
            width_only_mfe = _width_only_median(
                prepared, lookback, "FULL_DEVELOPMENT", "ALL", horizon, True, "mfe"
            )
            width_only_mae = _width_only_median(
                prepared, lookback, "FULL_DEVELOPMENT", "ALL", horizon, True, "mae"
            )
            horizon_metrics[horizon] = {
                "primary_minus_not_elevated_mfe": _difference(
                    primary["median_mfe_pct"], comparison["median_mfe_pct"]
                ),
                "primary_minus_not_elevated_mae": _difference(
                    primary["median_mae_pct"], comparison["median_mae_pct"]
                ),
                "primary_minus_not_elevated_quality": _difference(
                    primary["median_mfe_minus_mae_pct"],
                    comparison["median_mfe_minus_mae_pct"],
                ),
                "primary_minus_max_efficiency_mfe": _difference(
                    primary["median_mfe_pct"], max_efficiency["median_mfe_pct"]
                ),
                "width_only_minus_not_elevated_mfe": _difference(
                    width_only_mfe, comparison["median_mfe_pct"]
                ),
                "width_only_minus_not_elevated_mae": _difference(
                    width_only_mae, comparison["median_mae_pct"]
                ),
            }

        full_primary_support = all(
            horizon_metrics[h]["primary_minus_not_elevated_mfe"] > 0
            and horizon_metrics[h]["primary_minus_not_elevated_quality"] >= 0
            for h in PRIMARY_HORIZONS
        )
        max_efficiency_underperforms = all(
            horizon_metrics[h]["primary_minus_max_efficiency_mfe"] > 0
            for h in PRIMARY_HORIZONS
        )
        segment_support = {}
        for segment in ("DEV_FIRST_HALF", "DEV_SECOND_HALF"):
            mfe_deltas = []
            quality_deltas = []
            for horizon in PRIMARY_HORIZONS:
                primary = _summary_row(
                    stability, lookback, segment, "ALL", horizon, STATE_GROUPS[0]
                )
                comparison = _summary_row(
                    stability, lookback, segment, "ALL", horizon, STATE_GROUPS[2]
                )
                mfe_deltas.append(
                    _difference(primary["median_mfe_pct"], comparison["median_mfe_pct"])
                )
                quality_deltas.append(
                    _difference(
                        primary["median_mfe_minus_mae_pct"],
                        comparison["median_mfe_minus_mae_pct"],
                    )
                )
            segment_support[segment] = bool(
                np.nanmean(mfe_deltas) > 0 and np.nanmean(quality_deltas) >= 0
            )
        both_halves_support = all(segment_support.values())

        direction_support = {}
        for side in ("LONG", "SHORT"):
            mfe_deltas = []
            quality_deltas = []
            for horizon in PRIMARY_HORIZONS:
                primary = _summary_row(
                    direction, lookback, "FULL_DEVELOPMENT", side, horizon, STATE_GROUPS[0]
                )
                comparison = _summary_row(
                    direction, lookback, "FULL_DEVELOPMENT", side, horizon, STATE_GROUPS[2]
                )
                mfe_deltas.append(
                    _difference(primary["median_mfe_pct"], comparison["median_mfe_pct"])
                )
                quality_deltas.append(
                    _difference(
                        primary["median_mfe_minus_mae_pct"],
                        comparison["median_mfe_minus_mae_pct"],
                    )
                )
            direction_support[side] = bool(
                np.nanmean(mfe_deltas) > 0 and np.nanmean(quality_deltas) >= 0
            )
        no_severe_direction_contradiction = all(direction_support.values())

        counts = {
            state: int(
                _summary_row(
                    master, lookback, "FULL_DEVELOPMENT", "ALL", "30m", state
                )["event_n"]
            )
            for state in STATE_GROUPS
        }
        full_sample_adequate = (
            counts[STATE_GROUPS[0]] >= 20
            and counts[STATE_GROUPS[1]] >= 10
            and counts[STATE_GROUPS[2]] >= 20
        )
        half_primary_minimum = min(
            int(
                _summary_row(
                    stability, lookback, segment, "ALL", "30m", state
                )["event_n"]
            )
            for segment in ("DEV_FIRST_HALF", "DEV_SECOND_HALF")
            for state in (STATE_GROUPS[0], STATE_GROUPS[2])
        )
        direction_primary_minimum = min(
            int(
                _summary_row(
                    direction, lookback, "FULL_DEVELOPMENT", side, "30m", state
                )["event_n"]
            )
            for side in ("LONG", "SHORT")
            for state in (STATE_GROUPS[0], STATE_GROUPS[2])
        )
        sample_adequate = bool(
            full_sample_adequate
            and half_primary_minimum >= 10
            and direction_primary_minimum >= 10
        )
        combined_uplifts = [
            horizon_metrics[h]["primary_minus_not_elevated_mfe"]
            - horizon_metrics[h]["width_only_minus_not_elevated_mfe"]
            for h in PRIMARY_HORIZONS
        ]
        combined_more_interpretable = bool(
            max_efficiency_underperforms and np.nanmean(combined_uplifts) > 0
        )
        promotion_ready = bool(
            sample_adequate
            and full_primary_support
            and max_efficiency_underperforms
            and both_halves_support
            and no_severe_direction_contradiction
        )
        rows.append(
            {
                "research_scope": "DEVELOPMENT_ONLY",
                "hypothesis_id": HYPOTHESIS_ID,
                "lookback_sessions": lookback,
                "eligible_n": sum(counts.values()),
                "primary_n": counts[STATE_GROUPS[0]],
                "elevated_max_efficiency_n": counts[STATE_GROUPS[1]],
                "not_elevated_n": counts[STATE_GROUPS[2]],
                "full_30m_primary_minus_not_elevated_mfe_pct": horizon_metrics["30m"]["primary_minus_not_elevated_mfe"],
                "full_30m_primary_minus_not_elevated_mae_pct": horizon_metrics["30m"]["primary_minus_not_elevated_mae"],
                "full_30m_primary_minus_not_elevated_quality_pct": horizon_metrics["30m"]["primary_minus_not_elevated_quality"],
                "full_60m_primary_minus_not_elevated_mfe_pct": horizon_metrics["60m"]["primary_minus_not_elevated_mfe"],
                "full_60m_primary_minus_not_elevated_mae_pct": horizon_metrics["60m"]["primary_minus_not_elevated_mae"],
                "full_60m_primary_minus_not_elevated_quality_pct": horizon_metrics["60m"]["primary_minus_not_elevated_quality"],
                "full_30m_primary_minus_max_efficiency_mfe_pct": horizon_metrics["30m"]["primary_minus_max_efficiency_mfe"],
                "full_60m_primary_minus_max_efficiency_mfe_pct": horizon_metrics["60m"]["primary_minus_max_efficiency_mfe"],
                "full_30m_width_only_minus_not_elevated_mfe_pct": horizon_metrics["30m"]["width_only_minus_not_elevated_mfe"],
                "full_60m_width_only_minus_not_elevated_mfe_pct": horizon_metrics["60m"]["width_only_minus_not_elevated_mfe"],
                "first_half_support": segment_support["DEV_FIRST_HALF"],
                "second_half_support": segment_support["DEV_SECOND_HALF"],
                "both_halves_support": both_halves_support,
                "long_support": direction_support["LONG"],
                "short_support": direction_support["SHORT"],
                "no_severe_direction_contradiction": no_severe_direction_contradiction,
                "sample_adequate": sample_adequate,
                "full_primary_support": full_primary_support,
                "max_efficiency_underperforms": max_efficiency_underperforms,
                "combined_more_interpretable_than_width_alone": combined_more_interpretable,
                "promotion_ready": promotion_ready,
            }
        )
    assessment = pd.DataFrame(rows)
    promotion_count = int(assessment["promotion_ready"].sum())
    full_support_count = int(assessment["full_primary_support"].sum())
    half_support_count = int(assessment["both_halves_support"].sum())
    direction_support_count = int(
        assessment["no_severe_direction_contradiction"].sum()
    )
    max_efficiency_count = int(assessment["max_efficiency_underperforms"].sum())
    any_positive_count = int(
        (
            assessment[
                [
                    "full_30m_primary_minus_not_elevated_mfe_pct",
                    "full_60m_primary_minus_not_elevated_mfe_pct",
                ]
            ].max(axis=1)
            > 0
        ).sum()
    )
    if promotion_count >= 3:
        classification = "CONSISTENT_HYPOTHESIS_CANDIDATE"
    elif (
        full_support_count >= 2
        and max_efficiency_count >= 2
        and (half_support_count >= 2 or direction_support_count >= 2)
    ):
        classification = "POTENTIALLY_INFORMATIVE"
    elif any_positive_count >= 2:
        classification = "WEAK_OR_UNSTABLE"
    else:
        classification = "NO_CLEAR_RELATIONSHIP"
    if classification == "CONSISTENT_HYPOTHESIS_CANDIDATE":
        recommendation = "CONTINUED_IMMEDIATELY_AS_RESEARCH_CANDIDATE"
    elif classification in {"POTENTIALLY_INFORMATIVE", "WEAK_OR_UNSTABLE"}:
        recommendation = "PARKED_AS_RESEARCH_CANDIDATE"
    else:
        recommendation = "REJECTED_IN_CURRENT_FORM"
    return assessment, classification, recommendation


def render_report(
    master: pd.DataFrame,
    stability: pd.DataFrame,
    direction: pd.DataFrame,
    assessment: pd.DataFrame,
    audit: Mapping[str, Any],
) -> str:
    """Render the concise Stage 3C DEVELOPMENT-only research report."""

    eligibility = pd.DataFrame(
        [
            {
                "Lookback": f"{lookback} sessions",
                "Eligible N": audit["eligible_n_by_lookback"][str(lookback)],
                "Primary N": audit["group_counts_by_lookback"][str(lookback)][STATE_GROUPS[0]],
                "Elevated + max-eff N": audit["group_counts_by_lookback"][str(lookback)][STATE_GROUPS[1]],
                "Not elevated N": audit["group_counts_by_lookback"][str(lookback)][STATE_GROUPS[2]],
            }
            for lookback in LOOKBACKS
        ]
    )
    contrast_rows = []
    for row in assessment.itertuples():
        contrast_rows.append(
            {
                "Lookback": f"{row.lookback_sessions}d",
                "30m MFE delta": _fmt_pct(row.full_30m_primary_minus_not_elevated_mfe_pct),
                "30m MAE delta": _fmt_pct(row.full_30m_primary_minus_not_elevated_mae_pct),
                "60m MFE delta": _fmt_pct(row.full_60m_primary_minus_not_elevated_mfe_pct),
                "60m MAE delta": _fmt_pct(row.full_60m_primary_minus_not_elevated_mae_pct),
                "Max-eff underperforms": row.max_efficiency_underperforms,
            }
        )
    stability_rows = []
    for lookback in LOOKBACKS:
        for segment in ("DEV_FIRST_HALF", "DEV_SECOND_HALF"):
            deltas = []
            quality = []
            for horizon in PRIMARY_HORIZONS:
                primary = _summary_row(stability, lookback, segment, "ALL", horizon, STATE_GROUPS[0])
                comparison = _summary_row(stability, lookback, segment, "ALL", horizon, STATE_GROUPS[2])
                deltas.append(_difference(primary["median_mfe_pct"], comparison["median_mfe_pct"]))
                quality.append(_difference(primary["median_mfe_minus_mae_pct"], comparison["median_mfe_minus_mae_pct"]))
            stability_rows.append(
                {
                    "Lookback": f"{lookback}d",
                    "Segment": segment,
                    "Avg 30m/60m MFE delta": _fmt_pct(float(np.nanmean(deltas))),
                    "Avg quality delta": _fmt_pct(float(np.nanmean(quality))),
                }
            )
    direction_rows = []
    for lookback in LOOKBACKS:
        for side in ("LONG", "SHORT"):
            deltas = []
            quality = []
            for horizon in PRIMARY_HORIZONS:
                primary = _summary_row(direction, lookback, "FULL_DEVELOPMENT", side, horizon, STATE_GROUPS[0])
                comparison = _summary_row(direction, lookback, "FULL_DEVELOPMENT", side, horizon, STATE_GROUPS[2])
                deltas.append(_difference(primary["median_mfe_pct"], comparison["median_mfe_pct"]))
                quality.append(_difference(primary["median_mfe_minus_mae_pct"], comparison["median_mfe_minus_mae_pct"]))
            direction_rows.append(
                {
                    "Lookback": f"{lookback}d",
                    "Direction": side,
                    "Avg 30m/60m MFE delta": _fmt_pct(float(np.nanmean(deltas))),
                    "Avg quality delta": _fmt_pct(float(np.nanmean(quality))),
                }
            )
    split = audit["development_split"]
    return f"""# MNQ ORB V0.2 Stage 3C combined-state hypothesis test

## Scope

This final ORB round tests `HYP-ORB-STATE-01` on DEVELOPMENT only. It uses only
20-minute validated PRINT events, four frozen causal OR-width percentiles, the
unchanged Step-3 20-minute OR-efficiency quintiles, and existing clean
post-signal-bar percentage MFE/MAE. Signal-bar excursion is excluded. No
threshold search, feature search, strategy execution, P&L, Validation, or
OOS_BURNED data is used.

Width bands use `[0.00, 0.20)`, `[0.20, 0.40)`, `[0.40, 0.60)`,
`[0.60, 0.80)`, and `[0.80, 1.00]`. The primary state is width Q4/Q5 with
efficiency Q1-Q4. The max-efficiency comparison is width Q4/Q5 with efficiency
Q5. The not-elevated comparison is width Q1-Q3. Missing warm-up percentiles are
not backfilled.

## Eligibility and group counts

{_markdown_table(eligibility)}

## Full-DEVELOPMENT primary contrasts

Differences are primary state minus `WIDTH_NOT_ELEVATED`. Positive MFE favors
the hypothesis. Positive MAE means more adverse excursion.

{_markdown_table(pd.DataFrame(contrast_rows))}

## DEVELOPMENT-half stability

The same event-date split as Stage 3A is reused: {split['first_half_start']}
through {split['first_half_end']} and {split['second_half_start']} through
{split['second_half_end']}. Average deltas below average the predeclared 30m and
60m horizons only.

{_markdown_table(pd.DataFrame(stability_rows))}

## LONG and SHORT context

{_markdown_table(pd.DataFrame(direction_rows))}

## Guardrail assessment

{_markdown_table(assessment[[
    'lookback_sessions', 'sample_adequate', 'full_primary_support',
    'max_efficiency_underperforms', 'both_halves_support',
    'no_severe_direction_contradiction',
    'combined_more_interpretable_than_width_alone', 'promotion_ready'
]].rename(columns={
    'lookback_sessions': 'Lookback',
    'sample_adequate': 'Sample adequate',
    'full_primary_support': 'Full-DEV support',
    'max_efficiency_underperforms': 'Max-eff underperforms',
    'both_halves_support': 'Both halves support',
    'no_severe_direction_contradiction': 'LONG/SHORT consistent',
    'combined_more_interpretable_than_width_alone': 'Improves width-only interpretation',
    'promotion_ready': 'Promotion ready',
}))}

Final evidence classification: `{audit['hypothesis_classification']}`.

ORB research disposition: `{audit['orb_research_disposition']}`.

The combined state is judged more interpretable than width alone for
{audit['combined_more_interpretable_lookbacks']} of four causal lookbacks. This
is a descriptive hypothesis result, not a trading filter or validation result.

## Optional frozen-strategy diagnostic

Skipped. The exact 20m PRINT / midpoint / target75 freeze is available only in
aggregate candidate evidence, not as a reusable event-level trade artifact.
Producing conditional Avg R, PF, and win rate would require rebuilding execution,
which is outside this run.

## Output guardrail

The master CSV contains full-DEVELOPMENT results. The stability CSV contains
full, first-half, and second-half results for ALL, LONG, and SHORT. The direction
CSV contains full-DEVELOPMENT LONG/SHORT results. All percentages retain the
frozen fractional convention. The hypothesis is not validated or approved.
"""


def _prepare_events(
    events: pd.DataFrame,
    efficiency_intervals: list[Mapping[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = set(required_input_columns())
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError("Canonical Stage-3A input missing columns: " + ", ".join(missing))
    output = events[required_input_columns()].copy()
    dates = pd.to_datetime(output["session_date"], errors="coerce").dt.normalize()
    if dates.isna().any() or not dates.between(DEVELOPMENT_START, DEVELOPMENT_END).all():
        raise ValueError("Input contains rows outside frozen DEVELOPMENT dates")
    if not output["breakout_type"].astype(str).str.upper().eq("PRINT").all():
        raise ValueError("Stage 3C accepts validated PRINT events only")
    output["or_minutes"] = pd.to_numeric(output["or_minutes"], errors="raise").astype(int)
    output = output.loc[output["or_minutes"].eq(EXPECTED_OR_MINUTES)].copy()
    if output.empty:
        raise ValueError("Canonical input contains no 20-minute OR events")
    output["breakout_direction"] = output["breakout_direction"].astype(str).str.upper()
    if not set(output["breakout_direction"]) <= {"LONG", "SHORT"}:
        raise ValueError("Unsupported breakout direction")
    output["or_efficiency"] = pd.to_numeric(output["or_efficiency"], errors="coerce")
    output["_dev_half"], split = development_half_labels(output["session_date"])
    output["_efficiency_quintile"] = assign_fixed_quintiles(
        output["or_efficiency"], efficiency_intervals
    )
    eligible_n: dict[str, int] = {}
    unavailable_n: dict[str, int] = {}
    group_counts: dict[str, dict[str, int]] = {}
    for lookback in LOOKBACKS:
        assigned = assign_combined_states(
            output[f"or_width_hist_{lookback}_percentile"],
            output[f"or_width_hist_{lookback}_available"],
            output["or_efficiency"],
            efficiency_intervals,
        )
        output[f"_width_band_{lookback}"] = assigned["width_band"]
        output[f"_state_group_{lookback}"] = assigned["combined_state"]
        eligible_n[str(lookback)] = int(assigned["combined_state"].notna().sum())
        unavailable_n[str(lookback)] = int(assigned["combined_state"].isna().sum())
        group_counts[str(lookback)] = {
            state: int(assigned["combined_state"].eq(state).sum())
            for state in STATE_GROUPS
        }
    audit = {
        "research_scope": "DEVELOPMENT_ONLY",
        "input_rows": int(len(events)),
        "or_20m_rows": int(len(output)),
        "long_n": int(output["breakout_direction"].eq("LONG").sum()),
        "short_n": int(output["breakout_direction"].eq("SHORT").sum()),
        "eligible_n_by_lookback": eligible_n,
        "unavailable_n_by_lookback": unavailable_n,
        "group_counts_by_lookback": group_counts,
        "development_split": split,
        "efficiency_intervals": [dict(item) for item in efficiency_intervals],
        "signal_bar_chronology": "unknown_and_excluded",
        "optional_strategy_diagnostic": "SKIPPED_NO_REUSABLE_EVENT_LEVEL_FROZEN_ARTIFACT",
        "validation_accessed": False,
        "oos_burned_accessed": False,
        "thresholds_optimized": False,
        "other_features_tested": False,
    }
    return output, audit


def _build_summary(
    events: pd.DataFrame,
    *,
    segments: Iterable[str],
    directions: Iterable[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for lookback in LOOKBACKS:
        state_column = f"_state_group_{lookback}"
        width_column = f"_width_band_{lookback}"
        eligible = events.loc[events[state_column].notna()].copy()
        for segment in segments:
            segment_frame = (
                eligible
                if segment == "FULL_DEVELOPMENT"
                else eligible.loc[eligible["_dev_half"].eq(segment)]
            )
            for direction in directions:
                direction_frame = (
                    segment_frame
                    if direction == "ALL"
                    else segment_frame.loc[
                        segment_frame["breakout_direction"].eq(direction)
                    ]
                )
                denominator = len(direction_frame)
                for state in STATE_GROUPS:
                    state_frame = direction_frame.loc[direction_frame[state_column].eq(state)]
                    width_bands = "|".join(
                        sorted(
                            state_frame[width_column].dropna().unique(),
                            key=lambda value: BAND_LABELS.index(value),
                        )
                    )
                    efficiency_states = "|".join(
                        sorted(state_frame["_efficiency_quintile"].dropna().unique())
                    )
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
                        mean_mfe = _stat(mfe, "mean")
                        median_mfe = _stat(mfe, "median")
                        mean_mae = _stat(mae, "mean")
                        median_mae = _stat(mae, "median")
                        rows.append(
                            {
                                "research_scope": "DEVELOPMENT_ONLY",
                                "hypothesis_id": HYPOTHESIS_ID,
                                "or_minutes": EXPECTED_OR_MINUTES,
                                "lookback_sessions": lookback,
                                "dev_segment": segment,
                                "breakout_direction": direction,
                                "state_group": state,
                                "state_order": STATE_ORDER[state],
                                "width_bands_present": width_bands,
                                "efficiency_quintiles_present": efficiency_states,
                                "outcome_layer": "POST_SIGNAL_BAR_CLEAN",
                                "outcome_horizon": horizon,
                                "event_n": int(len(state_frame)),
                                "share_of_eligible_events": (
                                    float(len(state_frame) / denominator)
                                    if denominator
                                    else np.nan
                                ),
                                "long_n": int(state_frame["breakout_direction"].eq("LONG").sum()),
                                "short_n": int(state_frame["breakout_direction"].eq("SHORT").sum()),
                                "complete_outcome_n": int(len(complete_frame)),
                                "sample_status": (
                                    "SUFFICIENT"
                                    if len(complete_frame) >= MIN_REPORTING_N
                                    else "INSUFFICIENT_SAMPLE"
                                ),
                                "mfe_n": int(len(mfe)),
                                "mean_mfe_pct": mean_mfe,
                                "median_mfe_pct": median_mfe,
                                "mfe_p25_pct": _stat(mfe, "p25"),
                                "mfe_p75_pct": _stat(mfe, "p75"),
                                "mae_n": int(len(mae)),
                                "mean_mae_pct": mean_mae,
                                "median_mae_pct": median_mae,
                                "mae_p25_pct": _stat(mae, "p25"),
                                "mae_p75_pct": _stat(mae, "p75"),
                                "mean_mfe_minus_mae_pct": _difference(mean_mfe, mean_mae),
                                "median_mfe_minus_mae_pct": _difference(median_mfe, median_mae),
                            }
                        )
    return pd.DataFrame(rows)


def _summary_row(
    table: pd.DataFrame,
    lookback: int,
    segment: str,
    direction: str,
    horizon: str,
    state: str,
) -> pd.Series:
    selected = table.loc[
        table["lookback_sessions"].eq(lookback)
        & table["dev_segment"].eq(segment)
        & table["breakout_direction"].eq(direction)
        & table["outcome_horizon"].eq(horizon)
        & table["state_group"].eq(state)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"Expected one summary row for {lookback}/{segment}/{direction}/{horizon}/{state}"
        )
    return selected.iloc[0]


def _width_only_median(
    events: pd.DataFrame,
    lookback: int,
    segment: str,
    direction: str,
    horizon: str,
    elevated: bool,
    measure: str,
) -> float:
    frame = events
    if segment != "FULL_DEVELOPMENT":
        frame = frame.loc[frame["_dev_half"].eq(segment)]
    if direction != "ALL":
        frame = frame.loc[frame["breakout_direction"].eq(direction)]
    bands = BAND_LABELS[3:] if elevated else BAND_LABELS[:3]
    frame = frame.loc[frame[f"_width_band_{lookback}"].isin(bands)]
    complete = _boolean_series(frame[f"post_signal_bar_{horizon}_complete"])
    values = pd.to_numeric(
        frame.loc[complete, f"post_signal_bar_{horizon}_{measure}_pct"], errors="coerce"
    ).dropna()
    return _stat(values, "median")


def _boolean_series(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.fillna(False)
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def _as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


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


def _difference(left: Any, right: Any) -> float:
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return np.nan
    return left_value - right_value if np.isfinite(left_value) and np.isfinite(right_value) else np.nan


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
