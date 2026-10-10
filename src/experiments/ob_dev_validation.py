"""Order Block / Breaker / Mitigation — OB-I5 DEVELOPMENT validation runner (machine validation; read-only).

    .\\.venv\\Scripts\\python.exe -m src.experiments.ob_dev_validation            # FULL tier (final evidence)
    .\\.venv\\Scripts\\python.exe -m src.experiments.ob_dev_validation --fast     # FAST tier (one DEV week)
    .\\.venv\\Scripts\\python.exe -m src.experiments.ob_dev_validation --start 2024-08-01 --end 2024-08-31

DEVELOPMENT only.  Production path ``build_order_blocks`` on six timeframes at the OB default Swing depths 1/1.
Gates: frozen dependency parity (public Swing detector at the OB depths; FVG zone fingerprint equal to the frozen
FVG baseline on full DEV), 1m continuity baseline, frozen sources unchanged, OB-INV-* = 0, the independent causal
reference over every timeframe (full coverage), payload-level prefix replays around admissions, swing
confirmation, ordinary failure, successor admission and gaps (contract change: synthetic only — DEVELOPMENT has
none), shuffled-input determinism on a DEVELOPMENT month, price-free tracked artifacts.  Writes price-free CSVs and
a local, Git-ignored visual HTML.  No PnL, strategy, optimization, backtest, VALIDATION or OOS data.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import time

import pandas as pd

from src.data.sessions import load_session_spec
from src.experiments.fvg_dev_validation import (FAST_WINDOW, NY, PeakMemory, _gate, parse_args, provenance,
                                                select_window)
from src.experiments.fvg_visual import synthetic_bars
from src.experiments.ob_visual import Facts, build_cases, manifest_rows, page, synthetic_cases
from src.experiments.swing_structure_dev_validation import EXPECTED_CONTINUITY, load_development_bars
from src.ict_blocks.audit import canonical_rows, full_reference, invariants, prefix_mismatches, reconcile
from src.ict_blocks.pipeline import build_order_blocks
from src.ict_blocks.inputs import swing_definition
from src.market_structure.swing_detector import build_swing_points

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTRUMENT = "MNQ"
FULL_CUTOFF = pd.Timestamp("2025-06-30 17:00", tz=NY)
FROZEN_PATHS = ("src/data", "src/market_structure", "src/state", "src/features", "src/liquidity", "config", "src/fvg")
FROZEN_FVG_ZONE_FP = "735995a88d72336ec43dc8906983c18da3d186c707f97699884c1cfd93efa9a7"   # D-148 freeze note
SHUFFLE_WINDOW = ("2024-09-02", "2024-09-30")
PRICE_WORDS = ("price", "open", "high", "low", "close", "ticks", "lower", "upper", "midpoint", "ohlc")
FULL_DEV_ONLY = ("minute_episodes_equal_continuity_segments", "fvg_zone_fingerprint_equals_frozen_fvg")
# lifecycle / rejection paths and the synthetic fixtures (tests/ob_fixtures.py) that exercise each
SYNTHETIC_PATHS = {
    "ORDINARY_ADMITTED": "EX151 (+ mirrored), PLATEAU_OK, RALLY, HIGHER_LOW, INTERACT, LONG_VISIT",
    "BREAKER": "BREAKER (+ mirrored), CONCURRENT, NO_PRIOR source episodes, N2_DELAYED",
    "MITIGATION": "MITIGATION (+ mirrored)",
    "FAILED_FINAL|EQUAL_EXTREME": "EQUAL (+ mirrored)",
    "FAILED_FINAL|RAID_WITH_LESS_EXTREME_C": "RAID_LOWER_C (+ mirrored; raid on the break bar)",
    "FAILED_FINAL|NO_PRIOR_EXTREME": "NO_PRIOR (+ mirrored)",
    "FAILED_FINAL|NO_REVERSAL_SWING": "EARLY_RAID (+ mirrored)",
    "FAILED_AWAITING_CLASSIFICATION": "N2_DELAYED, N2_INVALID (N = 2 only; unreachable at N = 1)",
    "FAILED_FINAL|QUALIFIED_BUT_INVALID_BEFORE_ADMISSION": "N2_INVALID (N = 2 only)",
    "TERMINATED_DATA_GAP": "BREAKER with a missing bar (gap)",
    "PENDING_ADJUSTMENT": "BREAKER with a pure roll (roll); none on DEVELOPMENT",
    "SUPERSEDED": "test_ob_deadlines candidate_confirmed / plateau_confirmed",
    "REJECTED|SOURCE_BODY_LT_4_TICKS": "with_source 0 / 1 / 3 ticks, PLATEAU_DOJI",
    "REJECTED|SOURCE_DIRECTION_MISMATCH": "with_source bullish candle",
    "REJECTED|NO_DEPARTURE_FVG_IN_WINDOW": "HIGHER_LOW (bearish episode)",
    "REJECTED|NOT_VALIDATED_IN_WINDOW": "BREAKER (bearish episode at k1)",
    "REJECTED|ALREADY_INVALID_BEFORE_ADMISSION": "none (DEVELOPMENT only)",
    "GAP_BEYOND_REGION": "INTERACT (+ mirrored)",
}
TABLES = ("regions", "episodes", "evidence", "blocks", "stages", "lifecycle", "motifs", "visits", "interactions",
          "depth_versions", "transitions", "warnings", "pending")

# synthetic fixtures for the visual package (5m rows relative to 20,000; same as tests/ob_fixtures.py)
_HEAD = [(100, 101, 99, 100.5), (100.5, 120, 100, 119), (119, 119.5, 110, 111), (111, 112, 104, 105),
         (105, 106, 99, 100), (100, 112, 100, 111), (111, 118, 111, 117)]
_N2 = [(100, 101, 99, 100.5), (100.5, 115, 100, 114), (114, 120, 113, 119), (119, 119.5, 110, 111),
       (111, 112, 104, 105), (105, 106, 99, 100), (100.5, 110, 100.5, 109), (109, 113, 101, 112.5),
       (112.5, 118, 112.5, 117)]
_EX151 = [(104, 106, 103, 105), (105, 105.5, 101, 102), (102, 103, 99, 100), (100, 112, 100, 108),
          (108, 113, 102, 111), (111, 117, 110, 116), (116, 119, 114, 118), (118, 118.5, 117, 118)]
SYNTHETIC = {
    "BREAKER": (_HEAD + [(117, 123, 113, 122), (122, 124, 120, 121), (121, 121.5, 108, 109), (109, 110, 98, 98.5),
                         (98.5, 101, 97, 100), (100, 106, 99.5, 105.5), (105.5, 106, 104, 105)], 1, {}),
    "MITIGATION": (_HEAD + [(117, 119, 113, 118), (118, 119.5, 116, 117), (117, 117.5, 108, 109), (109, 110, 98, 98.5),
                            (98.5, 101, 97, 100), (100, 103, 99.5, 102), (102, 104.5, 101, 104)], 1, {}),
    "EQUAL": (_HEAD + [(117, 119, 113, 118), (118, 120, 116, 117), (117, 117.5, 108, 109), (109, 110, 98, 98.5),
                       (98.5, 101, 97, 100)], 1, {}),
    "RAID_LOWER_C": (_HEAD + [(117, 119, 113, 118), (118, 119.5, 116, 117), (117, 117.5, 108, 109), (109, 122, 98, 98.5),
                              (98.5, 101, 97, 100)], 1, {}),
    "N2_DELAYED": (_N2 + [(117, 123, 113, 122), (122, 124, 120, 121), (121, 121.5, 98, 98.5), (98.5, 100, 97, 99),
                          (99, 103, 98, 102), (102, 106, 101, 105.5)], 2, {}),
    "N2_INVALID": (_N2 + [(117, 123, 113, 122), (122, 124, 120, 121), (121, 121.5, 98, 98.5), (98.5, 106, 97, 105.5),
                          (105.5, 106, 103, 104)], 2, {}),
    "CONCURRENT": (_HEAD + [(117, 123, 113, 122), (120, 124, 119.5, 123.5), (123, 123.5, 112, 113), (113, 114, 98, 98.5),
                            (98.5, 101, 97, 100), (100, 103, 99.5, 102)], 1, {}),
    "BODY3": (_EX151[:2] + [(101, 103, 99, 100.25)] + _EX151[3:], 1, {}),
    "ROLL": (_HEAD + [(117, 123, 113, 122), (122, 124, 120, 121), (121, 121.5, 108, 109), (109, 110, 98, 98.5),
                      (98.5, 101, 97, 100), (100, 106, 99.5, 105.5), (105.5, 106, 104, 105)], 1,
             {"contracts": ["MNQ 09-26"] * 9 + ["MNQ 12-26"] * 5}),
    "ORDINARY": (_EX151, 1, {}),
}


def _mirror(rows, axis=200.0):
    return [(axis - o, axis - l, axis - h, axis - c) for o, h, l, c in rows]


SYNTHETIC["ORDINARY_M"] = (_mirror(_EX151), 1, {})
SYNTHETIC["BREAKER_M"] = (_mirror(SYNTHETIC["BREAKER"][0]), 1, {})
SYNTHETIC["MITIGATION_M"] = (_mirror(SYNTHETIC["MITIGATION"][0]), 1, {})


def build_synthetic(name, spec):
    rows, depth, kw = SYNTHETIC[name]
    bars, sched = synthetic_bars(rows, "5m", spec, **kw)
    return build_order_blocks(bars, spec, instrument_id=INSTRUMENT, replay_cutoff=sched.iloc[len(rows) - 1]["bar_end"],
                              timeframes=("5m",), left_depth=depth, right_depth=depth)


def _fp(values) -> str:
    return hashlib.sha256("\n".join(sorted(map(str, values))).encode()).hexdigest()


def main(argv=None) -> int:
    args = parse_args(argv)
    fast = args.start is not None
    started = time.perf_counter()
    mem = PeakMemory()
    spec = load_session_spec()
    bars = load_development_bars()
    cutoff, out_dir = FULL_CUTOFF, PROJECT_ROOT / "reports" / "validation"
    if fast:
        bars = select_window(bars, args.start, args.end)
        cutoff = bars.index.max()
        out_dir = PROJECT_ROOT / "reports" / "validation" / "ob_fast" / f"{args.start}_{args.end}"
    if args.out:
        out_dir = Path(args.out).resolve()
    tier = f"FAST {args.start} .. {args.end}" if fast else "FULL DEVELOPMENT"
    print(f"tier {tier}; outputs {out_dir}", flush=True)
    rows, gates, timings = [], {}, []
    add = lambda section, tf, metric, value: rows.append({"section": section, "timeframe": tf, "metric": metric,  # noqa: E731
                                                          "value": value})
    add("source", "", "tier", tier)
    add("source", "", "canonical_1m_rows", len(bars))
    add("source", "", "replay_cutoff", cutoff.isoformat())
    prov = provenance()
    prov["ob_source_sha256"] = _src_fp()
    for k, v in prov.items():
        add("provenance", "", k, v)
    print("provenance", prov, flush=True)

    t0 = time.perf_counter()
    run = build_order_blocks(bars, spec, instrument_id=INSTRUMENT, replay_cutoff=cutoff)
    timings.append({"stage": "build_order_blocks", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    print(f"build {timings[-1]['seconds']}s peak {mem.mb()} MB", flush=True)
    E = run.engine

    # --- dependency parity and baselines ---------------------------------------------------------
    ok = True
    for tf, frame_ in run.swing_frames.items():
        direct = build_swing_points(bars.loc[bars.index <= cutoff], tf, spec, swing_definition(1, 1), instrument_id=INSTRUMENT)
        direct = direct.loc[(pd.to_datetime(direct["available_at"], utc=True) <= cutoff).to_numpy()]
        ok &= _fp(frame_["swing_id"]) == _fp(direct["swing_id"]) and set(frame_["left_depth"]) <= {1}
        add("dependency", tf, "swing_facts_1_1", len(frame_))
        add("dependency", tf, "fvg_facts", int((run.fvg_zones["timeframe"] == tf).sum()))
    gates["swing_parity_public_detector_at_ob_depths"] = bool(ok)
    zone_fp = _fp(run.fvg_zones["zone_id"])
    add("dependency", "", "fvg_zone_id_sha256", zone_fp)
    eps = run.tape.episodes
    if fast:
        for g in FULL_DEV_ONLY:
            gates[g] = None
    else:
        gates["fvg_zone_fingerprint_equals_frozen_fvg"] = zone_fp == FROZEN_FVG_ZONE_FP
        gates["minute_episodes_equal_continuity_segments"] = (len(eps), sum(e.reset_at is not None for e in eps)) == \
            EXPECTED_CONTINUITY["1m"][1:]
    gates["frozen_sources_unchanged_vs_main"] = subprocess.run(
        ["git", "diff", "--quiet", "main", "--", *FROZEN_PATHS], cwd=PROJECT_ROOT).returncode == 0
    _summarize(run, add)

    # --- invariants and independent reference ----------------------------------------------------
    t0 = time.perf_counter()
    inv = invariants(run)
    timings.append({"stage": "invariants", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    gates["all_invariants_zero"] = int(inv["violations"].sum()) == 0
    print(f"invariants {timings[-1]['seconds']}s violations {int(inv['violations'].sum())}", flush=True)
    t0 = time.perf_counter()
    rec = reconcile(run, full_reference(run))
    rec.insert(1, "method", "FULL_RUN_INDEPENDENT_REFERENCE")
    timings.append({"stage": "reference", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    bad = int(rec[["missing", "extra"]].to_numpy().sum())
    gates["engine_equals_independent_reference_all_timeframes"] = bad == 0
    print(f"reference {timings[-1]['seconds']}s mismatches {bad}", flush=True)

    # --- prefix replays ----------------------------------------------------------------------------
    prefix_rows = []
    t0 = time.perf_counter()
    for label, cut in _prefix_cutoffs(run):
        tp = time.perf_counter()
        part = build_order_blocks(bars, spec, instrument_id=INSTRUMENT, replay_cutoff=cut)
        mm = prefix_mismatches(run, part)
        prefix_rows.append({"case": label, "replay_cutoff": cut.isoformat(), "mismatches": sum(mm.values()),
                            **{f"m_{k}": v for k, v in mm.items()}, "seconds": round(time.perf_counter() - tp, 1)})
        print(f"prefix {label}: {sum(mm.values())} mismatches", flush=True)
        del part
    prefix = pd.DataFrame(prefix_rows)
    gates["prefix_replay_equivalence_development"] = bool(len(prefix)) and int(prefix["mismatches"].sum()) == 0
    timings.append({"stage": "prefix_replays", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})

    # --- shuffled-input determinism (one DEVELOPMENT month, or the fast window) -------------------
    t0 = time.perf_counter()
    sb = bars if fast else select_window(load_development_bars(), *SHUFFLE_WINDOW)
    scut = sb.index.max()
    base = build_order_blocks(sb, spec, instrument_id=INSTRUMENT, replay_cutoff=scut)
    shuffle_counts = _path_counts(base)
    shuffle_ok = True
    for seed in (11, 23):
        other = build_order_blocks(sb, spec, instrument_id=INSTRUMENT, replay_cutoff=scut, shuffle_seed=seed)
        shuffle_ok &= all(canonical_rows(getattr(base.engine, t)) == canonical_rows(getattr(other.engine, t)) for t in TABLES)
    gates["shuffled_dependency_rows_deterministic"] = bool(shuffle_ok)
    add("determinism", "", "shuffle_window", "fast window" if fast else f"{SHUFFLE_WINDOW[0]} .. {SHUFFLE_WINDOW[1]}")
    add("determinism", "", "shuffle_window_blocks", len(base.engine.blocks))
    timings.append({"stage": "shuffle_determinism", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    del base

    # --- visual package ----------------------------------------------------------------------------
    t0 = time.perf_counter()
    dev_cases = build_cases(run)
    syn_cases, syn_facts = synthetic_cases(lambda name: build_synthetic(name, spec))
    cases = dev_cases + syn_cases
    header = [{"run_id": run.run_id, "tier": tier, "replay_cutoff": cutoff.isoformat(), "blocks": len(E.blocks),
               "cases": len(cases), **prov}]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ob_visual_validation.html").write_text(page(cases, {"dev": Facts(run), **syn_facts}, header), encoding="utf-8")
    timings.append({"stage": "visual", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    gates["visual_cases_generated"] = len(dev_cases) >= (1 if fast else 10) and len(syn_cases) >= 13
    add("visual", "", "dev_cases", len(dev_cases))
    add("visual", "", "synthetic_cases", len(syn_cases))
    add("visual", "", "dev_case_ids", ",".join(c.case_id for c in dev_cases))

    gates["no_validation_or_oos_data"] = True
    gates["no_strategy_pnl_backtest_or_optimization"] = True
    timings.append({"stage": "total", "seconds": round(time.perf_counter() - started, 1), "peak_rss_mb": mem.mb()})
    build_s = timings[0]["seconds"]
    slow = [t["stage"] for t in timings if t["stage"] not in ("build_order_blocks", "prefix_replays", "total",
                                                                "shuffle_determinism") and t["seconds"] > max(build_s, 30)]
    add("runtime", "", "stages_slower_than_build", ",".join(slow) or "none")
    coverage = coverage_frame(run, rec, prefix, "fast window" if fast else f"{SHUFFLE_WINDOW[0]} .. {SHUFFLE_WINDOW[1]}",
                              shuffle_counts, tier)
    absent_1d = sorted(set(rec.loc[(rec["timeframe"] == "1D") & (rec["reference"] == 0), "category"]))
    add("coverage", "1D", "reference_categories_absent", ",".join(absent_1d) or "none")
    tracked = {"ob_dev_invariants.csv": inv, "ob_dev_reconciliation.csv": rec, "ob_dev_prefix_replay.csv": prefix,
               "ob_dev_evidence_coverage.csv": coverage,
               "ob_dev_runtime.csv": pd.DataFrame(timings),
               "ob_visual_validation_cases.csv": pd.DataFrame(manifest_rows(cases))}
    summary = pd.DataFrame(rows)
    tracked["ob_dev_summary.csv"] = summary
    gates["tracked_artifacts_price_free"] = all(not any(w in c.lower() for c in f_.columns for w in PRICE_WORDS)
                                                for f_ in tracked.values())
    for name, ok_ in gates.items():
        summary.loc[len(summary)] = {"section": "machine_gate", "timeframe": "", "metric": name, "value": _gate(ok_)}
    for name, frame_ in tracked.items():
        frame_.to_csv(out_dir / name, index=False)
    print(f"total {round(time.perf_counter() - started, 1)}s peak {mem.mb()} MB")
    for name, ok_ in gates.items():
        print(f"GATE {name}: {_gate(ok_)}")
    if slow:
        print(f"WARNING stages slower than the build: {', '.join(slow)}")
    return 1 if any(v is False for v in gates.values()) else 0


def _path_counts(run) -> dict:
    E = run.engine
    tf_of = dict(zip(E.blocks["block_id"], E.blocks["timeframe"]))
    out: dict = {}

    def bump(path, tf):
        out.setdefault(path, {}).setdefault(tf, 0)
        out[path][tf] += 1
    for b in E.blocks.itertuples(index=False):
        bump("ORDINARY_ADMITTED", b.timeframe)
    for r in E.lifecycle.itertuples(index=False):
        tf = tf_of[r.block_id]
        if r.to_state in ("BREAKER", "MITIGATION", "FAILED_AWAITING_CLASSIFICATION", "TERMINATED_DATA_GAP",
                          "PENDING_ADJUSTMENT"):
            bump(r.to_state, tf)
        elif r.to_state == "FAILED_FINAL":
            bump(f"FAILED_FINAL|{r.reason}", tf)
    for r in E.episodes.itertuples(index=False):
        if r.status == "SUPERSEDED":
            bump("SUPERSEDED", r.timeframe)
        elif r.status == "REJECTED":
            bump(f"REJECTED|{r.reason}", r.timeframe)
    for r in E.interactions[E.interactions["kind"] == "GAP_BEYOND_REGION"].itertuples(index=False):
        bump("GAP_BEYOND_REGION", tf_of[r.block_id])
    return out


def coverage_frame(run, rec, prefix, shuffle_label, shuffle_counts, tier) -> pd.DataFrame:
    """Evidence classes kept distinct: FULL_DEV (or FAST window) counts per path x timeframe (zero cells kept),
    the reference reconciliation cells, the shuffled-input window, each prefix cutoff, and synthetic fixtures."""
    tfs = ("1m", "5m", "15m", "1H", "4H", "1D")
    rows = []
    cls = "FULL_DEV" if tier.startswith("FULL") else "FAST_WINDOW"
    counts = _path_counts(run)
    for path in SYNTHETIC_PATHS:
        for tf in tfs:
            rows.append({"evidence_class": cls, "item": path, "timeframe": tf, "count": counts.get(path, {}).get(tf, 0),
                         "note": ""})
        rows.append({"evidence_class": "SYNTHETIC", "item": path, "timeframe": "5m", "count": None,
                     "note": SYNTHETIC_PATHS[path]})
    for r in rec.itertuples(index=False):
        rows.append({"evidence_class": f"{cls}_REFERENCE", "item": f"reconcile|{r.category}", "timeframe": r.timeframe,
                     "count": int(r.reference), "note": f"mismatches {int(r.missing) + int(r.extra)}; fields: {r.compared_fields}"})
    for r in prefix.itertuples(index=False):
        rows.append({"evidence_class": "PREFIX_EARLY_DEV", "item": f"prefix|{r.case}", "timeframe": "all",
                     "count": int(r.mismatches), "note": f"cutoff {r.replay_cutoff}; all tables + views compared"})
    for path, per in shuffle_counts.items():
        rows.append({"evidence_class": "SHUFFLE_WINDOW", "item": path, "timeframe": "all", "count": sum(per.values()),
                     "note": shuffle_label})
    return pd.DataFrame(rows)


def _src_fp() -> str:
    h = hashlib.sha256()
    files = sorted(PROJECT_ROOT.glob("src/ict_blocks/*.py")) + sorted(PROJECT_ROOT.glob("src/experiments/ob_*.py"))
    for p in files:
        h.update(p.relative_to(PROJECT_ROOT).as_posix().encode() + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def _summarize(run, add) -> None:
    E = run.engine
    add("run", "", "run_id", run.run_id)
    for k, v in E.counters.items():
        add("counters", "", k, v)
    ep = E.episodes
    for (tf, st), n in ep.groupby(["timeframe", "status"]).size().items():
        add("episodes", tf, st, int(n))
    for (tf, reason), n in ep.dropna(subset=["reason"]).groupby(["timeframe", "reason"]).size().items():
        add("episode_reasons", tf, reason, int(n))
    b = E.blocks
    for (tf, d), n in b.groupby(["timeframe", "ordinary_direction"]).size().items():
        add("blocks", tf, d, int(n))
    st = E.stages.merge(b[["block_id", "timeframe"]], on="block_id", how="left", suffixes=("", "_b"))
    for (tf, kind), n in st.groupby(["timeframe", "stage_kind"]).size().items():
        add("stages", tf, kind, int(n))
    lc = E.lifecycle.merge(b[["block_id", "timeframe"]], on="block_id", how="left")
    for (tf, to, reason), n in lc.groupby(["timeframe", "to_state", "reason"]).size().items():
        add("lifecycle", tf, f"{to}|{reason}", int(n))
    mo = E.motifs.merge(b[["block_id", "timeframe"]], on="block_id", how="left")
    for (tf, outcome), n in mo.groupby(["timeframe", mo["outcome"].astype(str)]).size().items():
        add("motifs", tf, outcome, int(n))
    add("motifs", "", "raid_observed", int(mo["raid_observed"].sum()) if len(mo) else 0)
    add("motifs", "", "failed_awaiting_classification_transitions",
        int((E.lifecycle["to_state"] == "FAILED_AWAITING_CLASSIFICATION").sum()))
    it = E.interactions.merge(E.stages[["stage_id", "stage_kind"]], on="stage_id", how="left")
    for (kind, ev), n in it.groupby(["stage_kind", "kind"]).size().items():
        add("interactions", "", f"{kind}|{ev}", int(n))
    add("interactions", "", "visits", len(E.visits))
    add("interactions", "", "depth_versions", len(E.depth_versions))
    add("data", "", "data_gap_warnings", len(E.warnings))
    add("data", "", "pending_adjustment_blocks", len(E.pending))
    for name, col in (("block_id", b["block_id"]), ("source_region_id", E.regions["source_region_id"]),
                      ("stage_id", E.stages["stage_id"]), ("episode_id", ep["episode_id"]),
                      ("transition_id", E.transitions["transition_id"]), ("motif_id", E.motifs["motif_id"])):
        add("identity", "", f"{name}_sha256", _fp(col))


def _prefix_cutoffs(run):
    """Cutoffs around each event class in the early DEVELOPMENT episodes (affordable rebuilds)."""
    E = run.engine
    one = pd.Timedelta(minutes=1)
    eps = run.tape.episodes
    window_end = pd.Timestamp(int(eps[min(4, len(eps) - 1)].end[-1]), tz="UTC")
    out = []

    def early(series):
        s = series[series <= window_end].sort_values()
        return None if s.empty else s.iloc[len(s) // 2]
    b5 = E.blocks[E.blocks["timeframe"] == "5m"]
    t = early(b5["ordinary_available_at"])
    if t is not None:
        out += [("admission_5m_at", t), ("admission_5m_minus_1m", t - one)]
    t = early(E.episodes[E.episodes["timeframe"] == "15m"]["opened_at"])
    if t is not None:
        out.append(("swing_confirmation_15m_at", t))
    t = early(E.lifecycle[E.lifecycle["reason"].isin(["BREAKER_MOTIF", "MITIGATION_MOTIF", "NO_PRIOR_EXTREME",
                                                      "NO_REVERSAL_SWING", "EQUAL_EXTREME", "RAID_WITH_LESS_EXTREME_C"])]["at"])
    if t is not None:
        out += [("ordinary_failure_and_successor_at", t), ("ordinary_failure_minus_1m", t - one)]
    t = early(E.lifecycle[E.lifecycle["reason"] == "MITIGATION_MOTIF"]["at"])
    if t is not None:
        out.append(("mitigation_admission_at", t))
    t = early(E.lifecycle[E.lifecycle["reason"] == "SUCCESSOR_CLOSE_BEYOND"]["at"])
    if t is not None:
        out.append(("successor_retirement_at", t))
    gap = next((x for x in eps if x.reset_reason == "DATA_GAP"), None)
    if gap is not None:
        g = pd.Timestamp(gap.reset_at, tz="UTC")
        out += [("gap_onset", g), ("inside_gap", g + pd.Timedelta(minutes=30))]
    return [(label, pd.Timestamp(t).tz_convert(NY)) for label, t in out]


if __name__ == "__main__":
    raise SystemExit(main())
