"""Generic deterministic timeframe builder (on demand; no persistence).

Validated 1-minute bars are the canonical source.  Derived bars are computed
from them and are never authoritative.  Aggregation follows the generic
session model in ``src/data/sessions.py`` (D-111, D-116):

- Buckets are anchored at the **regular** session open of each trading date
  (18:00 ET on the prior calendar day), never at the first observed record.
  A ``minutes`` timeframe uses buckets ``[open + k*L, open + (k+1)*L)``; a
  session timeframe (``minutes=None``) uses one bucket per trading date.
- Buckets are clipped to the actual session bounds (calendar overrides
  applied), so the 4H bucket starting 14:00 ends at 17:00 and an early close
  shortens its bucket.  Clipped buckets are flagged ``is_session_truncated``.
- A source bar belongs to the bucket containing its bar-start instant
  (bar-end label minus the source interval).
- OHLCV: first open, max high, min low, last close, summed volume.
- Buckets without source bars produce no row; bars are never synthesized.
- Buckets missing some source bars are emitted with ``is_complete=False``
  and expected/observed counts; downstream code decides what to consume.
- A bucket mixing contracts raises ``TimeframeError`` (roll handling is
  deferred, D-117).

Timestamp semantics of derived bars: the index ``timestamp_et`` equals
``bar_end`` (bar-end labelling, as in the source), and ``available_at`` equals
``bar_end`` even when the bar is incomplete.  A consumer at time ``t`` may use
a derived bar only if ``available_at <= t``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

import pandas as pd

from src.data.sessions import (
    SessionSpec,
    assign_trading_dates,
    session_bounds,
    with_calendar_overrides,
    LABEL_BAR_END,
)

# Bump whenever build_timeframe() output semantics change; persisted derived
# data carrying an older version is treated as stale.
TIMEFRAME_BUILDER_VERSION = 1
DEFAULT_SOURCE_INTERVAL = pd.Timedelta(minutes=1)
PRICE_COLUMNS = ("open", "high", "low", "close")
REQUIRED_COLUMNS = (*PRICE_COLUMNS, "volume", "contract")
OUTPUT_COLUMNS = [
    "timeframe",
    "trading_date",
    "contract",
    "bar_start",
    "bar_end",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "expected_bars",
    "observed_bars",
    "is_complete",
    "is_session_truncated",
]
# Expected-schedule output: geometry only, no observation-dependent columns.
SCHEDULE_COLUMNS = [
    "timeframe",
    "trading_date",
    "bar_start",
    "bar_end",
    "available_at",
    "expected_bars",
    "is_session_truncated",
]


class TimeframeError(ValueError):
    """Raised for invalid timeframe definitions or source bars."""


@dataclass(frozen=True)
class TimeframeSpec:
    """A derived timeframe: fixed ``minutes`` buckets, or one bar per session."""

    timeframe_id: str
    minutes: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.timeframe_id, str) or not self.timeframe_id.strip():
            raise TimeframeError("timeframe_id must be a non-empty string")
        if self.minutes is not None and (
            isinstance(self.minutes, bool) or not isinstance(self.minutes, int) or self.minutes <= 0
        ):
            raise TimeframeError(f"minutes must be a positive integer or None, got {self.minutes!r}")


STANDARD_TIMEFRAMES = MappingProxyType({
    "5m": TimeframeSpec("5m", 5),
    "15m": TimeframeSpec("15m", 15),
    "1H": TimeframeSpec("1H", 60),
    "4H": TimeframeSpec("4H", 240),
    "1D": TimeframeSpec("1D", None),
})


def get_timeframe(timeframe: TimeframeSpec | str) -> TimeframeSpec:
    """Return a ``TimeframeSpec`` for a spec or a standard timeframe ID."""
    if isinstance(timeframe, TimeframeSpec):
        return timeframe
    if isinstance(timeframe, str) and timeframe in STANDARD_TIMEFRAMES:
        return STANDARD_TIMEFRAMES[timeframe]
    raise TimeframeError(
        f"Unknown timeframe {timeframe!r}; use one of {list(STANDARD_TIMEFRAMES)} or a TimeframeSpec"
    )


def build_timeframe(
    bars: pd.DataFrame,
    timeframe: TimeframeSpec | str,
    session_spec: SessionSpec,
    *,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> pd.DataFrame:
    """Aggregate bar-end-labelled source bars into ``timeframe`` bars.

    ``bars`` must have a timezone-aware ``DatetimeIndex`` of bar-end labels
    (e.g. ``frame.set_index("timestamp_et")``) and the columns open, high,
    low, close, volume and contract.  An optional ``session_date`` column is
    checked against the session model's trading date.
    """
    spec = get_timeframe(timeframe)
    interval, bucket_length = _interval_and_bucket_length(spec, source_interval)

    source = _validate_source(bars)
    labels = source.index
    trading_dates = assign_trading_dates(
        labels, session_spec, label=LABEL_BAR_END, bar_interval=interval
    ).to_numpy()
    if "session_date" in source.columns:
        declared = pd.to_datetime(source["session_date"]).dt.date.to_numpy()
        mismatch = declared != trading_dates
        if mismatch.any():
            position = mismatch.argmax()
            raise TimeframeError(
                f"session_date {declared[position]} at {labels[position]} disagrees with "
                f"trading date {trading_dates[position]} from the session model"
            )

    anchors, opens, closes, nominal = _session_frames(sorted(set(trading_dates)), session_spec)
    work = pd.DataFrame({
        "trading_date": trading_dates,
        "source_start": labels - interval,
        "source_end": labels,
        **{column: source[column].to_numpy() for column in REQUIRED_COLUMNS},
    })
    work["anchor"] = work["trading_date"].map(anchors)
    work["session_open"] = work["trading_date"].map(opens)
    work["session_close"] = work["trading_date"].map(closes)

    outside = (work["source_start"] < work["session_open"]) | (work["source_end"] > work["session_close"])
    if outside.any():
        position = outside.to_numpy().argmax()
        raise TimeframeError(
            f"Source bar ending {labels[position]} lies outside the session bounds of "
            f"{trading_dates[position]}"
        )
    offset = work["source_start"] - work["anchor"]
    if (offset % interval != pd.Timedelta(0)).any():
        raise TimeframeError("Source bars are not aligned to the session anchor and source interval")

    if bucket_length is None:
        work["bucket"] = 0
        work["nominal_length"] = work["trading_date"].map(nominal)
    else:
        work["bucket"] = (offset // bucket_length).astype("int64")
        work["nominal_length"] = bucket_length
    work["bar_start"], work["bar_end"] = _bucket_geometry(
        work["anchor"], work["bucket"], work["nominal_length"], bucket_length,
        work["session_open"], work["session_close"],
    )

    grouped = work.groupby(["trading_date", "bucket"], sort=True)
    output = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        contract=("contract", "first"),
        contract_count=("contract", "nunique"),
        bar_start=("bar_start", "first"),
        bar_end=("bar_end", "first"),
        nominal_length=("nominal_length", "first"),
        observed_bars=("open", "size"),
    ).reset_index()

    mixed = output["contract_count"] > 1
    if mixed.any():
        row = output.loc[mixed.idxmax()]
        raise TimeframeError(
            f"{spec.timeframe_id} bar {row['bar_start']} to {row['bar_end']} mixes contracts; "
            "contract-roll handling is not implemented"
        )

    output["expected_bars"], output["is_session_truncated"] = _bucket_metrics(
        output["bar_start"], output["bar_end"], output["nominal_length"], interval
    )
    output["observed_bars"] = output["observed_bars"].astype("int64")
    if (output["observed_bars"] > output["expected_bars"]).any():
        raise TimeframeError("Internal error: more source bars than expected in a bucket")
    output["is_complete"] = output["observed_bars"] == output["expected_bars"]
    output["available_at"] = output["bar_end"]
    output["timeframe"] = spec.timeframe_id
    output = output[OUTPUT_COLUMNS]
    output.index = pd.DatetimeIndex(output["bar_end"], name="timestamp_et")
    return output


def _validate_source(bars: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(bars, pd.DataFrame):
        raise TimeframeError("bars must be a pandas DataFrame")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise TimeframeError(
            "bars must have a timezone-aware DatetimeIndex of bar-end labels "
            "(e.g. set_index('timestamp_et'))"
        )
    if bars.empty:
        raise TimeframeError("bars is empty")
    missing = [column for column in REQUIRED_COLUMNS if column not in bars.columns]
    if missing:
        raise TimeframeError(f"bars missing required columns: {missing}")
    if bars.index.hasnans:
        raise TimeframeError("bars index contains missing timestamps")
    if bars.index.has_duplicates:
        raise TimeframeError(f"Duplicate bar timestamps: {bars.index[bars.index.duplicated()][0]}")
    source = bars.sort_index()
    if source[list(REQUIRED_COLUMNS)].isna().any().any():
        raise TimeframeError("bars contain missing OHLCV or contract values")
    if (source["contract"].astype(str).str.strip() == "").any():
        raise TimeframeError("bars contain empty contract identifiers")
    high, low = source["high"], source["low"]
    body_high = source[["open", "close"]].max(axis=1)
    body_low = source[["open", "close"]].min(axis=1)
    if ((high < body_high) | (low > body_low)).any():
        raise TimeframeError("bars contain inconsistent OHLC values (high/low do not bound open/close)")
    return source


def expected_timeframe_schedule(
    trading_dates: Any,
    timeframe: TimeframeSpec | str,
    session_spec: SessionSpec,
    *,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> pd.DataFrame:
    """Expected bucket geometry of ``timeframe`` for ``trading_dates`` (no source data).

    Uses exactly the bucket geometry of :func:`build_timeframe` (shared
    helpers): buckets anchored at the regular session open, clipped to the
    actual session bounds with verified calendar overrides applied, and
    flagged ``is_session_truncated`` when clipped.  ``available_at`` equals
    ``bar_end`` and ``expected_bars`` is ``(bar_end - bar_start) //
    source_interval``.

    Unlike ``build_timeframe``, every expected bucket is listed, including
    buckets that have no source observations (which ``build_timeframe``
    never synthesizes).  Dates that are not open sessions under the session
    model (verified ``CLOSED`` overrides, non-trading days) produce no rows;
    a weekday merely missing from source data is still an expected session.
    Sessions spanning a DST transition raise, as in ``build_timeframe``.

    ``trading_dates`` is one date (``date`` / ISO string / ``Timestamp``) or an
    iterable of them; duplicates are ignored.  Rows are ordered by
    ``trading_date`` then ``bar_start``; the index is the ``bar_end``
    ``DatetimeIndex`` named ``timestamp_et``, as in ``build_timeframe``.
    """
    spec = get_timeframe(timeframe)
    interval, bucket_length = _interval_and_bucket_length(spec, source_interval)
    days = _schedule_dates(trading_dates)
    anchors, opens, closes, nominal = _session_frames(days, session_spec, skip_closed=True)
    rows = []
    for day in sorted(anchors):
        anchor, session_open, session_close = anchors[day], opens[day], closes[day]
        if bucket_length is None:
            buckets, nominal_length = [0], nominal[day]
        else:
            first = (session_open - anchor) // bucket_length
            last = -((anchor - session_close) // bucket_length) - 1
            buckets, nominal_length = range(first, last + 1), bucket_length
        for bucket in buckets:
            rows.append((day, bucket, anchor, nominal_length, session_open, session_close))
    if not rows:
        empty = pd.DataFrame(columns=SCHEDULE_COLUMNS)
        empty.index = pd.DatetimeIndex([], name="timestamp_et")
        return empty
    work = pd.DataFrame(rows, columns=["trading_date", "bucket", "anchor", "nominal_length", "session_open", "session_close"])
    work["bar_start"], work["bar_end"] = _bucket_geometry(
        work["anchor"], work["bucket"], work["nominal_length"], bucket_length,
        work["session_open"], work["session_close"],
    )
    work = work.loc[work["bar_end"] > work["bar_start"]].reset_index(drop=True)
    work["expected_bars"], work["is_session_truncated"] = _bucket_metrics(
        work["bar_start"], work["bar_end"], work["nominal_length"], interval
    )
    work["available_at"] = work["bar_end"]
    work["timeframe"] = spec.timeframe_id
    output = work.sort_values(["trading_date", "bar_start"], kind="mergesort")[SCHEDULE_COLUMNS]
    output.index = pd.DatetimeIndex(output["bar_end"], name="timestamp_et")
    return output


def _interval_and_bucket_length(spec: TimeframeSpec, source_interval: Any) -> tuple[pd.Timedelta, pd.Timedelta | None]:
    """Validated source interval and bucket length (``None`` for session timeframes)."""
    interval = pd.Timedelta(source_interval)
    if interval <= pd.Timedelta(0):
        raise TimeframeError("source_interval must be positive")
    bucket_length = pd.Timedelta(minutes=spec.minutes) if spec.minutes is not None else None
    if bucket_length is not None and bucket_length % interval != pd.Timedelta(0):
        raise TimeframeError(f"{spec.timeframe_id} is not a multiple of the source interval {interval}")
    return interval, bucket_length


def _bucket_geometry(
    anchor: pd.Series,
    bucket: pd.Series,
    nominal_length: pd.Series,
    bucket_length: pd.Timedelta | None,
    session_open: pd.Series,
    session_close: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Shared M3 geometry: the nominal bucket clipped to the actual session bounds.

    Fixed-minute buckets are ``[anchor + k*L, anchor + (k+1)*L)``; a session
    timeframe has one bucket ``[anchor, anchor + nominal_length)``.
    """
    if bucket_length is None:
        nominal_start = anchor
        nominal_end = anchor + nominal_length
    else:
        nominal_start = anchor + bucket * bucket_length
        nominal_end = nominal_start + bucket_length
    bar_start = nominal_start.where(nominal_start >= session_open, session_open)
    bar_end = nominal_end.where(nominal_end <= session_close, session_close)
    return bar_start, bar_end


def _bucket_metrics(
    bar_start: pd.Series,
    bar_end: pd.Series,
    nominal_length: pd.Series,
    interval: pd.Timedelta,
) -> tuple[pd.Series, pd.Series]:
    """Shared M3 bucket metrics: expected source bars and session truncation."""
    duration = bar_end - bar_start
    return (duration // interval).astype("int64"), duration < nominal_length


def _schedule_dates(trading_dates: Any) -> list:
    if isinstance(trading_dates, (str, date, pd.Timestamp)):
        trading_dates = [trading_dates]
    try:
        values = list(trading_dates)
    except TypeError as exc:
        raise TimeframeError("trading_dates must be a date or an iterable of dates") from exc
    days = set()
    for value in values:
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise TimeframeError(f"Invalid trading date {value!r}") from exc
        if pd.isna(stamp):
            raise TimeframeError("trading_dates contains a missing value")
        days.add(stamp.date())
    return sorted(days)


def _session_frames(
    trading_dates: list,
    session_spec: SessionSpec,
    *,
    skip_closed: bool = False,
) -> tuple[dict, dict, dict, dict]:
    """Per trading date: regular anchor, actual open/close, regular length.

    A date that is not an open session raises (source bars cannot exist
    there) unless ``skip_closed`` is set, in which case it is omitted.
    """
    regular_spec = with_calendar_overrides(session_spec, [])
    regular_length = (
        pd.Timedelta(days=1)
        - (pd.Timedelta(hours=session_spec.open_time.hour, minutes=session_spec.open_time.minute)
           - pd.Timedelta(hours=session_spec.close_time.hour, minutes=session_spec.close_time.minute))
    )
    anchors, opens, closes, nominal = {}, {}, {}, {}
    for day in trading_dates:
        actual = session_bounds(day, session_spec)
        if not actual.is_open:
            if skip_closed:
                continue
            raise TimeframeError(f"Source bars present on {actual.kind} date {day}")
        regular = session_bounds(day, regular_spec)
        if regular.close - regular.open != regular_length:
            raise TimeframeError(f"Session {day} spans a DST transition; unsupported")
        anchors[day], opens[day], closes[day] = regular.open, actual.open, actual.close
        nominal[day] = regular_length
    return anchors, opens, closes, nominal
