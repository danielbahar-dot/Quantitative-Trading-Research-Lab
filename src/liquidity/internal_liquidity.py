"""Internal Liquidity engine (IL-I3; D-145, D-146, D-147).

Specification: ``docs/project/INTERNAL_LIQUIDITY_DESIGN.md`` rev 4 §3.3 - §3.9.

Inputs: canonical 1m bars, frozen External Liquidity output, Internal
formation atoms (IL-I2) and the shared consumption contract (IL-I1).

- **Levels** (``il_``): one active internal level per (contract, side,
  definitive price); evidence attaches as immutable, prospective versions
  (``iv_``: CREATED / EVIDENCE_ADDED / EVIDENCE_SUPERSEDED).  Price and the
  4-tick tolerance never change; consumption by the shared predicate.
  Terminal ids never revive; only genuinely new evidence starts a new id.
- **Grades**: ordered tier (timeframe first, then family; 1H candle < swing <
  REQ < EQ) plus a profile; confluence counts distinct physical extremes
  across the price record's internal and External evidence.
- **Price records** (``lp_``): grouping keys linking every internal level,
  External object and boundary assignment at one (contract, side, price),
  each keeping its own lifecycle and threshold.
- **Ranges** (``ir_``, versions ``rv_``) with **pinned boundary
  assignments** (``ba_``): establishment at the closest eligible candidates
  (upper may be UNBOUNDED; no lower -> INSUFFICIENT_BOUNDARY_DATA); at an
  assignment-consumption event the consumed side advances outward and the
  opposite side is reselected only if strictly closer; cluster extensions
  never move an assignment.
- **Membership** (derived): strictly inside the pinned boundaries.
- **Lifecycle logs**: M7A ``liquidity.consumption`` and
  ``liquidity.internal_range``.

Frozen External, Swing, Market Structure, continuity, M3 and M7 code is used
read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.instruments import DEFAULT_INSTRUMENT_CONFIG_DIR, load_instrument
from src.data.timeframes import build_timeframe, validate_source_bars
from src.features.external_liquidity import build_external_liquidity
from src.liquidity.consumption import (
    ACTIVE,
    BOUNDARY_ASSIGNMENT,
    CONSUMED,
    EXTERNAL_CLUSTER,
    EXTERNAL_DAILY,
    EXTERNAL_TOLERANCE_TICKS,
    INTERNAL_LEVEL,
    INTERNAL_TOLERANCE_TICKS,
    RANGE_TERMINATED,
    RELEASED,
    TERMINATED,
    ConsumableObject,
    ConsumableVersion,
    ConsumptionOutcome,
    ExternalObject,
    MinuteTape,
    build_minute_tape,
    current_version,
    evaluate,
    external_objects,
    sha_id,
    threshold_ticks,
)
from src.liquidity.contract import EQ, EXTERNAL, INTERNAL, LOWER, REQ, UPPER
from src.liquidity.internal_formation import (
    DEFINITION_VERSION,
    INTERNAL_CANDLE_HIGH,
    INTERNAL_CANDLE_LOW,
    InternalFormationResult,
    build_internal_formations,
)
from src.market_structure.structure import DATA_GAP, require_cutoff
from src.market_structure.swing_breaks import price_ticks
from src.state.contract import (
    SPECIFIC,
    AttributeSpec,
    SourceRef,
    StateNamespaceSpec,
    canonical_time,
    transition_id,
    validate_transitions,
)

ENGINE_VERSION = "il-engine-1"
RANGE_DEFINITION_VERSION = "internal-range-v1"
CONSUMPTION_NAMESPACE = "liquidity.consumption"
RANGE_NAMESPACE = "liquidity.internal_range"
UNBOUNDED = "UNBOUNDED"
INSUFFICIENT_BOUNDARY_DATA = "INSUFFICIENT_BOUNDARY_DATA"
NO_DATA = "NO_DATA"
CREATED, EVIDENCE_ADDED, EVIDENCE_SUPERSEDED = "CREATED", "EVIDENCE_ADDED", "EVIDENCE_SUPERSEDED"
ESTABLISHED, UPPER_ADVANCED, LOWER_ADVANCED, BOTH_ADVANCED = "ESTABLISHED", "UPPER_ADVANCED", "LOWER_ADVANCED", "BOTH_ADVANCED"
OPPOSITE_RESELECTED, ADVANCED_OUTWARD = "OPPOSITE_RESELECTED", "ADVANCED_OUTWARD"
RANGE_VERSION_EXCLUDES, LEVEL_CONSUMED, LEVEL_TERMINATED = "RANGE_VERSION_EXCLUDES", "LEVEL_CONSUMED", "LEVEL_TERMINATED"
COINCIDES_WITH_BOUNDARY, NOT_GENUINELY_NEW, PRE_GAP_SOURCE = "COINCIDES_WITH_BOUNDARY", "NOT_GENUINELY_NEW", "PRE_GAP_SOURCE"
VERSION_MOVED = "VERSION_MOVED"
CANDLE, SWING = "CANDLE", "SWING"
GRADE_RANK = {("5m", SWING): 1, ("5m", REQ): 2, ("5m", EQ): 3, ("15m", SWING): 4, ("15m", REQ): 5, ("15m", EQ): 6,
              ("1H", CANDLE): 7, ("1H", SWING): 8, ("1H", REQ): 9, ("1H", EQ): 10}
BOUNDARY_CLUSTER_FAMILY = "4H"
_NEVER = np.iinfo(np.int64).max


class InternalLiquidityError(ValueError):
    """Raised for inconsistent engine inputs or a violated contract (fail closed)."""


def price_record_id(instrument_id: str, contract: str, side: str, ticks: int) -> str:
    return sha_id("lp_", [instrument_id, SPECIFIC, contract, side, int(ticks)])


def consumption_namespace() -> StateNamespaceSpec:
    return StateNamespaceSpec(
        namespace=CONSUMPTION_NAMESPACE, entity_kind="liquidity_object", initial_state=ACTIVE,
        allowed_states=(ACTIVE, CONSUMED, TERMINATED),
        allowed_transitions=frozenset({(ACTIVE, CONSUMED), (ACTIVE, TERMINATED)}), definition_version=DEFINITION_VERSION,
        terminal_states=(CONSUMED, TERMINATED),
        attributes=(AttributeSpec("object_kind", "string"), AttributeSpec("class", "string"),
                    AttributeSpec("threshold_ticks", "Int64"), AttributeSpec("excess_ticks", "Int64"),
                    AttributeSpec("gap_through", "boolean"), AttributeSpec("version_evaluated", "string")))


def range_namespace() -> StateNamespaceSpec:
    return StateNamespaceSpec(namespace=RANGE_NAMESPACE, entity_kind="internal_range", initial_state=ACTIVE,
                              allowed_states=(ACTIVE, TERMINATED), allowed_transitions=frozenset({(ACTIVE, TERMINATED)}),
                              definition_version=RANGE_DEFINITION_VERSION, terminal_states=(TERMINATED,))


# ---------------------------------------------------------------------------
# Context shared by the stages
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    family: str                  # CANDLE / SWING / EQ / REQ
    timeframe: str
    side: str
    price: int                   # definitive price ticks
    available_at: pd.Timestamp
    contract: str
    atoms: tuple[str, ...]       # member ids (itself for members)
    supersedes: tuple[str, ...]  # structure ids superseded (structures only)


@dataclass
class Level:
    level_id: str
    side: str
    price: int
    contract: str
    available_at: pd.Timestamp
    first_evidence: str
    evidence: dict = field(default_factory=dict)      # evidence_id -> Evidence (active)
    superseded: dict = field(default_factory=dict)    # evidence_id -> Evidence (superseded)
    outcome: ConsumptionOutcome | None = None
    versions: list = field(default_factory=list)      # (available_at, version row, physical atoms at the price)

    @property
    def ended_at(self):
        return None if self.outcome is None else self.outcome.ended_at


@dataclass
class _Context:
    tape: MinuteTape
    tick: Decimal
    instrument_id: str
    spans: dict
    member_price: dict                  # internal member id -> ticks
    view: list
    ext_outcomes: dict
    ext_member: dict                    # External member id -> (ticks, source_at, reference_family)
    episode_open: dict                  # episode index -> ns of the opening onset (None for the first)
    audit: list = field(default_factory=list)
    view_by_key: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for x in self.view:
            self.view_by_key.setdefault((x.obj.contract, x.obj.side), []).append(x)

    def price(self, ticks) -> float | None:
        return None if ticks is None or pd.isna(ticks) else float(Decimal(int(ticks)) * self.tick)

    def episode_of(self, at) -> int:
        located = self.tape.locate(at)
        if located is None:
            raise InternalLiquidityError(f"availability {at} is not a 1m bar end on the tape")
        return located[0]

    def external_sources(self, x: ExternalObject, version: ConsumableVersion) -> list[pd.Timestamp]:
        return [self.ext_member[m][1] for m in x.version_members.get(version.version_ref, ()) if m in self.ext_member]


# ---------------------------------------------------------------------------
# Run result
# ---------------------------------------------------------------------------


@dataclass
class InternalLiquidityRun:
    manifest: dict
    formation: InternalFormationResult
    external_members: pd.DataFrame
    external_structures: pd.DataFrame
    levels: pd.DataFrame
    price_records: pd.DataFrame
    price_record_links: pd.DataFrame
    external_cluster_objects: pd.DataFrame
    ranges: pd.DataFrame
    assignments: pd.DataFrame
    memberships: pd.DataFrame
    consumption_evidence: pd.DataFrame
    consumption_transitions: pd.DataFrame
    consumption_entities: pd.DataFrame
    range_transitions: pd.DataFrame
    range_entities: pd.DataFrame
    range_status: pd.DataFrame
    audit: pd.DataFrame
    tape: MinuteTape = field(repr=False, default=None)
    external_view: list = field(repr=False, default_factory=list)
    source_spans: dict = field(repr=False, default_factory=dict)   # physical source spans used for confluence

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_internal_liquidity(
    bars: pd.DataFrame,
    session_spec,
    *,
    instrument_id: str,
    replay_cutoff: Any,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
    source_interval: Any = "1min",
) -> InternalLiquidityRun:
    """End-to-end run from canonical 1m bars up to an explicit ``replay_cutoff`` (later source never read)."""
    cutoff = require_cutoff(replay_cutoff)
    source = validate_source_bars(bars)
    source = source.loc[source.index <= cutoff]
    if source.empty:
        raise InternalLiquidityError("no source bars at or before replay_cutoff")
    tick = Decimal(str(load_instrument(instrument_id, instrument_config_dir).tick_size))
    formation = build_internal_formations(source, session_spec, instrument_id=instrument_id, replay_cutoff=cutoff,
                                          instrument_config_dir=instrument_config_dir, source_interval=source_interval)
    external = build_external_liquidity(source, session_spec, instrument_id=instrument_id,
                                        instrument_config_dir=instrument_config_dir, source_interval=source_interval)
    tape = build_minute_tape(source, session_spec, instrument_id=instrument_id, replay_cutoff=cutoff, tick=tick,
                             source_interval=source_interval)
    spans = dict(formation.spans)
    for tf in ("1D", "4H"):
        obs = build_timeframe(source, tf, session_spec, source_interval=source_interval)
        for start, end in zip(pd.to_datetime(obs["bar_start"], utc=True), pd.to_datetime(obs["bar_end"], utc=True)):
            spans[("bar", tf, end.value)] = (start.value, end.value, tf)
    fingerprint = hashlib.sha256(pd.util.hash_pandas_object(
        source[["open", "high", "low", "close", "volume", "contract"]], index=True).to_numpy().tobytes()).hexdigest()
    return run_internal_liquidity(formation, external.members, external.structures, tape, instrument_id=instrument_id,
                                  tick=tick, spans=spans, source_fingerprint=fingerprint)


def run_internal_liquidity(
    formation: InternalFormationResult,
    external_members: pd.DataFrame,
    external_structures: pd.DataFrame,
    tape: MinuteTape,
    *,
    instrument_id: str,
    tick: Decimal,
    spans: dict | None = None,
    source_fingerprint: str | None = None,
) -> InternalLiquidityRun:
    """Engine over prepared inputs (formation atoms, frozen External tables, minute tape)."""
    cutoff = tape.replay_cutoff
    ext_members = _until(external_members, cutoff)
    ext_structures = _until(external_structures, cutoff)
    view = external_objects(ext_members, ext_structures, tick)
    ext_member = {}
    if len(ext_members):
        for mid, ticks_, src, fam in zip(ext_members["member_id"], price_ticks(ext_members["price"].to_numpy(), tick),
                                         pd.to_datetime(ext_members["source_at"], utc=True),
                                         ext_members["reference_family"]):
            ext_member[mid] = (int(ticks_), src, fam)
    member_price = {}
    if formation.members is not None and not formation.members.empty:
        member_price = {m: int(t) for m, t in zip(formation.members["member_id"],
                                                  price_ticks(formation.members["price"].to_numpy(), tick))}
    episode_open, previous = {}, None
    for episode in tape.episodes:
        episode_open[episode.index] = None if previous is None or previous.reset_at is None else previous.reset_at.value
        previous = episode
    ctx = _Context(tape, tick, instrument_id, dict(spans or {}), member_price, view, {}, ext_member, episode_open)
    for x in view:
        ctx.episode_of(x.obj.available_at)
        ctx.ext_outcomes[x.obj.object_id] = evaluate(x.obj, tape)

    levels = _build_levels(formation, ctx)
    ranges, assignments, range_versions = _simulate_ranges(ctx)
    memberships = _memberships(levels, range_versions, ranges, ctx)

    manifest = {
        "engine_version": ENGINE_VERSION, "definition_version": DEFINITION_VERSION,
        "range_definition_version": RANGE_DEFINITION_VERSION, "instrument_id": instrument_id,
        "replay_cutoff": canonical_time(cutoff), "tick_size": str(tick), "source_fingerprint": source_fingerprint,
        "internal_tolerance_ticks": INTERNAL_TOLERANCE_TICKS, "external_tolerance_ticks": EXTERNAL_TOLERANCE_TICKS,
        "formation_fingerprint": _hash_ids(formation.members, "member_id") + _hash_ids(formation.structures, "structure_id"),
        "external_fingerprint": _hash_ids(ext_members, "member_id") + _hash_ids(ext_structures, "structure_id"),
    }
    manifest["run_id"] = sha_id("ilr_", [manifest[k] for k in sorted(manifest)])
    run_id = manifest["run_id"]

    level_frame = _frame([row for lv in levels for _, row, _ in lv.versions], run_id, hashed=True)
    links = _price_record_links(levels, assignments, ctx)
    records = _price_records(links, levels, ctx)
    objects = [(lv.level_id, INTERNAL_LEVEL, INTERNAL, lv.side, lv.contract, lv.available_at, lv.outcome)
               for lv in levels]
    objects += [(x.obj.object_id, x.obj.object_kind, EXTERNAL, x.obj.side, x.obj.contract, x.obj.available_at,
                 ctx.ext_outcomes[x.obj.object_id]) for x in view]
    objects += [(a["row"]["boundary_assignment_id"], BOUNDARY_ASSIGNMENT, EXTERNAL, a["row"]["side"],
                 a["row"]["contract"], a["row"]["assigned_at"], a["outcome"]) for a in assignments]
    c_entities, c_transitions, c_evidence = _consumption_log(objects, ctx, run_id)
    r_entities, r_transitions = _range_log(ranges, instrument_id, run_id)
    return InternalLiquidityRun(
        manifest=manifest, formation=formation, external_members=ext_members, external_structures=ext_structures,
        levels=level_frame, price_records=_frame(records, run_id), price_record_links=_frame(links, run_id),
        external_cluster_objects=_frame(_cluster_rows(ctx), run_id), ranges=_frame(range_versions, run_id, hashed=True),
        assignments=_frame([a["row"] for a in assignments], run_id, hashed=True),
        memberships=_frame(memberships, run_id), consumption_evidence=c_evidence, consumption_transitions=c_transitions,
        consumption_entities=c_entities, range_transitions=r_transitions, range_entities=r_entities,
        range_status=_range_status(ranges, range_versions, tape), audit=pd.DataFrame(ctx.audit), tape=tape,
        external_view=view, source_spans=ctx.spans)


def _until(frame: pd.DataFrame, cutoff) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame if frame is not None else pd.DataFrame()
    return frame.loc[(pd.to_datetime(frame["available_at"], utc=True) <= cutoff).to_numpy()].reset_index(drop=True)


def _hash_ids(frame, column) -> str:
    if frame is None or frame.empty:
        return hashlib.sha256(b"").hexdigest()[:16]
    return hashlib.sha256("\n".join(sorted(frame[column])).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Levels, versions, grades (§3.3, §3.5)
# ---------------------------------------------------------------------------


def _evidence(formation: InternalFormationResult, ctx: _Context) -> list[Evidence]:
    out: list[Evidence] = []
    members = formation.members
    if members is None or members.empty:
        return out
    for m in members.itertuples(index=False):
        family = CANDLE if m.member_kind in (INTERNAL_CANDLE_HIGH, INTERNAL_CANDLE_LOW) else SWING
        out.append(Evidence(m.member_id, family, m.reference_family, m.orientation, ctx.member_price[m.member_id],
                            pd.Timestamp(m.available_at).tz_convert("UTC"), m.contract, (m.member_id,), ()))
    structures = formation.structures
    if structures is not None and not structures.empty:
        for s in structures.itertuples(index=False):
            prices = [ctx.member_price[x] for x in s.member_ids]
            if s.structure_type == EQ and len(set(prices)) != 1:
                raise InternalLiquidityError(f"{s.structure_id}: EQ members must share one price")
            price = (max(prices) if s.orientation == UPPER else min(prices)) if s.structure_type == REQ else prices[0]
            out.append(Evidence(s.structure_id, s.structure_type, s.reference_family, s.orientation, price,
                                pd.Timestamp(s.available_at).tz_convert("UTC"), s.contract, tuple(s.member_ids),
                                tuple(s.supersedes)))
    return sorted(out, key=lambda e: (e.available_at, e.evidence_id))


def _pre_gap(ev: Evidence, ctx: _Context) -> bool:
    """A-15: after a gap only formations whose every source is later than the onset are admitted."""
    opened = ctx.episode_open[ctx.episode_of(ev.available_at)]
    if opened is None:
        return False
    return any(a in ctx.spans and ctx.spans[a][1] <= opened for a in ev.atoms)


def _build_levels(formation, ctx: _Context) -> list[Level]:
    by_time: dict = {}
    for ev in _evidence(formation, ctx):
        by_time.setdefault(ev.available_at, []).append(ev)
    active: dict = {}                  # (contract, side, price) -> Level
    terminated_atoms: dict = {}        # (contract, side, price) -> atom ids that were evidence of terminated levels
    holder: dict = {}                  # evidence_id -> Level holding it
    levels: list[Level] = []
    source_refs = {}
    if formation.members is not None and len(formation.members):
        source_refs = dict(zip(formation.members["member_id"], formation.members["source_ref"]))
    for at in sorted(by_time):
        for key, level in list(active.items()):
            if level.ended_at is not None and level.ended_at <= at:   # (a) consumption at e(m) precedes (b)
                pool = terminated_atoms.setdefault(key, set())
                for e in list(level.evidence.values()) + list(level.superseded.values()):
                    pool.update(e.atoms)
                del active[key]
        changes: dict = {}
        batch = sorted(by_time[at], key=lambda e: e.evidence_id)
        for ev in batch:
            for old in ev.supersedes:
                lv = holder.get(old)
                if lv is not None and active.get((lv.contract, lv.side, lv.price)) is lv and old in lv.evidence:
                    changes.setdefault((lv.contract, lv.side, lv.price), {"add": [], "drop": []})["drop"].append(old)
        for ev in batch:
            if _pre_gap(ev, ctx):
                ctx.audit.append({"kind": PRE_GAP_SOURCE, "object_id": ev.evidence_id, "at": at, "side": ev.side,
                                  "price_ticks": ev.price})
                continue
            changes.setdefault((ev.contract, ev.side, ev.price), {"add": [], "drop": []})["add"].append(ev)
        for key in sorted(changes):
            adds, drops = changes[key]["add"], changes[key]["drop"]
            level = active.get(key)
            kind = None
            if level is None:
                fresh = [e for e in adds if not set(e.atoms) <= terminated_atoms.get(key, set())]
                for e in adds:
                    if e not in fresh:
                        ctx.audit.append({"kind": NOT_GENUINELY_NEW, "object_id": e.evidence_id, "at": at,
                                          "side": e.side, "price_ticks": e.price})
                if not fresh:
                    continue
                adds = fresh
                first = adds[0]
                level = Level(sha_id("il_", [DEFINITION_VERSION, ctx.instrument_id, SPECIFIC, key[0], key[1], int(key[2]),
                                             _source_ref(first, source_refs)]), key[1], int(key[2]), key[0], at,
                              first.evidence_id)
                ctx.episode_of(at)
                level.outcome = evaluate(ConsumableObject(level.level_id, INTERNAL_LEVEL, INTERNAL, key[1], key[0], (
                    ConsumableVersion(level.level_id, int(key[2]), INTERNAL_TOLERANCE_TICKS, at),)), ctx.tape)
                active[key] = level
                levels.append(level)
                kind = CREATED
            for e in adds:
                level.evidence[e.evidence_id] = e
                holder[e.evidence_id] = level
            for old in drops:
                level.superseded[old] = level.evidence.pop(old)
            if kind is None:
                kind = EVIDENCE_ADDED if adds else EVIDENCE_SUPERSEDED
            atoms_here = tuple(sorted({a for e in level.evidence.values() for a in e.atoms
                                       if ctx.member_price.get(a) == level.price}))
            level.versions.append((at, _level_version_row(level, kind, at, atoms_here, ctx), atoms_here))
    return levels


def _source_ref(ev: Evidence, source_refs: dict) -> str:
    if ev.family in (CANDLE, SWING):
        return source_refs[ev.evidence_id]
    return f"LIQUIDITY_STRUCTURE:{ev.evidence_id}"


def _record_extremes(contract, side, price, at, internal_atoms, ctx: _Context):
    """Physical source spans at one price record: internal atoms at the price + active External atoms there."""
    intervals = [ctx.spans[a][:2] for a in internal_atoms if a in ctx.spans]
    coincident = []
    for x in ctx.view_by_key.get((contract, side), ()):
        if x.obj.available_at > at:
            continue
        out = ctx.ext_outcomes[x.obj.object_id]
        if out.ended_at is not None and out.ended_at <= at:
            continue
        version = current_version(x.obj, at)
        if version is None or version.price_ticks != price:
            continue
        coincident.append(x.obj.object_id)
        for m in x.version_members.get(version.version_ref, ()):
            ticks_, source_at, family = ctx.ext_member[m]
            key = ("bar", family, source_at.value)
            if ticks_ == price and key in ctx.spans:
                intervals.append(ctx.spans[key][:2])
    return _components(intervals), sorted(coincident)


def _components(intervals) -> int:
    """Distinct physical extremes: connected components of overlapping [start, end) spans."""
    count, current_end = 0, None
    for start, end in sorted(intervals):
        if current_end is None or start >= current_end:
            count += 1
            current_end = end
        else:
            current_end = max(current_end, end)
    return count


def _level_version_row(level: Level, kind: str, at, atoms_here, ctx: _Context) -> dict:
    ev = list(level.evidence.values())
    primary = max(ev, key=lambda e: (GRADE_RANK[(e.timeframe, e.family)], e.evidence_id)) if ev else None
    rank = GRADE_RANK[(primary.timeframe, primary.family)] if primary else 0
    confluence, coincident = _record_extremes(level.contract, level.side, level.price, at, atoms_here, ctx)
    timeframes = sorted({e.timeframe for e in ev})
    constituents = sorted({a for e in ev if e.family in (EQ, REQ) for a in e.atoms})
    constituent_prices = sorted({ctx.member_price[a] for a in constituents if a in ctx.member_price})
    families = {(e.timeframe, e.family) for e in ev}
    profile = {
        "primary_family": primary.family if primary else None, "primary_timeframe": primary.timeframe if primary else None,
        "confluence": confluence, "distinct_timeframes": len(timeframes), "constituent_count": len(constituents),
        "distinct_constituent_prices": len(constituent_prices),
        "candle_and_swing_coincide": ("1H", CANDLE) in families and ("1H", SWING) in families,
        "external_coincidence": coincident,
    }
    tier = f"{primary.timeframe} {primary.family}" if primary else "NONE"
    explanation = (f"{tier} (rank {rank}); confluence {confluence} physical extreme(s); timeframes {','.join(timeframes)}"
                   + (f"; {len(coincident)} coincident External object(s)" if coincident else ""))
    evidence_ids = sorted(level.evidence)
    superseded_ids = sorted(level.superseded)
    previous = level.versions[-1][1]["level_version_id"] if level.versions else None
    threshold = threshold_ticks(level.side, level.price, INTERNAL_TOLERANCE_TICKS)
    return {
        "level_id": level.level_id,
        "level_version_id": sha_id("iv_", [level.level_id, evidence_ids, superseded_ids]),
        "change_kind": kind, "supersedes": previous,
        "price_record_id": price_record_id(ctx.instrument_id, level.contract, level.side, level.price),
        "side": level.side, "price": ctx.price(level.price), "price_ticks": level.price,
        "tolerance_ticks": INTERNAL_TOLERANCE_TICKS, "consumption_threshold": ctx.price(threshold),
        "consumption_threshold_ticks": threshold,
        "evidence_member_ids": tuple(sorted(e.evidence_id for e in ev if e.family in (CANDLE, SWING))),
        "evidence_structure_ids": tuple(sorted(e.evidence_id for e in ev if e.family in (EQ, REQ))),
        "superseded_evidence_ids": tuple(superseded_ids),
        "constituent_prices": tuple(ctx.price(p) for p in constituent_prices),
        "primary_family": profile["primary_family"], "primary_timeframe": profile["primary_timeframe"],
        "timeframes": tuple(timeframes), "level_available_at": level.available_at, "available_at": at,
        "grade_tier": tier, "grade_rank": rank, "confluence": confluence, "distinct_timeframes": len(timeframes),
        "external_coincidence": tuple(coincident),
        "grade_profile": json.dumps(profile, sort_keys=True, separators=(",", ":")),
        "grade_explanation": explanation, "instrument_id": ctx.instrument_id, "contract_scope": SPECIFIC,
        "contract": level.contract, "definition_version": DEFINITION_VERSION,
    }


# ---------------------------------------------------------------------------
# Ranges and pinned boundary assignments (§3.6)
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    x: ExternalObject
    episode: int

    @property
    def obj(self) -> ConsumableObject:
        return self.x.obj


def _eligible(cands, side, at, ctx: _Context):
    """Eligible candidates at ``at`` (post-batch): (price, version_at, source_at, id, candidate, version)."""
    out = []
    for c in cands:
        if c.obj.side != side or c.obj.available_at > at:
            continue
        outcome = ctx.ext_outcomes[c.obj.object_id]
        if outcome.ended_at is not None and outcome.ended_at <= at:
            continue
        version = current_version(c.obj, at)
        sources = ctx.external_sources(c.x, version)
        opened = ctx.episode_open[c.episode]
        if opened is not None and any(s.value <= opened for s in sources):
            continue
        out.append((version.price_ticks, version.available_at, max(sources).value if sources else 0, c.obj.object_id,
                    c, version))
    return out


def _closest(items, side, *, reference=None, beyond=None):
    """Closest candidate (UPPER lowest price, LOWER highest), ties by version availability, source, id."""
    if side == UPPER:
        pool = [i for i in items if (reference is None or i[0] >= reference) and (beyond is None or i[0] > beyond)]
        return min(pool, key=lambda i: (i[0], i[1], i[2], i[3])) if pool else None
    pool = [i for i in items if (reference is None or i[0] <= reference) and (beyond is None or i[0] < beyond)]
    return min(pool, key=lambda i: (-i[0], i[1], i[2], i[3])) if pool else None


def _simulate_ranges(ctx: _Context):
    candidates = [_Candidate(x, ctx.episode_of(x.obj.available_at)) for x in ctx.view
                  if x.obj.object_kind == EXTERNAL_DAILY or x.family == BOUNDARY_CLUSTER_FAMILY]
    ranges: list[dict] = []
    assignments: list[dict] = []
    versions: list[dict] = []
    for episode in ctx.tape.episodes:
        cands = [c for c in candidates if c.episode == episode.index]
        _episode_ranges(ctx, episode, cands, ranges, assignments, versions)
    return ranges, assignments, versions


def _episode_ranges(ctx, episode, cands, ranges, assignments, versions):
    n = len(episode.bar_end)
    if n == 0:
        return
    tape = ctx.tape
    times = set()
    for c in cands:
        times.update(v.available_at for v in c.obj.versions)
        if ctx.ext_outcomes[c.obj.object_id].ended_at is not None:
            times.add(ctx.ext_outcomes[c.obj.object_id].ended_at)
    change_times = sorted(times)
    restricted = episode.index > 0 and tape.episodes[episode.index - 1].reset_reason == DATA_GAP
    state = None
    i = 0
    while i < n:
        if state is None:
            m = _find_establishment(ctx, episode, cands, i, change_times)
            if m is None:
                break
            at = pd.Timestamp(int(episode.bar_end[m]), tz="UTC")
            close = int(episode.close[m])
            up = _closest(_eligible(cands, UPPER, at, ctx), UPPER, reference=close)
            lo = _closest(_eligible(cands, LOWER, at, ctx), LOWER, reference=close)
            rng = {"range_id": sha_id("ir_", [RANGE_DEFINITION_VERSION, ctx.instrument_id, SPECIFIC, episode.contract,
                                              canonical_time(at)]),
                   "established_at": at, "contract": episode.contract, "ended_at": None, "end_reason": None,
                   "trigger": None, "episode": episode.index, "post_gap_restricted": bool(restricted)}
            ranges.append(rng)
            upper = _assign(ctx, episode, rng, UPPER, up, at, close, ESTABLISHED, None, assignments) if up else None
            lower = _assign(ctx, episode, rng, LOWER, lo, at, close, ESTABLISHED, None, assignments)
            state = {"range": rng, "upper": upper, "lower": lower}
            _version(ctx, versions, rng, upper, lower, at, ESTABLISHED, close)
            i = m + 1
            continue
        hits = [a for a in (state["upper"], state["lower"]) if a is not None and a["outcome"].status == CONSUMED]
        if not hits:
            break                                        # persists to the episode end (reset handled below)
        first = min(a["outcome"].ended_at for a in hits)
        m = int(np.searchsorted(episode.bar_end, first.value))
        at = pd.Timestamp(int(episode.bar_end[m]), tz="UTC")
        close = int(episode.close[m])
        sides = {a["row"]["side"] for a in hits if a["outcome"].ended_at == at}
        rng = state["range"]
        new_upper, new_lower = state["upper"], state["lower"]
        kinds = []
        lower_pick = None
        if LOWER in sides:
            lower_pick = _closest(_eligible(cands, LOWER, at, ctx), LOWER,
                                  beyond=state["lower"]["row"]["pinned_price_ticks"])
            if lower_pick is None:                       # A-17: terminate; nothing new is assigned at e(m)
                if UPPER not in sides and state["upper"] is not None:
                    _stop(ctx, state["upper"], at, RANGE_TERMINATED)
                rng["ended_at"], rng["end_reason"], rng["trigger"] = at, INSUFFICIENT_BOUNDARY_DATA, tape.bar_ref(episode, m)
                state = None
                i = m if _find_establishment(ctx, episode, cands, m, change_times, only=m) is not None else m + 1
                continue
        if UPPER in sides:
            pick = _closest(_eligible(cands, UPPER, at, ctx), UPPER, beyond=state["upper"]["row"]["pinned_price_ticks"])
            new_upper = _assign(ctx, episode, rng, UPPER, pick, at, close, ADVANCED_OUTWARD,
                                state["upper"]["row"]["boundary_assignment_id"], assignments) if pick else None
            kinds.append(UPPER_ADVANCED)
        if LOWER in sides:
            new_lower = _assign(ctx, episode, rng, LOWER, lower_pick, at, close, ADVANCED_OUTWARD,
                                state["lower"]["row"]["boundary_assignment_id"], assignments)
            kinds.append(LOWER_ADVANCED)
        if sides == {UPPER}:
            opp = state["lower"]
            pick = _closest(_eligible(cands, LOWER, at, ctx), LOWER, reference=close)
            if pick is not None and pick[0] > opp["row"]["pinned_price_ticks"]:
                _stop(ctx, opp, at, RELEASED)
                new_lower = _assign(ctx, episode, rng, LOWER, pick, at, close, OPPOSITE_RESELECTED,
                                    opp["row"]["boundary_assignment_id"], assignments)
                kinds.append(OPPOSITE_RESELECTED)
        elif sides == {LOWER}:
            opp = state["upper"]
            pick = _closest(_eligible(cands, UPPER, at, ctx), UPPER, reference=close)
            if pick is not None and (opp is None or pick[0] < opp["row"]["pinned_price_ticks"]):
                if opp is not None:
                    _stop(ctx, opp, at, RELEASED)
                new_upper = _assign(ctx, episode, rng, UPPER, pick, at, close, OPPOSITE_RESELECTED,
                                    opp["row"]["boundary_assignment_id"] if opp else None, assignments)
                kinds.append(OPPOSITE_RESELECTED)
        else:
            kinds = [BOTH_ADVANCED]
        state = {"range": rng, "upper": new_upper, "lower": new_lower}
        _version(ctx, versions, rng, new_upper, new_lower, at, "+".join(kinds), close)
        i = m + 1
    if state is not None and episode.reset_at is not None:
        rng = state["range"]
        rng["ended_at"], rng["end_reason"], rng["trigger"] = episode.reset_at, episode.reset_reason, episode.reset_ref


def _find_establishment(ctx, episode, cands, start, change_times, only=None):
    """First bar ``m >= start`` whose close is >= the lowest eligible LOWER candidate price at ``e(m)``."""
    n = len(episode.bar_end)
    stop = n if only is None else only + 1
    m = start
    while m < stop:
        at = pd.Timestamp(int(episode.bar_end[m]), tz="UTC")
        k = int(np.searchsorted([t.value for t in change_times], at.value, side="right"))
        hi = n if k >= len(change_times) else int(np.searchsorted(episode.bar_end, change_times[k].value, side="left"))
        hi = min(max(hi, m + 1), stop)
        lowers = _eligible(cands, LOWER, at, ctx)
        if lowers:
            floor = min(item[0] for item in lowers)
            idx = np.flatnonzero(episode.close[m:hi] >= floor)
            if len(idx):
                return m + int(idx[0])
        m = hi
    return None


def _assign(ctx, episode, rng, side, pick, at, close, kind, replaces, assignments):
    price, _, _, object_id, cand, version = pick
    tolerance = version.tolerance_ticks
    threshold = threshold_ticks(side, int(price), tolerance)
    row = {
        "boundary_assignment_id": sha_id("ba_", [rng["range_id"], side, object_id, version.version_ref, int(price),
                                                 tolerance, canonical_time(at)]),
        "range_id": rng["range_id"], "side": side, "external_object_id": object_id,
        "external_object_kind": cand.obj.object_kind, "pinned_formation_ref": version.version_ref,
        "pinned_member_ids": tuple(cand.x.version_members.get(version.version_ref, ())),
        "pinned_price": ctx.price(price), "pinned_price_ticks": int(price), "pinned_tolerance_ticks": tolerance,
        "pinned_threshold": ctx.price(threshold), "pinned_threshold_ticks": threshold, "assigned_at": at,
        "selection_kind": kind, "selection_close": ctx.price(close), "selection_close_ticks": close,
        "replaces_assignment_id": replaces,
        "price_record_id": price_record_id(ctx.instrument_id, episode.contract, side, int(price)),
        "instrument_id": ctx.instrument_id, "contract_scope": SPECIFIC, "contract": episode.contract,
    }
    obj = ConsumableObject(row["boundary_assignment_id"], BOUNDARY_ASSIGNMENT, EXTERNAL, side, episode.contract,
                           (ConsumableVersion(version.version_ref, int(price), tolerance, at),))
    item = {"row": row, "obj": obj, "outcome": evaluate(obj, ctx.tape)}
    assignments.append(item)
    return item


def _stop(ctx, item, at, reason):
    if item["outcome"].ended_at is not None and item["outcome"].ended_at <= at:
        return
    obj = item["obj"]
    item["obj"] = ConsumableObject(obj.object_id, obj.object_kind, obj.liquidity_class, obj.side, obj.contract,
                                   obj.versions, stop_at=at, stop_reason=reason)
    item["outcome"] = evaluate(item["obj"], ctx.tape)


def _version(ctx, versions, rng, upper, lower, at, kind, close):
    upper_id = upper["row"]["boundary_assignment_id"] if upper else UNBOUNDED
    lower_id = lower["row"]["boundary_assignment_id"]
    previous = rng.get("last_version")
    row = {
        "range_id": rng["range_id"],
        "range_version_id": sha_id("rv_", [rng["range_id"], canonical_time(at), upper_id, lower_id]),
        "change_kind": kind, "supersedes": previous,
        "upper_assignment_id": upper_id,
        "upper_pinned_price": upper["row"]["pinned_price"] if upper else None,
        "upper_pinned_price_ticks": upper["row"]["pinned_price_ticks"] if upper else None,
        "upper_pinned_threshold": upper["row"]["pinned_threshold"] if upper else None,
        "upper_pinned_threshold_ticks": upper["row"]["pinned_threshold_ticks"] if upper else None,
        "lower_assignment_id": lower_id,
        "lower_pinned_price": lower["row"]["pinned_price"],
        "lower_pinned_price_ticks": lower["row"]["pinned_price_ticks"],
        "lower_pinned_threshold": lower["row"]["pinned_threshold"],
        "lower_pinned_threshold_ticks": lower["row"]["pinned_threshold_ticks"],
        "available_at": at, "selection_close": ctx.price(close), "selection_close_ticks": close,
        "post_gap_restricted": rng["post_gap_restricted"], "episode": rng["episode"],
        "instrument_id": ctx.instrument_id, "contract_scope": SPECIFIC, "contract": rng["contract"],
        "definition_version": RANGE_DEFINITION_VERSION,
    }
    rng["last_version"] = row["range_version_id"]
    versions.append(row)


# ---------------------------------------------------------------------------
# Membership (§3.6.5)
# ---------------------------------------------------------------------------


def _memberships(levels: list[Level], versions: list[dict], ranges: list[dict], ctx: _Context) -> list[dict]:
    if not levels or not versions:
        return []
    price = np.array([lv.price for lv in levels], dtype=np.int64)
    contract = np.array([lv.contract for lv in levels], dtype=object)
    start = np.array([lv.available_at.value for lv in levels], dtype=np.int64)
    end = np.array([_NEVER if lv.ended_at is None else lv.ended_at.value for lv in levels], dtype=np.int64)
    by_range: dict = {}
    for v in versions:
        by_range.setdefault(v["range_id"], []).append(v)
    rows = []
    for rng in ranges:
        group = by_range.get(rng["range_id"], [])
        range_end = _NEVER if rng["ended_at"] is None else rng["ended_at"].value
        open_rows: dict = {}                                  # level index -> row
        for k, v in enumerate(group):
            vs = v["available_at"].value
            ve = group[k + 1]["available_at"].value if k + 1 < len(group) else range_end
            alive = (contract == v["contract"]) & (end > vs) & (start < ve)
            lower = v["lower_pinned_price_ticks"]
            upper = v["upper_pinned_price_ticks"]
            inside = alive & (price > lower) & (True if upper is None else price < upper)
            boundary = alive & ((price == lower) | (False if upper is None else price == upper))
            for j in np.flatnonzero(boundary):
                ctx.audit.append({"kind": COINCIDES_WITH_BOUNDARY, "object_id": levels[j].level_id,
                                  "at": pd.Timestamp(max(vs, start[j]), tz="UTC"), "side": levels[j].side,
                                  "price_ticks": int(price[j]), "range_version_id": v["range_version_id"]})
            for j in list(open_rows):
                if not inside[j]:
                    row = open_rows.pop(j)
                    row["until_at"], row["end_reason"] = pd.Timestamp(vs, tz="UTC"), RANGE_VERSION_EXCLUDES
            for j in np.flatnonzero(inside):
                if j not in open_rows:
                    open_rows[j] = {"range_id": rng["range_id"], "range_version_id": v["range_version_id"],
                                    "level_id": levels[j].level_id, "from_at": pd.Timestamp(max(vs, start[j]), tz="UTC"),
                                    "until_at": None, "end_reason": None}
                    rows.append(open_rows[j])
                if end[j] != _NEVER and end[j] <= ve:
                    row = open_rows.pop(j)
                    row["until_at"] = pd.Timestamp(int(end[j]), tz="UTC")
                    row["end_reason"] = LEVEL_CONSUMED if levels[j].outcome.status == CONSUMED else LEVEL_TERMINATED
        for row in open_rows.values():
            if range_end != _NEVER:
                row["until_at"], row["end_reason"] = pd.Timestamp(range_end, tz="UTC"), RANGE_TERMINATED
    return rows


# ---------------------------------------------------------------------------
# Price records (§3.4) and the External cluster table
# ---------------------------------------------------------------------------


def _price_record_links(levels, assignments, ctx: _Context) -> list[dict]:
    rows = []
    for lv in levels:
        rows.append(_link(ctx, lv.contract, lv.side, lv.price, lv.level_id, INTERNAL_LEVEL, INTERNAL,
                          INTERNAL_TOLERANCE_TICKS, lv.available_at, lv.ended_at,
                          None if lv.outcome.status == ACTIVE else lv.outcome.reason))
    for x in ctx.view:
        out = ctx.ext_outcomes[x.obj.object_id]
        for k, version in enumerate(x.obj.versions):
            if out.ended_at is not None and version.available_at >= out.ended_at:
                break
            nxt = x.obj.versions[k + 1].available_at if k + 1 < len(x.obj.versions) else None
            if nxt is not None and (out.ended_at is None or nxt < out.ended_at):
                until, reason = nxt, VERSION_MOVED
            else:
                until, reason = out.ended_at, out.reason
            rows.append(_link(ctx, x.obj.contract, x.obj.side, version.price_ticks, x.obj.object_id, x.obj.object_kind,
                              EXTERNAL, version.tolerance_ticks, version.available_at, until, reason,
                              version_ref=version.version_ref))
    for a in assignments:
        r = a["row"]
        rows.append(_link(ctx, r["contract"], r["side"], r["pinned_price_ticks"], r["boundary_assignment_id"],
                          BOUNDARY_ASSIGNMENT, EXTERNAL, r["pinned_tolerance_ticks"], r["assigned_at"],
                          a["outcome"].ended_at, a["outcome"].reason, version_ref=r["pinned_formation_ref"]))
    return rows


def _link(ctx, contract, side, ticks_, object_id, kind, cls, tolerance, linked_from, linked_until, unlink_reason,
          version_ref=None) -> dict:
    threshold = threshold_ticks(side, int(ticks_), tolerance)
    return {"price_record_id": price_record_id(ctx.instrument_id, contract, side, int(ticks_)), "side": side,
            "price": ctx.price(ticks_), "price_ticks": int(ticks_), "contract": contract, "object_id": object_id,
            "object_kind": kind, "liquidity_class": cls, "version_ref": version_ref, "tolerance_ticks": tolerance,
            "threshold": ctx.price(threshold), "threshold_ticks": threshold, "linked_from": linked_from,
            "linked_until": linked_until, "unlink_reason": unlink_reason}


def _price_records(links: list[dict], levels: list[Level], ctx: _Context) -> list[dict]:
    """Versioned price records: one row per change instant of a record's linked objects."""
    level_by_id = {lv.level_id: lv for lv in levels}
    by_record: dict = {}
    for link in links:
        by_record.setdefault(link["price_record_id"], []).append(link)
    rows = []
    for rid, group in by_record.items():
        instants = sorted({g["linked_from"] for g in group} | {g["linked_until"] for g in group
                                                                if g["linked_until"] is not None})
        for at in instants:
            live = [g for g in group if g["linked_from"] <= at and (g["linked_until"] is None or g["linked_until"] > at)]
            ended = [g for g in group if g["linked_until"] == at]
            internal = [g for g in live if g["object_kind"] == INTERNAL_LEVEL]
            atoms = ()
            if internal:
                atoms = [a for t, _, a in level_by_id[internal[0]["object_id"]].versions if t <= at][-1]
            confluence, _ = _record_extremes(group[0]["contract"], group[0]["side"], group[0]["price_ticks"], at,
                                             atoms, ctx)
            statuses = {g["object_id"]: {"status": ACTIVE, "threshold_ticks": g["threshold_ticks"]} for g in live}
            for g in ended:
                statuses.setdefault(g["object_id"], {"status": g["unlink_reason"] or "UNLINKED",
                                                     "threshold_ticks": g["threshold_ticks"]})
            rows.append({"price_record_id": rid, "side": group[0]["side"], "price": group[0]["price"],
                         "price_ticks": group[0]["price_ticks"], "contract": group[0]["contract"], "available_at": at,
                         "internal_level_id": internal[0]["object_id"] if internal else None,
                         "external_object_refs": tuple(sorted(g["object_id"] for g in live
                                                              if g["liquidity_class"] == EXTERNAL)),
                         "object_statuses": json.dumps(statuses, sort_keys=True, separators=(",", ":")),
                         "confluence": confluence, "instrument_id": ctx.instrument_id, "contract_scope": SPECIFIC})
    return rows


def _cluster_rows(ctx: _Context) -> list[dict]:
    rows = []
    for x in ctx.view:
        if x.obj.object_kind != EXTERNAL_CLUSTER:
            continue
        for k, version in enumerate(x.obj.versions):
            threshold = threshold_ticks(x.obj.side, version.price_ticks, version.tolerance_ticks)
            rows.append({"external_object_id": x.obj.object_id, "structure_id": version.version_ref,
                         "change_kind": "FORMED" if k == 0 and not x.merged_from else ("MERGED" if k == 0 else "EXTENDED"),
                         "merged_from_object_ids": x.merged_from, "reference_family": x.family,
                         "structure_type": x.structure_type, "side": x.obj.side, "price": ctx.price(version.price_ticks),
                         "price_ticks": version.price_ticks, "threshold": ctx.price(threshold),
                         "threshold_ticks": threshold, "available_at": version.available_at,
                         "contract": x.obj.contract, "instrument_id": ctx.instrument_id})
    return rows


# ---------------------------------------------------------------------------
# Lifecycle logs (M7A)
# ---------------------------------------------------------------------------


def _consumption_log(objects, ctx: _Context, run_id):
    entities, transitions, evidence = [], [], []
    for object_id, kind, cls, side, contract, available_at, out in objects:
        entities.append({"entity_id": object_id, "available_at": available_at, "valid_from": pd.NaT,
                         "valid_until": pd.NaT, "instrument_id": ctx.instrument_id, "contract_scope": SPECIFIC,
                         "contract": contract})
        if out.status == ACTIVE:
            continue
        trigger = out.trigger_ref or SourceRef(
            "LIQUIDITY_EVENT", f"{out.reason}|{object_id}|{canonical_time(out.ended_at)}").canonical
        new_state = CONSUMED if out.status == CONSUMED else TERMINATED
        tid = transition_id(namespace=CONSUMPTION_NAMESPACE, definition_version=DEFINITION_VERSION, entity_id=object_id,
                            previous_state=ACTIVE, new_state=new_state, transition_at=out.ended_at,
                            trigger_ref=trigger, source_refs=())
        transitions.append({
            "transition_id": tid, "namespace": CONSUMPTION_NAMESPACE, "entity_id": object_id, "previous_state": ACTIVE,
            "new_state": new_state, "transition_at": out.ended_at, "transition_seq_domain": None, "transition_seq": None,
            "available_at": out.ended_at, "available_seq_domain": None, "available_seq": None,
            "instrument_id": ctx.instrument_id, "contract_scope": SPECIFIC, "contract": contract,
            "definition_version": DEFINITION_VERSION, "trigger_ref": trigger, "source_refs": (),
            "reason_code": out.reason, "attr_object_kind": kind, "attr_class": cls, "attr_threshold_ticks": out.threshold,
            "attr_excess_ticks": out.excess_ticks, "attr_gap_through": out.gap_through,
            "attr_version_evaluated": out.version_ref})
        evidence.append({"object_id": object_id, "object_kind": kind, "liquidity_class": cls, "side": side,
                         "contract": contract, "status": new_state, "reason": out.reason, "ended_at": out.ended_at,
                         "trigger_ref": trigger, "version_evaluated": out.version_ref,
                         "price": ctx.price(out.price_ticks), "price_ticks": out.price_ticks,
                         "tolerance_ticks": out.tolerance_ticks, "threshold": ctx.price(out.threshold),
                         "threshold_ticks": out.threshold,
                         "bar_ohlc": None if out.bar_ohlc_ticks is None else tuple(ctx.price(v) for v in out.bar_ohlc_ticks),
                         "bar_ohlc_ticks": out.bar_ohlc_ticks, "excess_ticks": out.excess_ticks,
                         "gap_through": out.gap_through, "max_excursion_ticks": out.max_excursion_ticks})
    ent = _entity_frame(entities)
    tr = _transition_frame(transitions)
    if len(tr):
        for column, dtype in (("attr_object_kind", "string"), ("attr_class", "string"), ("attr_threshold_ticks", "Int64"),
                              ("attr_excess_ticks", "Int64"), ("attr_gap_through", "boolean"),
                              ("attr_version_evaluated", "string")):
            tr[column] = tr[column].astype(dtype)
        tr = validate_transitions(tr, consumption_namespace(), ent)
    tr["run_id"] = run_id
    return ent, tr, _frame(evidence, run_id)


def _range_log(ranges, instrument_id, run_id):
    entities, transitions = [], []
    for r in ranges:
        entities.append({"entity_id": r["range_id"], "available_at": r["established_at"], "valid_from": pd.NaT,
                         "valid_until": pd.NaT, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
                         "contract": r["contract"]})
        if r["ended_at"] is None:
            continue
        tid = transition_id(namespace=RANGE_NAMESPACE, definition_version=RANGE_DEFINITION_VERSION,
                            entity_id=r["range_id"], previous_state=ACTIVE, new_state=TERMINATED,
                            transition_at=r["ended_at"], trigger_ref=r["trigger"], source_refs=())
        transitions.append({
            "transition_id": tid, "namespace": RANGE_NAMESPACE, "entity_id": r["range_id"], "previous_state": ACTIVE,
            "new_state": TERMINATED, "transition_at": r["ended_at"], "transition_seq_domain": None,
            "transition_seq": None, "available_at": r["ended_at"], "available_seq_domain": None, "available_seq": None,
            "instrument_id": instrument_id, "contract_scope": SPECIFIC, "contract": r["contract"],
            "definition_version": RANGE_DEFINITION_VERSION, "trigger_ref": r["trigger"], "source_refs": (),
            "reason_code": r["end_reason"]})
    ent = _entity_frame(entities)
    tr = _transition_frame(transitions)
    if len(tr):
        tr = validate_transitions(tr, range_namespace(), ent)
    tr["run_id"] = run_id
    return ent, tr


def _entity_frame(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["entity_id", "available_at", "valid_from", "valid_until", "instrument_id",
                                        "contract_scope", "contract"])
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    for column in ("valid_from", "valid_until"):
        frame[column] = pd.Series([pd.NaT] * len(frame), dtype="datetime64[ns, UTC]")
    return frame


def _transition_frame(rows) -> pd.DataFrame:
    columns = ["transition_id", "namespace", "entity_id", "previous_state", "new_state", "transition_at",
               "transition_seq_domain", "transition_seq", "available_at", "available_seq_domain", "available_seq",
               "instrument_id", "contract_scope", "contract", "definition_version", "trigger_ref", "source_refs",
               "reason_code"]
    extra = sorted({k for r in rows for k in r if k not in columns})
    frame = pd.DataFrame(rows, columns=columns + extra)
    for column in ("transition_at", "available_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def _range_status(ranges, versions, tape) -> pd.DataFrame:
    """Status timeline over [from_at, until_at): ACTIVE (a range), INSUFFICIENT_BOUNDARY_DATA, NO_DATA."""
    rows = []
    previous_end = None
    for episode in tape.episodes:
        if len(episode.bar_end) == 0:
            continue
        start = pd.Timestamp(int(episode.bar_end[0]), tz="UTC")
        stop = episode.reset_at
        if previous_end is not None and previous_end < start:
            rows.append((None, NO_DATA, previous_end, start, None, None))
        cursor = start
        for r in sorted((r for r in ranges if r["episode"] == episode.index), key=lambda r: r["established_at"]):
            if cursor < r["established_at"]:
                rows.append((None, INSUFFICIENT_BOUNDARY_DATA, cursor, r["established_at"], None, episode.contract))
            rows.append((r["range_id"], ACTIVE, r["established_at"], r["ended_at"], r["end_reason"], episode.contract))
            cursor = r["ended_at"]
            if cursor is None:
                break
        if cursor is not None and (stop is None or cursor < stop):
            rows.append((None, INSUFFICIENT_BOUNDARY_DATA, cursor, stop,
                         episode.reset_reason if stop is not None else None, episode.contract))
        previous_end = stop
    if previous_end is not None:
        rows.append((None, NO_DATA, previous_end, None, None, None))
    frame = pd.DataFrame(rows, columns=["range_id", "status", "from_at", "until_at", "end_reason", "contract"])
    for column in ("from_at", "until_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def _frame(rows: list[dict], run_id: str, *, hashed: bool = False) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if hashed and len(frame):
        frame["fact_hash"] = [hashlib.sha256(json.dumps(row, default=str, sort_keys=True).encode()).hexdigest()
                              for row in rows]
    frame["run_id"] = run_id
    for column in frame.columns:
        if column.endswith("_at") or column in ("linked_from", "linked_until"):
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


# ---------------------------------------------------------------------------
# Causal active-level view (A-12)
# ---------------------------------------------------------------------------


def active_internal_levels(run: InternalLiquidityRun, at: Any) -> pd.DataFrame:
    """Member internal levels usable by the bar starting at ``at`` (bar-boundary rule ``available_at <= at``).

    One row per member level: its latest version, internal threshold, grade, and the range version current at
    ``at`` with its pinned boundary assignments.  No proximity or direction columns.
    """
    at = pd.Timestamp(at).tz_convert("UTC")
    m = run.memberships
    if m.empty:
        return pd.DataFrame()
    live = m[(m["from_at"] <= at) & (m["until_at"].isna() | (m["until_at"] > at))]
    if live.empty:
        return pd.DataFrame()
    versions = run.levels[run.levels["available_at"] <= at]
    latest = versions.groupby("level_id").tail(1).set_index("level_id")
    ranges = run.ranges[run.ranges["available_at"] <= at].groupby("range_id").tail(1).set_index("range_id")
    rows = []
    for r in live.itertuples(index=False):
        v = latest.loc[r.level_id]
        rv = ranges.loc[r.range_id]
        rows.append({"level_id": r.level_id, "level_version_id": v["level_version_id"],
                     "price_record_id": v["price_record_id"], "side": v["side"], "price": v["price"],
                     "price_ticks": v["price_ticks"], "consumption_threshold": v["consumption_threshold"],
                     "grade_tier": v["grade_tier"], "grade_rank": v["grade_rank"], "confluence": v["confluence"],
                     "distinct_timeframes": v["distinct_timeframes"], "grade_explanation": v["grade_explanation"],
                     "external_coincidence": v["external_coincidence"], "range_id": r.range_id,
                     "range_version_id": rv["range_version_id"], "upper_assignment_id": rv["upper_assignment_id"],
                     "upper_pinned_price": rv["upper_pinned_price"], "lower_assignment_id": rv["lower_assignment_id"],
                     "lower_pinned_price": rv["lower_pinned_price"]})
    frame = pd.DataFrame(rows)
    return frame.sort_values(["grade_rank", "confluence", "distinct_timeframes", "level_id"],
                             ascending=[False, False, False, True], kind="mergesort").reset_index(drop=True)
