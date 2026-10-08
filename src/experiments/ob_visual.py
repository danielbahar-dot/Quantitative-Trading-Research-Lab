"""Order Block / Breaker / Mitigation — OB-I5 visual validation package (local HTML with prices; price-free manifest).

Each case shows the block's own-timeframe candles with the source candle outlined, the swing source spans and their
confirmation markers (A / B / C labelled for motifs), the formation FVG box, the ordinary epoch and any successor
epoch drawn separately under the same block_id (the successor box starts at its own, later availability), the
zone midpoint, availability markers and the focus instant.  Tables: source candle and geometry (actionable
open-to-wick zone vs source body) → discovery episode and evidence → motif → lifecycle → stage-specific
interactions, with pre-state at the focus bar start, evidence and post-state at its close.  Times are New York.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import html
import json

import numpy as np
import pandas as pd

from src.experiments.fvg_visual import STYLE, capped, fmt_p, fmt_t, table

MAX_BARS = 60


@dataclass
class Case:
    case_id: str
    title: str
    category: str
    source: str
    run_key: str
    block_id: str | None
    focus: pd.Timestamp
    note: str
    episode_id: str | None = None
    tables: list = field(default_factory=list)
    refs: dict = field(default_factory=dict)


class Facts:
    def __init__(self, run):
        self.run = run
        self.tick = Decimal(run.manifest["tick_size"])
        E = run.engine
        self.blocks = E.blocks.set_index("block_id")
        self.regions = E.regions.set_index("source_region_id")
        self.episodes = E.episodes.set_index("episode_id")
        self.swing_ix = {}
        for tf, per in run.swings.items():
            for sws in per.values():
                for s in sws:
                    self.swing_ix[s.swing_id] = (tf, s)

    def p(self, ticks):
        return None if ticks is None or pd.isna(ticks) else float(Decimal(int(ticks)) * self.tick)

    def bars(self, tf, t0, t1):
        out = []
        for seg in self.run.obs[tf].segments:
            lo = int(np.searchsorted(seg["end"], pd.Timestamp(t0).value, side="left"))
            hi = int(np.searchsorted(seg["end"], pd.Timestamp(t1).value, side="right"))
            for k in range(lo, hi):
                out.append((int(seg["start"][k]), int(seg["end"][k]), self.p(seg["o"][k]), self.p(seg["h"][k]),
                            self.p(seg["l"][k]), self.p(seg["c"][k])))
        return out

    def swing_rows(self, ids):
        rows = []
        for label, sid in ids:
            if sid is None or (not isinstance(sid, str)) or sid not in self.swing_ix:
                continue
            tf, s = self.swing_ix[sid]
            seg = self.run.obs[tf].segments[s.seg]
            rows.append((label, s, int(seg["start"][s.a]), int(seg["end"][s.b]), s.available_ns, self.p(s.price)))
        return rows


def chart(f: Facts, case: Case, W=980, H=380) -> str:
    if case.block_id is None and case.episode_id is None:
        return ""
    ep = f.episodes.loc[case.episode_id] if case.episode_id else f.episodes.loc[f.blocks.loc[case.block_id, "episode_id"]]
    tf = ep["timeframe"]
    _, anchor = f.swing_ix[ep["anchor_swing_id"]]
    seg = f.run.obs[tf].segments[anchor.seg]
    from src.fvg.formation import timeframe_spec
    minutes = timeframe_spec(tf).minutes or 1380
    src_end = int(seg["end"][anchor.b])
    t0 = pd.Timestamp(src_end, tz="UTC") - pd.Timedelta(minutes=minutes * 8)
    t1 = max(case.focus, pd.Timestamp(src_end, tz="UTC")) + pd.Timedelta(minutes=minutes * 5)
    bars = f.bars(tf, t0, t1)
    if len(bars) > MAX_BARS:
        idx = int(np.searchsorted([b[1] for b in bars], case.focus.value))
        lo = max(0, min(idx - MAX_BARS // 2, len(bars) - MAX_BARS))
        lo = min(lo, max(0, int(np.searchsorted([b[1] for b in bars], src_end)) - 4))
        bars = bars[lo:lo + MAX_BARS]
    if not bars:
        return "<p class='note'>no bars in window</p>"
    ts, te = bars[0][0], bars[-1][1]
    boxes = []
    motif = None
    if case.block_id is not None:
        b = f.blocks.loc[case.block_id]
        r = f.regions.loc[b["source_region_id"]]
        st = f.run.engine.stages[f.run.engine.stages["block_id"] == case.block_id]
        for s in st.itertuples():
            boxes.append(("ord" if s.stage_kind == "ORDINARY" else "succ", r["lower"], r["upper"], r["zone_midpoint"],
                          s.available_at.value, None if pd.isna(s.ended_at) else s.ended_at.value,
                          f"{s.stage_kind} {s.direction[:4]}"))
        z = f.run.fvg_zones.set_index("zone_id").loc[b["formation_fvg_id"]]
        boxes.append(("fvg", z["lower"], z["upper"], z["midpoint"], z["available_at"].value, None, "formation FVG"))
        mo = f.run.engine.motifs[f.run.engine.motifs["block_id"] == case.block_id]
        motif = mo.iloc[0] if len(mo) else None
    prices = [x[3] for x in bars] + [x[4] for x in bars] + [x[1] for x in boxes] + [x[2] for x in boxes]
    lo_p, hi_p = min(prices), max(prices)
    pad = max((hi_p - lo_p) * 0.06, 0.5)
    lo_p, hi_p = lo_p - pad, hi_p + pad
    L, R, T, B = 74, 160, 14, 30

    def x(ns):
        ns = min(max(ns, ts), te)
        return L + (W - L - R) * (ns - ts) / (te - ts)

    def y(p):
        return T + (H - T - B) * (hi_p - p) / (hi_p - lo_p)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for k in range(6):
        p = lo_p + (hi_p - lo_p) * k / 5
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(p):.1f}" y2="{y(p):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{y(p) + 4:.1f}" class="ax" text-anchor="end">{p:,.2f}</text>')
    swings = [("B" if motif is not None else "anchor", ep["anchor_swing_id"])]
    if motif is not None:
        swings += [("A", motif["a_swing_id"]), ("C", motif["c_swing_id"])]
    for label, s, s0, s1, av, price in f.swing_rows(swings):
        out.append(f'<rect x="{x(s0):.1f}" y="{T}" width="{max(x(s1) - x(s0), 2):.1f}" height="{H - T - B}" class="span"/>'
                   f'<text x="{x(s1):.1f}" y="{y(price) + (-6 if s.orientation == "UPPER" else 14):.1f}" class="lab">'
                   f'{html.escape(label)} {fmt_p(price)}</text>')
    bw = max(2.0, (W - L - R) / len(bars) * 0.6)
    for s0, e0, o, h, l, c in bars:
        cx = (x(s0) + x(e0)) / 2
        cls = "up" if c > o else ("dn" if c < o else "dj")
        src = " c2" if e0 == src_end else ""
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(h):.1f}" y2="{y(l):.1f}" class="wick {cls}"/>'
                   f'<rect x="{cx - bw / 2:.1f}" y="{min(y(o), y(c)):.1f}" width="{bw:.1f}" '
                   f'height="{max(abs(y(o) - y(c)), 1):.1f}" class="body {cls}{src}"/>')
    for kind, lo, up, mid, a, b_, label in boxes:
        xa, xb = x(a), x(te if b_ is None else b_)
        klass = {"ord": "zone", "succ": "bpr", "fvg": "fvgbox"}[kind]
        out.append(f'<rect x="{xa:.1f}" y="{y(up):.1f}" width="{max(xb - xa, 2):.1f}" height="{max(y(lo) - y(up), 1):.1f}" class="{klass}"/>'
                   f'<line x1="{xa:.1f}" x2="{xb:.1f}" y1="{y(mid):.1f}" y2="{y(mid):.1f}" class="mid"/>'
                   f'<text x="{W - R + 4}" y="{y(up) + 4:.1f}" class="lab">{html.escape(label)} {fmt_p(lo)}–{fmt_p(up)}</text>')
    marks = [(int(pd.Timestamp(ep["opened_at"]).value), "swing confirmed")]
    if case.block_id is not None:
        for s in f.run.engine.lifecycle[f.run.engine.lifecycle["block_id"] == case.block_id].itertuples():
            marks.append((s.at.value, s.to_state.lower()))
        marks.append((f.blocks.loc[case.block_id, "ordinary_available_at"].value, "ordinary avail"))
    elif not pd.isna(ep["decided_at"]):
        marks.append((pd.Timestamp(ep["decided_at"]).value, ep["status"].lower()))
    used = {}
    for ns, label in sorted(marks):
        if not ts <= ns <= te:
            continue
        row = used.setdefault(round(x(ns)), len(used) % 4)
        out.append(f'<line x1="{x(ns):.1f}" x2="{x(ns):.1f}" y1="{T}" y2="{H - B}" class="mark"/>'
                   f'<text x="{x(ns) + 2:.1f}" y="{H - B - 6 - 11 * row:.1f}" class="lab mark">▲ {html.escape(label)}</text>')
    fx = x(case.focus.value)
    out.append(f'<line x1="{fx:.1f}" x2="{fx:.1f}" y1="{T}" y2="{H - B}" class="focus"/>'
               f'<text x="{L}" y="{H - 8}" class="ax">{fmt_t(pd.Timestamp(ts, tz="UTC"))}</text>'
               f'<text x="{W - R}" y="{H - 8}" class="ax" text-anchor="end">{fmt_t(pd.Timestamp(te, tz="UTC"))}</text>'
               f'<text x="{fx:.1f}" y="{H - 8}" class="ax" text-anchor="middle">focus {fmt_t(case.focus)} ({tf})</text></svg>')
    return "".join(out)


def _state_at(f: Facts, block_id, at):
    lc = f.run.engine.lifecycle
    lc = lc[(lc["block_id"] == block_id) & (lc["at"] <= at)]
    if len(lc):
        return lc.iloc[-1]["to_state"]
    return "ORDINARY" if f.blocks.loc[block_id, "ordinary_available_at"] <= at else "NOT YET ADMITTED"


def block_tables(f: Facts, case: Case) -> list:
    out = []
    bid, t = case.block_id, case.focus
    b = f.blocks.loc[bid]
    r = f.regions.loc[b["source_region_id"]]
    out.append(("Source candle and geometry (actionable open-to-wick zone vs source body)", [{
        "block": bid[:14], "timeframe": b["timeframe"], "ordinary direction": b["ordinary_direction"],
        "source bar": f"{fmt_t(r['source_bar_start'])} → {fmt_t(r['source_bar_end'])}",
        "O": fmt_p(f.p(r["source_open_ticks"])), "H": fmt_p(f.p(r["source_high_ticks"])),
        "L": fmt_p(f.p(r["source_low_ticks"])), "C": fmt_p(f.p(r["source_close_ticks"])), "body ticks": r["body_ticks"],
        "zone lower": fmt_p(r["lower"]), "zone upper": fmt_p(r["upper"]), "zone midpoint": fmt_p(r["zone_midpoint"]),
        "source body midpoint (not the zone midpoint)": fmt_p(r["source_body_midpoint"]), "width ticks": r["width_ticks"]}]))
    out += episode_tables(f, b["episode_id"])
    fz = f.run.fvg_zones.set_index("zone_id").loc[b["formation_fvg_id"]]
    out.append(("Formation FVG (departure evidence; no price overlap required)", [{
        "zone": b["formation_fvg_id"][:14], "direction": fz["original_direction"], "lower": fmt_p(fz["lower"]),
        "upper": fmt_p(fz["upper"]), "C2 end": fmt_t(fz["c2_end"]), "available": fmt_t(fz["available_at"]),
        "C2 beyond zone": bool(fz["lower_ticks"] > r["upper_ticks"]) if b["ordinary_direction"] == "BULLISH"
        else bool(fz["upper_ticks"] < r["lower_ticks"])}]))
    mo = f.run.engine.motifs[f.run.engine.motifs["block_id"] == bid]
    if len(mo):
        m = mo.iloc[0]
        rows = [{"role": lab, "swing": sid[:14] if isinstance(sid, str) else "—", "price": fmt_p(f.p(px)),
                 "confirmed": fmt_t(pd.Timestamp(f.swing_ix[sid][1].available_ns, tz="UTC")) if isinstance(sid, str) and sid in f.swing_ix else "—"}
                for lab, sid, px in (("A (prior extreme)", m["a_swing_id"], m["a_price_ticks"]),
                                     ("B (pinned anchor)", m["b_swing_id"], m["b_price_ticks"]),
                                     ("C (reversal swing)", m["c_swing_id"], m["c_price_ticks"]))]
        out.append(("Parent-pinned motif swings", rows))
        out.append(("Motif evidence and classification", [{
            "break x (close)": fmt_t(m["break_observed_at"]), "raid observed": m["raid_observed"],
            "first raid": fmt_t(m["first_raid_at"]), "C candidates": len(m["c_candidate_ids"] or ()),
            "resolved": fmt_t(m["resolved_at"]), "outcome": m["outcome"], "reason": m["reason"] or "—",
            "successor available": fmt_t(m["successor_available_at"])}]))
    pre = _state_at(f, bid, t - pd.Timedelta(minutes=1))
    post = _state_at(f, bid, t)
    out.append(("Pre-state at the focus bar start / post-state at its close", [{"pre": pre, "post": post}]))
    lc = f.run.engine.lifecycle[f.run.engine.lifecycle["block_id"] == bid]
    out.append(("Lifecycle (one logical change per instant)", [
        {"from": x_.from_state, "to": x_.to_state, "at": fmt_t(x_.at), "reason": x_.reason,
         "relative to focus": "at focus" if x_.at == t else ("before" if x_.at < t else "later")} for x_ in lc.itertuples()]))
    st = f.run.engine.stages[f.run.engine.stages["block_id"] == bid]
    out.append(("Stage epochs (same block_id)", [
        {"stage": s.stage_kind, "direction": s.direction, "available": fmt_t(s.available_at), "ended": fmt_t(s.ended_at),
         "end reason": s.end_reason or "—", "far boundary": s.far_boundary} for s in st.itertuples()]))
    for s in st.itertuples():
        it = f.run.engine.interactions[f.run.engine.interactions["stage_id"] == s.stage_id]
        out.append(capped(f"{s.stage_kind} stage interactions (1m, from its availability)", [
            {"event": x_.kind, "at": fmt_t(x_.at), "1m H/L": f"{fmt_p(f.p(x_.bar_high_ticks))} / {fmt_p(f.p(x_.bar_low_ticks))}",
             "relative to focus": "at focus" if x_.at == t else ("before" if x_.at < t else "later")}
            for x_ in it.itertuples()], 12, focal=lambda q: q["relative to focus"] == "at focus"))
        v = f.run.engine.visits[f.run.engine.visits["stage_id"] == s.stage_id]
        out.append(capped(f"{s.stage_kind} stage visits", [
            {"start": fmt_t(x_.started_at), "end": fmt_t(x_.ended_at), "bars": x_.bars, "penetrated": x_.penetrated,
             "midpoint observed": x_.midpoint_observed, "distal observed": x_.distal_observed,
             "max interior depth ticks": x_.max_interior_depth_ticks, "max adverse ticks": x_.max_adverse_excursion_ticks}
            for x_ in v.itertuples()], 10))
    return out


def episode_tables(f: Facts, eid) -> list:
    e = f.episodes.loc[eid]
    ev = f.run.engine.evidence[f.run.engine.evidence["episode_id"] == eid]
    return [("Discovery episode", [{"episode": eid[:14], "direction": e["direction"], "anchor swing": e["anchor_swing_id"][:14],
                                    "opened (swing confirmed)": fmt_t(e["opened_at"]), "status": e["status"],
                                    "decided": fmt_t(e["decided_at"]), "reason": e["reason"] if isinstance(e["reason"], str) else "—",
                                    "ownership deadline": fmt_t(e["ownership_deadline_at"])}]),
            ("Episode evidence (known-at times)", [{"kind": x_.kind, "observed": fmt_t(x_.observed_at), "known": fmt_t(x_.known_at),
                                                   "accepted": x_.accepted, "reason": x_.reason or "—"} for x_ in ev.itertuples()])]


def page(cases, facts_by_key, header) -> str:
    toc = "".join(f"<li><a href='#{c.case_id}'>{html.escape(c.case_id)} — {html.escape(c.title)}</a></li>" for c in cases)
    secs = []
    for c in cases:
        f = facts_by_key[c.run_key]
        tables = "".join(table(cap, rows) for cap, rows in c.tables)
        secs.append(f"<section id='{c.case_id}'><h2>{html.escape(c.case_id)} — {html.escape(c.title)}</h2>"
                    f"<p class='note'>{html.escape(c.category)} · {html.escape(c.source)}</p><p>{html.escape(c.note)}</p>"
                    f"{chart(f, c)}{tables}</section>")
    style = STYLE + ".fvgbox{fill:#f59e0b;opacity:.18;stroke:#f59e0b}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Order Block Validation</title><style>{style}</style></head><body>
<h1>Order Block / Breaker / Mitigation — OB-I5 visual validation</h1>
<p class="note">LOCAL ONLY — contains market prices (Git-ignored). Production pipeline (build_order_blocks), DEVELOPMENT and
isolated synthetic fixtures. Chart: own-timeframe candles; amber outline = the single source candle; shaded bands = swing
source spans with labels (anchor / A / B / C) at the swing price; blue box = ordinary epoch (open-to-wick zone) from its
availability; purple box = BREAKER / MITIGATION epoch of the same block from its own later availability; amber box = formation
FVG; dashed line = zone midpoint; ▲ = availability / lifecycle markers; dashed vertical = focus. Capped tables state displayed /
total counts. Machine evidence only; human visual approval pending.</p>
{table("Run", header)}<ol>{toc}</ol>{''.join(secs)}</body></html>"""


def manifest_rows(cases) -> list:
    return [{"case_id": c.case_id, "category": c.category, "title": c.title, "source": c.source,
             "focus_at": c.focus.isoformat(), "object_refs": json.dumps(c.refs, sort_keys=True)} for c in cases]


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------


def _pick(df):
    return None if df.empty else df.iloc[len(df) // 2]


def build_cases(run, run_key="dev", source="DEVELOPMENT", prefix="") -> list:
    f = Facts(run)
    E = run.engine
    cases = []

    def bcase(cid, title, cat, bid, focus, note):
        c = Case(prefix + cid, title, cat, source, run_key, bid, pd.Timestamp(focus), note,
                 refs={"block_id": bid})
        c.tables = block_tables(f, c)
        cases.append(c)

    def ecase(cid, title, cat, eid, focus, note):
        c = Case(prefix + cid, title, cat, source, run_key, None, pd.Timestamp(focus), note, episode_id=eid,
                 refs={"episode_id": eid})
        c.tables = episode_tables(f, eid)
        cases.append(c)
    b = E.blocks
    for tf in ("1m", "5m", "15m", "1H", "4H", "1D"):
        r = _pick(b[b["timeframe"] == tf])
        if r is not None:
            bcase(f"OB-{tf}", f"{tf} ordinary {r['ordinary_direction'].lower()} OB", "timeframe", r["block_id"],
                  r["ordinary_available_at"], "Terminal source candle, open-to-wick zone, FVG departure and validation close.")
    lc = E.lifecycle
    mo = E.motifs
    for outcome, cid, title in (("BREAKER", "BB", "Ordinary → BREAKER (raid above / below the prior extreme)"),
                                ("MITIGATION", "MB", "Ordinary → MITIGATION (failure swing, no raid)")):
        for d0 in ("BULLISH", "BEARISH"):
            m = mo[(mo["outcome"] == outcome) & (mo["successor_direction"] != d0)]
            r = _pick(m)
            if r is not None:
                bcase(f"{cid}-{d0[:4]}", f"{title}, {d0.lower()} parent", "successor", r["block_id"],
                      r["successor_available_at"], "Successor inherits the exact interval, reverses direction and starts its "
                      "own interaction history at its availability (no conversion-bar retest).")
    for reason in ("NO_PRIOR_EXTREME", "NO_REVERSAL_SWING", "EQUAL_EXTREME", "RAID_WITH_LESS_EXTREME_C",
                   "QUALIFIED_BUT_INVALID_BEFORE_ADMISSION", "EQUAL_EXTREME_WITH_RAID"):
        r = _pick(mo[mo["reason"] == reason])
        if r is not None:
            bcase(f"FAIL-{reason}", f"Ordinary failure without successor: {reason}", "failure", r["block_id"],
                  r["break_observed_at"], "Ordinary actionability ends at the failure close; no BB / MB stage.")
    st = E.stages
    succ = st[st["stage_kind"] != "ORDINARY"]
    conc = st[(st["stage_kind"] == "ORDINARY") & st["available_at"].isin(set(succ["available_at"]))]
    if len(conc):
        r = conc.iloc[0]
        bcase("CONCURRENT", "Independent opposing ordinary OB admitted at a successor's close", "independence",
              r["block_id"], r["available_at"], "A separately formed opposing ordinary OB is its own block, not a successor.")
    ep = E.episodes
    for reason, cid in (("SOURCE_BODY_LT_4_TICKS", "REJ-BODY"), ("SOURCE_DIRECTION_MISMATCH", "REJ-DIR"),
                        ("NO_DEPARTURE_FVG_IN_WINDOW", "REJ-NOFVG"), ("NOT_VALIDATED_IN_WINDOW", "REJ-NOVAL"),
                        ("ALREADY_INVALID_BEFORE_ADMISSION", "REJ-INVALID")):
        r = _pick(ep[ep["reason"] == reason])
        if r is not None:
            ecase(cid, f"Rejected episode: {reason}", "rejection", r["episode_id"], r["decided_at"],
                  "The last source candle decides; no earlier candle is substituted.")
    r = _pick(ep[ep["status"] == "SUPERSEDED"])
    if r is not None:
        ecase("SUPERSEDED", "Unadmitted episode superseded by a new same-side swing", "discovery", r["episode_id"],
              r["decided_at"], "Supersession is prospective, at the new swing's confirmation.")
    it = E.interactions
    g = it[it["kind"] == "GAP_BEYOND_REGION"]
    if len(g):
        x = g.iloc[len(g) // 2]
        bid = x["block_id"]
        bcase("GAP-BEYOND", "Gap-beyond evidence (no invented fill inside the zone)", "interaction", bid, x["at"],
              "The 1m range lies wholly beyond the far boundary after an approach-side bar.")
    m_ = it[it["kind"] == "FIRST_MIDPOINT"]
    if len(m_):
        x = m_.iloc[len(m_) // 2]
        bcase("MIDPOINT", "Zone midpoint observed (exact, half-tick)", "interaction", x["block_id"], x["at"],
              "Zone midpoint of the open-to-wick interval — not the source-body midpoint.")
    t_ = lc[lc["to_state"] == "TERMINATED_DATA_GAP"]
    if len(t_):
        x = t_.iloc[len(t_) // 2]
        bcase("DATA-GAP", "Termination at a 1m data-gap onset", "data", x["block_id"], x["at"],
              "Every live stage ends at the onset; nothing is inferred inside the gap.")
    return cases


def synthetic_cases(build) -> tuple[list, dict]:
    """``build(name) -> run`` for the isolated synthetic fixtures (tests/ob_fixtures.py equivalents)."""
    cases, facts = [], {}
    for name, title in (("BREAKER", "SYN Breaker with inherited interval"), ("MITIGATION", "SYN Mitigation"),
                        ("EQUAL", "SYN equal extreme (unclassified)"), ("RAID_LOWER_C", "SYN outside reversal bar: raid at x, less extreme C"),
                        ("N2_DELAYED", "SYN N = 2 delayed successor availability"),
                        ("N2_INVALID", "SYN N = 2 qualified but invalid before admission"),
                        ("CONCURRENT", "SYN concurrent independent ordinary OB and Breaker"),
                        ("BODY3", "SYN 3-tick last candle rejected (no fallback)"), ("ROLL", "SYN pure roll → PENDING_ADJUSTMENT")):
        run = build(name)
        f = Facts(run)
        facts["SYN-" + name] = f
        sub = build_cases(run, run_key="SYN-" + name, source="SYNTHETIC (isolated fixture)", prefix=f"SYN-{name}-")
        wanted = {"BREAKER": ("successor",), "MITIGATION": ("successor",), "EQUAL": ("failure",),
                  "RAID_LOWER_C": ("failure",), "N2_DELAYED": ("successor",), "N2_INVALID": ("failure",),
                  "CONCURRENT": ("independence",), "BODY3": ("rejection",), "ROLL": ()}[name]
        keep = [c for c in sub if c.category in wanted and "NO_PRIOR_EXTREME" not in c.case_id
                and (name != "BODY3" or c.case_id.endswith("REJ-BODY"))]
        if name == "ROLL":
            b = run.engine.blocks
            if len(b):
                c = Case(f"SYN-{name}", title, "data", "SYNTHETIC (isolated fixture)", "SYN-" + name, b.iloc[0]["block_id"],
                         run.engine.pending["since_at"].iloc[0] if len(run.engine.pending) else b.iloc[0]["ordinary_available_at"],
                         "Old-contract stages become PENDING_ADJUSTMENT; no raw cross-contract price test.",
                         refs={"fixture": name})
                c.tables = block_tables(f, c)
                keep = [c]
        for c in keep:
            c.title = f"{title} — {c.title}"
        cases += keep
    return cases, facts
