"""Synthetic fixtures for the Order Block tests (rev 3 §15 and the lifecycle motifs).

Rows are 5m (O, H, L, C) relative to 20,000 (``ms_fixtures.ohlc_bars``: observation k is exactly the row).
``mirror`` reflects prices around 20,100 so every bullish case has a bearish mirror with mirrored expectations.
"""

from __future__ import annotations

from ms_fixtures import BASE, SPEC, ohlc_bars, schedule
from src.ict_blocks.pipeline import build_order_blocks

AXIS = 200.0
TICK = 0.25


def mirror(rows):
    return [None if r is None else (AXIS - r[0], AXIS - r[2], AXIS - r[1], AXIS - r[3]) for r in rows]


def tk(price, mirrored=False):
    return int(round((BASE + (AXIS - price if mirrored else price)) / TICK))


def end(k, tf="5m"):
    return schedule(tf).iloc[k]["bar_end"].tz_convert("UTC")


def k_of(ts, tf="5m"):
    s = schedule(tf)
    hit = s.index[s["bar_end"] == ts]
    return int(hit[0]) if len(hit) else None


def run(rows, tf="5m", timeframes=None, cutoff_k=None, mirrored=False, depth=1, shuffle_seed=None, **kw):
    rows = mirror(rows) if mirrored else rows
    bars = ohlc_bars(rows, tf, **kw)
    k = len(rows) - 1 if cutoff_k is None else cutoff_k
    return build_order_blocks(bars, SPEC, instrument_id="MNQ", replay_cutoff=end(k, tf), timeframes=timeframes or (tf,),
                              left_depth=depth, right_depth=depth, shuffle_seed=shuffle_seed)


# §15.1: single source k2; first FVG k4/k5/k6 with C2 entirely above the region; rally-top swing k6
EX151 = [(104, 106, 103, 105), (105, 105.5, 101, 102), (102, 103, 99, 100), (100, 112, 100, 108),
         (108, 113, 102, 111), (111, 117, 110, 116), (116, 119, 114, 118), (118, 118.5, 117, 118)]

# Bullish parent at k4 ([99, 105]) with prior high A = k1 (120); FVG k5/k6/k7; rally top C = k8; break x = k10.
_HEAD = [(100, 101, 99, 100.5), (100.5, 120, 100, 119), (119, 119.5, 110, 111), (111, 112, 104, 105),
         (105, 106, 99, 100), (100, 112, 100, 111), (111, 118, 111, 117)]
BREAKER_ROWS = _HEAD + [(117, 123, 113, 122), (122, 124, 120, 121), (121, 121.5, 108, 109), (109, 110, 98, 98.5),
                        (98.5, 101, 97, 100), (100, 106, 99.5, 105.5), (105.5, 106, 104, 105)]
MITIGATION_ROWS = _HEAD + [(117, 119, 113, 118), (118, 119.5, 116, 117), (117, 117.5, 108, 109), (109, 110, 98, 98.5),
                           (98.5, 101, 97, 100), (100, 103, 99.5, 102), (102, 104.5, 101, 104)]
EQUAL_ROWS = _HEAD + [(117, 119, 113, 118), (118, 120, 116, 117), (117, 117.5, 108, 109), (109, 110, 98, 98.5),
                      (98.5, 101, 97, 100)]
RAID_LOWER_C_ROWS = _HEAD + [(117, 119, 113, 118), (118, 119.5, 116, 117), (117, 117.5, 108, 109), (109, 122, 98, 98.5),
                             (98.5, 101, 97, 100)]
NO_PRIOR_ROWS = [(106, 107, 104, 105)] + BREAKER_ROWS[4:]

# Concurrent: the rally top k8 is a bullish source for an independent bearish ordinary OB (FVG k8/k9/k10) admitted
# at k10 — the same close at which the old bullish block fails and becomes a bearish BREAKER.
CONCURRENT_ROWS = _HEAD + [(117, 123, 113, 122), (120, 124, 119.5, 123.5), (123, 123.5, 112, 113), (113, 114, 98, 98.5),
                           (98.5, 101, 97, 100), (100, 103, 99.5, 102)]
# Earlier excursion raid: k9 raids above A (122) inside an equal-high plateau k9..k10 that ends at the break bar, so
# it is not an eligible C and no other eligible C exists; the earlier raid evidence is kept (NO_REVERSAL_SWING).
# At N = 1 a raid with a less extreme eligible C can only come from the break bar itself (RAID_LOWER_C_ROWS).
EARLY_RAID_ROWS = _HEAD + [(117, 119, 113, 118), (118, 119.5, 116, 117), (117, 122, 108, 109), (109, 122, 98, 98.5),
                           (98.5, 101, 97, 100)]
# N = 2: B = k5 (two bars each side), FVG k6/k7/k8, C = k10 (two lower highs k11, k12), break x = k11, C confirmed at
# k12 → FAILED_AWAITING_CLASSIFICATION at k11, BREAKER at k12.
N2_HEAD = [(100, 101, 99, 100.5), (100.5, 115, 100, 114), (114, 120, 113, 119), (119, 119.5, 110, 111),
           (111, 112, 104, 105), (105, 106, 99, 100), (100.5, 110, 100.5, 109), (109, 113, 101, 112.5),
           (112.5, 118, 112.5, 117)]
N2_DELAYED_ROWS = N2_HEAD + [(117, 123, 113, 122), (122, 124, 120, 121), (121, 121.5, 98, 98.5), (98.5, 100, 97, 99),
                             (99, 103, 98, 102), (102, 106, 101, 105.5)]
# Same, but the close at k12 is already beyond the successor's far bound (> 105) → QUALIFIED_BUT_INVALID_BEFORE_ADMISSION.
N2_INVALID_ROWS = N2_HEAD + [(117, 123, 113, 122), (122, 124, 120, 121), (121, 121.5, 98, 98.5), (98.5, 106, 97, 105.5),
                             (105.5, 106, 103, 104)]


def with_source(o, c, rows=EX151, k=2):
    """§15.2: replace the source candle's open / close (high 103, low 99 kept)."""
    out = list(rows)
    out[k] = (o, rows[k][1], rows[k][2], c)
    return out


# Terminal plateau: equal lows k2..k3; k2 is a large bearish candle, k3 (terminal) decides.
PLATEAU_HEAD = [(104, 106, 103, 105), (105, 105.5, 101, 102), (102, 103, 99, 100)]
PLATEAU_TAIL = [(100, 112, 100, 108), (108, 113, 102, 111), (111, 117, 110, 116), (116, 119, 114, 118),
                (118, 118.5, 117, 118)]
PLATEAU_OK_ROWS = PLATEAU_HEAD + [(101.5, 102, 99, 100)] + PLATEAU_TAIL         # terminal body 6 ticks
PLATEAU_DOJI_ROWS = PLATEAU_HEAD + [(100.25, 101, 99, 100.25)] + PLATEAU_TAIL   # terminal doji; k2 never substituted
# §15.1 followed by a monotonic rally: several later bullish FVGs and no new swing low
RALLY_ROWS = EX151[:7] + [(118.5, 125, 118.5, 124), (124, 131, 120, 131), (131, 137, 130.5, 136),
                          (136, 138, 135, 137), (137, 139, 136.5, 138.5)]
# §15.1 then a higher low k8 (new same-side swing) with its own departure → a second bullish ordinary OB
HIGHER_LOW_ROWS = EX151[:7] + [(118, 118.5, 112, 113), (113, 114, 108, 109), (109, 118, 109, 117),
                               (117, 121, 115, 120), (120, 120.5, 119, 119.5)]
# §15.1 then interactions with the admitted bullish OB [99, 102] (zone midpoint 100.5)
INTERACT_ROWS = EX151 + [(118, 118.5, 102, 103), (103, 104, 101.5, 103.5), (103.5, 104, 100.5, 103),
                         (98.5, 98.75, 98, 98.5)]
# a completed one-minute visit at k8, then a multi-minute visit: k9 closes inside the admitted bullish zone [99, 102] (its last 4 minutes sit at 101) and
# k10 stays inside; k11's first minute still touches, then the flat minutes leave → one visit spanning k9..k11; a later visit at k13
LONG_VISIT_ROWS = EX151 + [(118, 118.5, 102, 103), (103, 104, 100.5, 101), (101, 101.5, 100.75, 101.25),
                           (101.25, 104, 101, 103.5), (103.5, 104, 103, 103.5), (103.5, 104, 101.5, 103)]
