"""Neutral swing-referenced Structure Break evidence (MS-I1; D-139, K-6, K-9).

Specification: ``docs/project/MARKET_STRUCTURE_SPEC.md`` §C.2 / §E.9.

One row per canonical swing that is ever closed strictly beyond inside its
own continuity segment: the **first** such observation only (a breach is
permanent and belongs to the ``swing_id``).  A break requires

- an observation of the swing's own segment (same contract, no continuity
  break between source and break);
- ``bar_start >= swing.available_at`` (actual observation geometry, never a
  fixed bar interval);
- a close strictly beyond the swing price in exact integer ticks: UPPER
  ``close > level``, LOWER ``close < level``.  Equality and wicks never break.

This is Interaction-layer evidence only: no direction, role, BOS / CHoCH or
lifecycle.  Frozen M6 is not used (its ``close_through`` is approach-relative
and it derives ``bar_start`` from a fixed interval; spec §A.2).
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from src.data.instruments import is_tick_aligned
from src.market_structure.swing import LOWER, SWING_TIMEFRAMES, UPPER, bar_span_ref
from src.state.contract import SPECIFIC, SourceRef, canonical_time

BREAK_ID_PREFIX = "sb_"
STRUCTURE_BREAK_KIND = "STRUCTURE_BREAK"
SWING_BREAK_COLUMNS = (
    "break_id",
    "observation_ref",
    "swing_id",
    "swing_ref",
    "timeframe",
    "orientation",
    "bar_start",
    "bar_end",
    "event_at",
    "available_at",
    "level_ticks",
    "close_ticks",
    "tick_size",
    "close_excess_ticks",
    "instrument_id",
    "contract_scope",
    "contract",
    "break_definition_version",
    "fact_hash",
)


class SwingBreakError(ValueError):
    """Raised for inconsistent swing / observation input or an invalid break row."""


def sha256_key(prefix: str, key: list) -> str:
    """``prefix`` + full SHA-256 of canonical JSON (``ensure_ascii=False``, compact separators)."""
    payload = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def break_id(*, break_definition_version: str, swing_id: str, observation_ref: str) -> str:
    """Natural id ``sb_`` + SHA-256(break_definition_version, swing_id, observation_ref)."""
    for name, value in (("break_definition_version", break_definition_version), ("swing_id", swing_id),
                        ("observation_ref", observation_ref)):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise SwingBreakError(f"{name} must be a non-empty trimmed string, got {value!r}")
    return sha256_key(BREAK_ID_PREFIX, [break_definition_version, swing_id, observation_ref])


def structure_break_ref(break_id_value: str) -> str:
    """Canonical ``STRUCTURE_BREAK:<break_id>`` SourceRef text."""
    return SourceRef(STRUCTURE_BREAK_KIND, break_id_value).canonical


def price_ticks(prices: Any, tick: Decimal) -> np.ndarray:
    """Exact integer tick indices; any off-grid price raises ``SwingBreakError``."""
    values = np.asarray(prices, dtype=float)
    if not np.isfinite(values).all():
        raise SwingBreakError("prices must be finite")
    for value in np.unique(values):
        if not is_tick_aligned(float(value), tick):
            raise SwingBreakError(f"price {value} is not on the instrument tick grid ({tick})")
    return np.rint(values / float(tick)).astype(np.int64)


class _FirstGreater:
    """Sparse table answering "first index >= start whose value > level" in O(log n)."""

    def __init__(self, values: np.ndarray) -> None:
        self.n = len(values)
        self.levels = [np.asarray(values, dtype=np.int64)]
        width = 1
        while width * 2 <= self.n:
            prev = self.levels[-1]
            self.levels.append(np.maximum(prev[:-width], prev[width:]))
            width *= 2

    def query(self, start: int, level: int) -> int | None:
        position = start
        if position >= self.n:
            return None
        for k in range(len(self.levels) - 1, -1, -1):
            width = 1 << k
            if position + width <= self.n and self.levels[k][position] <= level:
                position += width
        return position if position < self.n else None


def swing_breaks_from_segments(
    swings: pd.DataFrame,
    segments: list[pd.DataFrame],
    *,
    timeframe: str,
    break_definition_version: str,
    instrument_id: str,
    tick_size: Decimal,
) -> pd.DataFrame:
    """First strictly-beyond close per swing inside its own continuity segment.

    ``swings`` are canonical ``swing_points`` rows of one ``timeframe``;
    ``segments`` are the shared continuity segments (complete observations,
    ``src.data.continuity.continuity_segments``) of the same prepared frame.
    Every swing must have its source span and its confirming observation in
    one segment of its own contract (fail closed otherwise).
    """
    if timeframe not in SWING_TIMEFRAMES:
        raise SwingBreakError(f"timeframe must be one of {SWING_TIMEFRAMES}, got {timeframe!r}")
    tick = Decimal(str(tick_size))
    if swings.empty:
        return empty_swing_breaks()
    if (swings["timeframe"] != timeframe).any() or (swings["instrument_id"] != instrument_id).any():
        raise SwingBreakError("swings must all belong to the requested timeframe and instrument")

    locate: dict[int, tuple[int, int]] = {}
    prepared = []
    for index, segment in enumerate(segments):
        segment = segment.reset_index(drop=True)
        ends = _ns(segment["bar_end"])
        for position, end in enumerate(ends):
            locate[int(end)] = (index, position)
        closes = price_ticks(segment["close"].to_numpy(), tick)
        prepared.append({
            "segment": segment, "ends": ends, "starts": _ns(segment["bar_start"]), "closes": closes,
            UPPER: None, LOWER: None,
        })

    rows = []
    levels = price_ticks(swings["price"].to_numpy(), tick)
    for row, level in zip(swings.itertuples(index=False), levels):
        source = locate.get(int(pd.Timestamp(row.source_at).value))
        confirm = locate.get(int(pd.Timestamp(row.available_at).value))
        if source is None or confirm is None or source[0] != confirm[0]:
            raise SwingBreakError(f"{row.swing_id}: source and confirmation are not in one continuity segment")
        seg = prepared[source[0]]
        if seg["segment"]["contract"].iloc[source[1]] != row.contract:
            raise SwingBreakError(f"{row.swing_id}: swing contract differs from its segment")
        start = int(np.searchsorted(seg["starts"], pd.Timestamp(row.available_at).value, side="left"))
        if row.orientation == UPPER:
            if seg[UPPER] is None:
                seg[UPPER] = _FirstGreater(seg["closes"])
            hit = seg[UPPER].query(start, int(level))
        elif row.orientation == LOWER:
            if seg[LOWER] is None:
                seg[LOWER] = _FirstGreater(-seg["closes"])
            hit = seg[LOWER].query(start, -int(level))
        else:
            raise SwingBreakError(f"{row.swing_id}: unknown orientation {row.orientation!r}")
        if hit is None:
            continue
        bar = seg["segment"].iloc[hit]
        close = int(seg["closes"][hit])
        observation_ref = bar_span_ref(instrument_id=instrument_id, contract=row.contract, timeframe=timeframe,
                                       first_bar_end=bar["bar_end"], last_bar_end=bar["bar_end"])
        excess = abs(close - int(level))
        rows.append({
            "break_id": break_id(break_definition_version=break_definition_version, swing_id=row.swing_id,
                                 observation_ref=observation_ref),
            "observation_ref": observation_ref,
            "swing_id": row.swing_id,
            "swing_ref": row.source_ref,
            "timeframe": timeframe,
            "orientation": row.orientation,
            "bar_start": bar["bar_start"],
            "bar_end": bar["bar_end"],
            "event_at": bar["bar_end"],
            "available_at": bar["bar_end"],
            "level_ticks": int(level),
            "close_ticks": close,
            "tick_size": str(tick),
            "close_excess_ticks": excess,
            "instrument_id": instrument_id,
            "contract_scope": SPECIFIC,
            "contract": row.contract,
            "break_definition_version": break_definition_version,
            "fact_hash": sha256_key("", [int(level), close, str(tick), canonical_time(bar["bar_start"]),
                                         canonical_time(bar["bar_end"])]),
        })
    if not rows:
        return empty_swing_breaks()
    return validate_swing_breaks(pd.DataFrame(rows, columns=list(SWING_BREAK_COLUMNS)))


def empty_swing_breaks() -> pd.DataFrame:
    frame = pd.DataFrame({column: pd.Series(dtype=object) for column in SWING_BREAK_COLUMNS})
    for column in ("bar_start", "bar_end", "event_at", "available_at"):
        frame[column] = pd.Series(dtype="datetime64[ns, UTC]")
    for column in ("level_ticks", "close_ticks", "close_excess_ticks"):
        frame[column] = pd.Series(dtype="int64")
    return frame


def validate_swing_breaks(frame: pd.DataFrame) -> pd.DataFrame:
    """Schema, rule-shape and identity checks; returns rows in canonical order (UTC times)."""
    if not isinstance(frame, pd.DataFrame):
        raise SwingBreakError("swing breaks must be a pandas DataFrame")
    missing = [c for c in SWING_BREAK_COLUMNS if c not in frame.columns]
    extra = [c for c in frame.columns if c not in SWING_BREAK_COLUMNS]
    if missing or extra:
        raise SwingBreakError(f"swing breaks schema mismatch: missing {missing}, extra {extra}")
    out = frame[list(SWING_BREAK_COLUMNS)].reset_index(drop=True).copy()
    if out.empty:
        return empty_swing_breaks()
    for column in ("bar_start", "bar_end", "event_at", "available_at"):
        out[column] = pd.to_datetime(out[column], utc=True).dt.as_unit("ns")
    for column in ("level_ticks", "close_ticks", "close_excess_ticks"):
        out[column] = out[column].astype("int64")
    if not ((out["event_at"] == out["bar_end"]) & (out["available_at"] == out["bar_end"])).all():
        raise SwingBreakError("event_at and available_at must equal bar_end")
    if not (out["bar_start"] < out["bar_end"]).all():
        raise SwingBreakError("bar_start must precede bar_end")
    upper = out["orientation"] == UPPER
    lower = out["orientation"] == LOWER
    if not (upper | lower).all():
        raise SwingBreakError("orientation must be UPPER or LOWER")
    beyond = (upper & (out["close_ticks"] > out["level_ticks"])) | (lower & (out["close_ticks"] < out["level_ticks"]))
    if not beyond.all():
        raise SwingBreakError("every break needs a close strictly beyond the level")
    if not (out["close_excess_ticks"] == (out["close_ticks"] - out["level_ticks"]).abs()).all():
        raise SwingBreakError("close_excess_ticks must equal |close_ticks - level_ticks|")
    if (out["contract_scope"] != SPECIFIC).any():
        raise SwingBreakError(f"contract_scope must be {SPECIFIC}")
    if out["swing_id"].duplicated().any():
        raise SwingBreakError("at most one break row per swing_id (first break only)")
    expected = [break_id(break_definition_version=r.break_definition_version, swing_id=r.swing_id,
                         observation_ref=r.observation_ref) for r in out.itertuples(index=False)]
    if list(out["break_id"]) != expected:
        raise SwingBreakError("break_id does not match its natural key")
    for r in out.itertuples(index=False):
        ref = bar_span_ref(instrument_id=r.instrument_id, contract=r.contract, timeframe=r.timeframe,
                           first_bar_end=r.bar_end, last_bar_end=r.bar_end)
        if ref != r.observation_ref:
            raise SwingBreakError(f"{r.break_id}: observation_ref disagrees with the break observation")
    order = np.lexsort((out["swing_id"].to_numpy(), _ns(out["bar_end"])))
    return out.iloc[order].reset_index(drop=True)


def _ns(values: Any) -> np.ndarray:
    return pd.DatetimeIndex(pd.to_datetime(pd.Series(values), utc=True)).as_unit("ns").asi8
