"""FVG independent reference replay, invariants and prefix comparison (FVG-I5).

The reference re-derives every checked fact with its own, deliberately naive
code: scalar triple predicates and true ranges, a per-bar replay of the 1m
tape and the timeframe closes (mitigation, conversion, retirement, resets),
an all-pairs relationship reassessment from the final state of each instant,
per-bar BPR retirement, union-find formation groups and a linear-scan swing
association.  It shares only frozen inputs (M3 / continuity segments, the
§G.2a 1m episodes, frozen swing points) and identity formulas with
production, so ids can be compared.

Everything is confined to one 1m episode (every object ends at its episode's
reset), so a reference restricted to a subset of episodes is an exact
restriction of the full run.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pandas as pd

from src.fvg.formation import BASELINE_N, FVG_DEFINITION_VERSION, TF_RANK, bar_ref, raw_basis, sha_id
from src.state.contract import SPECIFIC, validate_transitions

BULL, BEAR = "BULLISH", "BEARISH"


def _opp(d):
    return BEAR if d == BULL else BULL


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------


def reference(run, episodes=None) -> dict:
    """Naive replay over the 1m episodes ``episodes`` (all when None)."""
    inst = run.manifest["instrument_id"]
    tape = run.tape
    eps = list(range(len(tape.episodes))) if episodes is None else sorted(episodes)
    keep = set(eps)
    zones, rejections = _ref_formation(run, inst, keep)
    lifecycle = _ref_replay(run, zones, keep, inst)
    assoc = _ref_association(run, zones, lifecycle)
    return {"zones": zones, "rejections": rejections, **lifecycle, "associations": assoc, "episodes_checked": eps}


def _ref_formation(run, inst, keep):
    zones, rejections = [], []
    for tf, data in run.tf_data.items():
        for si, seg in enumerate(data.segments):
            n = len(seg["end"])
            for k in range(2, n):
                loc = run.tape.locate(int(seg["end"][k]))
                if loc is None or loc[0] not in keep:
                    continue
                o2, c2 = int(seg["o"][k - 1]), int(seg["c"][k - 1])
                h1, l1, h3, l3 = int(seg["h"][k - 2]), int(seg["l"][k - 2]), int(seg["h"][k]), int(seg["l"][k])
                if l3 > h1:
                    d, lo, up, ok_dir, ok_span = BULL, h1, l3, c2 > o2, o2 <= h1 and c2 >= l3
                elif h3 < l1:
                    d, lo, up, ok_dir, ok_span = BEAR, h3, l1, c2 < o2, o2 >= l1 and c2 <= h3
                else:
                    continue
                tref = bar_ref(inst, seg["contract"], tf, int(seg["end"][k - 2]), int(seg["end"][k]))
                if not ok_dir or not ok_span:
                    rejections.append((tf, tref, "C2_NOT_DIRECTIONAL" if not ok_dir else "C2_BODY_NOT_SPANNING"))
                    continue
                k1 = k - 2
                trs = []
                for j in range(k1 - BASELINE_N, k1):
                    if j < 1:
                        trs = None
                        break
                    pc = int(seg["c"][j - 1])
                    trs.append(max(int(seg["h"][j]) - int(seg["l"][j]), abs(int(seg["h"][j]) - pc), abs(int(seg["l"][j]) - pc)))
                if trs is None:
                    status, strength = "INSUFFICIENT_HISTORY", None
                elif sum(trs) == 0:
                    status, strength = "ZERO_BASELINE", None
                else:
                    status, strength = "OK", Fraction(up - lo) / Fraction(sum(trs), BASELINE_N)
                zid = sha_id("fz_", [FVG_DEFINITION_VERSION, inst, SPECIFIC, seg["contract"], tf, d, tref])
                zones.append({"zone_id": zid, "tf": tf, "dir": d, "lo": lo, "up": up, "status": status,
                              "strength": strength, "avail": int(seg["end"][k]), "c1": int(seg["end"][k - 2]),
                              "c2": int(seg["end"][k - 1]), "span": (int(seg["start"][k - 2]), int(seg["end"][k])),
                              "contract": seg["contract"], "seg": si, "k3": k, "episode": loc[0]})
    return zones, rejections


def _ref_replay(run, zones, keep, inst):
    """Per-bar replay: mitigation (stage at bar start), closes, resets, episodes, BPRs, groups."""
    tape = run.tape
    tf_close = {}                     # (tf, end_ns) -> (start_ns, close)
    for tf, data in run.tf_data.items():
        for seg in data.segments:
            for k in range(len(seg["end"])):
                tf_close[(tf, int(seg["end"][k]))] = (int(seg["start"][k]), int(seg["c"][k]))
    by_avail = {}
    for z in zones:
        by_avail.setdefault(z["avail"], []).append(z)
    out = {"transitions": [], "mitigation": [], "episodes": [], "bprs": [], "grades": []}
    for ei in sorted(keep):
        ep = tape.episodes[ei]
        state = {}                    # zone_id -> dict(stage, dir, start, marks, maxdepth)
        bstate = {}                   # bpr_id -> dict
        open_ep = {}                  # pair -> episode
        partners_last = {}
        instants = sorted(set(int(x) for x in ep.end) | {a for a in by_avail if any(z["episode"] == ei for z in by_avail[a])})
        for t in instants:
            pos = int(np.searchsorted(ep.end, t))
            bar = (int(ep.start[pos]), int(ep.l[pos]), int(ep.h[pos])) if pos < len(ep.end) and int(ep.end[pos]) == t else None
            movers, exited = set(), {}
            # (a) mitigation, stage at bar start
            if bar is not None:
                for zid, s in state.items():
                    if s["stage"] in ("FVG", "IFVG") and bar[0] >= s["start"]:
                        _ref_mitigate(out, zid, "ZONE", s["stage"], s, bar[1], bar[2], t)
                for bid, b in bstate.items():
                    if b["active"] and b["dir"] != "UNDEFINED" and bar[0] >= b["avail"]:
                        _ref_mitigate(out, bid, "BPR", "BPR", b, bar[1], bar[2], t)
            # (b) closes
            for zid, s in list(state.items()):
                if s["stage"] not in ("FVG", "IFVG"):
                    continue
                key = (s["tf"], t)
                if key not in tf_close or tf_close[key][0] < s["start"]:
                    continue
                c = tf_close[key][1]
                beyond = c < s["lo"] if s["dir"] == BULL else c > s["up"]
                if beyond:
                    if s["stage"] == "FVG":
                        s.update(stage="IFVG", dir=_opp(s["dir"]), start=t, marks=set(), maxdepth=None)
                        out["transitions"].append((zid, "IFVG", t))
                        movers.add(zid)
                    else:
                        s["stage"] = "RETIRED"
                        out["transitions"].append((zid, "RETIRED", t))
                        exited[zid] = "PARENT_RETIRED"
            for bid, b in bstate.items():
                if not b["active"] or b["dir"] == "UNDEFINED":
                    continue
                key = (b["tf"], t)
                if key in tf_close and tf_close[key][0] >= b["avail"]:
                    c = tf_close[key][1]
                    if (b["dir"] == BULL and c < b["lo"]) or (b["dir"] == BEAR and c > b["up"]):
                        b["active"] = False
                        out["bprs"].append((bid, "RETIRED", t))
            # (c) admissions
            for z in by_avail.get(t, []):
                if z["episode"] != ei:
                    continue
                state[z["zone_id"]] = {"stage": "FVG", "dir": z["dir"], "start": t, "lo": z["lo"], "up": z["up"],
                                       "mid2": z["lo"] + z["up"], "tf": z["tf"], "marks": set(), "maxdepth": None,
                                       "z": z}
                movers.add(z["zone_id"])
            # (d) all-pairs reassessment from the final state (only instants where some object changed)
            if not movers and not exited:
                continue
            act = sorted(zid for zid, s in state.items() if s["stage"] in ("FVG", "IFVG"))
            for key in list(open_ep):
                if key[0] in exited or key[1] in exited:
                    e = open_ep.pop(key)
                    e["ended"], e["reason"] = t, exited.get(key[0], exited.get(key[1]))
            for i in range(len(act)):
                for j in range(i + 1, len(act)):
                    a, b = act[i], act[j]
                    sa, sb = state[a], state[b]
                    lo, up = max(sa["lo"], sb["lo"]), min(sa["up"], sb["up"])
                    if up - lo < 1:
                        continue
                    stages = (sa["stage"], sb["stage"])
                    old = open_ep.get((a, b))
                    if old is not None and old["stages"] == stages:
                        continue
                    if old is not None:
                        old["ended"], old["reason"] = t, "PARENT_STAGE_CHANGED"
                    mv = [x for x in (a, b) if x in movers]
                    if sa["dir"] == sb["dir"]:
                        label, d, gov = "FVG_OVERLAP", sa["dir"], None
                    else:
                        label = "BPR" if sa["tf"] == sb["tf"] else "MTF_BPR"
                        d, gov = (state[mv[0]]["dir"], state[mv[0]]["tf"]) if len(mv) == 1 else ("UNDEFINED", None)
                    rid = sha_id("fo_", [FVG_DEFINITION_VERSION, raw_basis(sa["z"]["contract"]), [a, stages[0]],
                                         [b, stages[1]]])
                    e = {"rid": rid, "pair": (a, b), "stages": stages, "label": label, "dir": d, "gov": gov,
                         "created": t, "ended": None, "reason": None, "lo": lo, "up": up}
                    open_ep[(a, b)] = e
                    out["episodes"].append(e)
                    if label != "FVG_OVERLAP":
                        bid = sha_id("fb_", [rid])
                        bstate[bid] = {"active": True, "dir": d, "tf": gov, "avail": t, "lo": lo, "up": up,
                                       "mid2": lo + up, "marks": set(), "maxdepth": None}
            # grades: partners = open FVG_OVERLAP episodes (full recomputation)
            partner_map = {}
            for e in open_ep.values():
                if e["label"] == "FVG_OVERLAP":
                    a, b = e["pair"]
                    partner_map.setdefault(a, []).append(b)
                    partner_map.setdefault(b, []).append(a)
            for zid in sorted(state):
                s = state[zid]
                actionable = s["stage"] in ("FVG", "IFVG")
                if not actionable and partners_last.get(zid, (None, None, None, False))[3] is False and zid not in exited                         and partners_last.get(zid) is not None:
                    continue
                parts = sorted(partner_map.get(zid, [])) if actionable else []
                comps = _ref_components([state[p]["z"]["span"] for p in parts])
                snap = (comps, tuple(parts), s["stage"], actionable)
                if partners_last.get(zid) != snap:
                    partners_last[zid] = snap
                    out["grades"].append((zid, t, comps, tuple(parts), s["stage"]))
        # reset
        if ep.reset_at is not None:
            t = ep.reset_at.value
            kind = "TERMINATED" if ep.reset_reason == "DATA_GAP" else "PENDING_ADJUSTMENT"
            for zid, s in state.items():
                if s["stage"] in ("FVG", "IFVG"):
                    out["transitions"].append((zid, kind, t))
                    out["grades"].append((zid, t, 0, (), kind))
            for bid, b in bstate.items():
                if b["active"]:
                    out["bprs"].append((bid, kind, t))
            reason = "PARENT_TERMINATED" if kind == "TERMINATED" else "PARENT_PENDING"
            for e in open_ep.values():
                e["ended"], e["reason"] = t, reason
    return out


def _ref_mitigate(out, oid, kind, stage, s, l, h, t):
    lo, up, mid2, d = s["lo"], s["up"], s["mid2"], s["dir"]
    if d == BULL:
        trade, beyond, depth = l < up and h >= lo, h < lo, up - l
        mid, full = 2 * l <= mid2, l <= lo
    else:
        trade, beyond, depth = h > lo and l <= up, l > up, h - lo
        mid, full = 2 * h >= mid2, h >= up
    marks = s["marks"]
    if beyond and "PENETRATION" not in marks and "GAP_THROUGH" not in marks:
        marks.add("GAP_THROUGH")
        out["mitigation"].append((oid, stage, "GAP_THROUGH", t, None))
    if not trade:
        return
    for name, ok in (("PENETRATION", True), ("MIDPOINT", mid), ("FULL", full)):
        if ok and name not in marks:
            marks.add(name)
            out["mitigation"].append((oid, stage, name, t, depth))
    if s["maxdepth"] is None or depth > s["maxdepth"]:
        s["maxdepth"] = depth
        out["mitigation"].append((oid, stage, "DEPTH", t, depth))


def _ref_components(spans):
    n = len(spans)
    parent = list(range(n))

    def f(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for i in range(n):
        for j in range(n):
            if i < j and spans[i][0] < spans[j][1] and spans[j][0] < spans[i][1]:
                parent[f(i)] = f(j)
    return len({f(i) for i in range(n)})


def _ref_association(run, zones, lifecycle):
    out = []
    conv = {}
    for zid, kind, t in lifecycle["transitions"]:
        conv.setdefault(zid, t)
    tick_vals = {}
    for tf, sw in run.swings.items():
        if sw is None or sw.empty:
            continue
        from src.market_structure.swing_breaks import price_ticks
        from decimal import Decimal
        px = price_ticks(sw["price"].to_numpy(), Decimal(run.manifest["tick_size"]))
        tick_vals[tf] = [{"id": r.swing_id, "o": r.orientation, "px": int(p),
                          "src": pd.Timestamp(r.source_at).value, "src_end": pd.Timestamp(r.source_end_at).value,
                          "av": pd.Timestamp(r.available_at).value} for r, p in zip(sw.itertuples(), px)]
    firsts = set()
    for z in sorted(zones, key=lambda z: (z["avail"], z["c2"], z["zone_id"])):
        data = run.tf_data[z["tf"]].segments[z["seg"]]
        seg_lo, seg_hi = int(data["start"][0]), int(data["end"][-1])
        sws = [s for s in tick_vals.get(z["tf"], []) if seg_lo < s["src"] <= seg_hi]
        own, opp = ("LOWER", "UPPER") if z["dir"] == BULL else ("UPPER", "LOWER")
        a = z["c2"]
        opps = [s for s in sws if s["o"] == opp and s["src_end"] < a]
        since = max((s["src_end"] for s in opps), default=None)
        cands = [s for s in sws if s["o"] == own and s["src"] <= a and (since is None or s["src"] > since)]
        if not cands:
            continue
        origin = min(cands, key=(lambda s: (s["px"], s["src"])) if own == "LOWER" else (lambda s: (-s["px"], s["src"])))
        k2 = z["k3"] - 1
        vals = data["l"] if z["dir"] == BULL else data["h"]
        j = k2
        while j > 0 and vals[j - 1] == vals[k2]:
            j -= 1
        qualified = j >= 2 and all((vals[x] >= vals[k2]) if z["dir"] == BULL else (vals[x] <= vals[k2]) for x in (j - 2, j - 1))
        if qualified:
            if k2 + 2 >= len(data["end"]):
                continue
            deadline = int(data["end"][k2 + 2])
        else:
            deadline = z["avail"]
        at = max(z["avail"], origin["av"], deadline)
        first = (z["dir"], origin["id"]) not in firsts
        firsts.add((z["dir"], origin["id"]))
        out.append((z["zone_id"], origin["id"], first, at))
    return out


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile(run, ref) -> pd.DataFrame:
    keep = set(ref["episodes_checked"])
    zone_ep = {}
    for z in run.zones.itertuples(index=False):
        loc = run.tape.locate(z.available_at.value)
        zone_ep[z.zone_id] = loc[0] if loc else None
    in_scope = {zid for zid, e in zone_ep.items() if e in keep}
    Z = run.zones[run.zones["zone_id"].isin(in_scope)]
    rows = []

    def add(cat, expected, actual):
        expected, actual = set(expected), set(actual)
        rows.append({"category": cat, "reference": len(expected), "production": len(actual),
                     "missing": len(expected - actual), "extra": len(actual - expected)})
    add("zones", [(z["zone_id"], z["lo"], z["up"], z["status"], None if z["strength"] is None else str(z["strength"]))
                  for z in ref["zones"]],
        [(r.zone_id, r.lower_ticks, r.upper_ticks, r.normalization_status,
          None if pd.isna(r.strength_num) else str(Fraction(int(r.strength_num), int(r.strength_den))))
         for r in Z.itertuples(index=False)])
    rej = run.rejections
    add("rejections", ref["rejections"], [(r.timeframe, r.triple_ref, r.reason) for r in rej.itertuples(index=False)
                                          if run.tape.locate(r.c3_end.value) and run.tape.locate(r.c3_end.value)[0] in keep])
    tr = run.engine.zone_transitions
    add("zone_transitions", ref["transitions"],
        [(r.entity_id, r.new_state, r.transition_at.value) for r in tr.itertuples(index=False) if r.entity_id in in_scope])
    m = run.engine.mitigation
    bpr_scope = set()
    b = run.engine.bprs
    for r in b.itertuples(index=False):
        loc = run.tape.locate(r.available_at.value)
        if loc and loc[0] in keep:
            bpr_scope.add(r.bpr_id)
    add("mitigation", ref["mitigation"],
        [(r.object_id, r.stage, r.kind, r.at.value, None if pd.isna(r.penetration_depth_ticks) or r.kind == "GAP_THROUGH"
          else int(r.penetration_depth_ticks)) for r in m.itertuples(index=False)
         if r.object_id in in_scope or r.object_id in bpr_scope])
    e = run.engine.episodes
    e = e[e["zone_a"].isin(in_scope)]
    add("episodes", [(x["rid"], x["label"], x["dir"], x["gov"], x["created"], x["ended"], x["reason"]) for x in ref["episodes"]],
        [(r.relationship_id, r.label, r.direction, None if pd.isna(r.governing_timeframe) else r.governing_timeframe,
          r.created_at.value, None if pd.isna(r.ended_at) else r.ended_at.value,
          None if pd.isna(r.end_reason) else r.end_reason) for r in e.itertuples(index=False)])
    btr = run.engine.bpr_transitions
    add("bpr_exits", ref["bprs"], [(r.entity_id, r.new_state, r.transition_at.value) for r in btr.itertuples(index=False)
                                   if r.entity_id in bpr_scope])
    g = run.engine.grades
    add("grades", [(zid, t, c, parts, st) for zid, t, c, parts, st in ref["grades"]],
        [(r.zone_id, r.available_at.value, int(r.overlap_contribution), tuple(r.partner_zone_ids), r.stage)
         for r in g.itertuples(index=False) if r.zone_id in in_scope])
    a = run.associations
    add("associations", ref["associations"],
        [(r.zone_id, r.leg_origin_swing_id, bool(r.is_first), r.association_available_at.value)
         for r in a.itertuples(index=False) if r.zone_id in in_scope])
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Invariants (FVG-INV-1 … FVG-INV-27; FVG-INV-21 = prefix, FVG-INV-25 = unit tests)
# ---------------------------------------------------------------------------


def invariants(run) -> pd.DataFrame:
    res = []

    def rec(name, checked, bad):
        res.append({"invariant": name, "checked": int(checked), "violations": int(bad)})
    Z, E = run.zones, run.engine
    seg_pos = {tf: d.segment_of_end() for tf, d in run.tf_data.items()}
    bad = 0
    for z in Z.itertuples(index=False):
        si, k3 = seg_pos[z.timeframe][z.available_at.value]
        seg = run.tf_data[z.timeframe].segments[si]
        ok = (k3 >= 2 and int(seg["end"][k3 - 2]) == z.c1_end.value and int(seg["end"][k3 - 1]) == z.c2_end.value
              and seg["contract"] == z.contract)
        if z.original_direction == BULL:
            ok &= z.lower_ticks == int(seg["h"][k3 - 2]) and z.upper_ticks == int(seg["l"][k3])
            ok &= int(seg["c"][k3 - 1]) > int(seg["o"][k3 - 1]) and int(seg["o"][k3 - 1]) <= z.lower_ticks \
                and int(seg["c"][k3 - 1]) >= z.upper_ticks
        else:
            ok &= z.lower_ticks == int(seg["h"][k3]) and z.upper_ticks == int(seg["l"][k3 - 2])
            ok &= int(seg["c"][k3 - 1]) < int(seg["o"][k3 - 1]) and int(seg["o"][k3 - 1]) >= z.upper_ticks \
                and int(seg["c"][k3 - 1]) <= z.lower_ticks
        ok &= z.width_ticks >= 1 and z.midpoint_half_ticks == z.lower_ticks + z.upper_ticks
        bad += not ok
    rec("FVG-INV-1/2/5 consecutive complete triple, wick bounds, C2 rule, width, exact midpoint", len(Z), bad)
    first_event = E.mitigation.groupby("object_id")["at"].min()
    av = dict(zip(Z["zone_id"], Z["available_at"]))
    bad = sum(1 for oid, t in first_event.items() if oid in av and t <= av[oid])
    bad += sum(1 for r in E.zone_transitions.itertuples(index=False) if r.transition_at <= av[r.entity_id])
    rec("FVG-INV-3 nothing at or before availability", len(Z), bad)
    rec("FVG-INV-4 unique ids", len(Z) + len(E.episodes) + len(E.bprs) + len(E.mitigation),
        Z["zone_id"].duplicated().sum() + E.episodes["relationship_id"].duplicated().sum()
        + E.bprs["bpr_id"].duplicated().sum() + E.mitigation["event_id"].duplicated().sum())
    # 6 / 7 / 11 / 12 (vectorized)
    zinfo = Z.set_index("zone_id")
    mz = E.mitigation[E.mitigation["object_kind"].astype(str) == "ZONE"].copy()
    mz["stage"] = mz["stage"].astype(str)
    st = E.stages[["zone_id", "stage", "current_direction", "stage_start"]]
    mz = mz.merge(st, left_on=["object_id", "stage"], right_on=["zone_id", "stage"], how="left")
    zz = Z[["zone_id", "lower_ticks", "upper_ticks", "contract"]].rename(columns={"contract": "zone_contract"})
    mz = mz.merge(zz, left_on="object_id", right_on="zone_id", how="left", suffixes=("", "_z"))
    bull = (mz["current_direction"] == BULL).to_numpy()
    lo_, up_ = mz["lower_ticks"].to_numpy(), mz["upper_ticks"].to_numpy()
    l_, h_ = mz["bar_low_ticks"].to_numpy(), mz["bar_high_ticks"].to_numpy()
    trade = np.where(bull, (l_ < up_) & (h_ >= lo_), (h_ > lo_) & (l_ <= up_))
    beyond = np.where(bull, h_ < lo_, l_ > up_)
    gap = (mz["kind"].astype(str) == "GAP_THROUGH").to_numpy()
    bad6 = int(np.sum(np.where(gap, ~beyond, ~trade)))
    bad11 = int(((mz["at"] - pd.Timedelta(minutes=1)) < mz["stage_start"]).sum())
    bad12 = int((mz["contract"].astype(str) != mz["zone_contract"].astype(str)).sum())
    firsts = mz.groupby(["object_id", "stage", mz["kind"].astype(str)])["at"].min().unstack()
    bad7 = 0
    if len(firsts):
        for a_, b_ in (("PENETRATION", "MIDPOINT"), ("MIDPOINT", "FULL")):
            if a_ in firsts and b_ in firsts:
                bad7 += int((firsts[b_] < firsts[a_]).sum())
        if "GAP_THROUGH" in firsts and "PENETRATION" in firsts:
            bad7 += int((firsts["GAP_THROUGH"] > firsts["PENETRATION"]).sum())
    dep = mz[mz["kind"].astype(str) == "DEPTH"].sort_values(["object_id", "stage", "at"])
    if len(dep):
        same = (dep["object_id"].to_numpy()[1:] == dep["object_id"].to_numpy()[:-1]) &                (dep["stage"].to_numpy()[1:] == dep["stage"].to_numpy()[:-1])
        d = dep["penetration_depth_ticks"].astype("int64").to_numpy()
        bad7 += int((same & (d[1:] <= d[:-1])).sum())
    rec("FVG-INV-6 milestones only from zone trades; gap-through only from beyond bars", len(mz), bad6)
    rec("FVG-INV-7 milestone order, depth growth, gap-through before first trade", len(mz), bad7)
    rec("FVG-INV-11 no stage evidence from bars starting before the stage", len(mz), bad11)
    rec("FVG-INV-12 basis: evidence bars share the object's contract", len(mz), bad12)
    # 8 / 18 / 19 (vectorized)
    g = E.grades
    gw = g["zone_id"].map(zinfo["width_ticks"])
    bad = int((g["original_width_ticks"] != gw).sum()) + int((g["overlap_contribution"] != g["group_count"]).sum())
    gs = g["zone_id"].map(zinfo["normalization_status"])
    bad += int((g["normalization_status"] != gs).sum())
    rec("FVG-INV-8/18/19 grade components consistent with immutable facts", len(g), bad)
    # 9 / 10 / 27
    bad9 = 0
    tr = E.zone_transitions
    for r in tr.itertuples(index=False):
        if r.reason_code in ("CONVERTED", "RETIRED"):
            z = zinfo.loc[r.entity_id]
            si, k = seg_pos[z["timeframe"]][r.transition_at.value]
            c = int(run.tf_data[z["timeframe"]].segments[si]["c"][k])
            d = r.attr_current_direction
            prior = _opp(d) if r.reason_code == "CONVERTED" else d
            bad9 += not ((c < z["lower_ticks"]) if prior == BULL else (c > z["upper_ticks"]))
    seqs = tr.sort_values("transition_at").groupby("entity_id")["new_state"].apply(tuple)
    allowed = {("IFVG",), ("IFVG", "RETIRED"), ("TERMINATED",), ("PENDING_ADJUSTMENT",), ("IFVG", "TERMINATED"),
               ("IFVG", "PENDING_ADJUSTMENT")}
    rec("FVG-INV-9 conversions / retirements are strict own-timeframe closes beyond the far bound", len(tr), bad9)
    rec("FVG-INV-10 stage sequences", len(seqs), sum(s not in allowed for s in seqs))
    rec("FVG-INV-27 one exit per entity and instant", len(tr),
        tr.duplicated(["entity_id", "transition_at"]).sum() + E.bpr_transitions.duplicated(["entity_id", "transition_at"]).sum())
    # 13 / 14 / 15 / 16 (vectorized)
    e = E.episodes.copy()
    za = Z.set_index("zone_id")[["lower_ticks", "upper_ticks", "original_direction", "timeframe"]]
    e = e.join(za.add_suffix("_a"), on="zone_a").join(za.add_suffix("_b"), on="zone_b")
    bad13 = int(((e["i_lower_ticks"] != np.maximum(e["lower_ticks_a"], e["lower_ticks_b"]))
                 | (e["i_upper_ticks"] != np.minimum(e["upper_ticks_a"], e["upper_ticks_b"]))
                 | (e["i_upper_ticks"] - e["i_lower_ticks"] < 1)).sum())
    flip = {BULL: BEAR, BEAR: BULL}
    da = np.where(e["stage_a"] == "FVG", e["original_direction_a"], e["original_direction_a"].map(flip))
    db = np.where(e["stage_b"] == "FVG", e["original_direction_b"], e["original_direction_b"].map(flip))
    want = np.where(da == db, "FVG_OVERLAP", np.where(e["timeframe_a"] == e["timeframe_b"], "BPR", "MTF_BPR"))
    nm = e["movers"].map(len).to_numpy()
    bad14 = int(((e["label"].to_numpy() != want) | (nm < 1)).sum())
    opp = (e["label"] != "FVG_OVERLAP").to_numpy()
    mv = e["movers"].map(lambda m: m[0] if len(m) == 1 else None)
    dm = np.where(mv == e["zone_a"], da, db)
    tm = np.where(mv == e["zone_a"], e["timeframe_a"], e["timeframe_b"])
    one = nm == 1
    bad15 = int((opp & one & ((e["direction"].to_numpy() != dm) | (e["governing_timeframe"].to_numpy() != tm))).sum())
    bad15 += int((opp & ~one & (e["direction"].to_numpy() != "UNDEFINED")).sum())
    rec("FVG-INV-13 positive intersection of parent bounds", len(e), bad13)
    rec("FVG-INV-14 labels from current directions; at least one mover", len(e), bad14)
    rec("FVG-INV-15 directional event", len(e), bad15)
    per_pair = e.groupby(["zone_a", "zone_b"]).size() if len(e) else pd.Series(dtype=int)
    rec("FVG-INV-16 one episode per stage pair; at most three per pair", len(e),
        e.duplicated(["zone_a", "stage_a", "zone_b", "stage_b"]).sum() + int((per_pair > 3).sum()))
    # 17
    b = E.bprs
    bad = 0
    for r in b.itertuples(index=False):
        if r.exit_state == "RETIRED":
            si, k = seg_pos[r.governing_timeframe][r.exit_at.value]
            c = int(run.tf_data[r.governing_timeframe].segments[si]["c"][k])
            bad += not ((c < r.lower_ticks) if r.direction == BULL else (c > r.upper_ticks))
        bad += r.direction == "UNDEFINED" and r.exit_state == "RETIRED"
    rec("FVG-INV-17 BPR exits only by its own predicate or a reset", len(b), bad)
    # 20
    bad = 0
    for ep in run.tape.episodes:
        if ep.reset_reason != "DATA_GAP":
            continue
        t = ep.reset_at
        live = E.stages[(E.stages["stage_start"] < t) & (E.stages["stage_end"].isna() | (E.stages["stage_end"] >= t))]
        live = live[live["zone_id"].map(lambda x: run.tape.locate(av[x].value)[0] == ep.index)]
        bad += int((live["end_kind"] != "TERMINATED").sum() if len(live) else 0)
        nxt = run.tape.episodes[ep.index + 1].end[0] if ep.index + 1 < len(run.tape.episodes) else None
        if nxt is not None:
            bad += int(((E.mitigation["at"] > t) & (E.mitigation["at"] < pd.Timestamp(int(nxt), tz="UTC"))).sum())
    rec("FVG-INV-20 gap onset terminates every active zone; nothing inside the gap", len(run.tape.episodes), bad)
    # 22 / 23 / 24
    a = run.associations
    sw_av = {}
    for tf_, sw in run.swings.items():
        if sw is not None and len(sw):
            sw_av.update(dict(zip(sw["swing_id"], pd.to_datetime(sw["available_at"], utc=True))))
    bad22 = int((a["association_available_at"] < a["formation_available_at"]).sum())
    if len(a):
        origin_av = pd.to_datetime(a["leg_origin_swing_id"].map(sw_av), utc=True)
        bad22 += int((origin_av > a["association_available_at"]).sum())
    term = a["last_terminator_swing_id"].map(lambda x: sw_av.get(x) if isinstance(x, str) else None)
    bad22 += int(sum(1 for t_, at_ in zip(term, a["association_available_at"]) if t_ is not None and not pd.isna(t_) and t_ > at_))
    rec("FVG-INV-22 association uses only swings known at the association instant", len(a), bad22)
    mt = run.marker_transitions
    bad = 0
    for r in mt.itertuples(index=False):
        bad += r.reason_code not in ("CONVERTED", "TERMINATED", "PENDING_ADJUSTMENT")
    rec("FVG-INV-23 markers end only at conversion or reset", len(mt), bad)
    firsts = a[a["is_first"]]
    rec("FVG-INV-24 at most one first marker per leg", len(firsts),
        firsts.duplicated(["direction", "leg_origin_swing_id"]).sum())
    # 26
    from src.fvg.association import marker_namespace
    from src.fvg.engine import bpr_namespace, overlap_namespace, zone_namespace
    bad = 0
    for frame_, spec, ent in ((E.zone_transitions, zone_namespace(), E.zone_entities),
                              (E.episode_transitions, overlap_namespace(), E.episode_entities),
                              (E.bpr_transitions, bpr_namespace(), E.bpr_entities),
                              (run.marker_transitions, marker_namespace(), run.marker_entities)):
        try:
            if len(frame_):
                validate_transitions(frame_, spec, ent)
        except Exception:      # noqa: BLE001 — counted as a violation
            bad += 1
    rec("FVG-INV-26 M7A validity of all namespaces", 4, bad)
    return pd.DataFrame(res)


# ---------------------------------------------------------------------------
# Prefix equivalence (FVG-INV-21)
# ---------------------------------------------------------------------------


def prefix_mismatches(full, part) -> dict:
    """Part (cutoff run) vs full restricted to the cutoff; also counts part rows after the cutoff."""
    cut = pd.Timestamp(part.manifest["replay_cutoff"])
    out = {}

    def cmp(name, fa, fb, key, time_col):
        a = fa[fa[time_col] <= cut]
        ka = set(map(tuple, a[key].astype(str).to_numpy())) if len(a) else set()
        kb = set(map(tuple, fb[key].astype(str).to_numpy())) if len(fb) else set()
        out[name] = len(ka ^ kb)
        out[name + "_future_rows"] = int((fb[time_col] > cut).sum()) if len(fb) else 0
    cmp("zones", full.zones, part.zones, ["zone_id", "normalization_status"], "available_at")
    cmp("rejections", full.rejections, part.rejections, ["triple_ref", "reason"], "c3_end")
    cmp("zone_transitions", full.engine.zone_transitions, part.engine.zone_transitions, ["transition_id"], "transition_at")
    cmp("mitigation", full.engine.mitigation, part.engine.mitigation, ["event_id"], "at")
    fe, pe = full.engine.episodes.copy(), part.engine.episodes.copy()
    fe["ended_cut"] = fe["ended_at"].where(fe["ended_at"] <= cut)
    pe["ended_cut"] = pe["ended_at"]
    cmp("episodes", fe, pe, ["relationship_id", "label", "direction", "ended_cut"], "created_at")
    cmp("bprs", full.engine.bprs, part.engine.bprs, ["bpr_id", "direction"], "available_at")
    cmp("bpr_transitions", full.engine.bpr_transitions, part.engine.bpr_transitions, ["transition_id"], "transition_at")
    cmp("grades", full.engine.grades, part.engine.grades, ["grade_version_id"], "available_at")
    cmp("associations", full.associations, part.associations, ["association_id", "is_first", "marker_never_active"],
        "association_available_at")
    cmp("marker_transitions", full.marker_transitions, part.marker_transitions, ["transition_id"], "transition_at")
    return out
