"""FVG full-run independent recomputation (FVG-I5 correction; complements ``src.fvg.audit``).

``src.fvg.audit.reference`` replays whole 1m episodes naively (all-pairs per instant) and is affordable only on
short episodes.  This module re-derives the same facts on the **full run** with different, deliberately simple
algorithms whose restrictions are exact:

- formation: scalar per-triple predicates and true ranges (``audit._ref_formation`` over every episode);
- zone lifecycle and mitigation: a scalar per-1m-bar replay **per zone** (a zone's lifecycle depends only on
  its own bars, so the per-zone restriction is exact; it never truncates active state);
- relationship episodes: an interval sweep over the reference's own stage intervals (positive time overlap
  of two stage intervals with positive price intersection), with movers, labels, direction, governing
  timeframe and end reasons derived from the intervals;
- BPR objects: a scalar per-bar replay on the governing timeframe (lifecycle) and 1m (mitigation);
- grade versions and groups: per-zone partner timelines from the reference episodes, union-find components
  over the partners' source spans, representative by the §3.9 order;
- first-FVG associations: a two-pointer streaming sweep per timeframe segment (no bisection index).

Inputs shared with production are only the frozen inputs (M3 observations in continuity segments, the §G.2a
1m episodes, frozen swing points) and the identity formulas, so ids can be compared.  Nothing here calls the
production engine, relationship, grade or association code.
"""

from __future__ import annotations

from bisect import bisect_left
from fractions import Fraction

import numpy as np
import pandas as pd

from src.fvg.audit import _ref_formation
from src.fvg.formation import FVG_DEFINITION_VERSION, TF_RANK, raw_basis, sha_id

BULL, BEAR = "BULLISH", "BEARISH"
LIVE = ("FVG", "IFVG")
EXIT_REASON = {"RETIRED": "PARENT_RETIRED", "TERMINATED": "PARENT_TERMINATED",
               "PENDING_ADJUSTMENT": "PARENT_PENDING"}
INF = 1 << 62


def _opp(d):
    return BEAR if d == BULL else BULL


def _reset_kind(ep):
    return "TERMINATED" if ep.reset_reason == "DATA_GAP" else "PENDING_ADJUSTMENT"


# ---------------------------------------------------------------------------
# Shared frozen inputs as plain Python structures
# ---------------------------------------------------------------------------


class _Inputs:
    def __init__(self, run):
        self.run = run
        self.eps = []
        for ep in run.tape.episodes:
            self.eps.append({"start": ep.start.tolist(), "end": ep.end.tolist(), "l": ep.l.tolist(),
                             "h": ep.h.tolist(), "reset_at": None if ep.reset_at is None else ep.reset_at.value,
                             "reset_kind": None if ep.reset_at is None else _reset_kind(ep), "contract": ep.contract})
        self.tf_close = {}                     # tf -> {end_ns: (start_ns, close)}
        for tf, data in run.tf_data.items():
            d = {}
            for seg in data.segments:
                for s, e, c in zip(seg["start"].tolist(), seg["end"].tolist(), seg["c"].tolist()):
                    d[e] = (s, c)
            self.tf_close[tf] = d
        minute_ends = {e for ep in self.eps for e in ep["end"]}
        # assumption check: every timeframe close inside an episode is a 1m bar end (else the replay misses it)
        self.off_grid_closes = 0
        for tf, d in self.tf_close.items():
            for e in d:
                if e not in minute_ends:
                    loc = run.tape.locate(e)
                    if loc is not None:
                        self.off_grid_closes += 1


# ---------------------------------------------------------------------------
# Zone lifecycle and mitigation (per zone, scalar)
# ---------------------------------------------------------------------------


def _mitigate(out, oid, kind, stage, s, l, h, t):
    lo, up, mid2, d = s["lo"], s["up"], s["mid2"], s["dir"]
    if d == BULL:
        trade, beyond, depth, inz = l < up and h >= lo, h < lo, up - l, up - max(l, lo)
        mid, full, span, far = 2 * l <= mid2, l <= lo, l <= lo and h >= up, h == lo
    else:
        trade, beyond, depth, inz = h > lo and l <= up, l > up, h - lo, min(h, up) - lo
        mid, full, span, far = 2 * h >= mid2, h >= up, h >= up and l <= lo, l == up
    marks = s["marks"]
    if beyond and "PENETRATION" not in marks and "GAP_THROUGH" not in marks:
        marks.add("GAP_THROUGH")
        out.append((oid, kind, stage, "GAP_THROUGH", t, "BEYOND", None, None))
    if not trade:
        return
    cls = "SPANNING" if span else "FAR_CONTACT" if far else "ZONE_TRADE"
    for name, ok in (("PENETRATION", True), ("MIDPOINT", mid), ("FULL", full)):
        if ok and name not in marks:
            marks.add(name)
            out.append((oid, kind, stage, name, t, cls, depth, inz))
    if s["maxdepth"] is None or depth > s["maxdepth"]:
        s["maxdepth"] = depth
        out.append((oid, kind, stage, "DEPTH", t, cls, depth, inz))


def zone_replays(inp: _Inputs, zones: list) -> dict:
    """Per-zone scalar replay: transitions, mitigation and stage intervals."""
    transitions, mitigation, intervals = [], [], []
    for z in zones:
        ep = inp.eps[z["episode"]]
        closes = inp.tf_close[z["tf"]]
        s = {"stage": "FVG", "dir": z["dir"], "start": z["avail"], "lo": z["lo"], "up": z["up"],
             "mid2": z["lo"] + z["up"], "marks": set(), "maxdepth": None}
        cur = ["FVG", z["dir"], z["avail"]]
        i = bisect_left(ep["start"], z["avail"])
        ends, starts, ls, hs = ep["end"], ep["start"], ep["l"], ep["h"]
        exit_kind = exit_t = None
        while i < len(ends):
            t = ends[i]
            if starts[i] >= s["start"]:
                _mitigate(mitigation, z["zone_id"], "ZONE", s["stage"], s, ls[i], hs[i], t)
            c = closes.get(t)
            if c is not None and c[0] >= s["start"]:
                beyond = c[1] < s["lo"] if s["dir"] == BULL else c[1] > s["up"]
                if beyond:
                    if s["stage"] == "FVG":
                        intervals.append((z["zone_id"], "FVG", s["dir"], cur[2], t, "CONVERTED"))
                        s.update(stage="IFVG", dir=_opp(s["dir"]), start=t, marks=set(), maxdepth=None)
                        cur = ["IFVG", s["dir"], t]
                        transitions.append((z["zone_id"], "IFVG", t))
                    else:
                        exit_kind, exit_t = "RETIRED", t
                        break
            i += 1
        if exit_kind is None and ep["reset_at"] is not None:
            exit_kind, exit_t = ep["reset_kind"], ep["reset_at"]
        intervals.append((z["zone_id"], cur[0], cur[1], cur[2], INF if exit_t is None else exit_t, exit_kind))
        if exit_kind is not None:
            transitions.append((z["zone_id"], exit_kind, exit_t))
    return {"transitions": transitions, "mitigation": mitigation, "intervals": intervals}


# ---------------------------------------------------------------------------
# Relationship episodes from stage intervals (interval sweep)
# ---------------------------------------------------------------------------


def relationship_episodes(zones: list, intervals: list) -> list:
    zi = {z["zone_id"]: z for z in zones}
    by_ep: dict = {}
    for iv in intervals:
        by_ep.setdefault(zi[iv[0]]["episode"], []).append(iv)
    out = []
    for _ei, ivs in sorted(by_ep.items()):
        ivs.sort(key=lambda v: (v[3], v[0], v[1]))
        n = len(ivs)
        start = np.array([v[3] for v in ivs], dtype=np.int64)
        end = np.array([v[4] for v in ivs], dtype=np.int64)
        lo = np.array([zi[v[0]]["lo"] for v in ivs], dtype=np.int64)
        up = np.array([zi[v[0]]["up"] for v in ivs], dtype=np.int64)
        for i in range(1, n):
            si = start[i]
            if end[i] <= si:
                continue
            ilo, iup = np.maximum(lo[:i], lo[i]), np.minimum(up[:i], up[i])
            js = np.flatnonzero((end[:i] > si) & (iup - ilo >= 1))
            for j in js.tolist():
                va, vb = ivs[j], ivs[i]
                if va[0] == vb[0]:
                    continue
                if va[0] > vb[0]:
                    va, vb = vb, va
                created = int(si)
                movers = [v for v in (va, vb) if v[3] == created]
                za, zb = zi[va[0]], zi[vb[0]]
                if va[2] == vb[2]:
                    label, d, gov = "FVG_OVERLAP", va[2], None
                else:
                    label = "BPR" if za["tf"] == zb["tf"] else "MTF_BPR"
                    d, gov = (movers[0][2], zi[movers[0][0]]["tf"]) if len(movers) == 1 else ("UNDEFINED", None)
                ended = min(va[4], vb[4])
                reason = None
                if ended < INF:
                    exiting = sorted(v[0] for v in (va, vb) if v[4] == ended and v[5] != "CONVERTED")
                    if exiting:
                        kind = next(v[5] for v in (va, vb) if v[0] == exiting[0])
                        reason = EXIT_REASON[kind]
                    else:
                        reason = "PARENT_STAGE_CHANGED"
                rid = sha_id("fo_", [FVG_DEFINITION_VERSION, raw_basis(za["contract"]), [va[0], va[1]], [vb[0], vb[1]]])
                out.append({"rid": rid, "a": va[0], "sa": va[1], "b": vb[0], "sb": vb[1], "label": label, "dir": d,
                            "gov": gov, "created": created, "ended": None if ended >= INF else int(ended),
                            "reason": reason, "lo": int(ilo[j]), "up": int(iup[j]), "episode": za["episode"],
                            "movers": tuple(sorted(v[0] for v in movers))})
    return out


# ---------------------------------------------------------------------------
# BPR objects (scalar governing-timeframe / 1m replay)
# ---------------------------------------------------------------------------


def bpr_replays(inp: _Inputs, episodes: list) -> dict:
    exits, mitigation = [], []
    for e in episodes:
        if e["label"] == "FVG_OVERLAP":
            continue
        bid = sha_id("fb_", [e["rid"]])
        ep = inp.eps[e["episode"]]
        s = {"dir": e["dir"], "lo": e["lo"], "up": e["up"], "mid2": e["lo"] + e["up"], "marks": set(),
             "maxdepth": None}
        defined = e["dir"] != "UNDEFINED"
        closes = inp.tf_close[e["gov"]] if defined else {}
        exit_kind = exit_t = None
        if defined:
            i = bisect_left(ep["start"], e["created"])
            while i < len(ep["end"]):
                t = ep["end"][i]
                _mitigate(mitigation, bid, "BPR", "BPR", s, ep["l"][i], ep["h"][i], t)
                c = closes.get(t)
                if c is not None and c[0] >= e["created"]:
                    if (e["dir"] == BULL and c[1] < e["lo"]) or (e["dir"] == BEAR and c[1] > e["up"]):
                        exit_kind, exit_t = "RETIRED", t
                        break
                i += 1
        if exit_kind is None and ep["reset_at"] is not None:
            exit_kind, exit_t = ep["reset_kind"], ep["reset_at"]
        exits.append((bid, e["rid"], e["label"], e["dir"], e["gov"], e["lo"], e["up"], e["created"], exit_kind, exit_t))
    return {"bprs": exits, "mitigation": mitigation}


# ---------------------------------------------------------------------------
# Grades and groups from partner timelines
# ---------------------------------------------------------------------------


def _components(spans_by_id: dict, ids: list) -> list:
    parent = {x: x for x in ids}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            (a0, a1), (b0, b1) = spans_by_id[a], spans_by_id[b]
            if a0 < b1 and b0 < a1:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
    comps: dict = {}
    for x in ids:
        comps.setdefault(find(x), []).append(x)
    return [sorted(c) for c in comps.values()]


def grade_timelines(zones: list, intervals: list, episodes: list) -> dict:
    zi = {z["zone_id"]: z for z in zones}
    spans = {z["zone_id"]: z["span"] for z in zones}
    ivs_by_zone: dict = {}
    for iv in intervals:
        ivs_by_zone.setdefault(iv[0], []).append(iv)
    ovl_by_zone: dict = {}
    for e in episodes:
        if e["label"] == "FVG_OVERLAP":
            for me, other in ((e["a"], e["b"]), (e["b"], e["a"])):
                ovl_by_zone.setdefault(me, []).append((e["created"], INF if e["ended"] is None else e["ended"], other))
    grades, groups = [], []
    for zid, ivs in ivs_by_zone.items():
        ivs.sort(key=lambda v: v[3])
        ovl = ovl_by_zone.get(zid, [])
        times = {v[3] for v in ivs} | {v[4] for v in ivs if v[4] < INF}
        times |= {c for c, _e, _o in ovl} | {e for _c, e, _o in ovl if e < INF}
        last = None
        for t in sorted(times):
            stage = dirn = None
            for v in ivs:
                if v[3] <= t < v[4]:
                    stage, dirn = v[1], v[2]
            if stage is None:
                tail = ivs[-1]
                if t < tail[3]:
                    continue
                stage, dirn = tail[5], tail[2]
            actionable = stage in LIVE
            parts = sorted({o for c, e, o in ovl if c <= t < e}) if actionable else []
            comps = _components(spans, parts)
            state = (len(comps), tuple(parts), stage, actionable)
            if state == last:
                continue
            last = state
            z = zi[zid]
            grades.append((zid, t, len(comps), tuple(parts), stage, dirn, actionable, TF_RANK[z["tf"]], z["status"],
                           None if z["strength"] is None else str(z["strength"]), z["up"] - z["lo"]))
            reps = []
            for c in comps:
                rep = min(c, key=lambda p: (-TF_RANK[zi[p]["tf"]], -(zi[p]["up"] - zi[p]["lo"]), zi[p]["avail"], p))
                reps.append((rep, tuple(c)))
            groups.append((zid, t, tuple(sorted(reps))))
    return {"grades": grades, "groups": groups}


# ---------------------------------------------------------------------------
# First-FVG association (streaming sweep per timeframe segment)
# ---------------------------------------------------------------------------


def associations(run, zones: list, transitions: list) -> list:
    from decimal import Decimal
    from src.market_structure.swing_breaks import price_ticks
    tick = Decimal(run.manifest["tick_size"])
    fvg_end = {}
    for zid, state, t in transitions:
        fvg_end[zid] = min(fvg_end.get(zid, INF), t)
    out = []
    for tf, data in run.tf_data.items():
        sw = run.swings.get(tf)
        rows = []
        if sw is not None and len(sw):
            px = price_ticks(sw["price"].to_numpy(), tick)
            rows = [{"id": r.swing_id, "o": r.orientation, "px": int(p), "src": pd.Timestamp(r.source_at).value,
                     "src_end": pd.Timestamp(r.source_end_at).value, "av": pd.Timestamp(r.available_at).value}
                    for r, p in zip(sw.itertuples(), px)]
        zs = [z for z in zones if z["tf"] == tf]
        found = []
        for si, seg in enumerate(data.segments):
            seg_lo, seg_hi = int(seg["start"][0]), int(seg["end"][-1])
            sws = [s for s in rows if seg_lo < s["src"] <= seg_hi]
            zseg = sorted((z for z in zs if z["seg"] == si), key=lambda z: z["c2"])
            if not zseg:
                continue
            seg_vals = {BULL: seg["l"].tolist(), BEAR: seg["h"].tolist()}
            seg_end = seg["end"].tolist()
            for d in (BULL, BEAR):
                own, opp = ("LOWER", "UPPER") if d == BULL else ("UPPER", "LOWER")
                opps = sorted((s for s in sws if s["o"] == opp), key=lambda s: s["src_end"])
                owns = sorted((s for s in sws if s["o"] == own), key=lambda s: (s["src"], s["id"]))
                key = (lambda s: (s["px"], s["src"])) if own == "LOWER" else (lambda s: (-s["px"], s["src"]))
                p = lo = hi = 0
                term, best = None, None
                for z in (z for z in zseg if z["dir"] == d):
                    a = z["c2"]
                    moved = False
                    while p < len(opps) and opps[p]["src_end"] < a:
                        term = opps[p]
                        p += 1
                        moved = True
                    since = None if term is None else term["src_end"]
                    while hi < len(owns) and owns[hi]["src"] <= a:
                        if best is None or key(owns[hi]) < key(best):
                            best = owns[hi] if (since is None or owns[hi]["src"] > since) else best
                        hi += 1
                    if moved:
                        while lo < hi and since is not None and owns[lo]["src"] <= since:
                            lo += 1
                        best = None
                        for s in owns[lo:hi]:
                            if best is None or key(s) < key(best):
                                best = s
                    if best is None:
                        continue
                    k2 = z["k3"] - 1
                    vals = seg_vals[d]
                    j = k2
                    while j > 0 and vals[j - 1] == vals[k2]:
                        j -= 1
                    qualified = j >= 2 and all((vals[x] >= vals[k2]) if d == BULL else (vals[x] <= vals[k2])
                                               for x in (j - 2, j - 1))
                    if qualified:
                        if k2 + 2 >= len(seg_end):
                            continue
                        deadline = seg_end[k2 + 2]
                    else:
                        deadline = z["avail"]
                    found.append((z, best, term, max(z["avail"], best["av"], deadline)))
        firsts = set()
        for z, origin, term, at in sorted(found, key=lambda x: (x[0]["avail"], x[0]["c2"], x[0]["zone_id"])):
            first = (z["dir"], origin["id"]) not in firsts
            firsts.add((z["dir"], origin["id"]))
            never = first and fvg_end.get(z["zone_id"], INF) <= at
            out.append((z["zone_id"], origin["id"], None if term is None else term["id"], first, at, bool(never)))
    return out


# ---------------------------------------------------------------------------
# Full-run reference and reconciliation
# ---------------------------------------------------------------------------


def full_reference(run, log=print) -> dict:
    import time
    t0 = time.perf_counter()
    inp = _Inputs(run)
    keep = set(range(len(run.tape.episodes)))
    zones, rejections = _ref_formation(run, run.manifest["instrument_id"], keep)
    log(f"  full ref formation {time.perf_counter() - t0:.0f}s")
    zr = zone_replays(inp, zones)
    log(f"  full ref zone replays {time.perf_counter() - t0:.0f}s")
    eps = relationship_episodes(zones, zr["intervals"])
    log(f"  full ref episodes {time.perf_counter() - t0:.0f}s")
    br = bpr_replays(inp, eps)
    log(f"  full ref bprs {time.perf_counter() - t0:.0f}s")
    gr = grade_timelines(zones, zr["intervals"], eps)
    log(f"  full ref grades {time.perf_counter() - t0:.0f}s")
    assoc = associations(run, zones, zr["transitions"])
    log(f"  full ref associations {time.perf_counter() - t0:.0f}s")
    return {"zones": zones, "rejections": rejections, "transitions": zr["transitions"],
            "zone_mitigation": zr["mitigation"], "episodes": eps, "bprs": br["bprs"],
            "bpr_mitigation": br["mitigation"], "grades": gr["grades"], "groups": gr["groups"],
            "associations": assoc, "off_grid_closes": inp.off_grid_closes}


def full_reconcile(run, ref) -> pd.DataFrame:
    """Reference vs production on the full run, by category and timeframe (method FULL_RUN_INDEPENDENT)."""
    rows = []
    ztf = {z.zone_id: z.timeframe for z in run.zones.itertuples(index=False)}

    def add(cat, expected, actual, tf_of):
        exp_by, act_by = {}, {}
        for x in expected:
            exp_by.setdefault(tf_of(x), set()).add(x)
        for x in actual:
            act_by.setdefault(tf_of(x), set()).add(x)
        for tf in sorted(set(exp_by) | set(act_by), key=lambda k: (TF_RANK.get(k, 99), str(k))):
            e, a = exp_by.get(tf, set()), act_by.get(tf, set())
            rows.append({"category": cat, "timeframe": tf, "method": "FULL_RUN_INDEPENDENT", "reference": len(e),
                         "production": len(a), "missing": len(e - a), "extra": len(a - e)})

    by_zone = lambda x: ztf.get(x[0], "?")  # noqa: E731
    add("zones", [(z["zone_id"], z["lo"], z["up"], z["status"], None if z["strength"] is None else str(z["strength"]))
                  for z in ref["zones"]],
        [(r.zone_id, r.lower_ticks, r.upper_ticks, r.normalization_status,
          None if pd.isna(r.strength_num) else str(Fraction(int(r.strength_num), int(r.strength_den))))
         for r in run.zones.itertuples(index=False)], by_zone)
    add("rejections", ref["rejections"], [(r.timeframe, r.triple_ref, r.reason) for r in run.rejections.itertuples(index=False)],
        lambda x: x[0])
    add("zone_transitions", ref["transitions"],
        [(r.entity_id, r.new_state, r.transition_at.value) for r in run.engine.zone_transitions.itertuples(index=False)],
        by_zone)
    m = run.engine.mitigation
    prod_m = list(zip(m["object_id"].tolist(), m["object_kind"].astype(str).tolist(), m["stage"].astype(str).tolist(),
                      m["kind"].astype(str).tolist(), [int(x) for x in m["at"].astype("int64").tolist()],
                      m["observation_class"].astype(str).tolist(),
                      [None if pd.isna(x) else int(x) for x in m["penetration_depth_ticks"].tolist()],
                      [None if pd.isna(x) else int(x) for x in m["in_zone_depth_ticks"].tolist()]))
    bpr_tf = {b[0]: (b[4] or "UNDEFINED") for b in ref["bprs"]}
    for b in run.engine.bprs.itertuples(index=False):
        bpr_tf.setdefault(b.bpr_id, b.governing_timeframe if isinstance(b.governing_timeframe, str) else "UNDEFINED")
    add("zone_mitigation", ref["zone_mitigation"], [x for x in prod_m if x[1] == "ZONE"], by_zone)
    add("bpr_mitigation", ref["bpr_mitigation"], [x for x in prod_m if x[1] == "BPR"], lambda x: bpr_tf.get(x[0], "?"))
    del prod_m
    e = run.engine.episodes
    add("episodes", [(x["rid"], x["a"], x["sa"], x["b"], x["sb"], x["label"], x["dir"], x["gov"], x["created"], x["ended"],
                      x["reason"], x["lo"], x["up"], x["movers"]) for x in ref["episodes"]],
        [(r.relationship_id, r.zone_a, r.stage_a, r.zone_b, r.stage_b, r.label, r.direction,
          None if pd.isna(r.governing_timeframe) else r.governing_timeframe, r.created_at.value,
          None if pd.isna(r.ended_at) else r.ended_at.value, None if pd.isna(r.end_reason) else r.end_reason,
          int(r.i_lower_ticks), int(r.i_upper_ticks), tuple(sorted(r.movers))) for r in e.itertuples(index=False)],
        lambda x: f"{x[5]}:{ztf.get(x[1], '?')}|{ztf.get(x[3], '?')}" if x[5] != "FVG_OVERLAP" else f"{x[5]}:{ztf.get(x[1], '?')}")
    b = run.engine.bprs
    add("bprs", [(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], x[8], x[9]) for x in ref["bprs"]],
        [(r.bpr_id, r.relationship_id, r.label, r.direction,
          None if pd.isna(r.governing_timeframe) else r.governing_timeframe, int(r.lower_ticks), int(r.upper_ticks),
          r.available_at.value, None if pd.isna(r.exit_state) else r.exit_state,
          None if pd.isna(r.exit_at) else r.exit_at.value) for r in b.itertuples(index=False)],
        lambda x: x[4] or "UNDEFINED")
    g = run.engine.grades
    add("grades", ref["grades"],
        [(r.zone_id, r.available_at.value, int(r.overlap_contribution), tuple(r.partner_zone_ids), r.stage,
          r.current_direction, bool(r.actionable), int(r.timeframe_rank), r.normalization_status,
          None if pd.isna(r.strength_num) else str(Fraction(int(r.strength_num), int(r.strength_den))),
          int(r.original_width_ticks)) for r in g.itertuples(index=False)], by_zone)
    gkey = dict(zip(g["grade_version_id"], zip(g["zone_id"], g["available_at"].astype("int64"))))
    grp: dict = {}
    for gid, rep, members in zip(run.engine.groups["grade_version_id"], run.engine.groups["representative_zone_id"],
                                 run.engine.groups["member_zone_ids"]):
        grp.setdefault(gkey[gid], []).append((rep, tuple(members)))
    prod_groups = [(zid, int(t), tuple(sorted(grp.get((zid, t), [])))) for zid, t in gkey.values()]
    add("groups", ref["groups"], prod_groups, by_zone)
    a = run.associations
    add("associations", ref["associations"],
        [(r.zone_id, r.leg_origin_swing_id, None if pd.isna(r.last_terminator_swing_id) else r.last_terminator_swing_id,
          bool(r.is_first), r.association_available_at.value, bool(r.marker_never_active))
         for r in a.itertuples(index=False)], by_zone)
    return pd.DataFrame(rows)


def subset_coverage(run, episodes_checked) -> pd.DataFrame:
    """Coverage of the episode-subset naive reference, by category and timeframe (zero-covered rows kept)."""
    keep = set(episodes_checked)
    E = run.engine
    ep_of = lambda ns: (run.tape.locate(int(ns)) or (None,))[0]  # noqa: E731
    Z = run.zones
    zep = dict(zip(Z["zone_id"], [ep_of(v) for v in Z["available_at"].astype("int64")]))
    ztf = dict(zip(Z["zone_id"], Z["timeframe"]))
    b = E.bprs
    bep = dict(zip(b["bpr_id"], [ep_of(v) for v in b["available_at"].astype("int64")]))
    btf = dict(zip(b["bpr_id"], b["governing_timeframe"].fillna("UNDEFINED")))
    m = E.mitigation
    cats = {
        "zones": [(ztf[z], zep[z]) for z in Z["zone_id"]],
        "rejections": [(tf, ep_of(t)) for tf, t in zip(run.rejections["timeframe"], run.rejections["c3_end"].astype("int64"))],
        "zone_transitions": [(ztf[z], zep[z]) for z in E.zone_transitions["entity_id"]],
        "zone_mitigation": [(ztf[o], zep[o]) for o, k in zip(m["object_id"], m["object_kind"].astype(str)) if k == "ZONE"],
        "bpr_mitigation": [(btf[o], bep[o]) for o, k in zip(m["object_id"], m["object_kind"].astype(str)) if k == "BPR"],
        "episodes": [(f"{lab}:{ztf[a]}", zep[a]) for lab, a in zip(E.episodes["label"], E.episodes["zone_a"])],
        "bprs": [(btf[x], bep[x]) for x in b["bpr_id"]],
        "grades": [(ztf[z], zep[z]) for z in E.grades["zone_id"]],
        "associations": [(ztf[z], zep[z]) for z in run.associations["zone_id"]],
    }
    rows = []
    for cat, items in cats.items():
        tot: dict = {}
        cov: dict = {}
        for tf, ep in items:
            tot[tf] = tot.get(tf, 0) + 1
            cov[tf] = cov.get(tf, 0) + (ep in keep)
        for tf in sorted(tot, key=lambda k: (TF_RANK.get(str(k).split(":")[-1], 99), str(k))):
            rows.append({"category": cat, "timeframe": tf, "method": "EPISODE_SUBSET_REFERENCE",
                         "production": tot[tf], "covered": cov[tf], "coverage_share": round(cov[tf] / tot[tf], 4)})
    return pd.DataFrame(rows)
