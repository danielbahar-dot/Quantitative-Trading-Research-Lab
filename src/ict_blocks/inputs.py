"""Order Block dependency facts (OB-I1; D-153, D-157).

Specification: ``docs/project/ORDER_BLOCK_BREAKER_MITIGATION_DESIGN.md`` rev 3 §5, §11, §22.

- Own-timeframe observations: unchanged M3 ``build_timeframe`` output (1m: canonical bars) in frozen
  expected-schedule continuity segments, complete observations only, exact integer ticks.
- Swing facts: the public detector ``build_swing_points`` with an explicit ``SwingDefinitionSpec`` (OB default
  left_depth = right_depth = 1); restricted to facts available by the replay cutoff.
- FVG facts: raw accepted formations of the frozen FVG layer (``fvg-v1``; ``build_formations``), not the
  first-in-leg marker.
- 1m tape: a new adapter over the frozen §G.2a ``detect_structure_episodes`` (DATA_GAP / CONTRACT_CHANGE
  resets with an explicit replay cutoff).

Nothing here reads liquidity, BOS/CHoCH or strategy inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from src.data.continuity import continuity_segments
from src.data.timeframes import TimeframeSpec, build_timeframe
from src.fvg.formation import FVG_DEFINITION_VERSION, build_formations, timeframe_spec
from src.market_structure.structure import detect_structure_episodes
from src.market_structure.swing import SwingDefinitionSpec
from src.market_structure.swing_breaks import price_ticks
from src.market_structure.swing_detector import build_swing_points

SWING_VERSION = "swing-pivot-v1"
DEFAULT_DEPTH = 1


class ObInputError(ValueError):
    """Dependency facts do not line up with the OB observations (fail closed)."""


def swing_definition(left_depth: int = DEFAULT_DEPTH, right_depth: int = DEFAULT_DEPTH) -> SwingDefinitionSpec:
    return SwingDefinitionSpec(definition_version=SWING_VERSION, left_depth=left_depth, right_depth=right_depth)


@dataclass
class TfObs:
    timeframe: str
    segments: list = field(default_factory=list)       # dicts: contract, start, end, o, h, l, c (ns / ticks)
    pos: dict = field(default_factory=dict)            # bar end ns -> (segment index, position)


def observations(source: pd.DataFrame, tf: str, session_spec, *, replay_cutoff: pd.Timestamp, tick: Decimal,
                 source_interval: Any = "1min") -> TfObs:
    data = TfObs(tf)
    if source.empty:
        return data
    obs = build_timeframe(source, timeframe_spec(tf), session_spec, source_interval=source_interval)
    obs = obs.loc[(pd.to_datetime(obs["bar_end"], utc=True) <= replay_cutoff).to_numpy()]
    if obs.empty:
        return data
    segments, _ = continuity_segments(obs, timeframe_spec(tf), session_spec, source_interval=source_interval)
    for si, seg in enumerate(segments):
        seg = seg.reset_index(drop=True)
        d = {"contract": seg["contract"].iloc[0],
             "start": pd.DatetimeIndex(pd.to_datetime(seg["bar_start"], utc=True)).as_unit("ns").asi8,
             "end": pd.DatetimeIndex(pd.to_datetime(seg["bar_end"], utc=True)).as_unit("ns").asi8,
             "o": price_ticks(seg["open"].to_numpy(), tick), "h": price_ticks(seg["high"].to_numpy(), tick),
             "l": price_ticks(seg["low"].to_numpy(), tick), "c": price_ticks(seg["close"].to_numpy(), tick)}
        data.segments.append(d)
        for k, e in enumerate(d["end"].tolist()):
            data.pos[e] = (si, k)
    return data


@dataclass(frozen=True)
class Swing:
    swing_id: str
    orientation: str
    seg: int
    a: int              # first bar of the source span (position in its segment)
    b: int              # last (terminal) bar of the source span
    price: int          # ticks
    available_ns: int


def swing_facts(source: pd.DataFrame, tf: str, session_spec, definition: SwingDefinitionSpec, obs: TfObs, *,
                instrument_id: str, replay_cutoff: pd.Timestamp, tick: Decimal,
                source_interval: Any = "1min") -> tuple[pd.DataFrame, dict]:
    """Public-detector swings at the OB depths, available by the cutoff, indexed per segment (sorted by span)."""
    if source.empty:
        return pd.DataFrame(), {}
    sw = build_swing_points(source, tf, session_spec, definition, instrument_id=instrument_id,
                            source_interval=source_interval)
    sw = sw.loc[(pd.to_datetime(sw["available_at"], utc=True) <= replay_cutoff).to_numpy()].reset_index(drop=True)
    by_seg: dict = {}
    if len(sw):
        px = price_ticks(sw["price"].to_numpy(), tick)
        for r, p in zip(sw.itertuples(index=False), px):
            a_ns = pd.Timestamp(r.source_at).tz_convert("UTC").value
            b_ns = pd.Timestamp(r.source_end_at).tz_convert("UTC").value
            av = pd.Timestamp(r.available_at).tz_convert("UTC").value
            if a_ns not in obs.pos or b_ns not in obs.pos:
                raise ObInputError(f"{tf}: swing {r.swing_id} source is not an OB observation")
            (sa, ka), (sb, kb) = obs.pos[a_ns], obs.pos[b_ns]
            if sa != sb:
                raise ObInputError(f"{tf}: swing {r.swing_id} spans two continuity segments")
            seg = obs.segments[sa]
            if kb + definition.right_depth >= len(seg["end"]) or int(seg["end"][kb + definition.right_depth]) != av:
                raise ObInputError(f"{tf}: swing {r.swing_id} availability is not bar b + right_depth")
            by_seg.setdefault(sa, []).append(Swing(r.swing_id, r.orientation, sa, ka, kb, int(p), av))
    for v in by_seg.values():
        v.sort(key=lambda s: (s.a, s.orientation))
    return sw, by_seg


@dataclass(frozen=True)
class Fvg:
    zone_id: str
    direction: str
    seg: int
    c2: int             # position of C2 in its segment
    available_ns: int
    lower: int
    upper: int


def fvg_facts(source: pd.DataFrame, session_spec, timeframes, obs_by_tf: dict, *, instrument_id: str,
              replay_cutoff: pd.Timestamp, tick: Decimal, source_interval: Any = "1min") -> tuple[pd.DataFrame, dict]:
    """Raw accepted FVG formations (``fvg-v1``) per timeframe and segment, sorted by C2."""
    formation = build_formations(source, session_spec, instrument_id=instrument_id, replay_cutoff=replay_cutoff,
                                 tick=tick, timeframes=timeframes, source_interval=source_interval)
    zones = formation.zones
    out: dict = {tf: {} for tf in timeframes}
    for z in zones.itertuples(index=False):
        obs = obs_by_tf[z.timeframe]
        c2 = z.c2_end.value
        if c2 not in obs.pos:
            raise ObInputError(f"{z.timeframe}: FVG {z.zone_id} C2 is not an OB observation")
        si, k = obs.pos[c2]
        if k + 1 >= len(obs.segments[si]["end"]) or int(obs.segments[si]["end"][k + 1]) != z.available_at.value:
            raise ObInputError(f"{z.timeframe}: FVG {z.zone_id} is not available at C3 close")
        out[z.timeframe].setdefault(si, []).append(Fvg(z.zone_id, z.original_direction, si, k, z.available_at.value,
                                                       int(z.lower_ticks), int(z.upper_ticks)))
    for per_tf in out.values():
        for v in per_tf.values():
            v.sort(key=lambda f: (f.c2, f.zone_id))
    return zones, out


# ---------------------------------------------------------------------------
# 1m tape and resets (new adapter over the frozen §G.2a episodes)
# ---------------------------------------------------------------------------


@dataclass
class TapeEpisode:
    index: int
    contract: str
    start: np.ndarray
    end: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    reset_at: int | None          # ns
    reset_reason: str | None
    reset_ref: str | None


@dataclass
class MinuteTape:
    episodes: list
    where: dict = field(default_factory=dict)

    def locate(self, end_ns: int):
        return self.where.get(int(end_ns))


def minute_tape(source: pd.DataFrame, session_spec, *, replay_cutoff: pd.Timestamp, tick: Decimal,
                source_interval: Any = "1min") -> MinuteTape:
    if source.empty:
        return MinuteTape([])
    obs = build_timeframe(source, TimeframeSpec("1m", 1), session_spec, source_interval=source_interval)
    episodes = detect_structure_episodes(obs, "1m", session_spec, replay_cutoff=replay_cutoff,
                                         source_interval=source_interval)
    out = []
    for k, ep in enumerate(episodes):
        rows = ep.rows
        out.append(TapeEpisode(
            k, ep.contract,
            pd.DatetimeIndex(pd.to_datetime(rows["bar_start"], utc=True)).as_unit("ns").asi8,
            pd.DatetimeIndex(pd.to_datetime(rows["bar_end"], utc=True)).as_unit("ns").asi8,
            price_ticks(rows["open"].to_numpy(), tick), price_ticks(rows["high"].to_numpy(), tick),
            price_ticks(rows["low"].to_numpy(), tick), price_ticks(rows["close"].to_numpy(), tick),
            None if ep.reset_at is None else pd.Timestamp(ep.reset_at).tz_convert("UTC").value, ep.reset_reason,
            ep.reset_ref))
    tape = MinuteTape(out)
    for ep in out:
        for pos, end in enumerate(ep.end.tolist()):
            tape.where[end] = (ep.index, pos)
    return tape


def segment_episode(tape: MinuteTape, obs: TfObs, si: int) -> TapeEpisode:
    """The 1m episode containing timeframe segment ``si`` (fail closed if it straddles episodes)."""
    seg = obs.segments[si]
    first, last = tape.locate(int(seg["end"][0])), tape.locate(int(seg["end"][-1]))
    if first is None or last is None or first[0] != last[0]:
        raise ObInputError(f"{obs.timeframe}: segment {si} is not inside one 1m episode")
    return tape.episodes[first[0]]


__all__ = ["FVG_DEFINITION_VERSION", "SWING_VERSION", "DEFAULT_DEPTH", "swing_definition", "observations",
           "swing_facts", "fvg_facts", "minute_tape", "segment_episode", "TfObs", "Swing", "Fvg", "MinuteTape",
           "TapeEpisode", "ObInputError"]
