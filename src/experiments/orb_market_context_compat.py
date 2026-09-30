"""ORB compatibility layer over the generic Market Context catalog (M5B).

The generic catalog (``src/features/session_context.py`` +
``config/features/market_context_windows.json``) is the authority for market
context.  Frozen ORB V0.2 research consumes it here.  Compatibility behavior
exists only where frozen ORB semantics genuinely differ:

- ``overnight``: frozen ORB used 18:00-09:30.  It is evaluated through the
  labelled compatibility definition ``orb_overnight_1800_0930``
  (``config/features/market_context_compatibility.json``).  The generic
  Overnight (18:00-07:00) is unchanged.
- ``previous_day`` / ``previous_rth``: frozen ORB used the previous session
  *present in the dataset*.  ``previous_available_session_legacy_orb`` isolates
  that policy.  Generic context uses the previous *expected* session and
  never falls back (D-113).
- ORB availability is completeness only (``is_complete``).  The summary is
  mapped to ORB's historical schema by ``to_orb_window_summary``.

Asia, London, NY pre-market and Overnight Context use the generic
definitions directly; no ORB duplicate exists.  Every window is evaluated
by the one generic engine, ``evaluate_context``.  New strategies must use
the generic API, not this module.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.data.sessions import SessionBounds, SessionSpec, load_session_spec, session_bounds, with_calendar_overrides
from src.features.market_context import _direction, _safe_divide
from src.features.session_context import (
    ONE_MINUTE,
    PREVIOUS_DAY_CONTEXT_ID,
    MarketContextError,
    MarketContextRegistry,
    evaluate_context,
    load_market_context_windows,
    prepare_context_bars,
    summarize_context,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ORB_COMPAT_CONFIG = PROJECT_ROOT / "config" / "features" / "market_context_compatibility.json"
ORB_INSTRUMENT_ID = "MNQ"

GENERIC = "generic"
COMPATIBILITY = "compatibility"

# ORB feature prefix -> (registry, context_id, legacy ORB window_id carried in the summary).
ORB_CONTEXT_SOURCES: Mapping[str, tuple[str, str, str]] = {
    "asia": (GENERIC, "asia_2000_0000", "asia_kill_zone"),
    "london": (GENERIC, "london_0200_0500", "london_kill_zone"),
    "ny_premarket": (GENERIC, "ny_premarket_0700_0900", "ny_premarket"),
    "overnight": (COMPATIBILITY, "orb_overnight_1800_0930", "overnight"),
    "overnight_context_2000_0900": (GENERIC, "overnight_context_2000_0900", "overnight_context_2000_0900"),
    "previous_day": (GENERIC, PREVIOUS_DAY_CONTEXT_ID, "trading_day"),
    "previous_rth": (GENERIC, "previous_rth", "rth"),
}
# Prefixes whose source session follows the legacy previous-AVAILABLE policy.
LEGACY_PREVIOUS_SESSION_PREFIXES = frozenset({"previous_day", "previous_rth"})
# Frozen ORB window config id -> ORB prefix (verified against the catalog).
ORB_CONFIG_WINDOW_PREFIXES: Mapping[str, str] = {
    "asia_kill_zone": "asia",
    "london_kill_zone": "london",
    "ny_premarket": "ny_premarket",
    "overnight": "overnight",
    "overnight_context_2000_0900": "overnight_context_2000_0900",
}
ORB_SUMMARY_KEYS = (
    "window_id", "feature_available", "expected_bars", "observed_bars", "available_at", "missing_reason",
    "first_bar_end", "last_bar_end", "open", "high", "low", "close", "range_points", "reference_price",
    "range_pct", "net_move_points", "net_move_pct", "direction", "efficiency", "high_timestamp",
    "low_timestamp",
)
NO_PRIOR_SESSION = "NO_PRIOR_SESSION"
INCOMPLETE_WINDOW = "INCOMPLETE_WINDOW"


def load_orb_compatibility_registry(session_spec: SessionSpec) -> MarketContextRegistry:
    """Load the ORB-only compatibility definitions (validated by the generic loader)."""
    return load_market_context_windows(session_spec, ORB_COMPAT_CONFIG)


def previous_available_session_legacy_orb(
    target_trading_date: date,
    available_trading_dates: Sequence[date],
    session_spec: SessionSpec,
) -> SessionBounds | None:
    """LEGACY ORB POLICY: the latest session *present in the dataset* before the target.

    Reproduces frozen ORB V0.2 behavior only.  Unlike the generic
    ``previous_expected_session``, it silently skips missing expected sessions.
    Returns None when no earlier session is present.
    """
    earlier = [day for day in available_trading_dates if day < target_trading_date]
    if not earlier:
        return None
    bounds = session_bounds(max(earlier), session_spec)
    if not bounds.is_open:
        raise MarketContextError(f"Dataset session {max(earlier)} is not an open session")
    return bounds


def assert_orb_window_config_matches(
    window_config: Mapping[str, Any],
    generic: MarketContextRegistry,
    compatibility: MarketContextRegistry,
) -> None:
    """Fail if the frozen ORB window config drifts from the definitions used for it."""
    configured = {item["window_id"]: item for item in window_config["windows"]}
    missing = sorted(set(ORB_CONFIG_WINDOW_PREFIXES) - set(configured))
    if missing:
        raise MarketContextError(f"ORB window config missing {missing}")
    for window_id, prefix in ORB_CONFIG_WINDOW_PREFIXES.items():
        item = configured[window_id]
        start = _minutes(item["start_time_et"]) + 1440 * int(item.get("start_day_offset", 0))
        end = _minutes(item["end_time_et"])
        if end <= start:
            end += 1440
        registry_name, context_id, _ = ORB_CONTEXT_SOURCES[prefix]
        registry = generic if registry_name == GENERIC else compatibility
        window = registry.get(context_id).window
        catalog_start = _minutes(window.start_time.isoformat()) + 1440 * window.start_day_offset
        catalog_end = _minutes(window.end_time.isoformat()) + 1440 * window.end_day_offset
        if (start, end) != (catalog_start, catalog_end):
            raise MarketContextError(
                f"ORB window {window_id!r} ({start}->{end} min) differs from {context_id!r} "
                f"({catalog_start}->{catalog_end} min)"
            )


def orb_window_summaries(
    prices: pd.DataFrame,
    window_config: Mapping[str, Any],
    session_spec: SessionSpec | None = None,
    *,
    instrument_id: str = ORB_INSTRUMENT_ID,
) -> dict[date, dict[str, dict[str, Any]]]:
    """ORB-schema window summaries per dataset session, computed by the generic engine."""
    spec = session_spec if session_spec is not None else load_session_spec()
    generic = load_market_context_windows(spec)
    compatibility = load_orb_compatibility_registry(spec)
    assert_orb_window_config_matches(window_config, generic, compatibility)
    prepared = prepare_context_bars(prices, spec)
    regular = with_calendar_overrides(spec, [])
    dataset_dates = sorted(prepared.bars_by_date)
    engine = {
        "session_spec": spec, "regular_spec": regular, "instrument_id": instrument_id,
        "coverage_start": prepared.coverage_start, "coverage_end": prepared.coverage_end,
        "interval": prepared.interval,
    }

    output: dict[date, dict[str, dict[str, Any]]] = {}
    for target in dataset_dates:
        summaries: dict[str, dict[str, Any]] = {}
        for prefix, (registry_name, context_id, legacy_window_id) in ORB_CONTEXT_SOURCES.items():
            definition = (generic if registry_name == GENERIC else compatibility).get(context_id)
            if prefix in LEGACY_PREVIOUS_SESSION_PREFIXES:
                source = previous_available_session_legacy_orb(target, dataset_dates, spec)
                if source is None:
                    # Frozen ORB summarized the target date's own window with no bars.
                    record = evaluate_context(
                        definition, target, session_bounds(target, spec), {},
                        engine["session_spec"], engine["regular_spec"], instrument_id=instrument_id,
                        coverage_start=engine["coverage_start"], coverage_end=engine["coverage_end"],
                        interval=engine["interval"],
                    )
                    summaries[prefix] = to_orb_window_summary(record, legacy_window_id, no_prior_session=True)
                    continue
                record = evaluate_context(
                    definition, target, source, prepared.bars_by_date,
                    engine["session_spec"], engine["regular_spec"], instrument_id=instrument_id,
                    coverage_start=engine["coverage_start"], coverage_end=engine["coverage_end"],
                    interval=engine["interval"],
                )
            else:
                record = summarize_context(
                    definition, target, prepared.bars_by_date, engine["session_spec"], engine["regular_spec"],
                    instrument_id=instrument_id, coverage_start=engine["coverage_start"],
                    coverage_end=engine["coverage_end"], interval=engine["interval"],
                )
            summaries[prefix] = to_orb_window_summary(record, legacy_window_id)
        output[target] = summaries
    return output


def to_orb_window_summary(
    record: Mapping[str, Any],
    legacy_window_id: str,
    *,
    no_prior_session: bool = False,
) -> dict[str, Any]:
    """Map one generic summary row to frozen ORB's ``summarize_window`` schema.

    Legacy ORB availability means completeness only; prices are NaN unless
    complete; ``missing_reason`` is ``""``, ``INCOMPLETE_WINDOW`` or
    ``NO_PRIOR_SESSION``.
    """
    complete = bool(record["is_complete"]) and not no_prior_session
    window_start, window_end = record["window_start"], record["window_end"]
    summary: dict[str, Any] = {
        "window_id": legacy_window_id,
        "feature_available": complete,
        "expected_bars": int(record["expected_count"]),
        "observed_bars": int(record["observed_count"]),
        "available_at": pd.NaT if no_prior_session else window_end,
        "missing_reason": NO_PRIOR_SESSION if no_prior_session else ("" if complete else INCOMPLETE_WINDOW),
        "first_bar_end": window_start + ONE_MINUTE,  # ORB data are 1m bar-end labels
        "last_bar_end": window_end,
    }
    if not complete:
        summary.update(
            open=np.nan, high=np.nan, low=np.nan, close=np.nan, range_points=np.nan, reference_price=np.nan,
            range_pct=np.nan, net_move_points=np.nan, net_move_pct=np.nan, direction=None, efficiency=np.nan,
            high_timestamp=pd.NaT, low_timestamp=pd.NaT,
        )
        return {key: summary[key] for key in ORB_SUMMARY_KEYS}
    open_price, high, low, close = (float(record[f"observed_{field}"]) for field in ("open", "high", "low", "close"))
    width, net = high - low, close - open_price
    summary.update(
        open=open_price, high=high, low=low, close=close, range_points=width, reference_price=open_price,
        range_pct=_safe_divide(width, open_price), net_move_points=net, net_move_pct=_safe_divide(net, open_price),
        direction=_direction(net), efficiency=_safe_divide(abs(net), width),
        high_timestamp=record["high_at"], low_timestamp=record["low_at"],
    )
    return {key: summary[key] for key in ORB_SUMMARY_KEYS}


def _minutes(value: str) -> int:
    parsed = time.fromisoformat(str(value))
    return parsed.hour * 60 + parsed.minute
