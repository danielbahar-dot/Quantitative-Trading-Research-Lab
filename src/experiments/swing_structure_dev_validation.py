"""Swing Structure 3.2 — SW-I3 DEVELOPMENT validation runner (machine validation; read-only).

Command (repository root)::

    .\\.venv\\Scripts\\python.exe -m src.experiments.swing_structure_dev_validation

DEVELOPMENT partition only (path from the dataset partition config); explicit
2/2 reference definition (``swing-pivot-v1``, not a detector default); all six
timeframes.  Production path: ``build_swing_points``.  Independent audit path:
``src.market_structure.swing_audit``.  Writes price-free tracked CSVs and the
local, Git-ignored candidate audit (gzip) and visual HTML under
``reports/validation/``.  No PnL, no strategy, no optimization, no VALIDATION /
OOS data.  It does not freeze anything; it reports machine gates.
"""

from __future__ import annotations

from datetime import date
import hashlib
import html
from pathlib import Path
import time

import pandas as pd

from src.data.continuity import continuity_segments
from src.data.partitions import load_partition_config
from src.data.sessions import load_session_spec
from src.data.timeframes import TimeframeSpec, build_timeframe, expected_timeframe_schedule
from src.market_structure import swing_detector
from src.market_structure.swing import LOWER, SWING_TIMEFRAMES, UPPER, SwingDefinitionSpec
from src.market_structure.swing_audit import (
    AUDIT_STATUSES,
    CONFIRMED,
    CONTINUITY_BREAK,
    INVALIDATED_STRICT_EXCEED,
    audit_swing_candidates,
    prepare_swing_observations,
    swing_invariants,
)
from src.market_structure.swing_detector import build_swing_points

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT = PROJECT_ROOT / "reports" / "validation"
NY = "America/New_York"
INSTRUMENT = "MNQ"
REFERENCE = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2)

EXPECTED_CONTINUITY = {"1m": (337815, 33, 32), "5m": (67552, 32, 31), "15m": (22506, 31, 30), "1H": (5614, 29, 28),
                       "4H": (1443, 29, 28), "1D": (220, 23, 22)}
EXPECTED_COUNTS = {"1m": (46516, 46819), "5m": (9040, 9118), "15m": (2982, 3055), "1H": (716, 736), "4H": (180, 187),
                   "1D": (16, 16)}
EXPECTED_TOTAL = 119381
EXPECTED_PLATEAU = {"1m": 4624, "5m": 422, "15m": 66, "1H": 5, "4H": 0, "1D": 0}
EXPECTED_PAIRS = {"1m": 892, "5m": 74, "15m": 9, "1H": 1, "4H": 0, "1D": 0}
EXPECTED_TRUNCATED_4H = (67, 367)
EXPECTED_XTF = {("4H", "15m"): (367, 28.0, 100.0, 9.50, 8.0), ("4H", "5m"): (367, 84.0, 100.0, 9.92, 24.0),
                ("1H", "15m"): (1452, 8.0, 100.0, 2.00, 2.0), ("1H", "5m"): (1452, 24.0, 100.0, 2.42, 7.0)}
PRICE_COLUMNS = {"price", "open", "high", "low", "close"}


def load_development_bars() -> pd.DataFrame:
    config = load_partition_config()
    development = next(p for p in config["partitions"] if p["name"] == "DEVELOPMENT")
    raw = pd.read_csv(PROJECT_ROOT / development["output_file"])
    raw["timestamp_et"] = pd.to_datetime(raw["timestamp_et"], utc=True).dt.tz_convert(NY)
    return raw.set_index("timestamp_et").sort_index()


def main() -> int:
    started = time.perf_counter()
    spec = load_session_spec()
    bars = load_development_bars()
    rows, timings, gates = [], [], {}
    add = lambda section, tf, orientation, metric, value: rows.append(  # noqa: E731
        {"section": section, "timeframe": tf, "orientation": orientation, "metric": metric, "value": value})
    add("source", "", "", "canonical_1m_rows", len(bars))
    add("source", "", "", "represented_sessions", int(bars["session_date"].nunique()))
    add("source", "", "", "first_session", str(bars["session_date"].min()))
    add("source", "", "", "last_session", str(bars["session_date"].max()))

    swings, audits, invariants, breaks_all, prepared = {}, {}, [], [], {}
    for tf in SWING_TIMEFRAMES:
        t0 = time.perf_counter()
        swings[tf] = build_swing_points(bars, tf, spec, REFERENCE, instrument_id=INSTRUMENT)
        t1 = time.perf_counter()
        audits[tf] = audit_swing_candidates(bars, tf, spec, REFERENCE, instrument_id=INSTRUMENT)
        t2 = time.perf_counter()
        prepared[tf] = prepare_swing_observations(bars, tf, spec)
        invariants.append(swing_invariants(swings[tf], bars, tf, spec, REFERENCE, instrument_id=INSTRUMENT))
        t3 = time.perf_counter()
        timings.append((tf, t1 - t0, t2 - t1, t3 - t2))
        print(f"{tf}: swings {len(swings[tf])} candidates {len(audits[tf])} "
              f"(detector {t1 - t0:.1f}s, audit {t2 - t1:.1f}s, invariants {t3 - t2:.1f}s)", flush=True)

    # --- continuity -------------------------------------------------------------------------------
    continuity_ok = True
    for tf in SWING_TIMEFRAMES:
        observations, segments, breaks = prepared[tf]
        seg_bars = sum(len(s) for s in segments)
        add("continuity", tf, "", "complete_segment_bars", seg_bars)
        add("continuity", tf, "", "segments", len(segments))
        add("continuity", tf, "", "breaks", len(breaks))
        for reason, count in breaks["reason"].value_counts().sort_index().items():
            add("continuity", tf, "", f"breaks_{reason}", int(count))
        continuity_ok &= (seg_bars, len(segments), len(breaks)) == EXPECTED_CONTINUITY[tf]
        breaks_all.append(breaks)
    gates["continuity_matches_baseline"] = continuity_ok

    # --- canonical counts, plateaus, separated pairs, truncation --------------------------------------
    counts_ok, plateau_ok, pairs_ok = True, True, True
    total = 0
    for tf in SWING_TIMEFRAMES:
        frame = swings[tf]
        up, low = int((frame["orientation"] == UPPER).sum()), int((frame["orientation"] == LOWER).sum())
        total += up + low
        add("canonical", tf, UPPER, "swings", up)
        add("canonical", tf, LOWER, "swings", low)
        add("canonical", tf, "ALL", "swings", up + low)
        counts_ok &= (up, low) == EXPECTED_COUNTS[tf]
        plateau = int((frame["source_at"] != frame["source_end_at"]).sum())
        add("canonical", tf, "ALL", "adjacent_plateau_swings", plateau)
        plateau_ok &= plateau == EXPECTED_PLATEAU[tf]
        pairs = _separated_equal_pairs(frame, prepared[tf][1], REFERENCE.right_depth)
        add("canonical", tf, "ALL", "separated_equal_pairs_both_confirmed", pairs)
        pairs_ok &= pairs == EXPECTED_PAIRS[tf]
    add("canonical", "", "ALL", "total_swings", total)
    truncated = _truncated_source_swings(swings["4H"], prepared["4H"][1])
    add("canonical", "4H", "ALL", "session_truncated_source_swings", truncated)
    gates["canonical_counts_match_baseline"] = counts_ok and total == EXPECTED_TOTAL
    gates["plateau_and_equality_counts_match"] = plateau_ok and pairs_ok
    gates["truncated_4h_67_of_367"] = (truncated, len(swings["4H"])) == EXPECTED_TRUNCATED_4H

    # --- audit + reconciliation ----------------------------------------------------------------------
    recon_ok = True
    for tf in SWING_TIMEFRAMES:
        audit = audits[tf]
        for orientation in (UPPER, LOWER):
            sub = audit[audit["orientation"] == orientation]
            add("audit", tf, orientation, "candidates", len(sub))
            for status in AUDIT_STATUSES:
                add("audit", tf, orientation, f"status_{status}", int((sub["status"] == status).sum()))
            confirmed = set(sub.loc[sub["status"] == CONFIRMED, "swing_id"])
            canonical = set(swings[tf].loc[swings[tf]["orientation"] == orientation, "swing_id"])
            add("reconciliation", tf, orientation, "confirmed_audit", len(confirmed))
            add("reconciliation", tf, orientation, "canonical", len(canonical))
            add("reconciliation", tf, orientation, "missing_from_canonical", len(confirmed - canonical))
            add("reconciliation", tf, orientation, "missing_from_audit", len(canonical - confirmed))
            recon_ok &= confirmed == canonical
            inv = sub[sub["status"] == INVALIDATED_STRICT_EXCEED]
            for side_name, count in inv["invalidating_side"].value_counts().sort_index().items():
                add("audit", tf, orientation, f"invalidated_side_{side_name}", int(count))
            cb = sub[sub["status"] == CONTINUITY_BREAK]
            for reason, count in cb["break_reason"].value_counts().sort_index().items():
                add("audit", tf, orientation, f"continuity_break_{reason}", int(count))
    gates["audit_canonical_reconciliation_exact"] = recon_ok

    # --- invariants ---------------------------------------------------------------------------------
    invariant_frame = pd.concat(invariants, ignore_index=True)
    gates["all_invariants_zero"] = int(invariant_frame["violations"].sum()) == 0

    # --- 1m direct vs M3 1m cross-check ----------------------------------------------------------------
    direct = swing_detector._one_minute_observations(bars, spec, "1min")  # validation-only use of the SW-I2 adapter
    m3 = build_timeframe(bars, TimeframeSpec("1m", 1), spec)
    same_columns = all(direct[c].tolist() == m3[c].tolist() for c in
                       ("trading_date", "bar_start", "bar_end", "high", "low", "contract", "expected_bars",
                        "observed_bars", "is_complete", "is_session_truncated"))
    d_segs, d_breaks = continuity_segments(direct, TimeframeSpec("1m", 1), spec)
    m_segs, m_breaks = continuity_segments(m3, TimeframeSpec("1m", 1), spec)
    cross_ok = same_columns and len(d_segs) == len(m_segs) == 33 and d_breaks.equals(m_breaks) \
        and [len(s) for s in d_segs] == [len(s) for s in m_segs]
    add("cross_check", "1m", "", "direct_vs_m3_segments", f"{len(d_segs)}/{len(m_segs)}")
    add("cross_check", "1m", "", "direct_vs_m3_exact", cross_ok)
    gates["one_minute_direct_vs_m3_exact"] = cross_ok

    # --- identity fingerprints ------------------------------------------------------------------------
    all_ids = []
    for tf in SWING_TIMEFRAMES:
        for orientation in (UPPER, LOWER):
            ids = sorted(swings[tf].loc[swings[tf]["orientation"] == orientation, "swing_id"])
            all_ids.extend(ids)
            add("identity", tf, orientation, "swing_id_sha256", _fingerprint(ids))
    add("identity", "", "ALL", "swing_id_sha256", _fingerprint(sorted(all_ids)))
    gates["swing_id_hashes_generated"] = True

    # --- cross-timeframe descriptive study --------------------------------------------------------------
    xtf_rows = []
    xtf_ok = True
    for htf, ltf in EXPECTED_XTF:
        for orientation in (UPPER, LOWER, "ALL"):
            result = _cross_timeframe(swings[htf], swings[ltf], prepared[htf][0], prepared[ltf][0], orientation)
            xtf_rows.append({"htf": htf, "ltf": ltf, "orientation": orientation, **result})
            if orientation == "ALL":
                got = (result["htf_swing_count"], result["median_ltf_bars_between_source_and_confirmation"],
                       round(result["same_price_match_rate"] * 100, 1), round(result["median_lead_minutes"] / 60, 2),
                       result["median_ltf_swings_available_in_interval"])
                xtf_ok &= got == EXPECTED_XTF[(htf, ltf)]
    gates["cross_timeframe_reproduces_spec"] = xtf_ok

    # --- local candidate audit (price-bearing, Git-ignored) ----------------------------------------------
    pd.concat([audits[tf] for tf in SWING_TIMEFRAMES], ignore_index=True).to_csv(
        OUT / "swing_structure_dev_candidate_audit.csv.gz", index=False, compression="gzip")

    # --- visual ------------------------------------------------------------------------------------------
    t_visual = time.perf_counter()
    cases = _visual(swings, audits, prepared, bars, spec)
    visual_seconds = time.perf_counter() - t_visual
    gates["all_24_visual_cases"] = len({c["case_id"] for c in cases}) == 24 \
        and sum(1 for c in {c["case_id"]: c for c in cases}.values() if c["source"] == "REAL") == 13

    # --- tracked CSVs ------------------------------------------------------------------------------------
    for tf, det, aud, inv in timings:
        print(f"runtime {tf}: detector {det:.1f}s audit {aud:.1f}s invariants {inv:.1f}s")
    tracked = {
        "swing_structure_dev_invariants.csv": invariant_frame,
        "swing_structure_dev_continuity_breaks.csv": pd.concat(breaks_all, ignore_index=True),
        "swing_structure_dev_cross_timeframe.csv": pd.DataFrame(xtf_rows),
        "swing_structure_visual_validation_cases.csv": pd.DataFrame(cases),
    }
    gates["no_validation_or_oos_data"] = True  # only the DEVELOPMENT partition file is read
    gates["no_strategy_or_pnl"] = True
    summary = pd.DataFrame(rows)
    tracked["swing_structure_dev_summary.csv"] = summary
    gates["tracked_artifacts_price_free"] = all(not (PRICE_COLUMNS & set(frame.columns)) for frame in tracked.values())
    for name, ok in gates.items():
        summary.loc[len(summary)] = {"section": "machine_gate", "timeframe": "", "orientation": "", "metric": name,
                                     "value": "PASS" if ok else "FAIL"}
    tracked["swing_structure_dev_summary.csv"] = summary
    for name, frame in tracked.items():
        frame.to_csv(OUT / name, index=False)
    total_seconds = time.perf_counter() - started
    print(f"visual generation {visual_seconds:.1f}s; total runner {total_seconds:.1f}s")
    for name, ok in gates.items():
        print(f"GATE {name}: {'PASS' if ok else 'FAIL'}")
    return 0 if all(gates.values()) else 1


# ---------------------------------------------------------------------------
# Metrics (exact SWING_STRUCTURE_SPEC §23 definitions)
# ---------------------------------------------------------------------------


def _positions(segments):
    where = {}
    for index, segment in enumerate(segments):
        for position, end in enumerate(segment["bar_end"]):
            where[pd.Timestamp(end).value] = (index, position)
    return where


def _separated_equal_pairs(swings, segments, right_depth):
    """Next same-side swing in the same segment starting within R observations of the previous plateau end,
    at the same price (spec §23)."""
    where = _positions(segments)
    pairs = 0
    for orientation in (UPPER, LOWER):
        sub = swings[swings["orientation"] == orientation]
        located = sorted((where[pd.Timestamp(r.source_at).value] + where[pd.Timestamp(r.source_end_at).value][1:]
                          + (r.price,)) for r in sub.itertuples(index=False))
        for (seg_i, a_i, b_i, p_i), (seg_j, a_j, _, p_j) in zip(located, located[1:]):
            if seg_i == seg_j and a_j - b_i <= right_depth and p_i == p_j:
                pairs += 1
    return pairs


def _truncated_source_swings(swings, segments):
    where = _positions(segments)
    count = 0
    for row in swings.itertuples(index=False):
        seg, a = where[pd.Timestamp(row.source_at).value]
        _, b = where[pd.Timestamp(row.source_end_at).value]
        count += bool(segments[seg]["is_session_truncated"].iloc[a:b + 1].any())
    return count


def _fingerprint(ids):
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def _cross_timeframe(htf_swings, ltf_swings, htf_obs, ltf_obs, orientation):
    """Spec §23 as-of study (descriptive; HTF and LTF detected independently)."""
    h = htf_swings if orientation == "ALL" else htf_swings[htf_swings["orientation"] == orientation]
    start_of = dict(zip((pd.Timestamp(t).value for t in htf_obs["bar_end"]), htf_obs["bar_start"]))
    ltf_ends = pd.DatetimeIndex(ltf_obs["bar_end"]).tz_convert("UTC").sort_values()
    between, matched, leads, available = [], 0, [], []
    for row in h.itertuples(index=False):
        start = pd.Timestamp(start_of[pd.Timestamp(row.source_at).value]).tz_convert("UTC")
        between.append(int(((ltf_ends > row.source_at) & (ltf_ends <= row.available_at)).sum()))
        same = ltf_swings[(ltf_swings["orientation"] == row.orientation) & (ltf_swings["price"] == row.price)
                          & (ltf_swings["source_at"] > start) & (ltf_swings["source_at"] <= row.source_end_at)]
        if len(same):
            matched += 1
            leads.append((row.available_at - same["available_at"].min()).total_seconds() / 60)
        available.append(int(((ltf_swings["available_at"] > row.source_at)
                              & (ltf_swings["available_at"] <= row.available_at)).sum()))
    return {
        "htf_swing_count": len(h), "same_price_match_count": matched,
        "same_price_match_rate": matched / len(h) if len(h) else 0.0,
        "median_ltf_bars_between_source_and_confirmation": float(pd.Series(between).median()),
        "median_lead_minutes": float(pd.Series(leads).median()) if leads else float("nan"),
        "median_ltf_swings_available_in_interval": float(pd.Series(available).median()),
    }


# ---------------------------------------------------------------------------
# Visual validation (local HTML, price-bearing) + price-free manifest
# ---------------------------------------------------------------------------


def _svg(frame, *, marks=(), vlines=(), shade=(), gaps=(), H=260, W=980, pad=44):
    frame = frame.sort_values("bar_end").reset_index(drop=True)
    prices = list(frame["high"]) + list(frame["low"]) + [m[1] for m in marks]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.08, hi + span * 0.14
    n = len(frame)
    cw = (W - 2 * pad) / max(n, 1)
    y = lambda v: pad + (hi - v) / (hi - lo) * (H - 2 * pad)  # noqa: E731
    ends = [pd.Timestamp(e).value for e in frame["bar_end"]]

    def x_of(ts):
        v = pd.Timestamp(ts).value
        for i, e in enumerate(ends):
            if e >= v:
                return pad + i * cw + cw / 2 if e == v else pad + i * cw
        return W - pad

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    for t0, t1, css in shade:
        x0, x1 = x_of(t0) - cw / 2, x_of(t1) + cw / 2
        out.append(f'<rect x="{x0:.1f}" y="{pad - 6}" width="{max(x1 - x0, 1):.1f}" height="{H - 2 * pad + 6}" class="{css}"/>')
    for g in gaps:
        gx = x_of(g) - cw / 2
        out.append(f'<line x1="{gx:.1f}" x2="{gx:.1f}" y1="{pad}" y2="{H - pad}" class="gap"/>'
                   f'<text x="{gx + 3:.1f}" y="{H - pad - 4}" class="gaplbl">continuity break</text>')
    for i, row in frame.iterrows():
        xc = pad + i * cw + cw / 2
        css = "up" if row["close"] >= row["open"] else "down"
        if not bool(row.get("is_complete", True)):
            css = "inc"
        out.append(f'<line x1="{xc:.1f}" x2="{xc:.1f}" y1="{y(row["high"]):.1f}" y2="{y(row["low"]):.1f}" class="wick"/>')
        top, bot = y(max(row["open"], row["close"])), y(min(row["open"], row["close"]))
        tip = f'{pd.Timestamp(row["bar_end"]).tz_convert(NY):%m-%d %H:%M} H{row["high"]} L{row["low"]}'
        out.append(f'<rect x="{xc - cw * 0.35:.1f}" y="{top:.1f}" width="{max(cw * 0.7, 0.8):.1f}" '
                   f'height="{max(bot - top, 1.2):.1f}" class="{css}"><title>{html.escape(tip)}</title></rect>')
        if n <= 30 or i % max(1, n // 10) == 0:
            out.append(f'<text x="{xc:.1f}" y="{H - 12}" class="tick" text-anchor="middle">'
                       f'{pd.Timestamp(row["bar_end"]).tz_convert(NY):%m-%d %H:%M}</text>')
    used = []
    for ts, price, label, css in marks:
        xc, yc = x_of(ts), y(price)
        out.append(f'<circle cx="{xc:.1f}" cy="{yc:.1f}" r="4.5" class="{css}"/>')
        if label:
            ly = yc - 9
            while any(abs(ly - u[1]) < 11 and abs(xc - u[0]) < 80 for u in used):
                ly -= 11
            used.append((xc, ly))
            out.append(f'<text x="{xc:.1f}" y="{ly:.1f}" class="mlbl {css}" text-anchor="middle">{html.escape(label)}</text>')
    for k, (ts, label, css) in enumerate(vlines):
        xc = x_of(ts)
        out.append(f'<line x1="{xc:.1f}" x2="{xc:.1f}" y1="{pad - 14}" y2="{H - pad}" class="{css}"/>'
                   f'<text x="{xc + 3:.1f}" y="{pad - 16 - 11 * (k % 2)}" class="vl {css}">{html.escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def _ts(value):
    return "" if value is None or pd.isna(value) else pd.Timestamp(value).tz_convert(NY).isoformat()


def _candidate_chart(obs, row, definition, *, context=4, gap=None):
    """Bars around a candidate with plateau, L/R windows, availability and invalidation marked."""
    obs = obs.sort_values("bar_end").reset_index(drop=True)
    end_values = [pd.Timestamp(e).value for e in obs["bar_end"]]
    a = end_values.index(pd.Timestamp(row["source_at"]).value)
    b = end_values.index(pd.Timestamp(row["source_end_at"]).value)
    window = obs.iloc[max(0, a - definition.left_depth - context): b + definition.right_depth + context + 1]
    field = "high" if row["orientation"] == UPPER else "low"
    marks = [(obs["bar_end"].iloc[k], obs[field].iloc[k], "plateau" if k == a else "", "src") for k in range(a, b + 1)]
    shade = [(obs["bar_end"].iloc[max(0, a - definition.left_depth)], obs["bar_end"].iloc[max(0, a - 1)], "lwin")]
    if b + 1 < len(obs):
        shade.append((obs["bar_end"].iloc[b + 1], obs["bar_end"].iloc[min(len(obs) - 1, b + definition.right_depth)], "rwin"))
    vlines = [(row["source_at"], "source_at", "vsrc")]
    if pd.notna(row.get("available_at")):
        vlines.append((row["available_at"], "available_at", "vav"))
    if pd.notna(row.get("invalidating_bar_end")):
        k = end_values.index(pd.Timestamp(row["invalidating_bar_end"]).value)
        marks.append((obs["bar_end"].iloc[k], obs[field].iloc[k], f"strict exceed ({row['invalidating_side']})", "inv"))
    return _svg(window, marks=marks, vlines=vlines, shade=shade, gaps=[gap] if gap is not None else [])


def _synthetic_bars(values_high, values_low, spec, *, contracts=None, absent=()):
    sched = expected_timeframe_schedule([date(2026, 9, 22)], "5m", spec).reset_index(drop=True)
    frames = []
    for k in range(len(values_high)):
        if k in absent:
            continue
        row = sched.iloc[k]
        minutes = pd.date_range(row["bar_start"] + pd.Timedelta(minutes=1), row["bar_end"], freq="min")
        low, high = 20000.0 + values_low[k], 20000.0 + values_high[k]
        frame = pd.DataFrame({"open": low, "high": low, "low": low, "close": low, "volume": 1,
                              "contract": contracts[k] if contracts else "MNQ 12-26"}, index=minutes)
        frame.iloc[0, frame.columns.get_loc("high")] = high
        frames.append(frame)
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="timestamp_et")
    return out


SYNTHETIC_CASES = [
    # id, title, highs, lows (None -> highs-4 ; for LOWER examples highs = lows+4), L, R, orientation, kwargs
    ("A", "A — valid Swing High", [100, 103, 110, 106, 105], None, 2, 2, UPPER, {}),
    ("B", "B — invalidation + successor", [100, 103, 110, 111, 108, 107], None, 2, 2, UPPER, {}),
    ("D", "D — valid Swing Low", [120, 115, 108, 112, 113], [116, 111, 100, 104, 105], 2, 2, LOWER, {}),
    ("EqA", "Equality A — adjacent plateau", [100, 110, 110, 105, 100], None, 1, 2, UPPER, {}),
    ("EqA2", "Equality A′ — three-bar plateau", [105, 110, 110, 110, 106, 104], None, 1, 2, UPPER, {}),
    ("EqB", "Equality B — separated equal highs (L=R=1)", [100, 110, 105, 110, 100], None, 1, 1, UPPER, {}),
    ("EqB2", "Equality B′ — separated equals inside each other's window (L=R=2)", [98, 100, 110, 105, 110, 100, 99],
     None, 2, 2, UPPER, {}),
    ("EqC", "Equality C — separated equal lows (L=R=1)", [114, 104, 109, 104, 114], [110, 100, 105, 100, 110], 1, 1,
     LOWER, {}),
    ("EqD", "Equality D — strict invalidation (L=1, R=2)", [100, 110, 105, 111, 108, 107], None, 1, 2, UPPER, {}),
    ("E", "E — continuity break", [100, 103, 110, 106, 0, 105, 104], None, 2, 2, UPPER, {"absent": {4}}),
    ("F", "F — contract roll", [100, 103, 110, 106, 105], None, 2, 2, UPPER,
     {"contracts": ["MNQ 09-26"] * 3 + ["MNQ 12-26"] * 2}),
]


def _visual(swings, audits, prepared, bars, spec):
    sections, manifest = [], []

    def record(case_id, source, area, case, rows, note, *charts, synthetic_reason=""):
        tag = '<span class="real">REAL DEVELOPMENT</span>' if source == "REAL" else '<span class="syn">SYNTHETIC</span>'
        sections.append(f"<section><h3>{html.escape(case_id)} · {html.escape(area)} — {html.escape(case)} {tag}</h3>"
                        f"<p class='note'>{html.escape(note)}</p>{''.join(charts)}</section>")
        for row in rows:
            manifest.append({
                "case_id": case_id, "source": source, "area": area, "case": case, "timeframe": row.get("timeframe", ""),
                "orientation": row.get("orientation", ""), "status": row.get("status", ""),
                "source_at": _ts(row.get("source_at")), "source_end_at": _ts(row.get("source_end_at")),
                "available_at": _ts(row.get("available_at")), "swing_id": row.get("swing_id") or "",
                "break_reason": row.get("break_reason") or "", "synthetic_reason": synthetic_reason,
            })

    def swing_row(tf, swing):
        hit = audits[tf][audits[tf]["swing_id"] == swing["swing_id"]]
        return hit.iloc[0].to_dict()

    def pick(tf, source_local, orientation):
        frame = swings[tf]
        t = pd.Timestamp(source_local, tz=NY)
        hit = frame[(frame["source_at"] == t) & (frame["orientation"] == orientation)]
        if hit.empty:
            raise RuntimeError(f"named REAL case missing: {tf} {orientation} source {source_local}")
        return hit.iloc[0]

    # 1-2 HTF -> LTF causal boundaries
    for case_id, (htf, ltf, src) in (("R01", ("4H", "5m", "2024-12-13 10:00")), ("R02", ("1H", "15m", "2024-12-23 02:00"))):
        h = pick(htf, src, UPPER)
        span = h["available_at"] - h["source_at"]
        top = prepared[htf][0]
        top = top[(top["bar_end"] >= h["source_at"] - span * 3) & (top["bar_end"] <= h["available_at"] + span * 1.5)]
        low_obs = prepared[ltf][0]
        low_obs = low_obs[(low_obs["bar_end"] >= h["source_at"] - span) & (low_obs["bar_end"] <= h["available_at"] + span * 0.6)]
        lsw = swings[ltf][(swings[ltf]["source_at"] >= h["source_at"] - span) & (swings[ltf]["source_at"] <= h["available_at"] + span * 0.6)]
        start = prepared[htf][0].set_index(pd.DatetimeIndex(prepared[htf][0]["bar_end"]).tz_convert("UTC")).loc[h["source_at"], "bar_start"]
        same = lsw[(lsw["orientation"] == h["orientation"]) & (lsw["price"] == h["price"])
                   & (lsw["source_at"] > start) & (lsw["source_at"] <= h["source_end_at"])].sort_values("available_at")
        marks = [(r.source_at, r.price, "", "lsw" if r.available_at <= h["available_at"] else "lswlate")
                 for r in lsw.itertuples(index=False)]
        rows = [swing_row(htf, h)]
        lead = ""
        if len(same):
            s0 = same.iloc[0]
            marks.append((s0["source_at"], s0["price"], f"{ltf} same-price swing (available {pd.Timestamp(s0['available_at']).tz_convert(NY):%H:%M})", "same"))
            rows.append(swing_row(ltf, s0))
            lead = f" The {ltf} same-price swing was available {h['available_at'] - s0['available_at']} before the {htf} confirmation."
        note = (f"{htf} Swing High source {_ts(h['source_at'])}, available {_ts(h['available_at'])}. Red band: the price exists "
                f"but the {htf} Swing is NOT yet known HTF context; an {ltf} bar may reference the same swing_id only when "
                f"bar_start >= available_at. {ltf} swings are detected independently (blue = available before HTF confirmation)."
                + lead)
        record(case_id, "REAL", "HTF→LTF causal boundary", f"{htf} → {ltf}", rows, note,
               f"<div class='pl'>{htf}</div>",
               _svg(top, marks=[(h["source_at"], h["price"], f"{htf} source", "src")],
                    vlines=[(h["source_at"], "source_at", "vsrc"), (h["available_at"], "available_at", "vav")],
                    shade=[(h["source_at"], h["available_at"], "unknown")]),
               f"<div class='pl'>{ltf} (same period)</div>",
               _svg(low_obs, marks=marks, vlines=[(h["source_at"], f"{htf} source_at", "vsrc"),
                                                   (h["available_at"], f"{htf} available_at", "vav")],
                    shade=[(h["source_at"], h["available_at"], "unknown")], H=280))

    def candidate_case(case_id, area, case, tf, row, note):
        obs = prepared[tf][0]
        record(case_id, "REAL", area, case, [row], note, _candidate_chart(obs, row, REFERENCE))

    def confirmed(tf, orientation, plen=None, truncated=False):
        frame = audits[tf][(audits[tf]["status"] == CONFIRMED) & (audits[tf]["orientation"] == orientation)]
        if plen is not None:
            frame = frame[_plateau_length(frame, prepared[tf][1]) == plen]
        if truncated:
            frame = frame[[_is_truncated(r, prepared[tf][1]) for r in frame.itertuples(index=False)]]
        if frame.empty:
            raise RuntimeError(f"REAL case not reproducible: {tf} {orientation} plen={plen} truncated={truncated}")
        return frame.iloc[len(frame) // 2].to_dict()

    candidate_case("R03", "Clean swing", "4H Swing High", "4H", confirmed("4H", UPPER),
                   "Confirmed 4H pivot: L=R=2 observations, no strict exceed.")
    candidate_case("R04", "Clean swing", "4H Swing Low", "4H", confirmed("4H", LOWER), "Mirror on lows.")
    candidate_case("R05", "Schedule", "Swing on a session-truncated 4H bar", "4H", confirmed("4H", UPPER, truncated=True),
                   "A complete session-clipped 14:00-17:00 bucket is a valid observation.")
    inv = audits["1H"][(audits["1H"]["status"] == INVALIDATED_STRICT_EXCEED) & (audits["1H"]["orientation"] == UPPER)
                       & (audits["1H"]["invalidating_side"] == "RIGHT")]
    if inv.empty:
        raise RuntimeError("REAL case not reproducible: invalidated 1H candidate")
    row = inv.iloc[min(200, len(inv) - 1)].to_dict()
    candidate_case("R06", "Invalidation", "Invalidated 1H candidate", "1H", row,
                   f"Strict exceed inside the right window ({row['invalidating_excess_ticks']} ticks); no canonical swing.")
    candidate_case("R07", "Plateau", "15m two-bar plateau", "15m", confirmed("15m", UPPER, plen=2),
                   "Adjacent equal highs form one plateau source (BAR_SPAN first..last); available R observations after its end.")
    candidate_case("R08", "Plateau", "5m three-bar plateau", "5m", confirmed("5m", UPPER, plen=3),
                   "Three adjacent equal highs: one swing.")
    for case_id, tf, orientation, label in (("R09", "15m", UPPER, "highs"), ("R10", "5m", LOWER, "lows")):
        frame = audits[tf][(audits[tf]["status"] == CONFIRMED) & (audits[tf]["orientation"] == orientation)]
        where = _positions(prepared[tf][1])
        located = sorted((where[pd.Timestamp(r.source_at).value] + where[pd.Timestamp(r.source_end_at).value][1:]
                          + (r.price, i)) for i, r in enumerate(frame.itertuples(index=False)))
        pair = next(((x, y) for x, y in zip(located, located[1:])
                     if x[0] == y[0] and y[1] - x[2] <= REFERENCE.right_depth and x[3] == y[3]), None)
        if pair is None:
            raise RuntimeError(f"REAL case not reproducible: separated equal {label} on {tf}")
        r1, r2 = frame.iloc[pair[0][4]].to_dict(), frame.iloc[pair[1][4]].to_dict()
        obs = prepared[tf][0].sort_values("bar_end").reset_index(drop=True)
        e = [pd.Timestamp(v).value for v in obs["bar_end"]]
        a, b = e.index(pd.Timestamp(r1["source_at"]).value), e.index(pd.Timestamp(r2["source_end_at"]).value)
        field = "high" if orientation == UPPER else "low"
        chart = _svg(obs.iloc[max(0, a - 5): b + 6],
                     marks=[(r1["source_at"], r1["price"], "Swing 1", "src"), (r2["source_at"], r2["price"], "Swing 2", "src")],
                     vlines=[(r1["available_at"], "available 1", "vav"), (r2["available_at"], "available 2", "vav")])
        record(case_id, "REAL", "Separated equality", f"separated equal {label} → two {tf} swings", [r1, r2],
               f"Equal {label} separated by other price action, each inside the other's window: equality is not a strict "
               f"exceed, so both confirm. EQ/REQ classification is downstream.", chart)
    breaks4 = prepared["4H"][2]
    cb = audits["4H"][audits["4H"]["status"] == CONTINUITY_BREAK]
    for case_id, case, frame in (
        ("R11", "4H continuity break", cb),
        ("R12", "4H contract roll", cb[cb["segment_index"].isin(
            [i for i, r in breaks4.iterrows() if bool(r["contract_changed"])])]),
    ):
        if frame.empty:
            raise RuntimeError(f"REAL case not reproducible: {case}")
        row = frame.iloc[min(4, len(frame) - 1)].to_dict() if case_id == "R11" else frame.iloc[0].to_dict()
        segs = prepared["4H"][1]
        seg, nxt = segs[row["segment_index"]], segs[row["segment_index"] + 1]
        window = pd.concat([seg.iloc[-8:], nxt.iloc[:4]])
        field = "high" if row["orientation"] == UPPER else "low"
        brow = breaks4.iloc[row["segment_index"]]
        note = (f"Candidate lacks R observations before the segment ends ({row['break_reason']}; contract changed "
                f"{bool(brow['contract_changed'])}: {seg['contract'].iloc[-1]} → {nxt['contract'].iloc[0]}). Bars after the "
                f"break are never used.")
        record(case_id, "REAL", "Continuity", case, [row], note,
               _svg(window, marks=[(row["source_at"], row["price"], "candidate (CONTINUITY_BREAK)", "inv")],
                    gaps=[nxt["bar_end"].iloc[0]]))
    # 13 nested
    h = pick("4H", "2025-06-30 06:00", UPPER)
    t0, t1 = h["source_at"] - pd.Timedelta(hours=12), h["available_at"] + pd.Timedelta(hours=4)
    charts = []
    rows13 = [swing_row("4H", h)]
    for tf in ("4H", "1H", "5m"):
        obs = prepared[tf][0]
        sw = swings[tf][(swings[tf]["source_at"] >= t0) & (swings[tf]["source_at"] <= t1)]
        charts += [f"<div class='pl'>{tf}</div>",
                   _svg(obs[(obs["bar_end"] >= t0) & (obs["bar_end"] <= t1)],
                        marks=[(r.source_at, r.price, ("H" if r.orientation == UPPER else "L") if tf != "5m" else "",
                                "src" if r.orientation == UPPER else "lsw") for r in sw.itertuples(index=False)])]
    record("R13", "REAL", "Nesting", "nested 4H / 1H / 5m swings (independent detection)", rows13,
           "Each timeframe is detected only from its own observations; identical prices across timeframes stay separate "
           "facts; no parent/child links.", *charts)

    # synthetic normative examples (production detector + audit)
    for k, (cid, title, highs, lows, left, right, orientation, kwargs) in enumerate(SYNTHETIC_CASES, start=1):
        lows = lows if lows is not None else [v - 4 for v in highs]
        if orientation == LOWER and highs is None:
            highs = [v + 4 for v in lows]
        definition = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=left, right_depth=right)
        sbars = _synthetic_bars(highs, lows, spec, **kwargs)
        audit = audit_swing_candidates(sbars, "5m", spec, definition, instrument_id=INSTRUMENT)
        canonical = build_swing_points(sbars, "5m", spec, definition, instrument_id=INSTRUMENT)
        decisive = (audit["status"].isin([CONFIRMED, CONTINUITY_BREAK])
                    | ((audit["status"] == INVALIDATED_STRICT_EXCEED) & (audit["invalidating_side"] == "RIGHT")))
        focus = audit[(audit["orientation"] == orientation) & decisive]
        obs, segs, _ = prepare_swing_observations(sbars, "5m", spec)
        field = "high" if orientation == UPPER else "low"
        marks = [(r.source_at, r.price, f"{r.status}", "src" if r.status == CONFIRMED else "inv")
                 for r in focus.itertuples(index=False)]
        vlines = [(r.available_at, "available_at", "vav") for r in focus.itertuples(index=False) if r.status == CONFIRMED]
        gaps = [s["bar_end"].iloc[0] for s in segs[1:]]
        note = (f"L={left}, R={right}; values {highs if orientation == UPPER else lows}. Audit: "
                + "; ".join(f"{_ts(r.source_at)[11:16]}–{_ts(r.source_end_at)[11:16]} {r.status}"
                            + (f" (break {r.break_reason})" if pd.notna(r.break_reason) else "")
                            for r in focus.itertuples(index=False))
                + f". Canonical rows: {len(canonical[canonical['orientation'] == orientation])}.")
        record(f"S{k:02d}", "SYNTHETIC", "Normative example", title, [r._asdict() for r in focus.itertuples(index=False)],
               note, _svg(obs, marks=marks, vlines=vlines, gaps=gaps),
               synthetic_reason="exact normative example from SWING_STRUCTURE_SPEC §7.3 / §8-§10")

    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swing Structure Validation</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--muted:#666;--up:#1a7f5a;--down:#c0392b;--inc:#d99a00;--acc:#2f5bd3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#9a9a9a;--up:#3ec48e;--down:#ef6b5b;--inc:#e3b341;--acc:#7aa2ff}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;max-width:1020px;margin:0 auto;padding:16px}}
h1{{font-size:20px}} h3{{font-size:15px;margin:26px 0 4px}} .note{{color:var(--muted);margin:2px 0 6px}} .pl{{font-size:12px;color:var(--muted);margin-top:6px}}
.wick{{stroke:var(--muted)}} .up{{fill:var(--up)}} .down{{fill:var(--down)}} .inc{{fill:var(--inc)}} .tick{{fill:var(--muted);font-size:10px}}
.src{{fill:var(--acc)}} .inv{{fill:#c0392b}} .lsw{{fill:var(--acc);opacity:.75}} .lswlate{{fill:var(--muted);opacity:.6}} .same{{fill:#d99a00}}
.mlbl{{font-size:10px}} text.src{{fill:var(--acc)}} text.inv{{fill:#c0392b}} text.same{{fill:#b07800}}
.vsrc{{stroke:var(--acc);stroke-dasharray:4 3}} .vav{{stroke:var(--fg);stroke-dasharray:2 2}} .vl{{font-size:10px}} text.vsrc{{fill:var(--acc)}} text.vav{{fill:var(--fg)}}
.unknown{{fill:rgba(192,57,43,.13)}} .lwin{{fill:rgba(47,91,211,.08)}} .rwin{{fill:rgba(26,127,90,.10)}} .gap{{stroke:#c0392b;stroke-width:2}} .gaplbl{{fill:#c0392b;font-size:10px}}
.syn{{background:#d99a00;color:#000;border-radius:4px;padding:1px 6px;font-size:11px}} .real{{background:#2f5bd3;color:#fff;border-radius:4px;padding:1px 6px;font-size:11px}}
</style></head><body><h1>Swing Structure 3.2 — SW-I3 implementation visual validation</h1>
<p class="note">LOCAL ONLY — contains market prices (Git-ignored). Production detector (build_swing_points) + independent candidate
audit, DEVELOPMENT, explicit 2/2 reference definition (synthetic examples use their stated depths). Blue band = left window,
green band = right window, dashed line = available_at. Machine-validation evidence; human visual approval pending.</p>
{''.join(sections)}</body></html>"""
    (OUT / "swing_structure_visual_validation.html").write_text(page, encoding="utf-8")
    return manifest


def _plateau_length(frame, segments):
    where = _positions(segments)
    return pd.Series([where[pd.Timestamp(r.source_end_at).value][1] - where[pd.Timestamp(r.source_at).value][1] + 1
                      for r in frame.itertuples(index=False)], index=frame.index)


def _is_truncated(row, segments):
    where = _positions(segments)
    seg, a = where[pd.Timestamp(row.source_at).value]
    _, b = where[pd.Timestamp(row.source_end_at).value]
    return bool(segments[seg]["is_session_truncated"].iloc[a:b + 1].any())


if __name__ == "__main__":
    raise SystemExit(main())
