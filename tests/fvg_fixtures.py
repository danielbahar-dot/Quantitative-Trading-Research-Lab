"""Synthetic fixtures for the FVG tests (worked examples of `docs/project/FVG_IFVG_BPR_DESIGN.md` rev 2.1 §5).

Rows are (O, H, L, C) relative to 20,000; ``mirror`` reflects prices around 20,100 (bullish ↔ bearish), so
every case can be checked in both directions with mirrored expectations.
"""

from __future__ import annotations

from ms_fixtures import BASE, SPEC, ohlc_bars, schedule
from src.fvg.pipeline import build_fvg

MIRROR_AXIS = 200.0
TICK = 0.25


def mirror(rows):
    return [None if r is None else (MIRROR_AXIS - r[0], MIRROR_AXIS - r[2], MIRROR_AXIS - r[1], MIRROR_AXIS - r[3])
            for r in rows]


def mp(price, mirrored):
    """Expected absolute price of relative ``price`` under the (optional) mirror."""
    return BASE + (MIRROR_AXIS - price if mirrored else price)


def tk(price, mirrored=False):
    return int(round(mp(price, mirrored) / TICK))


def end(k, tf="5m"):
    return schedule(tf).iloc[k]["bar_end"].tz_convert("UTC")


def run(rows, tf="5m", timeframes=None, cutoff_k=None, mirrored=False, **kw):
    rows = mirror(rows) if mirrored else rows
    bars = ohlc_bars(rows, tf, **kw)
    k = len(rows) - 1 if cutoff_k is None else cutoff_k
    return build_fvg(bars, SPEC, instrument_id="MNQ", replay_cutoff=end(k, tf), timeframes=timeframes or (tf,))


W1 = [(100, 101.00, 99, 100.75), (100.75, 104, 100.5, 103.75), (103.75, 105, 102.25, 104.5), (104.5, 104.75, 102.25, 103),
      (103, 103.25, 102, 102.5), (102.5, 102.75, 101.5, 102), (102, 102.25, 100.75, 101.25), (101.25, 101.5, 101.0, 101.0),
      (101, 101.25, 100.25, 100.5), (100.5, 101.0, 100.25, 100.75), (100.75, 101.75, 100.5, 101.5),
      (101.5, 102.5, 101.25, 102.25), (102.25, 103, 102, 102.75)]
ZONE3 = W1[:3]
W2 = W1[:3] + [(104.5, 104.75, 100.5, 100.75), (100.75, 101.5, 100.5, 101.25), (101.25, 101.5, 101.0, 101.25)]
W5 = [(100, 100.5, 99.5, 100.25), (100.25, 100.75, 100, 100.5), (100.5, 101, 100.25, 100.75),
      (100.75, 103, 100.75, 102.75), (102.75, 105, 102.5, 104.75), (104.75, 107, 104.5, 106.75),
      (106.75, 108, 106, 107.5), (107.5, 108.5, 107, 108), (108, 109, 107.25, 108.5)]
W6 = W1[:3] + [(104.5, 105.5, 104, 105), (105, 106, 104.5, 105.5), (105.5, 106.5, 105, 106),
               (106, 106.5, 103.25, 104), (104, 104.5, 103, 103.5), (103.5, 104, 103.25, 103.75),
               (103.75, 103.75, 102, 102.25), (102.25, 102.5, 101.5, 101.75), (101.75, 102, 101.25, 101.5),
               (101.5, 101.75, 101.25, 101.5), (101.5, 101.75, 101.25, 101.25), (101.25, 101.5, 101.0, 101.25),
               (101.25, 101.25, 100.5, 100.75), (100.75, 102.75, 100.75, 102.5), (102.5, 102.5, 101.75, 102.0),
               (102, 102.25, 101.75, 102.25), (102.25, 102.5, 102, 102.25), (102.25, 103, 102.25, 102.75)]
W7 = W5 + [(108.5, 108.5, 104.0, 104.25), (104.25, 104.5, 102.75, 103.0), (103.0, 103.5, 100.75, 101.0),
           (101.0, 101.25, 100.25, 100.75)]
W8 = W7[:11] + [(103.0, 103.5, 100.25, 100.5)]
W9A = [(110, 111, 108, 109), (109, 109.5, 105, 105.5), (105.5, 112.5, 100, 112), (112, 115, 110, 114.5),
       (114.5, 116, 113, 115.5), (115.5, 119, 115.25, 118.5), (118.5, 121, 117, 120.5)]
W9B = [(104, 105, 103, 104), (104, 104.5, 102, 102.5), (102.5, 103, 100, 102.75), (102.75, 104, 101, 103.75),
       (103.75, 108, 103.5, 107.75), (107.75, 110, 105, 109.5), (109.5, 111, 104.5, 105), (105, 112, 104, 111.5),
       (111.5, 113, 104.25, 112.75), (112.75, 114, 104.5, 113.5), (113.5, 117, 113.25, 116.5), (116.5, 118, 115, 117.5)]
W9C = W9B[:6] + [(109.5, 111, 101, 102), (102, 112, 99, 111), (111, 113, 99.5, 112.5), (112.5, 114, 100, 113.5),
                 (113.5, 117, 113.25, 116.5), (116.5, 118, 115, 117.5)]
W9D = [(106, 107, 105, 105.5), (105.5, 106, 104, 104.5), (104.5, 105, 100, 100.5), (100.5, 108, 100, 107.75),
       (107.75, 109, 105.5, 108.5), (108.5, 110, 106, 109.5), (109.5, 111, 107, 110.5)]
HISTORY_OK = [(100, 100.5, 99.5, 100)] * 15
HISTORY_FLAT = [(100, 100, 100, 100)] * 15


def zone_at(run_, lower, upper, mirrored=False, tf=None):
    """The unique zone with these relative bounds (mirrored bounds swap)."""
    lo, up = (tk(upper, True), tk(lower, True)) if mirrored else (tk(lower), tk(upper))
    z = run_.zones[(run_.zones["lower_ticks"] == lo) & (run_.zones["upper_ticks"] == up)]
    if tf is not None:
        z = z[z["timeframe"] == tf]
    assert len(z) == 1, (lower, upper, mirrored, len(z))
    return z.iloc[0]


def events(run_, zone_id, stage=None):
    m = run_.engine.mitigation
    m = m[m["object_id"] == zone_id]
    if stage is not None:
        m = m[m["stage"] == stage]
    return {k: g["at"].min() for k, g in m.groupby("kind")}
