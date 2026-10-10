"""Order Block independent reference, reconciliation, invariants and prefix comparison (OB-I4 / OB-I5).

The reference re-derives every checked fact with deliberately simple code that shares only the frozen inputs
(own-timeframe observations in continuity segments, the public Swing detector rows, the frozen FVG formation rows,
the §G.2a 1m tape) and identity formulas with production:

- discovery is a causal time-step over every own-timeframe bar using only swings / FVGs known at that bar
  (production computes each episode structurally from final facts with explicit deadlines);
- ordinary / successor lifecycles are scalar per-block bar scans (production: vectorised searches);
- motifs re-scan the known swings at their resolution time;
- interactions are a scalar per-minute loop (production: vectorised masks).

Every OB object lives inside one continuity segment and one 1m episode, so a reference restricted to a subset of
timeframes is an exact restriction of the full run.
"""

from __future__ import annotations

from bisect import bisect_right, insort
from collections import Counter
from decimal import Decimal

import numpy as np
import pandas as pd

from src.market_structure.swing_breaks import price_ticks

BULL, BEAR = "BULLISH", "BEARISH"


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------


def _segments_with_inputs(run, tf):
    obs = run.obs[tf]
    pos = {}
    for si, seg in enumerate(obs.segments):
        for k, e in enumerate(seg["end"].tolist()):
            pos[e] = (si, k)
    sw_rows = {}
    sw = run.swing_frames.get(tf)
    if sw is not None and len(sw):
        px = price_ticks(sw["price"].to_numpy(), Decimal(run.manifest["tick_size"]))
        for r, p in zip(sw.itertuples(index=False), px):
            si, a = pos[pd.Timestamp(r.source_at).value]
            _, b = pos[pd.Timestamp(r.source_end_at).value]
            sw_rows.setdefault(si, []).append({"id": r.swing_id, "o": r.orientation, "a": a, "b": b, "p": int(p),
                                               "av": pd.Timestamp(r.available_at).value})
    fv = {}
    z = run.fvg_zones
    if z is not None and len(z):
        for r in z[z["timeframe"] == tf].itertuples(index=False):
            si, c2 = pos[r.c2_end.value]
            fv.setdefault(si, []).append({"id": r.zone_id, "d": r.original_direction, "c2": c2,
                                          "av": r.available_at.value})
    return obs, sw_rows, fv


def _run_end_naive(vals, m, t):
    """End of the equal-value run containing m among bars <= t, and whether it is still open at t."""
    k = m
    while k + 1 <= t and vals[k + 1] == vals[m]:
        k += 1
    return k, k == t


def _pending_candidate(vals, more, r0, t, L, R):
    """Naive: is the run starting at r0 (bars <= t only) still a possible swing at t?  ``more(a, b)`` = a is
    strictly more extreme than b for this orientation."""
    v = vals[r0]
    if r0 - L < 0 or any(more(vals[k], v) for k in range(r0 - L, r0)):
        return False                        # never a swing
    r1 = r0
    while r1 + 1 <= t and vals[r1 + 1] == v:
        r1 += 1
    if r1 == t:
        return True                         # run may still extend
    for k in range(r1 + 1, min(t, r1 + R) + 1):
        if more(vals[k], v):
            return False                    # denied
    return t < r1 + R                       # confirmed once R bars are seen


def _runs_from(vals, first, last):
    starts, k = [], first
    while k <= last:
        starts.append(k)
        while k + 1 <= last and vals[k + 1] == vals[k]:
            k += 1
        k += 1
    return starts


def _episode_of_segment(run, seg):
    loc = run.tape.locate(int(seg["end"][0]))
    return run.tape.episodes[loc[0]]


def reference(run, timeframes=None) -> dict:
    R = int(run.manifest["right_depth"])
    out = {"episodes": [], "blocks": [], "changes": [], "motifs": [], "stages": [], "events": [], "visits": [],
           "depth": [], "timeframes": []}
    for tf in (timeframes or [t for t in run.manifest["timeframes"].split(",") if t]):
        out["timeframes"].append(tf)
        obs, sw_rows, fv = _segments_with_inputs(run, tf)
        for si, seg in enumerate(obs.segments):
            _ref_segment(run, tf, si, seg, sw_rows.get(si, []), fv.get(si, []), R, out)
    return out


def _ref_segment(run, tf, si, seg, sws, fvs, R, out):
    o, h, l, c, end = (seg[k].tolist() for k in ("o", "h", "l", "c", "end"))
    n = len(end)
    tape_ep = _episode_of_segment(run, seg)
    by_av = sorted(sws, key=lambda s: (s["av"], s["a"]))
    known = {"UPPER": [], "LOWER": []}          # sorted by a: (a, swing)
    episodes = []
    p = 0
    for t in range(n):
        now = end[t]
        while p < len(by_av) and by_av[p]["av"] <= now:
            sw = by_av[p]
            insort(known[sw["o"]], (sw["a"], sw["id"], sw))
            d = BULL if sw["o"] == "LOWER" else BEAR
            s = sw["b"]
            body = abs(c[s] - o[s])
            ok = c[s] < o[s] if d == BULL else c[s] > o[s]
            ep = {"tf": tf, "d": d, "anchor": sw, "s": s, "status": "WAITING_FOR_DEPARTURE", "at": None, "reason": None}
            episodes.append(ep)
            if body < 4:
                ep.update(status="REJECTED", at=now, reason="SOURCE_BODY_LT_4_TICKS")
            elif not ok:
                ep.update(status="REJECTED", at=now, reason="SOURCE_DIRECTION_MISMATCH")
            p += 1
        for ep in episodes:
            if ep["status"] != "WAITING_FOR_DEPARTURE":
                continue
            d, s, L = ep["d"], ep["s"], ep["anchor"]
            same, opp = ("LOWER", "UPPER") if d == BULL else ("UPPER", "LOWER")
            vals = l if d == BULL else h
            same_vals, opp_vals = (l, h) if d == BULL else (h, l)
            same_more = (lambda a, b: a < b) if d == BULL else (lambda a, b: a > b)
            opp_more = (lambda a, b: a > b) if d == BULL else (lambda a, b: a < b)
            Ld = int(run.manifest["left_depth"])
            H = next((x[2] for x in known[opp] if x[0] > s), None)
            L2 = next((x[2] for x in known[same] if x[0] > s), None)
            e = t
            if H is not None:
                e = min(e, H["b"])
            if L2 is not None:
                e = min(e, L2["a"] - 1)
            fvg = None
            for f in sorted(fvs, key=lambda f: (f["c2"], f["id"])):
                if f["d"] == d and f["av"] <= now and s < f["c2"] <= e:
                    fvg = f
                    break
            v = None
            for k in range(s + 1, e + 1):
                if (c[k] > h[s]) if d == BULL else (c[k] < l[s]):
                    v = k
                    break
            if fvg is not None and v is not None:
                m = max(fvg["c2"], v)
                pend = any(_pending_candidate(same_vals, same_more, r0, t, Ld, R)
                           for r0 in range(s + 1, m + 1) if r0 == s + 1 or same_vals[r0] != same_vals[r0 - 1])
                for r0 in _runs_from(opp_vals, s + 1, m - 1):
                    r1 = r0
                    while r1 + 1 <= m - 1 and opp_vals[r1 + 1] == opp_vals[r0]:
                        r1 += 1
                    if r1 + 1 <= t and opp_vals[r1 + 1] != opp_vals[r0] and r1 <= m - 1:
                        pend |= _pending_candidate(opp_vals, opp_more, r0, t, Ld, R)
                if not pend and L["av"] <= now:
                    lower, upper = (l[s], o[s]) if d == BULL else (o[s], h[s])
                    bad = any((c[k] < lower) if d == BULL else (c[k] > upper) for k in range(s + 1, t + 1))
                    if bad:
                        ep.update(status="REJECTED", at=now, reason="ALREADY_INVALID_BEFORE_ADMISSION")
                    else:
                        ep.update(status="ADMITTED", at=now, fvg=fvg["id"], lower=lower, upper=upper, adm=t)
                continue
            if L2 is not None and (H is None or L2["a"] - 1 < H["b"]):
                ep.update(status="SUPERSEDED", at=now, reason="NEW_SAME_SIDE_SWING")
            elif H is not None:
                pend = any(_pending_candidate(same_vals, same_more, r0, t, Ld, R)
                           for r0 in range(s + 1, H["b"] + 1) if same_vals[r0] != same_vals[r0 - 1])
                if not pend and H["av"] <= now:
                    ep.update(status="REJECTED", at=now,
                              reason="NO_DEPARTURE_FVG_IN_WINDOW" if fvg is None else "NOT_VALIDATED_IN_WINDOW")
    for ep in episodes:
        if ep["status"] == "WAITING_FOR_DEPARTURE" and tape_ep.reset_at is not None:
            ep.update(status="TERMINATED", at=tape_ep.reset_at, reason=tape_ep.reset_reason)
        out["episodes"].append((tf, ep["d"], ep["anchor"]["id"], ep["status"], ep["at"], ep["reason"]))
        if ep["status"] == "ADMITTED":
            _ref_block(run, tf, seg, sws, ep, R, tape_ep, out)


def _ref_block(run, tf, seg, sws, ep, R, tape_ep, out):
    o, h, l, c, end = (seg[k].tolist() for k in ("o", "h", "l", "c", "end"))
    n = len(end)
    d, s, adm, lower, upper = ep["d"], ep["s"], ep["adm"], ep["lower"], ep["upper"]
    key = (tf, d, end[s])
    out["blocks"].append((key, end[adm], lower, upper, ep["fvg"]))
    reset_kind = None if tape_ep.reset_at is None else (
        "TERMINATED_DATA_GAP" if tape_ep.reset_reason == "DATA_GAP" else "PENDING_ADJUSTMENT")
    x = None
    for k in range(adm + 1, n):
        if (c[k] < lower) if d == BULL else (c[k] > upper):
            x = k
            break
    stages = [[key, "ORDINARY", d, end[adm], None, None]]
    if x is None:
        if reset_kind:
            stages[0][4:] = [tape_ep.reset_at, reset_kind]
            out["changes"].append((key, "ORDINARY", reset_kind, tape_ep.reset_at, tape_ep.reset_reason))
        out["stages"] += [tuple(st) for st in stages]
        return
    stages[0][4:] = [end[x], "ORDINARY_FAILED"]
    d1 = BEAR if d == BULL else BULL
    opp = "UPPER" if d == BULL else "LOWER"
    resolve = x - 1 + R if x - 1 + R > x else x
    if resolve > n - 1:
        out["changes"].append((key, "ORDINARY", "FAILED_AWAITING_CLASSIFICATION", end[x], "ORDINARY_FAILED"))
        if reset_kind:
            out["changes"].append((key, "FAILED_AWAITING_CLASSIFICATION", reset_kind, tape_ep.reset_at, tape_ep.reset_reason))
        out["motifs"].append((key, "UNRESOLVED", None))
        out["stages"] += [tuple(st) for st in stages]
        return
    t_res = end[resolve]
    B = ep["anchor"]
    known = [sw for sw in sws if sw["o"] == opp and sw["av"] <= t_res]
    A = None
    for sw in known:
        if sw["b"] < B["a"] and (A is None or sw["a"] > A["a"]):
            A = sw
    C = None
    for sw in sorted(known, key=lambda q: q["a"]):
        if sw["a"] > B["b"] and sw["b"] < x:
            if C is None or ((sw["p"] > C["p"]) if d == BULL else (sw["p"] < C["p"])):
                C = sw
    raid = A is not None and any((h[k] > A["p"]) if d == BULL else (l[k] < A["p"]) for k in range(B["b"] + 1, x + 1))
    if A is None:
        cls, why = None, "NO_PRIOR_EXTREME"
    elif C is None:
        cls, why = None, "NO_REVERSAL_SWING"
    elif (C["p"] > A["p"]) if d == BULL else (C["p"] < A["p"]):
        cls, why = "BREAKER", None
    elif C["p"] == A["p"]:
        cls, why = None, "EQUAL_EXTREME" if not raid else "EQUAL_EXTREME_WITH_RAID"
    elif not raid:
        cls, why = "MITIGATION", None
    else:
        cls, why = None, "RAID_WITH_LESS_EXTREME_C"
    state = "ORDINARY"
    if resolve > x:
        out["changes"].append((key, "ORDINARY", "FAILED_AWAITING_CLASSIFICATION", end[x], "ORDINARY_FAILED"))
        state = "FAILED_AWAITING_CLASSIFICATION"
    if cls is None:
        out["changes"].append((key, state, "FAILED_FINAL", t_res, why))
        out["motifs"].append((key, "FAILED_FINAL", why, None if A is None else A["id"], None if C is None else C["id"], raid))
        out["stages"] += [tuple(st) for st in stages]
        return
    if resolve > x and any((c[k] > upper) if d1 == BEAR else (c[k] < lower) for k in range(x + 1, resolve + 1)):
        out["changes"].append((key, state, "FAILED_FINAL", t_res, "QUALIFIED_BUT_INVALID_BEFORE_ADMISSION"))
        out["motifs"].append((key, "FAILED_FINAL", "QUALIFIED_BUT_INVALID_BEFORE_ADMISSION", A["id"], C["id"], raid))
        out["stages"] += [tuple(st) for st in stages]
        return
    out["changes"].append((key, state, cls, t_res, cls + "_MOTIF"))
    out["motifs"].append((key, cls, None, A["id"], C["id"], raid))
    succ = [key, cls, d1, t_res, None, None]
    stages.append(succ)
    k_ret = None
    for k in range(resolve + 1, n):
        if (c[k] > upper) if d1 == BEAR else (c[k] < lower):
            k_ret = k
            break
    if k_ret is not None:
        succ[4:] = [end[k_ret], "RETIRED"]
        out["changes"].append((key, cls, "RETIRED", end[k_ret], "SUCCESSOR_CLOSE_BEYOND"))
    elif reset_kind:
        succ[4:] = [tape_ep.reset_at, reset_kind]
        out["changes"].append((key, cls, reset_kind, tape_ep.reset_at, tape_ep.reset_reason))
    out["stages"] += [tuple(st) for st in stages]


def reference_interactions(run, ref) -> None:
    """Scalar per-minute interactions for every reference stage (appends to ``ref``)."""
    for key, kind, d, avail, ended, _why in ref["stages"]:
        blk = next(b for b in ref["blocks"] if b[0] == key)
        lo, up = blk[2], blk[3]
        ep = next(e for e in run.tape.episodes if len(e.end) and e.end[0] <= avail <= e.end[-1])
        st, en, L, H = ep.start.tolist(), ep.end.tolist(), ep.l.tolist(), ep.h.tolist()
        width, mid2 = up - lo, lo + up
        bull = d == BULL
        firsts = {}
        visit = None
        visits, depth = [], []
        prev_touch, prev_end, prev_approach = False, None, False
        md = ma = 0
        first_bar = True
        for i in range(len(en)):
            if st[i] < avail or (ended is not None and en[i] > ended):
                continue
            lo_i, hi_i = L[i], H[i]
            touch = hi_i >= lo and lo_i <= up
            pen = hi_i > lo and lo_i < up
            midp = 2 * lo_i <= mid2 <= 2 * hi_i
            far = lo if bull else up
            distal = lo_i <= far <= hi_i
            full = lo_i <= lo and hi_i >= up
            dep = max(0, min(width, (up - max(lo_i, lo)) if bull else (min(hi_i, up) - lo))) if touch else 0
            adv = max(0, lo - lo_i) if bull else max(0, hi_i - up)
            beyond = hi_i < lo if bull else lo_i > up
            for name, flag in (("FIRST_TOUCH", touch), ("FIRST_PENETRATION", pen), ("FIRST_MIDPOINT", midp),
                               ("FIRST_DISTAL", distal), ("FIRST_FULL_SPAN", full)):
                if flag and name not in firsts:
                    firsts[name] = en[i]
            if beyond and prev_approach and not first_bar:
                ref["events"].append((key, kind, "GAP_BEYOND_REGION", en[i]))
            if touch:
                if not (prev_touch and prev_end == st[i]):
                    visit = [en[i], en[i], 0, False, False, False, False, 0, 0]
                    visits.append(visit)
                visit[1] = en[i]
                visit[2] += 1
                visit[3] |= pen
                visit[4] |= midp
                visit[5] |= distal
                visit[6] |= full
                visit[7] = max(visit[7], dep)
                visit[8] = max(visit[8], adv)
            nmd, nma = max(md, dep), max(ma, adv)
            if (first_bar and (nmd > 0 or nma > 0)) or (not first_bar and (nmd > md or nma > ma)):
                depth.append((key, kind, en[i], nmd, nma))
            md, ma = nmd, nma
            prev_touch, prev_end = touch, en[i]
            prev_approach = (lo_i > up) if bull else (hi_i < lo)
            first_bar = False
        for name, at in firsts.items():
            ref["events"].append((key, kind, name, at))
        for v in visits:
            ref["visits"].append((key, kind, *v))
        ref["depth"] += depth


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _ns(v):
    return None if v is None or (not isinstance(v, (int, np.integer)) and pd.isna(v)) else int(pd.Timestamp(v).value) \
        if not isinstance(v, (int, np.integer)) else int(v)


# Exactly which semantic fields the independent reference reproduces (object identity = timeframe, direction and
# source bar end).  Columns not listed (ids / hashes, refs, contract / basis labels, price floats derived from ticks,
# evidence rows, entities / M7A transitions) are checked by invariants, schema validation and prefix comparison.
COMPARED_FIELDS = {
    "episodes": "timeframe; direction; anchor_swing_id; status; decided_at; reason",
    "blocks": "block key; ordinary_available_at; lower_ticks; upper_ticks; formation_fvg_id",
    "lifecycle": "block key; from_state; to_state; at; reason",
    "motifs": "block key; outcome; reason; a_swing_id; c_swing_id; raid_observed",
    "stages": "block key; stage_kind; direction; available_at; ended_at; end_reason",
    "interactions": "block key; stage_kind; kind (first events, gap-beyond); at",
    "visits": "block key; stage_kind; started_at; ended_at; bars; penetrated; midpoint / distal / full-span observed; "
              "max interior depth; max adverse excursion",
    "depth_versions": "block key; stage_kind; at; running max interior depth; running max adverse excursion",
}


def reconcile(run, ref) -> pd.DataFrame:
    E = run.engine
    tfs = set(ref["timeframes"])
    reg = E.regions.set_index("source_region_id")
    blocks = E.blocks[E.blocks["timeframe"].isin(tfs)]
    key_of = {}
    for b in blocks.itertuples(index=False):
        r = reg.loc[b.source_region_id]
        key_of[b.block_id] = (b.timeframe, b.ordinary_direction, r["source_bar_end"].value)
    rows = []
    order = [t for t in ("1m", "5m", "15m", "1H", "4H", "1D") if t in tfs] + sorted(tfs - {"1m", "5m", "15m", "1H", "4H", "1D"})

    def tf_of(item):
        head = item[0]
        return head if isinstance(head, str) else head[0]      # episodes: tf first; others: block key first

    def add(cat, expected, actual):
        for tf in order:                                        # every category x timeframe, zero cells kept
            e = Counter(x for x in expected if tf_of(x) == tf)
            a = Counter(x for x in actual if tf_of(x) == tf)
            rows.append({"category": cat, "timeframe": tf, "reference": sum(e.values()), "production": sum(a.values()),
                         "missing": sum((e - a).values()), "extra": sum((a - e).values()),
                         "compared_fields": COMPARED_FIELDS[cat]})
    ep = E.episodes[E.episodes["timeframe"].isin(tfs)]
    status_map = {"TERMINATED": "TERMINATED"}
    add("episodes", [(t, d, a, s, _ns(at), r) for t, d, a, s, at, r in ref["episodes"]],
        [(r.timeframe, r.direction, r.anchor_swing_id, status_map.get(r.status, r.status), _ns(r.decided_at),
          None if pd.isna(r.reason) else r.reason) for r in ep.itertuples(index=False)])
    add("blocks", [(k, at, lo, up, f) for k, at, lo, up, f in ref["blocks"]],
        [(key_of[b.block_id], b.ordinary_available_at.value, int(reg.loc[b.source_region_id, "lower_ticks"]),
          int(reg.loc[b.source_region_id, "upper_ticks"]), b.formation_fvg_id) for b in blocks.itertuples(index=False)])
    lc = E.lifecycle[E.lifecycle["block_id"].isin(key_of)]
    add("lifecycle", [(k, f, t, _ns(at), r) for k, f, t, at, r in ref["changes"]],
        [(key_of[r.block_id], r.from_state, r.to_state, r.at.value, r.reason) for r in lc.itertuples(index=False)])
    mo = E.motifs[E.motifs["block_id"].isin(key_of)]
    prod_m = []
    for r in mo.itertuples(index=False):
        if r.outcome == "FAILED_AWAITING_CLASSIFICATION":
            prod_m.append((key_of[r.block_id], "UNRESOLVED", None))
        elif r.outcome == "FAILED_FINAL":
            prod_m.append((key_of[r.block_id], "FAILED_FINAL", r.reason, None if pd.isna(r.a_swing_id) else r.a_swing_id,
                           None if pd.isna(r.c_swing_id) else r.c_swing_id, bool(r.raid_observed)))
        else:
            prod_m.append((key_of[r.block_id], r.outcome, None, r.a_swing_id, r.c_swing_id, bool(r.raid_observed)))
    add("motifs", ref["motifs"], prod_m)
    st = E.stages[E.stages["block_id"].isin(key_of)]
    stage_key = {r.stage_id: (key_of[r.block_id], r.stage_kind) for r in st.itertuples(index=False)}
    add("stages", [(k, kind, d, _ns(a), _ns(e), w) for k, kind, d, a, e, w in ref["stages"]],
        [(key_of[r.block_id], r.stage_kind, r.direction, r.available_at.value, _ns(r.ended_at),
          None if pd.isna(r.end_reason) else r.end_reason) for r in st.itertuples(index=False)])
    if "events" in ref and ref.get("interactions_checked"):
        it = E.interactions[E.interactions["stage_id"].isin(stage_key)]
        add("interactions", [(k, kind, name, _ns(at)) for k, kind, name, at in ref["events"]],
            [(*stage_key[r.stage_id], r.kind, r.at.value) for r in it.itertuples(index=False)])
        vi = E.visits[E.visits["stage_id"].isin(stage_key)]
        add("visits", [(k, kind, *rest) for k, kind, *rest in ref["visits"]],
            [(*stage_key[r.stage_id], r.started_at.value, r.ended_at.value, int(r.bars), bool(r.penetrated),
              bool(r.midpoint_observed), bool(r.distal_observed), bool(r.full_span_observed),
              int(r.max_interior_depth_ticks), int(r.max_adverse_excursion_ticks)) for r in vi.itertuples(index=False)])
        dv = E.depth_versions[E.depth_versions["stage_id"].isin(stage_key)]
        add("depth_versions", ref["depth"],
            [(*stage_key[r.stage_id], r.at.value, int(r.max_interior_depth_ticks), int(r.max_adverse_excursion_ticks))
             for r in dv.itertuples(index=False)])
    return pd.DataFrame(rows)


def full_reference(run, timeframes=None, interactions_=True) -> dict:
    ref = reference(run, timeframes)
    if interactions_:
        reference_interactions(run, ref)
        ref["interactions_checked"] = True
    return ref


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def invariants(run) -> pd.DataFrame:
    E = run.engine
    res = []

    def rec(name, checked, bad):
        res.append({"invariant": name, "checked": int(checked), "violations": int(bad)})
    reg = E.regions.set_index("source_region_id")
    b = E.blocks.join(reg[["lower_ticks", "upper_ticks", "source_open_ticks", "source_high_ticks", "source_low_ticks",
                           "source_close_ticks", "body_ticks", "zone_midpoint_half_ticks",
                           "source_body_midpoint_half_ticks"]], on="source_region_id")
    bull = b["ordinary_direction"] == BULL
    geom = np.where(bull, (b["lower_ticks"] == b["source_low_ticks"]) & (b["upper_ticks"] == b["source_open_ticks"]),
                    (b["lower_ticks"] == b["source_open_ticks"]) & (b["upper_ticks"] == b["source_high_ticks"]))
    bad = int((~geom).sum()) + int((b["zone_midpoint_half_ticks"] != b["lower_ticks"] + b["upper_ticks"]).sum())
    bad += int((b["source_body_midpoint_half_ticks"] != b["source_open_ticks"] + b["source_close_ticks"]).sum())
    rec("OB-INV-1 open-to-wick geometry, exact zone and body midpoints", len(b), bad)
    colour = np.where(bull, b["source_close_ticks"] < b["source_open_ticks"], b["source_close_ticks"] > b["source_open_ticks"])
    rec("OB-INV-2 single source: opposite colour, body >= 4 ticks", len(b), int((~colour).sum() + (b["body_ticks"] < 4).sum()))
    rec("OB-INV-3 one block per source region; unique ids", len(b),
        int(b["source_region_id"].duplicated().sum() + b["block_id"].duplicated().sum()
            + E.stages["stage_id"].duplicated().sum() + E.episodes["episode_id"].duplicated().sum()))
    ep = E.episodes
    adm = ep[ep["status"] == "ADMITTED"]
    rec("OB-INV-4 one admission per episode; admitted episodes link one block", len(adm),
        int(adm["block_id"].isna().sum() + adm["block_id"].duplicated().sum()
            + (~adm["block_id"].isin(set(b["block_id"]))).sum()))
    st = E.stages
    succ = st[st["stage_kind"] != "ORDINARY"]
    par = st[st["stage_kind"] == "ORDINARY"].set_index("block_id")
    bad = 0
    for r in succ.itertuples(index=False):
        p = par.loc[r.block_id] if r.block_id in par.index else None
        bad += p is None or r.predecessor_stage_id != p["stage_id"] or not (p["available_at"] < r.available_at) \
            or r.direction == p["direction"] or pd.isna(p["ended_at"]) or r.available_at < p["ended_at"]
    rec("OB-INV-5 every successor has an earlier ordinary parent, reversed direction, after its failure", len(succ), bad)
    rec("OB-INV-6 at most one successor stage per block", len(succ), int(succ["block_id"].duplicated().sum()))
    # stage availability >= every input; no interaction before stage availability
    i = E.interactions.join(st.set_index("stage_id")[["available_at", "ended_at"]], on="stage_id", rsuffix="_stage")
    bad = 0
    if len(i):
        bad = int(((i["at"] - pd.Timedelta(minutes=1)) < i["available_at"]).sum()
                  + (i["ended_at"].notna() & (i["at"] > i["ended_at"])).sum())
    rec("OB-INV-7 interactions only from bars after stage availability and before its end", len(i), bad)
    blk = b.set_index("block_id")
    eps = ep.set_index("episode_id")
    bad = 0
    for r in b.itertuples(index=False):
        e_ = eps.loc[r.episode_id]
        bad += not (r.ordinary_available_at >= e_["opened_at"] and r.ordinary_available_at >= r.validation_close_at)
    rec("OB-INV-8 ordinary availability >= swing confirmation and validation close", len(b), bad)
    lc = E.lifecycle
    rec("OB-INV-9 one logical change per block and instant", len(lc), int(lc.duplicated(["block_id", "at"]).sum()))
    ev = E.evidence.join(eps["opened_at"], on="episode_id")
    rec("OB-INV-14 no episode evidence known before its episode opened", len(ev),
        int((ev["known_at"] < ev["opened_at"]).sum()) if len(ev) else 0)
    from src.ict_blocks.engine import block_namespace
    from src.state.contract import validate_transitions
    bad = 0
    try:
        if len(E.transitions):
            validate_transitions(E.transitions, block_namespace(), E.entities)
    except Exception:          # noqa: BLE001
        bad = 1
    rec("OB-INV-10 M7A lifecycle validity", 1, bad)
    seq = lc.sort_values(["block_id", "at"], kind="mergesort").groupby("block_id")["to_state"].apply(tuple) if len(lc) else []
    ok_seqs = 0
    for s_ in (seq if len(lc) else []):
        ok_seqs += any(x in ("BREAKER", "MITIGATION") for x in s_) and sum(x in ("BREAKER", "MITIGATION") for x in s_) > 1
    rec("OB-INV-11 no repeated inversion", len(seq) if len(lc) else 0, ok_seqs)
    mo = E.motifs
    good = mo[mo["outcome"].isin(["BREAKER", "MITIGATION"])]
    bad = 0
    for r in good.itertuples(index=False):
        bullish_parent = r.successor_direction == BEAR
        gt = (lambda p, q: p > q) if bullish_parent else (lambda p, q: p < q)
        if r.outcome == "BREAKER":
            bad += not gt(r.c_price_ticks, r.a_price_ticks)
        else:
            bad += not (gt(r.a_price_ticks, r.c_price_ticks) and not r.raid_observed)
    rec("OB-INV-12 BREAKER: C beyond A; MITIGATION: C short of A without raid", len(good), bad)
    rec("OB-INV-13 no liquidity / structure inputs in the manifest", 1,
        int(any(k for k in run.manifest if "liquidity" in k or "structure" in k)))
    return pd.DataFrame(res)


# ---------------------------------------------------------------------------
# Prefix equivalence (payload-level, as-of projection)
# ---------------------------------------------------------------------------


def canonical(value):
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return ("T", value.value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) else (int(value) if float(value).is_integer() else float(value))
    if isinstance(value, (list, tuple, np.ndarray)):
        return tuple(canonical(v) for v in value)
    return str(value)


def canonical_rows(frame: pd.DataFrame) -> list:
    cols = sorted(frame.columns)
    if frame.empty:
        return []
    values = [[canonical(v) for v in frame[c].tolist()] for c in cols]
    return [tuple(zip(cols, row)) for row in zip(*values)]


PREFIX_TABLES = {      # table -> (time column, identity key)
    "regions": ("source_bar_end", ["source_region_id"]),
    "evidence": ("known_at", ["episode_id", "kind", "ref"]),
    "blocks": ("ordinary_available_at", ["block_id"]),
    "lifecycle": ("at", ["block_id", "at"]),
    "motifs": ("break_observed_at", ["motif_id"]),
    "visits": ("started_at", ["visit_id"]),
    "interactions": ("at", ["event_id"]),
    "depth_versions": ("at", ["stage_id", "at"]),
    "transitions": ("transition_at", ["transition_id"]),
    "entities": ("available_at", ["entity_id"]),
    "warnings": ("at", ["at", "reason"]),
    "pending": ("since_at", ["block_id"]),
}


def visits_as_of(run, cut) -> pd.DataFrame:
    """Every visit started by ``cut`` as observable at ``cut``: its 1m bars ending at or before ``cut``, with
    membership, duration, flags and aggregates recomputed from those observations (scalar; independent of the
    production aggregation).  Visit rows describe the observed extent so far, so an ongoing visit is compared
    through the cutoff rather than excluded."""
    from src.ict_blocks.engine import VISIT_COLUMNS
    E = run.engine
    v = E.visits[E.visits["started_at"] <= cut]
    if v.empty:
        return v
    st = E.stages.set_index("stage_id")
    reg = E.regions.set_index("source_region_id")
    blk = E.blocks.set_index("block_id")["source_region_id"]
    rows = []
    cut_ns = int(cut.value)
    for r in v.itertuples(index=False):
        g = reg.loc[blk.loc[r.block_id]]
        lo, up = int(g["lower_ticks"]), int(g["upper_ticks"])
        bull = st.loc[r.stage_id, "direction"] == BULL
        a_ns = r.started_at.value
        ep = next(e for e in run.tape.episodes if len(e.end) and e.end[0] <= a_ns <= e.end[-1])
        ends, L, H = ep.end.tolist(), ep.l.tolist(), ep.h.tolist()
        i = ends.index(a_ns)
        last = min(r.ended_at.value, cut_ns)
        n = pen = midp = dist = full = False
        bars, dep, adv = 0, 0, 0
        while i < len(ends) and ends[i] <= last:
            lo_i, hi_i = L[i], H[i]
            bars += 1
            pen |= hi_i > lo and lo_i < up
            midp |= 2 * lo_i <= lo + up <= 2 * hi_i
            far = lo if bull else up
            dist |= lo_i <= far <= hi_i
            full |= lo_i <= lo and hi_i >= up
            dep = max(dep, max(0, min(up - lo, (up - max(lo_i, lo)) if bull else (min(hi_i, up) - lo))))
            adv = max(adv, max(0, lo - lo_i) if bull else max(0, hi_i - up))
            n = ends[i]
            i += 1
        rows.append((r.visit_id, r.stage_id, r.block_id, r.visit_seq, r.started_at, pd.Timestamp(n, tz="UTC"), bars,
                     bool(pen), bool(midp), bool(dist), bool(full), dep, adv))
    out = pd.DataFrame(rows, columns=list(VISIT_COLUMNS))
    for c in ("started_at", "ended_at"):
        out[c] = pd.to_datetime(out[c], utc=True)
    return out


def project_as_of(run, cut) -> dict:
    from src.ict_blocks.pipeline import episodes_as_of, stages_as_of
    E = run.engine
    out = {"episodes": episodes_as_of(run, cut), "stages": stages_as_of(run, cut)}
    blocks = E.blocks[E.blocks["ordinary_available_at"] <= cut]
    for name, (col, _key) in PREFIX_TABLES.items():
        f = getattr(E, name)
        out[name] = f[f[col] <= cut] if len(f) else f
    out["regions"] = E.regions[E.regions["source_region_id"].isin(set(blocks["source_region_id"]))]
    m = E.motifs[E.motifs["break_observed_at"] <= cut].copy()
    if len(m):         # motif fields resolved after the cutoff are not yet known
        later = (m["resolved_at"].isna()) | (m["resolved_at"] > cut)
        for col in ("resolved_at", "successor_available_at"):
            m[col] = m[col].astype(object)
            m.loc[later, col] = None
            m[col] = pd.to_datetime(m[col], utc=True)
        m["outcome"] = m["outcome"].astype(object)
        m.loc[later, "outcome"] = "FAILED_AWAITING_CLASSIFICATION"
        for col in ("classification", "reason", "c_swing_id", "c_price_ticks", "c_candidate_ids"):
            m[col] = m[col].astype(object)
            m.loc[later, col] = None
    out["motifs"] = m
    out["visits"] = visits_as_of(run, cut)
    return out


def prefix_mismatches(full, part) -> dict:
    cut = pd.Timestamp(part.manifest["replay_cutoff"])
    exp = project_as_of(full, cut)
    out = {}
    for name in ["episodes", "stages"] + list(PREFIX_TABLES):
        a = exp[name]
        b = getattr(part.engine, name)
        ra, rb = Counter(canonical_rows(a)), Counter(canonical_rows(b))
        out[name] = sum(((ra - rb) + (rb - ra)).values())
        key = PREFIX_TABLES.get(name, (None, ["episode_id"] if name == "episodes" else ["stage_id"]))[1]
        out[name + "_duplicate_ids"] = sum(int(f.duplicated(key).sum()) for f in (a, b) if len(f))
        col = PREFIX_TABLES.get(name, ("opened_at" if name == "episodes" else "available_at",))[0]
        out[name + "_future_rows"] = int((b[col] > cut).sum()) if len(b) else 0
    from src.ict_blocks.pipeline import active_blocks, discovery_status
    for name, f in (("view_active_blocks", active_blocks), ("view_discovery_status", discovery_status)):
        ra, rb = canonical_rows(f(full, cut)), canonical_rows(f(part, cut))
        out[name] = sum(x != y for x, y in zip(ra, rb)) + abs(len(ra) - len(rb))
    return out
