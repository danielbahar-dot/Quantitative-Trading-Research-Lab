"""Build DEVELOPMENT-only MNQ ORB V0.2 Stage-3A preparation tables.

This module joins frozen Stage-2 causal features onto frozen PRINT breakout
events and derives only room to the next already-known key level.  It does not
load price data, alter signal/execution logic, calculate strategy performance,
or register an experiment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


JOIN_KEYS = ("session_date", "contract", "or_minutes")
DEVELOPMENT_START = pd.Timestamp("2024-06-21")
DEVELOPMENT_END = pd.Timestamp("2025-06-30")

# Equal-price candidates resolve to the first item in this explicit order.
# The order follows the approved Stage-3A Step-1A source list.
ROOM_LEVEL_ORDER = (
    "previous_day_high",
    "previous_day_low",
    "overnight_high",
    "overnight_low",
    "asia_high",
    "asia_low",
    "london_high",
    "london_low",
    "ny_premarket_high",
    "ny_premarket_low",
)

ROOM_FIELDS = (
    "next_level_type",
    "next_level_price",
    "room_to_next_level_points",
    "room_to_next_level_pct",
    "room_to_next_level_or_widths",
    "no_level_ahead",
)

DIRECTIONAL_FIELDS = (
    "or_breakout_alignment",
    "directional_or_net_move_points",
    "directional_or_net_move_pct",
    "directional_clv",
)


def build_stage3a_breakout_events(
    features: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Join Stage-2 features to PRINT events and add room-to-level fields.

    ``room_to_next_level_pct`` uses OR midpoint as its price denominator.  This
    matches the frozen Stage-2 key-level distance-percent convention.
    """

    _validate_inputs(features, outcomes)
    outcome_columns = list(outcomes.columns)
    feature_columns = list(features.columns)
    overlapping = (set(outcome_columns) & set(feature_columns)) - set(JOIN_KEYS)
    if overlapping:
        raise ValueError(
            "Frozen inputs contain unexpected non-key column overlaps: "
            + ", ".join(sorted(overlapping))
        )

    # Copies consolidate the wide frozen frames before pandas performs the
    # many-to-one merge, avoiding fragmentation without changing either input.
    joined = outcomes.copy().merge(
        features.copy(),
        how="left",
        on=list(JOIN_KEYS),
        sort=False,
        validate="many_to_one",
        indicator=True,
    )
    unmatched = int(joined["_merge"].ne("both").sum())
    joined = joined.drop(columns="_merge")

    room = joined.apply(room_to_next_level, axis=1, result_type="expand")
    room.columns = list(ROOM_FIELDS)
    output = pd.concat([joined, room], axis=1)
    output = output[
        outcome_columns
        + [column for column in feature_columns if column not in JOIN_KEYS]
        + list(ROOM_FIELDS)
    ]

    audit = {
        "input_outcome_rows": int(len(outcomes)),
        "output_rows": int(len(output)),
        "unmatched_joins": unmatched,
        "no_level_ahead_count": int(output["no_level_ahead"].sum()),
        "missing_candidate_level_counts": _missing_candidate_counts(joined),
    }
    return output, audit


def room_to_next_level(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return nearest eligible known level for one LONG or SHORT event."""

    direction = str(row.get("breakout_direction", "")).upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Unsupported breakout direction: {direction!r}")

    boundary_name = "or_high" if direction == "LONG" else "or_low"
    boundary = _finite_number(row.get(boundary_name))
    if boundary is None:
        return _no_level_result()

    candidates: list[tuple[float, int, str, float]] = []
    for priority, level_name in enumerate(ROOM_LEVEL_ORDER):
        level = _valid_level(row, level_name)
        if level is None:
            continue
        distance = level - boundary if direction == "LONG" else boundary - level
        if distance > 0:
            candidates.append((float(distance), priority, level_name, level))

    if not candidates:
        return _no_level_result()

    distance, _, level_name, level = min(candidates)
    or_mid = _finite_number(row.get("or_mid"))
    or_width = _finite_number(row.get("or_width_points"))
    return {
        "next_level_type": level_name,
        "next_level_price": level,
        "room_to_next_level_points": distance,
        "room_to_next_level_pct": _positive_divide(distance, or_mid),
        "room_to_next_level_or_widths": _positive_divide(distance, or_width),
        "no_level_ahead": False,
    }


def build_directional_state_events(
    step1a_events: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Add only the predeclared Step-1B directional OR state fields."""

    _validate_step1b_input(step1a_events)
    existing = set(DIRECTIONAL_FIELDS) & set(step1a_events.columns)
    if existing:
        raise ValueError(
            "Step-1A input already contains Step-1B fields: "
            + ", ".join(sorted(existing))
        )

    output = step1a_events.copy()
    breakout_direction = output["breakout_direction"].astype(str).str.upper()
    or_direction = output["or_direction"].astype(str).str.upper()
    long_mask = breakout_direction.eq("LONG")
    short_mask = breakout_direction.eq("SHORT")

    alignment = pd.Series(pd.NA, index=output.index, dtype="object")
    alignment.loc[or_direction.eq("FLAT") & (long_mask | short_mask)] = "FLAT"
    alignment.loc[
        (long_mask & or_direction.eq("UP"))
        | (short_mask & or_direction.eq("DOWN"))
    ] = "ALIGNED"
    alignment.loc[
        (long_mask & or_direction.eq("DOWN"))
        | (short_mask & or_direction.eq("UP"))
    ] = "OPPOSED"

    or_open = pd.to_numeric(output["or_open"], errors="coerce")
    or_close = pd.to_numeric(output["or_close"], errors="coerce")
    signed_points = or_close - or_open
    directional_points = signed_points.where(long_mask, -signed_points).where(
        long_mask | short_mask
    )

    frozen_net_points = pd.to_numeric(output["or_net_move_points"], errors="coerce")
    comparable = signed_points.notna() & frozen_net_points.notna()
    if not np.allclose(
        signed_points.loc[comparable], frozen_net_points.loc[comparable]
    ):
        raise ValueError("Frozen OR net-move points do not reconcile to OR close - OR open")

    frozen_net_pct = pd.to_numeric(output["or_net_move_pct"], errors="coerce")
    directional_pct = frozen_net_pct.where(long_mask, -frozen_net_pct).where(
        long_mask | short_mask
    )
    or_clv = pd.to_numeric(output["or_clv"], errors="coerce")
    directional_clv = or_clv.where(long_mask, 1.0 - or_clv).where(
        long_mask | short_mask
    )

    output["or_breakout_alignment"] = alignment
    output["directional_or_net_move_points"] = directional_points
    output["directional_or_net_move_pct"] = directional_pct
    output["directional_clv"] = directional_clv

    alignment_counts = {
        state: int(output["or_breakout_alignment"].eq(state).sum())
        for state in ("ALIGNED", "OPPOSED", "FLAT")
    }
    audit = {
        "input_rows": int(len(step1a_events)),
        "output_rows": int(len(output)),
        "alignment_counts": alignment_counts,
        "missing_alignment_count": int(output["or_breakout_alignment"].isna().sum()),
        "directional_clv": _series_stats(output["directional_clv"]),
        "directional_or_net_move_points": _series_stats(
            output["directional_or_net_move_points"]
        ),
        "directional_or_net_move_pct": _series_stats(
            output["directional_or_net_move_pct"]
        ),
        "step1a_equal_price_tie_count": count_step1a_nearest_level_ties(output),
    }
    return output, audit


def count_step1a_nearest_level_ties(events: pd.DataFrame) -> int:
    """Count events with multiple eligible nearest levels at one exact price."""

    ties = 0
    for _, row in events.iterrows():
        direction = str(row.get("breakout_direction", "")).upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        boundary_name = "or_high" if direction == "LONG" else "or_low"
        boundary = _finite_number(row.get(boundary_name))
        if boundary is None:
            continue
        distances = []
        for level_name in ROOM_LEVEL_ORDER:
            level = _valid_level(row, level_name)
            if level is None:
                continue
            distance = level - boundary if direction == "LONG" else boundary - level
            if distance > 0:
                distances.append(float(distance))
        if distances:
            nearest = min(distances)
            ties += sum(distance == nearest for distance in distances) > 1
    return int(ties)


def render_step1b_audit_report(
    output: pd.DataFrame,
    audit: Mapping[str, Any],
) -> str:
    """Render the requested non-performance Step-1B audit."""

    alignment = audit["alignment_counts"]
    clv = audit["directional_clv"]
    points = audit["directional_or_net_move_points"]
    pct = audit["directional_or_net_move_pct"]
    return f"""# MNQ ORB V0.2 Stage 3A Step 1B audit

DEVELOPMENT-only dataset preparation audit. No outcome characterization,
state bucketing, strategy performance, filters, or optimization were run.

## Counts

- Input Step-1A rows: {audit['input_rows']}
- Output Step-1B rows: {audit['output_rows']}
- ALIGNED: {alignment['ALIGNED']}
- OPPOSED: {alignment['OPPOSED']}
- FLAT: {alignment['FLAT']}
- Missing alignment: {audit['missing_alignment_count']}
- Step-1A equal-price nearest-level ties: {audit['step1a_equal_price_tie_count']}

The tie count is the number of event rows with two or more eligible candidate
levels at the exact nearest price. Step-1A selection order and values are
unchanged.

## Directional-state ranges

| field | min | median | max |
| --- | ---: | ---: | ---: |
| directional_clv | {_stat_value(clv['min'])} | {_stat_value(clv['median'])} | {_stat_value(clv['max'])} |
| directional_or_net_move_points | {_stat_value(points['min'])} | {_stat_value(points['median'])} | {_stat_value(points['max'])} |
| directional_or_net_move_pct | {_stat_value(pct['min'])} | {_stat_value(pct['median'])} | {_stat_value(pct['max'])} |

`directional_or_net_move_pct` carries forward the frozen Stage-2 OR-open
normalization: LONG uses `or_net_move_pct`, while SHORT uses its sign inverse.
Existing `or_efficiency` values are carried forward unchanged.

## LONG examples

{_directional_example_table(output, 'LONG')}

## SHORT examples

{_directional_example_table(output, 'SHORT')}
"""


def render_audit_report(output: pd.DataFrame, audit: Mapping[str, Any]) -> str:
    """Render the requested non-performance Step-1A audit."""

    missing_lines = "\n".join(
        f"- `{level}`: {count}"
        for level, count in audit["missing_candidate_level_counts"].items()
    )
    long_examples = _example_table(output, "LONG")
    short_examples = _example_table(output, "SHORT")
    order = " -> ".join(f"`{level}`" for level in ROOM_LEVEL_ORDER)
    return f"""# MNQ ORB V0.2 Stage 3A Step 1A audit

DEVELOPMENT-only construction audit. This artifact does not characterize
performance, create filters, alter the frozen PRINT signal, or register a
Stage-3 experiment.

## Construction

- Join key: `session_date`, `contract`, `or_minutes`
- Input PRINT outcome rows: {audit['input_outcome_rows']}
- Output event rows: {audit['output_rows']}
- Unmatched joins: {audit['unmatched_joins']}
- `no_level_ahead` rows: {audit['no_level_ahead_count']}
- `room_to_next_level_pct`: point distance divided by frozen `or_mid`, matching
  the Stage-2 key-level distance-percent normalization.
- Equal-price tie order: {order}

## Missing candidate-level counts

Counts are event-row counts for unavailable or non-numeric frozen candidates.

{missing_lines}

## LONG examples

{long_examples}

## SHORT examples

{short_examples}
"""


def _validate_inputs(features: pd.DataFrame, outcomes: pd.DataFrame) -> None:
    required_features = set(JOIN_KEYS) | {
        "or_high",
        "or_low",
        "or_mid",
        "or_width_points",
        *ROOM_LEVEL_ORDER,
    }
    required_outcomes = set(JOIN_KEYS) | {"breakout_type", "breakout_direction"}
    for label, frame, required in (
        ("feature audit", features, required_features),
        ("PRINT outcomes", outcomes, required_outcomes),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} missing required columns: {', '.join(sorted(missing))}")
        dates = pd.to_datetime(frame["session_date"], errors="raise")
        if not dates.between(DEVELOPMENT_START, DEVELOPMENT_END).all():
            raise ValueError(f"{label} contains rows outside DEVELOPMENT")
    if features.duplicated(list(JOIN_KEYS)).any():
        raise ValueError("Feature audit must be unique on the Stage-3A join key")
    if not outcomes["breakout_type"].astype(str).str.upper().eq("PRINT").all():
        raise ValueError("Stage-3A Step 1A accepts PRINT outcomes only")


def _validate_step1b_input(events: pd.DataFrame) -> None:
    required = {
        "session_date",
        "breakout_type",
        "breakout_direction",
        "or_direction",
        "or_open",
        "or_close",
        "or_high",
        "or_low",
        "or_net_move_points",
        "or_net_move_pct",
        "or_clv",
        "or_efficiency",
        "next_level_type",
        "next_level_price",
        *ROOM_LEVEL_ORDER,
    }
    missing = required - set(events.columns)
    if missing:
        raise ValueError(
            "Step-1A input missing required columns: " + ", ".join(sorted(missing))
        )
    dates = pd.to_datetime(events["session_date"], errors="raise")
    if not dates.between(DEVELOPMENT_START, DEVELOPMENT_END).all():
        raise ValueError("Step-1A input contains rows outside DEVELOPMENT")
    if not events["breakout_type"].astype(str).str.upper().eq("PRINT").all():
        raise ValueError("Stage-3A Step 1B accepts PRINT outcomes only")


def _valid_level(row: Mapping[str, Any], level_name: str) -> float | None:
    level = _finite_number(row.get(level_name))
    if level is None:
        return None
    availability_name = f"level_{level_name}_available"
    if availability_name in row and not _truthy(row.get(availability_name)):
        return None
    return level


def _missing_candidate_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    for level_name in ROOM_LEVEL_ORDER:
        numeric = pd.to_numeric(frame[level_name], errors="coerce")
        valid = numeric.notna() & np.isfinite(numeric)
        availability_name = f"level_{level_name}_available"
        if availability_name in frame:
            valid &= frame[availability_name].map(_truthy)
        counts[level_name] = int((~valid).sum())
    return counts


def _example_table(output: pd.DataFrame, direction: str) -> str:
    columns = [
        "session_date",
        "contract",
        "or_minutes",
        "breakout_timestamp",
        "breakout_direction",
        "or_high",
        "or_low",
        *ROOM_FIELDS,
    ]
    examples = output.loc[
        output["breakout_direction"].astype(str).str.upper().eq(direction), columns
    ].head(5)
    if examples.empty:
        return "No examples available."
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(_markdown_value(value) for value in row) + " |"
        for row in examples.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def _directional_example_table(output: pd.DataFrame, direction: str) -> str:
    columns = [
        "session_date",
        "contract",
        "or_minutes",
        "breakout_timestamp",
        "breakout_direction",
        "or_direction",
        "or_open",
        "or_close",
        "or_breakout_alignment",
        "directional_or_net_move_points",
        "directional_or_net_move_pct",
        "directional_clv",
        "or_efficiency",
    ]
    examples = output.loc[
        output["breakout_direction"].astype(str).str.upper().eq(direction), columns
    ].head(5)
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(_markdown_value(value) for value in row) + " |"
        for row in examples.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def _no_level_result() -> dict[str, Any]:
    return {
        "next_level_type": None,
        "next_level_price": np.nan,
        "room_to_next_level_points": np.nan,
        "room_to_next_level_pct": np.nan,
        "room_to_next_level_or_widths": np.nan,
        "no_level_ahead": True,
    }


def _finite_number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _positive_divide(numerator: float, denominator: float | None) -> float:
    if denominator is None or denominator <= 0:
        return np.nan
    return numerator / denominator


def _truthy(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _markdown_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.8g}"
    return str(value).replace("|", "\\|")


def _series_stats(series: pd.Series) -> dict[str, float]:
    numeric = pd.to_numeric(series, errors="coerce")
    return {
        "min": float(numeric.min()),
        "median": float(numeric.median()),
        "max": float(numeric.max()),
    }


def _stat_value(value: float) -> str:
    return f"{value:.10g}"
