"""Swing candidate audit and invariant checks (SW-I3) — AUDIT / VALIDATION ONLY.

Not part of the canonical Swing downstream contract; no Strategy or execution
code may depend on it.  It provides an independent semantic cross-check of
the SW-I2 detector:

- ``audit_swing_candidates``: one row per maximal plateau candidate per
  orientation with an operational, noncanonical status (``CONFIRMED``,
  ``INVALIDATED_STRICT_EXCEED``, ``INSUFFICIENT_LEFT_HISTORY``,
  ``INSUFFICIENT_FUTURE_COVERAGE``, ``CONTINUITY_BREAK``).
- ``swing_invariants``: independent reconstruction of every canonical swing
  from its BAR_SPAN against the source observations and continuity segments.

Candidate evaluation and the 1m observation preparation are implemented
here independently of ``swing_detector`` (no private detector helper is
used).  Generic primitives are reused: M3 ``build_timeframe`` /
``validate_source_bars`` / ``expected_timeframe_schedule``, session trading
dates, shared continuity, M2 instrument metadata and the SW-I1 BAR_SPAN /
``swing_id`` / validation helpers.  Audit rows carry prices; keep them local.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.continuity import continuity_segments
from src.data.instruments import DEFAULT_INSTRUMENT_CONFIG_DIR, is_tick_aligned, load_instrument
from src.data.sessions import LABEL_BAR_END, SessionSpec, assign_trading_dates
from src.data.timeframes import (
    DEFAULT_SOURCE_INTERVAL,
    TimeframeSpec,
    build_timeframe,
    expected_timeframe_schedule,
    validate_source_bars,
)
from src.market_structure.swing import (
    LOWER,
    SWING_TIMEFRAMES,
    UPPER,
    SwingContractError,
    SwingDefinitionSpec,
    bar_span_ref,
    swing_id,
    validate_swing_points,
)
from src.state.contract import SPECIFIC

CONFIRMED = "CONFIRMED"
INVALIDATED_STRICT_EXCEED = "INVALIDATED_STRICT_EXCEED"
INSUFFICIENT_LEFT_HISTORY = "INSUFFICIENT_LEFT_HISTORY"
INSUFFICIENT_FUTURE_COVERAGE = "INSUFFICIENT_FUTURE_COVERAGE"
CONTINUITY_BREAK = "CONTINUITY_BREAK"
AUDIT_STATUSES = (CONFIRMED, INVALIDATED_STRICT_EXCEED, INSUFFICIENT_LEFT_HISTORY, INSUFFICIENT_FUTURE_COVERAGE,
                  CONTINUITY_BREAK)
LEFT, RIGHT = "LEFT", "RIGHT"

CANDIDATE_AUDIT_COLUMNS = (
    "orientation",
    "timeframe",
    "status",
    "swing_id",
    "price",
    "source_ref",
    "source_at",
    "source_end_at",
    "available_at",
    "invalidating_side",
    "invalidating_bar_end",
    "invalidating_excess_ticks",
    "break_reason",
    "instrument_id",
    "contract",
    "left_depth",
    "right_depth",
    "definition_version",
    "segment_index",
)
INVARIANT_COLUMNS = ("timeframe", "orientation", "invariant", "violations", "detail")
INVARIANTS = (
    "bar_span_in_one_segment",
    "plateau_price_exact",
    "plateau_maximal",
    "left_depth_observations_exist",
    "right_depth_observations_exist",
    "upper_window_no_strict_exceed",
    "lower_window_no_strict_exceed",
    "source_at_first_plateau_bar_end",
    "source_end_at_last_plateau_bar_end",
    "available_at_rth_post_plateau_bar_end",
    "timing_invariant",
    "price_tick_aligned",
    "contract_constant_over_window",
    "contract_scope_specific",
    "sequence_fields_null",
    "swing_id_recomputes",
    "swing_id_unique",
    "passes_validate_swing_points",
)
_FIELDS = {UPPER: "high", LOWER: "low"}


def prepare_swing_observations(
    bars: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    *,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> tuple[pd.DataFrame, list[pd.DataFrame], pd.DataFrame]:
    """Target-timeframe observations, continuity segments and break rows (audit preparation).

    ``1m``: canonical 1m bars directly (metadata only, prices untouched);
    ``5m``-``1D``: M3 ``build_timeframe``.  Implemented independently of the detector.
    """
    if timeframe not in SWING_TIMEFRAMES:
        raise SwingContractError(f"timeframe must be one of {SWING_TIMEFRAMES}, got {timeframe!r}")
    if timeframe == "1m":
        observations = _canonical_one_minute(bars, session_spec, source_interval)
        schedule_timeframe = TimeframeSpec("1m", 1)
    else:
        observations = build_timeframe(bars, timeframe, session_spec, source_interval=source_interval)
        schedule_timeframe = timeframe
    segments, breaks = continuity_segments(observations, schedule_timeframe, session_spec, source_interval=source_interval)
    breaks = breaks.assign(timeframe=timeframe)  # audit label as a plain string (1m uses a TimeframeSpec internally)
    return observations, [segment.reset_index(drop=True) for segment in segments], breaks


def audit_swing_candidates(
    bars: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    definition: SwingDefinitionSpec,
    *,
    instrument_id: str,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> pd.DataFrame:
    """One audit row per maximal plateau candidate per orientation (status precedence: SW-I3 §8)."""
    if not isinstance(definition, SwingDefinitionSpec):
        raise SwingContractError("definition must be a SwingDefinitionSpec")
    tick = load_instrument(instrument_id, instrument_config_dir).tick_size
    _, segments, breaks = prepare_swing_observations(bars, timeframe, session_spec, source_interval=source_interval)
    left, right = definition.left_depth, definition.right_depth
    columns: dict[str, list] = {name: [] for name in CANDIDATE_AUDIT_COLUMNS}
    for index, segment in enumerate(segments):
        last_segment = index == len(segments) - 1
        break_reason = None if last_segment else breaks["reason"].iloc[index]
        ends = list(segment["bar_end"])
        contract = segment["contract"].iloc[0]
        n = len(segment)
        for orientation in (UPPER, LOWER):
            prices = segment[_FIELDS[orientation]].tolist()
            ticks = _to_ticks(prices, tick)
            sign = 1 if orientation == UPPER else -1  # exceed = sign * (other - plateau) > 0
            for a, b in _runs(ticks):
                h = ticks[a]
                status, side, inv_end, excess, reason, avail, sid = None, None, None, None, None, None, None
                if a - left < 0:
                    status = INSUFFICIENT_LEFT_HISTORY
                if status is None:
                    for k in range(a - 1, a - left - 1, -1):  # nearest left violation first
                        if sign * (ticks[k] - h) > 0:
                            status, side, inv_end, excess = INVALIDATED_STRICT_EXCEED, LEFT, ends[k], sign * (ticks[k] - h)
                            break
                if status is None:
                    for k in range(b + 1, min(b + right, n - 1) + 1):  # first causal right violation
                        if sign * (ticks[k] - h) > 0:
                            status, side, inv_end, excess = INVALIDATED_STRICT_EXCEED, RIGHT, ends[k], sign * (ticks[k] - h)
                            break
                if status is None and b + right > n - 1:
                    if last_segment:
                        status = INSUFFICIENT_FUTURE_COVERAGE
                    else:
                        status, reason = CONTINUITY_BREAK, break_reason
                ref = bar_span_ref(instrument_id=instrument_id, contract=contract, timeframe=timeframe,
                                   first_bar_end=ends[a], last_bar_end=ends[b])
                if status is None:
                    status, avail = CONFIRMED, ends[b + right]
                    sid = swing_id(definition_version=definition.definition_version, instrument_id=instrument_id,
                                   contract_scope=SPECIFIC, contract=contract, timeframe=timeframe,
                                   orientation=orientation, left_depth=left, right_depth=right, source_ref=ref)
                for name, value in (
                    ("orientation", orientation), ("timeframe", timeframe), ("status", status), ("swing_id", sid),
                    ("price", float(prices[a])), ("source_ref", ref), ("source_at", ends[a]),
                    ("source_end_at", ends[b]), ("available_at", avail), ("invalidating_side", side),
                    ("invalidating_bar_end", inv_end), ("invalidating_excess_ticks", excess),
                    ("break_reason", reason), ("instrument_id", instrument_id), ("contract", contract),
                    ("left_depth", left), ("right_depth", right), ("definition_version", definition.definition_version),
                    ("segment_index", index),
                ):
                    columns[name].append(value)
    frame = pd.DataFrame(columns, columns=list(CANDIDATE_AUDIT_COLUMNS))
    for name in ("source_at", "source_end_at", "available_at", "invalidating_bar_end"):
        frame[name] = pd.to_datetime(frame[name], utc=True)
    frame["invalidating_excess_ticks"] = frame["invalidating_excess_ticks"].astype("Int64")
    frame["segment_index"] = frame["segment_index"].astype("int64")
    return frame


def swing_invariants(
    swings: pd.DataFrame,
    bars: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    definition: SwingDefinitionSpec,
    *,
    instrument_id: str,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> pd.DataFrame:
    """Independently reconstruct every canonical swing; one row per orientation x invariant (price-free)."""
    tick = load_instrument(instrument_id, instrument_config_dir).tick_size
    _, segments, _ = prepare_swing_observations(bars, timeframe, session_spec, source_interval=source_interval)
    where = {}
    for index, segment in enumerate(segments):
        for position, end in enumerate(segment["bar_end"]):
            where[pd.Timestamp(end).value] = (index, position)
    cache: dict[tuple[int, str], list[int]] = {}
    seg_ends = [[pd.Timestamp(end) for end in segment["bar_end"]] for segment in segments]
    seg_contracts = [segment["contract"].tolist() for segment in segments]

    def seg_ticks(index: int, orientation: str) -> list[int]:
        if (index, orientation) not in cache:
            cache[(index, orientation)] = _to_ticks(segments[index][_FIELDS[orientation]].tolist(), tick)
        return cache[(index, orientation)]

    validator_ok = True
    try:
        validate_swing_points(swings, definition, instrument_config_dir=instrument_config_dir)
    except SwingContractError:
        validator_ok = False
    duplicated = set(swings.loc[swings["swing_id"].duplicated(), "swing_id"])
    left, right = definition.left_depth, definition.right_depth
    rows = []
    for orientation in (UPPER, LOWER):
        subset = swings[swings["orientation"] == orientation]
        failures: dict[str, list[str]] = {name: [] for name in INVARIANTS}
        sign = 1 if orientation == UPPER else -1
        for row in subset.itertuples(index=False):
            fail = lambda name: failures[name].append(row.swing_id)  # noqa: E731
            first, last = _span_times(row.source_ref)
            located = (where.get(first), where.get(last))
            if None in located or located[0][0] != located[1][0]:
                fail("bar_span_in_one_segment")
                continue
            (index, a), (_, b) = located
            ticks, n, ends = seg_ticks(index, orientation), len(segments[index]), seg_ends[index]
            price_ok = is_tick_aligned(row.price, tick)
            if not price_ok:
                fail("price_tick_aligned")
            h = int(Decimal(repr(float(row.price))) / tick) if price_ok else None
            if h is None or any(ticks[k] != h for k in range(a, b + 1)):
                fail("plateau_price_exact")
            if (a - 1 >= 0 and ticks[a - 1] == ticks[a]) or (b + 1 < n and ticks[b + 1] == ticks[b]):
                fail("plateau_maximal")
            has_left, has_right = a - left >= 0, b + right < n
            if not has_left:
                fail("left_depth_observations_exist")
            if not has_right:
                fail("right_depth_observations_exist")
            window = [k for k in range(max(a - left, 0), a)] + [k for k in range(b + 1, min(b + right, n - 1) + 1)]
            if any(sign * (ticks[k] - ticks[a]) > 0 for k in window):
                fail("upper_window_no_strict_exceed" if orientation == UPPER else "lower_window_no_strict_exceed")
            if pd.Timestamp(row.source_at) != pd.Timestamp(ends[a]):
                fail("source_at_first_plateau_bar_end")
            if pd.Timestamp(row.source_end_at) != pd.Timestamp(ends[b]):
                fail("source_end_at_last_plateau_bar_end")
            if not has_right or pd.Timestamp(row.available_at) != pd.Timestamp(ends[b + right]):
                fail("available_at_rth_post_plateau_bar_end")
            if not (pd.Timestamp(row.source_at) <= pd.Timestamp(row.source_end_at) < pd.Timestamp(row.available_at)):
                fail("timing_invariant")
            region = set(seg_contracts[index][max(a - left, 0):min(b + right, n - 1) + 1])
            if region != {row.contract}:
                fail("contract_constant_over_window")
            if row.contract_scope != SPECIFIC:
                fail("contract_scope_specific")
            if any(pd.notna(getattr(row, name)) for name in ("source_seq_domain", "source_seq", "available_seq_domain",
                                                             "available_seq")):
                fail("sequence_fields_null")
            try:
                recomputed = swing_id(definition_version=row.definition_version, instrument_id=row.instrument_id,
                                      contract_scope=row.contract_scope, contract=row.contract, timeframe=row.timeframe,
                                      orientation=row.orientation, left_depth=row.left_depth,
                                      right_depth=row.right_depth, source_ref=row.source_ref)
            except SwingContractError:
                recomputed = None
            if recomputed != row.swing_id:
                fail("swing_id_recomputes")
            if row.swing_id in duplicated:
                fail("swing_id_unique")
        if not validator_ok:
            failures["passes_validate_swing_points"].append("<frame>")
        for name in INVARIANTS:
            if (name == "upper_window_no_strict_exceed" and orientation == LOWER) or \
               (name == "lower_window_no_strict_exceed" and orientation == UPPER):
                continue
            rows.append({"timeframe": timeframe, "orientation": orientation, "invariant": name,
                         "violations": len(failures[name]), "detail": failures[name][0] if failures[name] else ""})
    return pd.DataFrame(rows, columns=list(INVARIANT_COLUMNS))


# ---------------------------------------------------------------------------
# Independent helpers (do not use detector internals)
# ---------------------------------------------------------------------------


def _canonical_one_minute(bars: pd.DataFrame, session_spec: SessionSpec, source_interval: Any) -> pd.DataFrame:
    interval = pd.Timedelta(source_interval)
    if interval != pd.Timedelta(minutes=1):
        raise SwingContractError("1m audit needs a 1-minute source interval")
    source = validate_source_bars(bars)
    trading = assign_trading_dates(source.index, session_spec, label=LABEL_BAR_END, bar_interval=interval)
    frame = source[["open", "high", "low", "close", "volume", "contract"]].copy()
    frame.insert(0, "timeframe", "1m")
    frame["trading_date"] = trading.to_numpy()
    frame["bar_end"] = source.index
    frame["bar_start"] = source.index - interval
    frame["available_at"] = source.index
    schedule = expected_timeframe_schedule(sorted(set(frame["trading_date"])), TimeframeSpec("1m", 1), session_spec,
                                           source_interval=interval)
    keyed = schedule.set_index(["trading_date", "bar_start"])[["expected_bars", "is_session_truncated"]]
    lookup = pd.MultiIndex.from_arrays([frame["trading_date"],
                                        pd.DatetimeIndex(frame["bar_start"]).tz_convert(session_spec.timezone)])
    if not lookup.isin(keyed.index).all():
        raise SwingContractError("a 1m bar is not an expected 1m bucket")
    matched = keyed.loc[lookup]
    frame["expected_bars"] = matched["expected_bars"].to_numpy().astype("int64")
    frame["is_session_truncated"] = matched["is_session_truncated"].to_numpy().astype(bool)
    frame["observed_bars"] = 1
    frame["is_complete"] = frame["observed_bars"] == frame["expected_bars"]
    return frame.reset_index(drop=True)


def _to_ticks(prices: list, tick: Decimal) -> list[int]:
    out = []
    for price in prices:
        value = Decimal(str(float(price)))
        if not is_tick_aligned(price, tick):
            raise SwingContractError(f"price {price} is not on the instrument tick grid")
        out.append(int(value / tick))
    return out


def _runs(ticks: list[int]) -> list[tuple[int, int]]:
    """Maximal equal-value runs as (first, last) index pairs."""
    starts = [0] + [k for k in range(1, len(ticks)) if ticks[k] != ticks[k - 1]] if ticks else []
    return [(start, (starts[i + 1] - 1) if i + 1 < len(starts) else len(ticks) - 1) for i, start in enumerate(starts)]


def _span_times(ref: str) -> tuple[int, int]:
    """UTC nanosecond first/last bar ends of a canonical BAR_SPAN ref (independent parse)."""
    kind, key = ref.split(":", 1)
    if kind != "BAR_SPAN":
        raise SwingContractError(f"not a BAR_SPAN ref: {ref!r}")
    parts = key.split("|")
    return pd.Timestamp(parts[3]).value, pd.Timestamp(parts[4]).value
