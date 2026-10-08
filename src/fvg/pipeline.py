"""FVG pipeline entry point, manifest and strategy-facing causal views (rev 2.1 §3.12).

``build_fvg`` runs formation (FVG-I1), interaction / lifecycle / relationships
/ grading (FVG-I2, FVG-I3) and the first-FVG association (FVG-I4) up to an
explicit ``replay_cutoff``.  Source bars after the cutoff are never read.

Views apply the bar-boundary rule: a bar starting at ``t`` sees facts with
``available_at ≤ t``; lifecycle state at ``t`` is the state after every
event with ``at ≤ t``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.instruments import DEFAULT_INSTRUMENT_CONFIG_DIR, load_instrument
from src.data.timeframes import validate_source_bars
from src.fvg.association import LEG_RULE_VERSION, SWING_REFERENCE, associate, swings_by_timeframe
from src.fvg.engine import BEARISH, BULLISH, FVG, IFVG, UNDEFINED, EngineResult, build_tape, run_engine
from src.fvg.formation import FVG_DEFINITION_VERSION, TF_RANK, TIMEFRAMES, OK, build_formations, sha_id
from src.market_structure.structure import require_cutoff
from src.state.contract import canonical_time

ENGINE_VERSION = "fvg-engine-1"


@dataclass
class FvgRun:
    manifest: dict
    zones: pd.DataFrame
    rejections: pd.DataFrame
    engine: EngineResult
    associations: pd.DataFrame
    marker_transitions: pd.DataFrame
    marker_entities: pd.DataFrame
    counts: dict
    tape: Any = field(repr=False, default=None)
    tf_data: dict = field(repr=False, default_factory=dict)
    swings: dict = field(repr=False, default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]


def build_fvg(bars: pd.DataFrame, session_spec, *, instrument_id: str, replay_cutoff: Any,
              timeframes=TIMEFRAMES, instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
              source_interval: Any = "1min") -> FvgRun:
    cutoff = require_cutoff(replay_cutoff)
    source = validate_source_bars(bars)
    source = source.loc[source.index <= cutoff]
    tick = Decimal(str(load_instrument(instrument_id, instrument_config_dir).tick_size))
    formation = build_formations(source, session_spec, instrument_id=instrument_id, replay_cutoff=cutoff, tick=tick,
                                 timeframes=timeframes, source_interval=source_interval)
    tape = build_tape(source, session_spec, replay_cutoff=cutoff, tick=tick, source_interval=source_interval)
    engine = run_engine(formation.zones, formation.timeframe_data, tape, instrument_id=instrument_id, tick=tick)
    swings = swings_by_timeframe(source, session_spec, timeframes, instrument_id=instrument_id, replay_cutoff=cutoff,
                                 source_interval=source_interval)
    assoc, markers, marker_ent = associate(formation.zones, formation.timeframe_data, swings, engine.zone_exits,
                                           instrument_id=instrument_id, tick=tick)
    fingerprint = None
    if not source.empty:
        fingerprint = hashlib.sha256(pd.util.hash_pandas_object(
            source[["open", "high", "low", "close", "volume", "contract"]], index=True).to_numpy().tobytes()).hexdigest()
    manifest = {
        "engine_version": ENGINE_VERSION, "definition_version": FVG_DEFINITION_VERSION,
        "leg_rule_version": LEG_RULE_VERSION,
        "swing_reference": f"{SWING_REFERENCE.definition_version}:{SWING_REFERENCE.left_depth}/{SWING_REFERENCE.right_depth}",
        "instrument_id": instrument_id, "tick_size": str(tick), "replay_cutoff": canonical_time(cutoff),
        "basis": "RAW", "adjustment_version": None, "timeframes": ",".join(timeframes),
        "source_fingerprint": fingerprint,
        "zone_counts": ",".join(f"{tf}={formation.counts[tf]['zones']}" for tf in timeframes),
    }
    manifest["run_id"] = sha_id("fvr_", [manifest[k] for k in sorted(manifest)])
    return FvgRun(manifest, formation.zones, formation.rejections, engine, assoc, markers, marker_ent,
                  formation.counts, tape, formation.timeframe_data, swings)


# ---------------------------------------------------------------------------
# Strategy-facing causal views
# ---------------------------------------------------------------------------


def _utc(t) -> pd.Timestamp:
    return pd.Timestamp(t).tz_convert("UTC")


def active_fvg_zones(run: FvgRun, at: Any) -> pd.DataFrame:
    """Zones in stage FVG / IFVG at ``at`` with stage-scoped mitigation summary, marker, grade and priority rank."""
    t = _utc(at)
    st = stages_as_of(run, t)
    live = st[st["stage_end"].isna()]
    live = live[live["stage"].isin([FVG, IFVG])]
    if live.empty:
        return pd.DataFrame(columns=VIEW_COLUMNS)
    z = run.zones.set_index("zone_id")
    mit = run.engine.mitigation
    mit = mit[(mit["object_kind"] == "ZONE") & (mit["at"] <= t)]
    grades = run.engine.grades
    grades = grades[grades["available_at"] <= t].sort_values("available_at", kind="mergesort")
    grades = grades.groupby("zone_id").tail(1).set_index("zone_id")
    assoc = run.associations
    assoc = assoc[assoc["is_first"] & ~assoc["marker_never_active"] & (assoc["association_available_at"] <= t)]
    marked = set(assoc["zone_id"])
    rows = []
    for r in live.itertuples(index=False):
        zr = z.loc[r.zone_id]
        m = mit[(mit["object_id"] == r.zone_id) & (mit["stage"] == r.stage)]
        first = lambda kind: m.loc[m["kind"] == kind, "at"].min() if (m["kind"] == kind).any() else pd.NaT  # noqa: E731
        g = grades.loc[r.zone_id] if r.zone_id in grades.index else None
        rows.append({
            "zone_id": r.zone_id, "timeframe": zr["timeframe"], "stage": r.stage, "stage_start": r.stage_start,
            "current_direction": r.current_direction, "lower": zr["lower"], "upper": zr["upper"],
            "midpoint": zr["midpoint"], "lower_ticks": zr["lower_ticks"], "upper_ticks": zr["upper_ticks"],
            "midpoint_half_ticks": zr["midpoint_half_ticks"], "original_width_ticks": zr["width_ticks"],
            "normalization_status": zr["normalization_status"], "normalized_gap_strength": zr["normalized_gap_strength"],
            "first_mitigation_at": first("PENETRATION"), "midpoint_reached_at": first("MIDPOINT"),
            "full_reached_at": first("FULL"), "gap_through_at": first("GAP_THROUGH"),
            "max_penetration_depth_ticks": m.loc[m["kind"] == "DEPTH", "penetration_depth_ticks"].max()
            if (m["kind"] == "DEPTH").any() else None,
            "first_fvg_marker": r.stage == FVG and r.zone_id in marked,
            "timeframe_rank": TF_RANK[zr["timeframe"]],
            "overlap_contribution": 0 if g is None else int(g["overlap_contribution"]),
            "available_at": zr["available_at"], "contract": zr["contract"],
            "pending_cross_contract_count": int(((run.engine.pending["since_at"] <= t)
                                                 & (run.engine.pending["contract"] != zr["contract"])).sum()),
        })
    out = pd.DataFrame(rows, columns=VIEW_COLUMNS)
    return rank_zones(out)


VIEW_COLUMNS = ["zone_id", "timeframe", "stage", "stage_start", "current_direction", "lower", "upper", "midpoint",
                "lower_ticks", "upper_ticks", "midpoint_half_ticks", "original_width_ticks", "normalization_status",
                "normalized_gap_strength", "first_mitigation_at", "midpoint_reached_at", "full_reached_at",
                "gap_through_at", "max_penetration_depth_ticks", "first_fvg_marker", "timeframe_rank",
                "overlap_contribution", "available_at", "contract", "pending_cross_contract_count"]


def rank_zones(view: pd.DataFrame) -> pd.DataFrame:
    """§3.9.1: timeframe ↓, overlap contribution ↓, strength ↓ (nulls below values, tied), width ↓,
    available_at ↑, zone_id ↑."""
    if view.empty:
        return view.assign(priority_rank=pd.Series(dtype="Int64"))
    v = view.copy()
    v["_has"] = v["normalization_status"].eq(OK)
    v["_s"] = v["normalized_gap_strength"].where(v["_has"], 0.0).astype(float)
    v = v.sort_values(["timeframe_rank", "overlap_contribution", "_has", "_s", "original_width_ticks", "available_at",
                       "zone_id"], ascending=[False, False, False, False, False, True, True], kind="mergesort")
    v["priority_rank"] = range(1, len(v) + 1)
    return v.drop(columns=["_has", "_s"]).reset_index(drop=True)


# Lifecycle columns that describe a later exit; an as-of projection nulls them while the exit lies after ``at``.
FUTURE_LIFECYCLE = {
    "bprs": ("exit_at", ("exit_state", "exit_at", "exit_reason")),
    "episodes": ("ended_at", ("ended_at", "end_reason")),
    "stages": ("stage_end", ("stage_end", "end_kind")),
}
AVAILABILITY = {"bprs": "available_at", "episodes": "created_at", "stages": "stage_start"}


def as_of(frame: pd.DataFrame, kind: str, at: Any) -> pd.DataFrame:
    """Rows of a lifecycle table (``bprs`` / ``episodes`` / ``stages``) as knowable at ``at``.

    Keeps rows available at or before ``at`` and nulls the exit metadata of every exit that happens after
    ``at``.  The engine tables themselves keep the complete audit history."""
    t = _utc(at)
    out = frame[frame[AVAILABILITY[kind]] <= t].copy()
    when, cols = FUTURE_LIFECYCLE[kind]
    future = (out[when] > t).to_numpy()
    if future.any():
        for c in cols:
            out[c] = out[c].astype(object)
            out.loc[future, c] = None
        out[when] = pd.to_datetime(out[when], utc=True)
    return out.reset_index(drop=True)


def bprs_as_of(run: FvgRun, at: Any) -> pd.DataFrame:
    return as_of(run.engine.bprs, "bprs", at)


def episodes_as_of(run: FvgRun, at: Any) -> pd.DataFrame:
    return as_of(run.engine.episodes, "episodes", at)


def stages_as_of(run: FvgRun, at: Any) -> pd.DataFrame:
    return as_of(run.engine.stages, "stages", at)


def active_bprs(run: FvgRun, at: Any, *, include_undefined: bool = False) -> pd.DataFrame:
    """Active BPR objects at ``at``; defined-direction ones ranked (§3.9.3); UNDEFINED ones only descriptively.

    Causal: built from the as-of projection, so no exit metadata after ``at`` is visible (an active object
    has no exit yet; the exit columns are dropped)."""
    live = bprs_as_of(run, at)
    live = live[live["exit_at"].isna()].drop(columns=list(FUTURE_LIFECYCLE["bprs"][1]))
    undefined = live["direction"] == UNDEFINED
    if include_undefined:
        return live[undefined].reset_index(drop=True)
    live = live[~undefined].copy()
    live["_rank"] = live["governing_timeframe"].map(TF_RANK)
    live = live.sort_values(["_rank", "width_ticks", "available_at", "bpr_id"], ascending=[False, False, True, True],
                            kind="mergesort")
    live["bpr_rank"] = range(1, len(live) + 1)
    return live.drop(columns=["_rank"]).reset_index(drop=True)


def active_overlaps(run: FvgRun, at: Any) -> pd.DataFrame:
    """Open relationship episodes at ``at`` (as-of projection; end metadata dropped)."""
    e = episodes_as_of(run, at)
    return e[e["ended_at"].isna()].drop(columns=list(FUTURE_LIFECYCLE["episodes"][1])).reset_index(drop=True)
