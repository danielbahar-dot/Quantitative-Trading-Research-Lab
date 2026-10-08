"""FVG interaction, lifecycle, relationships, BPR and grading (FVG-I2, FVG-I3; D-149, D-150, D-152).

Specification: ``docs/project/FVG_IFVG_BPR_DESIGN.md`` rev 2.1 §3.4 – §3.9, §3.11 – §3.13.

Computation is staged without changing the causal batch semantics (§3.6):

1. **Per-zone lifecycle and mitigation** (vectorized).  A zone's stages depend
   only on its own-timeframe closes and the canonical 1m tape of its 1m
   episode, never on other objects.  Mitigation of a stage uses the 1m bars
   with ``bar_start ≥ stage_start`` up to the stage's closing bar (step a
   precedes step b at the same instant).  Resets come from the frozen §G.2a
   adapter: a ``DATA_GAP`` onset has no bar; a ``CONTRACT_CHANGE`` onset is
   the first new-contract bar, which belongs to the next episode and is
   therefore never evaluated against old-contract objects (basis guard).
2. **Relationship episodes** (event-ordered).  At every instant with an
   exit, a conversion or an admission, pairs involving a mover are
   reassessed once from the final batch state; episodes are keyed by the
   two parents' stage identities.
3. **BPR objects** (vectorized, governing timeframe) and **grade versions**
   (formation groups over same-direction partners).

All price comparisons are integer ticks (midpoints in half-ticks).  No age
limit; raw basis only (the shared adjustment method is deferred, §3.11.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from src.data.timeframes import TimeframeSpec, build_timeframe
from src.fvg.formation import (
    BEARISH,
    BULLISH,
    FVG_DEFINITION_VERSION,
    TF_RANK,
    FvgError,
    bar_ref,
    ctime,
    frame,
    raw_basis,
    sha_id,
)
from src.market_structure.structure import CONTRACT_CHANGE, DATA_GAP, detect_structure_episodes
from src.market_structure.swing import bar_span_ref
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

FVG, IFVG, RETIRED, TERMINATED, PENDING = "FVG", "IFVG", "RETIRED", "TERMINATED", "PENDING_ADJUSTMENT"
ACTIVE, ENDED = "ACTIVE", "ENDED"
CONVERTED = "CONVERTED"
FVG_OVERLAP, BPR, MTF_BPR, UNDEFINED = "FVG_OVERLAP", "BPR", "MTF_BPR", "UNDEFINED"
ZONE_TRADE, SPANNING, FAR_CONTACT, BEYOND = "ZONE_TRADE", "SPANNING", "FAR_CONTACT", "BEYOND"
PENETRATION, MIDPOINT, FULL, DEPTH, GAP_THROUGH = "PENETRATION", "MIDPOINT", "FULL", "DEPTH", "GAP_THROUGH"
PARENT_STAGE_CHANGED, PARENT_RETIRED, PARENT_TERMINATED, PARENT_PENDING = (
    "PARENT_STAGE_CHANGED", "PARENT_RETIRED", "PARENT_TERMINATED", "PARENT_PENDING")
BASIS_MISMATCH = "BASIS_MISMATCH"
NS_ZONE, NS_OVERLAP, NS_BPR = "fvg.zone", "fvg.overlap", "fvg.bpr"
_EXIT_REASON = {RETIRED: PARENT_RETIRED, TERMINATED: PARENT_TERMINATED, PENDING: PARENT_PENDING}

MITIGATION_COLUMNS = ("event_id", "object_id", "object_kind", "stage", "kind", "at", "bar_ref", "bar_open_ticks",
                      "bar_high_ticks", "bar_low_ticks", "bar_close_ticks", "observation_class",
                      "penetration_depth_ticks", "in_zone_depth_ticks", "contract", "basis_id")
EPISODE_COLUMNS = ("relationship_id", "label", "zone_a", "stage_a", "zone_b", "stage_b", "cross_timeframe", "movers",
                   "event_time", "direction", "governing_timeframe", "i_lower_ticks", "i_upper_ticks",
                   "i_midpoint_half_ticks", "i_lower", "i_upper", "created_at", "ended_at", "end_reason",
                   "contract", "basis_id", "definition_version")
BPR_COLUMNS = ("bpr_id", "relationship_id", "label", "direction", "governing_timeframe", "parent_a", "stage_a",
               "parent_b", "stage_b", "lower_ticks", "upper_ticks", "midpoint_half_ticks", "lower", "upper", "midpoint",
               "width_ticks", "available_at", "exit_state", "exit_at", "exit_reason", "contract", "basis_id",
               "definition_version")
GRADE_COLUMNS = ("grade_version_id", "zone_id", "available_at", "timeframe_rank", "overlap_contribution",
                 "partner_zone_ids", "group_count", "normalization_status", "normalized_gap_strength", "strength_num",
                 "strength_den", "original_width_ticks", "stage", "current_direction", "actionable", "supersedes")
GROUP_COLUMNS = ("grade_version_id", "zone_id", "group_index", "representative_zone_id", "member_zone_ids")
STAGE_COLUMNS = ("zone_id", "stage", "current_direction", "stage_start", "stage_end", "end_kind")
WARNING_COLUMNS = ("at", "reason", "reset_ref", "terminated_count", "contract")
PENDING_COLUMNS = ("object_id", "object_kind", "contract", "comparison_scope", "reason", "since_at")


# ---------------------------------------------------------------------------
# M7A namespaces
# ---------------------------------------------------------------------------


def zone_namespace() -> StateNamespaceSpec:
    return StateNamespaceSpec(
        namespace=NS_ZONE, entity_kind="fvg_zone", initial_state=FVG,
        allowed_states=(FVG, IFVG, RETIRED, TERMINATED, PENDING),
        allowed_transitions=frozenset({(FVG, IFVG), (IFVG, RETIRED), (FVG, TERMINATED), (IFVG, TERMINATED),
                                       (FVG, PENDING), (IFVG, PENDING)}),
        definition_version=FVG_DEFINITION_VERSION, terminal_states=(RETIRED, TERMINATED, PENDING),
        attributes=(AttributeSpec("current_direction", "string"), AttributeSpec("close_ticks", "Int64"),
                    AttributeSpec("timeframe", "string")))


def overlap_namespace() -> StateNamespaceSpec:
    return StateNamespaceSpec(namespace=NS_OVERLAP, entity_kind="fvg_relationship", initial_state=ACTIVE,
                              allowed_states=(ACTIVE, ENDED), allowed_transitions=frozenset({(ACTIVE, ENDED)}),
                              definition_version=FVG_DEFINITION_VERSION, terminal_states=(ENDED,))


def bpr_namespace() -> StateNamespaceSpec:
    return StateNamespaceSpec(namespace=NS_BPR, entity_kind="fvg_bpr", initial_state=ACTIVE,
                              allowed_states=(ACTIVE, RETIRED, TERMINATED, PENDING),
                              allowed_transitions=frozenset({(ACTIVE, RETIRED), (ACTIVE, TERMINATED),
                                                             (ACTIVE, PENDING)}),
                              definition_version=FVG_DEFINITION_VERSION, terminal_states=(RETIRED, TERMINATED, PENDING))


# ---------------------------------------------------------------------------
# Canonical 1m tape (frozen §G.2a adapter)
# ---------------------------------------------------------------------------


@dataclass
class TapeEpisode:
    index: int
    contract: str
    start: np.ndarray
    end: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    reset_at: pd.Timestamp | None
    reset_reason: str | None
    reset_ref: str | None
    next_first_end: int | None = None        # first bar end of the next episode (CB-2 trigger bar)


@dataclass
class MinuteTape:
    episodes: list
    where: dict = field(default_factory=dict)  # bar end ns -> (episode, position)

    def locate(self, ns: int):
        return self.where.get(int(ns))


def build_tape(source: pd.DataFrame, session_spec, *, replay_cutoff: pd.Timestamp, tick: Decimal,
               source_interval: Any = "1min") -> MinuteTape:
    if source.empty:
        return MinuteTape([])
    obs = build_timeframe(source, TimeframeSpec("1m", 1), session_spec, source_interval=source_interval)
    episodes = detect_structure_episodes(obs, "1m", session_spec, replay_cutoff=replay_cutoff,
                                         source_interval=source_interval)
    out = []
    for k, ep in enumerate(episodes):
        rows = ep.rows
        out.append(TapeEpisode(
            k, ep.contract,
            pd.DatetimeIndex(pd.to_datetime(rows["bar_start"], utc=True)).as_unit("ns").asi8,
            pd.DatetimeIndex(pd.to_datetime(rows["bar_end"], utc=True)).as_unit("ns").asi8,
            price_ticks(rows["open"].to_numpy(), tick), price_ticks(rows["high"].to_numpy(), tick),
            price_ticks(rows["low"].to_numpy(), tick), price_ticks(rows["close"].to_numpy(), tick),
            None if ep.reset_at is None else pd.Timestamp(ep.reset_at).tz_convert("UTC"), ep.reset_reason,
            ep.reset_ref))
    for a, b in zip(out, out[1:]):
        if len(b.end):
            a.next_first_end = int(b.end[0])
    tape = MinuteTape(out)
    for ep in out:
        for pos, end in enumerate(ep.end):
            tape.where[int(end)] = (ep.index, pos)
    return tape


def check_segments_within_episodes(tape: MinuteTape, tf_data: dict) -> None:
    """Fail closed if a timeframe continuity segment break is not matched by a 1m episode change (§3.1 / §3.6)."""
    for tf, data in tf_data.items():
        for a, b in zip(data.segments, data.segments[1:]):
            ea, eb = tape.locate(a["end"][-1]), tape.locate(b["end"][0])
            if ea is None or eb is None:
                raise FvgError(f"{tf}: segment bar end not on the 1m tape")
            if ea[0] == eb[0]:
                raise FvgError(f"{tf}: continuity break inside one 1m episode at {pd.Timestamp(int(a['end'][-1]), tz='UTC')}")


# ---------------------------------------------------------------------------
# Mitigation classification (§3.5)
# ---------------------------------------------------------------------------


def classify(direction: str, lo: int, up: int, mid2: int, l: np.ndarray, h: np.ndarray) -> dict:
    """Vectorized observation classes for bars (low ``l``, high ``h``) against a closed zone ``[lo, up]``."""
    if direction == BULLISH:          # price expected above; retracement downward
        trade = (l < up) & (h >= lo)
        return {"trade": trade, "beyond": h < lo, "spanning": trade & (l <= lo) & (h >= up), "far": trade & (h == lo),
                "midpoint": trade & (2 * l <= mid2), "full": trade & (l <= lo), "depth": up - l,
                "in_zone": up - np.maximum(l, lo)}
    trade = (h > lo) & (l <= up)
    return {"trade": trade, "beyond": l > up, "spanning": trade & (h >= up) & (l <= lo), "far": trade & (l == up),
            "midpoint": trade & (2 * h >= mid2), "full": trade & (h >= up), "depth": h - lo,
            "in_zone": np.minimum(h, up) - lo}


def mitigation_rows(object_id, kind, stage, direction, lo, up, mid2, ep: TapeEpisode, a: int, b: int, *,
                    instrument_id: str) -> list[dict]:
    """Stage milestones, depth records and gap-through evidence for 1m positions ``a .. b - 1``."""
    if b <= a:
        return []
    l, h = ep.l[a:b], ep.h[a:b]
    cls = classify(direction, lo, up, mid2, l, h)
    rows = []
    trade_idx = np.flatnonzero(cls["trade"])
    first_trade = int(trade_idx[0]) if len(trade_idx) else None

    def row(i, event_kind):
        pos = a + i
        obs_class = (SPANNING if cls["spanning"][i] else FAR_CONTACT if cls["far"][i] else ZONE_TRADE) \
            if cls["trade"][i] else BEYOND
        trade = bool(cls["trade"][i])
        ns = int(ep.end[pos])
        # tuple in MITIGATION_COLUMNS order (memory: millions of rows on DEVELOPMENT)
        return (sha_id("fm_", [object_id, stage, event_kind, ctime(ns)]), object_id, kind, stage, event_kind, ns,
                bar_ref(instrument_id, ep.contract, "1m", ns), int(ep.o[pos]), int(ep.h[pos]), int(ep.l[pos]),
                int(ep.c[pos]), obs_class, int(cls["depth"][i]) if trade else None,
                int(cls["in_zone"][i]) if trade else None, ep.contract, raw_basis(ep.contract))
    beyond_idx = np.flatnonzero(cls["beyond"])
    if len(beyond_idx) and (first_trade is None or beyond_idx[0] < first_trade):
        rows.append(row(int(beyond_idx[0]), GAP_THROUGH))
    if first_trade is None:
        return rows
    rows.append(row(first_trade, PENETRATION))
    for key, event_kind in (("midpoint", MIDPOINT), ("full", FULL)):
        idx = np.flatnonzero(cls[key])
        if len(idx):
            rows.append(row(int(idx[0]), event_kind))
    depth = np.where(cls["trade"], cls["depth"], np.iinfo(np.int64).min)
    running = np.maximum.accumulate(depth)
    grew = np.flatnonzero(cls["trade"] & (depth == running) & (np.r_[True, running[1:] > running[:-1]]))
    for i in grew:
        rows.append(row(int(i), DEPTH))
    return rows


# ---------------------------------------------------------------------------
# Run container
# ---------------------------------------------------------------------------


@dataclass
class EngineResult:
    stages: pd.DataFrame
    zone_transitions: pd.DataFrame
    zone_entities: pd.DataFrame
    mitigation: pd.DataFrame
    episodes: pd.DataFrame
    episode_transitions: pd.DataFrame
    episode_entities: pd.DataFrame
    bprs: pd.DataFrame
    bpr_transitions: pd.DataFrame
    bpr_entities: pd.DataFrame
    grades: pd.DataFrame
    groups: pd.DataFrame
    warnings: pd.DataFrame
    pending: pd.DataFrame
    zone_exits: dict = field(repr=False, default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 1: per-zone lifecycle and mitigation
# ---------------------------------------------------------------------------


def _reset_trigger(ep: TapeEpisode, instrument_id: str, next_contract: str | None) -> str:
    if ep.reset_reason == CONTRACT_CHANGE and ep.next_first_end is not None and next_contract is not None:
        end = pd.Timestamp(ep.next_first_end, tz="UTC")
        return bar_span_ref(instrument_id=instrument_id, contract=next_contract, timeframe="1m", first_bar_end=end,
                            last_bar_end=end)
    return ep.reset_ref


def zone_lifecycles(zones: pd.DataFrame, tf_data: dict, tape: MinuteTape, *, instrument_id: str):
    """Stages, exits and mitigation of every zone (independent of all other objects)."""
    stage_rows, transitions, mitigation, exits = [], [], [], {}
    seg_pos = {tf: d.segment_of_end() for tf, d in tf_data.items()}
    for z in zones.itertuples(index=False):
        avail_ns = z.available_at.value
        loc = tape.locate(avail_ns)
        if loc is None:
            raise FvgError(f"{z.zone_id}: availability {z.available_at} is not a 1m bar end on the tape")
        ep = tape.episodes[loc[0]]
        if ep.contract != z.contract:
            raise FvgError(f"{z.zone_id}: contract differs from its 1m episode")
        si, k3 = seg_pos[z.timeframe][avail_ns]
        seg = tf_data[z.timeframe].segments[si]
        closes, ends = seg["c"][k3 + 1:], seg["end"][k3 + 1:]
        lo, up, mid2 = z.lower_ticks, z.upper_ticks, z.midpoint_half_ticks
        d0 = z.original_direction
        d1 = BEARISH if d0 == BULLISH else BULLISH
        beyond0 = closes < lo if d0 == BULLISH else closes > up
        conv_idx = np.flatnonzero(beyond0)
        conv = int(conv_idx[0]) if len(conv_idx) else None
        retire = None
        if conv is not None:
            beyond1 = closes[conv + 1:] < lo if d1 == BULLISH else closes[conv + 1:] > up
            r_idx = np.flatnonzero(beyond1)
            retire = conv + 1 + int(r_idx[0]) if len(r_idx) else None
        conv_ns = int(ends[conv]) if conv is not None else None
        retire_ns = int(ends[retire]) if retire is not None else None
        # stages and the terminal exit
        stage_list = [(FVG, d0, avail_ns, conv_ns)]
        if conv is not None:
            stage_list.append((IFVG, d1, conv_ns, retire_ns))
        exit_kind = exit_ns = None
        if retire is not None:
            exit_kind, exit_ns = RETIRED, retire_ns
        elif ep.reset_at is not None:
            exit_kind = TERMINATED if ep.reset_reason == DATA_GAP else PENDING
            exit_ns = ep.reset_at.value
        exits[z.zone_id] = {"conv_ns": conv_ns, "exit_kind": exit_kind, "exit_ns": exit_ns, "episode": ep.index}
        for st, d, s_ns, e_ns in stage_list:
            end_ns = e_ns if e_ns is not None else exit_ns
            end_kind = (CONVERTED if st == FVG and conv_ns is not None else exit_kind)
            stage_rows.append({"zone_id": z.zone_id, "stage": st, "current_direction": d,
                               "stage_start": pd.Timestamp(s_ns, tz="UTC"),
                               "stage_end": None if end_ns is None else pd.Timestamp(end_ns, tz="UTC"),
                               "end_kind": end_kind})
            a = int(np.searchsorted(ep.start, s_ns, side="left"))
            b = len(ep.end) if e_ns is None else int(np.searchsorted(ep.end, e_ns, side="right"))
            mitigation += mitigation_rows(z.zone_id, "ZONE", st, d, lo, up, mid2, ep, a, b, instrument_id=instrument_id)
        # transitions
        def tf_ref(ns):
            t = pd.Timestamp(ns, tz="UTC")
            return bar_ref(instrument_id, z.contract, z.timeframe, int(ns))
        if conv_ns is not None:
            transitions.append(_zone_tr(z, FVG, IFVG, conv_ns, tf_ref(conv_ns), CONVERTED, d1,
                                        int(closes[conv]), instrument_id))
        if exit_kind is not None:
            prev = IFVG if conv_ns is not None else FVG
            if exit_kind == RETIRED:
                transitions.append(_zone_tr(z, IFVG, RETIRED, exit_ns, tf_ref(exit_ns), RETIRED, d1,
                                            int(closes[retire]), instrument_id))
            else:
                nxt = tape.episodes[ep.index + 1].contract if ep.index + 1 < len(tape.episodes) else None
                transitions.append(_zone_tr(z, prev, exit_kind, exit_ns, _reset_trigger(ep, instrument_id, nxt),
                                            ep.reset_reason, d1 if conv_ns is not None else d0, None, instrument_id))
    return stage_rows, transitions, mitigation, exits


def _zone_tr(z, prev, new, ns, trigger, reason, direction, close_ticks, instrument_id) -> dict:
    at = pd.Timestamp(ns, tz="UTC")
    return {"transition_id": transition_id(namespace=NS_ZONE, definition_version=FVG_DEFINITION_VERSION,
                                           entity_id=z.zone_id, previous_state=prev, new_state=new, transition_at=at,
                                           trigger_ref=trigger, source_refs=()),
            "namespace": NS_ZONE, "entity_id": z.zone_id, "previous_state": prev, "new_state": new,
            "transition_at": at, "transition_seq_domain": None, "transition_seq": None, "available_at": at,
            "available_seq_domain": None, "available_seq": None, "instrument_id": instrument_id,
            "contract_scope": SPECIFIC, "contract": z.contract, "definition_version": FVG_DEFINITION_VERSION,
            "trigger_ref": trigger, "source_refs": (), "reason_code": reason, "attr_current_direction": direction,
            "attr_close_ticks": close_ticks, "attr_timeframe": z.timeframe}


# ---------------------------------------------------------------------------
# Stage 2: relationship episodes (event-ordered, final-batch reassessment)
# ---------------------------------------------------------------------------


def _groups(partners: list[dict]) -> list[list[dict]]:
    """Connected components of partners linked by positive-duration overlap of their source spans."""
    parent = list(range(len(partners)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(partners)):
        for j in range(i + 1, len(partners)):
            a0, a1 = partners[i]["span"]
            b0, b1 = partners[j]["span"]
            if a0 < b1 and b0 < a1:
                parent[find(i)] = find(j)
    comps = {}
    for i in range(len(partners)):
        comps.setdefault(find(i), []).append(partners[i])
    return sorted(comps.values(), key=lambda g: min(p["zone_id"] for p in g))


def _representative(group: list[dict]) -> dict:
    return min(group, key=lambda p: (-TF_RANK[p["timeframe"]], -p["width"], p["available_ns"], p["zone_id"]))


def relationships(zones: pd.DataFrame, exits: dict, *, instrument_id: str):
    """Episodes and grade versions from an event-ordered replay of admissions, conversions and exits."""
    info = {}
    for z in zones.itertuples(index=False):
        e = exits[z.zone_id]
        info[z.zone_id] = {
            "zone_id": z.zone_id, "timeframe": z.timeframe, "contract": z.contract, "lo": z.lower_ticks,
            "up": z.upper_ticks, "d0": z.original_direction, "width": z.width_ticks,
            "available_ns": z.available_at.value, "span": (z.span_start.value, z.available_at.value),
            "conv_ns": e["conv_ns"], "exit_ns": e["exit_ns"], "exit_kind": e["exit_kind"],
            "status": z.normalization_status, "strength": z.normalized_gap_strength, "num": z.strength_num,
            "den": z.strength_den}
    events: dict = {}
    for zid, zi in info.items():
        events.setdefault(zi["available_ns"], {"admit": [], "convert": [], "exit": []})["admit"].append(zid)
        if zi["conv_ns"] is not None:
            events.setdefault(zi["conv_ns"], {"admit": [], "convert": [], "exit": []})["convert"].append(zid)
        if zi["exit_ns"] is not None:
            events.setdefault(zi["exit_ns"], {"admit": [], "convert": [], "exit": []})["exit"].append(zid)
    active: dict = {}                 # contract -> {zone_id: None} (insertion-ordered)
    stage = {}                        # zone_id -> (stage, direction)
    open_ep: dict = {}                # (zid_a, zid_b) -> episode row
    partners: dict = {}               # zone_id -> set of same-direction partner ids (open FVG_OVERLAP episodes)
    episodes, grades, groups = [], [], []
    last_grade: dict = {}
    for t_ns in sorted(events):
        ev = events[t_ns]
        t = pd.Timestamp(t_ns, tz="UTC")
        touched = set()
        # steps 0 / b: exits at t end every open episode of the parent
        for zid in sorted(ev["exit"]):
            zi = info[zid]
            active.get(zi["contract"], {}).pop(zid, None)
            stage[zid] = (zi["exit_kind"], stage.get(zid, (None, zi["d0"]))[1])
            for key in [k for k in open_ep if zid in k]:
                _end_episode(open_ep.pop(key), t, _EXIT_REASON[zi["exit_kind"]], partners, touched)
            touched.add(zid)
        # step b: conversions at t
        for zid in sorted(ev["convert"]):
            zi = info[zid]
            stage[zid] = (IFVG, BEARISH if zi["d0"] == BULLISH else BULLISH)
            touched.add(zid)
        # step c: admissions at t
        for zid in sorted(ev["admit"]):
            zi = info[zid]
            active.setdefault(zi["contract"], {})[zid] = None
            stage[zid] = (FVG, zi["d0"])
            touched.add(zid)
        movers = sorted(set(ev["admit"]) | set(ev["convert"]))
        movers = [m for m in movers if stage[m][0] in (FVG, IFVG)]
        mover_set = set(movers)
        # step d: reassessment from the final batch state
        handled = set()
        for m in movers:
            mi = info[m]
            pool = [p for p in active.get(mi["contract"], {}) if p != m]
            if not pool:
                continue
            lo = np.array([info[p]["lo"] for p in pool])
            up = np.array([info[p]["up"] for p in pool])
            ilo, iup = np.maximum(lo, mi["lo"]), np.minimum(up, mi["up"])
            for j in np.flatnonzero(iup - ilo >= 1):
                p = pool[int(j)]
                key = tuple(sorted((m, p)))
                if key in handled:
                    continue
                handled.add(key)
                a, b = key
                stages = (stage[a][0], stage[b][0])
                old = open_ep.get(key)
                if old is not None and (old["stage_a"], old["stage_b"]) == stages:
                    continue
                if old is not None:
                    _end_episode(open_ep.pop(key), t, PARENT_STAGE_CHANGED, partners, touched)
                ep = _new_episode(info, stage, a, b, stages, int(ilo[int(j)]), int(iup[int(j)]), t,
                                  [x for x in key if x in mover_set], instrument_id)
                open_ep[key] = ep
                episodes.append(ep)
                if ep["label"] == FVG_OVERLAP:
                    partners.setdefault(a, set()).add(b)
                    partners.setdefault(b, set()).add(a)
                touched.update(key)
        # step f: grade versions for every zone whose components may have changed at t
        for zid in sorted(touched):
            _grade_version(zid, info, stage, partners, t, grades, groups, last_grade)
    return episodes, grades, groups, info


def _new_episode(info, stage, a, b, stages, ilo, iup, t, movers, instrument_id) -> dict:
    da, db = stage[a][1], stage[b][1]
    ta, tb = info[a]["timeframe"], info[b]["timeframe"]
    if da == db:
        label, direction, gov = FVG_OVERLAP, da, None
    else:
        label = BPR if ta == tb else MTF_BPR
        if len(movers) == 1:
            direction, gov = stage[movers[0]][1], info[movers[0]]["timeframe"]
        else:
            direction, gov = UNDEFINED, None
    contract = info[a]["contract"]
    rid = sha_id("fo_", [FVG_DEFINITION_VERSION, raw_basis(contract), [a, stages[0]], [b, stages[1]]])
    return {"relationship_id": rid, "label": label, "zone_a": a, "stage_a": stages[0], "zone_b": b,
            "stage_b": stages[1], "cross_timeframe": ta != tb, "movers": tuple(movers), "event_time": t,
            "direction": direction, "governing_timeframe": gov, "i_lower_ticks": ilo, "i_upper_ticks": iup,
            "i_midpoint_half_ticks": ilo + iup, "created_at": t, "ended_at": None, "end_reason": None,
            "contract": contract, "basis_id": raw_basis(contract), "definition_version": FVG_DEFINITION_VERSION}


def _end_episode(ep, t, reason, partners, touched) -> None:
    ep["ended_at"], ep["end_reason"] = t, reason
    if ep["label"] == FVG_OVERLAP:
        partners.get(ep["zone_a"], set()).discard(ep["zone_b"])
        partners.get(ep["zone_b"], set()).discard(ep["zone_a"])
    touched.update((ep["zone_a"], ep["zone_b"]))


def _grade_version(zid, info, stage, partners, t, grades, groups, last_grade) -> None:
    zi = info[zid]
    st, direction = stage[zid]
    actionable = st in (FVG, IFVG)
    members = [info[p] for p in sorted(partners.get(zid, set()))] if actionable else []
    comps = _groups(members)
    member_ids = tuple(sorted(p["zone_id"] for p in members))
    state = (len(comps), member_ids, st, actionable)
    if last_grade.get(zid, (None,))[0] == state:
        return
    previous = last_grade.get(zid, (None, None))[1]
    gid = sha_id("fg_", [zid, ctime(t.value), list(member_ids), actionable, st])
    grades.append({"grade_version_id": gid, "zone_id": zid, "available_at": t, "timeframe_rank": TF_RANK[zi["timeframe"]],
                   "overlap_contribution": len(comps), "partner_zone_ids": member_ids, "group_count": len(comps),
                   "normalization_status": zi["status"], "normalized_gap_strength": zi["strength"],
                   "strength_num": zi["num"], "strength_den": zi["den"], "original_width_ticks": zi["width"],
                   "stage": st, "current_direction": direction, "actionable": actionable, "supersedes": previous})
    for gi, g in enumerate(comps):
        groups.append((gid, zid, gi, _representative(g)["zone_id"], tuple(sorted(p["zone_id"] for p in g))))
    last_grade[zid] = (state, gid)


# ---------------------------------------------------------------------------
# Stage 3: BPR objects (independent lifecycle on the governing timeframe)
# ---------------------------------------------------------------------------


def bpr_objects(episodes: list[dict], tf_data: dict, tape: MinuteTape, *, instrument_id: str, tick: Decimal):
    seg_pos = {tf: d.segment_of_end() for tf, d in tf_data.items()}
    rows, transitions, mitigation = [], [], []
    for ep in episodes:
        if ep["label"] == FVG_OVERLAP:
            continue
        t_ns = ep["created_at"].value
        lo, up = ep["i_lower_ticks"], ep["i_upper_ticks"]
        bid = sha_id("fb_", [ep["relationship_id"]])
        tape_ep = tape.episodes[tape.locate(t_ns)[0]]
        exit_state = exit_ns = exit_reason = trigger = close = None
        if ep["direction"] != UNDEFINED:
            si, k = seg_pos[ep["governing_timeframe"]][t_ns]
            seg = tf_data[ep["governing_timeframe"]].segments[si]
            closes, ends = seg["c"][k + 1:], seg["end"][k + 1:]
            beyond = closes < lo if ep["direction"] == BULLISH else closes > up
            idx = np.flatnonzero(beyond)
            if len(idx):
                j = int(idx[0])
                exit_state, exit_ns, exit_reason, close = RETIRED, int(ends[j]), RETIRED, int(closes[j])
                at = pd.Timestamp(exit_ns, tz="UTC")
                trigger = bar_ref(instrument_id, ep["contract"], ep["governing_timeframe"], exit_ns)
        if exit_state is None and tape_ep.reset_at is not None:
            exit_state = TERMINATED if tape_ep.reset_reason == DATA_GAP else PENDING
            exit_ns, exit_reason = tape_ep.reset_at.value, tape_ep.reset_reason
            nxt = tape.episodes[tape_ep.index + 1].contract if tape_ep.index + 1 < len(tape.episodes) else None
            trigger = _reset_trigger(tape_ep, instrument_id, nxt)
        rows.append({"bpr_id": bid, "relationship_id": ep["relationship_id"], "label": ep["label"],
                     "direction": ep["direction"], "governing_timeframe": ep["governing_timeframe"],
                     "parent_a": ep["zone_a"], "stage_a": ep["stage_a"], "parent_b": ep["zone_b"],
                     "stage_b": ep["stage_b"], "lower_ticks": lo, "upper_ticks": up, "midpoint_half_ticks": lo + up,
                     "lower": float(Decimal(lo) * tick), "upper": float(Decimal(up) * tick),
                     "midpoint": float(Decimal(lo + up) * tick / 2), "width_ticks": up - lo,
                     "available_at": ep["created_at"], "exit_state": exit_state,
                     "exit_at": None if exit_ns is None else pd.Timestamp(exit_ns, tz="UTC"), "exit_reason": exit_reason,
                     "contract": ep["contract"], "basis_id": ep["basis_id"], "definition_version": FVG_DEFINITION_VERSION})
        if exit_state is not None:
            at = pd.Timestamp(exit_ns, tz="UTC")
            transitions.append({
                "transition_id": transition_id(namespace=NS_BPR, definition_version=FVG_DEFINITION_VERSION, entity_id=bid,
                                               previous_state=ACTIVE, new_state=exit_state, transition_at=at,
                                               trigger_ref=trigger, source_refs=()),
                "namespace": NS_BPR, "entity_id": bid, "previous_state": ACTIVE, "new_state": exit_state,
                "transition_at": at, "transition_seq_domain": None, "transition_seq": None, "available_at": at,
                "available_seq_domain": None, "available_seq": None, "instrument_id": instrument_id,
                "contract_scope": SPECIFIC, "contract": ep["contract"], "definition_version": FVG_DEFINITION_VERSION,
                "trigger_ref": trigger, "source_refs": (), "reason_code": exit_reason})
        if ep["direction"] != UNDEFINED:
            a = int(np.searchsorted(tape_ep.start, t_ns, side="left"))
            b = len(tape_ep.end) if exit_ns is None else int(np.searchsorted(tape_ep.end, exit_ns, side="right"))
            mitigation += mitigation_rows(bid, "BPR", "BPR", ep["direction"], lo, up, lo + up, tape_ep, a, b,
                                          instrument_id=instrument_id)
    return rows, transitions, mitigation


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _entities(rows) -> pd.DataFrame:
    out = pd.DataFrame(rows, columns=["entity_id", "available_at", "valid_from", "valid_until", "instrument_id",
                                      "contract_scope", "contract"])
    out["available_at"] = pd.to_datetime(out["available_at"], utc=True)
    for column in ("valid_from", "valid_until"):
        out[column] = pd.Series([pd.NaT] * len(out), dtype="datetime64[ns, UTC]")
    return out


TRANSITION_BASE = ["transition_id", "namespace", "entity_id", "previous_state", "new_state", "transition_at",
                   "transition_seq_domain", "transition_seq", "available_at", "available_seq_domain", "available_seq",
                   "instrument_id", "contract_scope", "contract", "definition_version", "trigger_ref", "source_refs",
                   "reason_code"]


def _transitions(rows, spec: StateNamespaceSpec, entities: pd.DataFrame, attrs=()) -> pd.DataFrame:
    columns = TRANSITION_BASE + [f"attr_{a.name}" for a in spec.attributes]
    tr = pd.DataFrame(rows, columns=columns)
    for column in ("transition_at", "available_at"):
        tr[column] = pd.to_datetime(tr[column], utc=True)
    for a in spec.attributes:
        tr[f"attr_{a.name}"] = tr[f"attr_{a.name}"].astype(a.dtype)
    if len(tr):
        tr = validate_transitions(tr, spec, entities)
    return tr


def run_engine(zones: pd.DataFrame, tf_data: dict, tape: MinuteTape, *, instrument_id: str,
               tick: Decimal) -> EngineResult:
    check_segments_within_episodes(tape, tf_data)
    stage_rows, zone_tr, mitigation, exits = zone_lifecycles(zones, tf_data, tape, instrument_id=instrument_id)
    episodes, grades, groups, info = relationships(zones, exits, instrument_id=instrument_id)
    bprs, bpr_tr, bpr_mit = bpr_objects(episodes, tf_data, tape, instrument_id=instrument_id, tick=tick)
    # episode M7A log
    ep_entities, ep_tr = [], []
    for ep in episodes:
        ep_entities.append({"entity_id": ep["relationship_id"], "available_at": ep["created_at"],
                            "valid_from": pd.NaT, "valid_until": pd.NaT, "instrument_id": instrument_id,
                            "contract_scope": SPECIFIC, "contract": ep["contract"]})
        if ep["ended_at"] is not None:
            trigger = SourceRef("FVG_EVENT", f"{ep['end_reason']}|{ep['relationship_id']}|"
                                             f"{ctime(ep['ended_at'].value)}").canonical
            ep_tr.append({"transition_id": transition_id(namespace=NS_OVERLAP, definition_version=FVG_DEFINITION_VERSION,
                                                         entity_id=ep["relationship_id"], previous_state=ACTIVE,
                                                         new_state=ENDED, transition_at=ep["ended_at"],
                                                         trigger_ref=trigger, source_refs=()),
                          "namespace": NS_OVERLAP, "entity_id": ep["relationship_id"], "previous_state": ACTIVE,
                          "new_state": ENDED, "transition_at": ep["ended_at"], "transition_seq_domain": None,
                          "transition_seq": None, "available_at": ep["ended_at"], "available_seq_domain": None,
                          "available_seq": None, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
                          "contract": ep["contract"], "definition_version": FVG_DEFINITION_VERSION,
                          "trigger_ref": trigger, "source_refs": (), "reason_code": ep["end_reason"]})
    zone_ent = _entities([{"entity_id": z.zone_id, "available_at": z.available_at, "valid_from": pd.NaT,
                           "valid_until": pd.NaT, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
                           "contract": z.contract} for z in zones.itertuples(index=False)])
    bpr_ent = _entities([{"entity_id": b["bpr_id"], "available_at": b["available_at"], "valid_from": pd.NaT,
                          "valid_until": pd.NaT, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
                          "contract": b["contract"]} for b in bprs])
    ep_ent = _entities(ep_entities)
    # data warnings and pending records
    warnings, pending = [], []
    for e in tape.episodes:
        if e.reset_at is None:
            continue
        n = sum(1 for x in exits.values() if x["episode"] == e.index and x["exit_kind"] in (TERMINATED, PENDING))
        if e.reset_reason == DATA_GAP:
            warnings.append({"at": e.reset_at, "reason": DATA_GAP, "reset_ref": e.reset_ref, "terminated_count": n,
                             "contract": e.contract})
    for zid, x in exits.items():
        if x["exit_kind"] == PENDING:
            pending.append({"object_id": zid, "object_kind": "ZONE", "contract": info[zid]["contract"],
                            "comparison_scope": "ALL_OTHER_BASIS_OBJECTS", "reason": BASIS_MISMATCH,
                            "since_at": pd.Timestamp(x["exit_ns"], tz="UTC")})
    for b in bprs:
        if b["exit_state"] == PENDING:
            pending.append({"object_id": b["bpr_id"], "object_kind": "BPR", "contract": b["contract"],
                            "comparison_scope": "ALL_OTHER_BASIS_OBJECTS", "reason": BASIS_MISMATCH,
                            "since_at": b["exit_at"]})
    mitigation += bpr_mit
    mit = pd.DataFrame(mitigation, columns=list(MITIGATION_COLUMNS))
    del mitigation, bpr_mit
    mit["at"] = pd.to_datetime(mit["at"].astype("int64"), utc=True) if len(mit) else pd.Series(dtype="datetime64[ns, UTC]")
    for column in ("penetration_depth_ticks", "in_zone_depth_ticks"):
        mit[column] = mit[column].astype("Int64")
    for column in ("object_kind", "stage", "kind", "observation_class", "contract", "basis_id"):
        mit[column] = mit[column].astype("category")
    if mit["event_id"].duplicated().any():
        raise FvgError("duplicate mitigation event id")
    return EngineResult(
        stages=frame(stage_rows, STAGE_COLUMNS),
        zone_transitions=_transitions(zone_tr, zone_namespace(), zone_ent), zone_entities=zone_ent,
        mitigation=mit, episodes=frame(episodes, EPISODE_COLUMNS),
        episode_transitions=_transitions(ep_tr, overlap_namespace(), ep_ent), episode_entities=ep_ent,
        bprs=frame(bprs, BPR_COLUMNS), bpr_transitions=_transitions(bpr_tr, bpr_namespace(), bpr_ent),
        bpr_entities=bpr_ent, grades=frame(grades, GRADE_COLUMNS), groups=pd.DataFrame(groups, columns=list(GROUP_COLUMNS)),
        warnings=frame(warnings, WARNING_COLUMNS), pending=frame(pending, PENDING_COLUMNS), zone_exits=exits)
