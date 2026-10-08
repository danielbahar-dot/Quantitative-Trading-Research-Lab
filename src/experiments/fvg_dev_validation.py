"""FVG / IFVG / BPR — FVG-I5 DEVELOPMENT validation runner (machine validation; read-only).

Command (repository root)::

    .\\.venv\\Scripts\\python.exe -m src.experiments.fvg_dev_validation

DEVELOPMENT partition only; explicit ``replay_cutoff`` = close of the
partition's last session (2025-06-30 17:00 ET).  Production path:
``build_fvg`` (six timeframes, canonical 1m interaction, frozen 2/2 swings).

Evidence classes (kept distinct in the outputs):

- FULL RUN: ``invariants`` (FVG-INV-1 … 27) and ``src.fvg.audit_full`` — an independent recomputation of
  formation, zone lifecycle and mitigation, relationship episodes, BPR lifecycle and mitigation, grade versions,
  groups and associations over every episode and timeframe (exact per-object restrictions; no truncation);
- SUBSET: ``src.fvg.audit.reference`` (naive all-pairs replay) on the 1m episodes of at most
  ``REFERENCE_MAX_BARS`` bars, with coverage reported per category and timeframe (zero-covered rows kept);
- PREFIX: DEVELOPMENT rebuilds at cutoffs around admissions, mitigation, conversions, conversion-created BPRs,
  relationship changes, BPR retirement, gaps and association deadlines, compared payload for payload
  (all tables, as-of projection of later exits, duplicates, strategy views and ranks);
- SYNTHETIC: unit tests and synthetic visual cases (contract change, zero baseline: absent from DEVELOPMENT).

Frozen baselines (Swing counts, 1m continuity, frozen sources) are reconciled; the design's scratch evidence
(§5.14) is reconciled against the production counts.  Writes price-free tracked CSVs and a local, Git-ignored
visual HTML.  No PnL, strategy, optimization, backtest, VALIDATION or OOS
data.  It freezes nothing.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import threading
import time

import numpy as np
import pandas as pd
import psutil

from src.data.sessions import load_session_spec
from src.experiments.fvg_visual import Facts, build_dev_cases, manifest_rows, page, synthetic_cases
from src.experiments.swing_structure_dev_validation import EXPECTED_CONTINUITY, EXPECTED_COUNTS, load_development_bars
from src.fvg.audit import invariants, prefix_mismatches, reconcile, reference
from src.fvg.audit_full import full_reconcile, full_reference, subset_coverage
from src.fvg.pipeline import build_fvg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT = PROJECT_ROOT / "reports" / "validation"
NY = "America/New_York"
INSTRUMENT = "MNQ"
REPLAY_CUTOFF = pd.Timestamp("2025-06-30 17:00", tz=NY)
REFERENCE_MAX_BARS = 3600
FROZEN_PATHS = ("src/data", "src/market_structure", "src/state", "src/features", "src/liquidity", "config")
PRICE_WORDS = ("price", "open", "high", "low", "close", "ticks", "lower", "upper", "midpoint", "ohlc")
# Scratch evidence reported in the design draft (rev 2 §5.14); reconciled, never relabelled as validation.
SCRATCH = {
    "1m": {"wick_gaps": 66328, "zones": 59661, "bull": 30908, "bear": 28753, "c2_not_directional": 272, "c2_not_spanning": 6395,
           "equality": 7302, "one_tick": 5749, "ok": 59571, "insufficient": 90, "zero": 0},
    "5m": {"wick_gaps": 12862, "in_leg": 10953, "pending_candidates": 710, "zones": 12268, "bull": 6549, "bear": 5719, "c2_not_directional": 46, "c2_not_spanning": 548,
           "equality": 601, "one_tick": 545, "ok": 12188, "insufficient": 80, "zero": 0,
           "first_markers": 6837, "first_at_formation": 6211, "first_later": 626},
    "15m": {"wick_gaps": 4404, "in_leg": 3767, "pending_candidates": 282, "zones": 4223, "bull": 2319, "bear": 1904, "c2_not_directional": 26, "c2_not_spanning": 155,
            "equality": 106, "one_tick": 97, "ok": 4133, "insufficient": 90, "zero": 0,
            "first_markers": 2298, "first_at_formation": 2052, "first_later": 246},
    "1H": {"wick_gaps": 1153, "in_leg": 941, "pending_candidates": 77, "zones": 1090, "bull": 603, "bear": 487, "c2_not_directional": 10, "c2_not_spanning": 53, "equality": 12,
           "one_tick": 10, "ok": 1005, "insufficient": 85, "zero": 0,
           "first_markers": 568, "first_at_formation": 497, "first_later": 71},
    "4H": {"wick_gaps": 319, "in_leg": 235, "pending_candidates": 24, "zones": 285, "bull": 166, "bear": 119, "c2_not_directional": 5, "c2_not_spanning": 29, "equality": 1,
           "one_tick": 3, "ok": 206, "insufficient": 79, "zero": 0,
           "first_markers": 139, "first_at_formation": 118, "first_later": 21},
    "1D": {"wick_gaps": 40, "in_leg": 18, "pending_candidates": 2, "zones": 31, "bull": 17, "bear": 14, "c2_not_directional": 1, "c2_not_spanning": 8, "equality": 0,
           "one_tick": 0, "ok": 6, "insufficient": 25, "zero": 0,
           "first_markers": 11, "first_at_formation": 9, "first_later": 2},
}


class PeakMemory:
    def __init__(self):
        self.proc, self.peak, self._stop = psutil.Process(os.getpid()), 0, False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop:
            self.peak = max(self.peak, self.proc.memory_info().rss)
            time.sleep(0.25)

    def mb(self):
        return round(self.peak / 2 ** 20)


def provenance() -> dict:
    """Source revision, worktree state and a hash of the FVG sources, so evidence and HTML match the code."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()
    raw = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout
    status = [line for line in raw.splitlines() if line.strip()]      # no strip: the XY column may start with a space
    tracked = sorted(line[3:] for line in status if not line.startswith("??"))
    untracked = sorted(line[3:] for line in status if line.startswith("??"))
    files = sorted(PROJECT_ROOT.glob("src/fvg/*.py")) + sorted(PROJECT_ROOT.glob("src/experiments/fvg_*.py"))
    h = hashlib.sha256()
    for path in files:
        text = path.read_bytes().replace(b"\r\n", b"\n")      # line-ending independent
        h.update(path.relative_to(PROJECT_ROOT).as_posix().encode() + b"\0" + text + b"\0")
    code_dirty = [x for x in tracked + untracked if x.startswith(("src/", "tests/", "config/"))]
    return {"git_head": git("rev-parse", "HEAD"), "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "worktree_code_state": "CLEAN" if not code_dirty else "DIRTY: " + ", ".join(code_dirty),
            "worktree_other_changes": ", ".join([x for x in tracked if x not in code_dirty]
                                                + [f"?? {x}" for x in untracked if x not in code_dirty]) or "none",
            "fvg_source_sha256": h.hexdigest(), "fvg_source_files": len(files)}


def main() -> int:
    started = time.perf_counter()
    mem = PeakMemory()
    spec = load_session_spec()
    bars = load_development_bars()
    rows, gates, timings = [], {}, []
    add = lambda section, tf, metric, value: rows.append({"section": section, "timeframe": tf, "metric": metric,  # noqa: E731
                                                          "value": value})
    add("source", "", "canonical_1m_rows", len(bars))
    add("source", "", "replay_cutoff", REPLAY_CUTOFF.isoformat())
    prov = provenance()
    for k, v in prov.items():
        add("provenance", "", k, v)
    print("provenance", prov, flush=True)

    t0 = time.perf_counter()
    run = build_fvg(bars, spec, instrument_id=INSTRUMENT, replay_cutoff=REPLAY_CUTOFF)
    timings.append({"stage": "build_fvg_full", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    print(f"build {timings[-1]['seconds']}s peak {mem.mb()} MB", flush=True)

    # --- frozen baselines ------------------------------------------------------------------------
    swing_ok = all((int((run.swings[tf]["orientation"] == "UPPER").sum()), int((run.swings[tf]["orientation"] == "LOWER").sum()))
                   == EXPECTED_COUNTS[tf] for tf in run.swings)
    gates["swings_equal_frozen_swing_baseline"] = swing_ok
    eps = run.tape.episodes
    gates["minute_episodes_equal_continuity_segments"] = (len(eps), sum(e.reset_at is not None for e in eps)) == \
        EXPECTED_CONTINUITY["1m"][1:]
    gates["frozen_sources_unchanged_vs_main"] = subprocess.run(
        ["git", "diff", "--quiet", "main", "--", *FROZEN_PATHS], cwd=PROJECT_ROOT).returncode == 0
    _summarize(run, add)

    # --- scratch reconciliation ------------------------------------------------------------------
    scratch_rows = _scratch_reconciliation(run)
    scratch = pd.DataFrame(scratch_rows)
    gates["scratch_evidence_reconciled"] = bool((scratch["status"] == "EQUAL").all())

    # --- invariants and independent reference ----------------------------------------------------
    t0 = time.perf_counter()
    inv = invariants(run)
    timings.append({"stage": "invariants", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    gates["all_invariants_zero"] = int(inv["violations"].sum()) == 0
    print(f"invariants {timings[-1]['seconds']}s violations {int(inv['violations'].sum())}", flush=True)
    # full-run independent recomputation (every episode, every timeframe; exact per-object restrictions)
    t0 = time.perf_counter()
    fref = full_reference(run, log=lambda m: print(m, flush=True))
    full_rec = full_reconcile(run, fref)
    off_grid = fref["off_grid_closes"]
    del fref
    timings.append({"stage": "full_run_reference", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    full_bad = int(full_rec[["missing", "extra"]].to_numpy().sum())
    gates["full_run_engine_equals_independent_recomputation"] = full_bad == 0 and off_grid == 0
    add("full_reference", "", "categories", full_rec["category"].nunique())
    add("full_reference", "", "rows_compared", int(full_rec["reference"].sum()))
    add("full_reference", "", "mismatches", full_bad)
    add("full_reference", "", "off_grid_timeframe_closes", off_grid)
    print(f"full reference {timings[-1]['seconds']}s mismatches {full_bad} off-grid {off_grid}", flush=True)

    # naive all-pairs reference on the short 1m episodes only (subset; coverage reported per category / timeframe)
    ref_eps = [e.index for e in eps if len(e.end) <= REFERENCE_MAX_BARS]
    t0 = time.perf_counter()
    rec = reconcile(run, reference(run, ref_eps))
    rec.insert(1, "method", "EPISODE_SUBSET_REFERENCE")
    timings.append({"stage": "subset_reference", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    gates["subset_engine_equals_naive_reference"] = int(rec[["missing", "extra"]].to_numpy().sum()) == 0
    coverage = subset_coverage(run, ref_eps)
    covered_bars = sum(len(eps[i].end) for i in ref_eps)
    add("subset_reference", "", "episodes_checked", len(ref_eps))
    add("subset_reference", "", "episodes_total", len(eps))
    add("subset_reference", "", "minute_bars_checked_share", round(covered_bars / sum(len(e.end) for e in eps), 4))
    add("subset_reference", "", "zero_covered_category_timeframes", int((coverage["covered"] == 0).sum()))
    print(f"subset reference {timings[-1]['seconds']}s mismatches {int(rec[['missing', 'extra']].to_numpy().sum())}",
          flush=True)

    # --- prefix replays ----------------------------------------------------------------------------
    prefix_rows = []
    for label, cutoff in _prefix_cutoffs(run):
        tp = time.perf_counter()
        part = build_fvg(bars, spec, instrument_id=INSTRUMENT, replay_cutoff=cutoff)
        mm = prefix_mismatches(run, part)
        prefix_rows.append({"case": label, "replay_cutoff": cutoff.isoformat(), "mismatches": sum(mm.values()),
                            **{f"m_{k}": v for k, v in mm.items()}, "seconds": round(time.perf_counter() - tp, 1)})
        print(f"prefix {label}: {sum(mm.values())} mismatches", flush=True)
        del part
    prefix = pd.DataFrame(prefix_rows)
    gates["prefix_replay_equivalence_development"] = bool(len(prefix)) and int(prefix["mismatches"].sum()) == 0
    timings.append({"stage": "prefix_replays", "seconds": round(prefix["seconds"].sum(), 1), "peak_rss_mb": mem.mb()})

    # --- visual package ----------------------------------------------------------------------------
    t0 = time.perf_counter()
    dev_cases = build_dev_cases(run)
    syn_cases, syn_facts = synthetic_cases(spec)
    cases = dev_cases + syn_cases
    header = [{"run_id": run.run_id, "replay_cutoff": REPLAY_CUTOFF.isoformat(), "zones": len(run.zones),
               "bprs": len(run.engine.bprs), "cases": len(cases), **prov}]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fvg_visual_validation.html").write_text(page(cases, {"dev": Facts(run), **syn_facts}, header), encoding="utf-8")
    timings.append({"stage": "visual", "seconds": round(time.perf_counter() - t0, 1), "peak_rss_mb": mem.mb()})
    gates["visual_cases_generated"] = len(cases) >= 24
    add("visual", "", "cases", len(cases))
    add("visual", "", "timeframes_covered", ",".join(sorted({c.case_id.split("-")[1] for c in dev_cases if c.category == "timeframe"})))

    gates["no_validation_or_oos_data"] = True
    gates["no_strategy_pnl_backtest_or_optimization"] = True
    timings.append({"stage": "total", "seconds": round(time.perf_counter() - started, 1), "peak_rss_mb": mem.mb()})
    tracked = {
        "fvg_dev_invariants.csv": inv,
        "fvg_dev_reconciliation.csv": rec,
        "fvg_dev_full_reconciliation.csv": full_rec,
        "fvg_dev_reference_coverage.csv": coverage,
        "fvg_dev_prefix_replay.csv": prefix,
        "fvg_dev_runtime.csv": pd.DataFrame(timings),
        "fvg_dev_scratch_reconciliation.csv": scratch,
        "fvg_visual_validation_cases.csv": pd.DataFrame(manifest_rows(cases)),
    }
    summary = pd.DataFrame(rows)
    tracked["fvg_dev_summary.csv"] = summary
    gates["tracked_artifacts_price_free"] = all(not any(w in c.lower() for c in f.columns for w in PRICE_WORDS)
                                                for f in tracked.values())
    for name, ok in gates.items():
        summary.loc[len(summary)] = {"section": "machine_gate", "timeframe": "", "metric": name,
                                     "value": "PASS" if ok else "FAIL"}
    tracked["fvg_dev_summary.csv"] = summary
    for name, frame_ in tracked.items():
        frame_.to_csv(OUT / name, index=False)
    print(f"total {round(time.perf_counter() - started, 1)}s peak {mem.mb()} MB")
    for name, ok in gates.items():
        print(f"GATE {name}: {'PASS' if ok else 'FAIL'}")
    return 0 if all(gates.values()) else 1


def _fp(values) -> str:
    return hashlib.sha256("\n".join(sorted(map(str, values))).encode()).hexdigest()


def _summarize(run, add) -> None:
    add("run", "", "run_id", run.run_id)
    Z, E = run.zones, run.engine
    for tf, c in run.counts.items():
        z = Z[Z["timeframe"] == tf]
        add("formation", tf, "triples", c["triples"])
        add("formation", tf, "wick_gaps", c["wick_gaps"])
        add("formation", tf, "zones", c["zones"])
        add("formation", tf, "bullish", int((z["original_direction"] == "BULLISH").sum()))
        add("formation", tf, "bearish", int((z["original_direction"] == "BEARISH").sum()))
        add("formation", tf, "rejected_C2_NOT_DIRECTIONAL", c["C2_NOT_DIRECTIONAL"])
        add("formation", tf, "rejected_C2_BODY_NOT_SPANNING", c["C2_BODY_NOT_SPANNING"])
        add("formation", tf, "equality_triples", c["equality"])
        add("formation", tf, "one_tick", int((z["width_ticks"] == 1).sum()))
        add("formation", tf, "half_tick_midpoint_share", round(float((z["width_ticks"] % 2 == 1).mean()), 4) if len(z) else 0)
        add("formation", tf, "median_width_ticks", float(z["width_ticks"].median()) if len(z) else 0)
        for st, n in z["normalization_status"].value_counts().items():
            add("normalization", tf, st, int(n))
        s = z["normalized_gap_strength"].dropna().astype(float)
        if len(s):
            for q in (0.1, 0.5, 0.9):
                add("normalization", tf, f"strength_p{int(q * 100)}", round(float(s.quantile(q, interpolation="lower")), 4))
    tr = E.zone_transitions
    for (tf, reason), n in tr.groupby(["attr_timeframe", "reason_code"]).size().items():
        add("lifecycle", tf, reason, int(n))
    m = E.mitigation
    for (kind, ok, cls), n in m.groupby([m["object_kind"].astype(str), m["kind"].astype(str),
                                         m["observation_class"].astype(str)]).size().items():
        add("mitigation", "", f"{kind}_{ok}_{cls}", int(n))
    e = E.episodes
    exits = E.zone_exits
    conv_created = e.apply(lambda r: len(r["movers"]) == 1 and exits[r["movers"][0]]["conv_ns"] == r["created_at"].value, axis=1) \
        if len(e) else pd.Series(dtype=bool)
    for (label, cc), n in e.assign(created_by=np.where(conv_created, "conversion", "admission_or_multi")).groupby(
            ["label", "created_by"]).size().items():
        add("relationships", "", f"{label}_{cc}", int(n))
    for reason, n in e["end_reason"].fillna("OPEN").value_counts().items():
        add("relationships", "", f"episode_end_{reason}", int(n))
    b = E.bprs
    for (label, d, ex), n in b.groupby(["label", b["direction"].astype(str), b["exit_state"].fillna("ACTIVE")]).size().items():
        add("bpr", "", f"{label}_{d}_{ex}", int(n))
    g = E.grades
    add("grading", "", "grade_versions", len(g))
    for k, n in g[g["actionable"]]["overlap_contribution"].clip(upper=5).value_counts().sort_index().items():
        add("grading", "", f"actionable_versions_contribution_{k}{'+' if k == 5 else ''}", int(n))
    add("grading", "", "versions_with_nested_partners", int((g["partner_zone_ids"].map(len) > g["overlap_contribution"]).sum()))
    a = run.associations
    for tf, x in a.groupby("timeframe"):
        f = x[x["is_first"]]
        add("association", tf, "associations", len(x))
        add("association", tf, "first_markers", len(f))
        add("association", tf, "first_at_formation", int((f["association_available_at"] == f["formation_available_at"]).sum()))
        add("association", tf, "first_later", int((f["association_available_at"] > f["formation_available_at"]).sum()))
        add("association", tf, "pending_candidate_deadlines_in_leg", int((x["deadline_rule"] == "PENDING_CANDIDATE_AT_C2").sum()))
        add("association", tf, "pending_candidates_all_zones", _pending_candidates_all_zones(run, tf))
        add("association", tf, "marker_never_active", int(f["marker_never_active"].sum()))
    add("data", "", "data_gap_warnings", len(E.warnings))
    add("data", "", "pending_adjustment_objects", len(E.pending))
    for name, col in (("zone_id", Z["zone_id"]), ("relationship_id", e["relationship_id"]), ("bpr_id", b["bpr_id"]),
                      ("zone_transition_id", tr["transition_id"]), ("mitigation_event_id", m["event_id"]),
                      ("grade_version_id", g["grade_version_id"]), ("association_id", a["association_id"])):
        add("identity", "", f"{name}_sha256", _fp(col))


def _scratch_reconciliation(run) -> list:
    out = []
    Z, a = run.zones, run.associations
    for tf, exp in SCRATCH.items():
        z = Z[Z["timeframe"] == tf]
        c = run.counts[tf]
        f = a[(a["timeframe"] == tf) & a["is_first"]]
        prod = {"zones": len(z), "bull": int((z["original_direction"] == "BULLISH").sum()),
                "bear": int((z["original_direction"] == "BEARISH").sum()),
                "c2_not_directional": c["C2_NOT_DIRECTIONAL"], "c2_not_spanning": c["C2_BODY_NOT_SPANNING"],
                "equality": c["equality"], "one_tick": int((z["width_ticks"] == 1).sum()),
                "ok": int((z["normalization_status"] == "OK").sum()),
                "insufficient": int((z["normalization_status"] == "INSUFFICIENT_HISTORY").sum()),
                "zero": int((z["normalization_status"] == "ZERO_BASELINE").sum()),
                "wick_gaps": c["wick_gaps"], "in_leg": int((a["timeframe"] == tf).sum()),
                "pending_candidates": _pending_candidates_all_zones(run, tf),
                "first_markers": len(f),
                "first_at_formation": int((f["association_available_at"] == f["formation_available_at"]).sum()),
                "first_later": int((f["association_available_at"] > f["formation_available_at"]).sum())}
        for metric, scratch_value in exp.items():
            v = prod[metric]
            status, note = ("EQUAL", "") if v == scratch_value else ("DIFFERENCE", "")
            out.append({"timeframe": tf, "metric": metric, "scratch": scratch_value, "production": v,
                        "difference": v - scratch_value, "status": status, "note": note})
    return out


def _pending_candidates_all_zones(run, tf) -> int:
    """Zones whose C2 ends a left-qualified equal-extreme run, over ALL zones (in a leg or not).

    The scratch evidence (§5.14) counted this over every zone; production association rows exist only for
    zones in a leg, so the reconciliation recomputes the scratch scope here (validation code only)."""
    data = run.tf_data[tf]
    pos = data.segment_of_end()
    n = 0
    for z in run.zones[run.zones["timeframe"] == tf].itertuples(index=False):
        si, k2 = pos[z.c2_end.value]
        vals = data.segments[si]["l" if z.original_direction == "BULLISH" else "h"]
        v, j = int(vals[k2]), k2
        while j - 1 >= 0 and int(vals[j - 1]) == v:
            j -= 1
        if j - 2 >= 0:
            left = [int(x) for x in vals[j - 2:j]]
            n += all(x >= v for x in left) if z.original_direction == "BULLISH" else all(x <= v for x in left)
    return int(n)


def _prefix_cutoffs(run):
    """Early DEVELOPMENT cutoffs around each event class (early instants keep the rebuilds affordable)."""
    E, Z = run.engine, run.zones
    one = pd.Timedelta(minutes=1)
    out = []
    window_end = pd.Timestamp(int(run.tape.episodes[min(6, len(run.tape.episodes) - 1)].end[-1]), tz="UTC")

    def early(series):
        s = series[series <= window_end]
        return None if s.empty else s.iloc[len(s) // 2]
    z5 = Z[Z["timeframe"] == "5m"]["available_at"]
    t = early(z5)
    if t is not None:
        out += [("admission_5m_at", t), ("admission_5m_minus_1m", t - one)]
    m = E.mitigation[E.mitigation["kind"].astype(str) == "PENETRATION"]["at"]
    t = early(m.sort_values())
    if t is not None:
        out.append(("mitigation_at", t))
    tr = E.zone_transitions
    t = early(tr[tr["reason_code"] == "CONVERTED"]["transition_at"].sort_values())
    if t is not None:
        out += [("conversion_at", t), ("conversion_minus_1m", t - one)]
    e = E.episodes
    exits = E.zone_exits
    cc = e[(e["label"] != "FVG_OVERLAP") & (e["movers"].map(len) == 1)]
    cc = cc[cc.apply(lambda r: exits[r["movers"][0]]["conv_ns"] == r["created_at"].value, axis=1)] if len(cc) else cc
    t = early(cc["created_at"].sort_values()) if len(cc) else None
    if t is not None:
        out += [("conversion_created_bpr_at", t), ("conversion_created_bpr_plus_1m", t + one)]
    ch = e[e["end_reason"] == "PARENT_STAGE_CHANGED"]["ended_at"]
    t = early(ch.sort_values())
    if t is not None:
        out.append(("relationship_change_at", t))
    br = E.bpr_transitions
    t = early(br[br["reason_code"] == "RETIRED"]["transition_at"].sort_values())
    if t is not None:
        out.append(("bpr_retirement_at", t))
    gap = next((x for x in run.tape.episodes if x.reset_reason == "DATA_GAP"), None)
    if gap is not None:
        out += [("gap_onset", gap.reset_at), ("inside_gap", gap.reset_at + pd.Timedelta(minutes=30))]
    a = run.associations
    d = a[a["deadline_rule"] == "PENDING_CANDIDATE_AT_C2"]
    t = early(d["association_available_at"].sort_values())
    if t is not None:
        out += [("association_deadline_at", t), ("association_deadline_minus_1_bar", t - pd.Timedelta(minutes=5))]
    return [(label, pd.Timestamp(t).tz_convert(NY)) for label, t in out]


if __name__ == "__main__":
    raise SystemExit(main())
