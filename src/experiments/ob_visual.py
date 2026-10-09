"""Order Block / Breaker / Mitigation — OB-I5 visual validation package (local HTML with prices; price-free manifest).

Charts are planned, not clamped: every case gets one or two panels (formation, lifecycle) whose windows contain the
events they claim to show — the focus instant is always inside a plotted panel.  Objects outside a panel are omitted
and listed under it ("omitted context"), never drawn as edge slivers; objects that start or end outside a panel are
drawn over their visible part with ◀ / ▶ continuation marks.  Right-margin labels are de-overlapped and simultaneous
markers are merged into one label.

Tables carry the numerical decision evidence (source OHLC and body ticks, window boundary swings and their
confirmations, FVG candidates, validation close vs the source-wick threshold, A / B / C spans with raid evidence,
failure / retirement closes vs the stage boundary), the focal observation's own timeframe bar for pre- / post-state,
and keep later audit outcomes separate from what was known at the focus.  Missing values render as "—".
Times are New York.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import html
import json
import math

import numpy as np
import pandas as pd

from src.experiments.fvg_visual import STYLE, capped, fmt_p, fmt_t

MAX_BARS = 60
PAD = 4
DASH = "—"


def _missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, (str, bool, tuple, list)):
        return False
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def cell(v) -> str:
    """Display text for a table value; missing values (None / NaN / NaT / 'nan') render as an em dash."""
    if _missing(v) or (isinstance(v, str) and v.strip().lower() in ("nan", "nat", "none", "")):
        return DASH
    if isinstance(v, float) and math.isfinite(v) and float(v).is_integer():
        return str(int(v))
    return str(v)


def table(caption, rows) -> str:
    if not rows:
        return f"<h4>{html.escape(caption)}</h4><p class='note'>none</p>"
    cols = list(dict.fromkeys(k for r in rows for k in r))
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(cell(r.get(c)))}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<h4>{html.escape(caption)}</h4><div class='tw'><table><tr>{head}</tr>{body}</table></div>"


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
    partner_block_id: str | None = None          # concurrent case: the old parent whose successor shares the instant
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
        self.fvg = run.fvg_zones.set_index("zone_id") if run.fvg_zones is not None and len(run.fvg_zones) else None
        self.swing_ix = {}
        for tf, per in run.swings.items():
            for sws in per.values():
                for s in sws:
                    self.swing_ix[s.swing_id] = (tf, s)

    def p(self, ticks):
        return None if _missing(ticks) else float(Decimal(int(ticks)) * self.tick)

    def seg(self, tf, si):
        return self.run.obs[tf].segments[si]

    def tf_bar(self, tf, end_ns):
        """(segment, position) of the own-timeframe bar ending at ``end_ns``, or None."""
        return self.run.obs[tf].pos.get(int(end_ns))

    def bar_row(self, tf, si, k):
        g = self.seg(tf, si)
        return {"bar": f"{fmt_t(pd.Timestamp(int(g['start'][k]), tz='UTC'))} → {fmt_t(pd.Timestamp(int(g['end'][k]), tz='UTC'))}",
                "O": fmt_p(self.p(g["o"][k])), "H": fmt_p(self.p(g["h"][k])), "L": fmt_p(self.p(g["l"][k])),
                "C": fmt_p(self.p(g["c"][k]))}

    def bars(self, tf, si, k0, k1):
        g = self.seg(tf, si)
        k0, k1 = max(0, k0), min(len(g["end"]) - 1, k1)
        return [(int(g["start"][k]), int(g["end"][k]), self.p(g["o"][k]), self.p(g["h"][k]), self.p(g["l"][k]),
                 self.p(g["c"][k])) for k in range(k0, k1 + 1)]

    def swing(self, sid):
        if not isinstance(sid, str) or sid not in self.swing_ix:
            return None
        return self.swing_ix[sid][1]


# ---------------------------------------------------------------------------
# Chart planning (testable) and rendering
# ---------------------------------------------------------------------------


@dataclass
class Item:
    kind: str            # "span" | "box" | "mark"
    start: int
    end: int | None      # None: open to the right
    label: str
    lo: float | None = None
    up: float | None = None
    mid: float | None = None
    klass: str = ""
    price: float | None = None


@dataclass
class Panel:
    title: str
    k0: int
    k1: int
    ts: int = 0
    te: int = 0
    drawn: list = field(default_factory=list)
    clipped: list = field(default_factory=list)
    omitted: list = field(default_factory=list)


def _block_items(f: Facts, bid, tag=""):
    b = f.blocks.loc[bid]
    r = f.regions.loc[b["source_region_id"]]
    items = []
    st = f.run.engine.stages[f.run.engine.stages["block_id"] == bid]
    for s in st.itertuples():
        items.append(Item("box", s.available_at.value, None if pd.isna(s.ended_at) else s.ended_at.value,
                          f"{tag}{s.stage_kind} {s.direction[:4]}", r["lower"], r["upper"], r["zone_midpoint"],
                          "zone" if s.stage_kind == "ORDINARY" else "bpr"))
    if f.fvg is not None and b["formation_fvg_id"] in f.fvg.index:
        z = f.fvg.loc[b["formation_fvg_id"]]
        items.append(Item("box", z["available_at"].value, None, f"{tag}formation FVG", z["lower"], z["upper"],
                          z["midpoint"], "fvgbox"))
    ep = f.episodes.loc[b["episode_id"]]
    labels = [("B" if tag == "" else f"{tag}B", ep["anchor_swing_id"])]
    mo = f.run.engine.motifs[f.run.engine.motifs["block_id"] == bid]
    if len(mo):
        m = mo.iloc[0]
        labels += [(f"{tag}A", m["a_swing_id"]), (f"{tag}C", m["c_swing_id"])]
    for lab, sid in labels:
        sw = f.swing(sid)
        if sw is None:
            continue
        g = f.seg(b["timeframe"], sw.seg)
        items.append(Item("span", int(g["start"][sw.a]), int(g["end"][sw.b]), f"{lab} {fmt_p(f.p(sw.price))}",
                          price=f.p(sw.price), klass="UPPER" if sw.orientation == "UPPER" else "LOWER"))
        items.append(Item("mark", sw.available_ns, sw.available_ns, f"{lab} confirmed"))
    items.append(Item("mark", b["ordinary_available_at"].value, b["ordinary_available_at"].value, f"{tag}ordinary available"))
    for x_ in f.run.engine.lifecycle[f.run.engine.lifecycle["block_id"] == bid].itertuples():
        items.append(Item("mark", x_.at.value, x_.at.value, f"{tag}{x_.to_state.lower()}"))
    return items


def plan_panels(f: Facts, case: Case) -> list:
    """Formation panel around the source → admission; a lifecycle panel around the focus when the focus (or the
    lifecycle events of the case) are not inside the formation panel.  Each panel ≤ MAX_BARS own-tf bars."""
    eid = case.episode_id or f.blocks.loc[case.block_id, "episode_id"]
    ep = f.episodes.loc[eid]
    tf = ep["timeframe"]
    anchor = f.swing(ep["anchor_swing_id"])
    si = anchor.seg
    g = f.seg(tf, si)
    ends = g["end"]
    pos = lambda ns: int(np.searchsorted(ends, int(ns), side="left"))  # noqa: E731
    k_src = anchor.b
    k_form = k_src
    if case.block_id is not None:
        k_form = max(k_form, pos(f.blocks.loc[case.block_id, "ordinary_available_at"].value))
    elif not _missing(ep["decided_at"]):
        k_form = max(k_form, pos(pd.Timestamp(ep["decided_at"]).value))
    n = len(ends)
    k_focus = pos(case.focus.value)                 # first bar ending at or after the focus
    beyond = k_focus >= n                           # e.g. a reset instant after the segment's last bar
    k_focus = min(k_focus, n - 1)
    first = Panel("formation", max(0, k_src - 2 * PAD), min(n - 1, k_form + PAD))
    if first.k1 - first.k0 + 1 > MAX_BARS:
        first.k0 = max(0, first.k1 - MAX_BARS + 1)
    panels = [first]
    if not first.k0 <= k_focus <= first.k1:
        k0 = max(first.k1 + 1, k_focus - (MAX_BARS - PAD - 1))
        mo = f.run.engine.motifs[f.run.engine.motifs["block_id"] == case.block_id] if case.block_id else None
        if mo is not None and len(mo):            # include the reversal swing C when it fits
            c = f.swing(mo.iloc[0]["c_swing_id"])
            if c is not None and c.a > first.k1 and k_focus - c.a <= MAX_BARS - PAD - 1:
                k0 = min(k0, max(first.k1 + 1, c.a - 1))
        panels.append(Panel("lifecycle", k0, min(n - 1, k_focus + PAD)))
    for pnl in panels:
        pnl.ts, pnl.te = int(g["start"][pnl.k0]), int(ends[pnl.k1])
        if beyond and pnl.k0 <= k_focus <= pnl.k1:
            pnl.te = max(pnl.te, int(case.focus.value))
    return panels, tf, si


def _place(items, panel):
    for it in items:
        end = it.end if it.end is not None else math.inf
        if end < panel.ts or it.start > panel.te or (it.kind == "mark" and not panel.ts < it.start <= panel.te):
            panel.omitted.append(it)
        elif it.start < panel.ts or (it.end is not None and it.end > panel.te):
            panel.clipped.append(it)
        else:
            panel.drawn.append(it)


def _spread(labels, lo, hi, gap=11.0):
    """De-overlap right-margin labels: (y, text, klass) sorted by y with a minimum vertical gap."""
    out, last = [], -1e9
    for y, text, klass in sorted(labels):
        y = max(y, last + gap)
        out.append((min(y, hi), text, klass))
        last = y
    return out


def render_panel(f: Facts, case: Case, panel: Panel, tf, si, items, W=980, H=360) -> str:
    g = f.seg(tf, si)
    bars = f.bars(tf, si, panel.k0, panel.k1)
    _place(items, panel)
    vis = panel.drawn + panel.clipped
    prices = [b[3] for b in bars] + [b[4] for b in bars]
    prices += [x for it in vis if it.kind == "box" for x in (it.lo, it.up)]
    prices += [it.price for it in vis if it.kind == "span" and it.price is not None]
    lo_p, hi_p = min(prices), max(prices)
    pad = max((hi_p - lo_p) * 0.06, 0.5)
    lo_p, hi_p = lo_p - pad, hi_p + pad
    L, R, T, B = 74, 190, 14, 30
    ts, te = panel.ts, panel.te
    x = lambda ns: L + (W - L - R) * (min(max(ns, ts), te) - ts) / max(te - ts, 1)  # noqa: E731
    y = lambda p: T + (H - T - B) * (hi_p - p) / (hi_p - lo_p)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img"><text x="{L}" y="11" class="ax">{html.escape(panel.title)} '
           f'panel ({tf})</text>']
    for k in range(6):
        p = lo_p + (hi_p - lo_p) * k / 5
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(p):.1f}" y2="{y(p):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{y(p) + 4:.1f}" class="ax" text-anchor="end">{p:,.2f}</text>')
    labels = []
    for it in vis:
        if it.kind != "span":
            continue
        xa, xb = x(it.start), x(it.end)
        out.append(f'<rect x="{xa:.1f}" y="{T}" width="{max(xb - xa, 2):.1f}" height="{H - T - B}" class="span"/>')
        out.append(f'<text x="{xb + 2:.1f}" y="{y(it.price) + (-6 if it.klass == "UPPER" else 14):.1f}" class="lab">'
                   f'{html.escape(it.label)}{" ◀" if it.start < ts else ""}</text>')
    bw = max(2.0, (W - L - R) / max(len(bars), 1) * 0.6)
    src = None
    eid = case.episode_id or f.blocks.loc[case.block_id, "episode_id"]
    sw = f.swing(f.episodes.loc[eid, "anchor_swing_id"])
    if sw is not None and sw.seg == si:
        src = int(g["end"][sw.b])
    for s0, e0, o, h, l, c in bars:
        cx = (x(s0) + x(e0)) / 2
        cls = "up" if c > o else ("dn" if c < o else "dj")
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(h):.1f}" y2="{y(l):.1f}" class="wick {cls}"/>'
                   f'<rect x="{cx - bw / 2:.1f}" y="{min(y(o), y(c)):.1f}" width="{bw:.1f}" '
                   f'height="{max(abs(y(o) - y(c)), 1):.1f}" class="body {cls}{" c2" if e0 == src else ""}"/>')
    for it in vis:
        if it.kind != "box":
            continue
        xa, xb = x(it.start), x(te if it.end is None else it.end)
        out.append(f'<rect x="{xa:.1f}" y="{y(it.up):.1f}" width="{max(xb - xa, 2):.1f}" height="{max(y(it.lo) - y(it.up), 1):.1f}" class="{it.klass}"/>'
                   f'<line x1="{xa:.1f}" x2="{xb:.1f}" y1="{y(it.mid):.1f}" y2="{y(it.mid):.1f}" class="mid"/>')
        cont = ("◀ " if it.start < ts else "") + ("▶" if it.end is None or it.end > te else "")
        labels.append((y(it.up), f"{it.label} {fmt_p(it.lo)}–{fmt_p(it.up)} {cont}".strip(), it.klass))
    for yy, text, klass in _spread(labels, T, H - B):
        out.append(f'<text x="{W - R + 4}" y="{yy + 4:.1f}" class="lab {klass}">{html.escape(text)}</text>')
    marks: dict = {}
    for it in vis:
        if it.kind == "mark":
            marks.setdefault(round(x(it.start)), []).append(it.label)
    for i, (xx, labs) in enumerate(sorted(marks.items())):
        out.append(f'<line x1="{xx}" x2="{xx}" y1="{T}" y2="{H - B}" class="mark"/>'
                   f'<text x="{xx + 2}" y="{H - B - 6 - 11 * (i % 4)}" class="lab mark">▲ {html.escape(" / ".join(sorted(set(labs))))}</text>')
    if ts < case.focus.value <= te:
        fx = x(case.focus.value)
        out.append(f'<line x1="{fx:.1f}" x2="{fx:.1f}" y1="{T}" y2="{H - B}" class="focus"/>'
                   f'<text x="{fx:.1f}" y="{H - 8}" class="ax" text-anchor="middle">focus {fmt_t(case.focus)}</text>')
    out.append(f'<text x="{L}" y="{H - 8}" class="ax">{fmt_t(pd.Timestamp(ts, tz="UTC"))}</text>'
               f'<text x="{W - R}" y="{H - 8}" class="ax" text-anchor="end">{fmt_t(pd.Timestamp(te, tz="UTC"))}</text></svg>')
    if panel.omitted:
        names = sorted({f"{it.label} ({fmt_t(pd.Timestamp(it.start, tz='UTC'))})" for it in panel.omitted})
        out.append(f"<p class='note'>Omitted context outside this panel: {html.escape('; '.join(names))}</p>")
    return "".join(out)


def chart(f: Facts, case: Case) -> str:
    if case.block_id is None and case.episode_id is None:
        return ""
    panels, tf, si = plan_panels(f, case)
    items = []
    if case.block_id is not None:
        items += _block_items(f, case.block_id)
    else:
        ep = f.episodes.loc[case.episode_id]
        sw = f.swing(ep["anchor_swing_id"])
        g = f.seg(tf, sw.seg)
        items.append(Item("span", int(g["start"][sw.a]), int(g["end"][sw.b]), f"anchor {fmt_p(f.p(sw.price))}",
                          price=f.p(sw.price), klass=sw.orientation))
        items.append(Item("mark", sw.available_ns, sw.available_ns, "anchor confirmed"))
        for col in ("window_swing_id", "superseded_by_swing_id"):
            b_ = f.swing(ep[col])
            if b_ is not None:
                items.append(Item("span", int(g["start"][b_.a]), int(g["end"][b_.b]),
                                  f"{'window end' if col == 'window_swing_id' else 'new same-side'} {fmt_p(f.p(b_.price))}",
                                  price=f.p(b_.price), klass=b_.orientation))
                items.append(Item("mark", b_.available_ns, b_.available_ns, "boundary confirmed"))
        if not _missing(ep["decided_at"]):
            items.append(Item("mark", pd.Timestamp(ep["decided_at"]).value, pd.Timestamp(ep["decided_at"]).value,
                              str(ep["status"]).lower()))
    if case.partner_block_id is not None:
        items += _block_items(f, case.partner_block_id, tag="parent ")
    return "".join(render_panel(f, case, p, tf, si, [Item(**vars(i)) for i in items]) for p in panels)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def focal_observation(f: Facts, tf, at) -> dict:
    """The observation the focus instant closes: the own-timeframe bar, else a 1m bar, else a reset instant."""
    at = pd.Timestamp(at)
    loc = f.tf_bar(tf, at.value)
    if loc is not None:
        g = f.seg(tf, loc[0])
        return {"observation": f"{tf} bar", "bar_start": pd.Timestamp(int(g["start"][loc[1]]), tz="UTC"), "bar_end": at}
    m = f.run.tape.locate(at.value)
    if m is not None:
        e = f.run.tape.episodes[m[0]]
        return {"observation": "1m bar", "bar_start": pd.Timestamp(int(e.start[m[1]]), tz="UTC"), "bar_end": at}
    return {"observation": "reset instant (no bar closes here)", "bar_start": at, "bar_end": at}


def _state_at(f: Facts, block_id, at, strict=False):
    lc = f.run.engine.lifecycle
    lc = lc[(lc["block_id"] == block_id) & ((lc["at"] < at) if strict else (lc["at"] <= at))]
    if len(lc):
        return lc.iloc[-1]["to_state"]
    adm = f.blocks.loc[block_id, "ordinary_available_at"]
    return "ORDINARY" if (adm < at if strict else adm <= at) else "NOT YET ADMITTED"


def pre_post_rows(f: Facts, bid, at) -> list:
    tf = f.blocks.loc[bid, "timeframe"]
    o = focal_observation(f, tf, at)
    return [{"focal observation": o["observation"], "bar start": fmt_t(o["bar_start"]), "bar end / instant": fmt_t(o["bar_end"]),
             "pre-state (before the observation)": _state_at(f, bid, o["bar_start"], strict=o["bar_start"] == o["bar_end"]),
             "post-state (after it)": _state_at(f, bid, o["bar_end"])}]


def window_rows(f: Facts, eid) -> list:
    """Numerical window evidence of a discovery episode (source, boundaries, FVG candidates, validation)."""
    e = f.episodes.loc[eid]
    tf = e["timeframe"]
    anchor = f.swing(e["anchor_swing_id"])
    g = f.seg(tf, anchor.seg)
    s = anchor.b
    bull = e["direction"] == "BULLISH"
    o, h, l, c = (int(g[k][s]) for k in ("o", "h", "l", "c"))
    body = abs(c - o)
    rows = [{"item": "source candle (terminal swing bar)", **f.bar_row(tf, anchor.seg, s), "body ticks": body,
             "test": f"body {body} {'≥' if body >= 4 else '<'} 4 ticks; {'bearish' if c < o else 'bullish' if c > o else 'doji'} "
                     f"(needs {'bearish' if bull else 'bullish'})"}]
    opp_or = "UPPER" if bull else "LOWER"
    sws = [sw for sw in f.run.swings[tf].get(anchor.seg, [])]
    H = next((sw for sw in sorted(sws, key=lambda q: q.a) if sw.orientation == opp_or and sw.a > s), None)
    L2 = next((sw for sw in sorted(sws, key=lambda q: q.a) if sw.orientation == anchor.orientation and sw.a > s), None)
    e_end = len(g["end"]) - 1
    for lab, sw, edge in (("window end: first opposite swing", H, "H"), ("new same-side swing", L2, "L2")):
        if sw is None:
            rows.append({"item": lab, "test": "none in the data"})
            continue
        if edge == "H":
            e_end = min(e_end, sw.b)
        else:
            e_end = min(e_end, sw.a - 1)
        rows.append({"item": lab, "bar": f"{fmt_t(pd.Timestamp(int(g['start'][sw.a]), tz='UTC'))} → "
                                          f"{fmt_t(pd.Timestamp(int(g['end'][sw.b]), tz='UTC'))}",
                     "price": fmt_p(f.p(sw.price)), "confirmed": fmt_t(pd.Timestamp(sw.available_ns, tz="UTC"))})
    rows.append({"item": "departure window (inclusive)", "bar": f"after {fmt_t(pd.Timestamp(int(g['end'][s]), tz='UTC'))} "
                                                                f"through {fmt_t(pd.Timestamp(int(g['end'][e_end]), tz='UTC'))}"})
    fv = [x_ for x_ in f.run.fvgs[tf].get(anchor.seg, []) if x_.direction == e["direction"] and s < x_.c2 <= e_end]
    rows.append({"item": f"{e['direction'].lower()} FVG candidates with C2 in the window", "test": len(fv),
                 "C": ", ".join(f"C2 {fmt_t(pd.Timestamp(int(g['end'][x_.c2]), tz='UTC'))} [{fmt_p(f.p(x_.lower))}–{fmt_p(f.p(x_.upper))}]"
                                for x_ in fv[:3]) or DASH})
    thr = h if bull else l
    closes = g["c"][s + 1:e_end + 1]
    ext = (int(closes.max()) if bull else int(closes.min())) if len(closes) else None
    rows.append({"item": "validation threshold (source far wick)", "C": fmt_p(f.p(thr)),
                 "test": DASH if ext is None else f"{'max' if bull else 'min'} close in window {fmt_p(f.p(ext))} "
                                                  f"{('>' if bull else '<') if (ext > thr if bull else ext < thr) else ('≤' if bull else '≥')} "
                                                  f"{fmt_p(f.p(thr))} → {'validated' if (ext > thr if bull else ext < thr) else 'not validated'}"})
    rows.append({"item": "decision", "test": f"{e['status']} {cell(e['reason'])} at {fmt_t(e['decided_at'])}"})
    return rows


def motif_rows(f: Facts, m, tf) -> list:
    rows = []
    for lab, sid, px in (("A (prior extreme)", m["a_swing_id"], m["a_price_ticks"]),
                         ("B (pinned anchor)", m["b_swing_id"], m["b_price_ticks"]),
                         ("C (reversal swing)", m["c_swing_id"], m["c_price_ticks"])):
        sw = f.swing(sid)
        if sw is None:
            rows.append({"role": lab, "price": fmt_p(f.p(px))})
            continue
        g = f.seg(tf, sw.seg)
        rows.append({"role": lab, "span": f"{fmt_t(pd.Timestamp(int(g['start'][sw.a]), tz='UTC'))} → "
                                          f"{fmt_t(pd.Timestamp(int(g['end'][sw.b]), tz='UTC'))}",
                     "price": fmt_p(f.p(px)), "confirmed": fmt_t(pd.Timestamp(sw.available_ns, tz="UTC"))})
    return rows


def raid_rows(f: Facts, m, b) -> list:
    A, B = f.swing(m["a_swing_id"]), f.swing(m["b_swing_id"])
    if A is None or B is None:
        return [{"raid evidence": "no prior extreme A"}]
    tf = b["timeframe"]
    g = f.seg(tf, B.seg)
    x = int(np.searchsorted(g["end"], m["break_observed_at"].value))
    bull_parent = b["ordinary_direction"] == "BULLISH"
    seg_h = g["h"][B.b + 1:x + 1] if bull_parent else g["l"][B.b + 1:x + 1]
    ext = (int(seg_h.max()) if bull_parent else int(seg_h.min())) if len(seg_h) else None
    return [{"excursion": f"after B through the break ({x - B.b} bars)",
             f"{'max high' if bull_parent else 'min low'} in excursion": fmt_p(f.p(ext)),
             "A price": fmt_p(f.p(A.price)), "raid (strictly beyond A)": bool(m["raid_observed"]),
             "first raid bar": fmt_t(m["first_raid_at"]),
             "C vs A": DASH if _missing(m["c_price_ticks"]) else
             f"{fmt_p(f.p(m['c_price_ticks']))} vs {fmt_p(f.p(A.price))}"}]


def close_test_rows(f: Facts, bid) -> list:
    """Validation close vs the source wick, failure close vs the ordinary far boundary, successor retirement /
    invalid-before-admission closes vs the successor's far boundary."""
    b = f.blocks.loc[bid]
    r = f.regions.loc[b["source_region_id"]]
    tf = b["timeframe"]
    bull = b["ordinary_direction"] == "BULLISH"
    rows = []
    v = f.tf_bar(tf, b["validation_close_at"].value)
    if v is not None:
        c = int(f.seg(tf, v[0])["c"][v[1]])
        thr = int(r["source_high_ticks"] if bull else r["source_low_ticks"])
        rows.append({"test": "validation close vs source far wick", "at": fmt_t(b["validation_close_at"]),
                     "close": fmt_p(f.p(c)), "threshold": fmt_p(f.p(thr)),
                     "predicate": f"{fmt_p(f.p(c))} {'>' if bull else '<'} {fmt_p(f.p(thr))} → {c > thr if bull else c < thr}"})
    st = f.run.engine.stages[f.run.engine.stages["block_id"] == bid]
    for s in st.itertuples():
        if _missing(s.ended_at) or s.end_reason not in ("ORDINARY_FAILED", "RETIRED"):
            continue
        loc = f.tf_bar(tf, s.ended_at.value)
        if loc is None:
            continue
        c = int(f.seg(tf, loc[0])["c"][loc[1]])
        sb = s.direction == "BULLISH"
        bound = int(r["lower_ticks"] if sb else r["upper_ticks"])
        rows.append({"test": f"{s.stage_kind} close beyond its far boundary", "at": fmt_t(s.ended_at),
                     "close": fmt_p(f.p(c)), "threshold": fmt_p(f.p(bound)),
                     "predicate": f"{fmt_p(f.p(c))} {'<' if sb else '>'} {fmt_p(f.p(bound))} → {c < bound if sb else c > bound}"})
    mo = f.run.engine.motifs[f.run.engine.motifs["block_id"] == bid]
    if len(mo) and mo.iloc[0]["reason"] == "QUALIFIED_BUT_INVALID_BEFORE_ADMISSION":
        m = mo.iloc[0]
        x = f.tf_bar(tf, m["break_observed_at"].value)
        rz = f.tf_bar(tf, m["resolved_at"].value)
        sb = m["successor_direction"] == "BULLISH"
        bound = int(r["lower_ticks"] if sb else r["upper_ticks"])
        g = f.seg(tf, x[0])
        for k in range(x[1] + 1, rz[1] + 1):
            c = int(g["c"][k])
            rows.append({"test": "successor validity before admission", "at": fmt_t(pd.Timestamp(int(g["end"][k]), tz="UTC")),
                         "close": fmt_p(f.p(c)), "threshold": fmt_p(f.p(bound)),
                         "predicate": f"{fmt_p(f.p(c))} {'<' if sb else '>'} {fmt_p(f.p(bound))} → "
                                      f"{c < bound if sb else c > bound} (beyond → invalid)"})
    return rows


def block_tables(f: Facts, case: Case, bid=None, tag="") -> list:
    bid = bid or case.block_id
    t = case.focus
    out = []
    b = f.blocks.loc[bid]
    r = f.regions.loc[b["source_region_id"]]
    tf = b["timeframe"]
    out.append((f"{tag}Block, source candle and geometry (actionable open-to-wick zone vs source body)", [{
        "block": bid[:14], "timeframe": tf, "contract": b["contract"], "ordinary direction": b["ordinary_direction"],
        "source bar": f"{fmt_t(r['source_bar_start'])} → {fmt_t(r['source_bar_end'])}",
        "O": fmt_p(f.p(r["source_open_ticks"])), "H": fmt_p(f.p(r["source_high_ticks"])),
        "L": fmt_p(f.p(r["source_low_ticks"])), "C": fmt_p(f.p(r["source_close_ticks"])), "body ticks": r["body_ticks"],
        "zone lower": fmt_p(r["lower"]), "zone upper": fmt_p(r["upper"]), "zone midpoint": fmt_p(r["zone_midpoint"]),
        "source body midpoint (not the zone midpoint)": fmt_p(r["source_body_midpoint"]), "width ticks": r["width_ticks"]}]))
    out.append((f"{tag}Discovery window evidence", window_rows(f, b["episode_id"])))
    if f.fvg is not None and b["formation_fvg_id"] in f.fvg.index:
        z = f.fvg.loc[b["formation_fvg_id"]]
        loc = f.tf_bar(tf, z["c2_end"].value)
        g = f.seg(tf, loc[0])
        c2_lo, c2_hi = int(g["l"][loc[1]]), int(g["h"][loc[1]])
        bull = b["ordinary_direction"] == "BULLISH"
        out.append((f"{tag}Formation FVG (departure evidence; no adjacency or price overlap required)", [{
            "zone": b["formation_fvg_id"][:14], "FVG lower": fmt_p(z["lower"]), "FVG upper": fmt_p(z["upper"]),
            "available": fmt_t(z["available_at"]),
            "FVG gap entirely beyond the OB zone": bool(z["lower_ticks"] > r["upper_ticks"]) if bull
            else bool(z["upper_ticks"] < r["lower_ticks"]),
            "C2 bar": f.bar_row(tf, loc[0], loc[1])["bar"], "C2 O/H/L/C": "/".join(f.bar_row(tf, loc[0], loc[1])[k] for k in "OHLC"),
            "C2 range entirely beyond the OB zone": (c2_lo > int(r["upper_ticks"])) if bull else (c2_hi < int(r["lower_ticks"]))}]))
    out.append((f"{tag}Close tests (numerical)", close_test_rows(f, bid)))
    mo = f.run.engine.motifs[f.run.engine.motifs["block_id"] == bid]
    if len(mo):
        m = mo.iloc[0]
        out.append((f"{tag}Parent-pinned motif swings (spans and confirmations)", motif_rows(f, m, tf)))
        out.append((f"{tag}Raid evidence (numerical)", raid_rows(f, m, b)))
        out.append((f"{tag}Motif classification", [{
            "break x (close)": fmt_t(m["break_observed_at"]), "C candidates": len(m["c_candidate_ids"] or ()),
            "resolved": fmt_t(m["resolved_at"]), "outcome": m["outcome"], "reason": m["reason"],
            "successor available": fmt_t(m["successor_available_at"])}]))
    out.append((f"{tag}State around the focal observation", pre_post_rows(f, bid, t)))
    lc = f.run.engine.lifecycle[f.run.engine.lifecycle["block_id"] == bid]
    out.append((f"{tag}Lifecycle (one logical change per instant)", [
        {"from": x_.from_state, "to": x_.to_state, "at": fmt_t(x_.at), "reason": x_.reason,
         "known at the focus?": "yes" if x_.at <= t else "no — later audit outcome"} for x_ in lc.itertuples()]))
    st = f.run.engine.stages[f.run.engine.stages["block_id"] == bid]
    out.append((f"{tag}Stage epochs (same block_id)", [
        {"stage": s.stage_kind, "stage id": s.stage_id[:14], "predecessor": cell(s.predecessor_stage_id)[:14],
         "direction": s.direction, "available": fmt_t(s.available_at), "ended": fmt_t(s.ended_at),
         "end reason": s.end_reason, "end known at the focus?": DASH if _missing(s.ended_at)
         else ("yes" if s.ended_at <= t else "no — later audit outcome"), "far boundary": s.far_boundary}
        for s in st.itertuples()]))
    for s in st.itertuples():
        it = f.run.engine.interactions[f.run.engine.interactions["stage_id"] == s.stage_id]
        out.append(capped(f"{tag}{s.stage_kind} stage interactions (1m, from its availability)", [
            {"event": x_.kind, "at": fmt_t(x_.at), "1m H/L": f"{fmt_p(f.p(x_.bar_high_ticks))} / {fmt_p(f.p(x_.bar_low_ticks))}",
             "relative to focus": "at focus" if x_.at == t else ("before" if x_.at < t else "later")}
            for x_ in it.itertuples()], 12, focal=lambda q: q["relative to focus"] == "at focus"))
        v = f.run.engine.visits[f.run.engine.visits["stage_id"] == s.stage_id]
        out.append(visit_table(f"{tag}{s.stage_kind} stage visits", v, t))
    return out


def visit_table(caption, v, t) -> tuple:
    rows = [{"start": fmt_t(x_.started_at), "end": fmt_t(x_.ended_at), "bars": x_.bars, "penetrated": x_.penetrated,
             "midpoint observed": x_.midpoint_observed, "distal observed": x_.distal_observed,
             "max interior depth ticks": x_.max_interior_depth_ticks, "max adverse ticks": x_.max_adverse_excursion_ticks,
             "contains focus": bool(x_.started_at <= t <= x_.ended_at)} for x_ in v.itertuples()]
    return capped(caption, rows, 10, focal=lambda q: q["contains focus"])


def episode_tables(f: Facts, eid) -> list:
    e = f.episodes.loc[eid]
    ev = f.run.engine.evidence[f.run.engine.evidence["episode_id"] == eid]
    return [("Discovery episode", [{"episode": eid[:14], "timeframe": e["timeframe"], "direction": e["direction"],
                                    "anchor swing": e["anchor_swing_id"][:14], "opened (swing confirmed)": fmt_t(e["opened_at"]),
                                    "status": e["status"], "decided": fmt_t(e["decided_at"]), "reason": e["reason"],
                                    "ownership deadline": fmt_t(e["ownership_deadline_at"])}]),
            ("Window and decision evidence (numerical)", window_rows(f, eid)),
            ("Episode evidence (known-at times)", [{"kind": x_.kind, "observed": fmt_t(x_.observed_at), "known": fmt_t(x_.known_at),
                                                   "accepted": x_.accepted, "reason": x_.reason} for x_ in ev.itertuples()])]


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
isolated synthetic fixtures. Each case has a formation panel and, when the focus lies later, a separate lifecycle panel; the
focus is always inside a panel. Amber outline = the single source candle; shaded bands = swing source spans labelled anchor /
A / B / C (window end, new same-side swing for rejections) at the swing price; blue box = ordinary epoch; purple = BREAKER /
MITIGATION epoch of the same block from its own availability; amber box = formation FVG; dashed = zone midpoint; ▲ =
confirmation / availability / lifecycle markers (simultaneous ones merged); ◀ ▶ = continues outside the panel; omitted context
is listed under each panel. Tables separate what was known at the focus from later audit outcomes. Machine evidence only;
human visual approval pending.</p>
{table("Run", header)}<ol>{toc}</ol>{''.join(secs)}</body></html>"""


def manifest_rows(cases) -> list:
    return [{"case_id": c.case_id, "category": c.category, "title": c.title, "source": c.source,
             "focus_at": c.focus.isoformat(), "object_refs": json.dumps(c.refs, sort_keys=True)} for c in cases]


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------


def _pick(df):
    return None if df.empty else df.iloc[len(df) // 2]


def concurrent_pairs(run) -> pd.DataFrame:
    """Independent ordinary OB admitted at the same instant as an older block's successor, asserted relationship:
    different block ids, same timeframe and contract, same direction (opposite to the parent's ordinary direction)."""
    E = run.engine
    st = E.stages.merge(E.blocks[["block_id", "timeframe", "contract", "ordinary_direction"]], on="block_id",
                        suffixes=("", "_b"))
    succ = st[st["stage_kind"] != "ORDINARY"]
    ordn = st[st["stage_kind"] == "ORDINARY"]
    pairs = succ.merge(ordn, on=["available_at", "timeframe", "contract", "direction"], suffixes=("_succ", "_ord"))
    pairs = pairs[pairs["block_id_succ"] != pairs["block_id_ord"]]
    for r in pairs.itertuples(index=False):
        assert r.predecessor_stage_id_succ is not None and not _missing(r.predecessor_stage_id_succ)
        assert _missing(r.predecessor_stage_id_ord)
        assert r.ordinary_direction_succ != r.direction       # successor reverses its parent's ordinary direction
    return pairs.reset_index(drop=True)


def build_cases(run, run_key="dev", source="DEVELOPMENT", prefix="") -> list:
    f = Facts(run)
    E = run.engine
    cases = []

    def bcase(cid, title, cat, bid, focus, note, partner=None):
        c = Case(prefix + cid, title, cat, source, run_key, bid, pd.Timestamp(focus), note, partner_block_id=partner,
                 refs={"block_id": bid, **({"parent_block_id": partner} if partner else {})})
        c.tables = block_tables(f, c)
        if partner:
            c.tables += block_tables(f, c, partner, tag="Parent block — ")
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
    mo = E.motifs
    for outcome, cid, title in (("BREAKER", "BB", "Ordinary → BREAKER (raid beyond the prior extreme)"),
                                ("MITIGATION", "MB", "Ordinary → MITIGATION (failure swing, no raid)")):
        for d0 in ("BULLISH", "BEARISH"):
            r = _pick(mo[(mo["outcome"] == outcome) & (mo["successor_direction"] != d0)])
            if r is not None:
                bcase(f"{cid}-{d0[:4]}", f"{title}, {d0.lower()} parent", "successor", r["block_id"],
                      r["successor_available_at"], "Successor inherits the exact interval, reverses direction and starts "
                      "its own interaction history at its availability (no conversion-bar retest).")
    for reason in ("NO_PRIOR_EXTREME", "NO_REVERSAL_SWING", "EQUAL_EXTREME", "RAID_WITH_LESS_EXTREME_C",
                   "QUALIFIED_BUT_INVALID_BEFORE_ADMISSION", "EQUAL_EXTREME_WITH_RAID"):
        r = _pick(mo[mo["reason"] == reason])
        if r is not None:
            focus = r["resolved_at"] if not _missing(r["resolved_at"]) else r["break_observed_at"]
            bcase(f"FAIL-{reason}", f"Ordinary failure without successor: {reason}", "failure", r["block_id"],
                  focus, "Ordinary actionability ends at the failure close; no BB / MB stage.")
    pairs = concurrent_pairs(run)
    if len(pairs):
        r = pairs.iloc[0]
        bcase("CONCURRENT", "Independent opposing ordinary OB admitted at an older block's successor instant",
              "independence", r["block_id_ord"], r["available_at"],
              "Two different blocks: the new ordinary OB has no predecessor; the older block's successor is parent-linked "
              "to that block's ordinary stage. Same timeframe, contract, direction and instant; separate geometry.",
              partner=r["block_id_succ"])
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
        bcase("GAP-BEYOND", "Gap-beyond evidence (no invented fill inside the zone)", "interaction", x["block_id"], x["at"],
              "The 1m range lies wholly beyond the far boundary after an approach-side bar.")
    m_ = it[it["kind"] == "FIRST_MIDPOINT"]
    if len(m_):
        x = m_.iloc[len(m_) // 2]
        bcase("MIDPOINT", "Zone midpoint observed (exact, half-tick)", "interaction", x["block_id"], x["at"],
              "Zone midpoint of the open-to-wick interval — not the source-body midpoint.")
    t_ = E.lifecycle[E.lifecycle["to_state"] == "TERMINATED_DATA_GAP"]
    if len(t_):
        x = t_.iloc[len(t_) // 2]
        bcase("DATA-GAP", "Termination at a 1m data-gap onset", "data", x["block_id"], x["at"],
              "Every live stage ends at the onset (a reset instant, not a bar close); nothing is inferred inside the gap.")
    return cases


SYNTHETIC_TITLES = {
    "ORDINARY": "SYN ordinary bullish OB (§15.1)", "ORDINARY_M": "SYN ordinary bearish OB (§15.1 mirrored)",
    "BREAKER": "SYN Breaker, bullish parent", "BREAKER_M": "SYN Breaker, bearish parent (mirrored)",
    "MITIGATION": "SYN Mitigation, bullish parent", "MITIGATION_M": "SYN Mitigation, bearish parent (mirrored)",
    "EQUAL": "SYN equal extreme (unclassified)", "RAID_LOWER_C": "SYN outside reversal bar: raid at x, less extreme C",
    "N2_DELAYED": "SYN N = 2 delayed successor availability", "N2_INVALID": "SYN N = 2 qualified but invalid before admission",
    "CONCURRENT": "SYN concurrent independent ordinary OB and Breaker", "BODY3": "SYN 3-tick last candle rejected (no fallback)",
    "ROLL": "SYN pure roll → PENDING_ADJUSTMENT",
}
SYNTHETIC_WANT = {"ORDINARY": "timeframe", "ORDINARY_M": "timeframe", "BREAKER": "successor", "BREAKER_M": "successor",
                  "MITIGATION": "successor", "MITIGATION_M": "successor", "EQUAL": "failure", "RAID_LOWER_C": "failure",
                  "N2_DELAYED": "successor", "N2_INVALID": "failure", "CONCURRENT": "independence",
                  "BODY3": "rejection", "ROLL": None}


def synthetic_cases(build) -> tuple[list, dict]:
    """``build(name) -> run`` for the isolated synthetic fixtures."""
    cases, facts = [], {}
    for name, title in SYNTHETIC_TITLES.items():
        run = build(name)
        f = Facts(run)
        facts["SYN-" + name] = f
        sub = build_cases(run, run_key="SYN-" + name, source="SYNTHETIC (isolated fixture)", prefix=f"SYN-{name}-")
        want = SYNTHETIC_WANT[name]
        keep = [c for c in sub if c.category == want and "NO_PRIOR_EXTREME" not in c.case_id
                and (name != "BODY3" or c.case_id.endswith("REJ-BODY"))]
        if name == "ROLL" and len(run.engine.pending):
            p = run.engine.pending.iloc[0]
            c = Case(f"SYN-{name}", title, "data", "SYNTHETIC (isolated fixture)", "SYN-" + name, p["block_id"],
                     p["since_at"], "Old-contract stages become PENDING_ADJUSTMENT at the first new-contract minute; "
                     "no raw cross-contract price test.", refs={"fixture": name})
            c.tables = block_tables(f, c)
            keep = [c]
        for c in keep:
            c.title = f"{title} — {c.title}"
        cases += keep
    return cases, facts
