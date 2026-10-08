"""FVG formation and immutable zone facts (FVG-I1; D-148).

Specification: ``docs/project/FVG_IFVG_BPR_DESIGN.md`` rev 2.1 §3.1 – §3.3, §3.13.

- Six timeframes, each processed independently: canonical 1m bars and M3
  observations for 5m / 15m / 1H / 4H / 1D (frozen ``build_timeframe``).
- C1, C2, C3 are three consecutive complete expected observations of one
  frozen continuity segment (``continuity_segments``).
- **Wick gap** of at least one tick (bullish ``low(C3) > high(C1)``, bearish
  ``high(C3) < low(C1)``; equality is not an FVG) and a **C2 directional
  body spanning the gap** (bullish ``close > open``, ``open ≤ high(C1)``,
  ``close ≥ low(C3)``; bearish mirrored).  C1 / C3 any colour; a doji C2
  fails.  Rejected wick gaps are audited with their reason.
- Available at C3 close; exact integer-tick bounds, width and half-tick
  midpoint; normalized gap strength from the 14 true ranges before C1 (15
  consecutive observations of the segment), exact rational, with explicit
  ``INSUFFICIENT_HISTORY`` / ``ZERO_BASELINE`` statuses.

Frozen M3, continuity and Swing contract code is used read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from src.data.continuity import continuity_segments
from src.data.timeframes import TimeframeSpec, build_timeframe, get_timeframe
from src.market_structure.swing_breaks import price_ticks
from src.state.contract import SPECIFIC

FVG_DEFINITION_VERSION = "fvg-v1"
TIMEFRAMES = ("1m", "5m", "15m", "1H", "4H", "1D")
TF_RANK = {"1m": 1, "5m": 2, "15m": 3, "1H": 4, "4H": 5, "1D": 6}
BULLISH, BEARISH = "BULLISH", "BEARISH"
BASELINE_N = 14
OK, INSUFFICIENT_HISTORY, ZERO_BASELINE = "OK", "INSUFFICIENT_HISTORY", "ZERO_BASELINE"
C2_NOT_DIRECTIONAL, C2_BODY_NOT_SPANNING = "C2_NOT_DIRECTIONAL", "C2_BODY_NOT_SPANNING"

ZONE_COLUMNS = (
    "zone_id", "timeframe", "original_direction", "lower_ticks", "upper_ticks", "midpoint_half_ticks", "lower",
    "upper", "midpoint", "width_ticks", "width_points", "c1_ref", "c2_ref", "c3_ref", "source_ref", "source_at",
    "source_end_at", "span_start", "available_at", "c1_end", "c2_end", "segment_ref", "segment_index", "c1_index",
    "baseline_tr_sum_ticks", "baseline_atr_ticks", "normalization_status", "strength_num", "strength_den",
    "normalized_gap_strength", "instrument_id", "contract_scope", "contract", "basis_id", "definition_version",
)
REJECTION_COLUMNS = ("timeframe", "triple_ref", "wick_gap_direction", "reason", "c3_end", "contract", "instrument_id")


class FvgError(ValueError):
    """Raised for inconsistent FVG inputs (fail closed)."""


def sha_id(prefix: str, key: list) -> str:
    return prefix + hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


_CTIME: dict = {}


def ctime(ns: int) -> str:
    """Canonical UTC text of an integer-ns instant; identical to M7 ``canonical_time`` (cached; hot path)."""
    out = _CTIME.get(ns)
    if out is None:
        seconds, nanos = divmod(int(ns), 1_000_000_000)
        out = f"{pd.Timestamp(seconds, unit='s', tz='UTC').strftime('%Y-%m-%dT%H:%M:%S')}.{nanos:09d}Z"
        _CTIME[ns] = out
    return out


def bar_ref(instrument_id: str, contract: str, timeframe: str, first_ns: int, last_ns: int | None = None) -> str:
    """The frozen ``BAR_SPAN`` text (``bar_span_ref`` format, D-138) from integer-ns bar ends (tested equal)."""
    return f"BAR_SPAN:{instrument_id}|{contract}|{timeframe}|{ctime(first_ns)}|{ctime(first_ns if last_ns is None else last_ns)}"


def timeframe_spec(tf: str) -> TimeframeSpec:
    return TimeframeSpec("1m", 1) if tf == "1m" else get_timeframe(tf)


def raw_basis(contract: str) -> str:
    return f"RAW:{contract}"


@dataclass
class TimeframeData:
    """One timeframe's complete observations, split into frozen continuity segments (tick arrays)."""

    timeframe: str
    segments: list = field(default_factory=list)      # per segment: dict of numpy arrays and contract

    def segment_of_end(self) -> dict:
        out = {}
        for si, seg in enumerate(self.segments):
            for k, e in enumerate(seg["end"]):
                out[int(e)] = (si, k)
        return out


@dataclass
class FormationResult:
    zones: pd.DataFrame
    rejections: pd.DataFrame
    timeframe_data: dict
    counts: dict


def prepare_timeframe(source: pd.DataFrame, tf: str, session_spec, *, replay_cutoff: pd.Timestamp, tick: Decimal,
                      source_interval: Any = "1min") -> TimeframeData:
    """Complete observations of ``tf`` up to ``replay_cutoff`` in frozen continuity segments."""
    data = TimeframeData(tf)
    if source.empty:
        return data
    obs = build_timeframe(source, timeframe_spec(tf), session_spec, source_interval=source_interval)
    obs = obs.loc[(pd.to_datetime(obs["bar_end"], utc=True) <= replay_cutoff).to_numpy()]
    if obs.empty:
        return data
    segments, _ = continuity_segments(obs, timeframe_spec(tf), session_spec, source_interval=source_interval)
    for seg in segments:
        seg = seg.reset_index(drop=True)
        data.segments.append({
            "contract": seg["contract"].iloc[0],
            "start": pd.DatetimeIndex(pd.to_datetime(seg["bar_start"], utc=True)).as_unit("ns").asi8,
            "end": pd.DatetimeIndex(pd.to_datetime(seg["bar_end"], utc=True)).as_unit("ns").asi8,
            "o": price_ticks(seg["open"].to_numpy(), tick), "h": price_ticks(seg["high"].to_numpy(), tick),
            "l": price_ticks(seg["low"].to_numpy(), tick), "c": price_ticks(seg["close"].to_numpy(), tick),
        })
    return data


def _ts(ns: int) -> pd.Timestamp:
    return pd.Timestamp(int(ns), tz="UTC")


def _price(ticks: int, tick: Decimal) -> float:
    return float(Decimal(int(ticks)) * tick)


def formations_for_timeframe(data: TimeframeData, *, instrument_id: str, tick: Decimal) -> tuple[list, list, dict]:
    tf = data.timeframe
    zones, rejections = [], []
    counts = {"triples": 0, "wick_gaps": 0, "equality": 0, "zones": 0, C2_NOT_DIRECTIONAL: 0, C2_BODY_NOT_SPANNING: 0}
    for si, seg in enumerate(data.segments):
        n = len(seg["end"])
        if n < 3:
            continue
        o, h, l, c = seg["o"], seg["h"], seg["l"], seg["c"]
        counts["triples"] += n - 2
        i = np.arange(2, n)
        h1, l1, h3, l3 = h[i - 2], l[i - 2], h[i], l[i]
        o2, c2 = o[i - 1], c[i - 1]
        bull_gap = l3 > h1
        bear_gap = h3 < l1
        counts["equality"] += int(((l3 == h1) | (h3 == l1)).sum())
        bull_dir = c2 > o2
        bear_dir = c2 < o2
        bull_span = (o2 <= h1) & (c2 >= l3)
        bear_span = (o2 >= l1) & (c2 <= h3)
        # true ranges within the segment (index j >= 1 uses the previous close)
        tr = np.zeros(n, dtype=np.int64)
        if n > 1:
            prev = c[:-1]
            tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - prev), np.abs(l[1:] - prev)])
        csum = np.concatenate([[0], np.cumsum(tr)])
        seg_ref = f"{tf}|{seg['contract']}|{_ts(seg['end'][0]).isoformat()}"
        for idx in np.flatnonzero(bull_gap | bear_gap):
            k3 = int(i[idx])
            k1, k2 = k3 - 2, k3 - 1
            bull = bool(bull_gap[idx])
            counts["wick_gaps"] += 1
            directional = bool(bull_dir[idx]) if bull else bool(bear_dir[idx])
            spans = bool(bull_span[idx]) if bull else bool(bear_span[idx])
            triple_ref = bar_ref(instrument_id, seg["contract"], tf, int(seg["end"][k1]), int(seg["end"][k3]))
            if not directional or not spans:
                reason = C2_NOT_DIRECTIONAL if not directional else C2_BODY_NOT_SPANNING
                counts[reason] += 1
                rejections.append({"timeframe": tf, "triple_ref": triple_ref,
                                   "wick_gap_direction": BULLISH if bull else BEARISH, "reason": reason,
                                   "c3_end": _ts(seg["end"][k3]), "contract": seg["contract"],
                                   "instrument_id": instrument_id})
                continue
            lower, upper = (int(h[k1]), int(l[k3])) if bull else (int(h[k3]), int(l[k1]))
            width = upper - lower
            # baseline: TR of observations k1-14 .. k1-1, each with its previous close (k1-15 must exist)
            if k1 - BASELINE_N - 1 >= 0:
                tr_sum = int(csum[k1] - csum[k1 - BASELINE_N])
                status = OK if tr_sum > 0 else ZERO_BASELINE
            else:
                tr_sum, status = None, INSUFFICIENT_HISTORY
            if status == OK:
                strength = Fraction(width * BASELINE_N, tr_sum)
                num, den, dec = strength.numerator, strength.denominator, float(strength)
            else:
                num = den = dec = None
            refs = [bar_ref(instrument_id, seg["contract"], tf, int(seg["end"][k])) for k in (k1, k2, k3)]
            direction = BULLISH if bull else BEARISH
            zones.append({
                "zone_id": sha_id("fz_", [FVG_DEFINITION_VERSION, instrument_id, SPECIFIC, seg["contract"], tf,
                                          direction, triple_ref]),
                "timeframe": tf, "original_direction": direction, "lower_ticks": lower, "upper_ticks": upper,
                "midpoint_half_ticks": lower + upper, "lower": _price(lower, tick), "upper": _price(upper, tick),
                "midpoint": float(Decimal(lower + upper) * tick / 2), "width_ticks": width,
                "width_points": _price(width, tick), "c1_ref": refs[0], "c2_ref": refs[1], "c3_ref": refs[2],
                "source_ref": triple_ref, "source_at": _ts(seg["end"][k1]), "source_end_at": _ts(seg["end"][k3]),
                "span_start": _ts(seg["start"][k1]), "available_at": _ts(seg["end"][k3]),
                "c1_end": _ts(seg["end"][k1]), "c2_end": _ts(seg["end"][k2]), "segment_ref": seg_ref,
                "segment_index": si, "c1_index": k1, "baseline_tr_sum_ticks": tr_sum,
                "baseline_atr_ticks": None if tr_sum is None else float(Fraction(tr_sum, BASELINE_N)),
                "normalization_status": status, "strength_num": num, "strength_den": den,
                "normalized_gap_strength": dec, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
                "contract": seg["contract"], "basis_id": raw_basis(seg["contract"]),
                "definition_version": FVG_DEFINITION_VERSION,
            })
            counts["zones"] += 1
    return zones, rejections, counts


def build_formations(source: pd.DataFrame, session_spec, *, instrument_id: str, replay_cutoff: pd.Timestamp,
                     tick: Decimal, timeframes=TIMEFRAMES, source_interval: Any = "1min") -> FormationResult:
    zones, rejections, counts, data = [], [], {}, {}
    for tf in timeframes:
        data[tf] = prepare_timeframe(source, tf, session_spec, replay_cutoff=replay_cutoff, tick=tick,
                                     source_interval=source_interval)
        z, r, c = formations_for_timeframe(data[tf], instrument_id=instrument_id, tick=tick)
        zones += z
        rejections += r
        counts[tf] = c
    zf = frame(zones, ZONE_COLUMNS)
    if len(zf):
        zf = zf.sort_values(["available_at", "timeframe", "zone_id"], key=_tf_sort_key, kind="mergesort").reset_index(drop=True)
        if zf["zone_id"].duplicated().any():
            raise FvgError("duplicate zone_id")
    return FormationResult(zf, frame(rejections, REJECTION_COLUMNS), data, counts)


def _tf_sort_key(col: pd.Series) -> pd.Series:
    return col.map(TF_RANK) if col.name == "timeframe" else col


def frame(rows: list, columns: tuple) -> pd.DataFrame:
    """Fixed-schema frame (an empty table keeps its columns); ``*_at`` / ``*_end`` / ``span_start`` are UTC."""
    out = pd.DataFrame(rows, columns=list(columns))
    for column in out.columns:
        if column.endswith("_at") or column.endswith("_end") or column == "span_start":
            out[column] = pd.to_datetime(out[column], utc=True)
    return out
