"""Order Block run builder and causal strategy views (OB-I4; D-157).

``build_order_blocks`` takes canonical bar-end-labelled 1m bars and an explicit ``replay_cutoff``; it derives the
dependency facts (public Swing detector at the OB depths, raw ``fvg-v1`` formations, own-timeframe observations,
1m reset tape) and runs the engine.  ``shuffle_seed`` permutes the dependency fact rows before the engine
(determinism check: outputs must not change).

Views are as-of projections: they only expose facts known at the query time and never later exits.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.instruments import DEFAULT_INSTRUMENT_CONFIG_DIR, load_instrument
from src.data.timeframes import validate_source_bars
from src.fvg.formation import FVG_DEFINITION_VERSION, TIMEFRAMES, sha_id
from src.market_structure.structure import require_cutoff
from src.ict_blocks.engine import (BLOCK_COLUMNS, BREAKER, MITIGATION, OB_DEFINITION_VERSION, ORDINARY,
                                   SELECTION_POLICY, EngineResult, ObConfig, run_engine)
from src.ict_blocks.inputs import (DEFAULT_DEPTH, SWING_VERSION, fvg_facts, minute_tape, observations, swing_definition,
                                   swing_facts)

ENGINE_VERSION = "ob-engine-1"
ACTIONABLE = (ORDINARY, BREAKER, MITIGATION)


@dataclass
class ObRun:
    manifest: dict
    engine: EngineResult
    obs: dict = field(repr=False, default_factory=dict)
    swings: dict = field(repr=False, default_factory=dict)
    swing_frames: dict = field(repr=False, default_factory=dict)
    fvgs: dict = field(repr=False, default_factory=dict)
    fvg_zones: Any = field(repr=False, default=None)
    tape: Any = field(repr=False, default=None)

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]


def build_order_blocks(bars: pd.DataFrame, session_spec, *, instrument_id: str, replay_cutoff: Any,
                       timeframes=TIMEFRAMES, left_depth: int = DEFAULT_DEPTH, right_depth: int = DEFAULT_DEPTH,
                       instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
                       source_interval: Any = "1min", shuffle_seed: int | None = None) -> ObRun:
    cutoff = require_cutoff(replay_cutoff)
    source = validate_source_bars(bars)
    source = source.loc[source.index <= cutoff]
    tick = Decimal(str(load_instrument(instrument_id, instrument_config_dir).tick_size))
    definition = swing_definition(left_depth, right_depth)
    obs = {tf: observations(source, tf, session_spec, replay_cutoff=cutoff, tick=tick, source_interval=source_interval)
           for tf in timeframes}
    swing_frames, swings = {}, {}
    for tf in timeframes:
        swing_frames[tf], swings[tf] = swing_facts(source, tf, session_spec, definition, obs[tf],
                                                   instrument_id=instrument_id, replay_cutoff=cutoff, tick=tick,
                                                   source_interval=source_interval)
    fvg_zones, fvgs = (fvg_facts(source, session_spec, timeframes, obs, instrument_id=instrument_id,
                                 replay_cutoff=cutoff, tick=tick, source_interval=source_interval)
                       if not source.empty else (pd.DataFrame(), {tf: {} for tf in timeframes}))
    if shuffle_seed is not None:                       # determinism check: dependency rows in a random order
        rng = random.Random(shuffle_seed)
        for per in list(swings.values()) + list(fvgs.values()):
            for v in per.values():
                rng.shuffle(v)
    tape = minute_tape(source, session_spec, replay_cutoff=cutoff, tick=tick, source_interval=source_interval)
    cfg = ObConfig(instrument_id=instrument_id, tick=tick, left_depth=left_depth, right_depth=right_depth,
                   swing_definition=SWING_VERSION)
    if shuffle_seed is not None:                       # the engine's own ordering contract: sort by span / C2
        for per in swings.values():
            for v in per.values():
                v.sort(key=lambda s: (s.a, s.orientation))
        for per in fvgs.values():
            for v in per.values():
                v.sort(key=lambda f: (f.c2, f.zone_id))
    engine = run_engine(obs, swings, fvgs, tape, cfg)
    fingerprint = None
    if not source.empty:
        fingerprint = hashlib.sha256(pd.util.hash_pandas_object(
            source[["open", "high", "low", "close", "volume", "contract"]], index=True).to_numpy().tobytes()).hexdigest()
    manifest = {
        "engine_version": ENGINE_VERSION, "definition_version": OB_DEFINITION_VERSION,
        "selection_policy": SELECTION_POLICY, "swing_definition": SWING_VERSION, "left_depth": left_depth,
        "right_depth": right_depth, "fvg_definition": FVG_DEFINITION_VERSION, "instrument_id": instrument_id,
        "tick_size": str(tick), "replay_cutoff": cutoff.isoformat(), "basis": "RAW", "adjustment_version": None,
        "timeframes": ",".join(timeframes), "source_fingerprint": fingerprint,
        "block_counts": ",".join(f"{tf}={int((engine.blocks['timeframe'] == tf).sum())}" for tf in timeframes),
    }
    manifest["run_id"] = sha_id("obr_run_", [manifest[k] for k in sorted(manifest)])
    return ObRun(manifest, engine, obs, swings, swing_frames, fvgs, fvg_zones, tape)


# ---------------------------------------------------------------------------
# Causal views (as-of projections)
# ---------------------------------------------------------------------------


def _utc(t) -> pd.Timestamp:
    return pd.Timestamp(t).tz_convert("UTC")


def stages_as_of(run: ObRun, at: Any) -> pd.DataFrame:
    t = _utc(at)
    st = run.engine.stages
    out = st[st["available_at"] <= t].copy()
    later = (out["ended_at"] > t).to_numpy()
    if later.any():
        for col in ("ended_at", "end_reason"):
            out[col] = out[col].astype(object)
            out.loc[later, col] = None
        out["ended_at"] = pd.to_datetime(out["ended_at"], utc=True)
    return out.reset_index(drop=True)


def episodes_as_of(run: ObRun, at: Any) -> pd.DataFrame:
    """Discovery episodes opened by ``at``; decisions after ``at`` read as WAITING_FOR_DEPARTURE."""
    t = _utc(at)
    e = run.engine.episodes
    out = e[e["opened_at"] <= t].copy()
    later = (out["decided_at"] > t).to_numpy()
    if later.any():
        cols = ("decided_at", "reason", "window_swing_id", "superseded_by_swing_id", "formation_fvg_id",
                "validation_close_at", "ownership_deadline_at", "block_id")
        for col in cols:
            out[col] = out[col].astype(object)
            out.loc[later, col] = None
        out["status"] = out["status"].astype(object)
        out.loc[later, "status"] = "WAITING_FOR_DEPARTURE"
        for col in ("decided_at", "validation_close_at", "ownership_deadline_at"):
            out[col] = pd.to_datetime(out[col], utc=True)
    return out.reset_index(drop=True)


def block_history(run: ObRun, at: Any) -> pd.DataFrame:
    """Every stage known at ``at`` with the region geometry (later exits hidden)."""
    st = stages_as_of(run, at)
    if st.empty:
        return st
    b = run.engine.blocks.set_index("block_id")["source_region_id"]
    r = run.engine.regions.set_index("source_region_id")[["lower_ticks", "upper_ticks", "zone_midpoint_half_ticks",
                                                          "lower", "upper", "zone_midpoint"]]
    return st.join(b, on="block_id").join(r, on="source_region_id").reset_index(drop=True)


def active_blocks(run: ObRun, at: Any) -> pd.DataFrame:
    """Actionable stages at ``at`` (ORDINARY / BREAKER / MITIGATION not yet ended), with first-touch status."""
    h = block_history(run, at)
    if h.empty:
        return h
    live = h[h["ended_at"].isna() & h["stage_kind"].isin(ACTIONABLE)].drop(columns=["ended_at", "end_reason"])
    t = _utc(at)
    i = run.engine.interactions
    touched = set(i.loc[(i["kind"] == "FIRST_TOUCH") & (i["at"] <= t), "stage_id"])
    live = live.assign(touched=live["stage_id"].isin(touched))
    return live.sort_values(["available_at", "stage_id"], kind="mergesort").reset_index(drop=True)


def first_return_candidates(run: ObRun, at: Any) -> pd.DataFrame:
    a = active_blocks(run, at)
    return a[~a["touched"]].reset_index(drop=True) if len(a) else a


def discovery_status(run: ObRun, at: Any) -> pd.DataFrame:
    return episodes_as_of(run, at)


def pending_blocks(run: ObRun, at: Any) -> pd.DataFrame:
    p = run.engine.pending
    return p[p["since_at"] <= _utc(at)].reset_index(drop=True)


__all__ = ["build_order_blocks", "ObRun", "active_blocks", "block_history", "discovery_status",
           "first_return_candidates", "pending_blocks", "stages_as_of", "episodes_as_of", "BLOCK_COLUMNS"]
