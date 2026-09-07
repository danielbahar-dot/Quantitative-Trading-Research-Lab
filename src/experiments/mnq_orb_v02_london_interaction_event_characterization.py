"""DEVELOPMENT-only London 30-minute interaction event characterization.

This module preserves the frozen Stage-2 London-level primitives and existing
PRINT ORB outcomes. It reconstructs bar-end timestamps for the interaction
event study without changing signal, execution, or feature definitions.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_features import _excursion_fields
from src.experiments.mnq_orb_v02_width_characterization import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
)
from src.features.market_context import ET_TIMEZONE, level_interaction


EXPERIMENT_ID = "mnq_orb_v0_2_stage3b_london_interaction_event_characterization"
HYPOTHESIS_ID = "HYP-LONDON-ACCEPTANCE-01"
OR_MINUTES = 30
HORIZONS = ("5m", "15m", "30m", "60m", "session_end")
PRIMARY_STATES = ("CLOSE_THROUGH", "SWEEP")
ALL_INTERACTION_STATES = (
    "TOUCH",
    "TRADE_THROUGH",
    "CLOSE_THROUGH",
    "REJECT",
    "SWEEP",
)
LEVEL_TYPES = ("LONDON_HIGH", "LONDON_LOW")
DEV_SEGMENTS = ("FULL_DEVELOPMENT", "DEV_FIRST_HALF", "DEV_SECOND_HALF")
STAGE3A_FIRST_HALF_END = date(2024, 12, 20)
STAGE3A_SECOND_HALF_START = date(2024, 12, 23)
MIN_INFERENCE_N = 10


def assert_development_input_path(path: str | Path) -> None:
    """Reject paths that are not explicitly labeled as DEVELOPMENT inputs."""

    text = str(path).replace("\\", "/").lower()
    if "validation" in text or "oos_burned" in text:
        raise ValueError("Reserved Validation/OOS_BURNED input is prohibited")
    if "_dev_" not in text and "_development" not in text:
        raise ValueError("Stage 3B requires an explicitly DEVELOPMENT-labeled input")


def required_feature_columns() -> list[str]:
    columns = [
        "session_date",
        "contract",
        "or_minutes",
        "or_feature_available",
        "or_available_at",
        "or_last_bar_end",
        "or_high",
        "or_low",
        "or_open",
        "or_close",
        "or_width_points",
    ]
    for level in ("london_high", "london_low"):
        columns.append(f"{level}_price")
        columns.extend(
            f"level_{level}_{field}"
            for field in (
                "available",
                "start_side",
                "touched",
                "traded_through",
                "closed_through",
                "rejected",
                "swept",
            )
        )
    return columns


def required_outcome_columns() -> list[str]:
    columns = [
        "session_date",
        "contract",
        "or_minutes",
        "breakout_type",
        "breakout_direction",
        "breakout_timestamp",
        "breakout_price",
        "feature_row_key",
        "outcome_definition",
    ]
    for horizon in HORIZONS:
        columns.extend(
            [
                f"post_signal_bar_{horizon}_complete",
                f"post_signal_bar_{horizon}_bars",
                f"post_signal_bar_{horizon}_end_timestamp",
                f"post_signal_bar_{horizon}_mfe_points",
                f"post_signal_bar_{horizon}_mae_points",
                f"post_signal_bar_{horizon}_mfe_pct",
                f"post_signal_bar_{horizon}_mae_pct",
            ]
        )
    return columns


def required_price_columns() -> list[str]:
    return [
        "timestamp_et",
        "session_date",
        "contract",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]


def map_level_directions(level_type: str) -> tuple[str, str]:
    """Return the declared acceptance and rejection directions."""

    if level_type == "LONDON_HIGH":
        return "UP", "DOWN"
    if level_type == "LONDON_LOW":
        return "DOWN", "UP"
    raise ValueError(f"Unsupported London level type: {level_type}")


def derive_frozen_interaction_state(row: Mapping[str, Any], level: str) -> str:
    """Map one level's frozen primitives without changing their semantics."""

    prefix = f"level_{level}_"
    if not _as_bool(row[f"{prefix}available"]):
        return "UNAVAILABLE"
    if _as_bool(row[f"{prefix}swept"]):
        return "SWEEP"
    if _as_bool(row[f"{prefix}closed_through"]):
        return "CLOSE_THROUGH"
    if _as_bool(row[f"{prefix}rejected"]):
        return "REJECT"
    if _as_bool(row[f"{prefix}traded_through"]):
        return "TRADE_THROUGH"
    if _as_bool(row[f"{prefix}touched"]):
        return "TOUCH"
    return "NO_INTERACTION"


def first_interaction_timestamps(
    or_bars: pd.DataFrame,
    *,
    level_price: float,
    start_side: str,
) -> tuple[pd.Timestamp | pd.NaT, pd.Timestamp | pd.NaT]:
    """Return first touch and first strict trade-through bar-end timestamps."""

    touched = or_bars.loc[
        or_bars["low"].le(level_price) & or_bars["high"].ge(level_price)
    ]
    first_touch = touched.index[0] if not touched.empty else pd.NaT
    if start_side == "BELOW":
        traded = or_bars.loc[or_bars["high"].gt(level_price)]
    elif start_side == "ABOVE":
        traded = or_bars.loc[or_bars["low"].lt(level_price)]
    elif start_side == "AT":
        traded = or_bars.iloc[0:0]
    else:
        raise ValueError(f"Unsupported frozen start side: {start_side}")
    first_trade = traded.index[0] if not traded.empty else pd.NaT
    return first_touch, first_trade


def build_london_interaction_events(
    features: pd.DataFrame,
    prices: pd.DataFrame,
    orb_outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one row per frozen London High/Low 30m interaction event."""

    input_30m = features.loc[features["or_minutes"].eq(OR_MINUTES)].copy()
    input_feature_sessions = int(len(input_30m))
    unavailable_or_sessions = int(
        (~input_30m["or_feature_available"].map(_as_bool)).sum()
    )
    feature_source = _prepare_features(features)
    price_source = _prepare_prices(prices)
    outcome_source = _prepare_outcomes(orb_outcomes)
    price_groups = {
        key: group.sort_index()
        for key, group in price_source.groupby("session_date", sort=True)
    }
    outcome_groups = {
        key: group.sort_values(
            ["breakout_timestamp", "breakout_direction"], kind="mergesort"
        )
        for key, group in outcome_source.groupby("session_date", sort=True)
    }

    rows: list[dict[str, Any]] = []
    primitive_mismatches = 0
    timestamp_mismatches = 0
    for feature in feature_source.to_dict("records"):
        session_date = feature["session_date"]
        session_bars = price_groups.get(session_date)
        if session_bars is None or session_bars.empty:
            raise ValueError(f"Missing DEVELOPMENT price bars for {session_date}")
        contract = str(feature["contract"])
        if set(session_bars["contract"].astype(str)) != {contract}:
            raise ValueError(f"Contract mismatch in DEVELOPMENT prices for {session_date}")
        or_close_timestamp = _as_et_timestamp(feature["or_available_at"])
        last_bar_end = _as_et_timestamp(feature["or_last_bar_end"])
        if or_close_timestamp != last_bar_end:
            raise AssertionError(f"OR availability/last-bar mismatch for {session_date}")
        expected_or_close = pd.Timestamp.combine(session_date, time(10, 0)).tz_localize(
            ET_TIMEZONE
        )
        if or_close_timestamp != expected_or_close:
            raise AssertionError(f"30m OR close is not 10:00 ET for {session_date}")
        first_or_bar = pd.Timestamp.combine(session_date, time(9, 31)).tz_localize(
            ET_TIMEZONE
        )
        or_bars = session_bars.loc[
            (session_bars.index >= first_or_bar)
            & (session_bars.index <= or_close_timestamp)
        ]
        expected_or_index = pd.date_range(first_or_bar, or_close_timestamp, freq="min")
        if not or_bars.index.equals(expected_or_index):
            raise AssertionError(f"Incomplete 30m OR bar sequence for {session_date}")
        if not np.isclose(
            float(or_bars.iloc[-1]["close"]), float(feature["or_close"]), atol=1e-9
        ):
            raise AssertionError(f"OR close price mismatch for {session_date}")

        session_orbs = outcome_groups.get(session_date, outcome_source.iloc[0:0]).copy()
        session_orbs = session_orbs.loc[
            session_orbs["breakout_timestamp"].gt(or_close_timestamp)
        ]
        if not session_orbs.empty and set(session_orbs["contract"].astype(str)) != {
            contract
        }:
            raise ValueError(f"Contract mismatch in frozen ORB outcomes for {session_date}")

        for level_name, level_type in (
            ("london_high", "LONDON_HIGH"),
            ("london_low", "LONDON_LOW"),
        ):
            state = derive_frozen_interaction_state(feature, level_name)
            if state in {"UNAVAILABLE", "NO_INTERACTION"}:
                continue
            level_price = float(feature[f"{level_name}_price"])
            prefix = f"level_{level_name}_"
            start_side = str(feature[f"{prefix}start_side"])
            recomputed = level_interaction(
                level=level_price,
                or_open=float(feature["or_open"]),
                or_high=float(feature["or_high"]),
                or_low=float(feature["or_low"]),
                or_close=float(feature["or_close"]),
                or_mid=(float(feature["or_high"]) + float(feature["or_low"])) / 2.0,
            )
            for primitive in (
                "available",
                "touched",
                "traded_through",
                "closed_through",
                "rejected",
                "swept",
            ):
                if _as_bool(feature[f"{prefix}{primitive}"]) != bool(
                    recomputed[primitive]
                ):
                    primitive_mismatches += 1
            if start_side != recomputed["start_side"]:
                primitive_mismatches += 1

            first_touch, first_trade = first_interaction_timestamps(
                or_bars, level_price=level_price, start_side=start_side
            )
            if pd.isna(first_touch) != (not _as_bool(feature[f"{prefix}touched"])):
                timestamp_mismatches += 1
            if pd.isna(first_trade) != (
                not _as_bool(feature[f"{prefix}traded_through"])
            ):
                timestamp_mismatches += 1

            acceptance_direction, declared_rejection_direction = map_level_directions(
                level_type
            )
            frozen_trade_direction = (
                "UP" if start_side == "BELOW" else ("DOWN" if start_side == "ABOVE" else None)
            )
            frozen_rejection_direction = _opposite_direction(frozen_trade_direction)
            if state in {"SWEEP", "REJECT"}:
                interaction_direction = frozen_rejection_direction
            elif state in {"CLOSE_THROUGH", "TRADE_THROUGH"}:
                interaction_direction = frozen_trade_direction
            else:
                interaction_direction = acceptance_direction
            hypothesis_directional_context = bool(
                state in PRIMARY_STATES
                and frozen_trade_direction == acceptance_direction
            )

            first_orb = session_orbs.iloc[0] if not session_orbs.empty else None
            existing_orb_present = first_orb is not None
            orb_direction = (
                str(first_orb["breakout_direction"]) if existing_orb_present else None
            )
            orb_price_direction = _orb_to_price_direction(orb_direction)
            same_direction_present = bool(
                not session_orbs.empty
                and session_orbs["breakout_direction"]
                .map(_orb_to_price_direction)
                .eq(interaction_direction)
                .any()
            )
            opposite_direction_present = bool(
                not session_orbs.empty
                and session_orbs["breakout_direction"]
                .map(_orb_to_price_direction)
                .eq(_opposite_direction(interaction_direction))
                .any()
            )
            if not existing_orb_present:
                orb_group = "NO_ORB"
            elif orb_price_direction == interaction_direction:
                orb_group = "SAME_DIRECTION_ORB"
            else:
                orb_group = "OPPOSITE_DIRECTION_ORB"
            orb_timestamp = (
                _as_et_timestamp(first_orb["breakout_timestamp"])
                if existing_orb_present
                else pd.NaT
            )
            orb_reference_price = (
                float(first_orb["breakout_price"])
                if existing_orb_present
                else np.nan
            )
            or_close_price = float(feature["or_close"])
            signed_level_to_close = or_close_price - level_price
            signed_close_to_orb = (
                orb_reference_price - or_close_price
                if existing_orb_present
                else np.nan
            )
            row = {
                "event_id": f"{session_date.isoformat()}_{level_type}",
                "hypothesis_id": HYPOTHESIS_ID,
                "research_scope": "DEVELOPMENT_ONLY",
                "session_date": session_date,
                "contract": contract,
                "or_minutes": OR_MINUTES,
                "dev_segment": development_segment(session_date),
                "london_level_type": level_type,
                "london_level_price": level_price,
                "interaction_state": state,
                "frozen_start_side": start_side,
                "frozen_touched": _as_bool(feature[f"{prefix}touched"]),
                "frozen_traded_through": _as_bool(
                    feature[f"{prefix}traded_through"]
                ),
                "frozen_closed_through": _as_bool(
                    feature[f"{prefix}closed_through"]
                ),
                "frozen_rejected": _as_bool(feature[f"{prefix}rejected"]),
                "frozen_swept": _as_bool(feature[f"{prefix}swept"]),
                "first_touch_timestamp": first_touch,
                "first_trade_through_timestamp": first_trade,
                "30m_or_close_timestamp": or_close_timestamp,
                "interaction_state_confirmation_timestamp": or_close_timestamp,
                "acceptance_confirmation_timestamp": (
                    or_close_timestamp if state == "CLOSE_THROUGH" else pd.NaT
                ),
                "timestamp_semantics": "bar_end_time",
                "first_trade_through_state_knowledge": "RETROSPECTIVE_DESCRIPTIVE",
                "or_close_state_knowledge": "CAUSAL_STATE_KNOWN",
                "or_high": float(feature["or_high"]),
                "or_low": float(feature["or_low"]),
                "or_open": float(feature["or_open"]),
                "or_close": or_close_price,
                "or_width_points": float(feature["or_width_points"]),
                "acceptance_direction": acceptance_direction,
                "declared_rejection_direction": declared_rejection_direction,
                "frozen_trade_through_direction": frozen_trade_direction,
                "frozen_rejection_direction": frozen_rejection_direction,
                "interaction_direction": interaction_direction,
                "hypothesis_directional_context": hypothesis_directional_context,
                "existing_print_orb_present": existing_orb_present,
                "existing_print_orb_count": int(len(session_orbs)),
                "same_direction_orb_present": same_direction_present,
                "opposite_direction_orb_present": opposite_direction_present,
                "orb_confirmation_group": orb_group,
                "orb_direction": orb_direction,
                "orb_signal_timestamp": orb_timestamp,
                "orb_reference_timestamp": orb_timestamp,
                "orb_reference_price": orb_reference_price,
                "orb_selection_rule": "FIRST_LATER_VALIDATED_30M_PRINT_BY_TIMESTAMP",
                "minutes_from_trade_through_to_or_close": _minutes_between(
                    first_trade, or_close_timestamp
                ),
                "minutes_from_or_close_to_orb_signal": _minutes_between(
                    or_close_timestamp, orb_timestamp
                ),
                "first_trade_through_minutes_after_0930": _minutes_after_open(
                    session_date, first_trade
                ),
                "level_to_or_close_displacement_points": signed_level_to_close,
                "level_to_or_close_directional_displacement_points": _directional_value(
                    signed_level_to_close, interaction_direction
                ),
                "level_to_or_close_directional_displacement_pct": _safe_divide(
                    _directional_value(signed_level_to_close, interaction_direction),
                    level_price,
                ),
                "or_close_to_orb_displacement_points": signed_close_to_orb,
                "or_close_to_orb_directional_displacement_points": _directional_value(
                    signed_close_to_orb, interaction_direction
                ),
                "or_close_to_orb_directional_displacement_pct": _safe_divide(
                    _directional_value(signed_close_to_orb, interaction_direction),
                    or_close_price,
                ),
                "level_to_orb_directional_displacement_points": _directional_value(
                    orb_reference_price - level_price
                    if existing_orb_present
                    else np.nan,
                    interaction_direction,
                ),
                "level_to_orb_directional_displacement_pct": _safe_divide(
                    _directional_value(
                        orb_reference_price - level_price
                        if existing_orb_present
                        else np.nan,
                        interaction_direction,
                    ),
                    level_price,
                ),
            }
            row.update(
                _anchor_outcomes(
                    session_bars,
                    anchor_timestamp=first_trade,
                    direction=interaction_direction,
                    reference_price=level_price,
                    or_width_points=float(feature["or_width_points"]),
                    prefix="trade_through_anchor",
                )
            )
            row.update(
                _anchor_outcomes(
                    session_bars,
                    anchor_timestamp=or_close_timestamp,
                    direction=interaction_direction,
                    reference_price=or_close_price,
                    or_width_points=float(feature["or_width_points"]),
                    prefix="or_close_anchor",
                )
            )
            row.update(_copy_frozen_orb_outcomes(first_orb))
            rows.append(row)

    if primitive_mismatches:
        raise AssertionError(
            f"Frozen London primitive reconciliation failures: {primitive_mismatches}"
        )
    if timestamp_mismatches:
        raise AssertionError(
            f"Interaction timestamp/primitive reconciliation failures: {timestamp_mismatches}"
        )
    events = pd.DataFrame(rows).sort_values(
        ["session_date", "london_level_type"], kind="mergesort"
    ).reset_index(drop=True)
    if events["event_id"].duplicated().any():
        raise AssertionError("Duplicate Stage-3B London event IDs")
    audit = _event_audit(
        events,
        feature_source,
        outcome_source,
        input_feature_sessions=input_feature_sessions,
        unavailable_or_sessions=unavailable_or_sessions,
    )
    return events, audit


def build_timestamp_audit(events: pd.DataFrame) -> pd.DataFrame:
    """Return one chronology audit row per interaction event."""

    audit = events[
        [
            "event_id",
            "session_date",
            "contract",
            "london_level_type",
            "interaction_state",
            "frozen_start_side",
            "hypothesis_directional_context",
            "first_touch_timestamp",
            "first_trade_through_timestamp",
            "30m_or_close_timestamp",
            "acceptance_confirmation_timestamp",
            "orb_signal_timestamp",
        ]
    ].copy()
    audit["touch_not_after_or_close"] = (
        audit["first_touch_timestamp"].notna()
        & audit["first_touch_timestamp"].le(audit["30m_or_close_timestamp"])
    )
    audit["trade_through_not_after_or_close"] = (
        audit["first_trade_through_timestamp"].isna()
        | audit["first_trade_through_timestamp"].le(
            audit["30m_or_close_timestamp"]
        )
    )
    audit["touch_not_after_trade_through"] = (
        audit["first_trade_through_timestamp"].isna()
        | audit["first_touch_timestamp"].le(
            audit["first_trade_through_timestamp"]
        )
    )
    close_mask = audit["interaction_state"].eq("CLOSE_THROUGH")
    audit["acceptance_confirmed_only_at_or_close"] = (
        (~close_mask & audit["acceptance_confirmation_timestamp"].isna())
        | (
            close_mask
            & audit["acceptance_confirmation_timestamp"].eq(
                audit["30m_or_close_timestamp"]
            )
        )
    )
    audit["orb_signal_after_or_close"] = (
        audit["orb_signal_timestamp"].isna()
        | audit["orb_signal_timestamp"].gt(audit["30m_or_close_timestamp"])
    )
    audit["eventual_state_known_at_first_trade_through"] = False
    checks = [
        "touch_not_after_or_close",
        "trade_through_not_after_or_close",
        "touch_not_after_trade_through",
        "acceptance_confirmed_only_at_or_close",
        "orb_signal_after_or_close",
    ]
    audit["chronology_valid"] = audit[checks].all(axis=1)
    audit["human_review_status"] = "NOT_REVIEWED"
    return audit


def characterize_anchor_outcomes(
    events: pd.DataFrame, *, anchor_prefix: str
) -> pd.DataFrame:
    """Summarize CLOSE_THROUGH/SWEEP excursions from one event anchor."""

    rows: list[dict[str, Any]] = []
    populations = (
        ("HYPOTHESIS_DIRECTIONAL_CONTEXT", events["hypothesis_directional_context"]),
        ("ALL_FROZEN_INTERACTIONS", pd.Series(True, index=events.index)),
    )
    for population, population_mask in populations:
        for segment in DEV_SEGMENTS:
            segment_mask = (
                pd.Series(True, index=events.index)
                if segment == "FULL_DEVELOPMENT"
                else events["dev_segment"].eq(segment)
            )
            for level_scope in ("ALL", *LEVEL_TYPES):
                level_mask = (
                    pd.Series(True, index=events.index)
                    if level_scope == "ALL"
                    else events["london_level_type"].eq(level_scope)
                )
                base = events.loc[
                    population_mask
                    & segment_mask
                    & level_mask
                    & events["interaction_state"].isin(PRIMARY_STATES)
                ]
                for state in PRIMARY_STATES:
                    group = base.loc[base["interaction_state"].eq(state)]
                    for horizon in HORIZONS:
                        rows.append(
                            _summary_row(
                                group,
                                population=population,
                                segment=segment,
                                level_scope=level_scope,
                                state=state,
                                horizon=horizon,
                                anchor_prefix=anchor_prefix,
                            )
                        )
    return pd.DataFrame(rows)


def build_orb_confirmation_comparison(events: pd.DataFrame) -> pd.DataFrame:
    """Summarize ORB/no-ORB groups without simulating a new entry."""

    rows: list[dict[str, Any]] = []
    eligible = events.loc[
        events["hypothesis_directional_context"]
        & events["interaction_state"].isin(PRIMARY_STATES)
    ]
    for level_scope in ("ALL", *LEVEL_TYPES):
        level_frame = (
            eligible
            if level_scope == "ALL"
            else eligible.loc[eligible["london_level_type"].eq(level_scope)]
        )
        for state in PRIMARY_STATES:
            state_frame = level_frame.loc[
                level_frame["interaction_state"].eq(state)
            ]
            for orb_group in (
                "SAME_DIRECTION_ORB",
                "OPPOSITE_DIRECTION_ORB",
                "NO_ORB",
            ):
                group = state_frame.loc[
                    state_frame["orb_confirmation_group"].eq(orb_group)
                ]
                for horizon in HORIZONS:
                    or_close_mfe = group[f"or_close_anchor_{horizon}_mfe_pct"]
                    or_close_mae = group[f"or_close_anchor_{horizon}_mae_pct"]
                    orb_mfe = group[f"existing_orb_post_signal_bar_{horizon}_mfe_pct"]
                    orb_mae = group[f"existing_orb_post_signal_bar_{horizon}_mae_pct"]
                    rows.append(
                        {
                            "research_scope": "DEVELOPMENT_ONLY",
                            "analysis_population": "HYPOTHESIS_DIRECTIONAL_CONTEXT",
                            "level_scope": level_scope,
                            "interaction_state": state,
                            "orb_confirmation_group": orb_group,
                            "outcome_horizon": horizon,
                            "event_n": int(len(group)),
                            "sample_status": _sample_status(len(group)),
                            "median_minutes_trade_through_to_or_close": _median(
                                group["minutes_from_trade_through_to_or_close"]
                            ),
                            "median_minutes_or_close_to_orb": _median(
                                group["minutes_from_or_close_to_orb_signal"]
                            ),
                            "median_level_to_or_close_directional_points": _median(
                                group[
                                    "level_to_or_close_directional_displacement_points"
                                ]
                            ),
                            "median_or_close_to_orb_directional_points": _median(
                                group[
                                    "or_close_to_orb_directional_displacement_points"
                                ]
                            ),
                            "median_level_to_orb_directional_points": _median(
                                group["level_to_orb_directional_displacement_points"]
                            ),
                            "median_or_close_anchor_mfe_pct": _median(or_close_mfe),
                            "median_or_close_anchor_mae_pct": _median(or_close_mae),
                            "median_existing_orb_mfe_pct": _median(orb_mfe),
                            "median_existing_orb_mae_pct": _median(orb_mae),
                            "orb_outcome_direction_matches_interaction": (
                                orb_group == "SAME_DIRECTION_ORB"
                            ),
                            "new_strategy_simulated": False,
                        }
                    )
    return pd.DataFrame(rows)


def build_stability_table(or_close_summary: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compare CLOSE_THROUGH with SWEEP in full and half DEVELOPMENT samples."""

    source = or_close_summary.loc[
        or_close_summary["analysis_population"].eq(
            "HYPOTHESIS_DIRECTIONAL_CONTEXT"
        )
    ]
    rows: list[dict[str, Any]] = []
    for segment in DEV_SEGMENTS:
        for level_scope in ("ALL", *LEVEL_TYPES):
            for horizon in HORIZONS:
                frame = source.loc[
                    source["dev_segment"].eq(segment)
                    & source["level_scope"].eq(level_scope)
                    & source["outcome_horizon"].eq(horizon)
                ].set_index("interaction_state")
                close = frame.loc["CLOSE_THROUGH"]
                sweep = frame.loc["SWEEP"]
                rows.append(
                    {
                        "research_scope": "DEVELOPMENT_ONLY",
                        "analysis_population": "HYPOTHESIS_DIRECTIONAL_CONTEXT",
                        "dev_segment": segment,
                        "level_scope": level_scope,
                        "outcome_horizon": horizon,
                        "close_through_n": int(close["event_n"]),
                        "sweep_n": int(sweep["event_n"]),
                        "sample_status": (
                            "SUFFICIENT"
                            if min(close["event_n"], sweep["event_n"])
                            >= MIN_INFERENCE_N
                            else "INSUFFICIENT_SAMPLE"
                        ),
                        "close_through_median_mfe_pct": close["median_mfe_pct"],
                        "sweep_median_mfe_pct": sweep["median_mfe_pct"],
                        "close_minus_sweep_median_mfe_pct": _difference(
                            close["median_mfe_pct"], sweep["median_mfe_pct"]
                        ),
                        "close_through_median_mae_pct": close["median_mae_pct"],
                        "sweep_median_mae_pct": sweep["median_mae_pct"],
                        "close_minus_sweep_median_mae_pct": _difference(
                            close["median_mae_pct"], sweep["median_mae_pct"]
                        ),
                        "favorable_advantage_exceeds_adverse_increase": _advantage_exceeds_tradeoff(
                            close["median_mfe_pct"],
                            sweep["median_mfe_pct"],
                            close["median_mae_pct"],
                            sweep["median_mae_pct"],
                        ),
                    }
                )
    stability = pd.DataFrame(rows)
    classification = classify_hypothesis(stability)
    stability["hypothesis_classification"] = classification["classification"]
    return stability, classification


def classify_hypothesis(stability: pd.DataFrame) -> dict[str, Any]:
    """Apply fixed descriptive consistency and sample-size guardrails."""

    all_levels = stability.loc[stability["level_scope"].eq("ALL")]
    support: dict[str, int] = {}
    sufficient_horizons: dict[str, int] = {}
    for segment in DEV_SEGMENTS:
        frame = all_levels.loc[all_levels["dev_segment"].eq(segment)]
        sufficient = frame["sample_status"].eq("SUFFICIENT")
        sufficient_horizons[segment] = int(sufficient.sum())
        support[segment] = int(
            (
                sufficient
                & frame["close_minus_sweep_median_mfe_pct"].gt(0)
            ).sum()
        )
    full_30m = all_levels.loc[
        all_levels["dev_segment"].eq("FULL_DEVELOPMENT")
        & all_levels["outcome_horizon"].eq("30m")
    ].iloc[0]
    tradeoff_pass = bool(full_30m["favorable_advantage_exceeds_adverse_increase"])
    directional_30m = stability.loc[
        stability["dev_segment"].eq("FULL_DEVELOPMENT")
        & stability["level_scope"].isin(LEVEL_TYPES)
        & stability["outcome_horizon"].eq("30m")
    ]
    direction_consistency = bool(
        len(directional_30m) == len(LEVEL_TYPES)
        and directional_30m["sample_status"].eq("SUFFICIENT").all()
        and directional_30m["close_minus_sweep_median_mfe_pct"].gt(0).all()
    )
    minimum_support = min(support.values())
    if sufficient_horizons["FULL_DEVELOPMENT"] == 0:
        classification = "NO_CLEAR_RELATIONSHIP"
    elif minimum_support >= 3 and tradeoff_pass and direction_consistency:
        classification = "CONSISTENT_HYPOTHESIS_CANDIDATE"
    elif support["FULL_DEVELOPMENT"] >= 3 and (
        support["DEV_FIRST_HALF"] >= 3
        or support["DEV_SECOND_HALF"] >= 3
    ) and tradeoff_pass and direction_consistency:
        classification = "POTENTIALLY_INFORMATIVE"
    elif support["FULL_DEVELOPMENT"] > 0:
        classification = "WEAK_OR_UNSTABLE"
    else:
        classification = "NO_CLEAR_RELATIONSHIP"
    return {
        "classification": classification,
        "positive_mfe_horizons_by_segment": support,
        "sufficient_horizons_by_segment": sufficient_horizons,
        "full_30m_favorable_advantage_exceeds_adverse_increase": tradeoff_pass,
        "full_30m_london_high_low_direction_consistency": direction_consistency,
        "hypothesis_validated": False,
    }


def build_review_queue(events: pd.DataFrame, *, limit: int = 12) -> pd.DataFrame:
    """Create a deterministic representative-session queue for human review."""

    eligible = events.loc[
        events["hypothesis_directional_context"]
        & events["interaction_state"].isin(PRIMARY_STATES)
    ].sort_values(["session_date", "london_level_type"])
    selections: list[pd.Series] = []
    seen: set[str] = set()
    for state in PRIMARY_STATES:
        for level_type in LEVEL_TYPES:
            for group_name in (
                "SAME_DIRECTION_ORB",
                "OPPOSITE_DIRECTION_ORB",
                "NO_ORB",
            ):
                candidates = eligible.loc[
                    eligible["interaction_state"].eq(state)
                    & eligible["london_level_type"].eq(level_type)
                    & eligible["orb_confirmation_group"].eq(group_name)
                ]
                if candidates.empty:
                    continue
                chosen = candidates.iloc[0]
                if chosen["event_id"] not in seen:
                    selections.append(chosen)
                    seen.add(str(chosen["event_id"]))
    if len(selections) < limit:
        for _, candidate in eligible.iterrows():
            if candidate["event_id"] in seen:
                continue
            selections.append(candidate)
            seen.add(str(candidate["event_id"]))
            if len(selections) >= limit:
                break
    selected = pd.DataFrame(selections[:limit])
    columns = [
        "event_id",
        "session_date",
        "contract",
        "dev_segment",
        "london_level_type",
        "london_level_price",
        "interaction_state",
        "frozen_start_side",
        "first_touch_timestamp",
        "first_trade_through_timestamp",
        "30m_or_close_timestamp",
        "acceptance_confirmation_timestamp",
        "interaction_direction",
        "orb_confirmation_group",
        "orb_direction",
        "orb_signal_timestamp",
        "or_high",
        "or_low",
        "or_close",
    ]
    queue = selected[columns].copy()
    queue.insert(0, "review_case", [f"LONDON_EVENT_{index:02d}" for index in range(1, len(queue) + 1)])
    queue["selection_basis"] = (
        queue["interaction_state"].astype(str)
        + " / "
        + queue["london_level_type"].astype(str)
        + " / "
        + queue["orb_confirmation_group"].astype(str)
    )
    queue["human_review_status"] = "PENDING_HUMAN_REVIEW"
    queue["human_notes"] = ""
    return queue


def render_report(
    events: pd.DataFrame,
    stability: pd.DataFrame,
    confirmation: pd.DataFrame,
    classification: Mapping[str, Any],
    audit: Mapping[str, Any],
    review_queue: pd.DataFrame,
) -> str:
    """Render the concise Stage-3B research report."""

    primary = events.loc[events["hypothesis_directional_context"]]
    timing = primary["first_trade_through_minutes_after_0930"].describe(
        percentiles=[0.25, 0.5, 0.75]
    )
    core = stability.loc[
        stability["dev_segment"].eq("FULL_DEVELOPMENT")
        & stability["level_scope"].eq("ALL")
    ][
        [
            "outcome_horizon",
            "close_through_n",
            "sweep_n",
            "close_through_median_mfe_pct",
            "sweep_median_mfe_pct",
            "close_minus_sweep_median_mfe_pct",
            "close_through_median_mae_pct",
            "sweep_median_mae_pct",
            "close_minus_sweep_median_mae_pct",
        ]
    ].copy()
    for column in [column for column in core if column.endswith("_pct")]:
        core[column] = core[column].map(_fmt_pct)
    core = core.rename(
        columns={
            "outcome_horizon": "Horizon",
            "close_through_n": "Close N",
            "sweep_n": "Sweep N",
            "close_through_median_mfe_pct": "Close median MFE",
            "sweep_median_mfe_pct": "Sweep median MFE",
            "close_minus_sweep_median_mfe_pct": "Close−sweep MFE",
            "close_through_median_mae_pct": "Close median MAE",
            "sweep_median_mae_pct": "Sweep median MAE",
            "close_minus_sweep_median_mae_pct": "Close−sweep MAE",
        }
    )
    stability_30 = stability.loc[
        stability["level_scope"].eq("ALL")
        & stability["outcome_horizon"].eq("30m")
    ][
        [
            "dev_segment",
            "close_through_n",
            "sweep_n",
            "close_minus_sweep_median_mfe_pct",
            "close_minus_sweep_median_mae_pct",
            "sample_status",
        ]
    ].copy()
    stability_30["close_minus_sweep_median_mfe_pct"] = stability_30[
        "close_minus_sweep_median_mfe_pct"
    ].map(_fmt_pct)
    stability_30["close_minus_sweep_median_mae_pct"] = stability_30[
        "close_minus_sweep_median_mae_pct"
    ].map(_fmt_pct)
    stability_30 = stability_30.rename(
        columns={
            "dev_segment": "DEV segment",
            "close_through_n": "Close N",
            "sweep_n": "Sweep N",
            "close_minus_sweep_median_mfe_pct": "Close−sweep MFE",
            "close_minus_sweep_median_mae_pct": "Close−sweep MAE",
            "sample_status": "Sample status",
        }
    )
    group_counts = (
        primary.groupby(["interaction_state", "orb_confirmation_group"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=PRIMARY_STATES, fill_value=0)
        .reset_index()
    )
    group_counts = group_counts.rename(columns={"interaction_state": "State"})

    close_same = primary.loc[
        primary["interaction_state"].eq("CLOSE_THROUGH")
        & primary["orb_confirmation_group"].eq("SAME_DIRECTION_ORB")
    ]
    close_no_orb = primary.loc[
        primary["interaction_state"].eq("CLOSE_THROUGH")
        & primary["orb_confirmation_group"].eq("NO_ORB")
    ]
    sweep_no_orb = primary.loc[
        primary["interaction_state"].eq("SWEEP")
        & primary["orb_confirmation_group"].eq("NO_ORB")
    ]
    orb_delay = _median(close_same["minutes_from_or_close_to_orb_signal"])
    consumed_to_close = _median(
        close_same["level_to_or_close_directional_displacement_points"]
    )
    consumed_after_close = _median(
        close_same["or_close_to_orb_directional_displacement_points"]
    )
    consumed_total = _median(
        close_same["level_to_orb_directional_displacement_points"]
    )
    or_close_remaining = _median(close_same["or_close_anchor_30m_mfe_pct"])
    orb_remaining = _median(
        close_same["existing_orb_post_signal_bar_30m_mfe_pct"]
    )
    no_orb_rows = pd.DataFrame(
        [
            {
                "State": "CLOSE_THROUGH",
                "N": len(close_no_orb),
                "Median 30m MFE": _fmt_pct(
                    _median(close_no_orb["or_close_anchor_30m_mfe_pct"])
                ),
                "Median 30m MAE": _fmt_pct(
                    _median(close_no_orb["or_close_anchor_30m_mae_pct"])
                ),
            },
            {
                "State": "SWEEP",
                "N": len(sweep_no_orb),
                "Median 30m MFE": _fmt_pct(
                    _median(sweep_no_orb["or_close_anchor_30m_mfe_pct"])
                ),
                "Median 30m MAE": _fmt_pct(
                    _median(sweep_no_orb["or_close_anchor_30m_mae_pct"])
                ),
            },
        ]
    )
    conclusion = _classification_text(str(classification["classification"]))
    return f"""# MNQ ORB V0.2 Stage 3B London interaction event characterization

## Scope and chronology

This DEVELOPMENT-only event study contains {len(events)} frozen London High/Low
30-minute OR interaction events: {audit['state_counts'].get('CLOSE_THROUGH', 0)}
`CLOSE_THROUGH` and {audit['state_counts'].get('SWEEP', 0)} `SWEEP`. The primary
directional hypothesis population contains {len(primary)} events whose frozen OR
start side matches the declared London High UP / London Low DOWN acceptance
direction. Reverse-start events remain in the event and audit files but do not
enter the primary hypothesis classification.

Timestamps are one-minute bar-end labels. `first_trade_through_timestamp` is the
first strict crossing relative to the frozen OR start side. Eventual
`CLOSE_THROUGH`/`SWEEP` status is retrospective at that timestamp. The state is
causally known only at the 10:00 ET 30m OR close. Excursion windows begin with
the first complete bar after each anchor.

## First trade-through timing

- N: {int(timing['count'])}
- Minimum: {timing['min']:.0f} minute(s) after 09:30
- 25th percentile: {timing['25%']:.0f} minutes
- Median: {timing['50%']:.0f} minutes
- 75th percentile: {timing['75%']:.0f} minutes
- Maximum: {timing['max']:.0f} minutes

## Primary OR-close comparison

{_markdown_table(core)}

## ORB confirmation groups

The group uses the first later validated 30m PRINT by timestamp. Presence fields
in the event dataset also expose whether either direction occurs later that day.

{_markdown_table(group_counts)}

For CLOSE_THROUGH plus same-direction ORB events (N={len(close_same)}), the median
OR-close-to-ORB delay is {_fmt_number(orb_delay)} minutes. Median directional
displacement is {_fmt_number(consumed_to_close)} points from the London level to
OR close, {_fmt_number(consumed_after_close)} additional points from OR close to
the ORB reference, and {_fmt_number(consumed_total)} points in total. Median 30m
MFE is {_fmt_pct(or_close_remaining)} from the causal OR-close anchor versus
{_fmt_pct(orb_remaining)} in the unchanged post-ORB outcome. These windows have
different start times and are descriptive; no P&L or hypothetical fill is used.

## Interaction without a later ORB

{_markdown_table(no_orb_rows)}

These rows test whether interaction-state continuation exists without a later
qualifying PRINT. Sparse groups remain `INSUFFICIENT_SAMPLE` in the CSV outputs.

## DEVELOPMENT-half stability

{_markdown_table(stability_30)}

Positive MFE differences favor acceptance; positive MAE differences mean
acceptance also experienced more adverse excursion. The fixed classification is
`{classification['classification']}`. {conclusion}

## Human review and guardrails

{len(review_queue)} representative sessions are queued with status
`PENDING_HUMAN_REVIEW`. Human review is not marked complete. The analysis did not
access Validation/OOS_BURNED, redefine features or PRINT signals, simulate a new
entry, calculate P&L, optimize a threshold, or create a strategy rule.
"""


def development_segment(value: date) -> str:
    if value <= STAGE3A_FIRST_HALF_END:
        return "DEV_FIRST_HALF"
    if value >= STAGE3A_SECOND_HALF_START:
        return "DEV_SECOND_HALF"
    raise ValueError(f"Session date falls outside the Stage-3A split: {value}")


def _prepare_features(features: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(required_feature_columns()) - set(features.columns))
    if missing:
        raise ValueError("Feature input missing required columns: " + ", ".join(missing))
    source = features[required_feature_columns()].copy()
    source["session_date"] = pd.to_datetime(source["session_date"], errors="raise").dt.date
    _assert_development_dates(source["session_date"])
    source = source.loc[source["or_minutes"].eq(OR_MINUTES)].copy()
    if source["session_date"].duplicated().any():
        raise ValueError("Duplicate frozen 30m feature session")
    source = source.loc[source["or_feature_available"].map(_as_bool)].copy()
    return source.sort_values("session_date").reset_index(drop=True)


def _prepare_prices(prices: pd.DataFrame) -> pd.DataFrame:
    source = prices.copy()
    if "timestamp_et" in source.columns:
        source["timestamp_et"] = pd.to_datetime(
            source["timestamp_et"], utc=True, errors="raise"
        ).dt.tz_convert(ET_TIMEZONE)
        source = source.set_index("timestamp_et")
    if not isinstance(source.index, pd.DatetimeIndex):
        raise TypeError("DEVELOPMENT prices require a DatetimeIndex")
    if source.index.tz is None:
        raise ValueError("DEVELOPMENT price timestamps must be timezone-aware")
    source.index = source.index.tz_convert(ET_TIMEZONE)
    source["session_date"] = pd.to_datetime(
        source["session_date"], errors="raise"
    ).dt.date
    _assert_development_dates(source["session_date"])
    if source.index.duplicated().any():
        raise ValueError("Duplicate DEVELOPMENT price timestamp")
    return source.sort_index()


def _prepare_outcomes(outcomes: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(required_outcome_columns()) - set(outcomes.columns))
    if missing:
        raise ValueError("ORB outcome input missing required columns: " + ", ".join(missing))
    source = outcomes[required_outcome_columns()].copy()
    source["session_date"] = pd.to_datetime(source["session_date"], errors="raise").dt.date
    _assert_development_dates(source["session_date"])
    source = source.loc[
        source["or_minutes"].eq(OR_MINUTES)
        & source["breakout_type"].eq("PRINT")
    ].copy()
    source["breakout_timestamp"] = pd.to_datetime(
        source["breakout_timestamp"], utc=True, errors="raise"
    ).dt.tz_convert(ET_TIMEZONE)
    if source.duplicated(["session_date", "breakout_direction"]).any():
        raise ValueError("Frozen 30m PRINT outcomes must be first-per-direction")
    return source.sort_values(["breakout_timestamp", "breakout_direction"]).reset_index(drop=True)


def _anchor_outcomes(
    session_bars: pd.DataFrame,
    *,
    anchor_timestamp: pd.Timestamp | pd.NaT,
    direction: str | None,
    reference_price: float,
    or_width_points: float,
    prefix: str,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if pd.isna(anchor_timestamp) or direction not in {"UP", "DOWN"}:
        for horizon in HORIZONS:
            output.update(_empty_anchor_fields(prefix, horizon))
        return output
    orb_direction = "LONG" if direction == "UP" else "SHORT"
    for horizon in HORIZONS:
        if horizon == "session_end":
            end = pd.Timestamp.combine(
                anchor_timestamp.date(), time(16, 0)
            ).tz_localize(ET_TIMEZONE)
            expected = pd.date_range(
                anchor_timestamp + pd.Timedelta(minutes=1), end, freq="min"
            )
        else:
            minutes = int(horizon.removesuffix("m"))
            expected = pd.date_range(
                anchor_timestamp + pd.Timedelta(minutes=1),
                periods=minutes,
                freq="min",
            )
        selected = session_bars.loc[session_bars.index.intersection(expected)]
        complete = bool(
            len(expected) > 0
            and len(selected) == len(expected)
            and selected.index.equals(expected)
        )
        fields = _excursion_fields(
            selected, orb_direction, reference_price, horizon, complete
        )
        source_prefix = f"post_signal_bar_{horizon}"
        for suffix in (
            "complete",
            "bars",
            "end_timestamp",
            "mfe_points",
            "mae_points",
            "mfe_pct",
            "mae_pct",
        ):
            output[f"{prefix}_{horizon}_{suffix}"] = fields[
                f"{source_prefix}_{suffix}"
            ]
        output[f"{prefix}_{horizon}_mfe_or_widths"] = _safe_divide(
            output[f"{prefix}_{horizon}_mfe_points"], or_width_points
        )
        output[f"{prefix}_{horizon}_mae_or_widths"] = _safe_divide(
            output[f"{prefix}_{horizon}_mae_points"], or_width_points
        )
    return output


def _empty_anchor_fields(prefix: str, horizon: str) -> dict[str, Any]:
    return {
        f"{prefix}_{horizon}_complete": False,
        f"{prefix}_{horizon}_bars": 0,
        f"{prefix}_{horizon}_end_timestamp": pd.NaT,
        f"{prefix}_{horizon}_mfe_points": np.nan,
        f"{prefix}_{horizon}_mae_points": np.nan,
        f"{prefix}_{horizon}_mfe_pct": np.nan,
        f"{prefix}_{horizon}_mae_pct": np.nan,
        f"{prefix}_{horizon}_mfe_or_widths": np.nan,
        f"{prefix}_{horizon}_mae_or_widths": np.nan,
    }


def _copy_frozen_orb_outcomes(first_orb: pd.Series | None) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for horizon in HORIZONS:
        for suffix in (
            "complete",
            "bars",
            "end_timestamp",
            "mfe_points",
            "mae_points",
            "mfe_pct",
            "mae_pct",
        ):
            key = f"post_signal_bar_{horizon}_{suffix}"
            output[f"existing_orb_{key}"] = (
                first_orb[key] if first_orb is not None else pd.NA
            )
    return output


def _summary_row(
    group: pd.DataFrame,
    *,
    population: str,
    segment: str,
    level_scope: str,
    state: str,
    horizon: str,
    anchor_prefix: str,
) -> dict[str, Any]:
    mfe = pd.to_numeric(
        group[f"{anchor_prefix}_{horizon}_mfe_pct"], errors="coerce"
    )
    mae = pd.to_numeric(
        group[f"{anchor_prefix}_{horizon}_mae_pct"], errors="coerce"
    )
    complete = group[f"{anchor_prefix}_{horizon}_complete"].map(_as_bool)
    valid = complete & mfe.notna() & mae.notna()
    mfe = mfe.loc[valid]
    mae = mae.loc[valid]
    return {
        "research_scope": "DEVELOPMENT_ONLY",
        "analysis_population": population,
        "anchor": anchor_prefix,
        "anchor_information_status": (
            "RETROSPECTIVE_DESCRIPTIVE"
            if anchor_prefix == "trade_through_anchor"
            else "CAUSAL_STATE_KNOWN"
        ),
        "first_included_bar": "anchor timestamp + 1 minute",
        "dev_segment": segment,
        "level_scope": level_scope,
        "interaction_state": state,
        "interaction_direction_rule": "CLOSE=through direction; SWEEP=rejection direction",
        "outcome_horizon": horizon,
        "event_n": int(len(group)),
        "london_high_n": int(group["london_level_type"].eq("LONDON_HIGH").sum()),
        "london_low_n": int(group["london_level_type"].eq("LONDON_LOW").sum()),
        "same_direction_orb_n": int(
            group["orb_confirmation_group"].eq("SAME_DIRECTION_ORB").sum()
        ),
        "opposite_direction_orb_n": int(
            group["orb_confirmation_group"].eq("OPPOSITE_DIRECTION_ORB").sum()
        ),
        "no_orb_n": int(group["orb_confirmation_group"].eq("NO_ORB").sum()),
        "complete_outcome_n": int(valid.sum()),
        "sample_status": _sample_status(len(group)),
        "mean_mfe_pct": _mean(mfe),
        "median_mfe_pct": _median(mfe),
        "mfe_p25_pct": _quantile(mfe, 0.25),
        "mfe_p75_pct": _quantile(mfe, 0.75),
        "mean_mae_pct": _mean(mae),
        "median_mae_pct": _median(mae),
        "mae_p25_pct": _quantile(mae, 0.25),
        "mae_p75_pct": _quantile(mae, 0.75),
    }


def _event_audit(
    events: pd.DataFrame,
    features: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    input_feature_sessions: int,
    unavailable_or_sessions: int,
) -> dict[str, Any]:
    primary = events.loc[events["hypothesis_directional_context"]]
    return {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis_id": HYPOTHESIS_ID,
        "partition": "DEVELOPMENT",
        "feature_sessions_30m_input": input_feature_sessions,
        "feature_sessions_30m_eligible": int(len(features)),
        "feature_sessions_30m_unavailable": unavailable_or_sessions,
        "frozen_print_outcomes_30m": int(len(outcomes)),
        "total_london_interaction_events": int(len(events)),
        "state_counts": {
            str(key): int(value)
            for key, value in events["interaction_state"].value_counts().items()
        },
        "hypothesis_directional_events": int(len(primary)),
        "hypothesis_state_counts": {
            str(key): int(value)
            for key, value in primary["interaction_state"].value_counts().items()
        },
        "orb_group_counts_by_state": {
            str(state): {
                str(key): int(value)
                for key, value in group["orb_confirmation_group"].value_counts().items()
            }
            for state, group in primary.groupby("interaction_state")
        },
        "development_split": {
            "first_half_end": STAGE3A_FIRST_HALF_END.isoformat(),
            "second_half_start": STAGE3A_SECOND_HALF_START.isoformat(),
            "method": "same fixed date boundary as Stage 3A",
        },
        "primitive_reconciliation_failures": 0,
        "timestamp_reconciliation_failures": 0,
        "validation_or_oos_accessed": False,
        "new_strategy_simulated": False,
    }


def _assert_development_dates(values: pd.Series) -> None:
    if values.isna().any():
        raise ValueError("Missing session_date")
    dates = pd.to_datetime(values, errors="raise")
    if dates.min() < DEVELOPMENT_START or dates.max() > DEVELOPMENT_END:
        raise ValueError("Non-DEVELOPMENT session entered Stage 3B")


def _as_et_timestamp(value: Any) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    return pd.to_datetime(value, utc=True, errors="raise").tz_convert(ET_TIMEZONE)


def _as_bool(value: Any) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _orb_to_price_direction(value: Any) -> str | None:
    if value == "LONG":
        return "UP"
    if value == "SHORT":
        return "DOWN"
    if value is None or pd.isna(value):
        return None
    raise ValueError(f"Unsupported ORB direction: {value}")


def _opposite_direction(value: str | None) -> str | None:
    if value == "UP":
        return "DOWN"
    if value == "DOWN":
        return "UP"
    return None


def _directional_value(value: float, direction: str | None) -> float:
    if pd.isna(value) or direction not in {"UP", "DOWN"}:
        return np.nan
    return float(value) if direction == "UP" else -float(value)


def _safe_divide(numerator: Any, denominator: Any) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or abs(float(denominator)) < 1e-12:
        return np.nan
    return float(numerator) / float(denominator)


def _minutes_between(start: Any, end: Any) -> float:
    if pd.isna(start) or pd.isna(end):
        return np.nan
    return float((end - start).total_seconds() / 60.0)


def _minutes_after_open(session_date: date, timestamp: Any) -> float:
    if pd.isna(timestamp):
        return np.nan
    market_open = pd.Timestamp.combine(session_date, time(9, 30)).tz_localize(
        ET_TIMEZONE
    )
    return _minutes_between(market_open, timestamp)


def _sample_status(n: int) -> str:
    return "SUFFICIENT" if int(n) >= MIN_INFERENCE_N else "INSUFFICIENT_SAMPLE"


def _mean(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return float(values.mean()) if not values.empty else np.nan


def _median(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return float(values.median()) if not values.empty else np.nan


def _quantile(values: pd.Series, value: float) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return float(values.quantile(value)) if not values.empty else np.nan


def _difference(left: Any, right: Any) -> float:
    if pd.isna(left) or pd.isna(right):
        return np.nan
    return float(left) - float(right)


def _advantage_exceeds_tradeoff(
    close_mfe: Any, sweep_mfe: Any, close_mae: Any, sweep_mae: Any
) -> bool:
    values = (close_mfe, sweep_mfe, close_mae, sweep_mae)
    if any(pd.isna(value) for value in values):
        return False
    mfe_advantage = float(close_mfe) - float(sweep_mfe)
    mae_increase = max(0.0, float(close_mae) - float(sweep_mae))
    return bool(mfe_advantage > 0 and mfe_advantage > mae_increase)


def _fmt_pct(value: Any) -> str:
    if pd.isna(value):
        return "n.a."
    return f"{float(value) * 100:.3f}%"


def _fmt_number(value: Any) -> str:
    if pd.isna(value):
        return "n.a."
    return f"{float(value):.2f}"


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No rows."
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _classification_text(classification: str) -> str:
    if classification == "CONSISTENT_HYPOTHESIS_CANDIDATE":
        return (
            "HYP-LONDON-ACCEPTANCE-01 remains a viable DEVELOPMENT-only hypothesis "
            "candidate. It is not validated and is not a strategy rule."
        )
    if classification == "POTENTIALLY_INFORMATIVE":
        return (
            "The hypothesis remains potentially informative but does not meet the "
            "full cross-half consistency guardrail."
        )
    if classification == "WEAK_OR_UNSTABLE":
        return (
            "The hypothesis remains registered as a DEVELOPMENT-only research candidate, "
            "but its event-anchored evidence is weak or unstable and does not satisfy the "
            "candidate-promotion guardrail."
        )
    return "The event-anchored study does not show a clear relationship."
