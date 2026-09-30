"""Generic Market Context (M5A): strategy-independent session context.

Context is computed from canonical, bar-end-labelled 1-minute bars with the
generic session model (``src/data/sessions.py``).  It never depends on ORB
code or on derived-timeframe caches.

Three tiers keep diagnostic values away from consumers:

- ``build_market_context``: audit summary, one row per (target trading date,
  context).  Prices appear only as ``observed_*`` columns next to
  ``is_available`` / ``unavailable_reason``.
- ``valid_context_levels``: available contexts only, with plain
  ``open/high/low/close`` columns.
- ``align_market_context``: per-bar causal view.  A level is exposed only
  when the context is valid, ``bar_start >= available_at``, the bar belongs
  to the context's target trading date, and the contracts match.

Rules (D-113, D-123, M5A decisions):

- Strict completeness: every scheduled 1m bar must be present.  No fill,
  interpolation, substitution or silent shortening.
- Windows are intersected with the actual session (verified overrides);
  ``is_schedule_clipped`` flags clipping, ``NOT_SCHEDULED`` a window with no
  scheduled minutes.
- Previous-session contexts use the previous *expected* session and never
  fall back to an older available session.
- A window containing more than one contract is ``MIXED_CONTRACT``.
- ``calendar_verified`` is metadata only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import json
import re

import numpy as np
import pandas as pd

from src.data.instruments import load_instrument
from src.data.sessions import (
    LABEL_BAR_END,
    SessionSpec,
    assign_trading_dates,
    previous_expected_session,
    session_bounds,
    with_calendar_overrides,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTEXT_CONFIG = PROJECT_ROOT / "config" / "features" / "market_context_windows.json"
ONE_MINUTE = pd.Timedelta(minutes=1)

SOURCE_TARGET = "TARGET"
SOURCE_PREVIOUS_EXPECTED = "PREVIOUS_EXPECTED"
FULL_SESSION_WINDOW_ID = "full_session"
PREVIOUS_DAY_CONTEXT_ID = "previous_day"
PREVIOUS_DAY_DEFINITION_VERSION = 1

TARGET_SESSION_WINDOW = "TARGET_SESSION_WINDOW"
PREVIOUS_SESSION_WINDOW = "PREVIOUS_SESSION_WINDOW"
PREVIOUS_SESSION = "PREVIOUS_SESSION"

# Summary unavailable reasons, in precedence order (first match wins).
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
INSUFFICIENT_FUTURE_COVERAGE = "INSUFFICIENT_FUTURE_COVERAGE"
MISSING_EXPECTED_SESSION = "MISSING_EXPECTED_SESSION"
NOT_SCHEDULED = "NOT_SCHEDULED"
NO_OBSERVATIONS = "NO_OBSERVATIONS"
MIXED_CONTRACT = "MIXED_CONTRACT"
INCOMPLETE_WINDOW = "INCOMPLETE_WINDOW"
UNAVAILABLE_REASONS = (
    INSUFFICIENT_HISTORY,
    INSUFFICIENT_FUTURE_COVERAGE,
    MISSING_EXPECTED_SESSION,
    NOT_SCHEDULED,
    NO_OBSERVATIONS,
    MIXED_CONTRACT,
    INCOMPLETE_WINDOW,
)

# Per-bar alignment statuses (never used as summary reasons).
ALIGN_AVAILABLE = "AVAILABLE"
ALIGN_PENDING = "PENDING"
ALIGN_UNAVAILABLE_CONTEXT = "UNAVAILABLE_CONTEXT"
ALIGN_CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
ALIGNMENT_STATUSES = (ALIGN_AVAILABLE, ALIGN_PENDING, ALIGN_UNAVAILABLE_CONTEXT, ALIGN_CONTRACT_MISMATCH)

SUMMARY_COLUMNS = [
    "context_id",
    "context_type",
    "window_id",
    "definition_version",
    "instrument_id",
    "target_trading_date",
    "source_trading_date",
    "window_start",
    "window_end",
    "available_at",
    "contract",
    "contract_count",
    "observed_open",
    "observed_high",
    "observed_low",
    "observed_close",
    "high_at",
    "low_at",
    "expected_count",
    "observed_count",
    "missing_count",
    "is_complete",
    "is_schedule_clipped",
    "is_available",
    "unavailable_reason",
    "calendar_verified",
]
VALID_LEVEL_COLUMNS = [
    "context_id",
    "context_type",
    "definition_version",
    "instrument_id",
    "target_trading_date",
    "source_trading_date",
    "available_at",
    "contract",
    "open",
    "high",
    "low",
    "close",
    "high_at",
    "low_at",
    "is_schedule_clipped",
    "calendar_verified",
]
ALIGNABLE_FIELDS = ("open", "high", "low", "close", "high_at", "low_at")
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class MarketContextError(ValueError):
    """Raised for invalid context configuration or input bars."""


@dataclass(frozen=True)
class ContextWindow:
    """Wall-clock window relative to a trading date, with explicit day offsets."""

    window_id: str
    display_name: str
    start_time: time
    start_day_offset: int
    end_time: time
    end_day_offset: int

    def bounds(self, trading_date: date, timezone: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Timezone-aware nominal (start, end) for ``trading_date``."""
        return (
            _localize(trading_date + timedelta(days=self.start_day_offset), self.start_time, timezone),
            _localize(trading_date + timedelta(days=self.end_day_offset), self.end_time, timezone),
        )


@dataclass(frozen=True)
class ContextDefinition:
    """A context: a window (or the full session) taken from a source session."""

    context_id: str
    window_id: str
    source_session: str
    definition_version: int
    window: ContextWindow | None  # None means the full source session

    @property
    def context_type(self) -> str:
        if self.source_session == SOURCE_TARGET:
            return TARGET_SESSION_WINDOW
        return PREVIOUS_SESSION if self.window is None else PREVIOUS_SESSION_WINDOW


@dataclass(frozen=True)
class MarketContextRegistry:
    """Validated generic context definitions, in stable order."""

    session_id: str
    windows: Mapping[str, ContextWindow]
    contexts: tuple[ContextDefinition, ...]
    source_path: str | None = None

    def get(self, context_id: str) -> ContextDefinition:
        for definition in self.contexts:
            if definition.context_id == context_id:
                return definition
        raise MarketContextError(f"Unknown context_id {context_id!r}")


PREVIOUS_DAY_DEFINITION = ContextDefinition(
    context_id=PREVIOUS_DAY_CONTEXT_ID,
    window_id=FULL_SESSION_WINDOW_ID,
    source_session=SOURCE_PREVIOUS_EXPECTED,
    definition_version=PREVIOUS_DAY_DEFINITION_VERSION,
    window=None,
)


def load_market_context_windows(
    session_spec: SessionSpec,
    path: str | Path = DEFAULT_CONTEXT_CONFIG,
) -> MarketContextRegistry:
    """Load and validate the generic registry; Previous Day is appended from code."""
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MarketContextError(f"Cannot read context config {config_path}: {error}") from error
    for key in ("session_id", "timezone", "timestamp_semantics", "windows", "contexts"):
        if key not in config:
            raise MarketContextError(f"Context config missing {key!r}")
    if config["session_id"] != session_spec.session_id:
        raise MarketContextError(
            f"Context config session_id {config['session_id']!r} != session spec {session_spec.session_id!r}"
        )
    if config["timezone"] != session_spec.timezone:
        raise MarketContextError("Context config timezone differs from the session spec")
    if config["timestamp_semantics"] != LABEL_BAR_END:
        raise MarketContextError("Context config must declare bar_end timestamp semantics")

    open_position = session_spec.open_day_offset * 1440 + _minutes(session_spec.open_time)
    close_position = _minutes(session_spec.close_time)
    windows: dict[str, ContextWindow] = {}
    for item in config["windows"]:
        window_id = _identifier(item.get("window_id"), "window_id")
        if window_id in windows or window_id == FULL_SESSION_WINDOW_ID:
            raise MarketContextError(f"Duplicate or reserved window_id {window_id!r}")
        window = ContextWindow(
            window_id=window_id,
            display_name=str(item.get("display_name", window_id)),
            start_time=_parse_time(item.get("start_et"), f"{window_id}.start_et"),
            start_day_offset=_offset(item.get("start_day_offset"), f"{window_id}.start_day_offset"),
            end_time=_parse_time(item.get("end_et"), f"{window_id}.end_et"),
            end_day_offset=_offset(item.get("end_day_offset"), f"{window_id}.end_day_offset"),
        )
        start = window.start_day_offset * 1440 + _minutes(window.start_time)
        end = window.end_day_offset * 1440 + _minutes(window.end_time)
        if not open_position <= start < end <= close_position:
            raise MarketContextError(f"Window {window_id!r} must lie inside the regular session and have start < end")
        windows[window_id] = window

    contexts: list[ContextDefinition] = []
    seen: set[str] = set()
    for item in config["contexts"]:
        context_id = _identifier(item.get("context_id"), "context_id")
        if context_id in seen or context_id == PREVIOUS_DAY_CONTEXT_ID:
            raise MarketContextError(f"Duplicate or reserved context_id {context_id!r}")
        window_id = item.get("window_id")
        if window_id not in windows:
            raise MarketContextError(f"Context {context_id!r} references unknown window {window_id!r}")
        source = item.get("source_session")
        if source not in (SOURCE_TARGET, SOURCE_PREVIOUS_EXPECTED):
            raise MarketContextError(f"Context {context_id!r} has invalid source_session {source!r}")
        version = item.get("definition_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise MarketContextError(f"Context {context_id!r} needs a positive integer definition_version")
        contexts.append(ContextDefinition(context_id, window_id, source, version, windows[window_id]))
        seen.add(context_id)
    contexts.append(PREVIOUS_DAY_DEFINITION)
    return MarketContextRegistry(
        session_id=config["session_id"],
        windows=MappingProxyType(windows),
        contexts=tuple(contexts),
        source_path=str(config_path),
    )


def build_market_context(
    bars: pd.DataFrame,
    session_spec: SessionSpec,
    *,
    instrument_id: str,
    registry: MarketContextRegistry | None = None,
    context_ids: Sequence[str] | None = None,
    coverage: tuple[Any, Any] | None = None,
    bar_interval: Any = ONE_MINUTE,
) -> pd.DataFrame:
    """Audit summary: one row per (expected open target trading date, context).

    ``coverage`` is the known (start, end) instant range of the source; by
    default it is the first bar's start through the last bar's end.
    """
    registry = registry if registry is not None else load_market_context_windows(session_spec)
    definitions = _select_definitions(registry, context_ids)
    instrument = load_instrument(instrument_id).instrument_id
    interval = pd.Timedelta(bar_interval)
    source = _prepare_bars(bars, session_spec, interval)
    coverage_start, coverage_end = _coverage(source, interval, coverage)
    by_date = _group_by_trading_date(source)
    regular_spec = with_calendar_overrides(session_spec, [])

    first, last = source["trading_date"].iloc[0], source["trading_date"].iloc[-1]
    rows: list[dict[str, Any]] = []
    for target in _expected_open_dates(first, last, session_spec):
        for definition in definitions:
            rows.append(summarize_context(
                definition, target, by_date, session_spec, regular_spec,
                instrument_id=instrument, coverage_start=coverage_start,
                coverage_end=coverage_end, interval=interval,
            ))
    frame = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    return frame.reset_index(drop=True)


def summarize_context(
    definition: ContextDefinition,
    target_trading_date: date,
    bars_by_date: Mapping[date, pd.DataFrame],
    session_spec: SessionSpec,
    regular_spec: SessionSpec,
    *,
    instrument_id: str,
    coverage_start: pd.Timestamp,
    coverage_end: pd.Timestamp,
    interval: pd.Timedelta = ONE_MINUTE,
) -> dict[str, Any]:
    """Evaluate one context for one target trading date (one summary row)."""
    if definition.source_session == SOURCE_TARGET:
        source_bounds = session_bounds(target_trading_date, session_spec)
        calendar_verified = source_bounds.calendar_verified
    else:
        source_bounds = previous_expected_session(target_trading_date, session_spec)
        calendar_verified = source_bounds.calendar_verified
    source_date = source_bounds.trading_date
    regular = session_bounds(source_date, regular_spec)
    if definition.window is None:
        nominal_start, nominal_end = regular.open, regular.close
    else:
        nominal_start, nominal_end = definition.window.bounds(source_date, session_spec.timezone)

    clipped_start = max(nominal_start, source_bounds.open)
    clipped_end = min(nominal_end, source_bounds.close)
    scheduled = clipped_end > clipped_start
    window_start, window_end = (clipped_start, clipped_end) if scheduled else (nominal_start, nominal_end)
    expected_count = int((clipped_end - clipped_start) // interval) if scheduled else 0

    session_bars = bars_by_date.get(source_date)
    if session_bars is not None and scheduled:
        labels = session_bars.index
        lo = labels.searchsorted(window_start, side="right")
        hi = labels.searchsorted(window_end, side="right")
        observed = session_bars.iloc[lo:hi]
    else:
        observed = None
    observed_count = 0 if observed is None else int(len(observed))
    contracts = [] if observed is None else sorted(observed["contract"].astype(str).unique())

    if window_start < coverage_start:
        reason = INSUFFICIENT_HISTORY
    elif window_end > coverage_end:
        reason = INSUFFICIENT_FUTURE_COVERAGE
    elif session_bars is None:
        reason = MISSING_EXPECTED_SESSION
    elif not scheduled:
        reason = NOT_SCHEDULED
    elif observed_count == 0:
        reason = NO_OBSERVATIONS
    elif len(contracts) > 1:
        reason = MIXED_CONTRACT
    elif observed_count < expected_count:
        reason = INCOMPLETE_WINDOW
    else:
        reason = None

    row = {
        "context_id": definition.context_id,
        "context_type": definition.context_type,
        "window_id": definition.window_id,
        "definition_version": definition.definition_version,
        "instrument_id": instrument_id,
        "target_trading_date": target_trading_date,
        "source_trading_date": source_date,
        "window_start": window_start,
        "window_end": window_end,
        "available_at": window_end,
        "contract": contracts[0] if len(contracts) == 1 else None,
        "contract_count": len(contracts),
        "observed_open": np.nan,
        "observed_high": np.nan,
        "observed_low": np.nan,
        "observed_close": np.nan,
        "high_at": pd.NaT,
        "low_at": pd.NaT,
        "expected_count": expected_count,
        "observed_count": observed_count,
        "missing_count": expected_count - observed_count,
        "is_complete": bool(expected_count > 0 and observed_count == expected_count),
        "is_schedule_clipped": bool((window_start, window_end) != (nominal_start, nominal_end) or not scheduled),
        "is_available": reason is None,
        "unavailable_reason": reason,
        "calendar_verified": bool(calendar_verified),
    }
    if observed_count:
        highs, lows = observed["high"], observed["low"]
        row.update(
            observed_open=float(observed["open"].iloc[0]),
            observed_high=float(highs.max()),
            observed_low=float(lows.min()),
            observed_close=float(observed["close"].iloc[-1]),
            high_at=highs.idxmax(),  # first occurrence of the extreme
            low_at=lows.idxmin(),
        )
    return row


def valid_context_levels(context: pd.DataFrame) -> pd.DataFrame:
    """Only available contexts, with plain level columns. Unavailable rows never appear."""
    missing = [column for column in SUMMARY_COLUMNS if column not in context.columns]
    if missing:
        raise MarketContextError(f"Not a market-context summary; missing columns {missing}")
    valid = context.loc[context["is_available"].astype(bool)].copy()
    valid = valid.rename(columns={
        "observed_open": "open", "observed_high": "high",
        "observed_low": "low", "observed_close": "close",
    })
    return valid[VALID_LEVEL_COLUMNS].reset_index(drop=True)


def align_market_context(
    bars: pd.DataFrame,
    context: pd.DataFrame,
    session_spec: SessionSpec,
    *,
    context_ids: Sequence[str] | None = None,
    fields: Iterable[str] = ("high", "low", "close"),
    bar_interval: Any = ONE_MINUTE,
) -> pd.DataFrame:
    """Per-bar causal view of valid context for each bar's own trading date.

    Columns per context: ``<context_id>_<field>`` and ``<context_id>_status``
    (``AVAILABLE``, ``PENDING``, ``UNAVAILABLE_CONTEXT``, ``CONTRACT_MISMATCH``).
    Values are present only when the status is ``AVAILABLE``.
    """
    fields = tuple(fields)
    unknown = [field for field in fields if field not in ALIGNABLE_FIELDS]
    if unknown:
        raise MarketContextError(f"Unknown alignment fields {unknown}; use {ALIGNABLE_FIELDS}")
    interval = pd.Timedelta(bar_interval)
    source = _prepare_bars(bars, session_spec, interval)
    valid = valid_context_levels(context)
    ids = list(context_ids) if context_ids is not None else list(dict.fromkeys(context["context_id"]))
    unknown_ids = sorted(set(ids) - set(context["context_id"]))
    if unknown_ids:
        raise MarketContextError(f"Context ids not present in the summary: {unknown_ids}")

    bar_start = source.index - interval
    output = pd.DataFrame(index=source.index)
    for context_id in ids:
        levels = valid.loc[valid["context_id"] == context_id]
        if levels["target_trading_date"].duplicated().any():
            raise MarketContextError(f"Duplicate valid {context_id} rows for one target trading date")
        lookup = levels.set_index("target_trading_date")
        dates = source["trading_date"]
        has_valid = dates.isin(lookup.index).to_numpy()
        available_at = dates.map(lookup["available_at"])
        pending = has_valid & np.asarray(bar_start < pd.DatetimeIndex(available_at))
        mismatch = has_valid & (source["contract"].astype(str) != dates.map(lookup["contract"]).astype(str)).to_numpy()
        status = np.select(
            [~has_valid, pending, mismatch],
            [ALIGN_UNAVAILABLE_CONTEXT, ALIGN_PENDING, ALIGN_CONTRACT_MISMATCH],
            default=ALIGN_AVAILABLE,
        )
        visible = status == ALIGN_AVAILABLE
        for field in fields:
            values = dates.map(lookup[field])
            output[f"{context_id}_{field}"] = values.where(visible)
        output[f"{context_id}_status"] = status
    return output


def _select_definitions(
    registry: MarketContextRegistry,
    context_ids: Sequence[str] | None,
) -> list[ContextDefinition]:
    if context_ids is None:
        return list(registry.contexts)
    if len(set(context_ids)) != len(context_ids):
        raise MarketContextError("context_ids must be unique")
    return [registry.get(context_id) for context_id in context_ids]


def _prepare_bars(bars: pd.DataFrame, session_spec: SessionSpec, interval: pd.Timedelta) -> pd.DataFrame:
    if not isinstance(bars, pd.DataFrame):
        raise MarketContextError("bars must be a pandas DataFrame")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise MarketContextError("bars must have a timezone-aware DatetimeIndex of bar-end labels")
    if bars.empty:
        raise MarketContextError("bars is empty")
    required = ["open", "high", "low", "close", "contract"]
    missing = [column for column in required if column not in bars.columns]
    if missing:
        raise MarketContextError(f"bars missing required columns: {missing}")
    if bars.index.has_duplicates:
        raise MarketContextError("bars contain duplicate timestamps")
    if interval <= pd.Timedelta(0) or pd.Timedelta(days=1) % interval != pd.Timedelta(0):
        raise MarketContextError("bar_interval must be positive and divide one day")
    source = bars.sort_index()
    if source[required].isna().any().any():
        raise MarketContextError("bars contain missing OHLC or contract values")
    local = source.index.tz_convert(session_spec.timezone)
    if ((local - local.normalize()) % interval != pd.Timedelta(0)).any():
        raise MarketContextError("bar labels are not aligned to the bar interval")
    trading_dates = assign_trading_dates(source.index, session_spec, label=LABEL_BAR_END, bar_interval=interval)
    source = source.copy()
    source["trading_date"] = trading_dates.to_numpy()
    if "session_date" in source.columns:
        declared = pd.to_datetime(source["session_date"]).dt.date.to_numpy()
        mismatch = declared != source["trading_date"].to_numpy()
        if mismatch.any():
            raise MarketContextError(f"session_date disagrees with the session model at {source.index[mismatch.argmax()]}")
    return source


def _coverage(
    source: pd.DataFrame,
    interval: pd.Timedelta,
    coverage: tuple[Any, Any] | None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    observed = (source.index[0] - interval, source.index[-1])
    if coverage is None:
        return observed
    start, end = (pd.Timestamp(value) for value in coverage)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise MarketContextError("coverage must be timezone-aware (start, end) with start < end")
    if start > observed[0] or end < observed[1]:
        raise MarketContextError("declared coverage must contain every source bar")
    return start, end


def _group_by_trading_date(source: pd.DataFrame) -> dict[date, pd.DataFrame]:
    return {day: frame for day, frame in source.groupby("trading_date", sort=True)}


def _expected_open_dates(first: date, last: date, session_spec: SessionSpec) -> list[date]:
    days = []
    current = first
    while current <= last:
        if session_bounds(current, session_spec).is_open:
            days.append(current)
        current += timedelta(days=1)
    return days


def _localize(day: date, clock: time, timezone: str) -> pd.Timestamp:
    naive = pd.Timestamp(datetime.combine(day, clock))
    try:
        return naive.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    except Exception as error:  # pandas raises tz-library-specific types
        raise MarketContextError(f"{naive} is not a valid wall-clock time in {timezone}") from error


def _minutes(clock: time) -> int:
    return clock.hour * 60 + clock.minute


def _parse_time(value: Any, name: str) -> time:
    try:
        parsed = time.fromisoformat(str(value))
    except ValueError as error:
        raise MarketContextError(f"Invalid time for {name}: {value!r}") from error
    if parsed.second or parsed.microsecond:
        raise MarketContextError(f"{name} must be a whole minute")
    return parsed


def _offset(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarketContextError(f"{name} must be an integer day offset")
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise MarketContextError(f"Invalid {name}: {value!r}")
    return value
