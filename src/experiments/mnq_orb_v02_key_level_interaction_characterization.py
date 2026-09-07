"""DEVELOPMENT-only key-level interaction characterization for Stage 3A.

The analysis uses only frozen Stage-2 interaction primitives for previous-day,
NY pre-market, London, and Asia high/low families. Primitive definitions remain
unchanged; an analysis-only precedence creates mutually exclusive categories.
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


LEVEL_FAMILIES = {
    "previous_day": ("previous_day_high", "previous_day_low"),
    "ny_premarket": ("ny_premarket_high", "ny_premarket_low"),
    "london": ("london_high", "london_low"),
    "asia": ("asia_high", "asia_low"),
}
LEVEL_FAMILY_TITLES = {
    "previous_day": "Previous day",
    "ny_premarket": "NY pre-market",
    "london": "London",
    "asia": "Asia",
}
PRIMITIVES = (
    "touched",
    "traded_through",
    "closed_through",
    "rejected",
    "swept",
)
INTERACTION_STATES = (
    "NO_INTERACTION",
    "TOUCH_ONLY",
    "CLOSE_THROUGH",
    "REJECTION",
    "SWEEP",
)
STATE_PRECEDENCE = (
    "SWEEP",
    "REJECTION",
    "CLOSE_THROUGH",
    "TOUCH_ONLY",
    "NO_INTERACTION",
)


def required_input_columns() -> list[str]:
    """Return only grouping, frozen interaction, and clean outcome columns."""

    columns = [
        "session_date",
        "or_minutes",
        "breakout_type",
        "breakout_direction",
    ]
    for levels in LEVEL_FAMILIES.values():
        for level in levels:
            columns.append(f"level_{level}_available")
            columns.extend(f"level_{level}_{primitive}" for primitive in PRIMITIVES)
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
    """Reject paths that do not explicitly identify the DEVELOPMENT input."""

    text = str(path).replace("\\", "/").lower()
    if "validation" in text or "oos_burned" in text:
        raise ValueError("Reserved Validation/OOS_BURNED input is prohibited")
    if "_dev_" not in text:
        raise ValueError("Stage 3A Step 5 requires an explicitly DEV-labeled input")


def derive_interaction_category(
    *,
    available: bool,
    touched: bool,
    traded_through: bool,
    closed_through: bool,
    rejected: bool,
    swept: bool,
) -> Any:
    """Map frozen primitives to one category using the declared precedence."""

    if not available:
        return pd.NA
    if swept:
        return "SWEEP"
    if rejected:
        return "REJECTION"
    if closed_through:
        return "CLOSE_THROUGH"
    if touched:
        return "TOUCH_ONLY"
    return "NO_INTERACTION"


def characterize_key_level_interactions(
    events: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Return master, stability, direction, relationship, and audit tables."""

    family_events, audit = _prepare_family_events(events)
    master = _build_summary(
        family_events,
        or_scopes=(*EXPECTED_OR_MINUTES, "ALL"),
        segments=("FULL_DEVELOPMENT",),
        directions=("ALL",),
    )
    stability = _build_summary(
        family_events,
        or_scopes=EXPECTED_OR_MINUTES,
        segments=DEV_SEGMENTS,
        directions=("ALL", "LONG", "SHORT"),
    )
    direction = _build_summary(
        family_events,
        or_scopes=(*EXPECTED_OR_MINUTES, "ALL"),
        segments=("FULL_DEVELOPMENT",),
        directions=("LONG", "SHORT"),
    )
    relationships = summarize_relationships(master, stability)
    master = _attach_classifications(master, relationships)
    audit["relationship_label_counts"] = {
        str(label): int(count)
        for label, count in relationships["classification"].value_counts().items()
    }
    return master, stability, direction, relationships, audit


def summarize_relationships(
    master: pd.DataFrame, stability: pd.DataFrame
) -> pd.DataFrame:
    """Classify each family/duration across all clean outcome horizons."""

    rows: list[dict[str, Any]] = []
    for family in LEVEL_FAMILIES:
        for duration in EXPECTED_OR_MINUTES:
            segment_patterns: dict[str, list[tuple[str, str, float]]] = {}
            acceptance_patterns: dict[str, list[tuple[str, str, float]]] = {}
            for segment, table in (
                ("FULL_DEVELOPMENT", master),
                ("DEV_FIRST_HALF", stability),
                ("DEV_SECOND_HALF", stability),
            ):
                patterns: list[tuple[str, str, float]] = []
                acceptance: list[tuple[str, str, float]] = []
                for horizon in HORIZONS:
                    frame = _ordered_state_slice(
                        table,
                        family=family,
                        duration=duration,
                        segment=segment,
                        direction="ALL",
                        horizon=horizon,
                    )
                    pattern, strength = _categorical_pattern(frame)
                    comparison, difference = _acceptance_sweep_pattern(frame)
                    patterns.append((horizon, pattern, strength))
                    acceptance.append((horizon, comparison, difference))
                segment_patterns[segment] = patterns
                acceptance_patterns[segment] = acceptance

            full_pattern, full_support = _dominant_pattern(
                segment_patterns["FULL_DEVELOPMENT"]
            )
            first_pattern, first_support = _dominant_pattern(
                segment_patterns["DEV_FIRST_HALF"]
            )
            second_pattern, second_support = _dominant_pattern(
                segment_patterns["DEV_SECOND_HALF"]
            )
            full_acceptance, full_acceptance_support = _dominant_pattern(
                acceptance_patterns["FULL_DEVELOPMENT"]
            )
            first_acceptance, first_acceptance_support = _dominant_pattern(
                acceptance_patterns["DEV_FIRST_HALF"]
            )
            second_acceptance, second_acceptance_support = _dominant_pattern(
                acceptance_patterns["DEV_SECOND_HALF"]
            )

            full_30m = _ordered_state_slice(
                master,
                family=family,
                duration=duration,
                segment="FULL_DEVELOPMENT",
                direction="ALL",
                horizon="30m",
            )
            first_30m = _ordered_state_slice(
                stability,
                family=family,
                duration=duration,
                segment="DEV_FIRST_HALF",
                direction="ALL",
                horizon="30m",
            )
            second_30m = _ordered_state_slice(
                stability,
                family=family,
                duration=duration,
                segment="DEV_SECOND_HALF",
                direction="ALL",
                horizon="30m",
            )
            full_inference = full_30m[full_30m["event_n"] >= 10]
            contrast_pct = _numeric_range(full_inference["median_mfe_pct"])
            contrast_ratio = _iqr_scaled_contrast(full_inference)
            material_contrast = bool(
                np.isfinite(contrast_ratio) and contrast_ratio >= 0.25
            )
            top_state = (
                full_pattern.removeprefix("HIGHEST_MFE_")
                if full_pattern.startswith("HIGHEST_MFE_")
                else None
            )
            minimum_half_top_state_n = min(
                _state_n(first_30m, top_state),
                _state_n(second_30m, top_state),
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
            elif stable_pattern and minimum_half_top_state_n >= 10:
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

            close_row = full_30m[full_30m["state_label"] == "CLOSE_THROUGH"]
            sweep_row = full_30m[full_30m["state_label"] == "SWEEP"]
            rows.append(
                {
                    "research_scope": "DEVELOPMENT_ONLY",
                    "level_family": family,
                    "or_minutes": duration,
                    "assessment_horizons": "5m|15m|30m|60m|session_end",
                    "full_pattern": full_pattern,
                    "full_supporting_horizons": full_support,
                    "first_half_pattern": first_pattern,
                    "first_half_supporting_horizons": first_support,
                    "second_half_pattern": second_pattern,
                    "second_half_supporting_horizons": second_support,
                    "full_acceptance_vs_sweep_pattern": full_acceptance,
                    "full_acceptance_supporting_horizons": full_acceptance_support,
                    "first_half_acceptance_vs_sweep_pattern": first_acceptance,
                    "first_half_acceptance_supporting_horizons": first_acceptance_support,
                    "second_half_acceptance_vs_sweep_pattern": second_acceptance,
                    "second_half_acceptance_supporting_horizons": second_acceptance_support,
                    "full_30m_acceptance_minus_sweep_mfe_pct": _row_difference(
                        close_row, sweep_row, "median_mfe_pct"
                    ),
                    "full_30m_acceptance_minus_sweep_mae_pct": _row_difference(
                        close_row, sweep_row, "median_mae_pct"
                    ),
                    "full_30m_median_mfe_contrast_pct": contrast_pct,
                    "full_30m_iqr_scaled_mfe_contrast": contrast_ratio,
                    "minimum_half_top_state_n": minimum_half_top_state_n,
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
    """Render the concise Step-5 report."""

    relation_table = relationships[
        [
            "level_family",
            "or_minutes",
            "full_pattern",
            "first_half_pattern",
            "second_half_pattern",
            "classification",
        ]
    ].copy()
    relation_table["level_family"] = relation_table["level_family"].map(
        LEVEL_FAMILY_TITLES
    )
    relation_table = relation_table.rename(
        columns={
            "level_family": "Level family",
            "or_minutes": "OR min",
            "full_pattern": "Full DEV",
            "first_half_pattern": "First half",
            "second_half_pattern": "Second half",
            "classification": "Assessment",
        }
    )

    comparison_rows: list[dict[str, Any]] = []
    full_30m = master[
        master["outcome_horizon"].eq("30m")
        & master["or_minutes"].astype(str).isin({"15", "20", "30"})
    ]
    for (family, duration), group in full_30m.groupby(
        ["level_family", "or_minutes"], sort=False
    ):
        by_state = group.set_index("state_label")
        close = by_state.loc["CLOSE_THROUGH"]
        sweep = by_state.loc["SWEEP"]
        rejection = by_state.loc["REJECTION"]
        comparison_rows.append(
            {
                "Family": LEVEL_FAMILY_TITLES[family],
                "OR min": duration,
                "Close N": int(close["event_n"]),
                "Sweep N": int(sweep["event_n"]),
                "Reject N": int(rejection["event_n"]),
                "Close−sweep median MFE": _fmt_pct(
                    float(close["median_mfe_pct"])
                    - float(sweep["median_mfe_pct"])
                ),
                "Close−sweep median MAE": _fmt_pct(
                    float(close["median_mae_pct"])
                    - float(sweep["median_mae_pct"])
                ),
            }
        )

    availability_rows = []
    for family in LEVEL_FAMILIES:
        counts = audit["category_counts_by_family"][family]
        availability_rows.append(
            {
                "Family": LEVEL_FAMILY_TITLES[family],
                "Eligible N": audit["eligible_n_by_family"][family],
                "Unavailable N": audit["unavailable_n_by_family"][family],
                **{state: counts.get(state, 0) for state in INTERACTION_STATES},
            }
        )

    direction_30m = direction[
        direction["outcome_horizon"].eq("30m")
        & direction["or_minutes"].astype(str).isin({"15", "20", "30"})
    ]
    direction_rows: list[dict[str, Any]] = []
    for (family, side), group in direction_30m.groupby(
        ["level_family", "breakout_direction"], sort=False
    ):
        spans = []
        for duration, duration_group in group.groupby("or_minutes", sort=True):
            inference = duration_group[duration_group["event_n"] >= 10]
            spans.append((duration, _numeric_range(inference["median_mfe_pct"])))
        largest = max(spans, key=lambda item: item[1])
        direction_rows.append(
            {
                "Family": LEVEL_FAMILY_TITLES[family],
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
                "Median 30m state contrast": _fmt_pct(
                    float(group["full_30m_median_mfe_contrast_pct"].median())
                ),
                "Assessments": ", ".join(
                    f"{label}={count}"
                    for label, count in group["classification"].value_counts().items()
                ),
            }
        )

    informative = relationships[
        relationships["classification"].isin(
            {"POTENTIALLY_INFORMATIVE", "CONSISTENT_CANDIDATE_STATE"}
        )
    ]
    stable = relationships[
        relationships["classification"].eq("CONSISTENT_CANDIDATE_STATE")
    ]
    weak = relationships[
        relationships["classification"].isin(
            {"WEAK_OR_UNSTABLE", "NO_CLEAR_RELATIONSHIP"}
        )
    ]
    split = audit["development_split"]
    step4_comparison = (
        "Interaction states show more descriptive promise than Step 4 room distance "
        f"because {len(informative)} family/duration relationships clear the informative "
        "guardrail, while Step 4 recorded none. This is not evidence of a trading rule."
        if len(informative)
        else "Interaction states do not look more useful than Step 4 room distance: both "
        "runs remain entirely weak or no-clear under their predeclared guardrails."
    )

    return f"""# MNQ ORB V0.2 Stage 3A Step 5 key-level interaction

## Scope and deterministic category mapping

This DEVELOPMENT-only analysis uses {audit['input_rows']} Step-1B PRINT breakout
events and only frozen Stage-2 key-level interaction primitives for previous-day,
NY pre-market, London, and Asia high/low families. Existing normalized
post-signal-bar MFE/MAE at 5m, 15m, 30m, 60m, and session end are the outcomes.
Signal-bar excursion is excluded because its chronology is unknown.

Each family aggregates its high/low primitive flags without changing them. One
analysis category is assigned by the fixed precedence `SWEEP`, `REJECTION`,
`CLOSE_THROUGH`, `TOUCH_ONLY`, then `NO_INTERACTION`. An unavailable family is
excluded and is never treated as no interaction. The CSVs retain primitive-flag
counts under every exclusive state.

The input contains {split['unique_event_dates']} event-bearing dates. The first
{split['first_half_dates']} ({split['first_half_start']} through
{split['first_half_end']}) form `DEV_FIRST_HALF`; the final
{split['second_half_dates']} ({split['second_half_start']} through
{split['second_half_end']}) form `DEV_SECOND_HALF`.

{_markdown_table(pd.DataFrame(availability_rows))}

## Relationship assessment

Each family/duration assessment uses the state with the highest median MFE across
the five clean horizons, excludes states with fewer than 10 events from the
relationship inference, and requires a 30m state contrast of at least one quarter
of the median within-state IQR. `CONSISTENT_CANDIDATE_STATE` additionally requires
the same full/first-half/second-half pattern and at least 10 events in the top
state in each half. These are descriptive guardrails, not optimized thresholds.

{_markdown_table(relation_table)}

Potentially informative relationships: {_relationship_list(informative)}.

Consistent across DEV halves: {_relationship_list(stable)}.

Weak or no-clear relationships: {_relationship_list(weak)}.

## Acceptance versus sweep and rejection

`CLOSE_THROUGH` is the acceptance state. `SWEEP` has precedence over rejection
because the frozen sweep primitive also carries rejection. Non-sweep
`REJECTION` is reported separately but is sparse in this dataset.

{_markdown_table(pd.DataFrame(comparison_rows))}

Positive close−sweep MFE means acceptance produced more favorable excursion;
positive close−sweep MAE means acceptance also produced more adverse excursion.
The full five-horizon paths and half-sample comparisons remain in the CSVs.

## LONG/SHORT differences

{_markdown_table(pd.DataFrame(direction_rows))}

The spans show where direction-specific differences are largest. They do not
rank or define strategy rules.

## OR-duration and reference-family context

{_markdown_table(pd.DataFrame(duration_rows))}

Family labels with small or unstable states are not treated as superior even if
a point estimate is large. Combined-duration output is secondary context only.

## Comparison with Step 4 room distance

{step4_comparison}

No Step-4 state was recalculated or combined with an interaction state.

## Output guardrail

No OR-width, internal-structure, room-distance, pre-open, gap, combined-state,
strategy-performance, filter, optimization, or ML analysis was performed. Step 5
is complete; overall Stage 3A remains incomplete and reserved partitions remain
unexposed.
"""


def _prepare_family_events(
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = set(required_input_columns())
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError("Step-1B input missing required columns: " + ", ".join(missing))
    source = events[required_input_columns()].copy()
    dates = pd.to_datetime(source["session_date"], errors="coerce").dt.normalize()
    if dates.isna().any() or not dates.between(DEVELOPMENT_START, DEVELOPMENT_END).all():
        raise ValueError("Input contains rows outside the frozen DEVELOPMENT dates")
    if not source["breakout_type"].astype(str).str.upper().eq("PRINT").all():
        raise ValueError("Stage 3A Step 5 accepts PRINT events only")
    source["breakout_direction"] = source["breakout_direction"].astype(str).str.upper()
    if not set(source["breakout_direction"]) <= {"LONG", "SHORT"}:
        raise ValueError("Unsupported breakout direction")
    source["or_minutes"] = pd.to_numeric(source["or_minutes"], errors="raise").astype(int)
    if set(source["or_minutes"]) != set(EXPECTED_OR_MINUTES):
        raise ValueError("Input must contain exactly the 15m, 20m, and 30m OR durations")

    for levels in LEVEL_FAMILIES.values():
        for level in levels:
            source[f"level_{level}_available"] = _boolean_series(
                source[f"level_{level}_available"]
            )
            for primitive in PRIMITIVES:
                column = f"level_{level}_{primitive}"
                source[column] = _boolean_series(source[column])
            _validate_level_primitives(source, level)

    half_labels, split = development_half_labels(source["session_date"])
    family_frames: list[pd.DataFrame] = []
    availability_mismatches = 0
    for family, levels in LEVEL_FAMILIES.items():
        frame = source[
            [
                "session_date",
                "or_minutes",
                "breakout_type",
                "breakout_direction",
                *(column for column in source.columns if column.startswith("post_signal_bar_")),
            ]
        ].copy()
        available_columns = [f"level_{level}_available" for level in levels]
        any_available = source[available_columns].any(axis=1)
        all_available = source[available_columns].all(axis=1)
        availability_mismatches += int((any_available != all_available).sum())
        frame["level_family"] = family
        frame["level_members"] = "|".join(levels)
        frame["family_available"] = all_available
        for primitive in PRIMITIVES:
            columns = [f"level_{level}_{primitive}" for level in levels]
            frame[f"primitive_{primitive}"] = source[columns].any(axis=1)
        frame["interaction_state"] = [
            derive_interaction_category(
                available=bool(row.family_available),
                touched=bool(row.primitive_touched),
                traded_through=bool(row.primitive_traded_through),
                closed_through=bool(row.primitive_closed_through),
                rejected=bool(row.primitive_rejected),
                swept=bool(row.primitive_swept),
            )
            for row in frame.itertuples()
        ]
        frame["_dev_half"] = half_labels.to_numpy()
        family_frames.append(frame)
    if availability_mismatches:
        raise ValueError("High/low availability differs within a declared level family")
    family_events = pd.concat(family_frames, ignore_index=True)

    eligible_n = {
        family: int(
            (
                family_events["level_family"].eq(family)
                & family_events["family_available"]
            ).sum()
        )
        for family in LEVEL_FAMILIES
    }
    category_counts = {
        family: {
            state: int(
                (
                    family_events["level_family"].eq(family)
                    & family_events["interaction_state"].eq(state)
                ).sum()
            )
            for state in INTERACTION_STATES
        }
        for family in LEVEL_FAMILIES
    }
    audit = {
        "research_scope": "DEVELOPMENT_ONLY",
        "input_rows": int(len(source)),
        "family_event_rows": int(len(family_events)),
        "eligible_n_by_family": eligible_n,
        "unavailable_n_by_family": {
            family: int(len(source) - eligible_n[family]) for family in LEVEL_FAMILIES
        },
        "category_counts_by_family": category_counts,
        "availability_mismatch_n": availability_mismatches,
        "primitive_invariant_violations": 0,
        "development_split": split,
        "source_columns_loaded": required_input_columns(),
        "other_state_family_columns_loaded": False,
        "signal_bar_chronology": "unknown_and_excluded",
        "validation_accessed": False,
        "oos_burned_accessed": False,
    }
    return family_events, audit


def _build_summary(
    family_events: pd.DataFrame,
    *,
    or_scopes: Iterable[int | str],
    segments: Iterable[str],
    directions: Iterable[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for family in LEVEL_FAMILIES:
        family_frame = family_events[family_events["level_family"] == family]
        for duration in or_scopes:
            duration_frame = (
                family_frame
                if duration == "ALL"
                else family_frame[family_frame["or_minutes"] == duration]
            )
            duration_frame = duration_frame[duration_frame["interaction_state"].notna()]
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
                        else segment_frame[segment_frame["breakout_direction"] == direction]
                    )
                    denominator = len(direction_frame)
                    for state_order, state in enumerate(INTERACTION_STATES, 1):
                        state_frame = direction_frame[
                            direction_frame["interaction_state"] == state
                        ]
                        for horizon in HORIZONS:
                            rows.append(
                                _summary_row(
                                    state_frame,
                                    family=family,
                                    duration=duration,
                                    segment=segment,
                                    direction=direction,
                                    state=state,
                                    state_order=state_order,
                                    horizon=horizon,
                                    denominator=denominator,
                                )
                            )
    return pd.DataFrame(rows)


def _summary_row(
    state_frame: pd.DataFrame,
    *,
    family: str,
    duration: int | str,
    segment: str,
    direction: str,
    state: str,
    state_order: int,
    horizon: str,
    denominator: int,
) -> dict[str, Any]:
    complete = _boolean_series(state_frame[f"post_signal_bar_{horizon}_complete"])
    complete_frame = state_frame.loc[complete]
    mfe = pd.to_numeric(
        complete_frame[f"post_signal_bar_{horizon}_mfe_pct"], errors="coerce"
    ).dropna()
    mae = pd.to_numeric(
        complete_frame[f"post_signal_bar_{horizon}_mae_pct"], errors="coerce"
    ).dropna()
    return {
        "research_scope": "DEVELOPMENT_ONLY",
        "level_family": family,
        "level_members": "|".join(LEVEL_FAMILIES[family]),
        "or_minutes": duration,
        "dev_segment": segment,
        "breakout_direction": direction,
        "state_label": state,
        "state_order": state_order,
        "state_precedence": ">".join(STATE_PRECEDENCE),
        "outcome_layer": "POST_SIGNAL_BAR_CLEAN",
        "outcome_horizon": horizon,
        "eligible_event_n": int(denominator),
        "event_n": int(len(state_frame)),
        "share_of_eligible_events": (
            float(len(state_frame) / denominator) if denominator else np.nan
        ),
        "long_n": int(state_frame["breakout_direction"].eq("LONG").sum()),
        "short_n": int(state_frame["breakout_direction"].eq("SHORT").sum()),
        "primitive_touch_n": int(state_frame["primitive_touched"].sum()),
        "primitive_trade_through_n": int(
            state_frame["primitive_traded_through"].sum()
        ),
        "primitive_close_through_n": int(
            state_frame["primitive_closed_through"].sum()
        ),
        "primitive_rejection_n": int(state_frame["primitive_rejected"].sum()),
        "primitive_sweep_n": int(state_frame["primitive_swept"].sum()),
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


def _attach_classifications(
    master: pd.DataFrame, relationships: pd.DataFrame
) -> pd.DataFrame:
    columns = [
        "level_family",
        "or_minutes",
        "full_pattern",
        "first_half_pattern",
        "second_half_pattern",
        "full_acceptance_vs_sweep_pattern",
        "classification",
    ]
    output = master.merge(
        relationships[columns],
        on=["level_family", "or_minutes"],
        how="left",
        validate="many_to_one",
    )
    combined = output["or_minutes"].astype(str).eq("ALL")
    output.loc[combined, "classification"] = "SECONDARY_CONTEXT_NOT_CLASSIFIED"
    return output


def _ordered_state_slice(
    table: pd.DataFrame,
    *,
    family: str,
    duration: int,
    segment: str,
    direction: str,
    horizon: str,
) -> pd.DataFrame:
    return table[
        table["level_family"].eq(family)
        & table["or_minutes"].astype(str).eq(str(duration))
        & table["dev_segment"].eq(segment)
        & table["breakout_direction"].eq(direction)
        & table["outcome_horizon"].eq(horizon)
    ].sort_values("state_order").reset_index(drop=True)


def _categorical_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    inference = frame[
        frame["event_n"].ge(10) & frame["median_mfe_pct"].notna()
    ]
    if len(inference) < 2:
        return "NO_CLEAR_PATTERN", np.nan
    values = pd.to_numeric(inference["median_mfe_pct"], errors="coerce")
    if values.nunique() < 2:
        return "NO_CLEAR_PATTERN", 0.0
    top_index = values.idxmax()
    top_state = str(inference.loc[top_index, "state_label"])
    return f"HIGHEST_MFE_{top_state}", float(values.max() - values.min())


def _acceptance_sweep_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    comparison = frame[frame["state_label"].isin({"CLOSE_THROUGH", "SWEEP"})]
    if (
        len(comparison) != 2
        or comparison["median_mfe_pct"].isna().any()
        or comparison["event_n"].lt(10).any()
    ):
        return "NO_CLEAR_PATTERN", np.nan
    values = dict(
        zip(comparison["state_label"], comparison["median_mfe_pct"].astype(float))
    )
    difference = values["CLOSE_THROUGH"] - values["SWEEP"]
    if difference > 0:
        return "CLOSE_THROUGH_MORE_MFE_THAN_SWEEP", difference
    if difference < 0:
        return "SWEEP_MORE_MFE_THAN_CLOSE_THROUGH", difference
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


def _validate_level_primitives(frame: pd.DataFrame, level: str) -> None:
    prefix = f"level_{level}_"
    available = frame[f"{prefix}available"]
    touch = frame[f"{prefix}touched"]
    trade = frame[f"{prefix}traded_through"]
    close = frame[f"{prefix}closed_through"]
    reject = frame[f"{prefix}rejected"]
    sweep = frame[f"{prefix}swept"]
    violations = (
        ((touch | trade | close | reject | sweep) & ~available)
        | (trade & ~touch)
        | (close & ~(touch & trade))
        | (reject & ~touch)
        | (sweep & ~(touch & trade & reject))
        | (close & reject)
        | (trade & ~(close | sweep))
    )
    if violations.any():
        raise ValueError(f"Frozen primitive invariant violation for {level}")


def _state_n(frame: pd.DataFrame, state: str | None) -> int:
    if state is None:
        return 0
    row = frame[frame["state_label"] == state]
    return int(row["event_n"].iloc[0]) if len(row) == 1 else 0


def _row_difference(
    first: pd.DataFrame, second: pd.DataFrame, column: str
) -> float:
    if len(first) != 1 or len(second) != 1:
        return np.nan
    first_value = pd.to_numeric(first[column], errors="coerce").iloc[0]
    second_value = pd.to_numeric(second[column], errors="coerce").iloc[0]
    if not np.isfinite(first_value) or not np.isfinite(second_value):
        return np.nan
    return float(first_value - second_value)


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
        f"{LEVEL_FAMILY_TITLES[row.level_family]} / {int(row.or_minutes)}m"
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
