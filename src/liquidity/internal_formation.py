"""Internal Liquidity formation atoms (IL-I2; D-144).

Specification: ``docs/project/INTERNAL_LIQUIDITY_DESIGN.md`` rev 4 §3.2.

Atoms reuse the frozen ``liquidity_members`` / ``liquidity_structures``
envelope (``src/liquidity/contract.py``) with ``liquidity_class = INTERNAL``:

- ``INTERNAL_CANDLE_HIGH`` / ``_LOW``: every **complete** 1H bar's high / low,
  ``source_at = available_at = bar_end``, ``source_ref = HTF_BAR:...|1H|...``.
- ``INTERNAL_SWING_HIGH`` / ``_LOW``: frozen confirmed swings (explicit
  ``swing-pivot-v1`` 2/2) on 5m / 15m / 1H; ``source_ref`` = the swing's
  ``BAR_SPAN``; ``available_at`` = the swing's confirmation.
- EQ / REQ structure versions over swings of one side and one timeframe,
  inside one continuity segment and contract (D-134 grammar at the internal
  grain): EQ exact; REQ link <= 4 ticks with chain connectivity and >= 2
  distinct prices; pair-outer barrier on the timeframe's bars strictly
  between the two swings' plateaus; links decided when the later swing is
  confirmed; immutable FORMED / EXTENDED / MERGED versions with
  ``supersedes``.

Frozen modules (Swing detector, M3, continuity, External, liquidity
contract) are used read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.continuity import continuity_segments
from src.data.instruments import DEFAULT_INSTRUMENT_CONFIG_DIR, load_instrument
from src.data.timeframes import build_timeframe, validate_source_bars
from src.features.external_liquidity import htf_source_ref
from src.liquidity.contract import (
    EQ,
    EXTENDED,
    FORMED,
    INTERNAL,
    LOWER,
    MEMBER_COLUMNS,
    MERGED,
    REQ,
    STRUCTURE_COLUMNS,
    UPPER,
    assign_member_ids,
    assign_structure_ids,
    validate_liquidity_members,
    validate_liquidity_structures,
)
from src.market_structure.structure import require_cutoff
from src.market_structure.swing import SwingDefinitionSpec
from src.market_structure.swing_breaks import price_ticks
from src.market_structure.swing_detector import build_swing_points
from src.state.contract import SPECIFIC

DEFINITION_VERSION = "internal-liquidity-v1"
INTERNAL_TIMEFRAMES = ("5m", "15m", "1H")
CANDLE_TIMEFRAME = "1H"
SWING_DEFINITION = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2)
FORMATION_TOLERANCE_TICKS = {EQ: 0, REQ: 4}
INTERNAL_CANDLE_HIGH, INTERNAL_CANDLE_LOW = "INTERNAL_CANDLE_HIGH", "INTERNAL_CANDLE_LOW"
INTERNAL_SWING_HIGH, INTERNAL_SWING_LOW = "INTERNAL_SWING_HIGH", "INTERNAL_SWING_LOW"


class InternalFormationError(ValueError):
    """Raised for inconsistent formation inputs (fail closed)."""


@dataclass
class InternalFormationResult:
    members: pd.DataFrame                 # liquidity_members (INTERNAL)
    structures: pd.DataFrame              # liquidity_structures (INTERNAL)
    swings: dict = field(default_factory=dict)          # tf -> frozen swing_points
    observations: dict = field(default_factory=dict)    # tf -> M3 observations (<= cutoff)
    spans: dict = field(default_factory=dict)           # member_id -> (start_ns, end_ns, timeframe) physical source span
    barrier_blocks: pd.DataFrame | None = None          # audit: tolerance-passing pairs blocked by the barrier


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_internal_formations(
    bars: pd.DataFrame,
    session_spec,
    *,
    instrument_id: str,
    replay_cutoff: Any,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
    source_interval: Any = "1min",
) -> InternalFormationResult:
    """Internal formation atoms from canonical 1m bars up to ``replay_cutoff`` (source after it is never read)."""
    cutoff = require_cutoff(replay_cutoff)
    tick = Decimal(str(load_instrument(instrument_id, instrument_config_dir).tick_size))
    source = validate_source_bars(bars)
    source = source.loc[source.index <= cutoff]
    member_rows: list[dict] = []
    structure_rows: list[dict] = []
    blocks: list[dict] = []
    result = InternalFormationResult(members=None, structures=None)
    if source.empty:
        result.members = validate_liquidity_members(pd.DataFrame(columns=MEMBER_COLUMNS))
        result.structures = pd.DataFrame(columns=STRUCTURE_COLUMNS)
        result.barrier_blocks = pd.DataFrame()
        return result
    for tf in INTERNAL_TIMEFRAMES:
        obs = build_timeframe(source, tf, session_spec, source_interval=source_interval)
        obs = obs.loc[(pd.to_datetime(obs["bar_end"], utc=True) <= cutoff).to_numpy()]
        result.observations[tf] = obs
        swings = build_swing_points(source, tf, session_spec, SWING_DEFINITION, instrument_id=instrument_id,
                                    instrument_config_dir=instrument_config_dir, source_interval=source_interval)
        swings = swings.loc[(pd.to_datetime(swings["available_at"], utc=True) <= cutoff).to_numpy()].reset_index(drop=True)
        result.swings[tf] = swings
        if tf == CANDLE_TIMEFRAME:
            member_rows.extend(_candle_rows(obs, instrument_id, result.spans))
        swing_rows = _swing_rows(swings, tf, instrument_id)
        member_rows.extend(swing_rows)
        segments, _ = continuity_segments(obs, tf, session_spec, source_interval=source_interval)
        formed, tf_blocks = _clusters(segments, swings, swing_rows, tf, instrument_id, tick, result.spans)
        structure_rows.extend(formed)
        blocks.extend(tf_blocks)
    members = validate_liquidity_members(assign_member_ids(pd.DataFrame(member_rows, columns=MEMBER_COLUMNS)))
    frame = pd.DataFrame(structure_rows, columns=STRUCTURE_COLUMNS)
    structures = validate_liquidity_structures(assign_structure_ids(frame), members) if structure_rows else frame
    result.members, result.structures = members, structures
    result.barrier_blocks = pd.DataFrame(blocks)
    return result


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def _member_row(kind, family, orientation, price, source_ref, source_at, available_at, instrument_id, contract) -> dict:
    return {"member_id": None, "liquidity_class": INTERNAL, "member_kind": kind, "reference_family": family,
            "orientation": orientation, "price": float(price), "source_ref": source_ref, "source_at": source_at,
            "source_seq_domain": None, "source_seq": None, "available_at": available_at, "available_seq_domain": None,
            "available_seq": None, "instrument_id": instrument_id, "contract_scope": SPECIFIC, "contract": contract,
            "definition_version": DEFINITION_VERSION}


def _candle_rows(obs: pd.DataFrame, instrument_id: str, spans: dict) -> list[dict]:
    rows = []
    complete = obs.loc[obs["is_complete"].astype(bool).to_numpy()]
    for bar in complete.itertuples(index=False):
        ref = htf_source_ref(instrument_id, bar.contract, CANDLE_TIMEFRAME, bar.bar_end)
        for kind, orientation, price in ((INTERNAL_CANDLE_HIGH, UPPER, bar.high), (INTERNAL_CANDLE_LOW, LOWER, bar.low)):
            row = _member_row(kind, CANDLE_TIMEFRAME, orientation, price, ref, bar.bar_end, bar.bar_end, instrument_id,
                              bar.contract)
            row["_span"] = (pd.Timestamp(bar.bar_start).value, pd.Timestamp(bar.bar_end).value, CANDLE_TIMEFRAME)
            rows.append(row)
    _assign_ids(rows)
    for row in rows:
        spans[row["member_id"]] = row.pop("_span")
    return rows


def _swing_rows(swings: pd.DataFrame, tf: str, instrument_id: str) -> list[dict]:
    rows = []
    for s in swings.itertuples(index=False):
        kind = INTERNAL_SWING_HIGH if s.orientation == UPPER else INTERNAL_SWING_LOW
        row = _member_row(kind, tf, s.orientation, s.price, s.source_ref, s.source_at, s.available_at, instrument_id,
                          s.contract)
        row["_swing_id"] = s.swing_id
        rows.append(row)
    _assign_ids(rows)
    return rows


def _assign_ids(rows: list[dict]) -> None:
    """Frozen ``assign_member_ids`` over the whole batch (one call; identical ids)."""
    if rows:
        ids = assign_member_ids(pd.DataFrame(rows, columns=MEMBER_COLUMNS))["member_id"]
        for row, mid in zip(rows, ids):
            row["member_id"] = mid


# ---------------------------------------------------------------------------
# EQ / REQ clusters over swings (pure core + segment adapter)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SwingAtom:
    member_id: str
    a: int                    # first plateau position in the segment
    b: int                    # last plateau position
    value: int                # mirrored ticks (UPPER: price; LOWER: -price) so "outer = max"
    ticks: int                # actual price ticks
    available_at: Any
    contract: str


class _RangeMax:
    def __init__(self, values: np.ndarray) -> None:
        self.levels = [np.asarray(values, dtype=np.int64)]
        width = 1
        while width * 2 <= len(values):
            prev = self.levels[-1]
            self.levels.append(np.maximum(prev[:-width], prev[width:]))
            width *= 2

    def query(self, lo: int, hi: int) -> int | None:
        """Max over positions lo..hi inclusive; None for an empty range."""
        if hi < lo:
            return None
        k = (hi - lo + 1).bit_length() - 1
        return int(max(self.levels[k][lo], self.levels[k][hi - (1 << k) + 1]))


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.members: dict[str, set] = {}
        self.version: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent[x] = x
        self.members[x] = {x}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if (len(self.members[ra]), ra) < (len(self.members[rb]), rb):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] |= self.members.pop(rb)
        self.version.pop(rb, None)


def cluster_versions(atoms: list[SwingAtom], extremes: np.ndarray, *, orientation: str, timeframe: str,
                     instrument_id: str) -> tuple[list[dict], list[dict]]:
    """EQ / REQ versions for one side of one segment. ``atoms`` in confirmation order; ``extremes`` mirrored."""
    rmq = _RangeMax(extremes) if len(extremes) else None
    graphs = {EQ: _UnionFind(), REQ: _UnionFind()}
    done: list[SwingAtom] = []
    rows, blocks = [], []
    for j in atoms:
        linked = {EQ: [], REQ: []}
        for i in reversed(done):
            between = rmq.query(i.b + 1, j.a - 1) if rmq is not None else None
            if between is not None and between > j.value + FORMATION_TOLERANCE_TICKS[REQ]:
                break  # every earlier swing is blocked too (barrier only grows backwards)
            distance = abs(i.value - j.value)
            blocked = between is not None and between > max(i.value, j.value)
            for stype, tolerance in FORMATION_TOLERANCE_TICKS.items():
                if distance <= tolerance:
                    if blocked:
                        blocks.append({"timeframe": timeframe, "orientation": orientation, "structure_type": stype,
                                       "earlier_member_id": i.member_id, "later_member_id": j.member_id,
                                       "distance_ticks": distance, "blocking_excess_ticks": between - max(i.value, j.value)})
                    else:
                        linked[stype].append(i.member_id)
        for graph in graphs.values():
            graph.add(j.member_id)
        by_id = {x.member_id: x for x in done + [j]}
        for stype in (EQ, REQ):
            if not linked[stype]:
                continue
            graph = graphs[stype]
            prior = {graph.version[graph.find(i)] for i in linked[stype] if graph.find(i) in graph.version}
            for i in linked[stype]:
                graph.union(i, j.member_id)
            root = graph.find(j.member_id)
            component = sorted(graph.members[root])
            if stype == REQ and len({by_id[m].ticks for m in component}) < 2:
                continue
            change = FORMED if not prior else (EXTENDED if len(prior) == 1 else MERGED)
            row = {"structure_id": None, "liquidity_class": INTERNAL, "structure_type": stype,
                   "reference_family": timeframe, "orientation": orientation, "member_ids": tuple(component),
                   "available_at": j.available_at, "available_seq_domain": None, "available_seq": None,
                   "instrument_id": instrument_id, "contract_scope": SPECIFIC, "contract": j.contract,
                   "change_kind": change, "supersedes": tuple(sorted(prior)), "definition_version": DEFINITION_VERSION}
            row["structure_id"] = assign_structure_ids(pd.DataFrame([row], columns=STRUCTURE_COLUMNS))["structure_id"].iloc[0]
            graph.version[root] = row["structure_id"]
            rows.append(row)
        done.append(j)
    return rows, blocks


def _clusters(segments, swings, swing_rows, tf, instrument_id, tick, spans) -> tuple[list[dict], list[dict]]:
    member_of = {row["_swing_id"]: row["member_id"] for row in swing_rows}
    locate = {}
    prepared = []
    for index, segment in enumerate(segments):
        segment = segment.reset_index(drop=True)
        ends = pd.DatetimeIndex(pd.to_datetime(segment["bar_end"], utc=True)).as_unit("ns").asi8
        starts = pd.DatetimeIndex(pd.to_datetime(segment["bar_start"], utc=True)).as_unit("ns").asi8
        for pos, end in enumerate(ends):
            locate[int(end)] = (index, pos)
        prepared.append({"segment": segment, "starts": starts, "ends": ends,
                         UPPER: price_ticks(segment["high"].to_numpy(), tick),
                         LOWER: -price_ticks(segment["low"].to_numpy(), tick), "atoms": {UPPER: [], LOWER: []}})
    swing_ticks = price_ticks(swings["price"].to_numpy(), tick) if len(swings) else []
    for s, ticks_value in zip(swings.itertuples(index=False), swing_ticks):
        a = locate.get(pd.Timestamp(s.source_at).value)
        b = locate.get(pd.Timestamp(s.source_end_at).value)
        if a is None or b is None or a[0] != b[0]:
            raise InternalFormationError(f"{s.swing_id}: swing plateau is not inside one continuity segment")
        seg = prepared[a[0]]
        if seg["segment"]["contract"].iloc[a[1]] != s.contract:
            raise InternalFormationError(f"{s.swing_id}: swing contract differs from its segment")
        mid = member_of[s.swing_id]
        spans[mid] = (int(seg["starts"][a[1]]), int(seg["ends"][b[1]]), tf)
        value = int(ticks_value) if s.orientation == UPPER else -int(ticks_value)
        seg["atoms"][s.orientation].append(SwingAtom(mid, a[1], b[1], value, int(ticks_value),
                                                     pd.Timestamp(s.available_at), s.contract))
    rows, blocks = [], []
    for seg in prepared:
        for orientation in (UPPER, LOWER):
            atoms = sorted(seg["atoms"][orientation], key=lambda x: (x.available_at, x.a, x.member_id))
            if len(atoms) < 2:
                continue
            r, b = cluster_versions(atoms, seg[orientation], orientation=orientation, timeframe=tf,
                                    instrument_id=instrument_id)
            rows.extend(r)
            blocks.extend(b)
    for row in rows:
        row.pop("_swing_id", None)
    return rows, blocks


