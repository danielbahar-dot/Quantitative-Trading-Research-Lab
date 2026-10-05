"""Generic Market Structure — MS-I3 DEVELOPMENT validation runner (machine validation; read-only).

Command (repository root)::

    .\\.venv\\Scripts\\python.exe -m src.experiments.market_structure_dev_validation

DEVELOPMENT partition only (path from the dataset partition config); explicit
structure definition ``structure-v1`` / ``swing-break-v1`` over the explicit
2/2 Swing reference (``swing-pivot-v1``); all six timeframes; explicit
``replay_cutoff`` = close of the DEVELOPMENT partition's declared last
session (2025-06-30 17:00 ET), never inferred from the data.

Production path: ``build_market_structure``.  Independent checks:
``structure_audit.reference_structure`` / ``reconcile`` and
``structure_invariants`` (INV-1 … INV-17); DEVELOPMENT prefix replays with
cutoffs inside real gaps.  Writes price-free tracked CSVs and a local,
Git-ignored visual HTML (prices) under ``reports/validation/``.  No PnL, no
strategy, no optimization, no backtest, no VALIDATION / OOS data.  It does
not freeze anything; it reports machine gates.
"""

from __future__ import annotations

from datetime import date
import hashlib
import html
from pathlib import Path
import time

import pandas as pd

from src.data.sessions import load_session_spec
from src.data.timeframes import expected_timeframe_schedule
from src.experiments.swing_structure_dev_validation import (
    EXPECTED_CONTINUITY,
    EXPECTED_COUNTS,
    load_development_bars,
)
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
    StructureDefinitionSpec,
    build_market_structure,
)
from src.market_structure.structure_audit import reconcile, reference_structure, structure_invariants
from src.market_structure.swing import SWING_TIMEFRAMES, SwingDefinitionSpec

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT = PROJECT_ROOT / "reports" / "validation"
NY = "America/New_York"
INSTRUMENT = "MNQ"
DEFINITION = StructureDefinitionSpec(
    definition_version="structure-v1", break_definition_version="swing-break-v1",
    swing_definition=SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2))
REPLAY_CUTOFF = pd.Timestamp("2025-06-30 17:00", tz=NY)   # DEVELOPMENT partition end: last session close
TABLES = ("swing_breaks", "episodes", "roles", "events", "anomalies", "direction_transitions", "role_transitions")
PRICE_COLUMNS = {"price", "open", "high", "low", "close", "level_ticks", "close_ticks", "swing_price_ticks"}
ROLE_SHORT = {BULL_ANCHOR: "bull anchor", BEAR_ANCHOR: "bear anchor", BULL_CANDIDATE_TARGET: "bull cand. target",
              BEAR_CANDIDATE_TARGET: "bear cand. target", PROTECTION: "PROTECTION", TARGET: "TARGET"}
# reference reconciliation on 1m is bounded to every 4th continuity segment (runtime); all others are full
REFERENCE_FILTER = {"1m": lambda k: k % 4 == 0}


def main() -> int:
    started = time.perf_counter()
    spec = load_session_spec()
    bars = load_development_bars()
    rows, gates, invariants, reconciliations, timings = [], {}, [], [], []
    add = lambda section, tf, metric, value: rows.append(  # noqa: E731
        {"section": section, "timeframe": tf, "metric": metric, "value": value})
    add("source", "", "canonical_1m_rows", len(bars))
    add("source", "", "first_bar_end", bars.index.min().isoformat())
    add("source", "", "last_bar_end", bars.index.max().isoformat())
    add("source", "", "replay_cutoff", REPLAY_CUTOFF.isoformat())

    runs = {}
    swing_ok = episodes_ok = anomalies_ok = True
    for tf in SWING_TIMEFRAMES:
        t0 = time.perf_counter()
        run = build_market_structure(bars, tf, spec, DEFINITION, instrument_id=INSTRUMENT, replay_cutoff=REPLAY_CUTOFF)
        t1 = time.perf_counter()
        inv = structure_invariants(run, spec)
        t2 = time.perf_counter()
        ref = reference_structure(run, spec, episode_filter=REFERENCE_FILTER.get(tf))
        rec = reconcile(run, ref)
        rec.insert(0, "timeframe", tf)
        rec.insert(1, "replayed_segments", len(ref["segments"]))
        t3 = time.perf_counter()
        runs[tf] = run
        invariants.append(inv)
        reconciliations.append(rec)
        timings.append({"timeframe": tf, "engine_seconds": round(t1 - t0, 1), "invariants_seconds": round(t2 - t1, 1),
                        "reference_seconds": round(t3 - t2, 1)})
        print(f"{tf}: engine {t1 - t0:.1f}s invariants {t2 - t1:.1f}s reference {t3 - t2:.1f}s; "
              f"events {len(run.events)} roles {len(run.roles)}", flush=True)
        up, low = int((run.swings["orientation"] == "UPPER").sum()), int((run.swings["orientation"] == "LOWER").sum())
        swing_ok &= (up, low) == EXPECTED_COUNTS[tf]
        episodes_ok &= len(run.episodes) == EXPECTED_CONTINUITY[tf][1]
        anomalies_ok &= run.anomalies.empty
        _summarize(run, tf, add)
    gates["swings_equal_frozen_swing_baseline"] = swing_ok
    gates["episodes_equal_continuity_segments"] = episodes_ok
    gates["no_dual_establishment_anomalies"] = anomalies_ok
    invariant_frame = pd.concat(invariants, ignore_index=True)
    gates["all_invariants_zero"] = int(invariant_frame["violations"].sum()) == 0
    reconciliation_frame = pd.concat(reconciliations, ignore_index=True)
    gates["engine_equals_independent_reference"] = int(
        reconciliation_frame[["engine_only", "reference_only"]].to_numpy().sum()) == 0

    # --- DEVELOPMENT prefix replays (cutoffs inside real gaps and episodes) --------------------------
    prefix_rows = []
    prefix_ok = True
    for tf in ("4H", "1H"):
        for label, cutoff in _prefix_cutoffs(runs[tf]):
            run = build_market_structure(bars, tf, spec, DEFINITION, instrument_id=INSTRUMENT, replay_cutoff=cutoff)
            equal, detail = _restricted_equal(run, runs[tf], cutoff)
            prefix_ok &= equal
            prefix_rows.append({"timeframe": tf, "case": label, "replay_cutoff": cutoff.isoformat(),
                                "restricted_equal": equal, "detail": detail,
                                "episodes": len(run.episodes), "resets": int((run.events["kind"] == RESET).sum())})
    gates["prefix_replay_equivalence_development"] = prefix_ok

    # --- visual package (local HTML with prices) + price-free manifest -------------------------------
    t_visual = time.perf_counter()
    cases = _visual(runs, spec)
    visual_seconds = time.perf_counter() - t_visual
    gates["visual_cases_generated"] = len({c["case_id"] for c in cases}) >= 18

    tracked = {
        "market_structure_dev_invariants.csv": invariant_frame,
        "market_structure_dev_reconciliation.csv": reconciliation_frame,
        "market_structure_dev_prefix_replay.csv": pd.DataFrame(prefix_rows),
        "market_structure_dev_runtime.csv": pd.DataFrame(timings),
        "market_structure_dev_episodes.csv": pd.concat([_episode_rows(runs[tf]) for tf in SWING_TIMEFRAMES],
                                                       ignore_index=True),
        "market_structure_visual_validation_cases.csv": pd.DataFrame(cases),
    }
    gates["no_validation_or_oos_data"] = True   # only the DEVELOPMENT partition file is read
    gates["no_strategy_pnl_backtest_or_optimization"] = True
    summary = pd.DataFrame(rows)
    tracked["market_structure_dev_summary.csv"] = summary
    gates["tracked_artifacts_price_free"] = all(not (PRICE_COLUMNS & set(f.columns)) for f in tracked.values())
    for name, ok in gates.items():
        summary.loc[len(summary)] = {"section": "machine_gate", "timeframe": "", "metric": name,
                                     "value": "PASS" if ok else "FAIL"}
    tracked["market_structure_dev_summary.csv"] = summary
    for name, frame in tracked.items():
        frame.to_csv(OUT / name, index=False)
    print(f"visual {visual_seconds:.1f}s; total {time.perf_counter() - started:.1f}s")
    for name, ok in gates.items():
        print(f"GATE {name}: {'PASS' if ok else 'FAIL'}")
    return 0 if all(gates.values()) else 1


# ---------------------------------------------------------------------------
# Summary metrics (price-free)
# ---------------------------------------------------------------------------


def _fingerprint(values) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def _summarize(run, tf, add) -> None:
    add("run", tf, "run_id", run.run_id)
    add("counts", tf, "swings", len(run.swings))
    add("counts", tf, "swing_breaks", len(run.swing_breaks))
    add("counts", tf, "episodes", len(run.episodes))
    for cause, count in run.episodes["opening_cause"].value_counts().sort_index().items():
        add("episodes", tf, f"opening_{cause}", int(count))
    add("episodes", tf, "opening_contract_changed", int(run.episodes["opening_contract_changed"].sum()))
    for (kind, direction), count in run.events.groupby(["kind", run.events["direction"].fillna("-")]).size().items():
        add("events", tf, f"{kind}_{direction}", int(count))
    for reason, count in run.events["reset_reason"].dropna().value_counts().sort_index().items():
        add("events", tf, f"RESET_reason_{reason}", int(count))
    for (prev, new), count in run.direction_transitions.groupby(["previous_state", "new_state"]).size().items():
        add("direction_transitions", tf, f"{prev}->{new}", int(count))
    kinds = dict(zip(run.roles["role_id"], run.roles["role_kind"]))
    exits = run.role_transitions.assign(kind=run.role_transitions["entity_id"].map(kinds))
    for kind, count in run.roles["role_kind"].value_counts().sort_index().items():
        add("roles", tf, f"{kind}_assigned", int(count))
    for (kind, state), count in exits.groupby(["kind", "new_state"]).size().items():
        add("roles", tf, f"{kind}_{state}", int(count))
    add("roles", tf, "active_at_cutoff", int(len(run.roles) - len(run.role_transitions)))
    add("anomalies", tf, "DUAL_ESTABLISHMENT", len(run.anomalies))
    for name, column in (("episode_id", run.episodes["episode_id"]), ("role_id", run.roles["role_id"]),
                         ("event_id", run.events["event_id"]), ("break_id", run.swing_breaks["break_id"])):
        add("identity", tf, f"{name}_sha256", _fingerprint(column))


def _episode_rows(run) -> pd.DataFrame:
    ep = run.episodes[["timeframe", "episode_id", "first_bar_end", "opening_cause", "previous_contract",
                       "opening_contract_changed", "contract"]].copy()
    resets = run.events[run.events["kind"] == RESET].set_index("episode_id")
    ep["reset_at"] = ep["episode_id"].map(resets["event_at"])
    ep["reset_reason"] = ep["episode_id"].map(resets["reset_reason"])
    return ep


# ---------------------------------------------------------------------------
# Prefix replay on DEVELOPMENT
# ---------------------------------------------------------------------------


def _prefix_cutoffs(run):
    """Cutoffs: inside the first contract-roll gap (after the DATA_GAP reset, before the new contract's first bar),
    exactly at a gap reset onset, one minute before it, and mid-episode."""
    ep = run.episodes.sort_values("first_bar_end").reset_index(drop=True)
    resets = run.events[run.events["kind"] == RESET].set_index("episode_id")
    roll = ep.index[ep["opening_contract_changed"].astype(bool)][0]
    before = ep.iloc[roll - 1]
    t_r = pd.Timestamp(resets.loc[before["episode_id"], "event_at"])
    first_new = pd.Timestamp(ep.iloc[roll]["first_bar_end"])
    gap = ep.index[(~ep["opening_contract_changed"].astype(bool)) & (ep.index > 0)][0]
    t_gap = pd.Timestamp(resets.loc[ep.iloc[gap - 1]["episode_id"], "event_at"])
    mid = pd.Timestamp(ep.iloc[2]["first_bar_end"]) + pd.Timedelta(days=3)
    return [("inside_roll_gap", t_r + (first_new - t_r) / 2), ("at_gap_reset_onset", t_gap),
            ("one_minute_before_gap_reset", t_gap - pd.Timedelta(minutes=1)), ("mid_episode", mid),
            ("at_new_contract_first_bar", first_new)]


def _restricted_equal(prefix, full, cutoff):
    for name in TABLES:
        a, b = getattr(prefix, name), getattr(full, name)
        column = "bar_end" if name == "anomalies" else "available_at"
        a = a.drop(columns=["run_id"]).reset_index(drop=True)
        b = b.loc[(pd.to_datetime(b[column], utc=True) <= cutoff).to_numpy()].drop(columns=["run_id"]).reset_index(drop=True)
        if a.empty and b.empty:
            continue
        try:
            pd.testing.assert_frame_equal(a, b)
        except AssertionError:
            return False, f"{name} differs"
    return True, ""


# ---------------------------------------------------------------------------
# Visual validation (local HTML, price-bearing) + price-free manifest
# ---------------------------------------------------------------------------

_KIND_CSS = {BULL_ANCHOR: "ba", BEAR_ANCHOR: "ra", BULL_CANDIDATE_TARGET: "bt", BEAR_CANDIDATE_TARGET: "rt",
             PROTECTION: "pr", TARGET: "tg"}


def _chart(obs, run, t0, t1, *, events=(), focus_roles=None, resets=(), marks=(), H=300, W=980, pad=46):
    """Candles in [t0, t1] with role levels (assigned → exit), events, resets and swing confirmations."""
    obs = obs[(pd.to_datetime(obs["bar_end"], utc=True) >= t0) & (pd.to_datetime(obs["bar_end"], utc=True) <= t1)]
    obs = obs.sort_values("bar_end").reset_index(drop=True)
    if obs.empty:
        return "<p class='note'>(no observations in window)</p>"
    ends = list(pd.to_datetime(obs["bar_end"], utc=True))
    tick = float(run.manifest["tick_size"])
    roles = run.roles if focus_roles is None else run.roles[run.roles["role_id"].isin(focus_roles)]
    exits = run.role_transitions.set_index("entity_id")
    segs = []
    for r in roles.itertuples(index=False):
        a = pd.Timestamp(r.assigned_at)
        e = pd.Timestamp(exits.loc[r.role_id, "transition_at"]) if r.role_id in exits.index else ends[-1]
        state = exits.loc[r.role_id, "new_state"] if r.role_id in exits.index else "ACTIVE"
        if e < ends[0] or a > ends[-1]:
            continue
        segs.append((max(a, ends[0]), min(e, ends[-1]), r.swing_price_ticks * tick, r.role_kind, state))
    prices = list(obs["high"]) + list(obs["low"]) + [s[2] for s in segs] + [m[1] for m in marks]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.06, hi + span * 0.12
    n = len(obs)
    cw = (W - 2 * pad) / n
    y = lambda v: pad + (hi - v) / (hi - lo) * (H - 2 * pad)  # noqa: E731

    def x(ts):
        ts = pd.Timestamp(ts)
        for i, e in enumerate(ends):
            if e >= ts:
                return pad + i * cw + cw / 2 if e == ts else pad + i * cw
        return W - pad

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    for i, row in obs.iterrows():
        xc = pad + i * cw + cw / 2
        css = "up" if row["close"] >= row["open"] else "dn"
        out.append(f'<line x1="{xc:.1f}" x2="{xc:.1f}" y1="{y(row["high"]):.1f}" y2="{y(row["low"]):.1f}" class="wk"/>')
        top, bot = y(max(row["open"], row["close"])), y(min(row["open"], row["close"]))
        tip = (f'{pd.Timestamp(row["bar_end"]).tz_convert(NY):%Y-%m-%d %H:%M} O{row["open"]} H{row["high"]} '
               f'L{row["low"]} C{row["close"]}')
        out.append(f'<rect x="{xc - cw * 0.36:.1f}" y="{top:.1f}" width="{max(cw * 0.72, 0.8):.1f}" '
                   f'height="{max(bot - top, 1.0):.1f}" class="{css}"><title>{html.escape(tip)}</title></rect>')
        if n <= 40 or i % max(1, n // 10) == 0:
            out.append(f'<text x="{xc:.1f}" y="{H - 10}" class="tk" text-anchor="middle">'
                       f'{pd.Timestamp(row["bar_end"]).tz_convert(NY):%m-%d %H:%M}</text>')
    for a, e, price, kind, state in segs:
        css = _KIND_CSS[kind]
        out.append(f'<line x1="{x(a):.1f}" x2="{x(e):.1f}" y1="{y(price):.1f}" y2="{y(price):.1f}" class="role {css}"/>'
                   f'<text x="{x(a) + 2:.1f}" y="{y(price) - 3:.1f}" class="rl {css}">{html.escape(ROLE_SHORT[kind])}'
                   f' → {state}</text>')
    for ts, price, label, css in marks:
        out.append(f'<circle cx="{x(ts):.1f}" cy="{y(price):.1f}" r="4" class="{css}"/>'
                   f'<text x="{x(ts) + 5:.1f}" y="{y(price) + 12:.1f}" class="ml {css}">{html.escape(label)}</text>')
    for k, (ts, label) in enumerate(events):
        out.append(f'<line x1="{x(ts):.1f}" x2="{x(ts):.1f}" y1="{pad - 16}" y2="{H - pad}" class="ev"/>'
                   f'<text x="{x(ts) + 3:.1f}" y="{pad - 18 - 11 * (k % 2)}" class="evl">{html.escape(label)}</text>')
    for ts, label in resets:
        out.append(f'<line x1="{x(ts):.1f}" x2="{x(ts):.1f}" y1="{pad - 16}" y2="{H - pad}" class="rs"/>'
                   f'<text x="{x(ts) + 3:.1f}" y="{H - pad - 4}" class="rsl">{html.escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def _ts(value):
    return "" if value is None or pd.isna(value) else pd.Timestamp(value).tz_convert(NY).isoformat()


def _visual(runs, spec):
    sections, manifest = [], []

    def record(case_id, source, tf, area, case, note, chart, refs=(), synthetic_reason=""):
        tag = '<span class="real">REAL DEVELOPMENT</span>' if source == "REAL" else '<span class="syn">SYNTHETIC</span>'
        sections.append(f"<section><h3>{html.escape(case_id)} · {html.escape(tf)} · {html.escape(area)} — "
                        f"{html.escape(case)} {tag}</h3><p class='note'>{html.escape(note)}</p>{chart}</section>")
        manifest.append({"case_id": case_id, "source": source, "timeframe": tf, "area": area, "case": case,
                         "refs": " ".join(refs), "synthetic_reason": synthetic_reason})

    def roles_of(run, kind):
        return run.roles[run.roles["role_kind"] == kind]

    def exit_of(run, role_id):
        tr = run.role_transitions
        hit = tr[tr["entity_id"] == role_id]
        return (hit.iloc[0]["new_state"], pd.Timestamp(hit.iloc[0]["transition_at"])) if len(hit) else (None, None)

    def window(run, at, before, after):
        obs = run.observations
        ends = pd.to_datetime(obs["bar_end"], utc=True).sort_values().reset_index(drop=True)
        i = int(ends.searchsorted(pd.Timestamp(at)))
        return ends.iloc[max(0, i - before)], ends.iloc[min(len(ends) - 1, i + after)]

    def roles_at(run, at):
        """Roles active in the pre-state of the observation ending at ``at`` (assigned before, not exited before)."""
        exits = dict(zip(run.role_transitions["entity_id"], pd.to_datetime(run.role_transitions["transition_at"], utc=True)))
        r = run.roles
        mask = (pd.to_datetime(r["assigned_at"], utc=True) < at) & r["role_id"].map(lambda i: i not in exits or exits[i] >= at)
        return r[mask]

    def describe(run, at):
        pre = roles_at(run, at)
        tick = float(run.manifest["tick_size"])
        return "; ".join(f"{ROLE_SHORT[k]} {p * tick:g}" for k, p in zip(pre["role_kind"], pre["swing_price_ticks"]))

    def event_case(case_id, tf, kind, direction=None, pick=0, predicate=None, area="Classification", note_extra=""):
        run = runs[tf]
        ev = run.events[run.events["kind"] == kind]
        if direction:
            ev = ev[ev["direction"] == direction]
        if predicate is not None:
            ev = ev[[predicate(run, e) for e in ev.itertuples(index=False)]]
        if ev.empty:
            raise RuntimeError(f"REAL case not reproducible: {case_id} {tf} {kind} {direction}")
        e = ev.iloc[min(pick, len(ev) - 1)]
        at = pd.Timestamp(e["event_at"])
        t0, t1 = window(run, at, 26, 8)
        brk = run.swing_breaks[run.swing_breaks["break_id"] == e["break_id"]].iloc[0]
        tick = float(run.manifest["tick_size"])
        note = (f"Pre-state at s(N): {describe(run, at)}. Break evidence: close {brk['close_ticks'] * tick:g} vs level "
                f"{brk['level_ticks'] * tick:g} ({brk['close_excess_ticks']} ticks beyond). Event {kind} "
                f"({e['direction']}; {e['pre_direction']}→{e['post_direction']}) at {_ts(at)}. {note_extra}")
        record(case_id, "REAL", tf, area, f"{kind} {e['direction'] or ''}".strip(), note,
               _chart(run.observations, run, t0, t1, events=[(at, f"{kind} {e['direction']}")]),
               refs=(e["event_id"], e["break_id"]))
        return e

    # --- classifications ---------------------------------------------------------------------------
    event_case("R01", "4H", ESTABLISHMENT, "BULLISH", area="Establishment",
               note_extra="Anchor, candidate target and deepest pullback after the target (strictly above the anchor).")
    event_case("R02", "4H", ESTABLISHMENT, "BEARISH", area="Establishment", note_extra="Mirror on the bearish side.")

    def bos_kept(run, e):
        prot = roles_of(run, PROTECTION)
        return not (pd.to_datetime(prot["assigned_at"], utc=True) == pd.Timestamp(e.event_at)).any()

    event_case("R03", "1H", BOS, predicate=bos_kept, area="BOS",
               note_extra="No strictly tighter deepest pullback: PROTECTION keeps its role_id, assigned_at and promotion "
                          "parent (no transition at this BOS).")
    event_case("R04", "1H", BOS, predicate=lambda run, e: not bos_kept(run, e), area="BOS",
               note_extra="Strictly tighter deepest pullback: old PROTECTION REPLACED, new PROTECTION parented by this BOS.")
    event_case("R05", "1H", CHOCH, area="CHoCH",
               note_extra="Protection BROKEN, target ENDED, direction → UNDEFINED; candidates reseed in the same batch "
                          "with K-3 historical scope (source_at ≥ broken protection source_at).")
    event_case("R06", "4H", CHOCH, pick=1, area="CHoCH", note_extra="Second REAL CHoCH example.")

    # --- failures, invalidations, supersessions (non-event role exits) --------------------------------
    def exit_case(case_id, tf, kind, state, area, note, predicate=None, pick=0):
        run = runs[tf]
        tr = run.role_transitions
        ids = set(roles_of(run, kind)["role_id"])
        hits = tr[(tr["new_state"] == state) & tr["entity_id"].isin(ids)].sort_values("transition_at")
        if predicate is not None:
            hits = hits[[predicate(run, h) for h in hits.itertuples(index=False)]]
        if hits.empty:
            raise RuntimeError(f"REAL case not reproducible: {case_id} {tf} {kind} {state}")
        h = hits.iloc[min(pick, len(hits) - 1)]
        at = pd.Timestamp(h["transition_at"])
        t0, t1 = window(run, at, 26, 6)
        record(case_id, "REAL", tf, area, f"{ROLE_SHORT[kind]} → {state}",
               f"Pre-state at s(N): {describe(run, at)}. {note} Exit at {_ts(at)}.",
               _chart(run.observations, run, t0, t1, events=[(at, f"{state}")]), refs=(h["entity_id"],))
        return h

    exit_case("R07", "1H", BULL_CANDIDATE_TARGET, "RETIRED", "Failed establishment",
              "Close beyond the candidate target without qualification (deepest pullback missing, not beyond the anchor, "
              "or stale): target RETIRED, anchor persists, no event, no retrospective establishment (K-4 / K-8).")
    exit_case("R08", "1H", BEAR_CANDIDATE_TARGET, "RETIRED", "Failed establishment", "Bearish mirror of R07.")
    exit_case("R09", "1H", BULL_ANCHOR, "BROKEN", "Invalidation",
              "Close below the bull anchor while UNDEFINED: anchor BROKEN, no event; reseed only from eligible later "
              "admissions (K-2).", predicate=lambda run, h: True)
    exit_case("R10", "1H", TARGET, "SUPERSEDED", "Target progression",
              "A strictly more extreme since-expansion target admitted: old TARGET SUPERSEDED (K-7, D4).")

    def same_close(run, h):
        """T-1: a candidate target retired at e(N) and a new one created at e(N) on a swing confirmed at e(N)."""
        at = pd.Timestamp(h.transition_at)
        new = run.roles[(pd.to_datetime(run.roles["assigned_at"], utc=True) == at)
                        & run.roles["role_kind"].isin([BULL_CANDIDATE_TARGET, BEAR_CANDIDATE_TARGET])]
        return bool((pd.to_datetime(new["swing_available_at"], utc=True) == at).any())

    for case_id, tf in (("R11", "15m"), ("R11", "5m")):
        try:
            exit_case(case_id, tf, BULL_CANDIDATE_TARGET, "RETIRED", "T-1 same-close target",
                      "Failed establishment at N; a target confirmed at e(N) is assigned at e(N), was not used to classify "
                      "N, and is usable only from the next bar_start (T-1).", predicate=same_close)
            break
        except RuntimeError:
            if tf == "5m":
                raise

    def outside(run):
        r = run.roles
        anchors = r[r["role_kind"].isin([BULL_ANCHOR, BEAR_ANCHOR])]
        both = anchors.groupby("assigned_at").filter(
            lambda g: len(g) == 2 and g["swing_source_at"].nunique() == 1
            and (pd.to_datetime(g["swing_available_at"], utc=True) == pd.to_datetime(g["assigned_at"], utc=True)).all())
        return both

    for tf in ("1H", "15m", "5m"):
        both = outside(runs[tf])
        if len(both):
            run = runs[tf]
            at = pd.Timestamp(both.iloc[0]["assigned_at"])
            t0, t1 = window(run, at, 20, 6)
            record("R12", "REAL", tf, "Simultaneous admission", "outside bar replaces both anchors in one batch",
                   f"Pre-state: {describe(run, at)}. One observation is both a Swing High and a Swing Low (shared last "
                   "plateau bar, L0); both are admitted at the same e(N) and the rescan replaces both anchors in one "
                   "batch; no entity is created and exited at one instant.",
                   _chart(run.observations, run, t0, t1, events=[(at, "admission batch")]),
                   refs=tuple(both["role_id"]))
            break
    else:
        raise RuntimeError("REAL case not reproducible: outside bar simultaneous admission")

    # --- lifecycle: gap reset, contract-roll reset (CB-1) -------------------------------------------
    for case_id, tf, changed, label in (("R13", "1H", False, "gap reset, same contract (DATA_GAP)"),
                                        ("R14", "4H", True, "roll during missing roll-week sessions (CB-1)")):
        run = runs[tf]
        ep = run.episodes.sort_values("first_bar_end").reset_index(drop=True)
        k = ep.index[(ep["opening_contract_changed"].astype(bool) == changed) & (ep.index > 0)][0]
        new, old = ep.iloc[k], ep.iloc[k - 1]
        reset = run.events[(run.events["kind"] == RESET) & (run.events["episode_id"] == old["episode_id"])].iloc[0]
        t_r, first = pd.Timestamp(reset["event_at"]), pd.Timestamp(new["first_bar_end"])
        t0, _ = window(run, t_r, 18, 0)
        _, t1 = window(run, first, 0, 6)
        note = (f"Last {old['contract']} observation, then RESET({reset['reset_reason']}) at the expected completion of "
                f"the first missing observation {_ts(t_r)} (no contract flag on the reset). New episode "
                f"{new['opening_cause']} at {_ts(first)} on {new['contract']} (previous {new['previous_contract']}, "
                f"contract_changed={bool(new['opening_contract_changed'])}); its opening_ref is the reset ref. No state "
                "crosses the boundary.")
        record(case_id, "REAL", tf, "Lifecycle", label, note,
               _chart(run.observations, run, t0, t1, resets=[(t_r, f"RESET {reset['reset_reason']}")],
                      events=[(first, f"open {new['opening_cause']}")]),
               refs=(reset["event_id"], new["episode_id"]))

    # --- HTF -> LTF causal boundary ------------------------------------------------------------------
    run4, run5 = runs["4H"], runs["5m"]
    e = run4.events[run4.events["kind"].isin([BOS, ESTABLISHMENT])].iloc[3]
    at = pd.Timestamp(e["event_at"])
    obs5 = run5.observations
    first5 = obs5[pd.to_datetime(obs5["bar_start"], utc=True) >= at].sort_values("bar_start").iloc[0]
    t0, t1 = window(run4, at, 10, 3)
    note = (f"4H {e['kind']} {e['direction']} available at {_ts(at)}. The first 5m bar that may reference its event_id "
            f"is the one with bar_start {_ts(first5['bar_start'])} (HTF available_at ≤ LTF bar_start); 5m structure is "
            "computed independently and never copies or mutates 4H state.")
    record("R15", "REAL", "4H→5m", "Cross-timeframe", "HTF event first readable by LTF bar_start", note,
           _chart(run4.observations, run4, t0, t1, events=[(at, f"4H {e['kind']}")]) +
           "<div class='pl'>5m, same period</div>" +
           _chart(run5.observations, run5, at - pd.Timedelta(hours=2), at + pd.Timedelta(hours=1),
                  events=[(at, "4H event available")], focus_roles=[]),
           refs=(e["event_id"],))

    # --- synthetic normative examples (production engine on §H.0 bars) --------------------------------
    for case_id, title, rows_, kwargs in _synthetic_cases():
        bars = _synthetic_bars(rows_, spec, **kwargs)
        last = len(rows_) - 1
        cutoff = pd.Timestamp(_sched(spec)["bar_end"].iloc[kwargs.pop("cutoff_k", last) if "cutoff_k" in kwargs
                                                            else last]).tz_convert("UTC")
        run = build_market_structure(bars, "5m", spec, DEFINITION, instrument_id=INSTRUMENT, replay_cutoff=cutoff)
        evs = [(pd.Timestamp(r.event_at), f"{r.kind} {r.direction or r.reset_reason}") for r in run.events.itertuples()]
        resets = [(t, lbl) for t, lbl in evs if lbl.startswith("RESET")]
        evs = [(t, lbl) for t, lbl in evs if not lbl.startswith("RESET")]
        story = "; ".join(f"{r.role_kind} {r.swing_price_ticks * 0.25 - 20000:g}" for r in run.roles.itertuples())
        record(case_id, "SYNTHETIC", "5m", "Normative example", title,
               f"Production engine on the explicit OHLC of MARKET_STRUCTURE_SPEC §H.0 (prices shown +20000). Roles: "
               f"{story}. Episodes: {len(run.episodes)}.",
               _chart(run.observations, run, pd.Timestamp(run.observations['bar_end'].min()).tz_convert('UTC'),
                      cutoff, events=evs, resets=resets),
               synthetic_reason="exact normative example (spec §H) or contract boundary absent from DEVELOPMENT")

    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Structure Validation</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--mu:#666;--up:#1a7f5a;--dn:#c0392b}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--mu:#9a9a9a;--up:#3ec48e;--dn:#ef6b5b}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;max-width:1020px;margin:0 auto;padding:16px}}
h1{{font-size:20px}} h3{{font-size:15px;margin:26px 0 4px}} .note{{color:var(--mu);margin:2px 0 6px}} .pl{{font-size:12px;color:var(--mu)}}
.wk{{stroke:var(--mu)}} .up{{fill:var(--up)}} .dn{{fill:var(--dn)}} .tk{{fill:var(--mu);font-size:10px}}
.role{{stroke-width:2}} .rl{{font-size:9.5px}} .ba{{stroke:#2f5bd3;fill:#2f5bd3}} .ra{{stroke:#b03aa8;fill:#b03aa8}}
.bt{{stroke:#4f9bd9;fill:#4f9bd9;stroke-dasharray:5 3}} .rt{{stroke:#d07ac8;fill:#d07ac8;stroke-dasharray:5 3}}
.pr{{stroke:#d99a00;fill:#d99a00}} .tg{{stroke:#1a9b8a;fill:#1a9b8a;stroke-dasharray:2 2}}
.ev{{stroke:var(--fg);stroke-dasharray:3 3}} .evl{{font-size:10px;fill:var(--fg)}} .rs{{stroke:#c0392b;stroke-width:2}} .rsl{{fill:#c0392b;font-size:10px}}
.ml{{font-size:10px}} .syn{{background:#d99a00;color:#000;border-radius:4px;padding:1px 6px;font-size:11px}}
.real{{background:#2f5bd3;color:#fff;border-radius:4px;padding:1px 6px;font-size:11px}}
</style></head><body><h1>Generic Market Structure — MS-I3 visual validation</h1>
<p class="note">LOCAL ONLY — contains market prices (Git-ignored). Production engine (build_market_structure), DEVELOPMENT,
structure-v1 / swing-break-v1 over the explicit 2/2 Swing reference, replay cutoff {REPLAY_CUTOFF.isoformat()}.
Horizontal lines are role assignments drawn from assigned_at to their exit (label: role → exit state). Dashed vertical
lines are classification instants e(N); red lines are RESET onsets. Each note lists the pre-state at s(N), the break
evidence and the outcome. Machine-validation evidence; human visual approval pending.</p>
{''.join(sections)}</body></html>"""
    (OUT / "market_structure_visual_validation.html").write_text(page, encoding="utf-8")
    return manifest


def _sched(spec):
    days = [date(2026, 9, 14 + d) for d in range(5)] + [date(2026, 9, 21 + d) for d in range(5)]
    return expected_timeframe_schedule(days, "5m", spec).reset_index(drop=True)


def _synthetic_bars(rows, spec, *, contracts=None, absent=(), incomplete=(), cutoff_k=None):
    sched = _sched(spec)
    frames = []
    for k, row in enumerate(rows):
        if row is None or k in absent:
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


def _synthetic_cases():
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


if __name__ == "__main__":
    raise SystemExit(main())
