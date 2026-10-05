"""Shared synthetic fixtures for the Market Structure tests (not a test module).

``ohlc_bars`` builds canonical 1m source bars whose target-timeframe
observation k has exactly the requested (open, high, low, close): the first
minute carries O / H / L / C and the remaining minutes sit flat at C, so the
M3 (or direct 1m) observation is exactly (O, H, L, C).
"""

from datetime import date, timedelta

import pandas as pd

from src.data.continuity import continuity_segments
from src.data.sessions import load_session_spec
from src.data.timeframes import TimeframeSpec, build_timeframe, expected_timeframe_schedule

SPEC = load_session_spec()
NY = "America/New_York"
BASE = 20000.0
ONE_MINUTE = TimeframeSpec("1m", 1)
DAYS = [date(2026, 9, 14) + timedelta(days=d) for d in range(26) if (date(2026, 9, 14) + timedelta(days=d)).weekday() < 5]
CONTRACT = "MNQ 12-26"

# MARKET_STRUCTURE_SPEC §H.0 example sequences (prices relative to BASE)
EX_A = [
    (106, 107, 105, 106), (106, 106, 102, 103), (103, 104, 100, 103), (103, 106, 102, 105),
    (105, 108, 104, 107), (107, 110, 106, 108), (108, 109, 105, 106), (106, 107, 104, 105),
    (105, 108, 105, 107), (107, 109, 106, 108), (108, 112, 107, 111),
    (111, 115, 110, 114), (114, 118, 113, 116), (116, 117, 109, 110), (110, 111, 104, 106),
    (106, 109, 105, 108), (108, 112, 107, 111), (111, 116, 110, 115), (115, 120, 114, 119),
    (119, 124, 118, 123), (123, 126, 121, 122), (122, 124, 116, 117), (117, 118, 112, 114),
    (114, 119, 113, 118), (118, 122, 117, 121), (121, 125, 120, 124), (124, 129, 123, 128),
]
EX_B = [
    (106, 107, 105, 106), (106, 106, 102, 103), (103, 104, 100, 103), (103, 106, 102, 105),
    (105, 108, 104, 107), (107, 110, 106, 108), (108, 109, 105, 106), (106, 107, 104, 105),
    (105, 108, 105, 107), (107, 110, 106, 109), (109, 109, 106, 107), (107, 108, 104, 105),
    (105, 107, 105, 106), (106, 109, 105, 108), (108, 112, 107, 111),
]
EX_C = EX_A[:11] + [
    (111, 118, 110, 117), (117, 125, 116, 124), (124, 130, 123, 127), (127, 128, 120, 121),
    (121, 122, 116, 117), (117, 118, 108, 110), (110, 111, 102, 105), (105, 107, 102, 106),
    (106, 112, 105, 111), (111, 116, 110, 115), (115, 120, 114, 118), (118, 119, 112, 113),
    (113, 114, 107, 108), (108, 113, 108, 112), (112, 116, 111, 115), (115, 115, 110, 111),
    (111, 112, 103, 106), (106, 109, 105, 108), (108, 110, 106, 109),
    (109, 109.5, 103.5, 103.5),
    (104, 107, 104, 106), (106, 109, 105, 108), (108, 110, 106, 107), (107, 108, 105, 107),
    (107, 112, 106, 111), (111, 116, 110, 115), (115, 116, 114, 116),
    (116, 123, 115, 122),
    (122, 122, 118, 119), (119, 120, 116, 117),
]


def schedule(tf="5m", dates=DAYS, spec=SPEC):
    return expected_timeframe_schedule(dates, ONE_MINUTE if tf == "1m" else tf, spec).reset_index(drop=True)


def ohlc_bars(rows, tf="5m", *, contracts=None, absent=(), incomplete=(), dates=DAYS, spec=SPEC, offset=0):
    """1m source bars: target observation ``offset + k`` gets ``rows[k]`` (relative to BASE).

    ``absent`` / ``incomplete`` hold row indices k; ``contracts`` is per row.
    """
    sched = schedule(tf, dates, spec)
    frames = []
    for k, row in enumerate(rows):
        if k in absent or row is None:
            continue
        slot = sched.iloc[offset + k]
        minutes = pd.date_range(slot["bar_start"] + pd.Timedelta(minutes=1), slot["bar_end"], freq="min")
        if k in incomplete:
            minutes = minutes[:-1] if len(minutes) > 1 else minutes[:0]
            if len(minutes) == 0:
                continue
        o, h, lo, c = (BASE + value for value in row)
        frame = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1,
                              "contract": contracts[k] if contracts else CONTRACT}, index=minutes)
        first = frame.index[0]
        frame.loc[first, ["open", "high", "low", "close"]] = [o, h, lo, c]
        frames.append(frame)
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="timestamp_et")
    return out


def observations(bars, tf="5m", spec=SPEC):
    return build_timeframe(bars, ONE_MINUTE if tf == "1m" else tf, spec)


def segments(bars, tf="5m", spec=SPEC):
    obs = observations(bars, tf, spec)
    segs, breaks = continuity_segments(obs, ONE_MINUTE if tf == "1m" else tf, spec)
    return obs, segs, breaks


def slot_end(k, tf="5m", dates=DAYS, spec=SPEC):
    """UTC bar_end of expected target observation k."""
    return pd.Timestamp(schedule(tf, dates, spec)["bar_end"].iloc[k]).tz_convert("UTC")
