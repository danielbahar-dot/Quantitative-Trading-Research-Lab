"""Market Structure MS-I3 visual-validation package (local HTML with prices) + price-free manifest.

Used by ``market_structure_dev_validation``.  Every case is verifiable from the
page alone:

- the relevant swings are drawn with their **source span** (``source_at`` →
  ``source_end_at``) and an **available_at** marker;
- roles are drawn from ``assigned_at`` to their exit;
- each case carries a compact **pre-state → evidence → post-state** table with
  exact tick-aligned prices;
- failed establishments state the one failing condition, recomputed here from
  the run's own swings and breaks (deepest eligible pullback missing, not
  strictly beyond the anchor, or stale after the last CHoCH).

Visual / audit only; it never feeds the engine.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import html

import pandas as pd

from src.data.timeframes import expected_timeframe_schedule
from src.market_structure.structure import (
    BEAR_ANCHOR,
    BEAR_CANDIDATE_TARGET,
    BOS,
    BULL_ANCHOR,
    BULL_CANDIDATE_TARGET,
    CHOCH,
    ESTABLISHMENT,
    PROTECTION,
    RESET,
    TARGET,
    build_market_structure,
)

NY = "America/New_York"
ROLE_SHORT = {BULL_ANCHOR: "bull anchor", BEAR_ANCHOR: "bear anchor", BULL_CANDIDATE_TARGET: "bull cand. target",
              BEAR_CANDIDATE_TARGET: "bear cand. target", PROTECTION: "protection", TARGET: "target"}
_KIND_CSS = {BULL_ANCHOR: "ba", BEAR_ANCHOR: "ra", BULL_CANDIDATE_TARGET: "bt", BEAR_CANDIDATE_TARGET: "rt",
             PROTECTION: "pr", TARGET: "tg"}
MAX_BARS = 64


# ---------------------------------------------------------------------------
# Facts over one run (all times UTC internally, shown in New York time)
# ---------------------------------------------------------------------------


def _utc(value):
    return pd.Timestamp(value).tz_convert("UTC")


def fmt_time(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{pd.Timestamp(value).tz_convert(NY):%Y-%m-%d %H:%M}"


class Facts:
    """Read-only lookups over one MarketStructureRun."""

    def __init__(self, run):
        self.run = run
        self.tick = Decimal(run.manifest["tick_size"])
        sw = run.swings.copy()
        for column in ("source_at", "source_end_at", "available_at"):
            sw[column] = pd.to_datetime(sw[column], utc=True)
        self.swings = sw.set_index("swing_id")
        self.breaks = {r.swing_id: _utc(r.bar_end) for r in run.swing_breaks.itertuples(index=False)}
        obs = run.observations.copy()
        obs["_end"] = pd.to_datetime(obs["bar_end"], utc=True)
        obs["_start"] = pd.to_datetime(obs["bar_start"], utc=True)
        self.obs = obs.sort_values("_end").reset_index(drop=True)
        self.bar = {e: i for i, e in enumerate(self.obs["_end"])}
        roles = run.roles.copy()
        roles["assigned_at"] = pd.to_datetime(roles["assigned_at"], utc=True)
        self.roles = roles
        self.exits = {r.entity_id: (r.new_state, _utc(r.transition_at)) for r in run.role_transitions.itertuples(index=False)}
        eps = run.episodes.copy()
        eps["first_bar_end"] = pd.to_datetime(eps["first_bar_end"], utc=True)
        self.episodes = eps.sort_values("first_bar_end").reset_index(drop=True)
        ev = run.events.copy()
        ev["event_at"] = pd.to_datetime(ev["event_at"], utc=True)
        self.events = ev

    # prices ----------------------------------------------------------------------------------
    def price(self, value) -> str:
        """Exact tick-aligned price text from a float price."""
        ticks = (Decimal(repr(float(value))) / self.tick).to_integral_value()
        return f"{ticks * self.tick:.2f}"

    def price_ticks(self, ticks) -> str:
        return f"{Decimal(int(ticks)) * self.tick:.2f}"

    # observations ----------------------------------------------------------------------------
    def bar_row(self, at):
        return self.obs.iloc[self.bar[_utc(at)]]

    def ohlc(self, at) -> str:
        r = self.bar_row(at)
        return (f"O {self.price(r['open'])} · H {self.price(r['high'])} · L {self.price(r['low'])} · "
                f"C {self.price(r['close'])}")

    def window(self, start, end, before=3, after=4):
        lo = max(0, self.obs["_end"].searchsorted(_utc(start)) - before)
        hi = min(len(self.obs) - 1, self.obs["_end"].searchsorted(_utc(end)) + after)
        if hi - lo + 1 > MAX_BARS:
            lo = hi - MAX_BARS + 1
        return self.obs["_end"].iloc[lo], self.obs["_end"].iloc[hi]

    # swings ----------------------------------------------------------------------------------
    def swing(self, swing_id):
        return self.swings.loc[swing_id]

    def swing_text(self, swing_id) -> str:
        s = self.swing(swing_id)
        span = fmt_time(s["source_at"]) if s["source_at"] == s["source_end_at"] else \
            f"{fmt_time(s['source_at'])} → {fmt_time(s['source_end_at'])}"
        return (f"{s['orientation']} {self.price(s['price'])} · source {span} · available {fmt_time(s['available_at'])}"
                f" · {swing_id[:11]}…")

    # state -----------------------------------------------------------------------------------
    def episode_at(self, at):
        eps = self.episodes[self.episodes["first_bar_end"] <= _utc(at)]
        return eps.iloc[-1]

    def pre_state(self, at) -> pd.DataFrame:
        """Roles of S_N for the observation ending at ``at``: assigned before e(N), not exited before e(N)."""
        at = _utc(at)
        r = self.roles
        keep = (r["assigned_at"] < at) & r["role_id"].map(lambda i: i not in self.exits or self.exits[i][1] >= at)
        return r[keep]

    def created_at(self, at) -> pd.DataFrame:
        return self.roles[self.roles["assigned_at"] == _utc(at)]

    def exited_at(self, at) -> list:
        at = _utc(at)
        return [(rid, state) for rid, (state, when) in self.exits.items() if when == at]

    def role(self, role_id):
        return self.roles.set_index("role_id").loc[role_id]

    def eligible(self, at, orientation, episode) -> pd.DataFrame:
        """Swings eligible at s(N) (available_at <= bar_start(N), unbreached before N) in ``episode``."""
        start = self.bar_row(at)["_start"]
        sw = self.swings
        mask = ((sw["orientation"] == orientation) & (sw["available_at"] <= start) & (sw["contract"] == episode["contract"])
                & (sw["source_at"] >= episode["first_bar_end"]))
        out = sw[mask]
        unbroken = [sid for sid in out.index if sid not in self.breaks or self.breaks[sid] >= _utc(at)]
        return out.loc[unbroken]

    def pullback(self, at, reference_id, bull: bool, episode):
        """Deepest eligible pullback strictly after ``reference_id`` (earliest source span on ties)."""
        ref = self.swing(reference_id)
        pool = self.eligible(at, "LOWER" if bull else "UPPER", episode)
        pool = pool[pool["source_at"] > ref["source_end_at"]]
        if pool.empty:
            return None
        pool = pool.assign(_key=pool["price"] * (1 if bull else -1))
        return pool.sort_values(["_key", "source_at", "source_end_at"], kind="mergesort").index[0]

    def last_choch(self, at, episode):
        ev = self.events[(self.events["kind"] == CHOCH) & (self.events["episode_id"] == episode["episode_id"])
                         & (self.events["event_at"] < _utc(at))]
        return None if ev.empty else ev["event_at"].max()

    def failing_condition(self, target_role_id, at):
        """The single condition that failed for a candidate target closed beyond at ``at`` (K-4 / K-8 / D15 / D6)."""
        target = self.role(target_role_id)
        bull = target["role_kind"] == BULL_CANDIDATE_TARGET
        anchor = self.role(target["parent_role_id"])
        episode = self.episode_at(at)
        pstar = self.pullback(at, target["swing_id"], bull, episode)
        a_price = self.swing(anchor["swing_id"])["price"]
        if pstar is None:
            return "NO_PULLBACK", ("no eligible " + ("LOWER" if bull else "UPPER")
                                   + " swing strictly after the candidate target's span at s(N)"), None, anchor
        p = self.swing(pstar)
        beyond = p["price"] > a_price if bull else p["price"] < a_price
        if not beyond:
            return "NOT_BEYOND_ANCHOR", (f"deepest pullback {self.price(p['price'])} is not strictly "
                                         f"{'above' if bull else 'below'} the anchor {self.price(a_price)} (D15)"), \
                pstar, anchor
        choch = self.last_choch(at, episode)
        if choch is not None and p["source_at"] <= choch:
            return "STALE", (f"deepest pullback {self.price(p['price'])} has source_at {fmt_time(p['source_at'])} "
                             f"≤ e(X) {fmt_time(choch)} of the last CHoCH: stale (D6 / K-4)"), pstar, anchor
        raise RuntimeError(f"candidate target {target_role_id} RETIRED at {at} but every condition holds")


# ---------------------------------------------------------------------------
# SVG chart
# ---------------------------------------------------------------------------


class _Labels:
    """Greedy vertical de-overlap of text labels, kept inside [top, bottom]."""

    def __init__(self, top=10.0, bottom=10_000.0):
        self.boxes, self.top, self.bottom = [], top, bottom

    def place(self, x, y, text, step=11):
        width = 5.6 * len(text)
        candidates = [y] + [y + sign * step * m for m in range(1, 41) for sign in (-1, 1)]   # up first, then down
        for candidate in candidates:
            if not (self.top <= candidate <= self.bottom):
                continue
            if not any(abs(candidate - by) < 10 and x < bx + bw and bx < x + width for bx, by, bw in self.boxes):
                y = candidate
                break
        self.boxes.append((x, y, width))
        return y


def chart(facts: Facts, t0, t1, *, swings=(), roles=None, events=(), resets=(), highlight=None, H=330, W=980,
          pad=50) -> str:
    """Candles in [t0, t1]; swing source spans + available_at; role levels; events; resets; one highlighted bar."""
    obs = facts.obs[(facts.obs["_end"] >= _utc(t0)) & (facts.obs["_end"] <= _utc(t1))].reset_index(drop=True)
    if obs.empty:
        return "<p class='note'>(no observations in window)</p>"
    ends = list(obs["_end"])
    roles = facts.roles.iloc[0:0] if roles is None else roles
    segs = []
    for r in roles.itertuples(index=False):
        state, exit_at = facts.exits.get(r.role_id, ("ACTIVE", None))
        end = exit_at if exit_at is not None else ends[-1]
        if end < ends[0] or r.assigned_at > ends[-1]:
            continue
        segs.append((max(r.assigned_at, ends[0]), min(end, ends[-1]), facts.swing(r.swing_id)["price"], r.role_kind,
                     state, r.assigned_at < ends[0]))
    sw_rows = [(label, facts.swing(sid)) for label, sid in swings]
    prices = list(obs["high"]) + list(obs["low"]) + [s[2] for s in segs] + [s["price"] for _, s in sw_rows]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.08, hi + span * 0.16
    n = len(obs)
    cw = (W - 2 * pad) / n
    y = lambda v: pad + (hi - v) / (hi - lo) * (H - 2 * pad)  # noqa: E731

    def x(ts, edge="mid"):
        ts = _utc(ts)
        for i, e in enumerate(ends):
            if e >= ts:
                if e == ts:
                    return pad + i * cw + (cw / 2 if edge == "mid" else (cw if edge == "end" else 0))
                return pad + i * cw
        return W - pad

    labels = _Labels(top=10, bottom=H - 24)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    if highlight is not None:
        hx = x(highlight[0], "start")
        out.append(f'<rect x="{hx:.1f}" y="{pad - 6}" width="{cw:.1f}" height="{H - 2 * pad + 6}" class="hl"/>')
        ly = labels.place(hx + cw + 2, H - pad - 6, highlight[1])
        out.append(f'<text x="{hx + cw + 2:.1f}" y="{ly:.1f}" class="hll">{html.escape(highlight[1])}</text>')
    previous_day = None
    step = max(1, n // 7)
    last_tick_end = -1e9
    for i, row in obs.iterrows():
        xc = pad + i * cw + cw / 2
        css = "up" if row["close"] >= row["open"] else "dn"
        out.append(f'<line x1="{xc:.1f}" x2="{xc:.1f}" y1="{y(row["high"]):.1f}" y2="{y(row["low"]):.1f}" class="wk"/>')
        top, bot = y(max(row["open"], row["close"])), y(min(row["open"], row["close"]))
        tip = f"{fmt_time(row['_end'])} {facts.ohlc(row['_end'])}"
        out.append(f'<rect x="{xc - cw * 0.36:.1f}" y="{top:.1f}" width="{max(cw * 0.72, 0.8):.1f}" '
                   f'height="{max(bot - top, 1.0):.1f}" class="{css}"><title>{html.escape(tip)}</title></rect>')
        if i % step == 0 or i == n - 1:
            local = row["_end"].tz_convert(NY)
            text = f"{local:%m-%d %H:%M}" if local.date() != previous_day else f"{local:%H:%M}"
            width = 5.6 * len(text)
            if xc - width / 2 > last_tick_end + 6:   # never overlap the previous time label
                previous_day = local.date()
                last_tick_end = xc + width / 2
                out.append(f'<text x="{xc:.1f}" y="{H - 14}" class="tk" text-anchor="middle">{text}</text>')
    for a, e, price, kind, state, clipped in segs:
        css = _KIND_CSS[kind]
        out.append(f'<line x1="{x(a):.1f}" x2="{x(e):.1f}" y1="{y(price):.1f}" y2="{y(price):.1f}" class="role {css}"/>')
        text = f"{'◀ ' if clipped else ''}{ROLE_SHORT[kind]} {facts.price(price)} → {state}"
        ly = labels.place(x(a) + 2, y(price) - 3, text)
        out.append(f'<text x="{x(a) + 2:.1f}" y="{ly:.1f}" class="rl {css}">{html.escape(text)}</text>')
    for label, s in sw_rows:
        x0, x1 = x(s["source_at"], "start"), x(s["source_end_at"], "end")
        yy = y(s["price"])
        out.append(f'<rect x="{x0:.1f}" y="{yy - 3:.1f}" width="{max(x1 - x0, 3):.1f}" height="6" class="span"/>')
        ly = labels.place(x1 + 3, yy + 12, f"{label} {facts.price(s['price'])}")
        out.append(f'<text x="{x1 + 3:.1f}" y="{ly:.1f}" class="sl">{html.escape(label)} {facts.price(s["price"])}</text>')
        if ends[0] <= s["available_at"] <= ends[-1]:
            ax = x(s["available_at"], "end")
            out.append(f'<line x1="{ax:.1f}" x2="{ax:.1f}" y1="{H - pad}" y2="{H - pad + 8}" class="av"/>'
                       f'<polygon points="{ax - 4:.1f},{H - pad + 8} {ax + 4:.1f},{H - pad + 8} {ax:.1f},{H - pad + 2}" '
                       f'class="avm"/>')
            ly = labels.place(ax - 10, H - pad + 20, f"{label} avail")
            out.append(f'<text x="{ax - 10:.1f}" y="{ly:.1f}" class="avl">{html.escape(label)} avail</text>')
    for ts, label in events:
        ex = x(ts, "end")
        out.append(f'<line x1="{ex:.1f}" x2="{ex:.1f}" y1="{pad - 18}" y2="{H - pad}" class="ev"/>')
        ly = labels.place(ex + 3, pad - 20, label)
        out.append(f'<text x="{ex + 3:.1f}" y="{ly:.1f}" class="evl">{html.escape(label)}</text>')
    for ts, label in resets:
        rx = x(ts, "end")
        out.append(f'<line x1="{rx:.1f}" x2="{rx:.1f}" y1="{pad - 18}" y2="{H - pad}" class="rs"/>')
        ly = labels.place(rx + 3, pad - 8, label)
        out.append(f'<text x="{rx + 3:.1f}" y="{ly:.1f}" class="rsl">{html.escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def table(rows) -> str:
    body = "".join(f"<tr><td class='st'>{html.escape(stage)}</td><td>{html.escape(item)}</td>"
                   f"<td>{html.escape(detail)}</td></tr>" for stage, item, detail in rows)
    return f"<table><tr><th>stage</th><th>item</th><th>detail</th></tr>{body}</table>"


# ---------------------------------------------------------------------------
# Case builders
# ---------------------------------------------------------------------------


def _role_rows(facts, frame, stage):
    return [(stage, ROLE_SHORT[r.role_kind], f"{facts.swing_text(r.swing_id)} · assigned {fmt_time(r.assigned_at)}")
            for r in frame.itertuples(index=False)]


def _post_rows(facts, at):
    rows = []
    for rid, state in sorted(facts.exited_at(at), key=lambda item: facts.role(item[0])["role_kind"]):
        r = facts.role(rid)
        rows.append(("post-state e(N)", f"{ROLE_SHORT[r['role_kind']]} exits {state}", facts.swing_text(r["swing_id"])))
    for r in facts.created_at(at).itertuples(index=False):
        rows.append(("post-state e(N)", f"new {ROLE_SHORT[r.role_kind]}", facts.swing_text(r.swing_id)))
    if not rows:
        rows.append(("post-state e(N)", "roles", "no role created or exited"))
    return rows


def _labels(frame):
    return [(f"S{i + 1}", sid) for i, sid in enumerate(dict.fromkeys(frame))]


def build_cases(runs: dict, spec, definition) -> tuple[str, list]:
    """Return (HTML sections, price-free manifest rows)."""
    sections, manifest = [], []
    facts = {tf: Facts(run) for tf, run in runs.items()}

    def record(case_id, source, tf, area, case, note, chart_html, rows, refs=(), synthetic_reason=""):
        tag = '<span class="real">REAL DEVELOPMENT</span>' if source == "REAL" else '<span class="syn">SYNTHETIC</span>'
        sections.append(f"<section><h3>{html.escape(case_id)} · {html.escape(tf)} · {html.escape(area)} — "
                        f"{html.escape(case)} {tag}</h3><p class='note'>{html.escape(note)}</p>{chart_html}"
                        f"{table(rows)}</section>")
        manifest.append({"case_id": case_id, "source": source, "timeframe": tf, "area": area, "case": case,
                         "refs": " ".join(refs), "synthetic_reason": synthetic_reason})

    def event_rows(f, e):
        at = e["event_at"]
        brk = f.run.swing_breaks[f.run.swing_breaks["break_id"] == e["break_id"]].iloc[0]
        return [("evidence at N", "observation N", f"{fmt_time(f.bar_row(at)['_start'])} → {fmt_time(at)} · {f.ohlc(at)}"),
                ("evidence at N", "break", f"close {f.price_ticks(brk['close_ticks'])} vs level "
                                           f"{f.price_ticks(brk['level_ticks'])}: {int(brk['close_excess_ticks'])} "
                                           f"ticks beyond · {e['break_id'][:11]}…")]

    def chart_for(f, at, swing_ids, *, events=(), highlight=None, extra_roles=None):
        pre, created = f.pre_state(at), f.created_at(at)
        roles = pd.concat([pre, created] + ([extra_roles] if extra_roles is not None else []))
        roles = roles.drop_duplicates("role_id")
        starts = [f.swing(s)["source_at"] for s in swing_ids] or [at]
        t0, t1 = f.window(min(starts), at)
        return chart(f, t0, t1, swings=_labels(swing_ids), roles=roles, events=events, highlight=highlight)

    # ---- classification events --------------------------------------------------------------
    def event_case(case_id, tf, kind, direction=None, pick=0, predicate=None, area="Classification"):
        f = facts[tf]
        ev = f.events[f.events["kind"] == kind]
        if direction:
            ev = ev[ev["direction"] == direction]
        if predicate is not None:
            ev = ev[[predicate(f, e) for _, e in ev.iterrows()]]
        if ev.empty:
            raise RuntimeError(f"REAL case not reproducible: {case_id} {tf} {kind} {direction}")
        e = ev.sort_values("event_at").iloc[min(pick, len(ev) - 1)]
        at = e["event_at"]
        episode = f.episode_at(at)
        pre = f.pre_state(at)
        rows = _role_rows(f, pre, "pre-state S_N") + event_rows(f, e)
        focus = list(pre["swing_id"])
        bull = e["direction"] == "BULLISH"
        if kind == ESTABLISHMENT:
            target_kind = BULL_CANDIDATE_TARGET if bull else BEAR_CANDIDATE_TARGET
            target = pre[(pre["swing_id"] == e["swing_id"]) & (pre["role_kind"] == target_kind)].iloc[0]
            anchor = f.role(target["parent_role_id"])
            pstar = f.pullback(at, e["swing_id"], bull, episode)
            p = f.swing(pstar)
            choch = f.last_choch(at, episode)
            rows.append(("evidence at N", "deepest pullback P*", f.swing_text(pstar)))
            rows.append(("evidence at N", "qualification",
                         f"P* {f.price(p['price'])} strictly {'above' if bull else 'below'} anchor "
                         f"{f.price(f.swing(anchor['swing_id'])['price'])}; "
                         + ("no CHoCH in episode (no freshness test)" if choch is None else
                            f"fresh: source_at {fmt_time(p['source_at'])} > e(X) {fmt_time(choch)}")))
            focus.append(pstar)
        elif kind == BOS:
            prot = pre[pre["role_kind"] == PROTECTION].iloc[0]
            pstar = f.pullback(at, e["swing_id"], bull, episode)
            pp = f.swing(prot["swing_id"])["price"]
            if pstar is None:
                rows.append(("evidence at N", "deepest pullback P*", "none after the consumed target: protection kept"))
            else:
                p = f.swing(pstar)["price"]
                tighter = p > pp if bull else p < pp
                rows.append(("evidence at N", "deepest pullback P*", f.swing_text(pstar)))
                rows.append(("evidence at N", "protection test",
                             f"P* {f.price(p)} {'is' if tighter else 'is not'} strictly tighter than protection "
                             f"{f.price(pp)} → {'REPLACED' if tighter else 'kept (same role_id, no transition)'}"))
                focus.append(pstar)
        elif kind == CHOCH:
            rows.append(("evidence at N", "K-3 scope", f"after this CHoCH, reuse only swings with source_at ≥ "
                                                        f"{fmt_time(f.swing(e['swing_id'])['source_at'])} "
                                                        "(broken protection source_at)"))
            rows.append(("evidence at N", "freshness", f"later establishments need P* source_at > {fmt_time(at)}"))
        rows += _post_rows(f, at)
        focus += list(f.created_at(at)["swing_id"])
        record(case_id, "REAL", tf, area, f"{kind} {e['direction']}",
               f"{kind} {e['direction']} ({e['pre_direction']} → {e['post_direction']}) at {fmt_time(at)}.",
               chart_for(f, at, focus, events=[(at, f"N: {kind} {e['direction']}")]), rows,
               refs=(e["event_id"], e["break_id"]))

    event_case("R01", "4H", ESTABLISHMENT, "BULLISH", area="Establishment")
    event_case("R02", "4H", ESTABLISHMENT, "BEARISH", area="Establishment")

    def bos_kept(f, e):
        return not (f.created_at(e["event_at"])["role_kind"] == PROTECTION).any()

    event_case("R03", "1H", BOS, predicate=bos_kept, area="BOS without replacement")
    event_case("R04", "1H", BOS, predicate=lambda f, e: not bos_kept(f, e), area="BOS with replacement")
    event_case("R05", "1H", CHOCH, area="CHoCH")
    event_case("R06", "4H", CHOCH, pick=1, area="CHoCH")

    # ---- non-event role exits -----------------------------------------------------------------
    def exits_of(f, kind, state):
        ids = set(f.roles.loc[f.roles["role_kind"] == kind, "role_id"])
        return sorted(((when, rid) for rid, (s, when) in f.exits.items() if s == state and rid in ids))

    def failed_case(case_id, tf, kind, area, predicate=None, extra="", prefer=()):
        f = facts[tf]
        retired = exits_of(f, kind, "RETIRED")
        codes = {rid: f.failing_condition(rid, when)[0] for when, rid in retired}
        counts = ", ".join(f"{code} {sum(1 for c in codes.values() if c == code)}" for code in sorted(set(codes.values())))
        hits = [(when, rid) for when, rid in retired if predicate is None or predicate(f, rid, when)]
        for code in prefer:
            preferred = [(when, rid) for when, rid in hits if codes[rid] == code]
            if preferred:
                hits = preferred
                break
        if not hits:
            raise RuntimeError(f"REAL case not reproducible: {case_id} {tf} {kind}")
        at, rid = hits[0]
        target = f.role(rid)
        code, reason, pstar, anchor = f.failing_condition(rid, at)
        pre = f.pre_state(at)
        brk_id = f.run.swing_breaks.loc[f.run.swing_breaks["swing_id"] == target["swing_id"], "break_id"].iloc[0]
        brk = f.run.swing_breaks[f.run.swing_breaks["break_id"] == brk_id].iloc[0]
        rows = _role_rows(f, pre, "pre-state S_N") + [
            ("evidence at N", "observation N", f"{fmt_time(f.bar_row(at)['_start'])} → {fmt_time(at)} · {f.ohlc(at)}"),
            ("evidence at N", "candidate target closed beyond",
             f"close {f.price_ticks(brk['close_ticks'])} vs level {f.price_ticks(brk['level_ticks'])}: "
             f"{int(brk['close_excess_ticks'])} ticks beyond"),
            ("evidence at N", "deepest pullback P*", "none" if pstar is None else f.swing_text(pstar)),
            ("evidence at N", f"failing condition: {code}", reason),
        ] + _post_rows(f, at)
        focus = list(pre["swing_id"]) + ([pstar] if pstar else []) + list(f.created_at(at)["swing_id"])
        record(case_id, "REAL", tf, area, f"{ROLE_SHORT[kind]} → RETIRED ({code})",
               f"Failed establishment at {fmt_time(at)}: {reason}. Target RETIRED, anchor persists, no event, no "
               f"retrospective establishment (K-8). {extra} All {ROLE_SHORT[kind]} retirements on {tf} by failing "
               f"condition: {counts}.",
               chart_for(f, at, focus, events=[(at, f"N: target closed beyond — {code}")]), rows, refs=(rid,))

    failed_case("R07", "1H", BULL_CANDIDATE_TARGET, "Failed establishment", prefer=("NOT_BEYOND_ANCHOR", "STALE"))
    failed_case("R08", "1H", BEAR_CANDIDATE_TARGET, "Failed establishment", prefer=("STALE", "NOT_BEYOND_ANCHOR"))

    def same_close(f, rid, at):
        """T-1: the failed side gets a new candidate target (same kind, same persisting anchor) confirmed at e(N)."""
        retired = f.role(rid)
        new = f.created_at(at)
        new = new[(new["role_kind"] == retired["role_kind"]) & (new["parent_role_id"] == retired["parent_role_id"])]
        return any(f.swing(s)["available_at"] == at for s in new["swing_id"])

    def exit_case(case_id, tf, kind, state, area, note):
        f = facts[tf]
        hits = exits_of(f, kind, state)
        if not hits:
            raise RuntimeError(f"REAL case not reproducible: {case_id}")
        at, rid = hits[0]
        role = f.role(rid)
        pre = f.pre_state(at)
        rows = _role_rows(f, pre, "pre-state S_N") + [
            ("evidence at N", "observation N", f"{fmt_time(f.bar_row(at)['_start'])} → {fmt_time(at)} · {f.ohlc(at)}")]
        if state == "BROKEN":
            level = f.swing(role["swing_id"])["price"]
            close = f.bar_row(at)["close"]
            rows.append(("evidence at N", "invalidation", f"close {f.price(close)} strictly beyond anchor {f.price(level)}"))
        if state == "SUPERSEDED":
            new = f.created_at(at)
            new = new[new["role_kind"] == kind].iloc[0]
            rows.append(("evidence at N", "admitted at e(N)", f.swing_text(new["swing_id"])))
            rows.append(("evidence at N", "comparison", f"{f.price(f.swing(new['swing_id'])['price'])} is strictly more "
                                                        f"extreme than {f.price(f.swing(role['swing_id'])['price'])}"))
        rows += _post_rows(f, at)
        focus = list(pre["swing_id"]) + list(f.created_at(at)["swing_id"])
        record(case_id, "REAL", tf, area, f"{ROLE_SHORT[kind]} → {state}", f"{note} At {fmt_time(at)}.",
               chart_for(f, at, focus, events=[(at, f"N: {state}")]), rows, refs=(rid,))

    exit_case("R09", "1H", BULL_ANCHOR, "BROKEN", "Invalidation",
              "Close below the bull anchor while UNDEFINED: anchor BROKEN, no event; reseeding only from eligible swings "
              "(K-2).")
    exit_case("R10", "1H", TARGET, "SUPERSEDED", "Target progression",
              "A strictly more extreme since-expansion target is admitted: the old TARGET is SUPERSEDED (K-7, D4).")

    for tf in ("15m", "5m", "1m"):
        try:
            failed_case("R11", tf, BULL_CANDIDATE_TARGET, "T-1 same-close target", predicate=same_close,
                        extra="A new candidate target confirmed at e(N) is assigned at e(N); it is not part of S_N and is "
                              "first usable by the next observation (bar_start ≥ e(N)).")
            break
        except RuntimeError:
            if tf == "1m":
                raise

    # ---- R12 outside bar replacing both existing anchors -----------------------------------------
    for tf in ("1H", "15m", "5m", "1m"):
        f = facts[tf]
        anchors = f.roles[f.roles["role_kind"].isin([BULL_ANCHOR, BEAR_ANCHOR])]
        found = None
        for at, group in anchors.groupby("assigned_at"):
            if len(group) != 2 or group["swing_id"].map(lambda s: f.swing(s)["source_end_at"]).nunique() != 1:
                continue
            if not all(f.swing(s)["available_at"] == at for s in group["swing_id"]):
                continue
            replaced = [rid for rid, state in f.exited_at(at) if f.role(rid)["role_kind"] in (BULL_ANCHOR, BEAR_ANCHOR)
                        and state == "SUPERSEDED"]
            if len(replaced) == 2:
                found = at
                break
        if found is None:
            continue
        pre = f.pre_state(found)
        rows = _role_rows(f, pre, "pre-state S_N") + [
            ("evidence at N", "observation N", f"{fmt_time(f.bar_row(found)['_start'])} → {fmt_time(found)} · "
                                               f"{f.ohlc(found)}")]
        for r in f.created_at(found).itertuples(index=False):
            rows.append(("evidence at N", "admitted at e(N)", f.swing_text(r.swing_id)))
        rows += _post_rows(f, found)
        focus = list(pre["swing_id"]) + list(f.created_at(found)["swing_id"])
        record("R12", "REAL", tf, "Simultaneous admission", "one observation confirms a high and a low; both anchors "
               "replaced in one batch",
               f"Both new swings share their last plateau observation (L0) and are admitted at the same e(N) = "
               f"{fmt_time(found)}; the rescan supersedes both existing anchors in one batch; no entity is created and "
               "exited at one instant.",
               chart_for(f, found, focus, events=[(found, "admission batch e(N)")]), rows,
               refs=tuple(f.created_at(found)["role_id"]))
        break
    else:
        raise RuntimeError("REAL case not reproducible: R12 outside bar replacing both anchors")

    # ---- lifecycle -------------------------------------------------------------------------------
    for case_id, tf, changed, label in (("R13", "1H", False, "gap reset, same contract (DATA_GAP)"),
                                        ("R14", "4H", True, "roll during missing roll-week sessions (CB-1)")):
        f = facts[tf]
        ep = f.episodes
        k = ep.index[(ep["opening_contract_changed"].astype(bool) == changed) & (ep.index > 0)][0]
        new, old = ep.iloc[k], ep.iloc[k - 1]
        reset = f.events[(f.events["kind"] == RESET) & (f.events["episode_id"] == old["episode_id"])].iloc[0]
        t_r, first = reset["event_at"], new["first_bar_end"]
        last = f.obs[f.obs["_end"] < t_r]["_end"].iloc[-1]
        rows = _role_rows(f, f.pre_state(t_r), "active before reset") + [
            ("evidence", "last valid observation", f"{fmt_time(last)} on {old['contract']}"),
            ("evidence", "RESET onset t_r", f"{fmt_time(t_r)} = expected completion of the first missing observation; "
                                            f"reason {reset['reset_reason']}; no contract flag"),
            ("evidence", "reset_ref", reset["reset_ref"]),
            ("post-state", "new episode", f"{new['opening_cause']} at {fmt_time(first)} on {new['contract']} "
                                          f"(previous {new['previous_contract']}, contract_changed "
                                          f"{bool(new['opening_contract_changed'])})"),
            ("post-state", "opening_ref", str(new["opening_ref"])),
            ("post-state", "opening_contract_change_ref", str(new["opening_contract_change_ref"])),
        ]
        t0, _ = f.window(last, last, before=14, after=0)
        _, t1 = f.window(first, first, before=0, after=6)
        record(case_id, "REAL", tf, "Lifecycle", label,
               "All roles end at the reset; nothing crosses the boundary; the new episode starts UNDEFINED.",
               chart(f, t0, t1, roles=f.pre_state(t_r), resets=[(t_r, f"RESET {reset['reset_reason']} t_r")],
                     events=[(first, f"open {new['opening_cause']}")]),
               rows, refs=(reset["event_id"], new["episode_id"]))

    # ---- HTF -> LTF -------------------------------------------------------------------------------
    f4, f5 = facts["4H"], facts["5m"]
    e = f4.events[f4.events["kind"].isin([BOS, ESTABLISHMENT])].sort_values("event_at").iloc[3]
    at = e["event_at"]
    first5 = f5.obs[f5.obs["_start"] >= at].iloc[0]
    rows = event_rows(f4, e) + [
        ("cross-timeframe", "4H event available_at", fmt_time(at)),
        ("cross-timeframe", "first eligible 5m bar", f"{fmt_time(first5['_start'])} → {fmt_time(first5['_end'])} "
                                                     "(bar_start ≥ 4H available_at)"),
        ("cross-timeframe", "earlier 5m bars", "cannot reference the 4H event_id (their bar_start < available_at)")]
    t0, t1 = f4.window(at, at, before=10, after=3)
    record("R15", "REAL", "4H→5m", "Cross-timeframe", "HTF event first readable by LTF bar_start",
           f"4H {e['kind']} {e['direction']}; 5m structure is computed independently and only references the 4H "
           "event_id.",
           chart(f4, t0, t1, events=[(at, f"4H {e['kind']} available")]) + "<div class='pl'>5m around the 4H "
           "availability (highlighted: first eligible 5m bar)</div>" +
           chart(f5, at - pd.Timedelta(minutes=50), at + pd.Timedelta(minutes=40),
                 events=[(at, "4H event available_at")],
                 highlight=(first5["_end"], "first eligible 5m bar (bar_start = 4H available_at)")),
           rows, refs=(e["event_id"],))

    # ---- synthetic normative examples ---------------------------------------------------------------
    for case_id, title, rows_, kwargs in synthetic_cases():
        bars = synthetic_bars(rows_, spec, **kwargs)
        cutoff = _utc(_sched(spec)["bar_end"].iloc[len(rows_) - 1])
        run = build_market_structure(bars, "5m", spec, definition, instrument_id="MNQ", replay_cutoff=cutoff)
        f = Facts(run)
        rows = []
        for e in f.events.sort_values("event_at").itertuples(index=False):
            if e.kind == RESET:
                rows.append(("event", f"RESET {e.reset_reason}", f"t_r {fmt_time(e.event_at)} · {e.reset_ref}"))
                continue
            brk = run.swing_breaks[run.swing_breaks["break_id"] == e.break_id].iloc[0]
            rows.append(("event", f"{e.kind} {e.direction} at {fmt_time(e.event_at)}",
                         f"close {f.price_ticks(brk['close_ticks'])} vs level {f.price_ticks(brk['level_ticks'])} "
                         f"({int(brk['close_excess_ticks'])} ticks)"))
        for r in f.roles.sort_values("assigned_at").itertuples(index=False):
            state, when = f.exits.get(r.role_id, ("ACTIVE", None))
            rows.append(("role", f"{ROLE_SHORT[r.role_kind]} {f.price(f.swing(r.swing_id)['price'])}",
                         f"assigned {fmt_time(r.assigned_at)} → {state} {fmt_time(when) if when is not None else ''}"))
        for ep in f.episodes.itertuples(index=False):
            rows.append(("episode", ep.opening_cause, f"first bar {fmt_time(ep.first_bar_end)} · {ep.contract}"))
        resets = [(e.event_at, f"RESET {e.reset_reason}") for e in f.events.itertuples() if e.kind == RESET]
        evs = [(e.event_at, f"{e.kind} {e.direction}") for e in f.events.itertuples() if e.kind != RESET]
        record(case_id, "SYNTHETIC", "5m", "Normative example", title,
               "Production engine on the explicit OHLC of MARKET_STRUCTURE_SPEC §H.0 (prices +20000).",
               chart(f, f.obs["_end"].iloc[0], f.obs["_end"].iloc[-1], swings=_labels(list(f.swings.index)),
                     roles=f.roles, events=evs, resets=resets),
               rows, synthetic_reason="exact normative example (spec §H) or contract boundary absent from DEVELOPMENT")
    return "".join(sections), manifest


STYLE = """
:root{--bg:#fff;--fg:#1d1d1f;--mu:#666;--up:#1a7f5a;--dn:#c0392b;--line:#ddd}
@media (prefers-color-scheme:dark){:root{--bg:#151515;--fg:#eee;--mu:#9a9a9a;--up:#3ec48e;--dn:#ef6b5b;--line:#333}}
body{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;max-width:1040px;margin:0 auto;padding:16px}
h1{font-size:20px} h3{font-size:15px;margin:30px 0 4px} .note{color:var(--mu);margin:2px 0 6px} .pl{font-size:12px;color:var(--mu)}
table{border-collapse:collapse;width:100%;font-size:12px;margin:4px 0 8px} td,th{border-top:1px solid var(--line);padding:3px 6px;text-align:left;vertical-align:top}
td.st{white-space:nowrap;color:var(--mu)}
.wk{stroke:var(--mu)} .up{fill:var(--up)} .dn{fill:var(--dn)} .tk{fill:var(--mu);font-size:10px}
.role{stroke-width:2} .rl{font-size:9.5px} .ba{stroke:#2f5bd3;fill:#2f5bd3} .ra{stroke:#b03aa8;fill:#b03aa8}
.bt{stroke:#4f9bd9;fill:#4f9bd9;stroke-dasharray:5 3} .rt{stroke:#d07ac8;fill:#d07ac8;stroke-dasharray:5 3}
.pr{stroke:#d99a00;fill:#d99a00} .tg{stroke:#1a9b8a;fill:#1a9b8a;stroke-dasharray:2 2}
.span{fill:rgba(120,120,120,.35);stroke:var(--fg);stroke-width:.6} .sl{font-size:10px;fill:var(--fg);font-weight:600}
.av{stroke:var(--fg)} .avm{fill:var(--fg)} .avl{font-size:9px;fill:var(--mu)}
.ev{stroke:var(--fg);stroke-dasharray:3 3} .evl{font-size:10px;fill:var(--fg)} .rs{stroke:#c0392b;stroke-width:2} .rsl{fill:#c0392b;font-size:10px}
.hl{fill:rgba(217,154,0,.18);stroke:#d99a00;stroke-width:1.5} .hll{fill:#b07800;font-size:10px;font-weight:600}
.syn{background:#d99a00;color:#000;border-radius:4px;padding:1px 6px;font-size:11px}
.real{background:#2f5bd3;color:#fff;border-radius:4px;padding:1px 6px;font-size:11px}
"""


def page(sections: str, cutoff) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Structure Validation</title><style>{STYLE}</style></head><body>
<h1>Generic Market Structure — MS-I3 visual validation</h1>
<p class="note">LOCAL ONLY — contains market prices (Git-ignored). Production engine (build_market_structure), DEVELOPMENT,
structure-v1 / swing-break-v1 over the explicit 2/2 Swing reference, replay cutoff {pd.Timestamp(cutoff).isoformat()}.
Grey bars labelled S1, S2, … are swing source spans (source_at → source_end_at) at the swing price; ▲ marks the swing's
available_at. Coloured horizontal lines are role assignments from assigned_at to their exit (◀ = assigned before the window).
Dashed vertical line = observation N's close e(N); red = RESET onset. Tables: pre-state S_N → evidence at N → post-state at
e(N), exact tick-aligned prices, New York time. Machine-validation evidence; human visual approval pending.</p>
{sections}</body></html>"""


def _sched(spec):
    days = [date(2026, 9, 14 + d) for d in range(5)] + [date(2026, 9, 21 + d) for d in range(5)]
    return expected_timeframe_schedule(days, "5m", spec).reset_index(drop=True)


def synthetic_bars(rows, spec, *, contracts=None, incomplete=()):
    sched = _sched(spec)
    frames = []
    for k, row in enumerate(rows):
        if row is None:
            continue
        slot = sched.iloc[k]
        minutes = pd.date_range(slot["bar_start"] + pd.Timedelta(minutes=1), slot["bar_end"], freq="min")
        if k in incomplete:
            minutes = minutes[:-1]
        o, h, lo, c = (20000.0 + v for v in row)
        frame = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1,
                              "contract": contracts[k] if contracts else "MNQ 12-26"}, index=minutes)
        frame.loc[frame.index[0], ["open", "high", "low", "close"]] = [o, h, lo, c]
        frames.append(frame)
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="timestamp_et")
    return out


def synthetic_cases():
    ex_a = [
        (106, 107, 105, 106), (106, 106, 102, 103), (103, 104, 100, 103), (103, 106, 102, 105),
        (105, 108, 104, 107), (107, 110, 106, 108), (108, 109, 105, 106), (106, 107, 104, 105),
        (105, 108, 105, 107), (107, 109, 106, 108), (108, 112, 107, 111),
        (111, 115, 110, 114), (114, 118, 113, 116), (116, 117, 109, 110), (110, 111, 104, 106),
        (106, 109, 105, 108), (108, 112, 107, 111), (111, 116, 110, 115), (115, 120, 114, 119),
        (119, 124, 118, 123), (123, 126, 121, 122), (122, 124, 116, 117), (117, 118, 112, 114),
        (114, 119, 113, 118), (118, 122, 117, 121), (121, 125, 120, 124), (124, 129, 123, 128),
    ]
    ex_b = ex_a[:9] + [(107, 110, 106, 109), (109, 109, 106, 107), (107, 108, 104, 105), (105, 107, 105, 106),
                       (106, 109, 105, 108), (108, 112, 107, 111)]
    ex_c = ex_a[:11] + [
        (111, 118, 110, 117), (117, 125, 116, 124), (124, 130, 123, 127), (127, 128, 120, 121),
        (121, 122, 116, 117), (117, 118, 108, 110), (110, 111, 102, 105), (105, 107, 102, 106),
        (106, 112, 105, 111), (111, 116, 110, 115), (115, 120, 114, 118), (118, 119, 112, 113),
        (113, 114, 107, 108), (108, 113, 108, 112), (112, 116, 111, 115), (115, 115, 110, 111),
        (111, 112, 103, 106), (106, 109, 105, 108), (108, 110, 106, 109), (109, 109.5, 103.5, 103.5),
        (104, 107, 104, 106), (106, 109, 105, 108), (108, 110, 106, 107), (107, 108, 105, 107),
        (107, 112, 106, 111), (111, 116, 110, 115), (115, 116, 114, 116), (116, 123, 115, 122),
        (122, 122, 118, 119), (119, 120, 116, 117),
    ]
    return [
        ("S01", "EX-A / H.1 — establishment, BOS without and with protection replacement", ex_a, {}),
        ("S02", "EX-B / H.8 — equal targets, equal pullbacks", ex_b, {}),
        ("S03", "EX-C / H.5–H.6 — CHoCH reseed, stale deepest, waiting without reselection", ex_c, {}),
        ("S04", "CB-2 — pure contract change (no DEVELOPMENT example: every roll coincides with a gap)", ex_a[:20],
         {"contracts": ["MNQ 09-26"] * 12 + ["MNQ 12-26"] * 8}),
        ("S05", "Trailing incomplete observation — reset without a continuity break row (§G.2a)", ex_a[:16],
         {"incomplete": {15}}),
    ]
