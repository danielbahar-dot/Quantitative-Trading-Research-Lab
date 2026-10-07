"""Internal Liquidity — IL-I4 visual validation package (local HTML with prices; price-free manifest).

Each case shows a 1m chart window with exact prices, plus tables in the
order pre-state S_m (at s(m)) → evidence at m → post-state at e(m).
Pinned boundary assignments (solid, thick) are drawn separately from the
live External objects (dashed); internal levels are thin lines; dotted
lines are consumption thresholds θ.  Times are New York.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import html
import json

import numpy as np
import pandas as pd

NY = "America/New_York"
MAX_BARS = 70


def fmt_time(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return pd.Timestamp(value).tz_convert(NY).strftime("%Y-%m-%d %H:%M")


def fmt_price(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or pd.isna(value):
        return "UNBOUNDED"
    return f"{float(value):,.2f}"


@dataclass
class Line:
    t0: pd.Timestamp
    t1: pd.Timestamp | None
    price: float
    kind: str        # level / assignment / external / threshold
    label: str


@dataclass
class Case:
    case_id: str
    title: str
    category: str
    focus_at: pd.Timestamp
    note: str
    lines: list = field(default_factory=list)
    tables: list = field(default_factory=list)      # (caption, rows)
    refs: dict = field(default_factory=dict)        # price-free ids for the manifest
    window: tuple | None = None
    spans: list = field(default_factory=list)       # (start, end, price, label): physical source spans
    marks: list = field(default_factory=list)       # (at, label): available_at markers


class Facts:
    """Price lookups over one run (production tables only)."""

    def __init__(self, run):
        self.run = run
        self.tick = Decimal(run.manifest["tick_size"])
        tr = run.consumption_transitions
        self.end = {r.entity_id: (r.transition_at, r.new_state, r.reason_code) for r in tr.itertuples(index=False)}
        self.evidence = run.consumption_evidence.set_index("object_id") if len(run.consumption_evidence) else None
        self.view = {x.obj.object_id: x for x in run.external_view}
        levels = run.levels if "level_id" in run.levels.columns else pd.DataFrame(columns=["level_id"])
        self.levels_first = levels.groupby("level_id").head(1).set_index("level_id")
        self.levels_last = levels.groupby("level_id").tail(1).set_index("level_id")
        self.assign = run.assignments.set_index("boundary_assignment_id") if len(run.assignments) else None
        self.episodes = run.tape.episodes
        f = run.formation
        self.member = {} if f.members is None or not len(f.members) else {
            r.member_id: r for r in f.members.itertuples(index=False)}
        self.structure_members = {} if f.structures is None or not len(f.structures) else dict(
            zip(f.structures["structure_id"], f.structures["member_ids"]))
        self.source_spans = getattr(run, "source_spans", None) or f.spans
        xm = run.external_members
        self.ext_member = {} if xm is None or not len(xm) else {r.member_id: r for r in xm.itertuples(index=False)}

    def available_at(self, object_id):
        if object_id in self.levels_first.index:
            return self.levels_first.loc[object_id, "level_available_at"]
        if self.assign is not None and object_id in self.assign.index:
            return self.assign.loc[object_id, "assigned_at"]
        if object_id in self.view:
            return self.view[object_id].obj.available_at
        return None

    def p(self, ticks):
        return None if ticks is None or pd.isna(ticks) else float(Decimal(int(ticks)) * self.tick)

    def bars(self, t0, t1):
        rows = []
        for e in self.episodes:
            lo = int(np.searchsorted(e.bar_end, pd.Timestamp(t0).value, side="left"))
            hi = int(np.searchsorted(e.bar_end, pd.Timestamp(t1).value, side="right"))
            for k in range(lo, hi):
                rows.append((pd.Timestamp(int(e.bar_start[k]), tz="UTC"), pd.Timestamp(int(e.bar_end[k]), tz="UTC"),
                             self.p(e.open[k]), self.p(e.high[k]), self.p(e.low[k]), self.p(e.close[k]), e.contract))
        return rows

    def bar_at(self, at):
        for e in self.episodes:
            k = int(np.searchsorted(e.bar_end, pd.Timestamp(at).value))
            if k < len(e.bar_end) and e.bar_end[k] == pd.Timestamp(at).value:
                return {"bar": fmt_time(at), "open": fmt_price(self.p(e.open[k])), "high": fmt_price(self.p(e.high[k])),
                        "low": fmt_price(self.p(e.low[k])), "close": fmt_price(self.p(e.close[k])),
                        "contract": e.contract}
        return {"bar": fmt_time(at), "open": "absent"}

    def status_at(self, object_id, at):
        """Lifecycle state at instant ``at`` only (never a later outcome)."""
        avail = self.available_at(object_id)
        if avail is not None and avail > at:
            return "NOT YET AVAILABLE"
        e = self.end.get(object_id)
        if e is None or e[0] > at:
            return "ACTIVE"
        return f"{e[1]} ({e[2]}) @ {fmt_time(e[0])}"

    def evidence_spans(self, level_id):
        """Source spans (start, end, price, label) and available_at marks for every evidence atom of a level."""
        spans, marks = [], []
        versions = self.run.levels[self.run.levels["level_id"] == level_id]
        seen = set()
        for r in versions.itertuples(index=False):
            marks.append((r.available_at, f"{r.change_kind}"))
            atoms = list(r.evidence_member_ids)
            for sid in r.evidence_structure_ids:
                atoms += [a for a in self.structure_members.get(sid, ()) if a not in atoms]
            for a in atoms:
                if a in seen or a not in self.source_spans or a not in self.member:
                    continue
                seen.add(a)
                m = self.member[a]
                start, end, tf = self.source_spans[a]
                kind = "candle" if "CANDLE" in m.member_kind else "swing"
                spans.append((pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), float(m.price),
                              f"{tf} {kind} src"))
                marks.append((pd.Timestamp(m.available_at).tz_convert("UTC"), f"{tf} {kind} avail"))
        return spans, marks

    def external_spans(self, object_id, at):
        """Source spans of an External object's current version members at ``at``."""
        x = self.view.get(object_id)
        if x is None:
            return [], []
        vs = [v for v in x.obj.versions if v.available_at <= at] or list(x.obj.versions[:1])
        spans, marks = [], [(vs[-1].available_at, "External avail")]
        for m in x.version_members.get(vs[-1].version_ref, ()):
            r = self.ext_member.get(m)
            if r is None:
                continue
            key = ("bar", r.reference_family, pd.Timestamp(r.source_at).tz_convert("UTC").value)
            if key in self.source_spans:
                start, end, tf = self.source_spans[key]
                spans.append((pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), float(r.price),
                              f"{tf} External src"))
        return spans, marks

    def object_lines(self, object_id, kind_hint=None):
        """Lines for an internal level / External object / assignment, with thresholds."""
        lines = []
        end = self.end.get(object_id, (None,))[0]
        if object_id in self.levels_first.index:
            r = self.levels_first.loc[object_id]
            lines.append(Line(r["level_available_at"], end, r["price"], "level", f"IL {fmt_price(r['price'])}"))
            lines.append(Line(r["level_available_at"], end, r["consumption_threshold"], "threshold", "θ int"))
        elif self.assign is not None and object_id in self.assign.index:
            r = self.assign.loc[object_id]
            lines.append(Line(r["assigned_at"], end, r["pinned_price"], "assignment",
                              f"BA {r['side'][0]} {fmt_price(r['pinned_price'])}"))
            lines.append(Line(r["assigned_at"], end, r["pinned_threshold"], "threshold", "θ pin"))
        elif object_id in self.view:
            x = self.view[object_id]
            versions = x.obj.versions
            for k, v in enumerate(versions):
                t1 = versions[k + 1].available_at if k + 1 < len(versions) else end
                if end is not None and v.available_at >= end:
                    break
                lab = ("D" if x.obj.object_kind == "EXTERNAL_DAILY" else f"{x.family} {x.structure_type}")
                lines.append(Line(v.available_at, t1, self.p(v.price_ticks), "external", f"{lab} {fmt_price(self.p(v.price_ticks))}"))
                theta = v.price_ticks + v.tolerance_ticks if x.obj.side == "UPPER" else v.price_ticks - v.tolerance_ticks
                lines.append(Line(v.available_at, t1, self.p(theta), "threshold", "θ ext"))
        return lines


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def chart(facts: Facts, case: Case, W=980, H=340) -> str:
    focus = case.focus_at
    t0, t1 = case.window or (focus - pd.Timedelta(minutes=40), focus + pd.Timedelta(minutes=20))
    bars = facts.bars(t0, t1)[-MAX_BARS:]
    if not bars:
        return "<p class='note'>no bars in window</p>"
    t0, t1 = bars[0][0], bars[-1][1]
    lines = [ln for ln in case.lines if (ln.t1 is None or ln.t1 > t0) and ln.t0 <= t1 and ln.price is not None]
    prices = [b[3] for b in bars] + [b[4] for b in bars]
    band = max((max(prices) - min(prices)) * 0.35, 3.0)
    near = [ln.price for ln in lines if min(prices) - band <= ln.price <= max(prices) + band]
    lo, hi = min(prices + near), max(prices + near)
    pad = max((hi - lo) * 0.06, 0.5)
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 70, 150, 12, 26
    span = (t1 - t0).total_seconds()

    def x(t):
        t = min(max(pd.Timestamp(t), t0), t1)
        return L + (W - L - R) * (t - t0).total_seconds() / span

    def y(p):
        return T + (H - T - B) * (hi - p) / (hi - lo)
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for k in range(6):
        p = lo + (hi - lo) * k / 5
        parts.append(f'<line x1="{L}" x2="{W - R}" y1="{y(p):.1f}" y2="{y(p):.1f}" class="grid"/>'
                     f'<text x="{L - 6}" y="{y(p) + 4:.1f}" class="ax" text-anchor="end">{p:,.2f}</text>')
    bw = max(2.0, (W - L - R) / max(len(bars), 1) * 0.6)
    for s, e, o, h, l, c, _ in bars:
        cx = (x(s) + x(e)) / 2
        cls = "up" if c >= o else "dn"
        parts.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(h):.1f}" y2="{y(l):.1f}" class="wick {cls}"/>'
                     f'<rect x="{cx - bw / 2:.1f}" y="{min(y(o), y(c)):.1f}" width="{bw:.1f}" '
                     f'height="{max(abs(y(o) - y(c)), 1):.1f}" class="body {cls}"/>')
    for s0, s1, price, label in case.spans:
        if not lo <= price <= hi or s1 < t0 or s0 > t1:
            continue
        xa, xb = x(s0), x(s1)
        parts.append(f'<rect x="{xa:.1f}" y="{y(price) - 4:.1f}" width="{max(xb - xa, 2):.1f}" height="8" class="srcspan"/>'
                     f'<text x="{xa:.1f}" y="{y(price) - 6:.1f}" class="lab span">{html.escape(label)}</text>')
    mark_rows = {}
    for at, label in sorted(case.marks, key=lambda m: m[0]):
        if not t0 <= at <= t1:
            continue
        xm = x(at)
        row = mark_rows.setdefault(round(xm), len(mark_rows) % 3)
        parts.append(f'<line x1="{xm:.1f}" x2="{xm:.1f}" y1="{T}" y2="{H - B}" class="avail"/>'
                     f'<text x="{xm + 2:.1f}" y="{H - B - 6 - 11 * row:.1f}" class="lab avail">▲ {html.escape(label)}</text>')
    used = []
    edge = {"up": [], "dn": []}
    for ln in lines:
        if not lo <= ln.price <= hi:
            if ln.kind != "threshold":
                edge["up" if ln.price > hi else "dn"].append(f"{ln.label}")
            continue
        xa, xb = x(ln.t0), x(ln.t1 if ln.t1 is not None else t1)
        yy = y(ln.price)
        parts.append(f'<line x1="{xa:.1f}" x2="{xb:.1f}" y1="{yy:.1f}" y2="{yy:.1f}" class="ln {ln.kind}"/>')
        if ln.t1 is not None and t0 <= ln.t1 <= t1 and ln.kind != "threshold":
            parts.append(f'<text x="{xb:.1f}" y="{yy - 3:.1f}" class="end">✕</text>')
        ty = yy + 4
        while any(abs(ty - u) < 11 for u in used):
            ty += 11
        used.append(ty)
        if ln.kind != "threshold" or True:
            parts.append(f'<text x="{W - R + 4}" y="{ty:.1f}" class="lab {ln.kind}">{html.escape(ln.label)} '
                         f'{fmt_price(ln.price) if ln.kind == "threshold" else ""}</text>')
    for key, yy, arrow in (("up", T + 9, "↑"), ("dn", H - B - 3, "↓")):
        if edge[key]:
            text = html.escape("; ".join(dict.fromkeys(edge[key]))[:150])
            parts.append(f'<text x="{L + 4}" y="{yy}" class="lab edge">{arrow} off-scale: {text}</text>')
    fx = x(focus)
    parts.append(f'<line x1="{fx:.1f}" x2="{fx:.1f}" y1="{T}" y2="{H - B}" class="focus"/>')
    parts.append(f'<text x="{L}" y="{H - 6}" class="ax">{fmt_time(t0)}</text>'
                 f'<text x="{W - R}" y="{H - 6}" class="ax" text-anchor="end">{fmt_time(t1)}</text>'
                 f'<text x="{fx:.1f}" y="{H - 6}" class="ax" text-anchor="middle">e(m) {fmt_time(focus)}</text></svg>')
    return "".join(parts)


def table(caption, rows) -> str:
    if not rows:
        return f"<h4>{html.escape(caption)}</h4><p class='note'>none</p>"
    cols = list(rows[0])
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<h4>{html.escape(caption)}</h4><div class='tw'><table><tr>{head}</tr>{body}</table></div>"


STYLE = """
:root{--bg:#fff;--fg:#1d1d1f;--mute:#6b7280;--grid:#e5e7eb;--up:#16a34a;--dn:#dc2626;--lvl:#2563eb;--asg:#7c3aed;
--ext:#d97706;--thr:#9ca3af;--card:#f9fafb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111827;--fg:#f3f4f6;--mute:#9ca3af;--grid:#374151;
--card:#1f2937}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}
h1{font-size:22px}h2{font-size:17px;margin-top:34px;border-top:1px solid var(--grid);padding-top:14px}h4{margin:12px 0 4px}
.note{color:var(--mute)} .chart{width:100%;height:auto;background:var(--card);border-radius:6px}
.grid{stroke:var(--grid)} .ax{fill:var(--mute);font-size:10px} .wick{stroke-width:1} .up{stroke:var(--up);fill:var(--up)}
.dn{stroke:var(--dn);fill:var(--dn)} .ln{stroke-width:1.2} .ln.level{stroke:var(--lvl)} .ln.assignment{stroke:var(--asg);stroke-width:3}
.ln.external{stroke:var(--ext);stroke-dasharray:6 3;stroke-width:1.6} .ln.threshold{stroke:var(--thr);stroke-dasharray:2 3}
.lab{font-size:10px}.lab.level{fill:var(--lvl)}.lab.assignment{fill:var(--asg)}.lab.external{fill:var(--ext)}.lab.threshold{fill:var(--mute)}
.srcspan{fill:var(--lvl);opacity:.28;stroke:var(--lvl)}.lab.span{fill:var(--lvl)}
.avail{stroke:#0891b2;stroke-dasharray:1 3}.lab.avail{fill:#0891b2}
.end{fill:var(--dn);font-size:10px}.lab.edge{fill:var(--asg);font-weight:600}.focus{stroke:var(--fg);stroke-dasharray:3 3;opacity:.6}
.tw{overflow-x:auto} table{border-collapse:collapse;font-size:12px;margin-bottom:6px} td,th{border:1px solid var(--grid);padding:3px 6px;
white-space:nowrap;text-align:left} th{background:var(--card)}
"""


def page(cases: list[Case], facts_by_run: dict, cutoff, header_rows) -> str:
    toc = "".join(f"<li><a href='#{c.case_id}'>{html.escape(c.case_id)} — {html.escape(c.title)}</a></li>" for c in cases)
    sections = []
    for c in cases:
        facts = facts_by_run[c.refs.get("_run", "dev")]
        tables = "".join(table(cap, rows) for cap, rows in c.tables)
        sections.append(f"<section id='{c.case_id}'><h2>{html.escape(c.case_id)} — {html.escape(c.title)}</h2>"
                        f"<p>{html.escape(c.note)}</p>{chart(facts, c)}{tables}</section>")
    summary = table("Run", header_rows)
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Internal Liquidity Validation</title><style>{STYLE}</style></head><body>
<h1>Internal Liquidity — IL-I4 visual validation</h1>
<p class="note">LOCAL ONLY — contains market prices (Git-ignored). Production engine (build_internal_liquidity), DEVELOPMENT
partition, replay cutoff {pd.Timestamp(cutoff).isoformat()}, internal tolerance 4 ticks, External 6 ticks, MNQ tick 0.25.
Chart legend: thin blue = internal level; thick purple = <b>pinned boundary assignment</b>; dashed orange = <b>live External
object</b> (Daily member or cluster lineage at its current version); dotted grey = consumption threshold θ; ✕ = the object's
terminal exit; dashed vertical = e(m) of the focus bar. Tables follow pre-state S_m → evidence at m → post-state at e(m).
Machine-validation evidence; human visual approval pending.</p>{summary}<ol>{toc}</ol>{''.join(sections)}</body></html>"""


def manifest_rows(cases: list[Case]) -> list[dict]:
    rows = []
    for c in cases:
        refs = {k: v for k, v in c.refs.items() if not k.startswith("_")}
        rows.append({"case_id": c.case_id, "category": c.category, "title": c.title, "focus_at": c.focus_at.isoformat(),
                     "source": c.refs.get("_run", "dev"), "object_refs": json.dumps(refs, sort_keys=True)})
    return rows


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------


def _range_version_tables(facts: Facts, version_row, previous_row):
    at = version_row["available_at"]
    pre, post = [], []
    for label, row in (("pre", previous_row), ("post", version_row)):
        if row is None:
            continue
        target = pre if label == "pre" else post
        when = at if label == "post" else at - pd.Timedelta(microseconds=1)
        for side in ("upper", "lower"):
            aid = row[f"{side}_assignment_id"]
            if aid == "UNBOUNDED":
                target.append({"side": side.upper(), "assignment": "UNBOUNDED", "pinned price": "UNBOUNDED",
                               "pinned θ": "—", "pinned ref": "—", "selection": "—", "status": "—",
                               "live object": "—", "live current price": "—", "live status": "—"})
                continue
            a = facts.assign.loc[aid]
            x = facts.view.get(a["external_object_id"])
            cur = [v for v in x.obj.versions if v.available_at <= when] if x else []
            target.append({"side": side.upper(), "assignment": aid[:14], "pinned price": fmt_price(a["pinned_price"]),
                           "pinned θ": fmt_price(a["pinned_threshold"]),
                           "pinned ref": str(a["pinned_formation_ref"])[:14], "selection": a["selection_kind"],
                           "status": facts.status_at(aid, when), "live object": str(a["external_object_id"])[:14],
                           "live current price": fmt_price(facts.p(cur[-1].price_ticks)) if cur else "—",
                           "live status": facts.status_at(a["external_object_id"], when)})
    return pre, post


def _membership_delta(run, at):
    m = run.memberships
    if m.empty or "level_id" not in m.columns:
        return []
    price = run.levels.groupby("level_id").tail(1).set_index("level_id")["price"]
    rows = []
    for r in m[(m["from_at"] == at) | (m["until_at"] == at)].itertuples(index=False):
        rows.append({"level": r.level_id[:14], "price": fmt_price(price[r.level_id]),
                     "change": "JOINS" if r.from_at == at else f"LEAVES ({r.end_reason})",
                     "range_version": r.range_version_id[:14]})
    return rows[:30]


def _range_case(facts, case_id, title, category, v, note):
    run = facts.run
    group = run.ranges[run.ranges["range_id"] == v["range_id"]].sort_values("available_at").reset_index(drop=True)
    k = int(group.index[group["range_version_id"] == v["range_version_id"]][0])
    prev = group.iloc[k - 1] if k > 0 else None
    at = v["available_at"]
    pre, post = _range_version_tables(facts, v, prev)
    case = Case(case_id, title, category, at, note,
                refs={"range_version_id": v["range_version_id"], "range_id": v["range_id"]})
    for row in (prev, v):
        if row is None:
            continue
        for side in ("upper", "lower"):
            aid = row[f"{side}_assignment_id"]
            if aid != "UNBOUNDED":
                case.lines += facts.object_lines(aid)
                oid = facts.assign.loc[aid, "external_object_id"]
                case.lines += facts.object_lines(oid)
                case.marks.append((facts.assign.loc[aid, "assigned_at"], f"assigned {side}"))
                case.marks += [(t, f"{side} object avail") for t, _ in facts.external_spans(oid, at)[1]]
    evidence = []
    if facts.evidence is not None:
        hits = facts.evidence[facts.evidence["ended_at"] == at]
        for oid, r in hits.iterrows():
            evidence.append({"object": oid[:14], "kind": r["object_kind"], "side": r["side"], "reason": r["reason"],
                             "p": fmt_price(r["price"]), "θ": fmt_price(r["threshold"]),
                             "excess ticks": r["excess_ticks"], "gap through": r["gap_through"]})
    case.tables = [("Pre-state S_m (range version at s(m))", pre), ("Evidence: bar m", [facts.bar_at(at)]),
                   ("Evidence: objects ending at e(m)", evidence[:20]),
                   (f"Post-state at e(m): {v['change_kind']}", post),
                   ("Membership changes at e(m)", _membership_delta(run, at))]
    return case


def _price_theta(facts, oid, at):
    """(price, θ) of an object as of instant ``at`` (its version current at ``at``)."""
    if oid in facts.levels_first.index:
        r = facts.levels_first.loc[oid]
        return r["price"], r["consumption_threshold"]
    x = facts.view.get(oid)
    if x is not None:
        vs = [v for v in x.obj.versions if v.available_at <= at] or list(x.obj.versions[:1])
        v = vs[-1]
        theta = v.price_ticks + v.tolerance_ticks if x.obj.side == "UPPER" else v.price_ticks - v.tolerance_ticks
        return facts.p(v.price_ticks), facts.p(theta)
    return None, None


def _level_case(facts, case_id, title, category, level_id, note, focus=None, extra_lines=()):
    """Tables strictly ordered: pre-state at s(m) → evidence at m → post-state at e(m) → later lifecycle (separate)."""
    run = facts.run
    versions = run.levels[run.levels["level_id"] == level_id]
    first = versions.iloc[0]
    end = facts.end.get(level_id)
    focus = focus if focus is not None else (end[0] if end else first["available_at"])
    s_m = focus - pd.Timedelta(minutes=1)
    case = Case(case_id, title, category, focus, note, refs={"level_id": level_id})
    case.lines += facts.object_lines(level_id)
    spans, marks = facts.evidence_spans(level_id)
    for oid in extra_lines:
        case.lines += facts.object_lines(oid)
        xs, xmk = facts.external_spans(oid, focus)
        spans += xs
        marks += xmk
    case.spans, case.marks = spans, marks
    objects = (level_id, *extra_lines)

    def version_row(r):
        return {"version": r.level_version_id[:14], "change": r.change_kind, "available": fmt_time(r.available_at),
                "price": fmt_price(r.price), "θ": fmt_price(r.consumption_threshold), "tier": r.grade_tier,
                "rank": r.grade_rank, "confluence": r.confluence,
                "evidence": ",".join(x[:10] for x in tuple(r.evidence_member_ids) + tuple(r.evidence_structure_ids)),
                "superseded": ",".join(x[:10] for x in r.superseded_evidence_ids), "explanation": r.grade_explanation}

    def state_row(oid, at):
        price, theta = _price_theta(facts, oid, at)
        return {"object": oid[:14], "available": fmt_time(facts.available_at(oid)), "p": fmt_price(price),
                "θ": fmt_price(theta), "status": facts.status_at(oid, at)}

    case.tables.append(("Pre-state S_m (at s(m), start of the focus bar)", [state_row(o, s_m) for o in objects]))
    case.tables.append(("Level versions available by e(m)",
                        [version_row(r) for r in versions.itertuples() if r.available_at <= focus]))
    span_rows = [{"source span": f"{fmt_time(a)} → {fmt_time(b)}", "price": fmt_price(p), "atom": lab}
                 for a, b, p, lab in spans]
    case.tables.append(("Formation evidence: source spans (shaded) and availability (▲)", span_rows))
    case.tables.append(("Evidence: bar m", [facts.bar_at(focus)]))
    post = []
    for oid in objects:
        row = state_row(oid, focus)
        e = facts.end.get(oid)
        if e is not None and e[0] == focus and facts.evidence is not None and oid in facts.evidence.index:
            r = facts.evidence.loc[oid]
            row.update({"θ evaluated": fmt_price(r["threshold"]), "excess ticks": r["excess_ticks"],
                        "gap through": r["gap_through"],
                        "max penetration before m (ticks)": r["max_penetration_ticks"]})
        post.append(row)
    case.tables.append(("Post-state at e(m) (state at the focus instant only)", post))
    later = [dict(version_row(r), object=level_id[:14], event="later level version")
             for r in versions.itertuples() if r.available_at > focus]
    for oid in objects:
        e = facts.end.get(oid)
        if e is not None and e[0] <= focus:
            continue
        row = {"object": oid[:14], "event": "outcome after e(m)"}
        if e is None:
            row.update({"status": "ACTIVE at replay cutoff"})
        else:
            row.update({"status": f"{e[1]} ({e[2]})", "at": fmt_time(e[0])})
            if facts.evidence is not None and oid in facts.evidence.index:
                r = facts.evidence.loc[oid]
                row.update({"θ evaluated": fmt_price(r["threshold"]), "bar o/h/l/c": r["bar_ohlc"],
                            "excess ticks": r["excess_ticks"],
                            "max signed excursion before end (ticks)": r["max_signed_excursion_ticks"]})
        later.append(row)
    case.tables.append(("Later lifecycle (after e(m); not part of the focus-bar state)", later))
    return case


def build_dev_cases(run) -> tuple[list[Case], Facts]:
    facts = Facts(run)
    cases: list[Case] = []
    R = run.ranges.sort_values("available_at").reset_index(drop=True)
    A = run.assignments
    tr = run.consumption_transitions
    ck = R["change_kind"].astype(str)

    def first_range(mask, case_id, title, category, note):
        hit = R[mask]
        if len(hit):
            cases.append(_range_case(facts, case_id, title, category, hit.iloc[0], note))

    first_range(ck == "ESTABLISHED", "IL-V01", "Range establishment (closest eligible)", "establishment",
                "Lower = closest eligible LOWER <= c(m); upper = closest eligible UPPER >= c(m) (else UNBOUNDED).")
    first_range(ck.str.startswith("UPPER_ADVANCED") & ck.str.contains("OPPOSITE"), "IL-V02",
                "Upper consumed: advance outward + opposite reselected", "advance",
                "The pinned upper is consumed and advances beyond its pinned price; the lower is replaced only by a "
                "strictly closer eligible lower (old one RELEASED).")
    first_range(ck == "UPPER_ADVANCED", "IL-V03", "Upper advance, opposite retained", "advance",
                "No strictly closer lower: the existing lower assignment is retained unchanged.")
    first_range(ck.str.startswith("LOWER_ADVANCED"), "IL-V04", "Lower consumed: advance outward", "advance",
                "Mirror of the upper case.")
    first_range(ck == "BOTH_ADVANCED", "IL-V05", "Both boundaries consumed by one bar", "both",
                "Both pinned assignments exceeded on one 1m bar: both sides advance; no reselection.")
    first_range(R["upper_assignment_id"] == "UNBOUNDED", "IL-V06", "Unbounded upper", "unbounded",
                "No eligible upper: the range has an UNBOUNDED upper; membership is lower < p.")
    clusters = A[A["external_object_kind"] == "EXTERNAL_CLUSTER"] if len(A) else A
    chosen = None
    for a in clusters.itertuples(index=False):
        ae, xe = facts.end.get(a.boundary_assignment_id), facts.end.get(a.external_object_id)
        if ae and ae[2] == "CONSUMED" and (xe is None or xe[0] > ae[0]):
            x = facts.view[a.external_object_id]
            extended = any(a.assigned_at < v.available_at < ae[0] for v in x.obj.versions)
            if chosen is None or (extended and not chosen[1]):
                chosen = (ae[0], extended)
            if extended:
                break
    if chosen is not None and (R["available_at"] == chosen[0]).any():
        cases.append(_range_case(facts, "IL-V07", "Pinned assignment consumed, live cluster still ACTIVE (A-19)",
                                 "pinned_vs_live", R[R["available_at"] == chosen[0]].iloc[0],
                                 "The assignment is evaluated only against its pinned θ; the live cluster (dashed) is "
                                 "evaluated at its current version and stays ACTIVE"
                                 + (" — it was extended after the assignment was pinned." if chosen[1] else ".")))
    for a in clusters.itertuples(index=False):
        ae, xe = facts.end.get(a.boundary_assignment_id), facts.end.get(a.external_object_id)
        if ae and xe and ae[2] == "CONSUMED" and xe[2] == "CONSUMED" and ae[0] == xe[0] \
                and (R["available_at"] == ae[0]).any():
            cases.append(_range_case(facts, "IL-V08", "Assignment and live cluster consumed by the same bar",
                                     "pinned_vs_live", R[R["available_at"] == ae[0]].iloc[0],
                                     "Monotonicity: consumption of the live cluster implies consumption of its earlier "
                                     "pinned assignment at or before the same bar."))
            break
    rt = run.range_transitions
    st = run.range_status
    for reason, cid, title in (("INSUFFICIENT_BOUNDARY_DATA", "IL-V09", "Range terminated: no lower beyond"),
                               ("DATA_GAP", "IL-V10", "Range terminated by a data gap"),
                               ("CONTRACT_CHANGE", "IL-V11", "Range terminated by a contract change")):
        hit = rt[rt["reason_code"] == reason] if len(rt) else rt
        if not len(hit):
            continue
        r = hit.iloc[0]
        last = R[R["range_id"] == r["entity_id"]].iloc[-1]
        c = _range_case(facts, cid, title, "termination", last,
                        f"Terminal transition {reason} at {fmt_time(r['transition_at'])}. DATA_GAP / CONTRACT_CHANGE "
                        "end every active level, External object and assignment of the episode at the onset.")
        c.focus_at = r["transition_at"]
        c.window = (r["transition_at"] - pd.Timedelta(minutes=45), r["transition_at"] + pd.Timedelta(minutes=25))
        near = st[(st["from_at"] <= r["transition_at"] + pd.Timedelta(days=4))
                  & (st["until_at"].isna() | (st["until_at"] >= r["transition_at"] - pd.Timedelta(days=1)))]
        c.tables.insert(0, ("Range status around the event", [
            {"status": s.status, "from": fmt_time(s.from_at), "until": fmt_time(s.until_at), "reason": s.end_reason}
            for s in near.itertuples()]))
        c.tables.insert(1, ("Evidence at the event", [facts.bar_at(r["transition_at"])]))
        c.refs["transition_id"] = r["transition_id"]
        cases.append(c)
    post = R[R["post_gap_restricted"].astype(bool) & (ck == "ESTABLISHED")]
    if len(post):
        cases.append(_range_case(facts, "IL-V12", "Re-establishment after a gap (post-gap formations only)", "gap",
                                 post.iloc[0], "post_gap_restricted = true: candidates and levels are formations whose "
                                 "every source follows the gap onset."))
    L = run.levels
    ev = run.consumption_evidence
    lev_ev = ev[ev["object_kind"] == "INTERNAL_LEVEL"] if len(ev) else ev
    if len(lev_ev):
        eq = lev_ev[(lev_ev["status"] == "CONSUMED") & (lev_ev["max_penetration_ticks"] == 4)]
        if len(eq):
            cases.append(_level_case(facts, "IL-V13", "Strict threshold: equality first, consumption later",
                                     "threshold", eq.iloc[0]["object_id"],
                                     "Before consuming, the maximum penetration beyond p was exactly the 4-tick tolerance "
                                     "(equality with θ never consumes); the first bar strictly beyond θ consumes."))
    sup = L[L["change_kind"] == "EVIDENCE_SUPERSEDED"]
    if len(sup):
        cases.append(_level_case(facts, "IL-V14", "REQ outermost moved: EVIDENCE_SUPERSEDED", "versions",
                                 sup.iloc[0]["level_id"], "The REQ version moved to the level at the new outermost; "
                                 "this level keeps its own swing evidence.", focus=sup.iloc[0]["available_at"]))
    first = L.groupby("level_id").head(1)
    delayed = first[(first["primary_family"] == "SWING") & (first["primary_timeframe"] == "5m")]
    if len(delayed):
        r = delayed.iloc[len(delayed) // 2]
        c = _level_case(facts, "IL-V15", "Delayed confirmation (5m swing; 2-bar right window)", "delayed",
                        r["level_id"], "The level exists only from the swing's availability (after the two right-window "
                        "5m bars); earlier 1m bars, including those at the extreme, never test it.",
                        focus=r["available_at"])
        c.window = (r["available_at"] - pd.Timedelta(minutes=30), r["available_at"] + pd.Timedelta(minutes=20))
        cases.append(c)
    for r in first.itertuples(index=False):
        b = facts.bar_at(r.available_at)
        if b.get("open") == "absent":
            continue
        hi, lo_ = float(b["high"].replace(",", "")), float(b["low"].replace(",", ""))
        if (r.side == "UPPER" and hi > r.consumption_threshold) or (r.side == "LOWER" and lo_ < r.consumption_threshold):
            cases.append(_level_case(facts, "IL-V16", "Same-close admission not consumed by its own bar", "same_close",
                                     r.level_id, "Bar m exceeds θ, but the level became available at e(m): it is "
                                     "first tested by bar m+1.", focus=r.available_at))
            break
    for r in first[first["external_coincidence"].map(len) > 0].itertuples(index=False):
        xid = r.external_coincidence[0]
        le, xe = facts.end.get(r.level_id), facts.end.get(xid)
        if le and le[2] == "CONSUMED" and (xe is None or xe[0] > le[0]):
            cases.append(_level_case(facts, "IL-V17", "Coincident internal + External: separate statuses",
                                     "price_record", r.level_id, "One price record: the internal level (θ ±4) is "
                                     "consumed while the External object (θ ±6) stays ACTIVE.", extra_lines=[xid]))
            break
    for tier, cid in (("1H SWING", "IL-V18"), ("5m EQ", "IL-V19"), ("15m REQ", "IL-V20")):
        hit = L[L["grade_tier"] == tier]
        if tier == "1H SWING":
            hit = hit[hit["grade_profile"].str.contains('"candle_and_swing_coincide":true')]
        if len(hit):
            r = hit.iloc[0]
            cases.append(_level_case(facts, cid, f"Grade: {tier}", "grade", r["level_id"], r["grade_explanation"],
                                     focus=r["available_at"]))
    gap = tr[(tr["reason_code"] == "DATA_GAP") & (tr["attr_object_kind"] == "INTERNAL_LEVEL")]
    if len(gap):
        cases.append(_level_case(facts, "IL-V21", "Internal level terminated by a gap (never revived)", "gap",
                                 gap.iloc[0]["entity_id"], "DATA_GAP at the §G.2a onset; no pre-gap identity revives."))
    m = run.memberships
    if len(m):
        exc = m[m["end_reason"] == "RANGE_VERSION_EXCLUDES"]
        for r in exc.itertuples(index=False):
            v = R[R["available_at"] == r.until_at]
            if len(v):
                c = _range_case(facts, "IL-V22", "Membership leaves: RANGE_VERSION_EXCLUDES", "membership", v.iloc[0],
                                "After the boundary change the level is no longer strictly inside the pinned range.")
                c.lines += facts.object_lines(r.level_id)
                cases.append(c)
                break
    return cases, facts


# ---------------------------------------------------------------------------
# Synthetic worked examples on the production engine (E23 / E24 / E25 / E12)
# ---------------------------------------------------------------------------


def synthetic_runs(spec) -> dict:
    from datetime import date

    from src.data.timeframes import TimeframeSpec, expected_timeframe_schedule
    from src.liquidity.consumption import build_minute_tape
    from src.liquidity.contract import MEMBER_COLUMNS, STRUCTURE_COLUMNS
    from src.liquidity.internal_formation import InternalFormationResult
    from src.liquidity.internal_liquidity import run_internal_liquidity

    sched = expected_timeframe_schedule([date(2026, 9, 14)], TimeframeSpec("1m", 1), spec)
    ends = list(pd.to_datetime(sched["bar_end"]).dt.tz_convert("UTC"))
    tick = Decimal("0.25")

    def build(bar, extend, extra=(), internal=(), bars_at=None):
        rows = [(50, 50.25, 49.75, 50)] * 16
        rows[8] = bar
        for k, row in (bars_at or {}).items():
            rows[k] = row
        bars = pd.DataFrame([(20000 + o, 20000 + h, 20000 + l, 20000 + c, 1, "MNQ 12-26") for o, h, l, c in rows],
                            columns=["open", "high", "low", "close", "volume", "contract"],
                            index=pd.DatetimeIndex([t.tz_convert(NY) for t in ends[:16]], name="timestamp_et"))
        tape = build_minute_tape(bars, spec, instrument_id="MNQ", replay_cutoff=ends[15], tick=tick)

        def mem(mid, kind, fam, side, price, k):
            return {"member_id": mid, "liquidity_class": "EXTERNAL", "member_kind": kind, "reference_family": fam,
                    "orientation": side, "price": 20000 + price, "source_ref": f"SYN:{mid}", "source_at": ends[k],
                    "source_seq_domain": None, "source_seq": None, "available_at": ends[k],
                    "available_seq_domain": None, "available_seq": None, "instrument_id": "MNQ",
                    "contract_scope": "SPECIFIC", "contract": "MNQ 12-26", "definition_version": "synthetic"}

        def st(sid, members, k, change, sup):
            return {"structure_id": sid, "liquidity_class": "EXTERNAL", "structure_type": "REQ",
                    "reference_family": "4H", "orientation": "UPPER", "member_ids": tuple(members),
                    "available_at": ends[k], "available_seq_domain": None, "available_seq": None,
                    "instrument_id": "MNQ", "contract_scope": "SPECIFIC", "contract": "MNQ 12-26",
                    "change_kind": change, "supersedes": tuple(sup), "definition_version": "synthetic"}
        xm = [mem("DL", "DAILY_LOW", "1D", "LOWER", -100, 1), mem("DH", "DAILY_HIGH", "1D", "UPPER", 180, 1),
              mem("H1", "HTF_EQREQ_HIGH", "4H", "UPPER", 99, 1), mem("H2", "HTF_EQREQ_HIGH", "4H", "UPPER", 100, 1)]
        xm += [mem(*d) for d in extra]
        xs = [st("C1", ["H1", "H2"], 1, "FORMED", ())]
        if extend:
            xm.append(mem("H3", "HTF_EQREQ_HIGH", "4H", "UPPER", 101, 5))
            xs.append(st("C2", ["H1", "H2", "H3"], 5, "EXTENDED", ["C1"]))
        im = []
        spans = {}
        for mid, price, k in internal:
            row = mem(mid, "INTERNAL_SWING_HIGH", "5m", "UPPER", price, k)
            row["liquidity_class"] = "INTERNAL"
            im.append(row)
            spans[mid] = (ends[k - 3].value, ends[k - 2].value, "5m")
        formation = InternalFormationResult(members=pd.DataFrame(im, columns=MEMBER_COLUMNS),
                                            structures=pd.DataFrame(columns=STRUCTURE_COLUMNS), spans=spans)
        for m in xm:
            end = pd.Timestamp(m["source_at"]).value
            spans[("bar", m["reference_family"], end)] = (end - 4 * 60_000_000_000, end, m["reference_family"])
        return run_internal_liquidity(formation, pd.DataFrame(xm, columns=MEMBER_COLUMNS),
                                      pd.DataFrame(xs, columns=STRUCTURE_COLUMNS), tape, instrument_id="MNQ", tick=tick,
                                      spans=spans)

    return {"E23": build((50, 101.75, 49.75, 60), True), "E24": build((50, 102.75, 49.75, 60), True),
            "E25": build((50, 101.75, 49.75, 60), False),
            "E12": build((50, 102.75, -101.75, 0), False, extra=[("DL2", "DAILY_LOW", "1D", "LOWER", -180, 3)]),
            "E4": build((50, 50.25, 49.75, 50), False, internal=[("S60", 60, 5)], bars_at={5: (50, 62, 49.75, 50)}),
            "E19": build((50, 76.25, 49.75, 50), False, extra=[("D75", "DAILY_HIGH", "1D", "UPPER", 75, 3)],
                         internal=[("S75", 75, 4)], bars_at={11: (50, 76.75, 49.75, 50)})}


SYNTHETIC_NOTES = {
    "E23": "Extension 20,100.00 → 20,101.00 after BA1 was pinned. h = 20,101.75 consumes BA1 (θ 20,101.50) but not the "
           "cluster (θ 20,102.50); BA2 is pinned to the extended cluster at 20,101.00.",
    "E24": "h = 20,102.75 consumes BA1 and the live cluster; the advance skips the cluster and pins the Daily high 20,180.",
    "E25": "No extension: BA1 and the cluster (v1) are consumed together (P-1); the advance pins the Daily high 20,180.",
    "E12": "One bar consumes both pinned boundaries; both sides advance (BOTH_ADVANCED) to the farther candidates.",
    "E4": "A 5m swing level 20,060.00 (θ 20,061.00) becomes available at e(m) of a bar with h = 20,062.00: that bar never "
          "tests it (same-close admission); later bars stay below θ, so it remains ACTIVE.",
    "E19": "Internal swing 20,075.00 (θ 20,076.00) coincides with a non-boundary Daily high 20,075.00 (θ 20,076.50) admitted "
           "after establishment: h = 20,076.25 consumes the internal level only; h = 20,076.75 later consumes the "
           "External object. One price record, separate statuses; confluence 1 (overlapping source spans).",
}


def build_synthetic_cases(runs: dict) -> tuple[list[Case], dict]:
    cases, facts = [], {}
    for name, run in runs.items():
        f = Facts(run)
        facts[f"syn_{name}"] = f
        if name in ("E4", "E19"):
            lid = run.levels["level_id"].iloc[0]
            extra = ["D75"] if name == "E19" else []
            c = _level_case(f, f"IL-S-{name}", f"Synthetic {name}", "synthetic", lid, SYNTHETIC_NOTES[name],
                            extra_lines=extra)
            c.refs["_run"] = f"syn_{name}"
            c.window = (pd.Timestamp(int(run.tape.episodes[0].bar_end[0]), tz="UTC"), run.tape.replay_cutoff)
            c.focus_at = run.levels["available_at"].iloc[0] if name == "E4" else c.focus_at
            cases.append(c)
            continue
        v = run.ranges.sort_values("available_at").iloc[-1]
        c = _range_case(f, f"IL-S-{name}", f"Synthetic {name}", "synthetic", v, SYNTHETIC_NOTES[name])
        c.refs["_run"] = f"syn_{name}"
        c.window = (pd.Timestamp(int(run.tape.episodes[0].bar_end[0]), tz="UTC"), run.tape.replay_cutoff)
        cases.append(c)
    return cases, facts
