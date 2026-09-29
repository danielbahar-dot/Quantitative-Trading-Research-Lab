"""Generic exchange session model and trading-date assignment.

This module is the authoritative source for generic futures session facts:
timezone, regular session bounds, maintenance break, trading-date ownership,
and explicit calendar overrides (closures and shortened sessions).  It holds
no strategy or market-context windows.

All rules are evaluated on timezone-aware instants in the session timezone,
so DST is handled by the timezone database rather than fixed UTC offsets.
Bar-labelled data is evaluated on its bar-start instant: pass
``label="bar_end"`` with the bar interval, and the whole bar must end no later
than the session close.

The regular session for ``trading_date`` D is ``[18:00 ET on D-1, 17:00 ET on
D)``.  Overrides may only close a session or shorten it inside those bounds.
A date is ``calendar_verified`` only when it has an explicit override or lies
inside the declared override coverage; outside coverage an absent session
cannot be classified as a legitimate exchange closure.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping
import json

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SESSION_CONFIG = PROJECT_ROOT / "config" / "sessions" / "cme_globex_et.json"

# Session kinds returned by ``session_bounds``.
REGULAR = "REGULAR"
MODIFIED = "MODIFIED"
CLOSED = "CLOSED"
NON_TRADING_DAY = "NON_TRADING_DAY"

# Timestamp statuses returned by ``session_status``.
IN_SESSION = "IN_SESSION"
MAINTENANCE_BREAK = "MAINTENANCE_BREAK"
EXCHANGE_CLOSED = "EXCHANGE_CLOSED"

LABEL_INSTANT = "instant"
LABEL_BAR_END = "bar_end"

OVERRIDE_KINDS = (CLOSED, MODIFIED)
MAX_SESSION_SEARCH_DAYS = 14
WEEKDAY_CODES = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
OVERRIDE_FIELDS = {"trading_date", "kind", "open_et", "open_day_offset", "close_et", "reason"}


class SessionError(ValueError):
    """Raised for invalid session configuration or out-of-session timestamps."""


@dataclass(frozen=True)
class SessionOverride:
    """Explicit non-regular session for one trading date."""

    trading_date: date
    kind: str
    open_time: time | None = None
    open_day_offset: int | None = None
    close_time: time | None = None
    reason: str = ""


@dataclass(frozen=True)
class SessionSpec:
    """Regular weekly session definition plus explicit calendar overrides."""

    session_id: str
    timezone: str
    open_time: time
    open_day_offset: int
    close_time: time
    break_start: time
    break_end: time
    trading_weekdays: frozenset[int]
    overrides: Mapping[date, SessionOverride] = field(
        default_factory=lambda: MappingProxyType({})
    )
    calendar_coverage: tuple[date, date] | None = None
    source_path: str | None = None


@dataclass(frozen=True)
class SessionBounds:
    """Resolved session for one trading date; ``open``/``close`` are tz-aware."""

    trading_date: date
    kind: str
    open: pd.Timestamp | None
    close: pd.Timestamp | None
    calendar_verified: bool
    reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.kind in (REGULAR, MODIFIED)


def load_session_spec(
    path: str | Path = DEFAULT_SESSION_CONFIG,
    *,
    overrides_path: str | Path | None = None,
) -> SessionSpec:
    """Load and validate a session configuration and its override calendar."""
    config_path = Path(path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key in ("session_id", "timezone", "session_open", "session_close",
                "maintenance_break", "trading_weekdays"):
        if key not in config:
            raise SessionError(f"Session config missing required field: {key}")

    timezone = str(config["timezone"])
    _validate_timezone(timezone)
    open_time = _parse_time(config["session_open"]["time_et"], "session_open.time_et")
    open_day_offset = int(config["session_open"]["day_offset"])
    close_time = _parse_time(config["session_close"]["time_et"], "session_close.time_et")
    close_day_offset = int(config["session_close"].get("day_offset", 0))
    break_start = _parse_time(config["maintenance_break"]["start_et"], "maintenance_break.start_et")
    break_end = _parse_time(config["maintenance_break"]["end_et"], "maintenance_break.end_et")

    # The model supports exactly one regular form: an evening open on the prior
    # calendar day, an afternoon close, and a break covering the gap.
    if open_day_offset != -1 or close_day_offset != 0:
        raise SessionError("Only a prior-day open (day_offset -1) and same-day close are supported")
    if not close_time < open_time:
        raise SessionError("Session close must be earlier in the day than the session open")
    if break_start != close_time or break_end != open_time:
        raise SessionError("Maintenance break must span exactly [session close, session open)")

    codes = config["trading_weekdays"]
    unknown = sorted(set(codes) - set(WEEKDAY_CODES))
    if unknown or not codes:
        raise SessionError(f"Invalid trading_weekdays: {codes}")

    spec = SessionSpec(
        session_id=str(config["session_id"]),
        timezone=timezone,
        open_time=open_time,
        open_day_offset=open_day_offset,
        close_time=close_time,
        break_start=break_start,
        break_end=break_end,
        trading_weekdays=frozenset(WEEKDAY_CODES[code] for code in codes),
        source_path=str(config_path),
    )

    calendar_file = overrides_path
    if calendar_file is None and config.get("calendar", {}).get("overrides_file"):
        calendar_file = config_path.parent / config["calendar"]["overrides_file"]
    if calendar_file is None:
        return spec
    calendar_path = Path(calendar_file)
    if not calendar_path.is_file():
        raise SessionError(f"Declared override calendar not found: {calendar_path}")
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    if calendar.get("session_id") != spec.session_id:
        raise SessionError("Override calendar session_id does not match the session config")
    coverage = calendar.get("coverage") or {}
    return with_calendar_overrides(
        spec,
        calendar.get("overrides", []),
        coverage_start=coverage.get("start"),
        coverage_end=coverage.get("end"),
    )


def with_calendar_overrides(
    spec: SessionSpec,
    overrides: Iterable[SessionOverride | Mapping[str, Any]],
    *,
    coverage_start: date | str | None = None,
    coverage_end: date | str | None = None,
) -> SessionSpec:
    """Return ``spec`` with its override calendar replaced (not merged)."""
    if (coverage_start is None) != (coverage_end is None):
        raise SessionError("Calendar coverage requires both start and end, or neither")
    coverage = None
    if coverage_start is not None:
        coverage = (_as_date(coverage_start), _as_date(coverage_end))
        if coverage[0] > coverage[1]:
            raise SessionError("Calendar coverage start must not be after its end")

    parsed: dict[date, SessionOverride] = {}
    for item in overrides:
        override = item if isinstance(item, SessionOverride) else _parse_override(item)
        if override.trading_date in parsed:
            raise SessionError(f"Duplicate session override for {override.trading_date}")
        _validate_override(override, spec, coverage)
        parsed[override.trading_date] = override
    return replace(spec, overrides=MappingProxyType(parsed), calendar_coverage=coverage)


def get_session_override(trading_date: date | str, spec: SessionSpec) -> SessionOverride | None:
    """Return the explicit override for ``trading_date``, if any."""
    return spec.overrides.get(_as_date(trading_date))


def assign_trading_date(
    timestamp: Any,
    spec: SessionSpec,
    *,
    label: str = LABEL_INSTANT,
    bar_interval: Any = None,
) -> date:
    """Return the trading date owning ``timestamp`` under the regular convention.

    Raises ``SessionError`` for naive timestamps, maintenance-break instants,
    instants mapping to a non-trading weekday, and bars ending after the
    regular session close.  Calendar overrides do not change ownership; use
    ``session_status`` to learn whether the exchange was actually open.
    """
    start, end = _resolve_instant(timestamp, spec, label, bar_interval)
    if _in_break(start, spec):
        raise SessionError(f"{timestamp} falls in the maintenance break")
    trading_date = _clock_trading_date(start, spec)
    if trading_date.weekday() not in spec.trading_weekdays:
        raise SessionError(f"{timestamp} maps to non-trading day {trading_date}")
    if end is not None and end > _wall(trading_date, spec.close_time, 0, spec.timezone):
        raise SessionError(f"Bar ending {timestamp} extends beyond the session close")
    return trading_date


def assign_trading_dates(
    timestamps: Any,
    spec: SessionSpec,
    *,
    label: str = LABEL_INSTANT,
    bar_interval: Any = None,
) -> pd.Series:
    """Vectorized ``assign_trading_date`` for a sequence of timestamps.

    Returns a Series of ``date`` objects indexed by the input timestamps and
    applies exactly the same rules, raising ``SessionError`` for the first
    invalid timestamp instead of skipping it.
    """
    index = pd.DatetimeIndex(timestamps)
    if index.tz is None:
        raise SessionError("Timestamps must be timezone-aware")
    if index.hasnans:
        raise SessionError("Timestamps contain missing values")
    local = index.tz_convert(spec.timezone)
    if label == LABEL_INSTANT:
        if bar_interval is not None:
            raise SessionError("bar_interval is only valid with label='bar_end'")
        starts, ends = local, None
    elif label == LABEL_BAR_END:
        if bar_interval is None:
            raise SessionError("label='bar_end' requires bar_interval")
        interval = pd.Timedelta(bar_interval)
        if interval <= pd.Timedelta(0):
            raise SessionError("bar_interval must be positive")
        starts, ends = local - interval, local
    else:
        raise SessionError(f"Unknown timestamp label: {label}")

    wall = starts.tz_localize(None)
    clock = wall - wall.normalize()
    in_break = (clock >= _clock_offset(spec.break_start)) & (clock < _clock_offset(spec.break_end))
    if in_break.any():
        raise SessionError(f"{index[in_break.argmax()]} falls in the maintenance break")
    after_open = clock >= _clock_offset(spec.open_time)
    days = wall.normalize() + pd.to_timedelta(after_open.astype("int64"), unit="D")
    non_trading = ~days.weekday.isin(sorted(spec.trading_weekdays))
    if non_trading.any():
        position = non_trading.argmax()
        raise SessionError(f"{index[position]} maps to non-trading day {days[position].date()}")
    if ends is not None:
        closes = (days + _clock_offset(spec.close_time)).tz_localize(
            spec.timezone, ambiguous="raise", nonexistent="raise"
        )
        beyond = ends > closes
        if beyond.any():
            raise SessionError(f"Bar ending {index[beyond.argmax()]} extends beyond the session close")
    return pd.Series(days.date, index=index, name="trading_date")


def session_bounds(trading_date: date | str, spec: SessionSpec) -> SessionBounds:
    """Resolve the session for ``trading_date`` with overrides applied."""
    day = _as_date(trading_date)
    if day.weekday() not in spec.trading_weekdays:
        return SessionBounds(day, NON_TRADING_DAY, None, None, True, "Outside the regular weekly schedule")
    override = spec.overrides.get(day)
    if override is not None and override.kind == CLOSED:
        return SessionBounds(day, CLOSED, None, None, True, override.reason)
    open_ts, close_ts = _bounds_for(day, spec, override)
    return SessionBounds(
        trading_date=day,
        kind=MODIFIED if override is not None else REGULAR,
        open=open_ts,
        close=close_ts,
        calendar_verified=override is not None or _in_coverage(day, spec),
        reason=override.reason if override is not None else "",
    )


def session_status(
    timestamp: Any,
    spec: SessionSpec,
    *,
    label: str = LABEL_INSTANT,
    bar_interval: Any = None,
) -> str:
    """Classify a timestamp as IN_SESSION, MAINTENANCE_BREAK, NON_TRADING_DAY or EXCHANGE_CLOSED."""
    start, end = _resolve_instant(timestamp, spec, label, bar_interval)
    if _in_break(start, spec):
        day = start.date()
        between_sessions = (
            day.weekday() in spec.trading_weekdays
            and (day + timedelta(days=1)).weekday() in spec.trading_weekdays
        )
        return MAINTENANCE_BREAK if between_sessions else NON_TRADING_DAY
    trading_date = _clock_trading_date(start, spec)
    if trading_date.weekday() not in spec.trading_weekdays:
        return NON_TRADING_DAY
    bounds = session_bounds(trading_date, spec)
    if not bounds.is_open or not (bounds.open <= start < bounds.close):
        return EXCHANGE_CLOSED
    if end is not None and end > bounds.close:
        return EXCHANGE_CLOSED
    return IN_SESSION


def is_in_session(
    timestamp: Any,
    spec: SessionSpec,
    *,
    label: str = LABEL_INSTANT,
    bar_interval: Any = None,
) -> bool:
    """True when the exchange session (overrides applied) contains ``timestamp``."""
    return session_status(timestamp, spec, label=label, bar_interval=bar_interval) == IN_SESSION


def is_maintenance_break(
    timestamp: Any,
    spec: SessionSpec,
    *,
    label: str = LABEL_INSTANT,
    bar_interval: Any = None,
) -> bool:
    """True only for a between-session break (Mon–Thu 17:00–18:00 ET).

    Friday from 17:00 and Sunday before 18:00 are the weekend closure
    (``NON_TRADING_DAY``), not a maintenance break.
    """
    status = session_status(timestamp, spec, label=label, bar_interval=bar_interval)
    return status == MAINTENANCE_BREAK


def previous_expected_session(trading_date: date | str, spec: SessionSpec) -> SessionBounds:
    """Return the nearest earlier open session per the schedule and overrides.

    ``calendar_verified`` is True only if every date examined was verified, so
    an unverified result means an intervening closure may be unknown.
    """
    return _search_expected_session(_as_date(trading_date), spec, step=-1)


def next_expected_session(trading_date: date | str, spec: SessionSpec) -> SessionBounds:
    """Return the nearest later open session per the schedule and overrides."""
    return _search_expected_session(_as_date(trading_date), spec, step=1)


def _search_expected_session(day: date, spec: SessionSpec, *, step: int) -> SessionBounds:
    verified = True
    for offset in range(1, MAX_SESSION_SEARCH_DAYS + 1):
        bounds = session_bounds(day + timedelta(days=step * offset), spec)
        verified = verified and bounds.calendar_verified
        if bounds.is_open:
            return replace(bounds, calendar_verified=verified)
    raise SessionError(f"No open session within {MAX_SESSION_SEARCH_DAYS} days of {day}")


def _resolve_instant(
    timestamp: Any,
    spec: SessionSpec,
    label: str,
    bar_interval: Any,
) -> tuple[pd.Timestamp, pd.Timestamp | None]:
    """Return (evaluation instant, bar end or None) in the session timezone."""
    if isinstance(timestamp, date) and not isinstance(timestamp, datetime):
        raise SessionError("Expected a timestamp, not a date")
    stamp = pd.Timestamp(timestamp)
    if pd.isna(stamp):
        raise SessionError("Timestamp is missing")
    if stamp.tzinfo is None:
        raise SessionError(f"Timestamp must be timezone-aware: {timestamp}")
    local = stamp.tz_convert(spec.timezone)
    if label == LABEL_INSTANT:
        if bar_interval is not None:
            raise SessionError("bar_interval is only valid with label='bar_end'")
        return local, None
    if label == LABEL_BAR_END:
        if bar_interval is None:
            raise SessionError("label='bar_end' requires bar_interval")
        interval = pd.Timedelta(bar_interval)
        if interval <= pd.Timedelta(0):
            raise SessionError("bar_interval must be positive")
        return local - interval, local
    raise SessionError(f"Unknown timestamp label: {label}")


def _clock_offset(clock: time) -> pd.Timedelta:
    return pd.Timedelta(
        hours=clock.hour, minutes=clock.minute, seconds=clock.second, microseconds=clock.microsecond
    )


def _in_break(local: pd.Timestamp, spec: SessionSpec) -> bool:
    return spec.break_start <= local.time() < spec.break_end


def _clock_trading_date(local: pd.Timestamp, spec: SessionSpec) -> date:
    day = local.date()
    return day + timedelta(days=1) if local.time() >= spec.open_time else day


def _bounds_for(
    day: date,
    spec: SessionSpec,
    override: SessionOverride | None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    open_time = spec.open_time
    open_offset = spec.open_day_offset
    close_time = spec.close_time
    if override is not None:
        if override.open_time is not None:
            open_time = override.open_time
        if override.open_day_offset is not None:
            open_offset = override.open_day_offset
        if override.close_time is not None:
            close_time = override.close_time
    return (
        _wall(day, open_time, open_offset, spec.timezone),
        _wall(day, close_time, 0, spec.timezone),
    )


def _wall(day: date, clock: time, day_offset: int, timezone: str) -> pd.Timestamp:
    naive = pd.Timestamp(datetime.combine(day + timedelta(days=day_offset), clock))
    try:
        return naive.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    except Exception as error:  # pandas raises tz-library-specific types
        raise SessionError(f"{naive} is not a valid wall-clock time in {timezone}") from error


def _in_coverage(day: date, spec: SessionSpec) -> bool:
    coverage = spec.calendar_coverage
    return coverage is not None and coverage[0] <= day <= coverage[1]


def _parse_override(item: Mapping[str, Any]) -> SessionOverride:
    unknown = sorted(set(item) - OVERRIDE_FIELDS)
    if unknown:
        raise SessionError(f"Unknown session override fields: {unknown}")
    if "trading_date" not in item or "kind" not in item:
        raise SessionError("Session override requires trading_date and kind")
    open_et = item.get("open_et")
    close_et = item.get("close_et")
    offset = item.get("open_day_offset")
    return SessionOverride(
        trading_date=_as_date(item["trading_date"]),
        kind=str(item["kind"]),
        open_time=_parse_time(open_et, "open_et") if open_et is not None else None,
        open_day_offset=int(offset) if offset is not None else None,
        close_time=_parse_time(close_et, "close_et") if close_et is not None else None,
        reason=str(item.get("reason", "")),
    )


def _validate_override(
    override: SessionOverride,
    spec: SessionSpec,
    coverage: tuple[date, date] | None,
) -> None:
    day = override.trading_date
    if override.kind not in OVERRIDE_KINDS:
        raise SessionError(f"Unknown override kind for {day}: {override.kind}")
    if day.weekday() not in spec.trading_weekdays:
        raise SessionError(f"Override {day} is not a regular trading weekday")
    if coverage is not None and not coverage[0] <= day <= coverage[1]:
        raise SessionError(f"Override {day} lies outside the declared calendar coverage")
    times = (override.open_time, override.open_day_offset, override.close_time)
    if override.kind == CLOSED:
        if any(value is not None for value in times):
            raise SessionError(f"CLOSED override {day} must not define session times")
        return
    if all(value is None for value in times):
        raise SessionError(f"MODIFIED override {day} must change the open or close")
    regular_open, regular_close = _bounds_for(day, spec, None)
    open_ts, close_ts = _bounds_for(day, spec, override)
    if not regular_open <= open_ts < close_ts <= regular_close:
        raise SessionError(f"MODIFIED override {day} must shorten the session within regular bounds")
    if (open_ts, close_ts) == (regular_open, regular_close):
        raise SessionError(f"MODIFIED override {day} equals the regular session")


def _parse_time(value: Any, name: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError as error:
        raise SessionError(f"Invalid time for {name}: {value}") from error


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        raise SessionError("Expected a date, not a timestamp")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise SessionError(f"Invalid date: {value}") from error
    raise SessionError(f"Expected a date or ISO date string, got {type(value).__name__}")


def _validate_timezone(timezone: str) -> None:
    try:
        pd.Timestamp("2000-01-03 12:00").tz_localize(timezone)
    except Exception as error:
        raise SessionError(f"Unknown timezone: {timezone}") from error
