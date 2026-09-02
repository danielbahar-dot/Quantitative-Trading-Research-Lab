"""MNQ ORB V0.2 Stage 2 causal feature construction and characterization.

This module does not calculate strategy profitability or define V0.2 trading
rules.  It reads only the predeclared DEVELOPMENT partition, builds causal
features, and keeps explicitly future-looking breakout outcomes in a separate
table whose columns are prefixed ``outcome_``.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any, Iterable, Mapping
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from src.features.market_context import (
    ET_TIMEZONE,
    HISTORICAL_LOOKBACKS,
    OR_DURATIONS,
    WindowDefinition,
    add_causal_width_history,
    calculate_or_context,
    gap_context,
    interaction_state,
    level_interaction,
    load_context_windows,
    ny_open_gap_context,
    expected_bar_end_index,
    summarize_window,
)
from src.visualization.research_viewer import find_orb_signals


DEVELOPMENT_START = date(2024, 6, 21)
DEVELOPMENT_END = date(2025, 6, 30)
OUTCOME_HORIZONS = (5, 15, 30, 60)
WINDOW_PREFIXES = {
    "asia_kill_zone": "asia",
    "london_kill_zone": "london",
    "ny_premarket": "ny_premarket",
    "overnight": "overnight",
    "overnight_context_2000_0900": "overnight_context_2000_0900",
}
KEY_LEVEL_IDS = (
    "previous_day_high",
    "previous_day_low",
    "previous_day_close",
    "previous_rth_high",
    "previous_rth_low",
    "previous_rth_close",
    "overnight_high",
    "overnight_low",
    "asia_high",
    "asia_low",
    "london_high",
    "london_low",
    "ny_premarket_high",
    "ny_premarket_low",
    "globex_reopen",
    "globex_reopen_prior_1700_close",
    "ny_open_prior_1614_close",
    "ny_open_reference",
)
CHARACTERIZATION_FEATURES = (
    "or_width_pct",
    "or_width_hist_5_percentile",
    "or_width_hist_10_percentile",
    "or_width_hist_15_percentile",
    "or_width_hist_20_percentile",
    "asia_range_pct",
    "london_range_pct",
    "ny_premarket_range_pct",
    "overnight_range_pct",
    "overnight_context_2000_0900_range_pct",
    "globex_reopen_gap_pct",
    "ny_open_gap_pct",
    "or_to_asia_range_ratio",
    "or_to_london_range_ratio",
    "or_to_ny_premarket_range_ratio",
    "or_to_overnight_context_2000_0900_range_ratio",
)


def load_development_prices(path: str | Path) -> pd.DataFrame:
    """Load and hard-bound the qualified DEVELOPMENT partition only."""
    required = {
        "timestamp_et", "session_date", "contract", "open", "high", "low", "close", "volume",
    }
    available = set(pd.read_csv(path, nrows=0).columns)
    missing = required - available
    if missing:
        raise ValueError(f"DEVELOPMENT data missing columns: {sorted(missing)}")
    frame = pd.read_csv(path, usecols=sorted(required))
    frame["timestamp_et"] = pd.to_datetime(frame["timestamp_et"], utc=True).dt.tz_convert(ET_TIMEZONE)
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.date
    if frame["session_date"].min() < DEVELOPMENT_START or frame["session_date"].max() > DEVELOPMENT_END:
        raise AssertionError("Stage 2 input contains a non-DEVELOPMENT session")
    if frame["timestamp_et"].duplicated().any():
        raise AssertionError("DEVELOPMENT timestamps must be unique")
    return frame.set_index("timestamp_et").sort_index()


def build_feature_audit(
    prices: pd.DataFrame,
    window_config: Mapping[str, Any],
    *,
    durations: Iterable[int] = OR_DURATIONS,
    lookbacks: Iterable[int] = HISTORICAL_LOOKBACKS,
) -> pd.DataFrame:
    """Return one causal feature row per DEVELOPMENT session x OR duration."""
    _assert_development(prices)
    windows = load_context_windows(window_config)
    missing_windows = set(WINDOW_PREFIXES) - set(windows)
    if missing_windows:
        raise ValueError(f"Window configuration missing: {sorted(missing_windows)}")
    session_dates = sorted(prices["session_date"].unique())
    sessions = {
        session_date: prices.loc[prices["session_date"].eq(session_date)]
        for session_date in session_dates
    }
    rows: list[dict[str, Any]] = []
    rth_window = WindowDefinition("rth", time(9, 30), time(16, 0))
    trading_day_window = WindowDefinition("trading_day", time(18, 0), time(17, 0), -1)

    for session_offset, session_date in enumerate(session_dates):
        session_rows = sessions[session_date]
        prior_date = session_dates[session_offset - 1] if session_offset else None
        prior_rows = sessions.get(prior_date) if prior_date is not None else None
        base: dict[str, Any] = {
            "session_date": session_date,
            "contract": _session_contract(session_rows),
            "timezone": ET_TIMEZONE,
            "timestamp_semantics": "bar_end_time",
        }
        window_summaries: dict[str, dict[str, Any]] = {}
        for window_id, prefix in WINDOW_PREFIXES.items():
            summary = summarize_window(session_rows, session_date, windows[window_id])
            window_summaries[prefix] = summary
            base.update(_flatten_window(prefix, summary))

        if prior_rows is None:
            previous_day = summarize_window(pd.DataFrame(index=pd.DatetimeIndex([], tz=ET_TIMEZONE)), session_date, trading_day_window)
            previous_day["available_at"] = pd.NaT
            previous_day["missing_reason"] = "NO_PRIOR_SESSION"
            previous_rth = summarize_window(pd.DataFrame(index=pd.DatetimeIndex([], tz=ET_TIMEZONE)), session_date, rth_window)
            previous_rth["available_at"] = pd.NaT
            previous_rth["missing_reason"] = "NO_PRIOR_SESSION"
        else:
            previous_day = summarize_window(prior_rows, prior_date, trading_day_window)
            previous_rth = summarize_window(prior_rows, prior_date, rth_window)
        base.update(_flatten_window("previous_day", previous_day))
        base.update(_flatten_window("previous_rth", previous_rth))
        base.update(gap_context(prior_rows, session_rows, session_date))
        base.update(ny_open_gap_context(prior_rows, session_rows, session_date))
        base.update(_liquidity_path(window_summaries))

        levels = _key_levels(base)
        for duration in durations:
            or_context = calculate_or_context(session_rows, session_date, int(duration))
            row = {**base, **or_context}
            for level_id, level in levels.items():
                row[f"{level_id}_price"] = level
                relation = level_interaction(
                    level=level,
                    or_open=row["or_open"],
                    or_high=row["or_high"],
                    or_low=row["or_low"],
                    or_close=row["or_close"],
                    or_mid=row["or_mid"],
                )
                row.update({f"level_{level_id}_{key}": value for key, value in relation.items()})
            row.update(_expansion_ratios(row))
            row["row_feature_complete"] = bool(
                row["or_feature_available"]
                and row["ny_premarket_feature_available"]
            )
            rows.append(row)

    output = pd.DataFrame(rows)
    output = add_causal_width_history(output, lookbacks=lookbacks)
    if output.duplicated(["session_date", "or_minutes"]).any():
        raise AssertionError("Duplicate session x OR-duration feature records")
    _assert_development(output)
    _validate_feature_math(output)
    return output


def build_breakout_outcomes(
    prices: pd.DataFrame,
    features: pd.DataFrame,
    *,
    durations: Iterable[int] = OR_DURATIONS,
    horizons: Iterable[int] = OUTCOME_HORIZONS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build future-labelled PRINT excursion outcomes without strategy exits."""
    _assert_development(prices)
    levels = features[["session_date", "or_minutes", "or_feature_available", "or_high", "or_low", "or_mid"]].copy()
    levels = levels.rename(columns={"or_feature_available": "valid_or"})
    events: list[dict[str, Any]] = []
    ambiguity_rows: list[pd.DataFrame] = []
    for duration in durations:
        signals, ambiguous = find_orb_signals(
            prices,
            levels,
            start_date=DEVELOPMENT_START,
            end_date=DEVELOPMENT_END,
            or_minutes=int(duration),
            breakout_type="PRINT",
        )
        if not ambiguous.empty:
            ambiguity_rows.append(ambiguous.assign(or_minutes=int(duration)))
        for signal in signals.itertuples(index=False):
            breakout_price = float(signal.or_high if signal.direction == "LONG" else signal.or_low)
            session_rows = prices.loc[prices["session_date"].eq(signal.session_date)]
            event = {
                "session_date": signal.session_date,
                "contract": str(prices.loc[signal.signal_time, "contract"]),
                "or_minutes": int(duration),
                "breakout_type": "PRINT",
                "breakout_direction": signal.direction,
                "breakout_timestamp": signal.signal_time,
                "breakout_price": breakout_price,
                "feature_row_key": f"{signal.session_date.isoformat()}_{int(duration)}m",
                "outcome_definition": "signal-bar excursion is chronology-unknown; clean MFE/MAE starts with the first full post-signal bar",
            }
            signal_bar = prices.loc[signal.signal_time]
            event.update(_signal_bar_excursion_fields(signal_bar, signal.direction, breakout_price))
            for horizon in horizons:
                expected = pd.date_range(
                    signal.signal_time + pd.Timedelta(minutes=1), periods=int(horizon), freq="min"
                )
                selected = session_rows.loc[session_rows.index.intersection(expected)]
                complete = len(selected) == len(expected) and selected.index.equals(expected)
                event.update(_excursion_fields(selected, signal.direction, breakout_price, f"{int(horizon)}m", complete))
            session_end = pd.Timestamp.combine(signal.session_date, time(16, 0)).tz_localize(ET_TIMEZONE)
            expected_session = pd.date_range(signal.signal_time + pd.Timedelta(minutes=1), session_end, freq="min")
            selected_session = session_rows.loc[session_rows.index.intersection(expected_session)]
            complete_session = bool(
                len(expected_session) > 0
                and len(selected_session) == len(expected_session)
                and selected_session.index.equals(expected_session)
            )
            event.update(_excursion_fields(selected_session, signal.direction, breakout_price, "session_end", complete_session))
            events.append(event)
    outcomes = pd.DataFrame(events).sort_values(["breakout_timestamp", "or_minutes", "breakout_direction"]).reset_index(drop=True)
    if outcomes.duplicated(["session_date", "or_minutes", "breakout_direction"]).any():
        raise AssertionError("Validated first-direction PRINT outcomes must be unique")
    _assert_development(outcomes)
    ambiguity = pd.concat(ambiguity_rows, ignore_index=True) if ambiguity_rows else pd.DataFrame()
    return outcomes, ambiguity


def build_feature_contract(features: pd.DataFrame) -> pd.DataFrame:
    """Create a machine-auditable timing contract for every audit-table field."""
    return pd.DataFrame([_metadata_for_column(column) for column in features.columns])


def build_outcome_contract(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Describe the strict separation between signal-bar and later outcomes."""
    rows: list[dict[str, Any]] = []
    for column in outcomes.columns:
        if column.startswith("signal_bar_"):
            family = "signal_bar_descriptive_excursion"
            calculation = "OHLC extremes of the PRINT signal bar relative to the breakout reference"
            chronology_unknown = True
            first_included_bar = "PRINT signal bar"
        elif column.startswith("post_signal_bar_"):
            family = "clean_post_signal_bar_excursion"
            calculation = "complete one-minute bars strictly after the PRINT signal bar"
            chronology_unknown = False
            first_included_bar = "signal timestamp + 1 minute"
        else:
            family = "outcome_identity"
            calculation = "event identity or linkage"
            chronology_unknown = False
            first_included_bar = "not applicable"
        rows.append({
            "field_id": column,
            "outcome_family": family,
            "calculation_window": calculation,
            "first_included_bar": first_included_bar,
            "chronology_unknown": chronology_unknown,
            "strategy_execution_input": False,
            "future_label_not_causal_feature": True,
        })
    return pd.DataFrame(rows)


def build_window_availability_audit(
    prices: pd.DataFrame,
    window_config: Mapping[str, Any],
    *,
    window_ids: Iterable[str] = ("overnight", "overnight_context_2000_0900"),
) -> pd.DataFrame:
    """Classify each unavailable overnight/context observation without imputation."""
    _assert_development(prices)
    windows = load_context_windows(window_config)
    session_dates = sorted(prices["session_date"].unique())
    first_session = session_dates[0]
    rows: list[dict[str, Any]] = []
    for session_date in session_dates:
        session_rows = prices.loc[prices["session_date"].eq(session_date)]
        for window_id in window_ids:
            expected = expected_bar_end_index(session_date, windows[window_id])
            observed = session_rows.index.intersection(expected).sort_values()
            if len(observed) == len(expected) and observed.equals(expected):
                continue
            missing = expected.difference(observed)
            reason = _classify_unavailable_window(
                session_date=session_date,
                first_session=first_session,
                expected=expected,
                observed=observed,
                missing=missing,
            )
            rows.append({
                "session_date": session_date,
                "feature_window": window_id,
                "expected_bars": int(len(expected)),
                "observed_bars": int(len(observed)),
                "first_timestamp": observed[0] if len(observed) else pd.NaT,
                "last_timestamp": observed[-1] if len(observed) else pd.NaT,
                "first_missing_timestamp": missing[0] if len(missing) else pd.NaT,
                "last_missing_timestamp": missing[-1] if len(missing) else pd.NaT,
                "missing_bars": int(len(missing)),
                "unavailable_reason": reason,
            })
    return pd.DataFrame(rows)


def build_representative_review_queue(
    features: pd.DataFrame,
    availability_audit: pd.DataFrame,
) -> pd.DataFrame:
    """Select deterministic, non-performance examples for pending human review."""
    ordered = features.sort_values(["session_date", "or_minutes"]).copy()
    rows: list[dict[str, Any]] = []

    def add(case: str, candidates: pd.DataFrame, basis: str) -> None:
        if candidates.empty:
            rows.append({
                "review_case": case, "session_date": None, "or_minutes": None,
                "selection_basis": f"No populated candidate: {basis}",
                "human_review_status": "UNAVAILABLE", "human_notes": "",
            })
            return
        chosen = candidates.sort_values(["session_date", "or_minutes"]).iloc[0]
        rows.append({
            "review_case": case, "session_date": chosen["session_date"],
            "or_minutes": int(chosen["or_minutes"]), "selection_basis": basis,
            "human_review_status": "PENDING_HUMAN_REVIEW", "human_notes": "",
        })

    valid = ordered.loc[ordered["or_feature_available"]].copy()
    add("NARROW_OR", valid.nsmallest(1, "or_width_points"), "smallest populated OR width")
    add("WIDE_OR", valid.nlargest(1, "or_width_points"), "largest populated OR width")
    prior_touch = _any_level_state(ordered, ("previous_day_high", "previous_day_low"), "touched")
    add("PREVIOUS_DAY_LEVEL_TOUCH", ordered.loc[prior_touch], "previous-day high/low TOUCH")
    prior_levels = ("previous_day_high", "previous_day_low")
    prior_close = _any_level_state(ordered, ("previous_day_high", "previous_day_low"), "closed_through")
    prior_sweep = _any_level_state(ordered, ("previous_day_high", "previous_day_low"), "swept")
    prior_clean = _same_level_state_mask(
        ordered, prior_levels,
        required=("traded_through", "closed_through"),
        forbidden=("rejected",),
    )
    add("CLEAN_TRADE_THROUGH", ordered.loc[prior_clean], "same previous-day level TRADE_THROUGH plus CLOSE_THROUGH without REJECT")
    add("SWEEP", ordered.loc[prior_sweep], "previous-day level SWEEP")
    add("CLOSE_THROUGH", ordered.loc[prior_close], "previous-day level CLOSE_THROUGH")
    for label, levels in (
        ("ASIA_INTERACTION", ("asia_high", "asia_low")),
        ("LONDON_INTERACTION", ("london_high", "london_low")),
        ("NY_PREMARKET_INTERACTION", ("ny_premarket_high", "ny_premarket_low")),
    ):
        add(label, ordered.loc[_any_level_state(ordered, levels, "touched")], f"{label.replace('_INTERACTION', '')} high/low TOUCH")
    path_columns = [column for column in ordered if column.endswith("_state") and "_took_" in column]
    path_mask = pd.Series(False, index=ordered.index)
    for column in path_columns:
        path_mask |= ordered[column].fillna("NEITHER").ne("NEITHER")
    add("LIQUIDITY_PATH_SEQUENCE", ordered.loc[path_mask], "non-NEITHER pre-open liquidity-path state")
    for state in ("FILLED", "PARTIAL", "OPEN"):
        add(
            f"GLOBEX_GAP_{state}",
            ordered.loc[ordered["globex_reopen_gap_fill_state_at_0930"].eq(state)],
            f"GLOBEX_REOPEN_GAP state {state}",
        )
    if availability_audit.empty:
        add("INCOMPLETE_SOURCE_WINDOW", ordered.iloc[0:0], "unavailable overnight/context source window")
    else:
        unavailable = availability_audit.sort_values(["session_date", "feature_window"]).iloc[0]
        candidates = ordered.loc[ordered["session_date"].eq(unavailable["session_date"])]
        add(
            "INCOMPLETE_SOURCE_WINDOW", candidates,
            f"{unavailable['feature_window']}: {unavailable['unavailable_reason']}",
        )
    return _enrich_representative_review_queue(pd.DataFrame(rows), ordered)


def _same_level_state_mask(
    frame: pd.DataFrame,
    levels: Iterable[str],
    *,
    required: Iterable[str],
    forbidden: Iterable[str] = (),
) -> pd.Series:
    """Require every requested primitive to belong to one exact level."""
    combined = pd.Series(False, index=frame.index)
    for level in levels:
        level_mask = pd.Series(True, index=frame.index)
        for state in required:
            column = f"level_{level}_{state}"
            level_mask &= frame[column].fillna(False).astype(bool) if column in frame else False
        for state in forbidden:
            column = f"level_{level}_{state}"
            level_mask &= ~frame[column].fillna(False).astype(bool) if column in frame else True
        combined |= level_mask
    return combined


def _enrich_representative_review_queue(
    queue: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the exact evidence required to audit each representative case."""
    level_cases = {
        "PREVIOUS_DAY_LEVEL_TOUCH": (("previous_day_high", "previous_day_low"), ("touched",), ()),
        "CLEAN_TRADE_THROUGH": (
            ("previous_day_high", "previous_day_low"),
            ("traded_through", "closed_through"),
            ("rejected",),
        ),
        "SWEEP": (("previous_day_high", "previous_day_low"), ("swept",), ()),
        "CLOSE_THROUGH": (("previous_day_high", "previous_day_low"), ("closed_through",), ()),
        "ASIA_INTERACTION": (("asia_high", "asia_low"), ("touched",), ()),
        "LONDON_INTERACTION": (("london_high", "london_low"), ("touched",), ()),
        "NY_PREMARKET_INTERACTION": (("ny_premarket_high", "ny_premarket_low"), ("touched",), ()),
    }
    presets = {
        "NARROW_OR": "OR", "WIDE_OR": "OR",
        "PREVIOUS_DAY_LEVEL_TOUCH": "PREVIOUS DAY",
        "CLEAN_TRADE_THROUGH": "PREVIOUS DAY", "SWEEP": "PREVIOUS DAY",
        "CLOSE_THROUGH": "PREVIOUS DAY", "ASIA_INTERACTION": "ASIA",
        "LONDON_INTERACTION": "LONDON", "NY_PREMARKET_INTERACTION": "NY PRE-MARKET",
        "LIQUIDITY_PATH_SEQUENCE": "LIQUIDITY PATH",
        "GLOBEX_GAP_FILLED": "GLOBEX GAP", "GLOBEX_GAP_PARTIAL": "GLOBEX GAP",
        "GLOBEX_GAP_OPEN": "GLOBEX GAP", "INCOMPLETE_SOURCE_WINDOW": "OVERNIGHT",
    }
    empty = {
        "validation_preset": None, "trigger_type": None, "trigger_id": None,
        "trigger_label": None, "reference_price": np.nan,
        "or_open": np.nan, "or_high": np.nan, "or_low": np.nan, "or_close": np.nan,
        "start_side": None, "touch": None, "trade_through": None,
        "close_through": None, "reject": None, "sweep": None,
        "earlier_window": None, "later_window": None,
        "earlier_high": np.nan, "earlier_low": np.nan,
        "later_high": np.nan, "later_low": np.nan,
        "took_earlier_high": None, "took_earlier_low": None,
        "liquidity_path_state": None, "classification_summary": None,
    }
    records: list[dict[str, Any]] = []
    for _, review in queue.iterrows():
        record = {**review.to_dict(), **empty, "validation_preset": presets.get(review["review_case"])}
        if pd.isna(review["session_date"]) or pd.isna(review["or_minutes"]):
            records.append(record)
            continue
        matches = features.loc[
            features["session_date"].astype(str).eq(str(review["session_date"]))
            & pd.to_numeric(features["or_minutes"], errors="coerce").eq(int(review["or_minutes"]))
        ]
        if len(matches) != 1:
            raise AssertionError(f"Representative review row must resolve once: {review['review_case']}")
        feature = matches.iloc[0]
        record.update({name: feature.get(name, np.nan) for name in ("or_open", "or_high", "or_low", "or_close")})
        case = str(review["review_case"])
        if case in level_cases:
            levels, required, forbidden = level_cases[case]
            level = _first_matching_level(feature, levels, required, forbidden)
            if level is None:
                raise AssertionError(f"No exact triggering level found for {case}")
            record.update(_level_review_details(feature, level))
        elif case == "LIQUIDITY_PATH_SEQUENCE":
            path_key = _first_matching_liquidity_path(feature)
            if path_key is None:
                raise AssertionError("No explicit liquidity-path state found")
            record.update(_liquidity_path_review_details(feature, path_key))
        elif case in {"NARROW_OR", "WIDE_OR"}:
            record.update({
                "trigger_type": "OR_WIDTH", "trigger_id": "or_width_points",
                "trigger_label": "Opening Range width",
                "classification_summary": f"OR width = {float(feature['or_width_points']):.2f} points",
            })
        elif case.startswith("GLOBEX_GAP_"):
            state = feature.get("globex_reopen_gap_fill_state_at_0930")
            record.update({
                "trigger_type": "GAP_STATE",
                "trigger_id": "globex_reopen_gap_fill_state_at_0930",
                "trigger_label": "Globex reopen gap",
                "classification_summary": f"Globex reopen gap state = {state}",
            })
        elif case == "INCOMPLETE_SOURCE_WINDOW":
            record.update({
                "trigger_type": "AVAILABILITY",
                "trigger_id": str(review["selection_basis"]).split(":", 1)[0],
                "trigger_label": "Incomplete source window",
                "classification_summary": review["selection_basis"],
            })
        records.append(record)
    return pd.DataFrame(records)


def _first_matching_level(
    row: Mapping[str, Any],
    levels: Iterable[str],
    required: Iterable[str],
    forbidden: Iterable[str],
) -> str | None:
    for level in levels:
        if all(_feature_flag(row.get(f"level_{level}_{state}")) for state in required) and not any(
            _feature_flag(row.get(f"level_{level}_{state}")) for state in forbidden
        ):
            return level
    return None


def _feature_flag(value: Any) -> bool:
    return False if value is None or pd.isna(value) else bool(value)


def _level_review_details(row: Mapping[str, Any], level: str) -> dict[str, Any]:
    prefix = f"level_{level}_"
    labels = {
        "previous_day_high": "Previous Day High", "previous_day_low": "Previous Day Low",
        "asia_high": "Asia High", "asia_low": "Asia Low",
        "london_high": "London High", "london_low": "London Low",
        "ny_premarket_high": "NY Pre-Market High", "ny_premarket_low": "NY Pre-Market Low",
    }
    label = labels.get(level, level.replace("_", " ").title())
    flags = {
        "touch": _feature_flag(row.get(f"{prefix}touched")),
        "trade_through": _feature_flag(row.get(f"{prefix}traded_through")),
        "close_through": _feature_flag(row.get(f"{prefix}closed_through")),
        "reject": _feature_flag(row.get(f"{prefix}rejected")),
        "sweep": _feature_flag(row.get(f"{prefix}swept")),
    }
    summary = " · ".join(f"{name.upper()}={str(value).lower()}" for name, value in flags.items())
    return {
        "trigger_type": "KEY_LEVEL_INTERACTION", "trigger_id": level,
        "trigger_label": label, "reference_price": row.get(level, np.nan),
        "start_side": row.get(f"{prefix}start_side"), **flags,
        "classification_summary": summary,
    }


def _first_matching_liquidity_path(row: Mapping[str, Any]) -> str | None:
    for key in ("london_took_asia", "ny_premarket_took_london", "ny_premarket_took_asia"):
        state = row.get(f"{key}_state")
        if state is not None and not pd.isna(state) and state != "NEITHER":
            return key
    return None


def _liquidity_path_review_details(row: Mapping[str, Any], key: str) -> dict[str, Any]:
    later, earlier = key.split("_took_", 1)
    display = {"asia": "Asia", "london": "London", "ny_premarket": "NY pre-market"}
    state = row.get(f"{key}_state")
    took_high = _feature_flag(row.get(f"{key}_high"))
    took_low = _feature_flag(row.get(f"{key}_low"))
    return {
        "trigger_type": "LIQUIDITY_PATH", "trigger_id": key,
        "trigger_label": f"{display[later]} versus {display[earlier]}",
        "earlier_window": display[earlier], "later_window": display[later],
        "earlier_high": row.get(f"{earlier}_high", np.nan),
        "earlier_low": row.get(f"{earlier}_low", np.nan),
        "later_high": row.get(f"{later}_high", np.nan),
        "later_low": row.get(f"{later}_low", np.nan),
        "took_earlier_high": took_high, "took_earlier_low": took_low,
        "liquidity_path_state": state,
        "classification_summary": (
            f"{display[later]} took {display[earlier]} high={str(took_high).lower()} · "
            f"low={str(took_low).lower()} · state={state}"
        ),
    }


def apply_human_review_decisions(
    review_queue: pd.DataFrame,
    decisions: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Overlay versioned human decisions without changing canonical features."""
    result = review_queue.copy()
    for decision in decisions:
        mask = (
            result["review_case"].eq(decision["review_case"])
            & result["session_date"].astype(str).eq(str(decision["session_date"]))
            & pd.to_numeric(result["or_minutes"], errors="coerce").eq(int(decision["or_minutes"]))
        )
        if int(mask.sum()) != 1:
            raise AssertionError(f"Human review target must match exactly once: {decision['review_case']}")
        result.loc[mask, "human_review_status"] = decision["human_review_status"]
        result.loc[mask, "human_notes"] = decision.get("human_notes", "")
        result.loc[mask, "human_reviewer"] = decision.get("human_reviewer", "")
        result.loc[mask, "human_reviewed_at"] = decision.get("human_reviewed_at", "")
    return result


def characterize_features(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Describe distributions and redundancy without using outcome columns."""
    distribution_rows: list[dict[str, Any]] = []
    correlation_rows: list[dict[str, Any]] = []
    selected_features = [column for column in CHARACTERIZATION_FEATURES if column in features]
    for duration, group in features.groupby("or_minutes", sort=True):
        for column in selected_features:
            values = pd.to_numeric(group[column], errors="coerce").dropna()
            distribution_rows.append({
                "or_minutes": int(duration), "feature_id": column,
                "count": int(len(values)), "missing": int(group[column].isna().sum()),
                "mean": values.mean(), "std": values.std(ddof=1), "min": values.min(),
                "p10": values.quantile(.10), "p25": values.quantile(.25),
                "median": values.median(), "p75": values.quantile(.75),
                "p90": values.quantile(.90), "max": values.max(),
            })
        numeric = group[selected_features].apply(pd.to_numeric, errors="coerce")
        corr = numeric.corr()
        for left in selected_features:
            for right in selected_features:
                paired = numeric[[left, right]].dropna()
                correlation_rows.append({
                    "or_minutes": int(duration), "feature_x": left, "feature_y": right,
                    "correlation": corr.loc[left, right], "paired_count": len(paired),
                })
    return pd.DataFrame(distribution_rows), pd.DataFrame(correlation_rows)


def write_characterization_charts(
    features: pd.DataFrame,
    correlations: pd.DataFrame,
    *,
    distribution_path: str | Path,
    correlation_path: str | Path,
) -> None:
    """Write interactive DEVELOPMENT-only feature distribution/correlation HTML."""
    distribution_figure = go.Figure()
    trace_labels: list[str] = []
    for duration in sorted(features["or_minutes"].unique()):
        group = features.loc[features["or_minutes"].eq(duration)]
        for column in CHARACTERIZATION_FEATURES:
            if column not in group:
                continue
            values = pd.to_numeric(group[column], errors="coerce").dropna()
            distribution_figure.add_trace(go.Histogram(
                x=values, nbinsx=30, name=f"{duration}m · {column}", visible=False,
                hovertemplate="Value=%{x:.6f}<br>Count=%{y}<extra></extra>",
            ))
            trace_labels.append(f"{duration}m · {column}")
    if distribution_figure.data:
        distribution_figure.data[0].visible = True
    buttons = []
    for index, label in enumerate(trace_labels):
        visible = [False] * len(trace_labels)
        visible[index] = True
        buttons.append({"label": label, "method": "update", "args": [{"visible": visible}, {"title": f"DEVELOPMENT ONLY · {label}"}]})
    distribution_figure.update_layout(
        title=f"DEVELOPMENT ONLY · {trace_labels[0] if trace_labels else 'Feature distributions'}",
        template="plotly_white", bargap=.03,
        updatemenus=[{"buttons": buttons, "direction": "down", "x": 0, "y": 1.16}],
        xaxis_title="Feature value", yaxis_title="Sessions",
    )
    distribution_figure.write_html(distribution_path, include_plotlyjs="cdn", full_html=True)

    correlation_figure = go.Figure()
    durations = sorted(correlations["or_minutes"].unique())
    for index, duration in enumerate(durations):
        matrix = correlations.loc[correlations["or_minutes"].eq(duration)].pivot(
            index="feature_y", columns="feature_x", values="correlation"
        )
        correlation_figure.add_trace(go.Heatmap(
            z=matrix.values, x=matrix.columns, y=matrix.index, zmin=-1, zmax=1,
            colorscale="RdBu", reversescale=True, visible=index == 0,
            colorbar={"title": "Correlation"},
        ))
    correlation_figure.update_layout(
        title=f"DEVELOPMENT ONLY · Feature correlation · {durations[0]}m OR",
        template="plotly_white",
        updatemenus=[{"buttons": [
            {"label": f"{duration}m", "method": "update", "args": [
                {"visible": [position == index for position in range(len(durations))]},
                {"title": f"DEVELOPMENT ONLY · Feature correlation · {duration}m OR"},
            ]} for index, duration in enumerate(durations)
        ]}],
        height=850,
    )
    correlation_figure.write_html(correlation_path, include_plotlyjs="cdn", full_html=True)


def feature_summary(features: pd.DataFrame, outcomes: pd.DataFrame, ambiguous: pd.DataFrame) -> dict[str, Any]:
    return {
        "feature_rows": int(len(features)),
        "sessions": int(features["session_date"].nunique()),
        "or_durations": sorted(int(value) for value in features["or_minutes"].unique()),
        "minimum_session_date": features["session_date"].min().isoformat(),
        "maximum_session_date": features["session_date"].max().isoformat(),
        "complete_or_rows": int(features["or_feature_available"].sum()),
        "complete_ny_premarket_rows": int(features["ny_premarket_feature_available"].sum()),
        "complete_previous_day_rows": int(features["previous_day_feature_available"].sum()),
        "complete_ny_open_gap_rows": int(features["ny_open_gap_feature_available"].sum()),
        "outcome_events": int(len(outcomes)),
        "ambiguous_print_bars": int(len(ambiguous)),
        "validation_or_oos_loaded": False,
    }


def _flatten_window(prefix: str, summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_{key}": value
        for key, value in summary.items()
        if key != "window_id"
    }


def _session_contract(session_rows: pd.DataFrame) -> str:
    stamps = session_rows.between_time("09:31", "10:00").index
    if len(stamps):
        return str(session_rows.loc[stamps[0], "contract"])
    return str(session_rows.iloc[0]["contract"])


def _key_levels(row: Mapping[str, Any]) -> dict[str, float]:
    return {
        "previous_day_high": row.get("previous_day_high", np.nan),
        "previous_day_low": row.get("previous_day_low", np.nan),
        "previous_day_close": row.get("previous_day_close", np.nan),
        "previous_rth_high": row.get("previous_rth_high", np.nan),
        "previous_rth_low": row.get("previous_rth_low", np.nan),
        "previous_rth_close": row.get("previous_rth_close", np.nan),
        "overnight_high": row.get("overnight_high", np.nan),
        "overnight_low": row.get("overnight_low", np.nan),
        "asia_high": row.get("asia_high", np.nan),
        "asia_low": row.get("asia_low", np.nan),
        "london_high": row.get("london_high", np.nan),
        "london_low": row.get("london_low", np.nan),
        "ny_premarket_high": row.get("ny_premarket_high", np.nan),
        "ny_premarket_low": row.get("ny_premarket_low", np.nan),
        "globex_reopen": row.get("globex_reopen_price", np.nan),
        "globex_reopen_prior_1700_close": row.get("globex_reopen_gap_prior_1700_close", np.nan),
        "ny_open_prior_1614_close": row.get("ny_open_gap_prior_1614_close", np.nan),
        "ny_open_reference": row.get("ny_open_reference_price", np.nan),
    }


def _liquidity_path(summaries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    comparisons = (
        ("london", "asia"),
        ("ny_premarket", "london"),
        ("ny_premarket", "asia"),
    )
    for later, earlier in comparisons:
        available = bool(summaries[later]["feature_available"] and summaries[earlier]["feature_available"])
        high = bool(available and summaries[later]["high"] > summaries[earlier]["high"])
        low = bool(available and summaries[later]["low"] < summaries[earlier]["low"])
        key = f"{later}_took_{earlier}"
        output[f"{key}_available"] = available
        output[f"{key}_high"] = high if available else None
        output[f"{key}_low"] = low if available else None
        output[f"{key}_state"] = interaction_state(high, low) if available else None
    return output


def _expansion_ratios(row: Mapping[str, Any]) -> dict[str, float]:
    width = row["or_width_points"]
    return {
        "or_to_asia_range_ratio": _ratio(width, row.get("asia_range_points")),
        "or_to_london_range_ratio": _ratio(width, row.get("london_range_points")),
        "or_to_ny_premarket_range_ratio": _ratio(width, row.get("ny_premarket_range_points")),
        "or_to_overnight_context_2000_0900_range_ratio": _ratio(
            width, row.get("overnight_context_2000_0900_range_points")
        ),
    }


def _ratio(numerator: Any, denominator: Any) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or float(denominator) <= 1e-12:
        return np.nan
    return float(numerator) / float(denominator)


def _excursion_fields(
    bars: pd.DataFrame,
    direction: str,
    breakout_price: float,
    suffix: str,
    complete: bool,
) -> dict[str, Any]:
    prefix = f"post_signal_bar_{suffix}"
    if not complete or bars.empty:
        return {
            f"{prefix}_complete": False, f"{prefix}_bars": int(len(bars)),
            f"{prefix}_end_timestamp": pd.NaT, f"{prefix}_mfe_points": np.nan,
            f"{prefix}_mae_points": np.nan, f"{prefix}_mfe_pct": np.nan,
            f"{prefix}_mae_pct": np.nan,
        }
    if direction == "LONG":
        mfe = max(0.0, float(bars["high"].max()) - breakout_price)
        mae = max(0.0, breakout_price - float(bars["low"].min()))
    else:
        mfe = max(0.0, breakout_price - float(bars["low"].min()))
        mae = max(0.0, float(bars["high"].max()) - breakout_price)
    return {
        f"{prefix}_complete": True, f"{prefix}_bars": int(len(bars)),
        f"{prefix}_end_timestamp": bars.index[-1], f"{prefix}_mfe_points": mfe,
        f"{prefix}_mae_points": mae, f"{prefix}_mfe_pct": mfe / breakout_price,
        f"{prefix}_mae_pct": mae / breakout_price,
    }


def _signal_bar_excursion_fields(
    bar: pd.Series,
    direction: str,
    breakout_price: float,
) -> dict[str, Any]:
    """Return observable signal-bar extremes without inferring their order."""
    if direction == "LONG":
        favorable = max(0.0, float(bar["high"]) - breakout_price)
        adverse = max(0.0, breakout_price - float(bar["low"]))
    else:
        favorable = max(0.0, breakout_price - float(bar["low"]))
        adverse = max(0.0, float(bar["high"]) - breakout_price)
    return {
        "signal_bar_favorable_excursion_points": favorable,
        "signal_bar_adverse_excursion_points": adverse,
        "signal_bar_favorable_excursion_pct": favorable / breakout_price,
        "signal_bar_adverse_excursion_pct": adverse / breakout_price,
        "signal_bar_chronology_unknown": True,
    }


def _metadata_for_column(column: str) -> dict[str, Any]:
    metadata = {
        "feature_id": column, "feature_family": "audit_identity",
        "calculation_window": "not applicable", "timezone": ET_TIMEZONE,
        "earliest_availability_timestamp": "row identity",
        "causal": True, "required_warmup": "none",
        "normalization_method": "none", "source_columns": "derived identity",
        "missing_data_behavior": "required",
    }
    if column.startswith("or_width_hist_"):
        lookback = column.split("_")[3]
        metadata.update(feature_family="causal_historical_or_width", calculation_window=f"{lookback} prior completed sessions, same OR duration", earliest_availability_timestamp="OR completion", required_warmup=f"{lookback} prior valid OR widths", source_columns="or_width_points; prior session_date only", missing_data_behavior="null/unavailable before full warm-up")
    elif column.startswith("or_to_"):
        metadata.update(feature_family="preopen_expansion", calculation_window="pre-open window plus configured OR", earliest_availability_timestamp="OR completion", source_columns="or_width_points; window range_points", missing_data_behavior="null for missing/near-zero denominator")
    elif column.startswith("or_"):
        metadata.update(feature_family="opening_range", calculation_window="09:30 market time through configured OR completion", earliest_availability_timestamp="configured OR completion", source_columns="timestamp_et; open; high; low; close", missing_data_behavior="null/unavailable unless every expected bar exists")
    elif column.startswith("previous_day_"):
        metadata.update(feature_family="previous_full_trading_day_levels", calculation_window="prior futures trading day: prior-calendar-day 18:01 through trading-date 17:00 bar-end", earliest_availability_timestamp="prior trading day 17:00 ET", source_columns="prior session_date; OHLC", missing_data_behavior="null/unavailable unless the complete prior futures trading day exists")
    elif column.startswith("previous_rth_"):
        metadata.update(feature_family="previous_rth_levels", calculation_window="prior trading session 09:30-16:00 market time", earliest_availability_timestamp="prior session 16:00 ET", source_columns="prior session_date; OHLC", missing_data_behavior="null/unavailable without complete prior RTH")
    elif column.startswith("globex_reopen_gap_") or column == "globex_reopen_price":
        metadata.update(feature_family="globex_reopen_gap", calculation_window="prior 17:00 close to current 09:30 ET", earliest_availability_timestamp="09:30 ET", source_columns="prior close; 18:01 reopen bar open; pre-open high/low", missing_data_behavior="null/unavailable if close, reopen, or pre-open rows missing")
    elif column.startswith("ny_open_gap_") or column.startswith("ny_open_reference_"):
        metadata.update(feature_family="ny_open_gap", calculation_window="prior trading day's 16:14 bar close to current 09:31 bar open", earliest_availability_timestamp="09:31 ET bar-end", source_columns="prior 16:14 close; current 09:31 bar open", missing_data_behavior="null/unavailable; no substitute bar")
    elif column.startswith("level_") or column.endswith("_price"):
        metadata.update(feature_family="key_level_interaction", calculation_window="configured OR", earliest_availability_timestamp="OR completion", source_columns="OR OHLC; causal key-level price", missing_data_behavior="unavailable flags and null distances")
    elif "_took_" in column:
        metadata.update(feature_family="session_liquidity_path", calculation_window="Asia, London, and New York pre-market windows", earliest_availability_timestamp="09:00 ET", source_columns="window high/low", missing_data_behavior="null state when either source window incomplete")
    else:
        for prefix, label, available in (
            ("asia_", "preopen_asia", "00:00 ET"),
            ("london_", "preopen_london", "05:00 ET"),
            ("ny_premarket_", "preopen_new_york", "09:00 ET"),
            ("overnight_", "preopen_overnight", "09:30 ET"),
            ("overnight_context_2000_0900_", "overnight_context_2000_0900", "09:00 ET"),
        ):
            if column.startswith(prefix):
                metadata.update(feature_family=label, calculation_window=prefix.rstrip("_"), earliest_availability_timestamp=available, source_columns="timestamp_et; OHLC", missing_data_behavior="null/unavailable unless every expected bar exists")
                break
    if column.endswith("_pct"):
        metadata["normalization_method"] = "decimal ratio using the explicitly recorded reference price"
    return metadata


def _classify_unavailable_window(
    *,
    session_date: date,
    first_session: date,
    expected: pd.DatetimeIndex,
    observed: pd.DatetimeIndex,
    missing: pd.DatetimeIndex,
) -> str:
    if session_date == first_session and len(missing) and missing[0] == expected[0]:
        return "DATASET_BOUNDARY"
    if (
        len(missing)
        and missing[0] == expected[0]
        and missing[-1].time() == time(0, 0)
        and len(observed)
        and observed[0].time() == time(0, 1)
        and session_date.month in {3, 6, 9, 12}
    ):
        return "CONTRACT_ROLL_DATA_GAP"
    if not len(observed):
        return "MISSING_SOURCE_BARS"
    return "MISSING_SOURCE_BARS"


def _any_level_state(
    frame: pd.DataFrame,
    levels: Iterable[str],
    state: str,
) -> pd.Series:
    mask = pd.Series(False, index=frame.index)
    for level in levels:
        column = f"level_{level}_{state}"
        if column in frame:
            mask |= frame[column].fillna(False).astype(bool)
    return mask


def _assert_development(frame: pd.DataFrame) -> None:
    if "session_date" not in frame:
        raise AssertionError("session_date is required")
    values = pd.Series(frame["session_date"]).dropna()
    if values.empty:
        raise AssertionError("No DEVELOPMENT sessions were provided")
    if values.min() < DEVELOPMENT_START or values.max() > DEVELOPMENT_END:
        raise AssertionError("Validation or OOS session entered Stage 2")


def _validate_feature_math(frame: pd.DataFrame) -> None:
    valid_or = frame.loc[frame["or_feature_available"]]
    if not np.allclose(valid_or["or_width_points"], valid_or["or_high"] - valid_or["or_low"]):
        raise AssertionError("OR range does not reconcile")
    if not np.allclose(valid_or["or_width_pct"], valid_or["or_width_points"] / valid_or["or_reference_price"]):
        raise AssertionError("OR normalization does not reconcile")
    if not valid_or["or_efficiency"].between(0, 1).all():
        raise AssertionError("OR efficiency outside [0, 1]")
    if not valid_or["or_clv"].between(0, 1).all():
        raise AssertionError("OR CLV outside [0, 1]")


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
