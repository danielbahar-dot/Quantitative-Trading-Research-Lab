"""First FVG in a directional swing leg (FVG-I4; D-151).

Specification: ``docs/project/FVG_IFVG_BPR_DESIGN.md`` rev 2.1 §3.10.

Inputs are the zone's own-timeframe ``swing_points`` from the frozen detector
under the explicit 2/2 reference definition, restricted to the zone's
continuity segment.  Bullish shown (bearish mirrors):

- anchor ``e(C2)``; last terminator ``U`` = last UPPER swing with
  ``source_end_at < e(C2)``; origin candidates = LOWER swings with
  ``source_at ≤ e(C2)`` after ``U``; origin = the lowest (earliest on ties);
- first = no earlier same-direction zone of the timeframe in the leg
  (earlier failed / converted zones still count: no promotion);
- ``association_available_at = max(formation, origin availability, D)``,
  where ``D = e(C2 + right_depth)`` iff the equal-extreme run ending at C2
  is a left-qualified swing candidate, else formation (exact 2/2 deadline);
- the marker is active in the FVG stage only, from the association instant;
  it ends ``CONVERTED`` / ``DATA_GAP`` / ``CONTRACT_CHANGE``; never on the
  IFVG; ``marker_never_active`` when the FVG stage ended at or before the
  association instant.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Any

import pandas as pd

from src.fvg.formation import BEARISH, BULLISH, FVG_DEFINITION_VERSION, frame, sha_id
from src.market_structure.swing import SwingDefinitionSpec
from src.market_structure.swing_detector import build_swing_points
from src.state.contract import (
    SPECIFIC,
    SourceRef,
    StateNamespaceSpec,
    canonical_time,
    transition_id,
    validate_transitions,
)

SWING_REFERENCE = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2)
LEG_RULE_VERSION = "fvg-first-leg-v1"
NS_MARKER = "fvg.first_marker"
ACTIVE, ENDED = "ACTIVE", "ENDED"
ASSOCIATION_COLUMNS = ("association_id", "zone_id", "timeframe", "direction", "leg_origin_swing_id",
                       "last_terminator_swing_id", "is_first", "formation_available_at", "association_available_at",
                       "deadline_rule", "marker_never_active", "reason", "contract", "leg_rule_version")


def marker_namespace() -> StateNamespaceSpec:
    return StateNamespaceSpec(namespace=NS_MARKER, entity_kind="fvg_first_marker", initial_state=ACTIVE,
                              allowed_states=(ACTIVE, ENDED), allowed_transitions=frozenset({(ACTIVE, ENDED)}),
                              definition_version=FVG_DEFINITION_VERSION, terminal_states=(ENDED,))


def swings_by_timeframe(source: pd.DataFrame, session_spec, timeframes, *, instrument_id: str,
                        replay_cutoff: pd.Timestamp, source_interval: Any = "1min") -> dict:
    out = {}
    for tf in timeframes:
        if source.empty:
            out[tf] = pd.DataFrame()
            continue
        sw = build_swing_points(source, tf, session_spec, SWING_REFERENCE, instrument_id=instrument_id,
                                source_interval=source_interval)
        out[tf] = sw.loc[(pd.to_datetime(sw["available_at"], utc=True) <= replay_cutoff).to_numpy()].reset_index(drop=True)
    return out


class _SegmentSwings:
    """Swings of one continuity segment, indexed for the §3.10 queries (bisection; no scans)."""

    def __init__(self, swings: list):
        self.by = {}
        for o in ("LOWER", "UPPER"):
            ss = sorted((s for s in swings if s["o"] == o), key=lambda s: (s["src"], s["id"]))
            self.by[o] = {"rows": ss, "src": [s["src"] for s in ss], "src_end": [s["src_end"] for s in ss]}

    def origin(self, direction: str, anchor: int):
        own, opp = ("LOWER", "UPPER") if direction == BULLISH else ("UPPER", "LOWER")
        o = self.by[opp]
        # same-orientation swings never overlap, so source_end_at is sorted with source_at
        k = bisect_left(o["src_end"], anchor)
        term = o["rows"][k - 1] if k > 0 else None
        since = term["src_end"] if term is not None else None
        w = self.by[own]
        lo = 0 if since is None else bisect_right(w["src"], since)
        hi = bisect_right(w["src"], anchor)
        if hi <= lo:
            return None, term
        cands = w["rows"][lo:hi]
        key = (lambda s: (s["px"], s["src"])) if own == "LOWER" else (lambda s: (-s["px"], s["src"]))
        return min(cands, key=key), term


def associate(zones: pd.DataFrame, tf_data: dict, swings: dict, exits: dict, *, instrument_id: str, tick):
    """Association rows and marker transitions for every zone whose association is knowable."""
    from src.market_structure.swing_breaks import price_ticks
    rows, markers, entities = [], [], []
    for tf, data in tf_data.items():
        z_tf = zones[zones["timeframe"] == tf]
        if z_tf.empty:
            continue
        pos = data.segment_of_end()
        sw = swings.get(tf)
        by_seg: dict = {}
        if sw is not None and len(sw):
            pxs = price_ticks(sw["price"].to_numpy(), tick)
            for r, p in zip(sw.itertuples(index=False), pxs):
                src = pd.Timestamp(r.source_at).tz_convert("UTC").value
                si = pos[src][0]
                by_seg.setdefault(si, []).append({
                    "id": r.swing_id, "o": r.orientation, "px": int(p), "src": src,
                    "src_end": pd.Timestamp(r.source_end_at).tz_convert("UTC").value,
                    "av": pd.Timestamp(r.available_at).tz_convert("UTC").value})
        indexed = {si: _SegmentSwings(v) for si, v in by_seg.items()}
        empty = _SegmentSwings([])
        firsts = {}
        for z in z_tf.sort_values(["available_at", "c2_end", "zone_id"], kind="mergesort").itertuples(index=False):
            anchor = z.c2_end.value
            si, k2 = pos[anchor]
            seg = data.segments[si]
            origin, term = indexed.get(si, empty).origin(z.original_direction, anchor)
            vals = seg["l"] if z.original_direction == BULLISH else seg["h"]
            v, j = int(vals[k2]), k2
            while j - 1 >= 0 and int(vals[j - 1]) == v:
                j -= 1
            left = [int(x) for x in vals[j - 2:j]] if j - 2 >= 0 else None
            qualified = left is not None and (all(x >= v for x in left) if z.original_direction == BULLISH
                                              else all(x <= v for x in left))
            avail = z.available_at.value
            if qualified:
                deadline = int(seg["end"][k2 + 2]) if k2 + 2 < len(seg["end"]) else None
                rule = "PENDING_CANDIDATE_AT_C2"
            else:
                deadline, rule = avail, "NO_PENDING_CANDIDATE"
            if deadline is None or origin is None:
                continue          # not knowable at the cutoff, or in no leg: no row
            at_ns = max(avail, origin["av"], deadline)
            key = (z.original_direction, origin["id"])
            first = key not in firsts
            if first:
                firsts[key] = z.zone_id
            ex = exits[z.zone_id]
            fvg_end = ex["conv_ns"] if ex["conv_ns"] is not None else ex["exit_ns"]
            never = first and fvg_end is not None and fvg_end <= at_ns
            reason = None
            if never:
                reason = "CONVERTED" if ex["conv_ns"] is not None else ex["exit_kind"]
            aid = sha_id("fa_", [z.zone_id, origin["id"], LEG_RULE_VERSION])
            at = pd.Timestamp(at_ns, tz="UTC")
            rows.append({"association_id": aid, "zone_id": z.zone_id, "timeframe": tf,
                         "direction": z.original_direction, "leg_origin_swing_id": origin["id"],
                         "last_terminator_swing_id": None if term is None else term["id"], "is_first": first,
                         "formation_available_at": z.available_at, "association_available_at": at,
                         "deadline_rule": rule, "marker_never_active": bool(never), "reason": reason,
                         "contract": z.contract, "leg_rule_version": LEG_RULE_VERSION})
            if first and not never:
                entities.append({"entity_id": aid, "available_at": at, "valid_from": pd.NaT, "valid_until": pd.NaT,
                                 "instrument_id": instrument_id, "contract_scope": SPECIFIC, "contract": z.contract})
                if fvg_end is not None:
                    end_reason = "CONVERTED" if ex["conv_ns"] is not None else ex["exit_kind"]
                    end_at = pd.Timestamp(fvg_end, tz="UTC")
                    trigger = SourceRef("FVG_EVENT", f"{end_reason}|{z.zone_id}|{canonical_time(end_at)}").canonical
                    markers.append({
                        "transition_id": transition_id(namespace=NS_MARKER, definition_version=FVG_DEFINITION_VERSION,
                                                       entity_id=aid, previous_state=ACTIVE, new_state=ENDED,
                                                       transition_at=end_at, trigger_ref=trigger, source_refs=()),
                        "namespace": NS_MARKER, "entity_id": aid, "previous_state": ACTIVE, "new_state": ENDED,
                        "transition_at": end_at, "transition_seq_domain": None, "transition_seq": None,
                        "available_at": end_at, "available_seq_domain": None, "available_seq": None,
                        "instrument_id": instrument_id, "contract_scope": SPECIFIC, "contract": z.contract,
                        "definition_version": FVG_DEFINITION_VERSION, "trigger_ref": trigger, "source_refs": (),
                        "reason_code": end_reason})
    from src.fvg.engine import TRANSITION_BASE, _entities
    ent = _entities(entities)
    tr = pd.DataFrame(markers, columns=TRANSITION_BASE)
    for column in ("transition_at", "available_at"):
        tr[column] = pd.to_datetime(tr[column], utc=True)
    if len(tr):
        tr = validate_transitions(tr, marker_namespace(), ent)
    return frame(rows, ASSOCIATION_COLUMNS), tr, ent
