"""Internal Liquidity independent reference replay and invariants (IL-I4; D-143 - D-147).

The reference re-derives everything from the run's raw inputs (formation
atoms, frozen External tables, the canonical 1m bar arrays and §G.2a episode
boundaries) with its own code:

- External lineages from ``supersedes`` chains (not ``external_objects``);
- consumption by direct per-object numpy scans (``argmax`` over bar slices),
  not the sparse-table first-hit search;
- internal levels by a separate chronological pass;
- ranges / pinned assignments by a **per-bar** forward replay of §3.8
  (production is event-driven);
- membership by strict containment evaluated at sampled instants.

It shares only identity formulas (natural-key hashes) with production, so
ids can be compared.  ``reconcile`` returns per-category mismatch counts.
``internal_liquidity_invariants`` checks IL-INV-1 … IL-INV-20 directly on
the production outputs (IL-INV-15, prefix equivalence, is checked by the
runner through ``prefix_mismatches``).
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from src.data.continuity import continuity_segments
from src.data.timeframes import TimeframeSpec
from src.liquidity.consumption import sha_id
from src.liquidity.contract import EQ, EXTENDED, FORMED, LOWER, MERGED, REQ, UPPER
from src.liquidity.internal_formation import DEFINITION_VERSION
from src.liquidity.internal_liquidity import (
    GRADE_RANK,
    RANGE_DEFINITION_VERSION,
    consumption_namespace,
    range_namespace,
)
from src.state.contract import SPECIFIC, canonical_time, validate_transitions

INTERNAL_T, EXTERNAL_T = 4, 6
_CANDLE_KINDS = {"INTERNAL_CANDLE_HIGH", "INTERNAL_CANDLE_LOW"}


def _ticks(price, tick: Decimal) -> int:
    value = Decimal(str(price)) / tick
    if value != value.to_integral_value():
        raise AssertionError(f"price {price} is not tick aligned")
    return int(value)


def _ts(ns: int) -> pd.Timestamp:
    return pd.Timestamp(int(ns), tz="UTC")


class _Bars:
    """Plain bar arrays per episode, plus a bar-end index."""

    def __init__(self, tape):
        self.episodes = tape.episodes
        self.where = {}
        for e in tape.episodes:
            for pos, end in enumerate(e.bar_end):
                self.where[int(end)] = (e.index, pos)
        self.open_at = {}
        previous = None
        for e in tape.episodes:
            self.open_at[e.index] = None if previous is None or previous.reset_at is None else previous.reset_at.value
            previous = e

    def scan(self, episode, side, lo_ns, hi_ns, threshold):
        """First bar with start in [lo_ns, hi_ns) beyond ``threshold`` (direct slice scan)."""
        e = self.episodes[episode]
        lo = int(np.searchsorted(e.bar_start, lo_ns, side="left"))
        hi = len(e.bar_start) if hi_ns is None else int(np.searchsorted(e.bar_start, hi_ns, side="left"))
        if hi <= lo:
            return None
        hits = e.high[lo:hi] > threshold if side == UPPER else e.low[lo:hi] < threshold
        if not hits.any():
            return None
        return lo + int(np.argmax(hits))

    def outcome(self, episode, side, windows, stop_ns=None, stop_reason=None):
        """windows: [(start_ns, price, tol, ref)] prospective. Returns (end_ns, reason, ref, position)."""
        e = self.episodes[episode]
        for k, (start, price, tol, ref) in enumerate(windows):
            nxt = windows[k + 1][0] if k + 1 < len(windows) else None
            if stop_ns is not None:
                nxt = stop_ns if nxt is None else min(nxt, stop_ns)
            threshold = price + tol if side == UPPER else price - tol
            hit = self.scan(episode, side, start, nxt, threshold)
            if hit is not None:
                return int(e.bar_end[hit]), "CONSUMED", ref, hit
        if stop_ns is not None and (e.reset_at is None or stop_ns <= e.reset_at.value):
            return stop_ns, stop_reason, None, None
        if e.reset_at is not None:
            return e.reset_at.value, e.reset_reason, None, None
        return None, None, None, None


# ---------------------------------------------------------------------------
# Reference replay
# ---------------------------------------------------------------------------


def reference_internal_liquidity(run) -> dict:
    tick = Decimal(run.manifest["tick_size"])
    inst = run.manifest["instrument_id"]
    bars = _Bars(run.tape)
    ext = _reference_external(run, tick, bars)
    levels = _reference_levels(run, tick, bars, ext)
    ranges = _reference_ranges(run, bars, ext, inst)
    return {"external": ext, "levels": levels, **ranges}


def _reference_external(run, tick, bars) -> dict:
    members = run.external_members
    objects = {}
    member_info = {}
    for m in members.itertuples(index=False):
        member_info[m.member_id] = (_ticks(m.price, tick), pd.Timestamp(m.source_at).tz_convert("UTC").value)
        if m.member_kind in ("DAILY_HIGH", "DAILY_LOW"):
            side = UPPER if m.member_kind == "DAILY_HIGH" else LOWER
            t = pd.Timestamp(m.available_at).tz_convert("UTC").value
            objects[m.member_id] = {"id": m.member_id, "kind": "EXTERNAL_DAILY", "side": side, "contract": m.contract,
                                    "family": "1D", "versions": [(t, member_info[m.member_id][0], m.member_id,
                                                                  (m.member_id,))], "stop": None}
    structures = run.external_structures
    if structures is not None and len(structures):
        frame = structures.assign(ref_t=pd.to_datetime(structures["available_at"], utc=True)).sort_values(
            ["ref_t", "structure_id"])
        lineage = {}
        for s in frame.itertuples(index=False):
            prices = [member_info[x][0] for x in s.member_ids]
            if s.structure_type == REQ:
                price = max(prices) if s.orientation == UPPER else min(prices)
            else:
                price = prices[0]
            t = s.ref_t.value
            version = (t, price, s.structure_id, tuple(s.member_ids))
            if s.change_kind == EXTENDED:
                lid = lineage[s.supersedes[0]]
                objects[lid]["versions"].append(version)
            else:
                lid = sha_id("xc_", [s.structure_id])
                objects[lid] = {"id": lid, "kind": "EXTERNAL_CLUSTER", "side": s.orientation, "contract": s.contract,
                                "family": s.reference_family, "versions": [version], "stop": None}
                if s.change_kind == MERGED:
                    for old in {lineage[x] for x in s.supersedes}:
                        if objects[old]["stop"] is None:
                            objects[old]["stop"] = t
            lineage[s.structure_id] = lid
    for obj in objects.values():
        episode = bars.where[obj["versions"][0][0]][0]
        obj["episode"] = episode
        windows = [(t, p, EXTERNAL_T, ref) for t, p, ref, _ in obj["versions"]]
        end, reason, ref, _ = bars.outcome(episode, obj["side"], windows, obj["stop"], "MERGED")
        obj["end"], obj["reason"], obj["consumed_ref"] = end, reason, ref
    return {"objects": objects, "member_info": member_info}


def _reference_levels(run, tick, bars, ext) -> dict:
    f = run.formation
    events = []
    price_of = {}
    source_ref = {}
    if f.members is not None and len(f.members):
        for m in f.members.itertuples(index=False):
            price_of[m.member_id] = _ticks(m.price, tick)
            source_ref[m.member_id] = m.source_ref
            fam = "CANDLE" if m.member_kind in _CANDLE_KINDS else "SWING"
            events.append((pd.Timestamp(m.available_at).tz_convert("UTC").value, m.member_id, fam, m.reference_family,
                           m.orientation, price_of[m.member_id], m.contract, (m.member_id,), ()))
    if f.structures is not None and len(f.structures):
        for s in f.structures.itertuples(index=False):
            prices = [price_of[x] for x in s.member_ids]
            price = (max(prices) if s.orientation == UPPER else min(prices)) if s.structure_type == REQ else prices[0]
            source_ref[s.structure_id] = f"LIQUIDITY_STRUCTURE:{s.structure_id}"
            events.append((pd.Timestamp(s.available_at).tz_convert("UTC").value, s.structure_id, s.structure_type,
                           s.reference_family, s.orientation, price, s.contract, tuple(s.member_ids),
                           tuple(s.supersedes)))
    events.sort(key=lambda e: (e[0], e[1]))
    current = {}           # key -> level dict
    holder = {}            # evidence id -> level dict
    dead_atoms = {}        # key -> set
    levels = []
    versions = []
    spans = f.spans
    i = 0
    while i < len(events):
        t = events[i][0]
        batch = []
        while i < len(events) and events[i][0] == t:
            batch.append(events[i])
            i += 1
        for key in list(current):
            lv = current[key]
            if lv["end"] is not None and lv["end"] <= t:
                dead_atoms.setdefault(key, set()).update(a for e in lv["all"].values() for a in e[7])
                del current[key]
        touched = {}
        for ev in batch:
            for old in ev[8]:
                lv = holder.get(old)
                if lv is not None and current.get(lv["key"]) is lv and old in lv["active"]:
                    touched.setdefault(lv["key"], {"add": [], "drop": []})["drop"].append(old)
        episode = bars.where[t][0]
        opened = bars.open_at[episode]
        for ev in batch:
            if opened is not None and any(a in spans and spans[a][1] <= opened for a in ev[7]):
                continue
            touched.setdefault((ev[6], ev[4], ev[5]), {"add": [], "drop": []})["add"].append(ev)
        for key in sorted(touched):
            adds, drops = touched[key]["add"], touched[key]["drop"]
            lv = current.get(key)
            kind = None
            if lv is None:
                adds = [e for e in adds if not set(e[7]) <= dead_atoms.get(key, set())]
                if not adds:
                    continue
                first = adds[0]
                lid = sha_id("il_", [DEFINITION_VERSION, run.manifest["instrument_id"], SPECIFIC, key[0], key[1],
                                     int(key[2]), source_ref[first[1]]])
                threshold = key[2] + INTERNAL_T if key[1] == UPPER else key[2] - INTERNAL_T
                hit = bars.scan(episode, key[1], t, None, threshold)
                e = bars.episodes[episode]
                if hit is not None:
                    end, reason = int(e.bar_end[hit]), "CONSUMED"
                elif e.reset_at is not None:
                    end, reason = e.reset_at.value, e.reset_reason
                else:
                    end, reason = None, None
                lv = {"id": lid, "key": key, "start": t, "end": end, "reason": reason, "active": {}, "all": {},
                      "superseded": set(), "episode": episode}
                current[key] = lv
                levels.append(lv)
                kind = "CREATED"
            for e in adds:
                lv["active"][e[1]] = e
                lv["all"][e[1]] = e
                holder[e[1]] = lv
            for old in drops:
                lv["active"].pop(old)
                lv["superseded"].add(old)
            kind = kind or ("EVIDENCE_ADDED" if adds else "EVIDENCE_SUPERSEDED")
            rank = max(GRADE_RANK[(e[3], e[2])] for e in lv["active"].values()) if lv["active"] else 0
            vid = sha_id("iv_", [lv["id"], sorted(lv["active"]), sorted(lv["superseded"])])
            versions.append({"level_id": lv["id"], "level_version_id": vid, "change_kind": kind, "available_at": t,
                             "grade_rank": rank, "evidence": tuple(sorted(lv["active"]))})
    return {"levels": levels, "versions": versions}


def _reference_ranges(run, bars, ext, inst) -> dict:
    objects = ext["objects"]
    info = ext["member_info"]
    cands = [o for o in objects.values() if o["kind"] == "EXTERNAL_DAILY" or o["family"] == "4H"]
    by_episode = {}
    for o in cands:
        by_episode.setdefault(o["episode"], []).append(o)
    ranges, versions, assignments = [], [], []

    def eligible(pool, side, t):
        out = []
        for o in pool:
            if o["side"] != side or o["versions"][0][0] > t or (o["end"] is not None and o["end"] <= t):
                continue
            v = [x for x in o["versions"] if x[0] <= t][-1]
            sources = [info[m][1] for m in v[3]]
            opened = bars.open_at[o["episode"]]
            if opened is not None and any(s <= opened for s in sources):
                continue
            out.append((v[1], v[0], max(sources), o["id"], o, v))
        return out

    def closest(items, side, ref=None, beyond=None):
        if side == UPPER:
            pool = [x for x in items if (ref is None or x[0] >= ref) and (beyond is None or x[0] > beyond)]
            return min(pool, key=lambda x: (x[0], x[1], x[2], x[3]), default=None)
        pool = [x for x in items if (ref is None or x[0] <= ref) and (beyond is None or x[0] < beyond)]
        return min(pool, key=lambda x: (-x[0], x[1], x[2], x[3]), default=None)

    def assign(rng, side, pick, t, close, kind, replaces, contract):
        price, _, _, oid, o, v = pick
        threshold = price + EXTERNAL_T if side == UPPER else price - EXTERNAL_T
        a = {"boundary_assignment_id": sha_id("ba_", [rng["range_id"], side, oid, v[2], int(price), EXTERNAL_T,
                                                      canonical_time(_ts(t))]),
             "side": side, "external_object_id": oid, "pinned_formation_ref": v[2], "pinned_price_ticks": price,
             "pinned_threshold_ticks": threshold, "assigned_at": t, "selection_kind": kind,
             "replaces_assignment_id": replaces, "end": None, "reason": None}
        assignments.append(a)
        return a

    def version(rng, up, lo, t, kind):
        uid = up["boundary_assignment_id"] if up else "UNBOUNDED"
        vid = sha_id("rv_", [rng["range_id"], canonical_time(_ts(t)), uid, lo["boundary_assignment_id"]])
        versions.append({"range_id": rng["range_id"], "range_version_id": vid, "change_kind": kind, "available_at": t,
                         "upper_assignment_id": uid, "lower_assignment_id": lo["boundary_assignment_id"],
                         "upper": None if up is None else up["pinned_price_ticks"], "lower": lo["pinned_price_ticks"]})

    def end(a, t, reason):
        if a is not None and a["end"] is None:
            a["end"], a["reason"] = t, reason

    for e in bars.episodes:
        pool = by_episode.get(e.index, [])
        changes = sorted({v[0] for o in pool for v in o["versions"]} | {o["end"] for o in pool if o["end"] is not None})
        floor_cache = (np.iinfo(np.int64).max, 0, None)   # (valid_from, valid_until, min eligible lower price); stale
        rng, up, lo = None, None, None
        for m in range(len(e.bar_end)):
            t = int(e.bar_end[m])
            close = int(e.close[m])
            if rng is not None:
                hit_up = up is not None and int(e.high[m]) > up["pinned_threshold_ticks"]
                hit_lo = int(e.low[m]) < lo["pinned_threshold_ticks"]
                if hit_up or hit_lo:
                    if hit_up:
                        end(up, t, "CONSUMED")
                    if hit_lo:
                        end(lo, t, "CONSUMED")
                    new_lo = lo
                    if hit_lo:
                        pick = closest(eligible(pool, LOWER, t), LOWER, beyond=lo["pinned_price_ticks"])
                        if pick is None:
                            if not hit_up:
                                end(up, t, "RANGE_TERMINATED")
                            rng["end"], rng["reason"] = t, "INSUFFICIENT_BOUNDARY_DATA"
                            rng, up, lo = None, None, None
                        else:
                            new_lo = assign(rng, LOWER, pick, t, close, "ADVANCED_OUTWARD", lo["boundary_assignment_id"],
                                            e.contract)
                    if rng is not None:
                        kinds = []
                        new_up = up
                        if hit_up:
                            pick = closest(eligible(pool, UPPER, t), UPPER, beyond=up["pinned_price_ticks"])
                            new_up = None if pick is None else assign(rng, UPPER, pick, t, close, "ADVANCED_OUTWARD",
                                                                      up["boundary_assignment_id"], e.contract)
                            kinds.append("UPPER_ADVANCED")
                        if hit_lo:
                            kinds.append("LOWER_ADVANCED")
                        if hit_up and not hit_lo:
                            pick = closest(eligible(pool, LOWER, t), LOWER, ref=close)
                            if pick is not None and pick[0] > lo["pinned_price_ticks"]:
                                end(lo, t, "RELEASED")
                                new_lo = assign(rng, LOWER, pick, t, close, "OPPOSITE_RESELECTED",
                                                lo["boundary_assignment_id"], e.contract)
                                kinds.append("OPPOSITE_RESELECTED")
                        elif hit_lo and not hit_up:
                            pick = closest(eligible(pool, UPPER, t), UPPER, ref=close)
                            if pick is not None and (up is None or pick[0] < up["pinned_price_ticks"]):
                                end(up, t, "RELEASED")
                                new_up = assign(rng, UPPER, pick, t, close, "OPPOSITE_RESELECTED",
                                                None if up is None else up["boundary_assignment_id"], e.contract)
                                kinds.append("OPPOSITE_RESELECTED")
                        else:
                            kinds = ["BOTH_ADVANCED"]
                        up, lo = new_up, new_lo
                        version(rng, up, lo, t, "+".join(kinds))
                        continue
            if rng is None:
                if not (floor_cache[0] <= t and (floor_cache[1] is None or t < floor_cache[1])):
                    k = int(np.searchsorted(changes, t, side="right"))
                    nxt = changes[k] if k < len(changes) else None
                    prev = changes[k - 1] if k > 0 else -1
                    lows = eligible(pool, LOWER, t)
                    floor_cache = (prev, nxt, min(x[0] for x in lows) if lows else None)
                if floor_cache[2] is not None and floor_cache[2] <= close:
                    lowers = eligible(pool, LOWER, t)
                    rng = {"range_id": sha_id("ir_", [RANGE_DEFINITION_VERSION, run.manifest["instrument_id"], SPECIFIC,
                                                      e.contract, canonical_time(_ts(t))]),
                           "start": t, "end": None, "reason": None, "contract": e.contract}
                    ranges.append(rng)
                    pick_up = closest(eligible(pool, UPPER, t), UPPER, ref=close)
                    pick_lo = closest(lowers, LOWER, ref=close)
                    up = None if pick_up is None else assign(rng, UPPER, pick_up, t, close, "ESTABLISHED", None,
                                                             e.contract)
                    lo = assign(rng, LOWER, pick_lo, t, close, "ESTABLISHED", None, e.contract)
                    version(rng, up, lo, t, "ESTABLISHED")
        if e.reset_at is not None:
            if rng is not None:
                rng["end"], rng["reason"] = e.reset_at.value, e.reset_reason
            end(up, e.reset_at.value, e.reset_reason)
            end(lo, e.reset_at.value, e.reset_reason)
    return {"ranges": ranges, "range_versions": versions, "assignments": assignments}


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _outcomes(run) -> dict:
    tr = run.consumption_transitions
    return {r.entity_id: (r.transition_at.value, r.reason_code) for r in tr.itertuples(index=False)}


def reconcile(run, ref: dict, *, membership_samples: int = 400, seed: int = 7) -> pd.DataFrame:
    out = _outcomes(run)
    rows = []

    def add(category, expected, actual):
        expected, actual = set(expected), set(actual)
        rows.append({"category": category, "reference": len(expected), "production": len(actual),
                     "missing": len(expected - actual), "extra": len(actual - expected),
                     "example": next(iter(sorted(map(str, expected ^ actual))), "")[:200]})

    ext = ref["external"]["objects"]
    add("external_object_outcomes",
        [(o["id"], o["end"], o["reason"]) for o in ext.values()],
        [(oid, *out.get(oid, (None, None))) for oid in ext if oid in out or True])
    levels = ref["levels"]["levels"]
    add("levels", [(lv["id"], lv["start"], lv["end"], lv["reason"]) for lv in levels],
        [(r.level_id, r.level_available_at.value, *out.get(r.level_id, (None, None)))
         for r in run.levels.groupby("level_id").head(1).itertuples(index=False)])
    add("level_versions", [(v["level_version_id"], v["change_kind"], v["available_at"], v["grade_rank"])
                           for v in ref["levels"]["versions"]],
        [(r.level_version_id, r.change_kind, r.available_at.value, r.grade_rank) for r in run.levels.itertuples(index=False)])
    add("range_versions", [(v["range_version_id"], v["change_kind"], v["available_at"], v["upper_assignment_id"],
                            v["lower_assignment_id"]) for v in ref["range_versions"]],
        [(r.range_version_id, r.change_kind, r.available_at.value, r.upper_assignment_id, r.lower_assignment_id)
         for r in run.ranges.itertuples(index=False)] if len(run.ranges) else [])
    rtr = {r.entity_id: (r.transition_at.value, r.reason_code) for r in run.range_transitions.itertuples(index=False)}
    add("range_terminations", [(r["range_id"], r["end"], r["reason"]) for r in ref["ranges"]],
        [(rid, *rtr.get(rid, (None, None))) for rid in run.range_entities["entity_id"]])
    a = run.assignments
    add("assignments", [(x["boundary_assignment_id"], x["external_object_id"], x["pinned_formation_ref"],
                         x["pinned_price_ticks"], x["assigned_at"], x["selection_kind"], x["replaces_assignment_id"],
                         x["end"], x["reason"]) for x in ref["assignments"]],
        [(r.boundary_assignment_id, r.external_object_id, r.pinned_formation_ref, r.pinned_price_ticks,
          r.assigned_at.value, r.selection_kind, None if pd.isna(r.replaces_assignment_id) else r.replaces_assignment_id,
          *out.get(r.boundary_assignment_id, (None, None))) for r in a.itertuples(index=False)] if len(a) else [])
    # membership at sampled instants: every range-version instant, plus seeded samples of level-end instants and bars
    rng = np.random.default_rng(seed)
    instants = {v["available_at"] for v in ref["range_versions"]}
    level_ends = sorted({lv["end"] for lv in levels if lv["end"]})
    if level_ends:
        instants |= set(rng.choice(level_ends, size=min(membership_samples, len(level_ends)), replace=False).tolist())
    all_ends = np.concatenate([e.bar_end for e in run.tape.episodes]) if run.tape.episodes else np.array([], dtype=np.int64)
    if len(all_ends):
        instants |= set(rng.choice(all_ends, size=min(membership_samples, len(all_ends)), replace=False).tolist())
    lv_contract = np.array([lv["key"][0] for lv in levels], dtype=object)
    lv_price = np.array([lv["key"][2] for lv in levels], dtype=np.int64)
    lv_start = np.array([lv["start"] for lv in levels], dtype=np.int64)
    lv_end = np.array([lv["end"] if lv["end"] is not None else np.iinfo(np.int64).max for lv in levels], dtype=np.int64)
    lv_id = np.array([lv["id"] for lv in levels], dtype=object)
    rv = sorted(ref["range_versions"], key=lambda v: v["available_at"])
    rinfo = {r["range_id"]: r for r in ref["ranges"]}
    m = run.memberships
    if len(m):
        m_from = m["from_at"].map(lambda x: x.value).to_numpy(dtype=np.int64)
        m_until = np.array([np.iinfo(np.int64).max if pd.isna(x) else x.value for x in m["until_at"]], dtype=np.int64)
    expected, actual = [], []
    for t in sorted(int(x) for x in instants):
        current = {}
        for v in rv:
            if v["available_at"] > t:
                break
            end = rinfo[v["range_id"]]["end"]
            if end is None or end > t:
                current[v["range_id"]] = v
        for v in current.values():
            mask = (lv_contract == rinfo[v["range_id"]]["contract"]) & (lv_start <= t) & (lv_end > t) & (lv_price > v["lower"])
            if v["upper"] is not None:
                mask &= lv_price < v["upper"]
            expected.extend((t, v["range_id"], x) for x in lv_id[mask])
        if len(m):
            live = (m_from <= t) & (m_until > t)
            actual.extend((t, r, x) for r, x in zip(m["range_id"].to_numpy()[live], m["level_id"].to_numpy()[live]))
    add("membership_samples", expected, actual)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Invariants IL-INV-1 … IL-INV-20
# ---------------------------------------------------------------------------


def internal_liquidity_invariants(run, session_spec=None) -> pd.DataFrame:
    tick = Decimal(run.manifest["tick_size"])
    bars = _Bars(run.tape)
    results = []

    def record(name, checked, violations, detail=""):
        results.append({"invariant": name, "checked": int(checked), "violations": int(violations), "detail": detail})

    L, A, R = run.levels, run.assignments, run.ranges
    out = _outcomes(run)
    f = run.formation
    member_price = {}
    if f.members is not None and len(f.members):
        member_price = {m: _ticks(p, tick) for m, p in zip(f.members["member_id"], f.members["price"])}
    structures = f.structures.set_index("structure_id") if f.structures is not None and len(f.structures) else None

    # IL-INV-1: tick alignment and definitive prices
    bad = 0
    for r in L.itertuples(index=False):
        bad += Decimal(str(r.price)) != Decimal(r.price_ticks) * tick
        for mid in r.evidence_member_ids:
            bad += member_price[mid] != r.price_ticks
        for sid in r.evidence_structure_ids:
            s = structures.loc[sid]
            prices = [member_price[x] for x in s["member_ids"]]
            want = (max(prices) if s["orientation"] == UPPER else min(prices)) if s["structure_type"] == REQ else prices[0]
            bad += want != r.price_ticks
    record("IL-INV-1 definitive tick-aligned prices", len(L), bad)

    # IL-INV-2: one active level per (contract, side, price)
    first = L.groupby("level_id").head(1)
    bad = 0
    for _, g in first.groupby(["contract", "side", "price_ticks"]):
        spans = sorted((r.level_available_at.value, out.get(r.level_id, (np.iinfo(np.int64).max,))[0])
                       for r in g.itertuples(index=False))
        bad += sum(spans[k + 1][0] < spans[k][1] for k in range(len(spans) - 1))
    record("IL-INV-2 one active level per key", len(first), bad)

    # IL-INV-3: terminal ids never reappear
    ends = {k: v[0] for k, v in out.items()}
    bad = sum(r.level_id in ends and r.available_at.value >= ends[r.level_id] for r in L.itertuples(index=False))
    M = run.memberships
    if len(M):
        bad += sum(r.level_id in ends and (pd.isna(r.until_at) or r.until_at.value > ends[r.level_id])
                   for r in M.itertuples(index=False))
    if len(R):
        terminal_assign = {k: v for k, v in ends.items() if k.startswith("ba_")}
        for r in R.itertuples(index=False):
            for aid in (r.upper_assignment_id, r.lower_assignment_id):
                bad += aid in terminal_assign and terminal_assign[aid] < r.available_at.value
    record("IL-INV-3 terminal ids never reappear", len(L) + len(M) + len(R), bad)

    # IL-INV-4 / IL-INV-5 / IL-INV-6: consumption evidence re-check on the bar arrays
    ev = run.consumption_evidence
    tol = {"INTERNAL_LEVEL": INTERNAL_T, "EXTERNAL_DAILY": EXTERNAL_T, "EXTERNAL_CLUSTER": EXTERNAL_T,
           "BOUNDARY_ASSIGNMENT": EXTERNAL_T}
    avail = dict(zip(run.consumption_entities["entity_id"], run.consumption_entities["available_at"]))
    bad4 = bad5 = bad6 = checked = 0
    windows = _object_windows(run, tick)
    for r in ev.itertuples(index=False):
        bad6 += r.tolerance_ticks is not None and not pd.isna(r.tolerance_ticks) and r.tolerance_ticks != tol[r.object_kind]
        if r.status != "CONSUMED":
            continue
        checked += 1
        bad5 += r.excess_ticks <= 0 or r.ended_at <= avail[r.object_id]
        episode, pos = bars.where[r.ended_at.value]
        e = bars.episodes[episode]
        start = e.bar_start[pos]
        version = [w for w in windows[r.object_id] if w[0] <= start][-1]
        theta = version[1] + version[2] if r.side == UPPER else version[1] - version[2]
        beyond = e.high[pos] > theta if r.side == UPPER else e.low[pos] < theta
        bad4 += (not beyond) or version[3] != r.version_evaluated or theta != r.threshold_ticks
        # first hit: no earlier bar beyond its own start version since availability
        earlier = _first_hit(bars, episode, r.side, windows[r.object_id], upto=pos)
        bad4 += earlier is not None
    record("IL-INV-4 version at s(m), strict, first hit", checked, bad4)
    record("IL-INV-5 no excess-0 / no same-bar consumption", checked, bad5)
    bad6 += sum(r.tolerance_ticks != INTERNAL_T for r in L.itertuples(index=False))
    if len(A):
        bad6 += int((A["pinned_tolerance_ticks"] != EXTERNAL_T).sum())
    record("IL-INV-6 tolerances 4 / 6", len(ev) + len(L) + len(A), bad6)

    # IL-INV-7: P-1 (no extension / merge of a consumed cluster)
    bad, checked = _p1(run, out)
    record("IL-INV-7 P-1 no extension after consumption", checked, bad)

    # IL-INV-8: membership strictness / both active / not while insufficient
    bad = 0
    if len(M):
        lv_price = dict(zip(L["level_id"], L["price_ticks"]))
        lv_start = dict(zip(first["level_id"], first["level_available_at"]))
        rv = R.sort_values("available_at")
        for r in M.itertuples(index=False):
            p = lv_price[r.level_id]
            versions = rv[(rv["range_id"] == r.range_id) & (rv["available_at"] <= (r.until_at if not pd.isna(r.until_at)
                                                                                    else rv["available_at"].max()))]
            for v in versions.itertuples(index=False):
                if not pd.isna(r.until_at) and v.available_at >= r.until_at:
                    continue
                later = rv[(rv["range_id"] == r.range_id) & (rv["available_at"] > v.available_at)]
                v_end = later["available_at"].min() if len(later) else None
                if v_end is not None and v_end <= r.from_at:
                    continue
                upper = v.upper_pinned_price_ticks
                bad += not (p > v.lower_pinned_price_ticks and (pd.isna(upper) or p < upper))
            bad += r.from_at < lv_start[r.level_id]
            if r.level_id in ends:
                bad += pd.isna(r.until_at) or r.until_at.value > ends[r.level_id]
    record("IL-INV-8 strict membership", len(M), bad)

    # IL-INV-9: boundary selection = reference (counted by reconcile); here: candidate family and closeness at ESTABLISHED
    bad = 0
    if len(A):
        kinds = set(A["external_object_kind"])
        bad += len(kinds - {"EXTERNAL_DAILY", "EXTERNAL_CLUSTER"})
        fam = {x.obj.object_id: x.family for x in run.external_view}
        bad += sum(fam[o] not in ("1D", "4H") or (k == "EXTERNAL_CLUSTER" and fam[o] != "4H")
                   for o, k in zip(A["external_object_id"], A["external_object_kind"]))
        est = A[A["selection_kind"] == "ESTABLISHED"]
        bad += int(((est["side"] == UPPER) & (est["pinned_price_ticks"] < est["selection_close_ticks"])).sum())
        bad += int(((est["side"] == LOWER) & (est["pinned_price_ticks"] > est["selection_close_ticks"])).sum())
    record("IL-INV-9 boundary families and selection side", len(A), bad)

    # IL-INV-10: versions immutable and prospective
    bad = int(L["level_version_id"].duplicated().sum())
    for _, g in L.groupby("level_id"):
        bad += g["level_available_at"].nunique() != 1
        bad += not g["available_at"].is_monotonic_increasing or g["available_at"].duplicated().any()
        bad += g["available_at"].iloc[0] != g["level_available_at"].iloc[0]
    record("IL-INV-10 immutable prospective versions", len(L), bad)

    # IL-INV-11: confluence = distinct physical extremes (independent union-find over overlapping spans)
    bad = _confluence_check(run, member_price)
    record("IL-INV-11 confluence distinct extremes", len(L), bad)

    # IL-INV-12: contract isolation and reset timing
    bad = 0
    contract_of = dict(zip(first["level_id"], first["contract"]))
    if len(M):
        rc = dict(zip(R["range_id"], R["contract"]))
        bad += sum(contract_of[r.level_id] != rc[r.range_id] for r in M.itertuples(index=False))
    resets = {(e.reset_at.value, e.reset_reason) for e in run.tape.episodes if e.reset_at is not None}
    tr = run.consumption_transitions
    gap = tr[tr["reason_code"].isin(["DATA_GAP", "CONTRACT_CHANGE"])]
    bad += sum((t.value, why) not in resets for t, why in zip(gap["transition_at"], gap["reason_code"]))
    rt = run.range_transitions
    rgap = rt[rt["reason_code"].isin(["DATA_GAP", "CONTRACT_CHANGE"])]
    bad += sum((t.value, why) not in resets for t, why in zip(rgap["transition_at"], rgap["reason_code"]))
    if len(A):
        xc = {x.obj.object_id: x.obj.contract for x in run.external_view}
        bad += sum(xc[o] != c for o, c in zip(A["external_object_id"], A["contract"]))
    record("IL-INV-12 contract isolation / reset onsets", len(M) + len(gap) + len(rgap) + len(A), bad)

    # IL-INV-13: grade purity / ordering
    bad = 0
    member_family = {}
    if f.members is not None and len(f.members):
        member_family = {m: (tf, "CANDLE" if k in _CANDLE_KINDS else "SWING")
                         for m, tf, k in zip(f.members["member_id"], f.members["reference_family"], f.members["member_kind"])}
    structure_family = {} if structures is None else {
        sid: (tf, st) for sid, tf, st in zip(structures.index, structures["reference_family"], structures["structure_type"])}
    for r in L.itertuples(index=False):
        ids = list(r.evidence_member_ids) + list(r.evidence_structure_ids)
        ranks = []
        for x in ids:
            tf, fam = member_family[x] if x in member_family else structure_family[x]
            ranks.append((GRADE_RANK[(tf, fam)], tf, fam))
        best = max(ranks) if ranks else (0, None, None)
        bad += best[0] != r.grade_rank or (ranks and r.grade_tier != f"{best[1]} {best[2]}")
    record("IL-INV-13 grade tiers", len(L), bad)

    # IL-INV-14: M7A validity of both namespaces
    bad = 0
    try:
        validate_transitions(run.consumption_transitions.drop(columns=["run_id"]), consumption_namespace(),
                             run.consumption_entities)
        validate_transitions(run.range_transitions.drop(columns=["run_id"]), range_namespace(), run.range_entities)
    except Exception as exc:   # noqa: BLE001 — reported as a violation
        bad += 1
        detail = str(exc)[:200]
    else:
        detail = ""
    bad += int(tr["entity_id"].duplicated().sum()) + int(rt["entity_id"].duplicated().sum())
    record("IL-INV-14 M7A validity", len(tr) + len(rt), bad, detail)

    # IL-INV-16: internal EQ / REQ grammar (independent recomputation)
    bad, checked = _grammar_check(run, tick, session_spec)
    record("IL-INV-16 internal D-134 grammar (4-tick link)", checked, bad)

    # IL-INV-17: post-gap sources
    bad, checked = _post_gap_check(run, bars, member_price)
    record("IL-INV-17 post-gap sources only", checked, bad)

    # IL-INV-18: coincident objects keep separate statuses; External never consumed before coincident internal
    bad, checked = _price_record_check(run, out)
    record("IL-INV-18 price record separate statuses", checked, bad)

    # IL-INV-19 / IL-INV-20: assignments
    bad19, bad20, checked = _assignment_checks(run, out, bars, tick)
    record("IL-INV-19 boundary immutability", checked, bad19)
    record("IL-INV-20 assignment vs live cluster", checked, bad20)
    return pd.DataFrame(results)


def _object_windows(run, tick) -> dict:
    """object id -> [(start_ns, price_ticks, tol, version_ref)] from the production tables (for re-checks)."""
    windows = {}
    for r in run.levels.groupby("level_id").head(1).itertuples(index=False):
        windows[r.level_id] = [(r.level_available_at.value, r.price_ticks, INTERNAL_T, r.level_id)]
    for x in run.external_view:
        windows[x.obj.object_id] = [(v.available_at.value, v.price_ticks, v.tolerance_ticks, v.version_ref)
                                    for v in x.obj.versions]
    for r in run.assignments.itertuples(index=False):
        windows[r.boundary_assignment_id] = [(r.assigned_at.value, r.pinned_price_ticks, r.pinned_tolerance_ticks,
                                              r.pinned_formation_ref)]
    return windows


def _first_hit(bars, episode, side, windows, *, upto):
    e = bars.episodes[episode]
    for k, (start, price, tol, _) in enumerate(windows):
        nxt = windows[k + 1][0] if k + 1 < len(windows) else None
        hit = bars.scan(episode, side, start, nxt, price + tol if side == UPPER else price - tol)
        if hit is not None and hit < upto:
            return hit
    return None


def _p1(run, out):
    bad = checked = 0
    for x in run.external_view:
        end = out.get(x.obj.object_id)
        if end is None or end[1] != "CONSUMED":
            continue
        checked += 1
        bad += sum(v.available_at.value >= end[0] for v in x.obj.versions)
        merged = [y for y in run.external_view if x.obj.object_id in y.merged_from]
        bad += sum(y.obj.available_at.value >= end[0] for y in merged)
    # internal: a structure superseding a version that was evidence of a level consumed before it
    L = run.levels
    f = run.formation
    if f.structures is not None and len(f.structures):
        evidence_end = {}
        for r in L.groupby("level_id").tail(1).itertuples(index=False):
            e = out.get(r.level_id)
            if e is not None and e[1] == "CONSUMED":
                for sid in r.evidence_structure_ids:
                    evidence_end[sid] = e[0]
        for s in f.structures.itertuples(index=False):
            for old in s.supersedes:
                if old in evidence_end:
                    checked += 1
                    bad += pd.Timestamp(s.available_at).value > evidence_end[old]
    return bad, checked


def _confluence_check(run, member_price) -> int:
    spans = run.source_spans or run.formation.spans
    bad = 0
    view = run.external_view
    ext_member = {m: (p, s, fam) for m, p, s, fam in zip(
        run.external_members["member_id"],
        [round(float(x) / float(run.manifest["tick_size"])) for x in run.external_members["price"]],
        pd.to_datetime(run.external_members["source_at"], utc=True), run.external_members["reference_family"])} \
        if len(run.external_members) else {}
    out = _outcomes(run)
    s = run.formation.structures
    structure_members = {} if s is None or not len(s) else dict(zip(s["structure_id"], s["member_ids"]))
    by_key = {}
    for x in view:
        by_key.setdefault((x.obj.contract, x.obj.side), []).append(x)
    for r in run.levels.itertuples(index=False):
        t = r.available_at.value
        boxes = []
        for eid in list(r.evidence_member_ids) + list(r.evidence_structure_ids):
            atoms = (eid,) if eid in member_price else structure_members[eid]
            boxes.extend(spans[a][:2] for a in atoms if member_price.get(a) == r.price_ticks and a in spans)
        boxes = list(dict.fromkeys(boxes))
        coincident = []
        for x in by_key.get((r.contract, r.side), ()):
            if x.obj.available_at.value > t:
                continue
            e = out.get(x.obj.object_id)
            if e is not None and e[0] <= t:
                continue
            vs = [v for v in x.obj.versions if v.available_at.value <= t]
            if not vs or vs[-1].price_ticks != r.price_ticks:
                continue
            coincident.append(x.obj.object_id)
            for m in x.version_members.get(vs[-1].version_ref, ()):
                p, s, fam = ext_member[m]
                key = ("bar", fam, s.value)
                if p == r.price_ticks and key in spans:
                    boxes.append(spans[key][:2])
        # union-find over pairwise overlap
        parent = list(range(len(boxes)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if boxes[i][0] < boxes[j][1] and boxes[j][0] < boxes[i][1]:
                    parent[find(i)] = find(j)
        components = len({find(i) for i in range(len(boxes))})
        bad += components != r.confluence or tuple(sorted(coincident)) != tuple(r.external_coincidence)
    return bad


def _grammar_check(run, tick, session_spec):
    """Recompute internal EQ / REQ versions with a naive pairwise link search per segment."""
    f = run.formation
    if session_spec is None or not f.swings:
        return 0, 0
    produced = set()
    if f.structures is not None and len(f.structures):
        for s in f.structures.itertuples(index=False):
            produced.add((s.reference_family, s.orientation, s.structure_type, frozenset(s.member_ids),
                          pd.Timestamp(s.available_at).value, s.change_kind))
    members = f.members
    swing_member = {}
    if members is not None and len(members):
        sw = members[members["member_kind"].str.startswith("INTERNAL_SWING")]
        for r in sw.itertuples(index=False):
            swing_member[(r.reference_family, r.orientation, r.source_ref)] = r.member_id
    expected = set()
    for tf, swings in f.swings.items():
        obs = f.observations[tf]
        segments, _ = continuity_segments(obs, TimeframeSpec(tf, {"5m": 5, "15m": 15, "1H": 60}[tf]), session_spec)
        for seg in segments:
            seg = seg.reset_index(drop=True)
            ends = pd.to_datetime(seg["bar_end"], utc=True)
            pos = {t.value: k for k, t in enumerate(ends)}
            highs = np.array([_ticks(x, tick) for x in seg["high"]])
            lows = np.array([-_ticks(x, tick) for x in seg["low"]])
            for side, extremes in ((UPPER, highs), (LOWER, lows)):
                atoms = []
                for s in swings[swings["orientation"] == side].itertuples(index=False):
                    a = pos.get(pd.Timestamp(s.source_at).value)
                    b = pos.get(pd.Timestamp(s.source_end_at).value)
                    if a is None or b is None:
                        continue
                    value = _ticks(s.price, tick) * (1 if side == UPPER else -1)
                    atoms.append((pd.Timestamp(s.available_at).value, a, b, value, swing_member[(tf, side, s.source_ref)],
                                  _ticks(s.price, tick)))
                atoms.sort(key=lambda x: (x[0], x[1], x[4]))
                for stype, tol in ((EQ, 0), (REQ, 4)):
                    comp = {}
                    for j, aj in enumerate(atoms):
                        links = []
                        for i in range(j):
                            ai = atoms[i]
                            if abs(ai[3] - aj[3]) > tol:
                                continue
                            between = extremes[ai[2] + 1:aj[1]]
                            if len(between) and between.max() > max(ai[3], aj[3]):
                                continue
                            links.append(ai[4])
                        comp[aj[4]] = frozenset([aj[4]])
                        if not links:
                            continue
                        prior = {comp[x] for x in links}
                        merged = frozenset().union(*prior) | {aj[4]}
                        for x in merged:
                            comp[x] = merged
                        prices = {a[5] for a in atoms[:j + 1] if a[4] in merged}
                        if stype == REQ and len(prices) < 2:
                            continue
                        emitted_prior = {p for p in prior if len(p) > 1 and (stype == EQ or len(
                            {a[5] for a in atoms if a[4] in p}) > 1)}
                        kind = FORMED if not emitted_prior else (EXTENDED if len(emitted_prior) == 1 else MERGED)
                        expected.add((tf, side, stype, merged, aj[0], kind))
    return len(expected ^ produced), len(expected | produced)


def _post_gap_check(run, bars, member_price):
    bad = checked = 0
    spans = run.formation.spans
    structures = run.formation.structures.set_index("structure_id") if run.formation.structures is not None and len(
        run.formation.structures) else None
    for r in run.levels.itertuples(index=False):
        episode = bars.where[r.available_at.value][0]
        opened = bars.open_at[episode]
        if opened is None:
            continue
        checked += 1
        atoms = list(r.evidence_member_ids)
        for sid in r.evidence_structure_ids:
            atoms.extend(structures.loc[sid, "member_ids"])
        bad += any(a in spans and spans[a][1] <= opened for a in atoms)
    src = dict(zip(run.external_members["member_id"], pd.to_datetime(run.external_members["source_at"], utc=True))) \
        if len(run.external_members) else {}
    for r in run.assignments.itertuples(index=False):
        episode = bars.where[r.assigned_at.value][0]
        opened = bars.open_at[episode]
        if opened is None:
            continue
        checked += 1
        bad += any(src[m].value <= opened for m in r.pinned_member_ids)
    return bad, checked


def _price_record_check(run, out):
    links = run.price_record_links
    bad = checked = 0
    if links.empty:
        return 0, 0
    for _, g in links.groupby("price_record_id"):
        internal = g[g["object_kind"] == "INTERNAL_LEVEL"]
        external = g[g["object_kind"].isin(["EXTERNAL_DAILY", "EXTERNAL_CLUSTER"])]
        for x in external.itertuples(index=False):
            e = out.get(x.object_id)
            if e is None or e[1] != "CONSUMED" or x.unlink_reason != "CONSUMED":
                continue
            for lv in internal.itertuples(index=False):
                checked += 1
                active_then = lv.linked_from.value < e[0] and (pd.isna(lv.linked_until) or lv.linked_until.value >= e[0])
                if active_then:
                    le = out.get(lv.object_id)
                    bad += le is None or le[0] > e[0]
        thresholds = g.groupby("object_id")["tolerance_ticks"].nunique()
        bad += int((thresholds > 1).sum())
    return bad, checked


def _assignment_checks(run, out, bars, tick):
    A, R = run.assignments, run.ranges
    if A.empty:
        return 0, 0, 0
    bad19 = bad20 = 0
    bad19 += int(A["boundary_assignment_id"].duplicated().sum())
    a = A.set_index("boundary_assignment_id")
    for r in R.itertuples(index=False):
        if r.upper_assignment_id != "UNBOUNDED":
            bad19 += a.loc[r.upper_assignment_id, "pinned_price_ticks"] != r.upper_pinned_price_ticks
            bad19 += a.loc[r.upper_assignment_id, "pinned_threshold_ticks"] != r.upper_pinned_threshold_ticks
        bad19 += a.loc[r.lower_assignment_id, "pinned_price_ticks"] != r.lower_pinned_price_ticks
        bad19 += a.loc[r.lower_assignment_id, "pinned_threshold_ticks"] != r.lower_pinned_threshold_ticks
    consumed_at = {k: v[0] for k, v in out.items() if k.startswith("ba_") and v[1] == "CONSUMED"}
    for r in R.itertuples(index=False):
        if r.change_kind == "ESTABLISHED":
            continue
        bad19 += r.available_at.value not in set(consumed_at.values())
    for row in A.itertuples(index=False):
        bad19 += row.pinned_threshold_ticks != (row.pinned_price_ticks + row.pinned_tolerance_ticks if row.side == UPPER
                                                else row.pinned_price_ticks - row.pinned_tolerance_ticks)
    view = {x.obj.object_id: x for x in run.external_view}
    for row in A.itertuples(index=False):
        x = view[row.external_object_id]
        vs = [v for v in x.obj.versions if v.available_at <= row.assigned_at]
        bad20 += not vs or vs[-1].version_ref != row.pinned_formation_ref or vs[-1].price_ticks != row.pinned_price_ticks
        e = out.get(row.external_object_id)
        bad20 += e is not None and e[0] <= row.assigned_at.value
        if x.obj.object_kind == "EXTERNAL_CLUSTER" and e is not None and e[1] == "CONSUMED":
            ae = out.get(row.boundary_assignment_id)
            if row.assigned_at.value < e[0]:
                bad20 += ae is None or ae[0] > e[0]
    return bad19, bad20, len(A) + len(R)


# ---------------------------------------------------------------------------
# Prefix equivalence (IL-INV-15)
# ---------------------------------------------------------------------------


def prefix_mismatches(full, part) -> dict:
    """Facts of ``part`` (cutoff run) vs ``full`` restricted to the part's cutoff."""
    cut = part.tape.replay_cutoff
    out = {}
    for name, key, time in (("levels", "level_version_id", "available_at"), ("ranges", "range_version_id", "available_at"),
                            ("assignments", "boundary_assignment_id", "assigned_at"),
                            ("memberships", None, "from_at")):
        a, b = getattr(full, name), getattr(part, name)
        if name == "memberships":
            def ids(frame, limit):
                if frame.empty:
                    return set()
                rows = frame[frame["from_at"] <= limit]
                return {(r.range_id, r.level_id, r.from_at.value,
                         None if pd.isna(r.until_at) or r.until_at > limit else r.until_at.value) for r in rows.itertuples()}
            out[name] = len(ids(a, cut) ^ ids(b, cut))
            continue
        ea = set(a.loc[a[time] <= cut, key]) if len(a) else set()
        eb = set(b[key]) if len(b) else set()
        out[name] = len(ea ^ eb)
    ta, tb = full.consumption_transitions, part.consumption_transitions
    out["consumption_transitions"] = len(set(ta.loc[ta["transition_at"] <= cut, "transition_id"]) ^ set(tb["transition_id"]))
    ra, rb = full.range_transitions, part.range_transitions
    out["range_transitions"] = len(set(ra.loc[ra["transition_at"] <= cut, "transition_id"]) ^ set(rb["transition_id"])) \
        if len(ra) or len(rb) else 0
    return out


__all__ = ["reference_internal_liquidity", "reconcile", "internal_liquidity_invariants", "prefix_mismatches"]
