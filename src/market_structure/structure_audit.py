"""Market Structure audit and invariants (MS-I3) — AUDIT / VALIDATION ONLY.

Not part of the downstream contract; no Strategy or execution code may
depend on it.  It provides an independent cross-check of the MS-I2 engine
(``structure.py``):

- ``reference_structure``: a straightforward re-implementation of the §E / §F
  rules written from the specification, sharing no selection, breach, diff
  or exit-reason code with the engine.  It uses frozen continuity segments
  (not the reset adapter), computes breaches by scanning closes, selects by
  the literal total orders of §E.1 (price, ``available_at``, ``source_at``,
  ``source_end_at``, ``swing_id``) over plain lists, and records roles by
  semantic content (kind, swing, assignment / exit instant and state).
- ``reconcile``: compares the engine's roles, events and direction
  transitions with the reference (exact set equality).
- ``structure_invariants``: INV-1 … INV-17 (spec §I.3) with violation counts.
"""

from __future__ import annotations

import bisect
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from src.data.continuity import continuity_segments
from src.data.sessions import SessionSpec
from src.data.timeframes import DEFAULT_SOURCE_INTERVAL, TimeframeSpec, expected_timeframe_schedule
from src.market_structure.swing import UPPER, SwingDefinitionSpec
from src.market_structure.swing_breaks import price_ticks
from src.market_structure.structure import (
    BEAR_ANCHOR,
    BEAR_CANDIDATE_TARGET,
    BEARISH,
    BOS,
    BROKEN,
    BULL_ANCHOR,
    BULL_CANDIDATE_TARGET,
    BULLISH,
    CHOCH,
    CONSUMED,
    CONTRACT_CHANGE,
    CONTRACT_CHANGE_REESTABLISHMENT,
    DATA_GAP,
    DATA_GAP_REESTABLISHMENT,
    DATA_START,
    ENDED,
    ESTABLISHMENT,
    PROTECTION,
    REPLACED,
    RESET,
    RETIRED,
    SUPERSEDED,
    TARGET,
    UNDEFINED,
    MarketStructureRun,
    StructureDefinitionSpec,
    direction_namespace,
    require_cutoff,
    role_namespace,
)
from src.state.contract import validate_transitions

_PRECEDENCE = (CONSUMED, BROKEN, REPLACED, RETIRED, SUPERSEDED, ENDED)


# ---------------------------------------------------------------------------
# Independent reference replay
# ---------------------------------------------------------------------------


class _RefSwing:
    __slots__ = ("id", "up", "price", "a", "b", "av", "av_time", "source_at", "source_end_at")

    def __init__(self, row, price, a, b, av):
        self.id, self.up, self.price = row.swing_id, row.orientation == UPPER, price
        self.a, self.b, self.av = a, b, av
        self.av_time, self.source_at, self.source_end_at = row.available_at, row.source_at, row.source_end_at

    def order(self, best_high: bool):
        """§E.1 total order: most extreme price, then first eligible, earliest source span, swing_id."""
        return (-self.price if best_high else self.price, self.av_time, self.source_at, self.source_end_at, self.id)


def _pick(candidates, best_high):
    return min(candidates, key=lambda s: s.order(best_high)) if candidates else None


def _pick_pullback(candidates, best_high):
    """§E.1 pullback order: deepest, then earliest source span, then swing_id."""
    if not candidates:
        return None
    return min(candidates, key=lambda s: (-s.price if best_high else s.price, s.source_at, s.source_end_at, s.id))


def _reference_episode(rows: pd.DataFrame, swings: list[_RefSwing], tick) -> dict:
    closes = [int(v) for v in price_ticks(rows["close"].to_numpy(), tick)]
    alive: list[_RefSwing] = []          # admitted, not yet breached
    roles: dict[str, tuple] = {}         # kind -> (swing, parent, assigned position)
    log_roles, log_events, log_dirs = [], [], []
    direction = UNDEFINED
    scope_a, choch = 0, None
    expansion = baseline = protection = leg = None

    def after(x, ref):
        return x.a > ref.b

    for N, c in enumerate(closes):
        reasons: dict[str, set] = {}

        def mark(kind, reason):
            if kind in roles:
                reasons.setdefault(kind, set()).add(reason)

        lows = [s for s in alive if not s.up]
        highs = [s for s in alive if s.up]
        event = promote = None
        if direction == UNDEFINED:
            wins, tries = [], {}
            for kind_a, kind_t, bull in ((BULL_ANCHOR, BULL_CANDIDATE_TARGET, True),
                                         (BEAR_ANCHOR, BEAR_CANDIDATE_TARGET, False)):
                if kind_a not in roles:
                    continue
                anchor = roles[kind_a][0]
                if (c < anchor.price) if bull else (c > anchor.price):
                    mark(kind_a, BROKEN)
                    continue
                if kind_t not in roles:
                    continue
                target = roles[kind_t][0]
                if (c > target.price) if bull else (c < target.price):
                    p = _pick_pullback([s for s in (lows if bull else highs) if after(s, target)], best_high=not bull)
                    ok = p is not None and ((p.price > anchor.price) if bull else (p.price < anchor.price))
                    ok = ok and (choch is None or p.a > choch)
                    tries[kind_t] = (bull, ok, target, p)
                    if ok:
                        wins.append(kind_t)
            for kind_t, (bull, ok, target, p) in tries.items():
                if not (ok and len(wins) == 1):
                    mark(kind_t, RETIRED)
            if len(wins) == 1:
                bull, _, target, p = tries[wins[0]]
                mark(wins[0], CONSUMED)
                event = (ESTABLISHMENT, BULLISH if bull else BEARISH, target)
                promote = p
        else:
            bull = direction == BULLISH
            prot = roles[PROTECTION][0]
            if (c < prot.price) if bull else (c > prot.price):
                mark(PROTECTION, BROKEN)
                if TARGET in roles:
                    pass
                event = (CHOCH, BEARISH if bull else BULLISH, prot)
            elif TARGET in roles and ((c > roles[TARGET][0].price) if bull else (c < roles[TARGET][0].price)):
                target = roles[TARGET][0]
                mark(TARGET, CONSUMED)
                event = (BOS, direction, target)
                p = _pick_pullback([s for s in (lows if bull else highs) if after(s, target)], best_high=not bull)
                if p is not None and ((p.price > prot.price) if bull else (p.price < prot.price)):
                    mark(PROTECTION, REPLACED)
                    promote = p

        # breaches at N (independent close scan), then admissions at e(N)
        alive = [s for s in alive if not ((c > s.price) if s.up else (c < s.price))]
        alive += [s for s in swings if s.av == N]

        if event is not None:
            kind, new_direction, ref = event
            if kind == ESTABLISHMENT:
                log_dirs.append((N, direction, new_direction))
                direction, baseline, expansion, leg = new_direction, ref, N, N
                protection = (promote, N)
            elif kind == BOS:
                baseline, expansion, leg = ref, N, N
                if promote is not None:
                    protection = (promote, N)
            else:
                log_dirs.append((N, direction, UNDEFINED))
                direction, scope_a, choch = UNDEFINED, ref.a, N
                baseline = expansion = leg = protection = None
            log_events.append((N, kind, new_direction, ref.id))

        # final roles by literal rescan
        lows = [s for s in alive if not s.up]
        highs = [s for s in alive if s.up]
        final: dict[str, tuple] = {}

        def keep_or_new(kind, swing, parent):
            old = roles.get(kind)
            return old if old is not None and old[0] is swing and old[1] == parent else (swing, parent, N)

        if direction == UNDEFINED:
            for kind_a, kind_t, anchor_pool, target_pool, bull in (
                    (BULL_ANCHOR, BULL_CANDIDATE_TARGET, lows, highs, True),
                    (BEAR_ANCHOR, BEAR_CANDIDATE_TARGET, highs, lows, False)):
                anchor = _pick([s for s in anchor_pool if s.a >= scope_a], best_high=not bull)
                if anchor is None:
                    continue
                final[kind_a] = keep_or_new(kind_a, anchor, ("scope", scope_a))
                target = _pick([s for s in target_pool if after(s, anchor)], best_high=bull)
                if target is not None:
                    final[kind_t] = keep_or_new(kind_t, target, ("anchor", anchor.id, final[kind_a][2]))
        else:
            bull = direction == BULLISH
            final[PROTECTION] = keep_or_new(PROTECTION, protection[0], ("promotion", protection[1]))
            pool = [s for s in (highs if bull else lows)
                    if after(s, baseline) and s.b >= expansion
                    and ((s.price > baseline.price) if bull else (s.price < baseline.price))]
            target = _pick(pool, best_high=bull)
            if target is not None:
                final[TARGET] = keep_or_new(TARGET, target, ("leg", leg))

        for kind, old in roles.items():
            if final.get(kind) is old:
                continue
            new = final.get(kind)
            got = set(reasons.get(kind, set()))
            if new is not None and new[0] is not old[0] and kind != PROTECTION and \
                    (kind not in (BULL_CANDIDATE_TARGET, BEAR_CANDIDATE_TARGET) or new[1] == old[1]):
                lower_better = kind in (BULL_ANCHOR, BEAR_CANDIDATE_TARGET) or (kind == TARGET and direction == BEARISH)
                if (new[0].price < old[0].price) if lower_better else (new[0].price > old[0].price):
                    got.add(SUPERSEDED)
            log_roles.append((kind, old[0].id, old[2], next((s for s in _PRECEDENCE if s in got), ENDED), N))
        roles = final
    return {"roles": log_roles, "active": [(k, v[0].id, v[2]) for k, v in roles.items()], "events": log_events,
            "directions": log_dirs}


def reference_structure(run: MarketStructureRun, session_spec: SessionSpec, *,
                        source_interval: Any = DEFAULT_SOURCE_INTERVAL, episode_filter=None) -> dict:
    """Independent replay over frozen continuity segments of the run's own observations and swings.

    Returns semantic tuples with absolute UTC times so they compare directly
    with the engine output.  ``episode_filter(k)`` limits the replay to chosen
    segment indices (bounds the runtime on 1m).
    """
    timeframe = run.manifest["timeframe"]
    tick = Decimal(run.manifest["tick_size"])
    cutoff = require_cutoff(pd.Timestamp(run.manifest["replay_cutoff"]))
    obs = run.observations.loc[(pd.to_datetime(run.observations["bar_end"], utc=True) <= cutoff).to_numpy()]
    tf_spec = TimeframeSpec("1m", 1) if timeframe == "1m" else timeframe
    segments, _ = continuity_segments(obs, tf_spec, session_spec, source_interval=source_interval)
    where = {}
    for k, seg in enumerate(segments):
        for p, end in enumerate(pd.to_datetime(seg["bar_end"], utc=True)):
            where[end.value] = (k, p)
    per = [[] for _ in segments]
    prices = price_ticks(run.swings["price"].to_numpy(), tick) if len(run.swings) else []
    for row, price in zip(run.swings.itertuples(index=False), prices):
        k, a = where[pd.Timestamp(row.source_at).value]
        _, b = where[pd.Timestamp(row.source_end_at).value]
        _, av = where[pd.Timestamp(row.available_at).value]
        per[k].append(_RefSwing(row, int(price), a, b, av))
    out = {"roles": set(), "active": set(), "events": set(), "directions": set(), "segments": []}
    for k, seg in enumerate(segments):
        if episode_filter is not None and not episode_filter(k):
            continue
        ends = list(pd.to_datetime(seg["bar_end"], utc=True))
        result = _reference_episode(seg.reset_index(drop=True), per[k], tick)
        out["segments"].append((ends[0], ends[-1]))
        out["roles"] |= {(kind, sid, ends[a], state, ends[x]) for kind, sid, a, state, x in result["roles"]}
        out["active"] |= {(kind, sid, ends[a]) for kind, sid, a in result["active"]}
        out["events"] |= {(ends[p], kind, d, sid) for p, kind, d, sid in result["events"]}
        out["directions"] |= {(ends[p], a, b) for p, a, b in result["directions"]}
    return out


def reconcile(run: MarketStructureRun, reference: dict) -> pd.DataFrame:
    """Exact comparison of engine output and the reference over the replayed segments.

    RESET content is excluded (the reference has no adapter); roles ended by a
    RESET count as active at segment end on both sides.
    """
    windows = sorted(reference["segments"])
    starts = [lo for lo, _ in windows]

    def inside(ts):
        ts = pd.Timestamp(ts)
        i = bisect.bisect_right(starts, ts) - 1
        return i >= 0 and windows[i][0] <= ts <= windows[i][1]

    all_exits = run.role_transitions.set_index("entity_id")
    engine_roles, engine_active = set(), set()
    for role in run.roles.itertuples(index=False):
        if not inside(role.assigned_at):
            continue
        assigned = pd.Timestamp(role.assigned_at)
        if role.role_id in all_exits.index:
            ex = all_exits.loc[role.role_id]
            if str(ex["trigger_ref"]).startswith("CONTINUITY_BREAK:"):
                engine_active.add((role.role_kind, role.swing_id, assigned))
            else:
                engine_roles.add((role.role_kind, role.swing_id, assigned, ex["new_state"],
                                  pd.Timestamp(ex["transition_at"])))
        else:
            engine_active.add((role.role_kind, role.swing_id, assigned))
    engine_events = {(pd.Timestamp(e.event_at), e.kind, e.direction, e.swing_id)
                     for e in run.events.itertuples(index=False) if e.kind != RESET and inside(e.event_at)}
    engine_dirs = {(pd.Timestamp(t.transition_at), t.previous_state, t.new_state)
                   for t in run.direction_transitions.itertuples(index=False)
                   if t.new_state != RESET and inside(t.transition_at)}
    rows = []
    for name, engine, ref in (("role_exits", engine_roles, reference["roles"]),
                              ("roles_active_at_segment_end", engine_active, reference["active"]),
                              ("events", engine_events, reference["events"]),
                              ("direction_transitions", engine_dirs, reference["directions"])):
        rows.append({"item": name, "engine": len(engine), "reference": len(ref),
                     "engine_only": len(engine - ref), "reference_only": len(ref - engine)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Invariants (spec §I.3)
# ---------------------------------------------------------------------------


def structure_invariants(run: MarketStructureRun, session_spec: SessionSpec, *,
                         source_interval: Any = DEFAULT_SOURCE_INTERVAL) -> pd.DataFrame:
    """INV-1 … INV-17 violation counts for one run (each must be 0)."""
    tf = run.manifest["timeframe"]
    tick = float(run.manifest["tick_size"])
    cutoff = require_cutoff(pd.Timestamp(run.manifest["replay_cutoff"]))
    if run.episodes.empty:
        return _zero_episode_invariants(run, session_spec, cutoff, tf, source_interval)
    swings = run.swings.set_index("swing_id")
    breaks = run.swing_breaks.set_index("swing_id")
    roles, events, rt, dt = run.roles, run.events, run.role_transitions, run.direction_transitions
    exits = rt.set_index("entity_id")
    events_by_id = events.set_index("event_id")
    start_of = dict(zip(pd.to_datetime(run.observations["bar_end"], utc=True),
                        pd.to_datetime(run.observations["bar_start"], utc=True)))
    v: dict[str, int] = {}

    def breach_at(swing_id):
        return pd.Timestamp(breaks.loc[swing_id, "bar_end"]) if swing_id in breaks.index else None

    v["INV-1 no structure_anomalies rows"] = len(run.anomalies)

    bad = 0
    for e in events[events["kind"] != RESET].itertuples(index=False):
        start = start_of[pd.Timestamp(e.event_at)]
        bad += int(pd.Timestamp(swings.loc[e.swing_id, "available_at"]) > start
                   or breach_at(e.swing_id) != pd.Timestamp(e.event_at))
    v["INV-2 classified reference eligible at s(N) and broken at N"] = bad

    by_role = roles.set_index("role_id")
    bad = 0
    for r in roles[roles["parent_role_id"].notna()].itertuples(index=False):
        anchor = swings.loc[by_role.loc[r.parent_role_id, "swing_id"]]
        bad += int(not pd.Timestamp(swings.loc[r.swing_id, "source_at"]) > pd.Timestamp(anchor["source_end_at"]))
    for r in roles[roles["role_kind"] == PROTECTION].itertuples(index=False):
        consumed = swings.loc[events_by_id.loc[r.parent_key, "swing_id"]]
        bad += int(not pd.Timestamp(swings.loc[r.swing_id, "source_at"]) > pd.Timestamp(consumed["source_end_at"]))
    v["INV-3 sequence spans strictly ordered"] = bad

    prot = roles[roles["role_kind"] == PROTECTION]
    prot_ids = set(prot["role_id"])
    prot_by_ep: dict[str, list] = {}
    for r in prot.sort_values("assigned_at").itertuples(index=False):
        exit_at = pd.Timestamp(exits.loc[r.role_id, "transition_at"]) if r.role_id in exits.index else None
        prot_by_ep.setdefault(r.episode_id, []).append((pd.Timestamp(r.assigned_at), exit_at, r))
    bad4 = bad14 = 0
    for items in prot_by_ep.values():
        for i, (_, exit_at, r) in enumerate(items):
            if exit_at is None:
                continue
            state = exits.loc[r.role_id, "new_state"]
            bad14 += int(state not in (REPLACED, BROKEN, ENDED))
            if state == REPLACED:
                nxt = items[i + 1][2] if i + 1 < len(items) and items[i + 1][0] == exit_at else None
                bull = r.direction_context == BULLISH
                bad4 += int(nxt is None or not ((nxt.swing_price_ticks > r.swing_price_ticks) if bull
                                                else (nxt.swing_price_ticks < r.swing_price_ticks)))
    prot_exit_at = Counter(pd.Timestamp(t) for t, e in zip(rt["transition_at"], rt["entity_id"]) if e in prot_ids)
    prot_new_at = Counter(pd.Timestamp(t) for t in prot["assigned_at"])
    for e in events[events["kind"] == BOS].itertuples(index=False):
        at = pd.Timestamp(e.event_at)
        bad14 += int(prot_exit_at.get(at, 0) != prot_new_at.get(at, 0))
    v["INV-4 protection strictly tightened on replacement"] = bad4

    bad5 = bad6 = 0
    for t in roles[roles["role_kind"] == TARGET].itertuples(index=False):
        items = prot_by_ep.get(t.episode_id, [])
        at = pd.Timestamp(t.assigned_at)
        i = bisect.bisect_right([item[0] for item in items], at) - 1
        if i < 0 or (items[i][1] is not None and items[i][1] <= at):
            bad5 += 1
            continue
        p = items[i][2]
        bull = t.direction_context == BULLISH
        bad5 += int(not ((p.swing_price_ticks < t.swing_price_ticks) if bull
                         else (p.swing_price_ticks > t.swing_price_ticks)))
        base = swings.loc[events_by_id.loc[t.parent_key, "swing_id"]]
        base_ticks = int(round(float(base["price"]) / tick))
        bad6 += int(not ((t.swing_price_ticks > base_ticks) if bull else (t.swing_price_ticks < base_ticks)))
        bad6 += int(not pd.Timestamp(swings.loc[t.swing_id, "source_at"]) > pd.Timestamp(base["source_end_at"]))
    v["INV-5 protection beyond-side of target while both active"] = bad5
    v["INV-6 targets strictly progressive versus baseline"] = bad6

    bad = 0
    for _, group in roles.groupby("episode_id"):
        changes = []
        for r in group.itertuples(index=False):
            changes.append((pd.Timestamp(r.assigned_at), 1, r.role_kind))
            if r.role_id in exits.index:
                changes.append((pd.Timestamp(exits.loc[r.role_id, "transition_at"]), 0, r.role_kind))
        changes.sort()
        live: Counter = Counter()
        for i, (at, created, kind) in enumerate(changes):
            live[kind] += 1 if created else -1
            if i + 1 == len(changes) or changes[i + 1][0] != at:
                bad += sum(1 for count in live.values() if count > 1)
    v["INV-7 active-role uniqueness"] = bad

    bad = 0
    for b in run.swing_breaks.itertuples(index=False):
        bad += int(pd.Timestamp(b.bar_start) < pd.Timestamp(swings.loc[b.swing_id, "available_at"]))
    v["INV-8 no swing_breaks row with bar_start < available_at"] = bad

    bad = int((pd.to_datetime(roles["assigned_at"], utc=True)
               < pd.to_datetime(roles["swing_available_at"], utc=True)).sum())
    ep_first = dict(zip(run.episodes["episode_id"], pd.to_datetime(run.episodes["first_bar_end"], utc=True)))
    bad += int((pd.to_datetime(events["event_at"], utc=True) < events["episode_id"].map(ep_first)).sum())
    bad += int((pd.to_datetime(roles["assigned_at"], utc=True) < roles["episode_id"].map(ep_first)).sum())
    v["INV-9 outputs available no earlier than inputs"] = bad

    contract_of = dict(zip(run.episodes["episode_id"], run.episodes["contract"]))
    role_contract = dict(zip(roles["role_id"], roles["contract"]))
    bad = int((roles["episode_id"].map(contract_of) != roles["contract"]).sum())
    bad += int((events["episode_id"].map(contract_of) != events["contract"]).sum())
    bad += int((roles["swing_id"].map(swings["contract"]) != roles["contract"]).sum())
    bad += int((rt["entity_id"].map(role_contract) != rt["contract"]).sum())
    bad += int((dt["entity_id"].map(contract_of) != dt["contract"]).sum())
    v["INV-10 no output or reference crosses a contract"] = bad

    bad = 0
    try:
        validate_transitions(dt.drop(columns=["run_id"]), _spec(run, direction_namespace), run.direction_entities)
        validate_transitions(rt.drop(columns=["run_id"]), _spec(run, role_namespace), run.role_entities)
    except Exception:  # noqa: BLE001 - any contract failure is a violation
        bad += 1
    assigned = dict(zip(roles["role_id"], roles["assigned_at"]))
    bad += sum(int(pd.Timestamp(assigned[t.entity_id]) >= pd.Timestamp(t.transition_at))
               for t in rt.itertuples(index=False))
    v["INV-11 M7A validity; no create-and-exit at one instant"] = bad

    bad = 0
    for r in roles.itertuples(index=False):
        s = swings.loc[r.swing_id]
        bad += int(round(float(s["price"]) / tick) != r.swing_price_ticks
                   or pd.Timestamp(s["available_at"]) != pd.Timestamp(r.swing_available_at)
                   or pd.Timestamp(s["source_at"]) != pd.Timestamp(r.swing_source_at)
                   or pd.Timestamp(s["source_end_at"]) != pd.Timestamp(r.swing_source_end_at))
    v["INV-12 pinned facts equal input facts"] = bad

    v["INV-13 RESET onsets follow the schedule rule and are <= replay_cutoff"] = _check_resets(
        run, session_spec, cutoff, tf, source_interval)
    v["INV-14 protection exits only REPLACED/BROKEN/ENDED; untouched by BOS without replacement"] = bad14
    v["INV-15 no role on a swing breached at or before assigned_at"] = sum(
        int((breach_at(r.swing_id) is not None and breach_at(r.swing_id) <= pd.Timestamp(r.assigned_at))
            or pd.Timestamp(swings.loc[r.swing_id, "available_at"]) > pd.Timestamp(r.assigned_at))
        for r in roles.itertuples(index=False))

    bad = 0
    resets = events[events["kind"] == RESET]
    bad += int(len(resets) - resets["reset_reason"].isin([DATA_GAP, CONTRACT_CHANGE]).sum())
    eps = run.episodes.sort_values("first_bar_end").reset_index(drop=True)
    reset_of = dict(zip(resets["episode_id"], zip(resets["reset_ref"], resets["reset_reason"])))
    for k, ep in eps.iterrows():
        if k == 0:
            bad += int(ep["opening_cause"] != DATA_START or ep["opening_ref"] is not None)
            continue
        prev = eps.iloc[k - 1]
        ref, reason = reset_of.get(prev["episode_id"], (None, None))
        bad += int(ep["opening_ref"] != ref or ep["previous_contract"] != prev["contract"])
        changed = ep["contract"] != prev["contract"]
        bad += int(bool(ep["opening_contract_changed"]) != changed)
        if changed:
            stamp = pd.Timestamp(ep["first_bar_end"]).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S")
            bad += int(not str(ep["opening_contract_change_ref"]).endswith(f"|{stamp}.000000000Z"))
        else:
            bad += int(ep["opening_contract_change_ref"] is not None)
        expected = DATA_GAP_REESTABLISHMENT if reason == DATA_GAP else CONTRACT_CHANGE_REESTABLISHMENT
        bad += int(ep["opening_cause"] != expected)
    v["INV-16 contract-boundary provenance (CB-1 / CB-2)"] = bad

    tf_spec = TimeframeSpec("1m", 1) if tf == "1m" else tf
    obs_cut = run.observations.loc[(pd.to_datetime(run.observations["bar_end"], utc=True) <= cutoff).to_numpy()]
    segments, brk_rows = continuity_segments(obs_cut, tf_spec, session_spec, source_interval=source_interval)
    bad = int(len(segments) != len(eps))
    if not bad:
        for seg, ep in zip(segments, eps.itertuples(index=False)):
            bad += int(pd.Timestamp(seg["bar_end"].iloc[0]) != pd.Timestamp(ep.first_bar_end))
        bad += int(len(brk_rows) != max(len(eps) - 1, 0))
        for k, row in enumerate(brk_rows.itertuples(index=False), start=1):
            bad += int(bool(row.contract_changed) != bool(eps.iloc[k]["opening_contract_changed"]))
    v["INV-17 adapter episodes and boundaries agree with continuity"] = bad

    return pd.DataFrame([{"timeframe": tf, "invariant": key, "violations": int(value)} for key, value in v.items()])


INVARIANT_NAMES = (
    "INV-1 no structure_anomalies rows",
    "INV-2 classified reference eligible at s(N) and broken at N",
    "INV-3 sequence spans strictly ordered",
    "INV-4 protection strictly tightened on replacement",
    "INV-5 protection beyond-side of target while both active",
    "INV-6 targets strictly progressive versus baseline",
    "INV-7 active-role uniqueness",
    "INV-8 no swing_breaks row with bar_start < available_at",
    "INV-9 outputs available no earlier than inputs",
    "INV-10 no output or reference crosses a contract",
    "INV-11 M7A validity; no create-and-exit at one instant",
    "INV-12 pinned facts equal input facts",
    "INV-13 RESET onsets follow the schedule rule and are <= replay_cutoff",
    "INV-14 protection exits only REPLACED/BROKEN/ENDED; untouched by BOS without replacement",
    "INV-15 no role on a swing breached at or before assigned_at",
    "INV-16 contract-boundary provenance (CB-1 / CB-2)",
    "INV-17 adapter episodes and boundaries agree with continuity",
)


def _zero_episode_invariants(run, session_spec, cutoff, tf, source_interval) -> pd.DataFrame:
    """No complete observation up to the cutoff: every structure output must be empty, and frozen continuity
    must agree that there is no segment and no break row."""
    outputs = (len(run.swings) + len(run.swing_breaks) + len(run.roles) + len(run.events) + len(run.anomalies)
               + len(run.direction_transitions) + len(run.role_transitions))
    tf_spec = TimeframeSpec("1m", 1) if tf == "1m" else tf
    obs_cut = run.observations.loc[(pd.to_datetime(run.observations["bar_end"], utc=True) <= cutoff).to_numpy()]
    segments, brk_rows = continuity_segments(obs_cut, tf_spec, session_spec, source_interval=source_interval)
    counts = {name: outputs for name in INVARIANT_NAMES}
    counts[INVARIANT_NAMES[0]] = len(run.anomalies)
    counts[INVARIANT_NAMES[-1]] = len(segments) + len(brk_rows)
    return pd.DataFrame([{"timeframe": tf, "invariant": key, "violations": int(value)} for key, value in counts.items()])


def _spec(run: MarketStructureRun, factory):
    sd = run.manifest["swing_definition"]
    definition = StructureDefinitionSpec(
        definition_version=run.manifest["definition_version"],
        break_definition_version=run.manifest["break_definition_version"],
        swing_definition=SwingDefinitionSpec(definition_version=sd[0], left_depth=sd[1], right_depth=sd[2]))
    return factory(definition)


def _check_resets(run, session_spec, cutoff, tf, source_interval) -> int:
    """Independent schedule walk (INV-13): each episode resets at the first missing / incomplete expected position
    after its first observation (DATA_GAP) or at the first complete observation of another contract
    (CONTRACT_CHANGE); no reset when neither occurs up to the cutoff."""
    resets = run.events[run.events["kind"] == RESET].set_index("episode_id")
    obs = run.observations.copy()
    obs["_end"] = pd.to_datetime(obs["bar_end"], utc=True)
    obs = obs[obs["_end"] <= cutoff]
    complete = set(obs.loc[obs["is_complete"].astype(bool), "_end"])
    contract_at = dict(zip(obs["_end"], obs["contract"]))
    tf_spec = TimeframeSpec("1m", 1) if tf == "1m" else tf
    first = min(obs["trading_date"])
    last = cutoff.tz_convert(session_spec.timezone).date() + timedelta(days=1)
    dates = [first + timedelta(days=k) for k in range((last - first).days + 1)]
    sched = expected_timeframe_schedule(dates, tf_spec, session_spec, source_interval=source_interval)
    sched_ends = sorted(e for e in pd.to_datetime(sched["bar_end"], utc=True) if e <= cutoff)
    bad = 0
    for ep in run.episodes.itertuples(index=False):
        i = bisect.bisect_left(sched_ends, pd.Timestamp(ep.first_bar_end))
        expected = None
        while i < len(sched_ends):
            end = sched_ends[i]
            if end not in complete:
                expected = (end, DATA_GAP)
                break
            if contract_at[end] != ep.contract:
                expected = (end, CONTRACT_CHANGE)
                break
            i += 1
        has = ep.episode_id in resets.index
        if expected is None:
            bad += int(has)
        elif not has:
            bad += 1
        else:
            row = resets.loc[ep.episode_id]
            bad += int(pd.Timestamp(row["event_at"]) != expected[0] or row["reset_reason"] != expected[1]
                       or pd.Timestamp(row["event_at"]) > cutoff)
    return bad
