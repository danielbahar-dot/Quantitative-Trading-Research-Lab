"""Shared tolerance-based liquidity consumption contract (IL-I1; D-143, D-147).

Specification: ``docs/project/INTERNAL_LIQUIDITY_DESIGN.md`` rev 4 §3.1, §3.6.1, §3.6.2, §3.7.

- **Predicate.**  Canonical 1m bar ``m`` consumes an active object iff, using
  the object version available at ``s(m)``, UPPER ``high > p + t`` or LOWER
  ``low < p - t`` (integer ticks; equality never consumes).  Consumption is
  recorded at ``e(m)``; no intrabar order is inferred.
- **Tape.**  Canonical 1m observations split into episodes by the approved
  Market Structure reset adapter (``detect_structure_episodes``, §G.2a) with
  an explicit ``replay_cutoff``: a missing / incomplete expected minute or a
  contract change terminates every object of the episode (``DATA_GAP`` /
  ``CONTRACT_CHANGE``), never as consumption.  Objects are bound to the
  episode in which they become available; nothing crosses an episode.
- **External derived view.**  Frozen External members / structures become
  consumable objects without modification: Daily H/L member objects (fixed
  price) and EQ / REQ cluster *lineages* (``xc_``; FORMED starts, EXTENDED
  continues, MERGED starts a new lineage and terminates the absorbed ones as
  ``MERGED``), priced at the current version's definitive price.
- **Pinned boundary assignments** are consumable objects with exactly one
  version, evaluated independently of their live cluster (A-19).

Frozen External, Swing, Market Structure, continuity, M3 and M7 code is used
read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from src.data.timeframes import TimeframeSpec, build_timeframe, validate_source_bars
from src.liquidity.contract import EQ, EXTERNAL, INTERNAL, LOWER, MERGED, REQ, UPPER, EXTENDED, FORMED
from src.market_structure.structure import CONTRACT_CHANGE, DATA_GAP, detect_structure_episodes, require_cutoff
from src.market_structure.swing_breaks import price_ticks

INTERNAL_TOLERANCE_TICKS = 4
EXTERNAL_TOLERANCE_TICKS = 6

# object kinds and lifecycle vocabulary (liquidity.consumption namespace)
INTERNAL_LEVEL = "INTERNAL_LEVEL"
EXTERNAL_DAILY = "EXTERNAL_DAILY"
EXTERNAL_CLUSTER = "EXTERNAL_CLUSTER"
BOUNDARY_ASSIGNMENT = "BOUNDARY_ASSIGNMENT"
OBJECT_KINDS = (INTERNAL_LEVEL, EXTERNAL_DAILY, EXTERNAL_CLUSTER, BOUNDARY_ASSIGNMENT)
ACTIVE, CONSUMED, TERMINATED = "ACTIVE", "CONSUMED", "TERMINATED"
RELEASED, RANGE_TERMINATED = "RELEASED", "RANGE_TERMINATED"
LINEAGE_PREFIX = "xc_"

DAILY_KINDS = {"DAILY_HIGH": UPPER, "DAILY_LOW": LOWER}


class ConsumptionError(ValueError):
    """Raised for inconsistent consumption inputs (fail closed)."""


def sha_id(prefix: str, key: list) -> str:
    return prefix + hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def threshold_ticks(side: str, price: int, tolerance: int) -> int:
    """``θ`` in ticks: UPPER ``p + t``, LOWER ``p - t``."""
    if side == UPPER:
        return price + tolerance
    if side == LOWER:
        return price - tolerance
    raise ConsumptionError(f"side must be UPPER or LOWER, got {side!r}")


# ---------------------------------------------------------------------------
# Objects and outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsumableVersion:
    version_ref: str
    price_ticks: int
    tolerance_ticks: int
    available_at: pd.Timestamp


@dataclass(frozen=True)
class ConsumableObject:
    object_id: str
    object_kind: str
    liquidity_class: str
    side: str
    contract: str
    versions: tuple[ConsumableVersion, ...]
    stop_at: pd.Timestamp | None = None        # non-consumption end imposed by the caller (MERGED / RELEASED / ...)
    stop_reason: str | None = None

    @property
    def available_at(self) -> pd.Timestamp:
        return self.versions[0].available_at


@dataclass(frozen=True)
class ConsumptionOutcome:
    object_id: str
    status: str                                 # ACTIVE / CONSUMED / TERMINATED (at the replay cutoff)
    ended_at: pd.Timestamp | None
    reason: str | None                          # CONSUMED / DATA_GAP / CONTRACT_CHANGE / MERGED / RELEASED / ...
    trigger_ref: str | None                     # consuming bar BAR_SPAN or the CONTINUITY_BREAK ref
    version_ref: str | None                     # version evaluated by the consuming bar
    price_ticks: int | None
    tolerance_ticks: int | None
    threshold: int | None
    bar_end: pd.Timestamp | None
    bar_ohlc_ticks: tuple | None
    excess_ticks: int | None
    gap_through: bool | None
    max_signed_excursion_ticks: int | None      # audit only; see ``_excursion`` (signed; negative = never reached p)

    @property
    def max_penetration_ticks(self) -> int | None:
        """Nonnegative depth beyond ``p`` before the end: ``max(0, max_signed_excursion_ticks)``."""
        return None if self.max_signed_excursion_ticks is None else max(0, self.max_signed_excursion_ticks)


# ---------------------------------------------------------------------------
# Canonical 1m tape (episodes from the §G.2a adapter)
# ---------------------------------------------------------------------------


class _FirstAbove:
    """Sparse table: first index >= lo whose value > level (O(log n))."""

    def __init__(self, values: np.ndarray) -> None:
        self.n = len(values)
        self.levels = [np.asarray(values, dtype=np.int64)]
        width = 1
        while width * 2 <= self.n:
            prev = self.levels[-1]
            self.levels.append(np.maximum(prev[:-width], prev[width:]))
            width *= 2

    def first(self, lo: int, level: int) -> int | None:
        pos = lo
        if pos >= self.n:
            return None
        for k in range(len(self.levels) - 1, -1, -1):
            width = 1 << k
            if pos + width <= self.n and self.levels[k][pos] <= level:
                pos += width
        return pos if pos < self.n else None


@dataclass
class TapeEpisode:
    index: int
    contract: str
    bar_start: np.ndarray        # ns
    bar_end: np.ndarray          # ns
    open: np.ndarray             # ticks
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    reset_at: pd.Timestamp | None
    reset_reason: str | None
    reset_ref: str | None
    _upper: _FirstAbove | None = field(default=None, repr=False)
    _lower: _FirstAbove | None = field(default=None, repr=False)

    def first_beyond(self, side: str, lo: int, threshold: int) -> int | None:
        if side == UPPER:
            if self._upper is None:
                self._upper = _FirstAbove(self.high)
            return self._upper.first(lo, threshold)
        if self._lower is None:
            self._lower = _FirstAbove(-self.low)
        return self._lower.first(lo, -threshold)


@dataclass
class MinuteTape:
    instrument_id: str
    tick: Decimal
    replay_cutoff: pd.Timestamp
    episodes: list[TapeEpisode]
    _end_index: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for episode in self.episodes:
            for position, end in enumerate(episode.bar_end):
                self._end_index[int(end)] = (episode.index, position)

    def locate(self, at: Any) -> tuple[int, int] | None:
        """(episode, position) of the 1m bar ending exactly at ``at``."""
        return self._end_index.get(int(pd.Timestamp(at).value))

    def bar_ref(self, episode: TapeEpisode, position: int) -> str:
        from src.market_structure.swing import bar_span_ref

        end = pd.Timestamp(int(episode.bar_end[position]), tz="UTC")
        return bar_span_ref(instrument_id=self.instrument_id, contract=episode.contract, timeframe="1m",
                            first_bar_end=end, last_bar_end=end)


def build_minute_tape(bars: pd.DataFrame, session_spec, *, instrument_id: str, replay_cutoff: Any, tick: Decimal,
                      source_interval: Any = "1min") -> MinuteTape:
    """Canonical 1m observations up to ``replay_cutoff`` split into §G.2a episodes."""
    cutoff = require_cutoff(replay_cutoff)
    source = validate_source_bars(bars)
    source = source.loc[source.index <= cutoff]
    if source.empty:
        return MinuteTape(instrument_id, tick, cutoff, [])
    observations = build_timeframe(source, TimeframeSpec("1m", 1), session_spec, source_interval=source_interval)
    episodes = detect_structure_episodes(observations, "1m", session_spec, replay_cutoff=cutoff,
                                         source_interval=source_interval)
    out = []
    for k, episode in enumerate(episodes):
        rows = episode.rows
        out.append(TapeEpisode(
            index=k, contract=episode.contract,
            bar_start=pd.DatetimeIndex(pd.to_datetime(rows["bar_start"], utc=True)).as_unit("ns").asi8,
            bar_end=pd.DatetimeIndex(pd.to_datetime(rows["bar_end"], utc=True)).as_unit("ns").asi8,
            open=price_ticks(rows["open"].to_numpy(), tick), high=price_ticks(rows["high"].to_numpy(), tick),
            low=price_ticks(rows["low"].to_numpy(), tick), close=price_ticks(rows["close"].to_numpy(), tick),
            reset_at=None if episode.reset_at is None else pd.Timestamp(episode.reset_at).tz_convert("UTC"),
            reset_reason=episode.reset_reason, reset_ref=episode.reset_ref))
    return MinuteTape(instrument_id, tick, cutoff, out)


# ---------------------------------------------------------------------------
# The predicate (shared by every object kind)
# ---------------------------------------------------------------------------


def evaluate(obj: ConsumableObject, tape: MinuteTape) -> ConsumptionOutcome:
    """First consumption (or termination) of ``obj`` on the tape, using per-bar start versions."""
    if not obj.versions:
        raise ConsumptionError(f"{obj.object_id}: no versions")
    times = [v.available_at for v in obj.versions]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ConsumptionError(f"{obj.object_id}: version availability must strictly increase")
    located = tape.locate(obj.available_at)
    if located is None:
        raise ConsumptionError(f"{obj.object_id}: available_at {obj.available_at} is not a 1m bar end on the tape")
    episode = tape.episodes[located[0]]
    if episode.contract != obj.contract:
        raise ConsumptionError(f"{obj.object_id}: contract {obj.contract} differs from its episode {episode.contract}")
    stop_ns = None if obj.stop_at is None else int(pd.Timestamp(obj.stop_at).value)
    starts = episode.bar_start
    for k, version in enumerate(obj.versions):
        lo = int(np.searchsorted(starts, int(version.available_at.value), side="left"))
        hi_time = int(obj.versions[k + 1].available_at.value) if k + 1 < len(obj.versions) else None
        if stop_ns is not None:
            hi_time = stop_ns if hi_time is None else min(hi_time, stop_ns)
        hi = len(starts) if hi_time is None else int(np.searchsorted(starts, hi_time, side="left"))
        if lo >= hi:
            continue
        theta = threshold_ticks(obj.side, version.price_ticks, version.tolerance_ticks)
        hit = episode.first_beyond(obj.side, lo, theta)
        if hit is not None and hit < hi:
            o, h, lo_, c = (int(episode.open[hit]), int(episode.high[hit]), int(episode.low[hit]), int(episode.close[hit]))
            excess = h - theta if obj.side == UPPER else theta - lo_
            gap = o > theta if obj.side == UPPER else o < theta
            start = int(np.searchsorted(starts, int(obj.available_at.value), side="left"))
            return ConsumptionOutcome(
                obj.object_id, CONSUMED, pd.Timestamp(int(episode.bar_end[hit]), tz="UTC"), CONSUMED,
                tape.bar_ref(episode, hit), version.version_ref, version.price_ticks, version.tolerance_ticks, theta,
                pd.Timestamp(int(episode.bar_end[hit]), tz="UTC"), (o, h, lo_, c), int(excess), bool(gap),
                _excursion(obj.side, episode, start, hit, obj.versions))
    if stop_ns is not None and (episode.reset_at is None or stop_ns <= int(episode.reset_at.value)):
        return _ended(obj, TERMINATED, pd.Timestamp(stop_ns, tz="UTC"), obj.stop_reason, None, episode, tape)
    if episode.reset_at is not None:
        return _ended(obj, TERMINATED, episode.reset_at, episode.reset_reason, episode.reset_ref, episode, tape)
    return _ended(obj, ACTIVE, None, None, None, episode, tape)


def _ended(obj, status, at, reason, trigger, episode, tape) -> ConsumptionOutcome:
    starts = episode.bar_start
    lo = int(np.searchsorted(starts, int(obj.available_at.value), side="left"))
    hi = len(starts) if at is None else int(np.searchsorted(starts, int(pd.Timestamp(at).value), side="left"))
    return ConsumptionOutcome(obj.object_id, status, at, reason, trigger, None, None, None, None, None, None, None,
                              None, _excursion(obj.side, episode, lo, hi, obj.versions))


def _excursion(side, episode, lo, hi, versions) -> int | None:
    """Max signed excursion beyond ``p`` over bars ``lo .. hi-1`` (before the end; the consuming bar excluded).

    Each bar is measured against the version available at its start: UPPER ``high - p``, LOWER ``p - low``
    (ticks).  Negative: price stayed short of ``p``; ``0 .. t``: reached ``p`` within tolerance (equality with
    ``θ`` gives exactly ``t``).  It never exceeds ``t``, because the first bar beyond ``θ`` ends the object.
    Audit only; ``max_penetration_ticks`` is its nonnegative form.
    """
    if hi <= lo:
        return None
    starts = episode.bar_start
    best = None
    for k, version in enumerate(versions):
        a = max(lo, int(np.searchsorted(starts, int(version.available_at.value), side="left")))
        b = hi if k + 1 == len(versions) else min(hi, int(np.searchsorted(
            starts, int(versions[k + 1].available_at.value), side="left")))
        if b <= a:
            continue
        value = (int(episode.high[a:b].max()) - version.price_ticks if side == UPPER
                 else version.price_ticks - int(episode.low[a:b].min()))
        best = value if best is None else max(best, value)
    return best


# ---------------------------------------------------------------------------
# External derived view (frozen External members / structures, unmodified)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExternalObject:
    obj: ConsumableObject
    family: str                       # 1D / 4H
    structure_type: str | None        # None (Daily member), EQ, REQ
    version_members: dict             # version_ref -> tuple(member ids)
    merged_from: tuple[str, ...] = ()


def external_objects(members: pd.DataFrame, structures: pd.DataFrame, tick: Decimal) -> list[ExternalObject]:
    """Daily H/L member objects and EQ / REQ cluster lineages (``xc_``), all with ``t = 6``."""
    out: list[ExternalObject] = []
    members = members.reset_index(drop=True)
    price = dict(zip(members["member_id"], price_ticks(members["price"].to_numpy(), tick))) if len(members) else {}
    for row in members.itertuples(index=False):
        side = DAILY_KINDS.get(row.member_kind)
        if side is None:
            continue
        version = ConsumableVersion(row.member_id, int(price[row.member_id]), EXTERNAL_TOLERANCE_TICKS,
                                    pd.Timestamp(row.available_at).tz_convert("UTC"))
        out.append(ExternalObject(ConsumableObject(row.member_id, EXTERNAL_DAILY, EXTERNAL, side, row.contract,
                                                   (version,)), "1D", None, {row.member_id: (row.member_id,)}))
    if structures is None or structures.empty:
        return out
    frame = structures.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    frame = frame.sort_values(["available_at", "structure_id"], kind="mergesort")
    lineage_of: dict[str, str] = {}
    lineages: dict[str, dict] = {}
    for row in frame.itertuples(index=False):
        ids = tuple(row.member_ids)
        prices = [int(price[m]) for m in ids]
        if row.structure_type == EQ and len(set(prices)) != 1:
            raise ConsumptionError(f"{row.structure_id}: EQ members must share one price")
        definitive = (max(prices) if row.orientation == UPPER else min(prices)) if row.structure_type == REQ else prices[0]
        version = ConsumableVersion(row.structure_id, definitive, EXTERNAL_TOLERANCE_TICKS, row.available_at)
        supersedes = tuple(row.supersedes)
        if row.change_kind == FORMED:
            lid = sha_id(LINEAGE_PREFIX, [row.structure_id])
            lineages[lid] = {"row": row, "versions": [version], "members": {row.structure_id: ids}, "merged_from": (),
                             "stop": None}
        elif row.change_kind == EXTENDED:
            lid = lineage_of[supersedes[0]]
            lineages[lid]["versions"].append(version)
            lineages[lid]["members"][row.structure_id] = ids
        elif row.change_kind == MERGED:
            lid = sha_id(LINEAGE_PREFIX, [row.structure_id])
            absorbed = tuple(sorted({lineage_of[s] for s in supersedes}))
            for old in absorbed:
                if lineages[old]["stop"] is None:
                    lineages[old]["stop"] = row.available_at
            lineages[lid] = {"row": row, "versions": [version], "members": {row.structure_id: ids},
                             "merged_from": absorbed, "stop": None}
        else:
            raise ConsumptionError(f"{row.structure_id}: unknown change_kind {row.change_kind}")
        lineage_of[row.structure_id] = lid
    for lid, item in lineages.items():
        row = item["row"]
        obj = ConsumableObject(lid, EXTERNAL_CLUSTER, EXTERNAL, row.orientation, row.contract, tuple(item["versions"]),
                               stop_at=item["stop"], stop_reason=MERGED if item["stop"] is not None else None)
        out.append(ExternalObject(obj, row.reference_family, row.structure_type, item["members"], item["merged_from"]))
    return out


def current_version(obj: ConsumableObject, at: Any) -> ConsumableVersion | None:
    """Latest version available at or before ``at`` (post-batch view at ``e(m)``)."""
    at = pd.Timestamp(at)
    chosen = None
    for version in obj.versions:
        if version.available_at <= at:
            chosen = version
    return chosen
