"""Generic multi-timeframe Swing detector (SW-I2; D-135, D-136, D-138).

One detection algorithm for every supported Swing timeframe (1m, 5m, 15m,
1H, 4H, 1D).  Only the preparation of the target-timeframe observations
differs:

- ``1m``: the original canonical 1-minute source bars, used directly; a thin
  adapter adds schedule metadata and never aggregates or recomputes prices.
- ``5m`` / ``15m`` / ``1H`` / ``4H`` / ``1D``: the unchanged M3
  ``build_timeframe`` output.

Every prepared frame then goes through the same pipeline: shared
expected-schedule continuity (``src.data.continuity``) → maximal equal-value
plateaus per orientation on the exact tick grid → left / right windows
(only a strict exceed fails; equality never invalidates) → canonical rows
(SW-I1 ``bar_span_ref`` / ``assign_swing_ids`` / ``validate_swing_points``).

Detection on a timeframe depends only on that timeframe's observations,
continuity, contracts, the explicit ``SwingDefinitionSpec`` and the tick
size.  No cross-timeframe input, no alternation, no candidate audit, no
projection, no liquidity or structure classification.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from src.data.continuity import ContinuityError, continuity_segments
from src.data.instruments import (
    DEFAULT_INSTRUMENT_CONFIG_DIR,
    InstrumentError,
    is_tick_aligned,
    load_instrument,
    normalize_instrument_id,
)
from src.data.sessions import LABEL_BAR_END, SessionError, SessionSpec, assign_trading_dates
from src.data.timeframes import (
    DEFAULT_SOURCE_INTERVAL,
    OUTPUT_COLUMNS,
    TimeframeError,
    TimeframeSpec,
    build_timeframe,
    expected_timeframe_schedule,
    validate_source_bars,
)
from src.market_structure.swing import (
    LOWER,
    SWING_COLUMNS,
    SWING_TIMEFRAMES,
    UPPER,
    SwingContractError,
    SwingDefinitionSpec,
    assign_swing_ids,
    bar_span_ref,
    validate_swing_points,
)
from src.state.contract import SPECIFIC

ONE_MINUTE = "1m"
_ONE_MINUTE_SPEC = TimeframeSpec(ONE_MINUTE, 1)
_SIDES = ((UPPER, "high"), (LOWER, "low"))


@contextmanager
def _boundary() -> Iterator[None]:
    """Translate errors from reused data-layer primitives into SwingContractError."""
    try:
        yield
    except (ContinuityError, TimeframeError, SessionError, InstrumentError) as exc:
        raise SwingContractError(str(exc)) from exc


def build_swing_points(
    bars: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    definition: SwingDefinitionSpec,
    *,
    instrument_id: str,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> pd.DataFrame:
    """Detect canonical ``swing_points`` for one target ``timeframe``.

    ``bars`` are canonical bar-end-labelled 1-minute source bars (as for
    ``build_timeframe``).  ``timeframe`` is one of ``SWING_TIMEFRAMES``; depth
    is measured in observations of that timeframe.  Returns rows validated by
    ``validate_swing_points`` (an empty canonical frame when nothing confirms).
    """
    if timeframe not in SWING_TIMEFRAMES:
        raise SwingContractError(f"timeframe must be one of {SWING_TIMEFRAMES}, got {timeframe!r}")
    if not isinstance(definition, SwingDefinitionSpec):
        raise SwingContractError("definition must be a SwingDefinitionSpec")
    with _boundary():
        if normalize_instrument_id(instrument_id) != instrument_id:
            raise SwingContractError(f"instrument_id must be canonical, got {instrument_id!r}")
        tick = load_instrument(instrument_id, instrument_config_dir).tick_size
        observations = _prepare_observations(bars, timeframe, session_spec, source_interval)
        schedule_timeframe = _ONE_MINUTE_SPEC if timeframe == ONE_MINUTE else timeframe
        segments, _breaks = continuity_segments(observations, schedule_timeframe, session_spec,
                                                source_interval=source_interval)

    rows = []
    for segment in segments:
        segment = segment.reset_index(drop=True)
        ends = list(segment["bar_end"])
        contract = segment["contract"].iloc[0]
        for orientation, field in _SIDES:
            prices = segment[field].tolist()
            values = _tick_indices(prices, tick)
            if orientation == LOWER:
                values = [-value for value in values]  # mirror: one "exceed = greater" rule for both sides
            for a, b in _confirmed_plateaus(values, definition.left_depth, definition.right_depth):
                rows.append({
                    "swing_id": None, "orientation": orientation, "timeframe": timeframe, "price": float(prices[a]),
                    "source_ref": bar_span_ref(instrument_id=instrument_id, contract=contract, timeframe=timeframe,
                                               first_bar_end=ends[a], last_bar_end=ends[b]),
                    "source_at": ends[a], "source_seq_domain": None, "source_seq": None, "source_end_at": ends[b],
                    "available_at": ends[b + definition.right_depth], "available_seq_domain": None,
                    "available_seq": None, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
                    "contract": contract, "left_depth": definition.left_depth, "right_depth": definition.right_depth,
                    "definition_version": definition.definition_version,
                })
    frame = pd.DataFrame(rows, columns=list(SWING_COLUMNS))
    if rows:
        frame = assign_swing_ids(frame)
    return validate_swing_points(frame, definition, instrument_config_dir=instrument_config_dir)


# ---------------------------------------------------------------------------
# Target-timeframe preparation (the only timeframe-dependent step)
# ---------------------------------------------------------------------------


def _prepare_observations(bars: pd.DataFrame, timeframe: str, session_spec: SessionSpec, source_interval: Any) -> pd.DataFrame:
    if timeframe == ONE_MINUTE:
        return _one_minute_observations(bars, session_spec, source_interval)
    return build_timeframe(bars, timeframe, session_spec, source_interval=source_interval)


def _one_minute_observations(bars: pd.DataFrame, session_spec: SessionSpec, source_interval: Any) -> pd.DataFrame:
    """Canonical 1m source bars as a ``build_timeframe``-shaped frame, prices untouched.

    Adds metadata only (trading date, bar geometry, completeness, schedule
    truncation flag); OHLCV, contract and the bar-end timestamps are the
    original source values.  Every bar must be an expected 1m bucket.
    """
    interval = pd.Timedelta(source_interval)
    if interval != pd.Timedelta(minutes=1):
        raise SwingContractError(f"1m swings need a 1-minute source interval, got {source_interval!r}")
    source = validate_source_bars(bars)
    index = source.index
    trading_dates = assign_trading_dates(index, session_spec, label=LABEL_BAR_END, bar_interval=interval).to_numpy()
    if "session_date" in source.columns:
        declared = pd.to_datetime(source["session_date"]).dt.date.to_numpy()
        mismatch = declared != trading_dates
        if mismatch.any():
            position = int(mismatch.argmax())
            raise SwingContractError(f"session_date {declared[position]} at {index[position]} disagrees with "
                                     f"trading date {trading_dates[position]} from the session model")
    frame = pd.DataFrame({
        "timeframe": ONE_MINUTE,
        "trading_date": trading_dates,
        "contract": source["contract"].to_numpy(),
        "bar_start": index - interval,
        "bar_end": index,
        "available_at": index,
        "open": source["open"].to_numpy(),
        "high": source["high"].to_numpy(),
        "low": source["low"].to_numpy(),
        "close": source["close"].to_numpy(),
        "volume": source["volume"].to_numpy(),
        "observed_bars": 1,
        "is_complete": True,
    })
    schedule = expected_timeframe_schedule(sorted(set(trading_dates)), _ONE_MINUTE_SPEC, session_spec,
                                           source_interval=interval)
    geometry = dict(zip(
        zip(schedule["trading_date"], schedule["bar_start"]),
        zip(schedule["expected_bars"], schedule["is_session_truncated"]),
    ))
    starts = pd.DatetimeIndex(frame["bar_start"]).tz_convert(session_spec.timezone)
    looked_up = [geometry.get((day, start)) for day, start in zip(frame["trading_date"], starts)]
    missing = [position for position, item in enumerate(looked_up) if item is None]
    if missing:
        raise SwingContractError(f"1m bar ending {index[missing[0]]} is not an expected 1m bucket")
    frame["expected_bars"] = [int(item[0]) for item in looked_up]
    frame["is_session_truncated"] = [bool(item[1]) for item in looked_up]
    if (frame["expected_bars"] != 1).any():
        raise SwingContractError("expected 1m buckets must hold exactly one source bar")
    frame = frame[OUTPUT_COLUMNS]
    frame.index = pd.DatetimeIndex(index, name="timestamp_et")
    return frame


# ---------------------------------------------------------------------------
# Generic detection (identical for every timeframe)
# ---------------------------------------------------------------------------


def _tick_indices(prices: list, tick: Decimal) -> list[int]:
    """Exact integer tick indices (converted once per segment / orientation); off-grid raises."""
    out = []
    for price in prices:
        with _boundary():
            aligned = is_tick_aligned(price, tick)
        if not aligned:
            raise SwingContractError(f"price {price} is not on the instrument tick grid ({tick})")
        out.append(int(Decimal(repr(float(price))) / tick))
    return out


def _confirmed_plateaus(values: list[int], left_depth: int, right_depth: int) -> Iterator[tuple[int, int]]:
    """Yield ``(a, b)`` for each maximal equal-value run confirmed by its windows.

    A run ``[a..b]`` with value ``h`` confirms when ``a - left_depth >= 0``,
    ``b + right_depth < len(values)`` and no value in ``values[a-left_depth:a]``
    or ``values[b+1:b+right_depth+1]`` is strictly greater than ``h``.
    Equality outside the run never invalidates.  O(n * (L + R)).
    """
    n = len(values)
    a = 0
    while a < n:
        b = a
        while b + 1 < n and values[b + 1] == values[a]:
            b += 1
        h = values[a]
        if (a - left_depth >= 0 and b + right_depth < n
                and max(values[a - left_depth:a]) <= h and max(values[b + 1:b + right_depth + 1]) <= h):
            yield a, b
        a = b + 1
