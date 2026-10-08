"""FVG / IFVG / BPR — FVG-I5 visual validation package (local HTML with prices; price-free manifest).

Each case renders the zone's own-timeframe candles with the C1–C3 source span
shaded, the C2 body outlined, the exact zone / BPR bounds and midpoint, and
availability markers (formation, conversion, BPR, association).  Tables show
the immutable facts and formation candles, then pre-state at s(m) → evidence
at m → post-state at e(m) → later lifecycle, stage-separated mitigation,
relationship / overlap groups and grade components.  Times are New York.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import html
import json

import numpy as np
import pandas as pd

NY = "America/New_York"
MAX_BARS = 60


def fmt_t(v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "—"
    return pd.Timestamp(v).tz_convert(NY).strftime("%Y-%m-%d %H:%M")


def fmt_p(v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "—"
    return f"{float(v):,.3f}".rstrip("0").rstrip(".") if float(v) * 8 % 2 else f"{float(v):,.2f}"


@dataclass
class Case:
    case_id: str
    title: str
    category: str
    source: str
    run_key: str
    zone_id: str | None
    focus: pd.Timestamp
    note: str
    extra_zones: list = field(default_factory=list)
    bpr_ids: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    refs: dict = field(default_factory=dict)


class Facts:
    def __init__(self, run):
        self.run = run
        self.tick = Decimal(run.manifest["tick_size"])
        self.z = run.zones.set_index("zone_id")
        self.e = run.engine

    def p(self, ticks):
        return None if ticks is None or pd.isna(ticks) else float(Decimal(int(ticks)) * self.tick)

    def tf_bars(self, tf, t0, t1):
        out = []
        for seg in self.run.tf_data[tf].segments:
            lo = int(np.searchsorted(seg["end"], pd.Timestamp(t0).value, side="left"))
            hi = int(np.searchsorted(seg["end"], pd.Timestamp(t1).value, side="right"))
            for k in range(lo, hi):
                out.append((int(seg["start"][k]), int(seg["end"][k]), self.p(seg["o"][k]), self.p(seg["h"][k]),
                            self.p(seg["l"][k]), self.p(seg["c"][k])))
        return out

    def bar_1m(self, at):
        loc = self.run.tape.locate(pd.Timestamp(at).value)
        if loc is None:
            return {"1m bar": fmt_t(at), "status": "absent"}
        ep = self.run.tape.episodes[loc[0]]
        k = loc[1]
        return {"1m bar ending": fmt_t(at), "O": fmt_p(self.p(ep.o[k])), "H": fmt_p(self.p(ep.h[k])),
                "L": fmt_p(self.p(ep.l[k])), "C": fmt_p(self.p(ep.c[k])), "contract": ep.contract}

    def stage_at(self, zid, at):
        st = self.e.stages[self.e.stages["zone_id"] == zid]
        for r in st.itertuples():
            if r.stage_start <= at and (pd.isna(r.stage_end) or r.stage_end > at):
                return r.stage, r.current_direction
        tr = self.e.zone_transitions[(self.e.zone_transitions["entity_id"] == zid) & (self.e.zone_transitions["transition_at"] <= at)]
        if len(tr):
            return tr.sort_values("transition_at")["new_state"].iloc[-1], None
        return ("NOT YET AVAILABLE", None) if at < self.z.loc[zid, "available_at"] else ("FVG", self.z.loc[zid, "original_direction"])


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


def chart(f: Facts, case: Case, W=980, H=360) -> str:
    zid = case.zone_id
    zones = ([zid] if zid else []) + list(case.extra_zones)
    if not zones:
        return ""
    tf = f.z.loc[zones[0], "timeframe"]
    z0 = f.z.loc[zones[0]]
    from src.fvg.formation import timeframe_spec
    minutes = timeframe_spec(tf).minutes or 1380
    t0 = min(f.z.loc[x, "span_start"] for x in zones) - pd.Timedelta(minutes=minutes * 6)
    t1 = max(case.focus, max(f.z.loc[x, "available_at"] for x in zones)) + pd.Timedelta(minutes=minutes * 6)
    bars = f.tf_bars(tf, t0, t1)
    if len(bars) > MAX_BARS:
        focus_ns = case.focus.value
        idx = int(np.searchsorted([b[1] for b in bars], focus_ns))
        lo = max(0, min(idx - MAX_BARS // 2, len(bars) - MAX_BARS))
        bars = bars[lo:lo + MAX_BARS]
    if not bars:
        return "<p class='note'>no bars in window</p>"
    ts, te = bars[0][0], bars[-1][1]
    rects = []
    for x in zones:
        z = f.z.loc[x]
        st = f.e.stages[f.e.stages["zone_id"] == x]
        end = st["stage_end"].max() if st["stage_end"].notna().all() else None
        rects.append(("zone", z["lower"], z["upper"], z["midpoint"], z["available_at"].value,
                      None if end is None else end.value, f"{z['timeframe']} {z['original_direction'][:4]}"))
    for bid in case.bpr_ids:
        b = f.e.bprs.set_index("bpr_id").loc[bid]
        rects.append(("bpr", b["lower"], b["upper"], b["midpoint"], b["available_at"].value,
                      None if pd.isna(b["exit_at"]) else b["exit_at"].value, f"{b['label']} {str(b['direction'])[:4]}"))
    prices = [b[3] for b in bars] + [b[4] for b in bars] + [r[1] for r in rects] + [r[2] for r in rects]
    lo_p, hi_p = min(prices), max(prices)
    pad = max((hi_p - lo_p) * 0.06, 0.5)
    lo_p, hi_p = lo_p - pad, hi_p + pad
    L, R, T, B = 74, 150, 14, 30

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
    # source spans (C1–C3) and C2 body outline
    for x_ in zones:
        z = f.z.loc[x_]
        xa, xb = x(z["span_start"].value), x(z["available_at"].value)
        out.append(f'<rect x="{xa:.1f}" y="{T}" width="{max(xb - xa, 2):.1f}" height="{H - T - B}" class="span"/>')
    bw = max(2.0, (W - L - R) / len(bars) * 0.6)
    c2_ends = {f.z.loc[x_, "c2_end"].value for x_ in zones}
    for s, e, o, h, l, c in bars:
        cx = (x(s) + x(e)) / 2
        cls = "up" if c > o else ("dn" if c < o else "dj")
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(h):.1f}" y2="{y(l):.1f}" class="wick {cls}"/>'
                   f'<rect x="{cx - bw / 2:.1f}" y="{min(y(o), y(c)):.1f}" width="{bw:.1f}" '
                   f'height="{max(abs(y(o) - y(c)), 1):.1f}" class="body {cls}{" c2" if e in c2_ends else ""}"/>')
    for kind, lo, up, mid, a, b_, label in rects:
        xa, xb = x(a), x(te if b_ is None else b_)
        out.append(f'<rect x="{xa:.1f}" y="{y(up):.1f}" width="{max(xb - xa, 2):.1f}" height="{max(y(lo) - y(up), 1):.1f}" class="{kind}"/>'
                   f'<line x1="{xa:.1f}" x2="{xb:.1f}" y1="{y(mid):.1f}" y2="{y(mid):.1f}" class="mid"/>'
                   f'<text x="{W - R + 4}" y="{y(up) + 4:.1f}" class="lab {kind}">{html.escape(label)} {fmt_p(lo)}–{fmt_p(up)}</text>'
                   f'<text x="{W - R + 4}" y="{y(mid) + 4:.1f}" class="lab mid">mid {fmt_p(mid)}</text>')
    marks = []
    for x_ in zones:
        marks.append((f.z.loc[x_, "available_at"].value, "formed"))
        tr = f.e.zone_transitions[f.e.zone_transitions["entity_id"] == x_]
        marks += [(r.transition_at.value, r.new_state.lower()) for r in tr.itertuples()]
    for bid in case.bpr_ids:
        marks.append((f.e.bprs.set_index("bpr_id").loc[bid, "available_at"].value, "bpr avail"))
    a = f.run.associations
    for r in a[a["zone_id"].isin(zones)].itertuples():
        marks.append((r.association_available_at.value, "assoc" + (" first" if r.is_first else "")))
    rows_used = {}
    for ns, label in sorted(marks):
        if not ts <= ns <= te:
            continue
        row = rows_used.setdefault(round(x(ns)), len(rows_used) % 4)
        out.append(f'<line x1="{x(ns):.1f}" x2="{x(ns):.1f}" y1="{T}" y2="{H - B}" class="mark"/>'
                   f'<text x="{x(ns) + 2:.1f}" y="{H - B - 6 - 11 * row:.1f}" class="lab mark">▲ {html.escape(label)}</text>')
    fx = x(case.focus.value)
    out.append(f'<line x1="{fx:.1f}" x2="{fx:.1f}" y1="{T}" y2="{H - B}" class="focus"/>'
               f'<text x="{L}" y="{H - 8}" class="ax">{fmt_t(pd.Timestamp(ts, tz="UTC"))}</text>'
               f'<text x="{W - R}" y="{H - 8}" class="ax" text-anchor="end">{fmt_t(pd.Timestamp(te, tz="UTC"))}</text>'
               f'<text x="{fx:.1f}" y="{H - 8}" class="ax" text-anchor="middle">focus {fmt_t(case.focus)} ({tf})</text></svg>')
    return "".join(out)


def table(caption, rows) -> str:
    if not rows:
        return f"<h4>{html.escape(caption)}</h4><p class='note'>none</p>"
    cols = list(dict.fromkeys(k for r in rows for k in r))
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<h4>{html.escape(caption)}</h4><div class='tw'><table><tr>{head}</tr>{body}</table></div>"


# ---------------------------------------------------------------------------
# Standard tables for a zone case
# ---------------------------------------------------------------------------


def zone_tables(f: Facts, case: Case) -> list:
    zid, t = case.zone_id, case.focus
    z = f.z.loc[zid]
    tables = []
    tables.append(("Immutable zone facts", [{
        "zone": zid[:14], "timeframe": z["timeframe"], "direction": z["original_direction"], "lower": fmt_p(z["lower"]),
        "upper": fmt_p(z["upper"]), "midpoint (exact)": fmt_p(z["midpoint"]), "width ticks": z["width_ticks"],
        "width points": z["width_points"], "C1 end": fmt_t(z["c1_end"]), "C2 end": fmt_t(z["c2_end"]),
        "available_at (C3 close)": fmt_t(z["available_at"]), "normalization": z["normalization_status"],
        "strength": "—" if pd.isna(z["strength_num"]) else f"{int(z['strength_num'])}/{int(z['strength_den'])} = {z['normalized_gap_strength']:.4f}",
        "baseline ATR ticks": "—" if pd.isna(z["baseline_atr_ticks"]) else f"{z['baseline_atr_ticks']:.3f}"}]))
    seg = None
    for s in f.run.tf_data[z["timeframe"]].segments:
        k = int(np.searchsorted(s["end"], z["available_at"].value))
        if k < len(s["end"]) and s["end"][k] == z["available_at"].value:
            seg = (s, k)
    if seg:
        s, k3 = seg
        rows = []
        for name, k in (("C1", k3 - 2), ("C2", k3 - 1), ("C3", k3)):
            o, c = f.p(s["o"][k]), f.p(s["c"][k])
            rows.append({"candle": name, "end": fmt_t(pd.Timestamp(int(s["end"][k]), tz="UTC")), "O": fmt_p(o),
                         "H": fmt_p(f.p(s["h"][k])), "L": fmt_p(f.p(s["l"][k])), "C": fmt_p(c),
                         "body": "bullish" if c > o else ("bearish" if c < o else "doji"),
                         "C2 body covers gap": (f"{fmt_p(min(o, c))} ≤ {fmt_p(z['lower'])} and {fmt_p(max(o, c))} ≥ {fmt_p(z['upper'])}"
                                                if name == "C2" else "")})
        tables.append(("Formation candles (C2 directional body must span the gap)", rows))
    s_m = t - pd.Timedelta(minutes=1)
    st_pre, d_pre = f.stage_at(zid, s_m)
    st_post, d_post = f.stage_at(zid, t)
    tables.append(("Pre-state at s(m)", [{"zone": zid[:14], "stage": st_pre, "direction": d_pre}]))
    tables.append(("Evidence at m", [f.bar_1m(t)]))
    mit = f.e.mitigation[(f.e.mitigation["object_id"] == zid) & (f.e.mitigation["at"] == t)]
    if len(mit):
        tables.append(("Evidence at m: mitigation records", [
            {"stage": r.stage, "kind": r.kind, "class": r.observation_class, "depth": r.penetration_depth_ticks,
             "in-zone depth": r.in_zone_depth_ticks} for r in mit.itertuples()]))
    tr = f.e.zone_transitions[(f.e.zone_transitions["entity_id"] == zid) & (f.e.zone_transitions["transition_at"] == t)]
    if len(tr):
        tables.append(("Evidence at m: lifecycle transition", [
            {"from": r.previous_state, "to": r.new_state, "reason": r.reason_code, "close": fmt_p(f.p(r.attr_close_ticks)),
             "trigger": r.trigger_ref} for r in tr.itertuples()]))
    tables.append(("Post-state at e(m)", [{"zone": zid[:14], "stage": st_post, "direction": d_post}]))
    allm = f.e.mitigation[f.e.mitigation["object_id"] == zid].sort_values(["stage", "at"])
    tables.append(("Stage-separated mitigation (complete history)", [
        {"stage": r.stage, "kind": r.kind, "at": fmt_t(r.at), "class": r.observation_class,
         "depth": r.penetration_depth_ticks, "in-zone": r.in_zone_depth_ticks,
         "1m H/L": f"{fmt_p(f.p(r.bar_high_ticks))} / {fmt_p(f.p(r.bar_low_ticks))}",
         "relative to focus": "≤ e(m)" if r.at <= t else "later"} for r in allm.itertuples()][:40]))
    later = f.e.zone_transitions[(f.e.zone_transitions["entity_id"] == zid) & (f.e.zone_transitions["transition_at"] > t)]
    tables.append(("Later lifecycle (after e(m))", [
        {"to": r.new_state, "at": fmt_t(r.transition_at), "reason": r.reason_code} for r in later.itertuples()]))
    g = f.e.grades[f.e.grades["zone_id"] == zid]
    tables.append(("Grade versions (components)", [
        {"at": fmt_t(r.available_at), "tf rank": r.timeframe_rank, "overlap contribution": r.overlap_contribution,
         "partners": len(r.partner_zone_ids), "strength": r.normalization_status if pd.isna(r.normalized_gap_strength)
         else f"{r.normalized_gap_strength:.4f}", "width": r.original_width_ticks, "stage": r.stage,
         "actionable": r.actionable} for r in g.itertuples()][:20]))
    grp = f.e.groups[f.e.groups["zone_id"] == zid]
    if len(grp):
        tables.append(("Formation groups (each counted once)", [
            {"grade version": r.grade_version_id[:12], "group": r.group_index, "representative": r.representative_zone_id[:12],
             "members": ", ".join(m[:10] for m in r.member_zone_ids)} for r in grp.itertuples()][:20]))
    a = f.run.associations[f.run.associations["zone_id"] == zid]
    if len(a):
        tables.append(("First-FVG association", [
            {"is first": r.is_first, "formation available": fmt_t(r.formation_available_at),
             "association available": fmt_t(r.association_available_at), "deadline rule": r.deadline_rule,
             "marker never active": r.marker_never_active, "reason": r.reason} for r in a.itertuples()]))
    return tables


def bpr_tables(f: Facts, case: Case, bid: str) -> list:
    b = f.e.bprs.set_index("bpr_id").loc[bid]
    ep = f.e.episodes.set_index("relationship_id").loc[b["relationship_id"]]
    return [("BPR object", [{"bpr": bid[:14], "label": b["label"], "direction": b["direction"],
                             "governing tf": b["governing_timeframe"], "lower": fmt_p(b["lower"]), "upper": fmt_p(b["upper"]),
                             "midpoint": fmt_p(b["midpoint"]), "available_at": fmt_t(b["available_at"]),
                             "exit": b["exit_state"], "exit at": fmt_t(b["exit_at"])}]),
            ("Creating episode", [{"label": ep["label"], "parents": f"{ep['zone_a'][:10]} ({ep['stage_a']}) × {ep['zone_b'][:10]} ({ep['stage_b']})",
                                   "movers": ", ".join(m[:10] for m in ep["movers"]), "event time": fmt_t(ep["event_time"]),
                                   "intersection": f"{fmt_p(f.p(ep['i_lower_ticks']))}–{fmt_p(f.p(ep['i_upper_ticks']))}"}])]


STYLE = """
:root{--bg:#fff;--fg:#1d1d1f;--mute:#6b7280;--grid:#e5e7eb;--up:#16a34a;--dn:#dc2626;--zone:#2563eb;--bpr:#7c3aed;--card:#f9fafb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111827;--fg:#f3f4f6;--mute:#9ca3af;--grid:#374151;--card:#1f2937}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1120px;padding:16px}
h1{font-size:22px}h2{font-size:17px;margin-top:34px;border-top:1px solid var(--grid);padding-top:14px}h4{margin:12px 0 4px}
.note{color:var(--mute)}.chart{width:100%;height:auto;background:var(--card);border-radius:6px}
.grid{stroke:var(--grid)}.ax{fill:var(--mute);font-size:10px}.wick{stroke-width:1}.up{stroke:var(--up);fill:var(--up)}
.dn{stroke:var(--dn);fill:var(--dn)}.dj{stroke:var(--mute);fill:var(--mute)}.body.c2{stroke:#f59e0b;stroke-width:2.5}
.span{fill:#f59e0b;opacity:.10}.zone{fill:var(--zone);opacity:.18;stroke:var(--zone)}.bpr{fill:var(--bpr);opacity:.25;stroke:var(--bpr)}
.mid{stroke:var(--fg);stroke-dasharray:4 3;opacity:.7}.lab{font-size:10px;fill:var(--fg)}.lab.zone{fill:var(--zone)}.lab.bpr{fill:var(--bpr)}
.mark{stroke:#0891b2;stroke-dasharray:1 3}.lab.mark{fill:#0891b2}.focus{stroke:var(--fg);stroke-dasharray:3 3;opacity:.6}
.tw{overflow-x:auto}table{border-collapse:collapse;font-size:12px;margin-bottom:6px}td,th{border:1px solid var(--grid);padding:3px 6px;white-space:nowrap;text-align:left}
th{background:var(--card)}
"""


def page(cases, facts_by_key, header) -> str:
    toc = "".join(f"<li><a href='#{c.case_id}'>{html.escape(c.case_id)} — {html.escape(c.title)}</a></li>" for c in cases)
    secs = []
    for c in cases:
        f = facts_by_key[c.run_key]
        tables = "".join(table(cap, rows) for cap, rows in c.tables)
        secs.append(f"<section id='{c.case_id}'><h2>{html.escape(c.case_id)} — {html.escape(c.title)}</h2>"
                    f"<p class='note'>{html.escape(c.category)} · {html.escape(c.source)}</p><p>{html.escape(c.note)}</p>"
                    f"{chart(f, c)}{tables}</section>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FVG Validation</title><style>{STYLE}</style></head><body>
<h1>FVG / IFVG / BPR — FVG-I5 visual validation</h1>
<p class="note">LOCAL ONLY — contains market prices (Git-ignored). Production pipeline (build_fvg), DEVELOPMENT partition and
synthetic worked examples. Chart: own-timeframe candles; amber shading = C1–C3 source span; amber outline = C2 body; blue box = zone
bounds from availability to stage end (dashed = exact midpoint); purple box = BPR; ▲ = availability / lifecycle markers; dashed
vertical = focus instant e(m). Tables: immutable facts → formation candles → pre-state at s(m) → evidence at m → post-state at e(m)
→ later lifecycle. Machine evidence only; human visual approval pending.</p>
{table("Run", header)}<ol>{toc}</ol>{''.join(secs)}</body></html>"""


def manifest_rows(cases) -> list:
    return [{"case_id": c.case_id, "category": c.category, "title": c.title, "source": c.source,
             "focus_at": c.focus.isoformat(), "object_refs": json.dumps(c.refs, sort_keys=True)} for c in cases]


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------


def _first(df, mask):
    hit = df[mask]
    return None if hit.empty else hit.iloc[0]


def build_dev_cases(run) -> list:
    f = Facts(run)
    cases = []
    Z, E = run.zones, run.engine
    tr = E.zone_transitions

    def zcase(cid, title, cat, zid, focus, note, extra=(), bprs=()):
        c = Case(cid, title, cat, "DEVELOPMENT", "dev", zid, pd.Timestamp(focus), note, list(extra), list(bprs),
                 refs={"zone_id": zid, "bpr_ids": list(bprs)})
        c.tables = zone_tables(f, c)
        for b in bprs:
            c.tables += bpr_tables(f, c, b)
        cases.append(c)
    # one formation + lifecycle case per timeframe (prefer a converted zone)
    for tf in ("1m", "5m", "15m", "1H", "4H", "1D"):
        conv = tr[(tr["reason_code"] == "CONVERTED") & (tr["attr_timeframe"] == tf)]
        if len(conv):
            r = conv.iloc[len(conv) // 2]
            zcase(f"FVG-{tf}-CONV", f"{tf} formation → conversion", "timeframe", r["entity_id"], r["transition_at"],
                  "Own-timeframe close strictly beyond the far bound converts the zone; wicks beyond never do.")
        else:
            zz = Z[Z["timeframe"] == tf]
            if len(zz):
                r = zz.iloc[len(zz) // 2]
                zcase(f"FVG-{tf}-FORM", f"{tf} formation", "timeframe", r["zone_id"], r["available_at"],
                      "Formation at C3 close; the zone is first testable by the next 1m bar.")
    m = E.mitigation[E.mitigation["object_kind"] == "ZONE"]
    for cls, kind, cid, title in (("SPANNING", "FULL", "MIT-SPAN", "Spanning bar: all milestones at once"),
                                  ("FAR_CONTACT", "PENETRATION", "MIT-FAR", "Far-boundary contact from beyond"),
                                  ("BEYOND", "GAP_THROUGH", "MIT-GAP", "Wholly beyond: gap-through evidence, no milestone"),
                                  ("ZONE_TRADE", "MIDPOINT", "MIT-MID", "Midpoint reached (inclusive)")):
        r = _first(m, (m["observation_class"] == cls) & (m["kind"] == kind) & (Z.set_index("zone_id").loc[m["object_id"], "timeframe"].to_numpy() == "5m"))
        if r is not None:
            zcase(cid, title, "mitigation", r["object_id"], r["at"], f"Observation class {cls}; event {kind}.")
    ret = _first(tr, (tr["reason_code"] == "RETIRED") & (tr["attr_timeframe"] == "5m"))
    if ret is not None:
        zcase("LIFE-RETIRE", "IFVG retirement (no re-inversion)", "lifecycle", ret["entity_id"], ret["transition_at"],
              "The IFVG retires on a strict close beyond its far bound in the reversed direction.")
    ifvg_m = _first(m, (m["stage"] == "IFVG") & (m["kind"] == "PENETRATION"))
    if ifvg_m is not None:
        zcase("LIFE-IFVG-RETEST", "IFVG retest (stage-separated mitigation)", "lifecycle", ifvg_m["object_id"],
              ifvg_m["at"], "IFVG-stage evidence starts with the 1m bar after the conversion close.")
    gap = _first(tr, tr["reason_code"] == "DATA_GAP")
    if gap is not None:
        zcase("DATA-GAP", "Termination at a 1m data-gap onset", "data", gap["entity_id"], gap["transition_at"],
              "Every active object ends at the onset; nothing is inferred inside the gap.")
    for status, cid in (("OK", "NORM-OK"), ("INSUFFICIENT_HISTORY", "NORM-INSUFFICIENT")):
        r = _first(Z, (Z["normalization_status"] == status) & (Z["timeframe"] == "15m"))
        if r is not None:
            zcase(cid, f"Normalization {status}", "grading", r["zone_id"], r["available_at"],
                  "Strength = width / ATR(14) of the observations before C1 (exact rational); nulls are never fabricated.")
    e = E.episodes
    g = E.grades
    grp = g[(g["overlap_contribution"] >= 1) & (g["partner_zone_ids"].map(len) > g["overlap_contribution"])]
    if len(grp):
        r = grp.iloc[0]
        zcase("OVL-GROUP", "FVG_OVERLAP with a nested formation group (counted once)", "overlap", r["zone_id"],
              r["available_at"], f"{len(r['partner_zone_ids'])} partners form {r['overlap_contribution']} group(s).",
              extra=list(r["partner_zone_ids"])[:3])
    b = E.bprs
    for label, cid in (("BPR", "BPR-ADMIT"), ("MTF_BPR", "MTF-BPR")):
        cand = b[(b["label"] == label) & (b["direction"] != "UNDEFINED")]
        if len(cand):
            r = cand.iloc[len(cand) // 3]
            zcase(cid, f"{label} (admission-created)", "bpr", r["parent_a"], r["available_at"],
                  "Intersection of the parents; direction and governing timeframe from the unique mover.",
                  extra=[r["parent_b"]], bprs=[r["bpr_id"]])
    exits = E.zone_exits
    conv_eps = e[(e["label"] != "FVG_OVERLAP") & (e["movers"].map(len) == 1)
                 & e.apply(lambda r: exits[r["movers"][0]]["conv_ns"] == r["created_at"].value, axis=1)] if len(e) else e
    if len(conv_eps):
        r = conv_eps.iloc[0]
        bid = b[b["relationship_id"] == r["relationship_id"]]["bpr_id"].iloc[0]
        zcase("BPR-CONV", "Conversion-created BPR", "bpr", r["movers"][0], r["created_at"],
              "A conversion made a same-direction pair opposite: new BPR with the converting parent's direction, its "
              "timeframe and the conversion instant; usable only after it.", extra=[x for x in (r["zone_a"], r["zone_b"]) if x != r["movers"][0]],
              bprs=[bid])
    a = run.associations
    for rule, cid, title in (("NO_PENDING_CANDIDATE", "ASSOC-IMMEDIATE", "First FVG associated at formation"),
                             ("PENDING_CANDIDATE_AT_C2", "ASSOC-DELAYED", "First FVG associated after the C2 deadline")):
        r = _first(a, a["is_first"] & (a["deadline_rule"] == rule) & (a["timeframe"] == "5m"))
        if r is not None:
            zcase(cid, title, "association", r["zone_id"], r["association_available_at"],
                  "C2 anchor; most extreme origin since the last opposite swing; the marker is visible only from the "
                  "association instant.")
    return cases


# ---------------------------------------------------------------------------
# Synthetic worked examples (design §5) on the production pipeline
# ---------------------------------------------------------------------------

_W1 = [(100, 101.00, 99, 100.75), (100.75, 104, 100.5, 103.75), (103.75, 105, 102.25, 104.5), (104.5, 104.75, 102.25, 103),
       (103, 103.25, 102, 102.5), (102.5, 102.75, 101.5, 102), (102, 102.25, 100.75, 101.25), (101.25, 101.5, 101.0, 101.0),
       (101, 101.25, 100.25, 100.5), (100.5, 101.0, 100.25, 100.75), (100.75, 101.75, 100.5, 101.5),
       (101.5, 102.5, 101.25, 102.25), (102.25, 103, 102, 102.75)]
_W5 = [(100, 100.5, 99.5, 100.25), (100.25, 100.75, 100, 100.5), (100.5, 101, 100.25, 100.75),
       (100.75, 103, 100.75, 102.75), (102.75, 105, 102.5, 104.75), (104.75, 107, 104.5, 106.75),
       (106.75, 108, 106, 107.5), (107.5, 108.5, 107, 108), (108, 109, 107.25, 108.5)]
_W7 = _W5 + [(108.5, 108.5, 104.0, 104.25), (104.25, 104.5, 102.75, 103.0), (103.0, 103.5, 100.75, 101.0),
             (101.0, 101.25, 100.25, 100.75)]
_W9D = [(106, 107, 105, 105.5), (105.5, 106, 104, 104.5), (104.5, 105, 100, 100.5), (100.5, 108, 100, 107.75),
        (107.75, 109, 105.5, 108.5), (108.5, 110, 106, 109.5), (109.5, 111, 107, 110.5)]
_BASE4 = _W1[:3] + [(104.5, 104.75, 103, 103.0)]


def synthetic_bars(rows, tf, spec, *, contracts=None, absent=()):
    """1m source bars whose ``tf`` observation k has exactly ``rows[k]`` (first minute O/H/L/C, rest at C).

    Isolated synthetic fixture for the visual package (2026-09-14 onward, regular calendar; no override)."""
    from src.data.timeframes import TimeframeSpec, expected_timeframe_schedule
    from src.fvg.formation import timeframe_spec
    days = [date(2026, 9, 14 + d) for d in range(5)]
    sched = expected_timeframe_schedule(days, timeframe_spec(tf), spec).reset_index(drop=True)
    frames = []
    for k, row in enumerate(rows):
        if row is None or k in absent:
            continue
        slot = sched.iloc[k]
        minutes = pd.date_range(slot["bar_start"] + pd.Timedelta(minutes=1), slot["bar_end"], freq="min")
        o, h, lo, c = (20000.0 + v for v in row)
        fr = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1,
                           "contract": contracts[k] if contracts else "MNQ 12-26"}, index=minutes)
        fr.loc[fr.index[0], ["open", "high", "low", "close"]] = [o, h, lo, c]
        frames.append(fr)
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="timestamp_et")
    return out, sched


def synthetic_cases(spec) -> tuple[list, dict]:
    from src.fvg.pipeline import build_fvg
    specs = [
        ("SYN-W1", "W1 bullish: touch, penetration, midpoint, spanning, conversion, IFVG, retirement, BPR survival", _W1, "5m", ("5m",), {}, (101.00, 102.25), 8),
        ("SYN-W2", "W2 1m conversion-bar ordering", _W1[:3] + [(104.5, 104.75, 100.5, 100.75), (100.75, 101.5, 100.5, 101.25), (101.25, 101.5, 101.0, 101.25)], "1m", ("1m",), {}, (101.00, 102.25), 3),
        ("SYN-W4a", "W4a wholly beyond: gap-through, close-based conversion", _BASE4 + [(100.0, 100.75, 99.5, 100.25)], "5m", ("5m",), {}, (101.00, 102.25), 4),
        ("SYN-W4b", "W4b far-boundary contact from beyond", _BASE4 + [(100.5, 101.0, 100.0, 101.0)], "5m", ("5m",), {}, (101.00, 102.25), 4),
        ("SYN-W4c", "W4c spanning bar", _BASE4 + [(103.0, 103.25, 100.75, 101.5)], "5m", ("5m",), {}, (101.00, 102.25), 4),
        ("SYN-W5", "W5 nested formation group (contribution 1)", _W5, "5m", ("5m", "15m"), {}, (101.00, 106.00), 8),
        ("SYN-W7", "W7 conversion-created MTF_BPR", _W7, "5m", ("5m", "15m"), {}, (105.00, 106.00), 9),
        ("SYN-W9D", "W9d plateau deadline: association one bar after formation", _W9D, "5m", ("5m",), {}, (105.00, 105.50), 5),
        ("SYN-W10", "W10 zero baseline (strength null, zone kept)", [(100, 100, 100, 100)] * 15 + _W1[:3], "5m", ("5m",), {}, (101.00, 102.25), 17),
        ("SYN-W11", "W11 data gap: termination, no inference", _W1, "5m", ("5m",), {"absent": {5}}, (101.00, 102.25), None),
        ("SYN-W12", "W12 pure roll: basis guard and PENDING_ADJUSTMENT", _W1, "5m", ("5m",), {"contracts": ["MNQ 09-26"] * 6 + ["MNQ 12-26"] * 7}, (101.00, 102.25), None),
    ]
    cases, facts = [], {}
    for cid, title, rows, tf, tfs, kw, bounds, focus_k in specs:
        bars, sched = synthetic_bars(rows, tf, spec, **kw)
        run = build_fvg(bars, spec, instrument_id="MNQ", replay_cutoff=sched.iloc[len(rows) - 1]["bar_end"], timeframes=tfs)
        f = Facts(run)
        facts[cid] = f
        lo, up = int(round((20000 + bounds[0]) / 0.25)), int(round((20000 + bounds[1]) / 0.25))
        z = run.zones[(run.zones["lower_ticks"] == lo) & (run.zones["upper_ticks"] == up)].iloc[0]
        if focus_k is not None:
            focus = sched.iloc[focus_k]["bar_end"].tz_convert("UTC")
        else:
            tr = run.engine.zone_transitions
            focus = tr[tr["entity_id"] == z["zone_id"]]["transition_at"].iloc[0]
        bprs = list(run.engine.bprs["bpr_id"])
        others = [x for x in run.zones["zone_id"] if x != z["zone_id"]][:3]
        c = Case(cid, title, "synthetic", "SYNTHETIC (design §5)", cid, z["zone_id"], pd.Timestamp(focus),
                 "Executed on the production pipeline with an isolated synthetic fixture.", others, bprs[:2],
                 refs={"fixture": cid})
        c.tables = zone_tables(f, c)
        for b in bprs[:2]:
            c.tables += bpr_tables(f, c, b)
        cases.append(c)
    return cases, facts
