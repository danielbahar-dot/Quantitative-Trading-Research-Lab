"""Order Block / Breaker / Mitigation engine (OB-I1 – OB-I3; D-153 – D-157).

Specification: ``docs/project/ORDER_BLOCK_BREAKER_MITIGATION_DESIGN.md`` rev 3 (§5 – §11, §13, §22).

Per timeframe and continuity segment (bullish shown; bearish mirrors every inequality and orientation):

Discovery (one episode per confirmed LOWER swing L, terminal source s = L's last span bar):
  source tests (body ≥ 4 ticks, then bearish colour) → window end e = source end of the first UPPER swing H with
  span start > s (inclusive), cut before a new LOWER swing L2 (start > s) → departure = first bullish FVG with
  s < C2 ≤ e → validation = first close > h[s] at a bar in (s, e] → ownership deadline for m = max(C2, validation
  bar): the first bar at which every left-qualified LOWER run starting in (s, m] and every left-qualified UPPER run
  in (s, m) is decided (confirmed or denied by the detector's own window rule) → admission at
  max(L, FVG, validation, deadline) unless a close < l[s] occurred in (s, admission]. Rejection only when
  knowable (H confirmed and every same-side candidate in (s, H] decided); waiting episodes end at a 1m reset.

Lifecycle (one block, persistent block_id; ``ict.block`` M7A entity):
  ORDINARY fails at the first close < lower after admission (x). Motif: B = L (pinned), A = latest UPPER swing
  ending before B starts, C = most extreme UPPER swing with span strictly inside (B, x), raid = any high > A.price
  on bars after B's span through x. C > A → BREAKER; C < A and no raid → MITIGATION; else FAILED_FINAL (reason).
  Successor availability = max(x, resolution of every C candidate = bar x − 1 + R); FAILED_AWAITING_CLASSIFICATION
  when later (unreachable at R = 1); closes in (x, availability] beyond the successor's far bound →
  QUALIFIED_BUT_INVALID_BEFORE_ADMISSION. Successor (reversed direction, inherited interval) retires on its own
  strict far-boundary close. A 1m DATA_GAP / CONTRACT_CHANGE reset ends every live or waiting state.

Interactions: canonical 1m bars with bar_start ≥ stage availability and bar_end ≤ stage end (no formation or
conversion-bar retest); visits, first events, depth / adverse-excursion versions, gap-beyond evidence.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
import pandas as pd

from src.fvg.formation import bar_ref, ctime, raw_basis, sha_id
from src.ict_blocks.inputs import MinuteTape, ObInputError, TfObs, segment_episode
from src.state.contract import SPECIFIC, SourceRef, StateNamespaceSpec, transition_id, validate_transitions

OB_DEFINITION_VERSION = "ob-v1"
SELECTION_POLICY = "terminal-source-v1"
BODY_MIN_TICKS = 4
BULLISH, BEARISH = "BULLISH", "BEARISH"
LOWER, UPPER = "LOWER", "UPPER"
ORDINARY, BREAKER, MITIGATION = "ORDINARY", "BREAKER", "MITIGATION"
FAILED_AWAITING, FAILED_FINAL, RETIRED = "FAILED_AWAITING_CLASSIFICATION", "FAILED_FINAL", "RETIRED"
TERMINATED, PENDING = "TERMINATED_DATA_GAP", "PENDING_ADJUSTMENT"
ADMITTED, REJECTED, SUPERSEDED, WAITING, EP_TERMINATED = "ADMITTED", "REJECTED", "SUPERSEDED", "WAITING_FOR_DEPARTURE", "TERMINATED"
DATA_GAP, CONTRACT_CHANGE = "DATA_GAP", "CONTRACT_CHANGE"
NS_BLOCK = "ict.block"

REGION_COLUMNS = ("source_region_id", "timeframe", "contract", "source_ref", "source_bar_start", "source_bar_end",
                  "source_open_ticks", "source_high_ticks", "source_low_ticks", "source_close_ticks", "body_ticks",
                  "lower_ticks", "upper_ticks", "zone_midpoint_half_ticks", "source_body_midpoint_half_ticks",
                  "lower", "upper", "zone_midpoint", "source_body_midpoint", "width_ticks", "selection_policy",
                  "basis_id")
EPISODE_COLUMNS = ("episode_id", "timeframe", "direction", "anchor_swing_id", "anchor_source_ref", "source_ref",
                   "opened_at", "status", "decided_at", "reason", "window_swing_id", "superseded_by_swing_id",
                   "formation_fvg_id", "validation_close_at", "ownership_deadline_at", "block_id", "left_depth",
                   "right_depth", "contract")
EVIDENCE_COLUMNS = ("episode_id", "kind", "ref", "observed_at", "known_at", "accepted", "reason")
BLOCK_COLUMNS = ("block_id", "source_region_id", "episode_id", "anchor_swing_id", "timeframe", "ordinary_direction",
                 "ordinary_available_at", "formation_fvg_id", "formation_fvg_c2_end", "validation_close_at",
                 "swing_definition", "left_depth", "right_depth", "definition_version", "contract", "basis_id")
STAGE_COLUMNS = ("stage_id", "block_id", "stage_kind", "direction", "predecessor_stage_id", "available_at",
                 "ended_at", "end_reason", "motif_id", "far_boundary", "timeframe", "contract")
LIFECYCLE_COLUMNS = ("block_id", "from_state", "to_state", "at", "reason", "from_stage_id", "to_stage_id",
                     "trigger_ref", "observed_at")
MOTIF_COLUMNS = ("motif_id", "block_id", "parent_stage_id", "successor_direction", "a_swing_id", "a_price_ticks",
                 "b_swing_id", "b_price_ticks", "c_swing_id", "c_price_ticks", "c_candidate_ids",
                 "raid_observed", "first_raid_at", "break_observed_at", "resolved_at", "classification",
                 "successor_available_at", "outcome", "reason")
VISIT_COLUMNS = ("visit_id", "stage_id", "block_id", "visit_seq", "started_at", "ended_at", "bars", "penetrated",
                 "midpoint_observed", "distal_observed", "full_span_observed", "max_interior_depth_ticks",
                 "max_adverse_excursion_ticks")
INTERACTION_COLUMNS = ("event_id", "stage_id", "block_id", "kind", "at", "bar_ref", "bar_high_ticks", "bar_low_ticks",
                       "visit_id")
DEPTH_COLUMNS = ("stage_id", "block_id", "at", "max_interior_depth_ticks", "max_adverse_excursion_ticks")
WARNING_COLUMNS = ("at", "reason", "reset_ref", "terminated_blocks", "terminated_episodes", "contract")
PENDING_COLUMNS = ("block_id", "stage_id", "contract", "comparison_scope", "reason", "since_at")
TRANSITION_BASE = ["transition_id", "namespace", "entity_id", "previous_state", "new_state", "transition_at",
                   "transition_seq_domain", "transition_seq", "available_at", "available_seq_domain", "available_seq",
                   "instrument_id", "contract_scope", "contract", "definition_version", "trigger_ref", "source_refs",
                   "reason_code"]
SUCCESSOR_REASON = {BREAKER: "BREAKER_MOTIF", MITIGATION: "MITIGATION_MOTIF"}


def block_namespace() -> StateNamespaceSpec:
    live = (ORDINARY, FAILED_AWAITING, BREAKER, MITIGATION)
    edges = {(ORDINARY, BREAKER), (ORDINARY, MITIGATION), (ORDINARY, FAILED_AWAITING), (ORDINARY, FAILED_FINAL),
             (FAILED_AWAITING, BREAKER), (FAILED_AWAITING, MITIGATION), (FAILED_AWAITING, FAILED_FINAL),
             (BREAKER, RETIRED), (MITIGATION, RETIRED)}
    edges |= {(s, TERMINATED) for s in live} | {(s, PENDING) for s in live}
    return StateNamespaceSpec(namespace=NS_BLOCK, entity_kind="ict_block", initial_state=ORDINARY,
                              allowed_states=(ORDINARY, FAILED_AWAITING, BREAKER, MITIGATION, FAILED_FINAL, RETIRED,
                                              TERMINATED, PENDING),
                              allowed_transitions=frozenset(edges), definition_version=OB_DEFINITION_VERSION,
                              terminal_states=(FAILED_FINAL, RETIRED, TERMINATED, PENDING))


def _opp(d):
    return BEARISH if d == BULLISH else BULLISH


def _ts(ns):
    return None if ns is None else pd.Timestamp(int(ns), tz="UTC")


@dataclass
class ObConfig:
    instrument_id: str
    tick: Decimal
    left_depth: int = 1
    right_depth: int = 1
    swing_definition: str = "swing-pivot-v1"


@dataclass
class EngineResult:
    regions: pd.DataFrame
    episodes: pd.DataFrame
    evidence: pd.DataFrame
    blocks: pd.DataFrame
    stages: pd.DataFrame
    lifecycle: pd.DataFrame
    motifs: pd.DataFrame
    visits: pd.DataFrame
    interactions: pd.DataFrame
    depth_versions: pd.DataFrame
    transitions: pd.DataFrame
    entities: pd.DataFrame
    warnings: pd.DataFrame
    pending: pd.DataFrame
    counters: dict = field(default_factory=dict)


def frame(rows: list, columns: tuple) -> pd.DataFrame:
    out = pd.DataFrame(rows, columns=list(columns))
    for c in out.columns:
        if c.endswith("_at") or c.endswith("_bar_start") or c.endswith("_bar_end") or c == "formation_fvg_c2_end":
            out[c] = pd.to_datetime(out[c], utc=True)
    return out


# ---------------------------------------------------------------------------
# Discovery and ordinary formation (per segment and direction)
# ---------------------------------------------------------------------------


def _run_end(vals: np.ndarray, m: int) -> int:
    """Last position of the maximal equal-value run containing ``m``."""
    v, k = int(vals[m]), m
    while k + 1 < len(vals) and int(vals[k + 1]) == v:
        k += 1
    return k


def _decision(signed: np.ndarray, r0: int, r1: int, L: int, R: int):
    """Bar at which the swing status of the maximal equal run [r0, r1] is decided (detector semantics: only a
    strictly more extreme value inside the L / R windows fails it).  ``None`` when the run can never be a swing
    (not left-qualified: decided as soon as it starts); a value > last bar means still undecided in the data."""
    h = int(signed[r0])
    if r0 - L < 0 or int(signed[r0 - L:r0].max()) > h:
        return None
    for j in range(1, R + 1):
        k = r1 + j
        if k >= len(signed) or int(signed[k]) > h:
            return k                    # beyond the data (undecided) or denied at k
    return r1 + R                       # confirmed at r1 + R


def _candidate_runs(signed: np.ndarray, first: int, last: int):
    """Maximal equal runs (r0, r1) with r0 in [first, last]."""
    k = first
    while k <= last:
        r1 = _run_end(signed, k)
        yield k, r1
        k = r1 + 1


def ownership_deadline(same: np.ndarray, opp: np.ndarray, s: int, m: int, L: int, R: int) -> int:
    """First bar at which window membership of evidence at bar m is knowable: every same-side run starting in
    (s, m] (a new same-side swing there would end the window before m) and every opposite run starting after s
    and ending before m (it would close the window before m) is decided.  Only left-qualified runs can wait."""
    deadline = m
    for r0, r1 in _candidate_runs(same, s + 1, m):
        d = _decision(same, r0, r1, L, R)
        if d is not None:
            deadline = max(deadline, d)
    for r0, r1 in _candidate_runs(opp, s + 1, m - 1):
        if r1 <= m - 1:
            d = _decision(opp, r0, r1, L, R)
            if d is not None:
                deadline = max(deadline, d)
    return deadline


def window_close_decision(same: np.ndarray, s: int, hb: int, L: int, R: int) -> int:
    """First bar at which a window ending at the opposite swing's last bar hb is final: hb's swing is confirmed
    (hb + R) and no same-side swing can still start in (s, hb]."""
    dec = hb + R
    for r0, r1 in _candidate_runs(same, s + 1, hb):
        d = _decision(same, r0, r1, L, R)
        if d is not None:
            dec = max(dec, d)
    return dec


def discover(tf: str, obs: TfObs, swings: dict, fvgs: dict, tape: MinuteTape, cfg: ObConfig, out: dict) -> list:
    """Episodes and ordinary admissions; returns the admitted block specs for the lifecycle stage."""
    R = cfg.right_depth
    admitted = []
    used_sources = set()
    for si, seg in enumerate(obs.segments):
        o, h, l, c, end = seg["o"], seg["h"], seg["l"], seg["c"], seg["end"]
        n = len(end)
        ep = segment_episode(tape, obs, si)
        sws = swings.get(si, [])
        lows = [s for s in sws if s.orientation == LOWER]
        highs = [s for s in sws if s.orientation == UPPER]
        seg_fvgs = fvgs.get(si, [])
        for direction, anchors, opps in ((BULLISH, lows, highs), (BEARISH, highs, lows)):
            opp_a = [s.a for s in opps]
            dir_fvgs = [f for f in seg_fvgs if f.direction == direction]
            fvg_c2 = [f.c2 for f in dir_fvgs]
            same_signed = -l if direction == BULLISH else h        # larger = more extreme for the anchor side
            opp_signed = h if direction == BULLISH else -l
            Ld = cfg.left_depth
            for idx, L in enumerate(anchors):
                out["counters"]["source_searches"] += 1
                s = L.b
                src_ref = bar_ref(cfg.instrument_id, seg["contract"], tf, int(end[s]))
                anchor_ref = bar_ref(cfg.instrument_id, seg["contract"], tf, int(end[L.a]), int(end[L.b]))
                eid = sha_id("obe_", [OB_DEFINITION_VERSION, L.swing_id, direction, cfg.left_depth, cfg.right_depth])
                row = {"episode_id": eid, "timeframe": tf, "direction": direction, "anchor_swing_id": L.swing_id,
                       "anchor_source_ref": anchor_ref, "source_ref": src_ref, "opened_at": _ts(L.available_ns),
                       "status": WAITING, "decided_at": None, "reason": None, "window_swing_id": None,
                       "superseded_by_swing_id": None, "formation_fvg_id": None, "validation_close_at": None,
                       "ownership_deadline_at": None, "block_id": None, "left_depth": cfg.left_depth,
                       "right_depth": cfg.right_depth, "contract": seg["contract"]}
                out["episodes"].append(row)
                body = abs(int(c[s]) - int(o[s]))
                colour_ok = c[s] < o[s] if direction == BULLISH else c[s] > o[s]
                if body < BODY_MIN_TICKS or not colour_ok:
                    row.update(status=REJECTED, decided_at=_ts(L.available_ns),
                               reason="SOURCE_BODY_LT_4_TICKS" if body < BODY_MIN_TICKS else "SOURCE_DIRECTION_MISMATCH")
                    out["evidence"].append((eid, "SOURCE", src_ref, _ts(end[s]), _ts(L.available_ns), False, row["reason"]))
                    continue
                out["evidence"].append((eid, "SOURCE", src_ref, _ts(end[s]), _ts(L.available_ns), True, None))
                if (direction, si, s) in used_sources:            # guard: one block per source candle
                    row.update(status=REJECTED, decided_at=_ts(L.available_ns), reason="SOURCE_ALREADY_USED")
                    continue
                # window end: inclusive source end of the first opposite swing after s; before a new same-side swing
                j = bisect_right(opp_a, s)
                H = opps[j] if j < len(opps) else None
                L2 = anchors[idx + 1] if idx + 1 < len(anchors) else None
                e, boundary, boundary_kind = n - 1, None, None
                if H is not None:
                    e, boundary, boundary_kind = H.b, H, "WINDOW"
                if L2 is not None and L2.a - 1 < e:
                    e, boundary, boundary_kind = L2.a - 1, L2, "SUPERSEDE"
                # departure FVG: first by C2 with s < C2 <= e
                k = bisect_right(fvg_c2, s)
                fvg = dir_fvgs[k] if k < len(dir_fvgs) and dir_fvgs[k].c2 <= e else None
                # validation close in (s, e]
                far_wick = int(h[s]) if direction == BULLISH else int(l[s])
                seg_c = c[s + 1:e + 1]
                hit = np.flatnonzero(seg_c > far_wick if direction == BULLISH else seg_c < far_wick)
                v = s + 1 + int(hit[0]) if len(hit) else None
                # evidence is reported when its window ownership is knowable, and never before its episode exists
                # (the anchor swing's confirmation, bar b + R)
                def known(own, m):
                    k_ = max(own, L.b + R, ownership_deadline(same_signed, opp_signed, s, m, Ld, R))
                    return k_ if k_ <= n - 1 else None
                kf = known(fvg.c2 + 1, fvg.c2) if fvg is not None else None
                kv = known(v, v) if v is not None else None
                if kf is not None:
                    out["evidence"].append((eid, "DEPARTURE_FVG", fvg.zone_id, _ts(end[fvg.c2]), _ts(end[kf]), True, None))
                if kv is not None:
                    out["evidence"].append((eid, "VALIDATION_CLOSE", bar_ref(cfg.instrument_id, seg["contract"], tf,
                                                                            int(end[v])), _ts(end[v]), _ts(end[kv]), True, None))
                if fvg is not None and v is not None:
                    m = max(fvg.c2, v)
                    deadline = ownership_deadline(same_signed, opp_signed, s, m, Ld, R)
                    adm = max(L.b + R, fvg.c2 + 1, v, deadline)
                    if adm <= n - 1:
                        row.update(formation_fvg_id=fvg.zone_id, validation_close_at=_ts(end[v]),
                                   ownership_deadline_at=_ts(end[min(deadline, n - 1)]))
                        lower, upper = ((int(l[s]), int(o[s])) if direction == BULLISH else (int(o[s]), int(h[s])))
                        adverse = c[s + 1:adm + 1] < lower if direction == BULLISH else c[s + 1:adm + 1] > upper
                        if adverse.any():
                            row.update(status=REJECTED, decided_at=_ts(end[adm]), reason="ALREADY_INVALID_BEFORE_ADMISSION")
                            continue
                        used_sources.add((direction, si, s))
                        row.update(status=ADMITTED, decided_at=_ts(end[adm]))
                        out["counters"]["ordinary_admissions"] += 1
                        admitted.append({"episode": row, "anchor": L, "seg": si, "s": s, "adm": adm, "fvg": fvg, "v": v,
                                         "direction": direction, "lower": lower, "upper": upper, "tf": tf})
                        continue
                    complete = True          # evidence present; admission not yet knowable inside this segment
                else:
                    complete = False
                # not admitted (yet): decide only when knowable; complete evidence is never turned into a rejection
                # the window end is knowable once its boundary swing is confirmed and no same-side swing can still
                # start at or before it (the same-side run containing H's last bar has resolved)
                dec = None
                if boundary_kind == "SUPERSEDE":
                    dec = boundary.b + R
                elif boundary_kind == "WINDOW":
                    dec = window_close_decision(same_signed, s, boundary.b, Ld, R)
                if not complete and dec is not None and dec <= n - 1:
                    row["window_swing_id" if boundary_kind == "WINDOW" else "superseded_by_swing_id"] = boundary.swing_id
                    if boundary_kind == "SUPERSEDE":
                        row.update(status=SUPERSEDED, decided_at=_ts(end[dec]), reason="NEW_SAME_SIDE_SWING")
                    else:
                        row.update(status=REJECTED, decided_at=_ts(end[dec]),
                                   reason="NO_DEPARTURE_FVG_IN_WINDOW" if fvg is None else "NOT_VALIDATED_IN_WINDOW")
                elif ep.reset_at is not None:
                    row.update(status=EP_TERMINATED, decided_at=_ts(ep.reset_at), reason=ep.reset_reason)
                    out["reset_episodes"][ep.index] = out["reset_episodes"].get(ep.index, 0) + 1
    return admitted


# ---------------------------------------------------------------------------
# Lifecycle and parent-pinned motifs
# ---------------------------------------------------------------------------


def lifecycle(spec: dict, obs: TfObs, swings: dict, tape: MinuteTape, cfg: ObConfig, out: dict) -> None:
    tf, si, s, adm = spec["tf"], spec["seg"], spec["s"], spec["adm"]
    seg = obs.segments[si]
    o, h, l, c, end, start = seg["o"], seg["h"], seg["l"], seg["c"], seg["end"], seg["start"]
    n = len(end)
    R = cfg.right_depth
    d0, lower, upper = spec["direction"], spec["lower"], spec["upper"]
    ep = segment_episode(tape, obs, si)
    contract, basis = seg["contract"], raw_basis(seg["contract"])
    src_ref = spec["episode"]["source_ref"]
    region_id = sha_id("obr_", [cfg.instrument_id, contract, tf, src_ref, SELECTION_POLICY])
    block_id = sha_id("ob_", [region_id, d0, cfg.swing_definition, cfg.left_depth, cfg.right_depth,
                              OB_DEFINITION_VERSION, basis])
    spec["episode"]["block_id"] = block_id
    tick = cfg.tick
    price = lambda t: float(Decimal(int(t)) * tick)  # noqa: E731
    out["regions"].append({
        "source_region_id": region_id, "timeframe": tf, "contract": contract, "source_ref": src_ref,
        "source_bar_start": _ts(start[s]), "source_bar_end": _ts(end[s]), "source_open_ticks": int(o[s]),
        "source_high_ticks": int(h[s]), "source_low_ticks": int(l[s]), "source_close_ticks": int(c[s]),
        "body_ticks": abs(int(c[s]) - int(o[s])), "lower_ticks": lower, "upper_ticks": upper,
        "zone_midpoint_half_ticks": lower + upper, "source_body_midpoint_half_ticks": int(o[s]) + int(c[s]),
        "lower": price(lower), "upper": price(upper), "zone_midpoint": float(Decimal(lower + upper) * tick / 2),
        "source_body_midpoint": float(Decimal(int(o[s]) + int(c[s])) * tick / 2), "width_ticks": upper - lower,
        "selection_policy": SELECTION_POLICY, "basis_id": basis})
    fvg = spec["fvg"]
    out["blocks"].append({
        "block_id": block_id, "source_region_id": region_id, "episode_id": spec["episode"]["episode_id"],
        "anchor_swing_id": spec["anchor"].swing_id, "timeframe": tf, "ordinary_direction": d0,
        "ordinary_available_at": _ts(end[adm]), "formation_fvg_id": fvg.zone_id, "formation_fvg_c2_end": _ts(end[fvg.c2]),
        "validation_close_at": _ts(end[spec["v"]]), "swing_definition": cfg.swing_definition,
        "left_depth": cfg.left_depth, "right_depth": cfg.right_depth, "definition_version": OB_DEFINITION_VERSION,
        "contract": contract, "basis_id": basis})
    out["entities"].append({"entity_id": block_id, "available_at": _ts(end[adm]), "valid_from": pd.NaT,
                            "valid_until": pd.NaT, "instrument_id": cfg.instrument_id, "contract_scope": SPECIFIC,
                            "contract": contract})
    ord_stage = sha_id("obs_", [block_id, ORDINARY])
    stages = [{"stage_id": ord_stage, "block_id": block_id, "stage_kind": ORDINARY, "direction": d0,
               "predecessor_stage_id": None, "available_at": _ts(end[adm]), "ended_at": None, "end_reason": None,
               "motif_id": None, "far_boundary": "LOWER" if d0 == BULLISH else "UPPER", "timeframe": tf,
               "contract": contract}]

    def change(frm, to, at_ns, reason, from_stage, to_stage, trigger, observed_ns=None):
        out["lifecycle"].append({"block_id": block_id, "from_state": frm, "to_state": to, "at": _ts(at_ns),
                                 "reason": reason, "from_stage_id": from_stage, "to_stage_id": to_stage,
                                 "trigger_ref": trigger, "observed_at": _ts(observed_ns if observed_ns is not None else at_ns)})

    def reset(state, stage_id):
        """End the live / waiting state at the 1m episode reset (if any)."""
        if ep.reset_at is None:
            return
        kind = TERMINATED if ep.reset_reason == DATA_GAP else PENDING
        if stage_id is not None:
            for st in stages:
                if st["stage_id"] == stage_id:
                    st.update(ended_at=_ts(ep.reset_at), end_reason=kind)
            if kind == PENDING:
                out["pending"].append({"block_id": block_id, "stage_id": stage_id, "contract": contract,
                                       "comparison_scope": "CROSS_CONTRACT_RAW", "reason": CONTRACT_CHANGE,
                                       "since_at": _ts(ep.reset_at)})
        change(state, kind, ep.reset_at, ep.reset_reason, stage_id, None, ep.reset_ref)
        out["reset_blocks"][ep.index] = out["reset_blocks"].get(ep.index, 0) + 1

    beyond = (c < lower) if d0 == BULLISH else (c > upper)
    idx = np.flatnonzero(beyond[adm + 1:])
    if not len(idx):
        reset(ORDINARY, ord_stage)
        out["stages"].extend(stages)
        return
    x = adm + 1 + int(idx[0])
    x_ref = bar_ref(cfg.instrument_id, contract, tf, int(end[x]))
    stages[0].update(ended_at=_ts(end[x]), end_reason="ORDINARY_FAILED")     # known at the break itself
    out["counters"]["ordinary_failures"] += 1
    # motif (parent-pinned B)
    d1 = _opp(d0)
    B = spec["anchor"]
    opp_or = UPPER if d0 == BULLISH else LOWER
    sws = [sw for sw in swings.get(si, []) if sw.orientation == opp_or]
    prior = [sw for sw in sws if sw.b < B.a]
    A = prior[-1] if prior else None
    cands = [sw for sw in sws if sw.a > B.b and sw.b < x]
    more = (lambda p, q: p > q) if d0 == BULLISH else (lambda p, q: p < q)
    C = None
    for sw in cands:
        if C is None or more(sw.price, C.price):
            C = sw
    resolve = max(x, x - 1 + R)
    raid_at = None
    if A is not None:
        ex = h[B.b + 1:x + 1] > A.price if d0 == BULLISH else l[B.b + 1:x + 1] < A.price
        r_idx = np.flatnonzero(ex)
        raid_at = B.b + 1 + int(r_idx[0]) if len(r_idx) else None
    if A is None:
        cls, reason = None, "NO_PRIOR_EXTREME"
    elif C is None:
        cls, reason = None, "NO_REVERSAL_SWING"
    elif more(C.price, A.price):
        cls, reason = BREAKER, None
    elif C.price == A.price:
        cls, reason = None, "EQUAL_EXTREME" if raid_at is None else "EQUAL_EXTREME_WITH_RAID"
    elif raid_at is None:
        cls, reason = MITIGATION, None
    else:
        cls, reason = None, "RAID_WITH_LESS_EXTREME_C"
    motif_id = sha_id("obm_", [block_id, x_ref])
    motif = {"motif_id": motif_id, "block_id": block_id, "parent_stage_id": ord_stage, "successor_direction": d1,
             "a_swing_id": None if A is None else A.swing_id, "a_price_ticks": None if A is None else A.price,
             "b_swing_id": B.swing_id, "b_price_ticks": B.price, "c_swing_id": None if C is None else C.swing_id,
             "c_price_ticks": None if C is None else C.price, "c_candidate_ids": tuple(sw.swing_id for sw in cands),
             "raid_observed": raid_at is not None, "first_raid_at": None if raid_at is None else _ts(end[raid_at]),
             "break_observed_at": _ts(end[x]), "resolved_at": None, "classification": cls,
             "successor_available_at": None, "outcome": None, "reason": reason}
    out["motifs"].append(motif)
    if resolve > n - 1:                       # resolution not knowable inside the segment
        change(ORDINARY, FAILED_AWAITING, end[x], "ORDINARY_FAILED", ord_stage, None, x_ref)
        motif.update(outcome=FAILED_AWAITING, classification=None, reason=None, c_swing_id=None, c_price_ticks=None,
                     c_candidate_ids=None)          # C candidates are not all known yet
        reset(FAILED_AWAITING, None)
        out["stages"].extend(stages)
        return
    motif["resolved_at"] = _ts(end[resolve])
    res_ref = bar_ref(cfg.instrument_id, contract, tf, int(end[resolve]))      # == x_ref when resolved at x
    state = ORDINARY
    if resolve > x:
        change(ORDINARY, FAILED_AWAITING, end[x], "ORDINARY_FAILED", ord_stage, None, x_ref)
        state = FAILED_AWAITING
    if cls is None:
        change(state, FAILED_FINAL, end[resolve], reason, ord_stage if state == ORDINARY else None, None, res_ref,
               observed_ns=end[x])
        motif["outcome"] = FAILED_FINAL
        out["stages"].extend(stages)
        return
    # successor must still be valid at its availability
    succ_beyond = (c > upper) if d1 == BEARISH else (c < lower)
    if resolve > x and succ_beyond[x + 1:resolve + 1].any():
        motif.update(outcome=FAILED_FINAL, reason="QUALIFIED_BUT_INVALID_BEFORE_ADMISSION")
        change(state, FAILED_FINAL, end[resolve], "QUALIFIED_BUT_INVALID_BEFORE_ADMISSION", None, None, res_ref,
               observed_ns=end[x])
        out["stages"].extend(stages)
        return
    succ_stage = sha_id("obs_", [block_id, cls])
    motif.update(successor_available_at=_ts(end[resolve]), outcome=cls)
    stages.append({"stage_id": succ_stage, "block_id": block_id, "stage_kind": cls, "direction": d1,
                   "predecessor_stage_id": ord_stage, "available_at": _ts(end[resolve]), "ended_at": None,
                   "end_reason": None, "motif_id": motif_id, "far_boundary": "UPPER" if d1 == BEARISH else "LOWER",
                   "timeframe": tf, "contract": contract})
    change(state, cls, end[resolve], SUCCESSOR_REASON[cls], ord_stage if state == ORDINARY else None, succ_stage,
           res_ref, observed_ns=end[x])
    out["counters"]["successor_admissions"] += 1
    r_idx = np.flatnonzero(succ_beyond[resolve + 1:])
    if not len(r_idx):
        reset(cls, succ_stage)
        out["stages"].extend(stages)
        return
    k = resolve + 1 + int(r_idx[0])
    stages[1].update(ended_at=_ts(end[k]), end_reason=RETIRED)
    change(cls, RETIRED, end[k], "SUCCESSOR_CLOSE_BEYOND", succ_stage, None,
           bar_ref(cfg.instrument_id, contract, tf, int(end[k])))
    out["stages"].extend(stages)


# ---------------------------------------------------------------------------
# 1m interactions per stage
# ---------------------------------------------------------------------------


def interactions(stage: dict, region: dict, tape: MinuteTape, cfg: ObConfig, out: dict) -> None:
    a_ns = stage["available_at"].value
    loc = None
    ep = None
    for e in tape.episodes:                      # the stage's 1m episode: the one containing its availability
        if len(e.end) and e.end[0] <= a_ns <= e.end[-1]:
            ep = e
            break
    if ep is None:
        raise ObInputError(f"stage {stage['stage_id']}: availability outside the 1m tape")
    lo, up = region["lower_ticks"], region["upper_ticks"]
    mid2, width = lo + up, up - lo
    first = int(np.searchsorted(ep.start, a_ns, side="left"))
    last = len(ep.end) if pd.isna(stage["ended_at"]) else int(np.searchsorted(ep.end, stage["ended_at"].value, side="right"))
    if last <= first:
        return
    L, H = ep.l[first:last], ep.h[first:last]
    starts, ends = ep.start[first:last], ep.end[first:last]
    bull = stage["direction"] == BULLISH
    touch = (H >= lo) & (L <= up)
    pen = (H > lo) & (L < up)
    midp = (2 * L <= mid2) & (2 * H >= mid2)
    far = lo if bull else up
    distal = (L <= far) & (H >= far)
    full = (L <= lo) & (H >= up)
    depth = np.where(touch, np.clip(up - np.maximum(L, lo) if bull else np.minimum(H, up) - lo, 0, width), 0)
    adverse = np.maximum(lo - L, 0) if bull else np.maximum(H - up, 0)
    wholly_beyond = (H < lo) if bull else (L > up)
    approach = (L > up) if bull else (H < lo)
    sid, bid = stage["stage_id"], stage["block_id"]
    contig = np.r_[False, starts[1:] == ends[:-1]]
    new_visit = touch & ~(np.r_[False, touch[:-1]] & contig)
    visit_no = np.cumsum(new_visit)
    contract = ep.contract

    def ref(i):
        return bar_ref(cfg.instrument_id, contract, "1m", int(ends[i]))
    visit_ids = {}
    for vno in np.unique(visit_no[touch]):
        mask = touch & (visit_no == vno)
        ii = np.flatnonzero(mask)
        vid = sha_id("obv_", [sid, ctime(int(ends[ii[0]]))])
        visit_ids[int(vno)] = vid
        out["visits"].append((vid, sid, bid, int(vno), _ts(ends[ii[0]]), _ts(ends[ii[-1]]), len(ii), bool(pen[ii].any()),
                              bool(midp[ii].any()), bool(distal[ii].any()), bool(full[ii].any()), int(depth[ii].max()),
                              int(adverse[ii].max())))
    for kind, mask in (("FIRST_TOUCH", touch), ("FIRST_PENETRATION", pen), ("FIRST_MIDPOINT", midp),
                       ("FIRST_DISTAL", distal), ("FIRST_FULL_SPAN", full)):
        ii = np.flatnonzero(mask)
        if len(ii):
            i = int(ii[0])
            out["interactions"].append((sha_id("obi_", [sid, kind, ctime(int(ends[i]))]), sid, bid, kind, _ts(ends[i]),
                                        ref(i), int(H[i]), int(L[i]), visit_ids.get(int(visit_no[i])) if touch[i] else None))
    gap = wholly_beyond & np.r_[False, approach[:-1]]
    for i in np.flatnonzero(gap).tolist():
        out["interactions"].append((sha_id("obi_", [sid, "GAP_BEYOND_REGION", ctime(int(ends[i]))]), sid, bid,
                                    "GAP_BEYOND_REGION", _ts(ends[i]), ref(i), int(H[i]), int(L[i]), None))
    md, ma = np.maximum.accumulate(depth), np.maximum.accumulate(adverse)
    grew = np.r_[md[0] > 0 or ma[0] > 0, (md[1:] > md[:-1]) | (ma[1:] > ma[:-1])]
    for i in np.flatnonzero(grew).tolist():
        out["depth"].append((sid, bid, _ts(ends[i]), int(md[i]), int(ma[i])))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def run_engine(obs_by_tf: dict, swings_by_tf: dict, fvgs_by_tf: dict, tape: MinuteTape, cfg: ObConfig) -> EngineResult:
    out = {k: [] for k in ("episodes", "evidence", "regions", "blocks", "stages", "lifecycle", "motifs", "visits",
                           "interactions", "depth", "entities", "pending")}
    out["counters"] = {"source_searches": 0, "ordinary_admissions": 0, "ordinary_failures": 0, "successor_admissions": 0,
                       "fvg_facts_offered": sum(len(v) for per in fvgs_by_tf.values() for v in per.values())}
    out["reset_blocks"], out["reset_episodes"] = {}, {}
    specs = []
    for tf, obs in obs_by_tf.items():
        specs += discover(tf, obs, swings_by_tf.get(tf, {}), fvgs_by_tf.get(tf, {}), tape, cfg, out)
    for spec in specs:
        lifecycle(spec, obs_by_tf[spec["tf"]], swings_by_tf.get(spec["tf"], {}), tape, cfg, out)
    regions = {r["source_region_id"]: r for r in out["regions"]}
    block_region = {b["block_id"]: regions[b["source_region_id"]] for b in out["blocks"]}
    for st in out["stages"]:
        interactions(st, block_region[st["block_id"]], tape, cfg, out)
    # M7A lifecycle log (one entity per block)
    spec_ns = block_namespace()
    ents = pd.DataFrame(out["entities"], columns=["entity_id", "available_at", "valid_from", "valid_until",
                                                  "instrument_id", "contract_scope", "contract"])
    ents["available_at"] = pd.to_datetime(ents["available_at"], utc=True)
    for col in ("valid_from", "valid_until"):
        ents[col] = pd.Series([pd.NaT] * len(ents), dtype="datetime64[ns, UTC]")
    contract_of = {b["block_id"]: b["contract"] for b in out["blocks"]}
    tr_rows = []
    for ch in out["lifecycle"]:
        trig = ch["trigger_ref"] or SourceRef("OB_EVENT", f"{ch['reason']}|{ch['block_id']}|{ctime(ch['at'].value)}").canonical
        tr_rows.append({
            "transition_id": transition_id(namespace=NS_BLOCK, definition_version=OB_DEFINITION_VERSION,
                                           entity_id=ch["block_id"], previous_state=ch["from_state"],
                                           new_state=ch["to_state"], transition_at=ch["at"], trigger_ref=trig,
                                           source_refs=()),
            "namespace": NS_BLOCK, "entity_id": ch["block_id"], "previous_state": ch["from_state"],
            "new_state": ch["to_state"], "transition_at": ch["at"], "transition_seq_domain": None, "transition_seq": None,
            "available_at": ch["at"], "available_seq_domain": None, "available_seq": None,
            "instrument_id": cfg.instrument_id, "contract_scope": SPECIFIC, "contract": contract_of[ch["block_id"]],
            "definition_version": OB_DEFINITION_VERSION, "trigger_ref": trig, "source_refs": (), "reason_code": ch["reason"]})
    tr = pd.DataFrame(tr_rows, columns=TRANSITION_BASE)
    for col in ("transition_at", "available_at"):
        tr[col] = pd.to_datetime(tr[col], utc=True)
    if len(tr):
        tr = validate_transitions(tr, spec_ns, ents)
    warnings = []
    for ep in tape.episodes:
        if ep.reset_at is not None and ep.reset_reason == DATA_GAP:
            warnings.append({"at": _ts(ep.reset_at), "reason": DATA_GAP, "reset_ref": ep.reset_ref,
                             "terminated_blocks": out["reset_blocks"].get(ep.index, 0),
                             "terminated_episodes": out["reset_episodes"].get(ep.index, 0), "contract": ep.contract})
    order = lambda df, cols: df.sort_values(cols, kind="mergesort").reset_index(drop=True) if len(df) else df  # noqa: E731
    return EngineResult(
        regions=order(frame(out["regions"], REGION_COLUMNS), ["source_bar_end", "source_region_id"]),
        episodes=order(frame(out["episodes"], EPISODE_COLUMNS), ["opened_at", "episode_id"]),
        evidence=order(frame(out["evidence"], EVIDENCE_COLUMNS), ["known_at", "episode_id", "kind"]),
        blocks=order(frame(out["blocks"], BLOCK_COLUMNS), ["ordinary_available_at", "block_id"]),
        stages=order(frame(out["stages"], STAGE_COLUMNS), ["available_at", "stage_id"]),
        lifecycle=order(frame(out["lifecycle"], LIFECYCLE_COLUMNS), ["at", "block_id"]),
        motifs=order(frame(out["motifs"], MOTIF_COLUMNS), ["break_observed_at", "motif_id"]),
        visits=order(frame(out["visits"], VISIT_COLUMNS), ["started_at", "visit_id"]),
        interactions=order(frame(out["interactions"], INTERACTION_COLUMNS), ["at", "event_id"]),
        depth_versions=order(frame(out["depth"], DEPTH_COLUMNS), ["at", "stage_id"]),
        transitions=order(tr, ["transition_at", "entity_id"]), entities=order(ents, ["available_at", "entity_id"]),
        warnings=frame(warnings, WARNING_COLUMNS), pending=frame(out["pending"], PENDING_COLUMNS),
        counters=out["counters"])
