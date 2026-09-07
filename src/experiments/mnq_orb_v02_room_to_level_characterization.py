"""DEVELOPMENT-only room-to-next-key-level characterization for Stage 3A.

This module analyzes only the frozen Step-1A room-to-level fields carried by
the Step-1B event table. It summarizes existing clean post-signal excursion
outcomes and does not combine room state with any other state family.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_stage3a import ROOM_LEVEL_ORDER
from src.experiments.mnq_orb_v02_width_characterization import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    DEV_SEGMENTS,
    EXPECTED_OR_MINUTES,
    HORIZONS,
    development_half_labels,
)


CONTINUOUS_REPRESENTATIONS = (
    "room_to_next_level_pct",
    "room_to_next_level_or_widths",
    "room_to_next_level_points",
)
NO_LEVEL_REPRESENTATION = "no_level_ahead"
REPRESENTATIONS = (*CONTINUOUS_REPRESENTATIONS, NO_LEVEL_REPRESENTATION)
PRIMARY_REPRESENTATIONS = (
    "room_to_next_level_pct",
    "room_to_next_level_or_widths",
    NO_LEVEL_REPRESENTATION,
)
REPRESENTATION_TITLES = {
    "room_to_next_level_pct": "Room / OR-mid price",
    "room_to_next_level_or_widths": "Room / OR width",
    "room_to_next_level_points": "Room in points",
    NO_LEVEL_REPRESENTATION: "Known level ahead",
}
REPRESENTATION_ROLES = {
    "room_to_next_level_pct": "PRIMARY",
    "room_to_next_level_or_widths": "PRIMARY",
    "room_to_next_level_points": "SECONDARY",
    NO_LEVEL_REPRESENTATION: "PRIMARY",
}
QUINTILE_LABELS = ("Q1", "Q2", "Q3", "Q4", "Q5")
NO_LEVEL_STATE = "NO_LEVEL_AHEAD"
KNOWN_LEVEL_STATE = "KNOWN_LEVEL_AHEAD"
NO_LEVEL_STATES = (KNOWN_LEVEL_STATE, NO_LEVEL_STATE)
TYPE_TIE_SCOPES = ("ALL_FROZEN_LABELS", "UNTIED_ONLY_SENSITIVITY")


def required_input_columns() -> list[str]:
    """Return only the Step-4 state, tie-audit, grouping, and outcome fields."""

    columns = [
        "session_date",
        "or_minutes",
        "breakout_type",
        "breakout_direction",
        "or_high",
        "or_low",
        "next_level_type",
        "next_level_price",
        *CONTINUOUS_REPRESENTATIONS,
        NO_LEVEL_REPRESENTATION,
        *ROOM_LEVEL_ORDER,
        *(f"level_{name}_available" for name in ROOM_LEVEL_ORDER),
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
        raise ValueError("Stage 3A Step 4 requires an explicitly DEV-labeled input")


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
    """Apply full-DEVELOPMENT boundaries without recomputing subgroup edges."""

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


def identify_equal_price_nearest_ties(events: pd.DataFrame) -> pd.Series:
    """Flag rows whose exact nearest valid price is shared by multiple levels."""

    flags: list[bool] = []
    for _, row in events.iterrows():
        direction = str(row.get("breakout_direction", "")).upper()
        boundary_name = "or_high" if direction == "LONG" else "or_low"
        boundary = _finite_number(row.get(boundary_name))
        if direction not in {"LONG", "SHORT"} or boundary is None:
            flags.append(False)
            continue
        candidates: list[tuple[float, int, str, float]] = []
        for priority, level_name in enumerate(ROOM_LEVEL_ORDER):
            level = _valid_level(row, level_name)
            if level is None:
                continue
            distance = level - boundary if direction == "LONG" else boundary - level
            if distance > 0:
                candidates.append((float(distance), priority, level_name, level))
        if not candidates:
            flags.append(False)
            continue
        nearest_distance = min(item[0] for item in candidates)
        flags.append(sum(item[0] == nearest_distance for item in candidates) > 1)
    return pd.Series(flags, index=events.index, dtype=bool, name="next_level_type_tied")


def characterize_room_to_level(
    events: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Return master, stability, direction, type, relationship, and audit tables."""

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
    type_description = _build_type_description(prepared)
    relationships = summarize_relationships(master, stability)
    master = _attach_classifications(master, relationships)
    audit["relationship_label_counts"] = {
        str(label): int(count)
        for label, count in relationships["classification"].value_counts().items()
    }
    return master, stability, direction, type_description, relationships, audit


def summarize_relationships(
    master: pd.DataFrame, stability: pd.DataFrame
) -> pd.DataFrame:
    """Classify each primary representation/duration across clean horizons."""

    rows: list[dict[str, Any]] = []
    for representation in PRIMARY_REPRESENTATIONS:
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
                        representation=representation,
                        duration=duration,
                        segment=segment,
                        direction="ALL",
                        horizon=horizon,
                    )
                    inference = frame[frame["state_label"] != NO_LEVEL_STATE]
                    if representation == NO_LEVEL_REPRESENTATION:
                        inference = frame
                        pattern, ordering = _no_level_pattern(inference)
                    else:
                        pattern, ordering = _continuous_pattern(inference)
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
                representation=representation,
                duration=duration,
                segment="FULL_DEVELOPMENT",
                direction="ALL",
                horizon="30m",
            )
            first_30m = _ordered_state_slice(
                stability,
                representation=representation,
                duration=duration,
                segment="DEV_FIRST_HALF",
                direction="ALL",
                horizon="30m",
            )
            second_30m = _ordered_state_slice(
                stability,
                representation=representation,
                duration=duration,
                segment="DEV_SECOND_HALF",
                direction="ALL",
                horizon="30m",
            )
            if representation != NO_LEVEL_REPRESENTATION:
                full_30m = full_30m[full_30m["state_label"] != NO_LEVEL_STATE]
                first_30m = first_30m[first_30m["state_label"] != NO_LEVEL_STATE]
                second_30m = second_30m[second_30m["state_label"] != NO_LEVEL_STATE]
            contrast_pct = _numeric_range(full_30m["median_mfe_pct"])
            mae_contrast_pct = _numeric_range(full_30m["median_mae_pct"])
            contrast_ratio = _iqr_scaled_contrast(full_30m)
            minimum_half_state_n = int(
                min(first_30m["event_n"].min(), second_30m["event_n"].min())
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
                    "source_feature": representation,
                    "representation_role": REPRESENTATION_ROLES[representation],
                    "or_minutes": duration,
                    "assessment_horizons": "5m|15m|30m|60m|session_end",
                    "full_pattern": full_pattern,
                    "full_supporting_horizons": full_support,
                    "first_half_pattern": first_pattern,
                    "first_half_supporting_horizons": first_support,
                    "second_half_pattern": second_pattern,
                    "second_half_supporting_horizons": second_support,
                    "full_30m_median_mfe_contrast_pct": contrast_pct,
                    "full_30m_median_mae_contrast_pct": mae_contrast_pct,
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
    type_description: pd.DataFrame,
    relationships: pd.DataFrame,
    audit: Mapping[str, Any],
) -> str:
    """Render the concise Step-4 report without combining state families."""

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
        REPRESENTATION_TITLES
    )
    relation_table = relation_table.rename(
        columns={
            "source_feature": "Representation",
            "or_minutes": "OR min",
            "full_pattern": "Full DEV",
            "first_half_pattern": "First half",
            "second_half_pattern": "Second half",
            "classification": "Assessment",
        }
    )

    q_detail = master[
        master["source_feature"].isin(CONTINUOUS_REPRESENTATIONS[:2])
        & master["or_minutes"].astype(str).isin({"15", "20", "30"})
        & master["outcome_horizon"].eq("30m")
        & master["state_label"].isin({"Q1", "Q5"})
    ]
    q_rows: list[dict[str, Any]] = []
    for (feature, duration), group in q_detail.groupby(
        ["source_feature", "or_minutes"], sort=False
    ):
        by_state = group.set_index("state_label")
        if not {"Q1", "Q5"} <= set(by_state.index):
            continue
        q_rows.append(
            {
                "Representation": REPRESENTATION_TITLES[feature],
                "OR min": duration,
                "Q5-Q1 median MFE": _fmt_pct(
                    float(by_state.loc["Q5", "median_mfe_pct"])
                    - float(by_state.loc["Q1", "median_mfe_pct"])
                ),
                "Q5-Q1 median MAE": _fmt_pct(
                    float(by_state.loc["Q5", "median_mae_pct"])
                    - float(by_state.loc["Q1", "median_mae_pct"])
                ),
                "Q5-Q1 total excursion": _fmt_pct(
                    float(by_state.loc["Q5", "median_mfe_pct"])
                    + float(by_state.loc["Q5", "median_mae_pct"])
                    - float(by_state.loc["Q1", "median_mfe_pct"])
                    - float(by_state.loc["Q1", "median_mae_pct"])
                ),
            }
        )

    no_level = master[
        master["source_feature"].eq(NO_LEVEL_REPRESENTATION)
        & master["or_minutes"].astype(str).isin({"15", "20", "30"})
        & master["outcome_horizon"].eq("30m")
    ]
    no_level_rows = no_level[
        ["or_minutes", "state_label", "event_n", "median_mfe_pct", "median_mae_pct"]
    ].copy()
    no_level_rows["median_mfe_pct"] = no_level_rows["median_mfe_pct"].map(_fmt_pct)
    no_level_rows["median_mae_pct"] = no_level_rows["median_mae_pct"].map(_fmt_pct)
    no_level_rows = no_level_rows.rename(
        columns={
            "or_minutes": "OR min",
            "state_label": "State",
            "event_n": "N",
            "median_mfe_pct": "Median MFE",
            "median_mae_pct": "Median MAE",
        }
    )

    direction_30m = direction[
        direction["source_feature"].isin(PRIMARY_REPRESENTATIONS)
        & direction["or_minutes"].astype(str).isin({"15", "20", "30"})
        & direction["outcome_horizon"].eq("30m")
    ]
    direction_rows: list[dict[str, Any]] = []
    for (feature, side), group in direction_30m.groupby(
        ["source_feature", "breakout_direction"], sort=False
    ):
        inference = (
            group
            if feature == NO_LEVEL_REPRESENTATION
            else group[group["state_label"] != NO_LEVEL_STATE]
        )
        contrasts = [
            (duration, _numeric_range(duration_group["median_mfe_pct"]))
            for duration, duration_group in inference.groupby("or_minutes", sort=True)
        ]
        largest = max(contrasts, key=lambda item: item[1])
        direction_rows.append(
            {
                "Representation": REPRESENTATION_TITLES[feature],
                "Side": side,
                "Largest 30m median-MFE state span": _fmt_pct(largest[1]),
                "OR duration": largest[0],
            }
        )

    types = type_description[
        type_description["or_minutes"].astype(str).eq("ALL")
        & type_description["tie_scope"].eq("ALL_FROZEN_LABELS")
        & type_description["outcome_horizon"].eq("30m")
        & type_description["event_n"].gt(0)
    ].sort_values("event_n", ascending=False)
    type_rows = types[
        ["next_level_type", "event_n", "long_n", "short_n", "tied_n", "median_mfe_pct", "median_mae_pct"]
    ].copy()
    type_rows["median_mfe_pct"] = type_rows["median_mfe_pct"].map(_fmt_pct)
    type_rows["median_mae_pct"] = type_rows["median_mae_pct"].map(_fmt_pct)
    type_rows = type_rows.rename(
        columns={
            "next_level_type": "Frozen type",
            "event_n": "N",
            "long_n": "LONG N",
            "short_n": "SHORT N",
            "tied_n": "Tied N",
            "median_mfe_pct": "Median MFE",
            "median_mae_pct": "Median MAE",
        }
    )

    tie_impact = _maximum_type_tie_impact(type_description)
    stable = relationships[
        relationships["classification"].eq("CONSISTENT_CANDIDATE_STATE")
    ]
    weak = relationships[
        relationships["classification"].isin(
            {"WEAK_OR_UNSTABLE", "NO_CLEAR_RELATIONSHIP"}
        )
    ]
    split = audit["development_split"]
    return f"""# MNQ ORB V0.2 Stage 3A Step 4 room to next key level

## Scope

This DEVELOPMENT-only analysis uses {audit['input_rows']} Step-1B PRINT breakout
events and only the frozen room-to-next-level fields. Existing normalized
post-signal-bar MFE/MAE at 5m, 15m, 30m, 60m, and session end are the outcomes.
Signal-bar excursion is excluded because its chronology is unknown. No OR-width,
internal-structure, key-level-interaction, pre-open, gap, combined-state,
strategy-performance, filter, optimization, or ML analysis is included.

## State definitions

`room_to_next_level_pct` and `room_to_next_level_or_widths` are the two primary
continuous representations. `room_to_next_level_points` is secondary context;
no preferred representation is selected. Each continuous measure uses ordinary
full-DEVELOPMENT value quintiles calculated separately for each OR duration.
Combined results use their own boundaries and are secondary. Boundaries are
left-inclusive and right-exclusive, except the final interval includes its
upper bound. The full-DEVELOPMENT edges recorded in the CSVs are reused for all
DEV-half and LONG/SHORT comparisons.

The {audit['no_level_ahead_n']} `NO_LEVEL_AHEAD` events remain a separate state
and are never put into a high-distance quintile. The other
{audit['known_level_ahead_n']} events form the distance quintiles.

The input has {split['unique_event_dates']} event-bearing dates. The first
{split['first_half_dates']} ({split['first_half_start']} through
{split['first_half_end']}) form `DEV_FIRST_HALF`; the final
{split['second_half_dates']} ({split['second_half_start']} through
{split['second_half_end']}) form `DEV_SECOND_HALF`.

## Relationship assessment

Patterns must recur in at least three of five clean horizons. Continuous
monotonic patterns require absolute Spearman ordering of at least 0.70. A
relationship also needs a 30m median-MFE contrast of at least one quarter of the
median within-state IQR. `CONSISTENT_CANDIDATE_STATE` additionally requires the
same pattern in full DEV and both halves with at least 10 events in every
inferential half-state. These fixed rules are descriptive guardrails, not
trading thresholds or filters.

{_markdown_table(relation_table)}

Consistent across DEV halves: {_relationship_list(stable)}.

Weak or no-clear: {_relationship_list(weak)}.

No primary representation reaches `POTENTIALLY_INFORMATIVE` or
`CONSISTENT_CANDIDATE_STATE`. Price-normalized room has the largest full-DEV
contrast: more room generally corresponds to more MFE for 15m and 20m ORs, but
the 30m endpoint is nearly flat and the first half is middle-shaped or unclear.
OR-width-normalized room does not confirm that relationship: its Q5 median MFE
is below Q1 for every OR duration, with middle-range or high-room-deterioration
patterns depending on duration and half.

## Distance, MFE, MAE, and total excursion

The table compares the outer quintiles at the clean 30m horizon. Positive MAE
deltas mean more adverse excursion, not improvement. “Total excursion” is the
sum of the median favorable and adverse magnitudes and is descriptive only.

{_markdown_table(pd.DataFrame(q_rows))}

This shows whether any wider-room pattern is primarily a favorable-excursion
shift, an adverse-excursion reduction, or a larger overall excursion. The full
quintile paths for all five horizons are retained in the master CSV; nonlinear
and half-unstable patterns are not promoted to filters.

At 15m and 20m, the price-normalized Q5/Q1 difference is mainly a larger total
excursion: both MFE and MAE rise, so greater room does not reduce adverse
excursion. At 30m, MFE is effectively unchanged while MAE rises. In OR-width
units, Q5 has lower MFE and higher MAE at all three durations. These conflicting
normalizations are a principal reason not to select a preferred representation.

## No known level ahead

`NO_LEVEL_AHEAD` is compared directly with `KNOWN_LEVEL_AHEAD`, independently
of the distance quintiles.

{_markdown_table(no_level_rows)}

Full DEV shows lower 30m median MFE for `NO_LEVEL_AHEAD` at every OR duration.
Its MAE is higher at 15m but lower at 20m and 30m. The contrasts are small
relative to within-state dispersion, and the 30m OR MFE ordering reverses in the
second DEV half, so the categorical difference is weak rather than stable.

## LONG/SHORT and OR-duration context

The largest 30m median-MFE state spans by side identify where differences are
most visible; they do not rank rules.

{_markdown_table(pd.DataFrame(direction_rows))}

## Equal-price ties and next-level type

Exactly {audit['equal_price_tie_n']} events have multiple reference labels at
the same exact nearest price. The frozen Step-1A type remains unchanged and the
analysis-only `next_level_type_tied` flag does not alter distance values or
selection semantics. Distance analyses include these rows. Type results include
both all frozen labels and an untied-only sensitivity view. The largest absolute
30m median-MFE change after removing tied rows is {tie_impact}; therefore type
labels remain descriptive and are not used for superiority claims.

{_markdown_table(type_rows)}

The displayed type table is combined secondary context. The complete type CSV
also separates 15m, 20m, and 30m ORs and records tied counts, LONG/SHORT counts,
eligible shares, and clean outcome distributions. Any type pattern is only a
candidate for a later predeclared hypothesis.

The type table has visible outcome dispersion, but it is also strongly
side-imbalanced, and the two overnight labels contain all 71 ties. Their
untied-only samples shrink materially and can move the median MFE substantially.
That makes a label-specific hypothesis premature; a later investigation would
need a predeclared treatment of ties and direction, neither of which is added
here.

## Output guardrail

The master CSV contains separate 15m/20m/30m results and combined secondary
context. The stability CSV contains full, first-half, and second-half results
for ALL, LONG, and SHORT. The direction CSV contains full-DEVELOPMENT LONG/SHORT
results. Percentages retain the frozen fractional convention. Step 4 is
complete; overall Stage 3A remains incomplete and reserved partitions remain
unexposed.
"""


def _prepare_events(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = set(required_input_columns())
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError("Step-1B input missing required columns: " + ", ".join(missing))
    output = events[required_input_columns()].copy()
    dates = pd.to_datetime(output["session_date"], errors="coerce").dt.normalize()
    if dates.isna().any() or not dates.between(DEVELOPMENT_START, DEVELOPMENT_END).all():
        raise ValueError("Input contains rows outside the frozen DEVELOPMENT dates")
    if not output["breakout_type"].astype(str).str.upper().eq("PRINT").all():
        raise ValueError("Stage 3A Step 4 accepts PRINT events only")
    output["breakout_direction"] = output["breakout_direction"].astype(str).str.upper()
    if not set(output["breakout_direction"]) <= {"LONG", "SHORT"}:
        raise ValueError("Unsupported breakout direction")
    output["or_minutes"] = pd.to_numeric(output["or_minutes"], errors="raise").astype(int)
    if set(output["or_minutes"]) != set(EXPECTED_OR_MINUTES):
        raise ValueError("Input must contain exactly the 15m, 20m, and 30m OR durations")
    for feature in CONTINUOUS_REPRESENTATIONS:
        output[feature] = pd.to_numeric(output[feature], errors="coerce")
    output[NO_LEVEL_REPRESENTATION] = _boolean_series(output[NO_LEVEL_REPRESENTATION])
    known = ~output[NO_LEVEL_REPRESENTATION]
    if output.loc[known, list(CONTINUOUS_REPRESENTATIONS)].isna().any().any():
        raise ValueError("Known-level rows must retain all frozen distance measures")
    if output.loc[output[NO_LEVEL_REPRESENTATION], list(CONTINUOUS_REPRESENTATIONS)].notna().any().any():
        raise ValueError("No-level rows must retain null frozen distance measures")
    output["next_level_type_tied"] = identify_equal_price_nearest_ties(output)
    selection_mismatches = _frozen_selection_mismatches(output)
    if selection_mismatches:
        raise ValueError("Reconstructed nearest-level selection does not match frozen Step 1A")
    output["_dev_half"], split = development_half_labels(output["session_date"])
    audit = {
        "research_scope": "DEVELOPMENT_ONLY",
        "input_rows": int(len(output)),
        "known_level_ahead_n": int(known.sum()),
        "no_level_ahead_n": int(output[NO_LEVEL_REPRESENTATION].sum()),
        "equal_price_tie_n": int(output["next_level_type_tied"].sum()),
        "frozen_selection_mismatch_n": selection_mismatches,
        "available_n_by_representation": {
            feature: int(output[feature].notna().sum())
            for feature in CONTINUOUS_REPRESENTATIONS
        }
        | {NO_LEVEL_REPRESENTATION: int(len(output))},
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
    known = events[~events[NO_LEVEL_REPRESENTATION]]
    for feature in CONTINUOUS_REPRESENTATIONS:
        for duration in (*EXPECTED_OR_MINUTES, "ALL"):
            frame = known if duration == "ALL" else known[known["or_minutes"] == duration]
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
    for feature in REPRESENTATIONS:
        for duration in or_scopes:
            duration_frame = (
                events.copy()
                if duration == "ALL"
                else events[events["or_minutes"] == duration].copy()
            )
            if feature == NO_LEVEL_REPRESENTATION:
                state_specs = [
                    {"state_label": KNOWN_LEVEL_STATE, "state_order": 1, "lower": np.nan, "upper": np.nan, "upper_inclusive": False},
                    {"state_label": NO_LEVEL_STATE, "state_order": 2, "lower": np.nan, "upper": np.nan, "upper_inclusive": False},
                ]
                duration_frame["_state"] = np.where(
                    duration_frame[NO_LEVEL_REPRESENTATION], NO_LEVEL_STATE, KNOWN_LEVEL_STATE
                )
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
                        else segment_frame[segment_frame["breakout_direction"] == direction]
                    )
                    denominator = len(direction_frame)
                    for state in state_specs:
                        state_frame = direction_frame[direction_frame["_state"] == state["state_label"]]
                        for horizon in HORIZONS:
                            rows.append(
                                _summary_row(
                                    state_frame,
                                    feature=feature,
                                    state_kind=state_kind,
                                    duration=duration,
                                    segment=segment,
                                    direction=direction,
                                    state=state,
                                    horizon=horizon,
                                    denominator=denominator,
                                )
                            )
    return pd.DataFrame(rows)


def _build_type_description(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    typed = events.copy()
    typed["_next_type_state"] = typed["next_level_type"].where(
        ~typed[NO_LEVEL_REPRESENTATION], NO_LEVEL_STATE
    )
    type_states = (*ROOM_LEVEL_ORDER, NO_LEVEL_STATE)
    for duration in (*EXPECTED_OR_MINUTES, "ALL"):
        duration_frame = typed if duration == "ALL" else typed[typed["or_minutes"] == duration]
        for tie_scope in TYPE_TIE_SCOPES:
            scope_frame = (
                duration_frame
                if tie_scope == "ALL_FROZEN_LABELS"
                else duration_frame[~duration_frame["next_level_type_tied"]]
            )
            denominator = len(scope_frame)
            for order, level_type in enumerate(type_states, 1):
                state_frame = scope_frame[scope_frame["_next_type_state"] == level_type]
                for horizon in HORIZONS:
                    base = _summary_row(
                        state_frame,
                        feature="next_level_type",
                        state_kind="FROZEN_CATEGORICAL_LABEL",
                        duration=duration,
                        segment="FULL_DEVELOPMENT",
                        direction="ALL",
                        state={
                            "state_label": level_type,
                            "state_order": order,
                            "lower": np.nan,
                            "upper": np.nan,
                            "upper_inclusive": False,
                        },
                        horizon=horizon,
                        denominator=denominator,
                    )
                    base.update(
                        {
                            "tie_scope": tie_scope,
                            "next_level_type": level_type,
                            "type_priority_order": order,
                            "type_inference_guardrail": "DESCRIPTIVE_ONLY_NO_SUPERIORITY_INFERENCE",
                        }
                    )
                    rows.append(base)
    return pd.DataFrame(rows)


def _summary_row(
    state_frame: pd.DataFrame,
    *,
    feature: str,
    state_kind: str,
    duration: int | str,
    segment: str,
    direction: str,
    state: Mapping[str, Any],
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
        "source_feature": feature,
        "representation_role": REPRESENTATION_ROLES.get(feature, "DESCRIPTIVE"),
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
        "eligible_event_n": int(denominator),
        "event_n": int(len(state_frame)),
        "share_of_eligible_events": (
            float(len(state_frame) / denominator) if denominator else np.nan
        ),
        "long_n": int(state_frame["breakout_direction"].eq("LONG").sum()),
        "short_n": int(state_frame["breakout_direction"].eq("SHORT").sum()),
        "tied_n": int(state_frame["next_level_type_tied"].sum()),
        "untied_n": int((~state_frame["next_level_type_tied"]).sum()),
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
    relationship_columns = [
        "source_feature",
        "or_minutes",
        "full_pattern",
        "first_half_pattern",
        "second_half_pattern",
        "classification",
    ]
    output = master.merge(
        relationships[relationship_columns],
        on=["source_feature", "or_minutes"],
        how="left",
        validate="many_to_one",
    )
    secondary = output["source_feature"].eq("room_to_next_level_points")
    combined = output["or_minutes"].astype(str).eq("ALL")
    output.loc[secondary, "classification"] = "SECONDARY_DESCRIPTIVE_ONLY"
    output.loc[combined & ~secondary, "classification"] = "SECONDARY_CONTEXT_NOT_CLASSIFIED"
    return output


def _ordered_state_slice(
    table: pd.DataFrame,
    *,
    representation: str,
    duration: int,
    segment: str,
    direction: str,
    horizon: str,
) -> pd.DataFrame:
    return table[
        table["source_feature"].eq(representation)
        & table["or_minutes"].astype(str).eq(str(duration))
        & table["dev_segment"].eq(segment)
        & table["breakout_direction"].eq(direction)
        & table["outcome_horizon"].eq(horizon)
    ].sort_values("state_order").reset_index(drop=True)


def _continuous_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    mfe = pd.to_numeric(frame["median_mfe_pct"], errors="coerce").to_numpy(dtype=float)
    mae = pd.to_numeric(frame["median_mae_pct"], errors="coerce").to_numpy(dtype=float)
    if len(mfe) < 3 or not np.isfinite(mfe).all() or not np.isfinite(mae).all():
        return "NO_CLEAR_PATTERN", np.nan
    ordering = float(pd.Series(np.arange(len(mfe))).corr(pd.Series(mfe), method="spearman"))
    if mfe[-1] < np.median(mfe[:-1]) and mae[-1] > np.median(mae[:-1]):
        return "HIGH_ROOM_DETERIORATION", ordering
    if ordering >= 0.70:
        return "MONOTONIC_MORE_ROOM_MORE_MFE", ordering
    if ordering <= -0.70:
        return "MONOTONIC_MORE_ROOM_LESS_MFE", ordering
    peak = int(np.argmax(mfe))
    if peak not in {0, len(mfe) - 1} and mfe[peak] > mfe[0] and mfe[peak] > mfe[-1]:
        return "MIDDLE_RANGE_PREFERENCE", ordering
    return "NO_CLEAR_PATTERN", ordering


def _no_level_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    if len(frame) != 2 or frame["median_mfe_pct"].isna().any():
        return "NO_CLEAR_PATTERN", np.nan
    values = dict(zip(frame["state_label"], frame["median_mfe_pct"].astype(float)))
    difference = values[NO_LEVEL_STATE] - values[KNOWN_LEVEL_STATE]
    if difference > 0:
        return "NO_LEVEL_AHEAD_MORE_MFE", difference
    if difference < 0:
        return "KNOWN_LEVEL_AHEAD_MORE_MFE", difference
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


def _frozen_selection_mismatches(events: pd.DataFrame) -> int:
    mismatches = 0
    for _, row in events.iterrows():
        direction = str(row["breakout_direction"]).upper()
        boundary = _finite_number(row["or_high"] if direction == "LONG" else row["or_low"])
        candidates: list[tuple[float, int, str, float]] = []
        if boundary is not None:
            for priority, level_name in enumerate(ROOM_LEVEL_ORDER):
                level = _valid_level(row, level_name)
                if level is None:
                    continue
                distance = level - boundary if direction == "LONG" else boundary - level
                if distance > 0:
                    candidates.append((float(distance), priority, level_name, level))
        if not candidates:
            if not bool(row[NO_LEVEL_REPRESENTATION]):
                mismatches += 1
            continue
        _, _, expected_type, expected_price = min(candidates)
        observed_price = _finite_number(row["next_level_price"])
        if (
            bool(row[NO_LEVEL_REPRESENTATION])
            or str(row["next_level_type"]) != expected_type
            or observed_price != expected_price
        ):
            mismatches += 1
    return mismatches


def _maximum_type_tie_impact(type_description: pd.DataFrame) -> str:
    frame = type_description[
        type_description["outcome_horizon"].eq("30m")
        & type_description["or_minutes"].astype(str).isin({"15", "20", "30"})
        & type_description["next_level_type"].ne(NO_LEVEL_STATE)
    ]
    pivot = frame.pivot_table(
        index=["or_minutes", "next_level_type"],
        columns="tie_scope",
        values="median_mfe_pct",
        aggfunc="first",
    ).dropna()
    if pivot.empty:
        return "NA"
    delta = (
        pivot["ALL_FROZEN_LABELS"] - pivot["UNTIED_ONLY_SENSITIVITY"]
    ).abs()
    duration, level_type = delta.idxmax()
    return f"{_fmt_pct(float(delta.max()))} ({duration}m {level_type})"


def _iqr_scaled_contrast(frame: pd.DataFrame) -> float:
    contrast = _numeric_range(frame["median_mfe_pct"])
    widths = pd.to_numeric(frame["mfe_p75_pct"], errors="coerce") - pd.to_numeric(
        frame["mfe_p25_pct"], errors="coerce"
    )
    scale = float(widths.dropna().median()) if not widths.dropna().empty else np.nan
    return float(contrast / scale) if np.isfinite(scale) and scale > 0 else np.nan


def _valid_level(row: Mapping[str, Any], level_name: str) -> float | None:
    level = _finite_number(row.get(level_name))
    if level is None:
        return None
    available_name = f"level_{level_name}_available"
    if available_name in row and not _truthy(row.get(available_name)):
        return None
    return level


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


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
        f"{REPRESENTATION_TITLES[row.source_feature]} / {int(row.or_minutes)}m"
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
