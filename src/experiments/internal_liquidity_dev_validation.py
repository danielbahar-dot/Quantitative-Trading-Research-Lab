"""Internal Liquidity — IL-I4 DEVELOPMENT validation runner (machine validation; read-only).

Command (repository root)::

    .\\.venv\\Scripts\\python.exe -m src.experiments.internal_liquidity_dev_validation

DEVELOPMENT partition only; explicit ``replay_cutoff`` = close of the
partition's declared last session (2025-06-30 17:00 ET).  Production path:
``build_internal_liquidity`` (5m / 15m / 1H internal formations, frozen
External Daily / 4H, canonical 1m consumption).  Independent checks:
``internal_liquidity_audit.reference_internal_liquidity`` / ``reconcile``,
``internal_liquidity_invariants`` (IL-INV-1 … IL-INV-20) and DEVELOPMENT
prefix replays around admissions, consumption, a gap and a range change.
Frozen baselines (External, Swing, 1m continuity, frozen source files) are
reconciled.  Writes price-free tracked CSVs and a local, Git-ignored visual
HTML (prices) under ``reports/validation/``.  No PnL, strategy,
optimization, backtest, VALIDATION or OOS data.  It freezes nothing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import time

import pandas as pd

from src.data.sessions import load_session_spec
from src.experiments.internal_liquidity_visual import (
    build_dev_cases,
    build_synthetic_cases,
    manifest_rows,
    page,
    synthetic_runs,
)
from src.experiments.swing_structure_dev_validation import EXPECTED_CONTINUITY, EXPECTED_COUNTS, load_development_bars
from src.liquidity.internal_liquidity import build_internal_liquidity
from src.liquidity.internal_liquidity_audit import (
    internal_liquidity_invariants,
    prefix_mismatches,
    reconcile,
    reference_internal_liquidity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT = PROJECT_ROOT / "reports" / "validation"
NY = "America/New_York"
INSTRUMENT = "MNQ"
REPLAY_CUTOFF = pd.Timestamp("2025-06-30 17:00", tz=NY)
EXPECTED_EXTERNAL = (2553, 86)                       # frozen External DEVELOPMENT members / structures
FROZEN_PATHS = ("src/features/external_liquidity.py", "src/liquidity/contract.py", "src/market_structure",
                "src/state", "src/data", "src/features", "config")
PRICE_WORDS = ("price", "open", "high", "low", "close", "threshold", "ohlc")
MIN_VISUAL_CASES = 18


def main() -> int:
    started = time.perf_counter()
    spec = load_session_spec()
    bars = load_development_bars()
    rows, gates, timings = [], {}, []
    add = lambda section, metric, value: rows.append({"section": section, "metric": metric, "value": value})  # noqa: E731
    add("source", "canonical_1m_rows", len(bars))
    add("source", "replay_cutoff", REPLAY_CUTOFF.isoformat())

    t0 = time.perf_counter()
    run = build_internal_liquidity(bars, spec, instrument_id=INSTRUMENT, replay_cutoff=REPLAY_CUTOFF)
    t1 = time.perf_counter()
    timings.append({"stage": "engine_full", "seconds": round(t1 - t0, 1)})
    print(f"engine {t1 - t0:.1f}s", flush=True)

    # --- frozen baselines -----------------------------------------------------------------------
    f = run.formation
    swing_ok = all(
        (int((f.swings[tf]["orientation"] == "UPPER").sum()), int((f.swings[tf]["orientation"] == "LOWER").sum()))
        == EXPECTED_COUNTS[tf] for tf in ("5m", "15m", "1H"))
    gates["swings_equal_frozen_swing_baseline"] = swing_ok
    tracked_ext = pd.read_csv(OUT / "external_liquidity_dev_structures.csv")
    gates["external_equals_frozen_baseline"] = (
        (len(run.external_members), len(run.external_structures)) == EXPECTED_EXTERNAL
        and set(run.external_structures["structure_id"]) == set(tracked_ext["structure_id"]))
    episodes = run.tape.episodes
    gates["minute_episodes_equal_continuity_segments"] = (
        len(episodes), sum(e.reset_at is not None for e in episodes)) == EXPECTED_CONTINUITY["1m"][1:]
    diff = subprocess.run(["git", "diff", "--quiet", "main", "--", *FROZEN_PATHS], cwd=PROJECT_ROOT)
    gates["frozen_sources_unchanged_vs_main"] = diff.returncode == 0
    add("baseline", "external_members", len(run.external_members))
    add("baseline", "external_structures", len(run.external_structures))
    for tf in ("5m", "15m", "1H"):
        add("baseline", f"swings_{tf}", len(f.swings[tf]))
    add("baseline", "minute_episodes", len(episodes))

    _summarize(run, add)

    # --- invariants and independent reference ----------------------------------------------------
    t2 = time.perf_counter()
    invariants = internal_liquidity_invariants(run, spec)
    t3 = time.perf_counter()
    reference = reference_internal_liquidity(run)
    reconciliation = reconcile(run, reference)
    t4 = time.perf_counter()
    timings += [{"stage": "invariants", "seconds": round(t3 - t2, 1)},
                {"stage": "reference_and_reconcile", "seconds": round(t4 - t3, 1)}]
    print(f"invariants {t3 - t2:.1f}s reference {t4 - t3:.1f}s", flush=True)
    gates["all_invariants_zero"] = int(invariants["violations"].sum()) == 0
    gates["engine_equals_independent_reference"] = int(reconciliation[["missing", "extra"]].to_numpy().sum()) == 0

    # --- prefix replays ---------------------------------------------------------------------------
    prefix_rows = []
    for label, cutoff in _prefix_cutoffs(run):
        tp = time.perf_counter()
        part = build_internal_liquidity(bars, spec, instrument_id=INSTRUMENT, replay_cutoff=cutoff)
        mismatches = prefix_mismatches(run, part)
        prefix_rows.append({"case": label, "replay_cutoff": cutoff.isoformat(),
                            "mismatches": sum(mismatches.values()),
                            **{f"mismatch_{k}": v for k, v in mismatches.items()},
                            "seconds": round(time.perf_counter() - tp, 1)})
        print(f"prefix {label}: {sum(mismatches.values())} mismatches", flush=True)
    prefix = pd.DataFrame(prefix_rows)
    gates["prefix_replay_equivalence_development"] = bool(len(prefix)) and int(prefix["mismatches"].sum()) == 0

    # --- visual package ---------------------------------------------------------------------------
    tv = time.perf_counter()
    cases, facts = build_dev_cases(run)
    syn_cases, syn_facts = build_synthetic_cases(synthetic_runs(spec))
    all_cases = syn_cases + cases
    header = [{"run_id": run.run_id, "replay_cutoff": REPLAY_CUTOFF.isoformat(), "levels": run.levels["level_id"].nunique(),
               "range_versions": len(run.ranges), "assignments": len(run.assignments)}]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "internal_liquidity_visual_validation.html").write_text(
        page(all_cases, {"dev": facts, **syn_facts}, REPLAY_CUTOFF, header), encoding="utf-8")
    timings.append({"stage": "visual", "seconds": round(time.perf_counter() - tv, 1)})
    gates["visual_cases_generated"] = len(all_cases) >= MIN_VISUAL_CASES
    add("visual", "cases", len(all_cases))
    add("visual", "missing_dev_categories", ",".join(sorted(
        {"IL-V%02d" % k for k in range(1, 23)} - {c.case_id for c in cases})) or "none")

    gates["no_validation_or_oos_data"] = True
    gates["no_strategy_pnl_backtest_or_optimization"] = True
    tracked = {
        "internal_liquidity_dev_invariants.csv": invariants,
        "internal_liquidity_dev_reconciliation.csv": reconciliation.drop(columns=["example"]),
        "internal_liquidity_dev_prefix_replay.csv": prefix,
        "internal_liquidity_dev_runtime.csv": pd.DataFrame(timings),
        "internal_liquidity_visual_validation_cases.csv": pd.DataFrame(manifest_rows(all_cases)),
    }
    summary = pd.DataFrame(rows)
    tracked["internal_liquidity_dev_summary.csv"] = summary
    gates["tracked_artifacts_price_free"] = all(
        not any(word in column.lower() for column in frame.columns for word in PRICE_WORDS)
        for frame in tracked.values())
    for name, ok in gates.items():
        summary.loc[len(summary)] = {"section": "machine_gate", "metric": name, "value": "PASS" if ok else "FAIL"}
    tracked["internal_liquidity_dev_summary.csv"] = summary
    for name, frame in tracked.items():
        frame.to_csv(OUT / name, index=False)
    print(f"total {time.perf_counter() - started:.1f}s")
    for name, ok in gates.items():
        print(f"GATE {name}: {'PASS' if ok else 'FAIL'}")
    return 0 if all(gates.values()) else 1


def _fingerprint(values) -> str:
    return hashlib.sha256("\n".join(sorted(map(str, values))).encode("utf-8")).hexdigest()


def _summarize(run, add) -> None:
    add("run", "run_id", run.run_id)
    L = run.levels
    first = L.groupby("level_id").head(1)
    add("levels", "levels", len(first))
    add("levels", "level_versions", len(L))
    for kind, n in L["change_kind"].value_counts().sort_index().items():
        add("levels", f"versions_{kind}", int(n))
    last = L.groupby("level_id").tail(1)
    for tier, n in last["grade_tier"].value_counts().sort_index().items():
        add("grades", f"final_tier_{tier}", int(n))
    for side, n in first["side"].value_counts().sort_index().items():
        add("levels", f"side_{side}", int(n))
    tr = run.consumption_transitions
    for (kind, reason), n in tr.groupby(["attr_object_kind", "reason_code"]).size().items():
        add("lifecycle", f"{kind}_{reason}", int(n))
    ent = run.consumption_entities
    add("lifecycle", "active_at_cutoff", int(len(ent) - len(tr)))
    gap_through = tr["attr_gap_through"].fillna(False).astype(bool)
    add("lifecycle", "consumed_gap_through", int(gap_through.sum()))
    add("ranges", "ranges", int(run.range_entities.shape[0]))
    add("ranges", "range_versions", len(run.ranges))
    for kind, n in run.ranges["change_kind"].value_counts().sort_index().items():
        add("ranges", f"version_{kind}", int(n))
    add("ranges", "post_gap_restricted_versions", int(run.ranges["post_gap_restricted"].astype(bool).sum()))
    add("ranges", "unbounded_upper_versions", int((run.ranges["upper_assignment_id"] == "UNBOUNDED").sum()))
    for reason, n in run.range_transitions["reason_code"].value_counts().sort_index().items():
        add("ranges", f"terminated_{reason}", int(n))
    A = run.assignments
    for (kind, sel), n in A.groupby(["external_object_kind", "selection_kind"]).size().items():
        add("assignments", f"{kind}_{sel}", int(n))
    st = run.range_status
    for status, g in st.groupby("status"):
        until = g["until_at"].fillna(run.tape.replay_cutoff)
        add("range_status", f"{status}_minutes", int(((until - g["from_at"]).dt.total_seconds() / 60).sum()))
    add("membership", "membership_intervals", len(run.memberships))
    for reason, n in run.memberships["end_reason"].fillna("OPEN").value_counts().sort_index().items():
        add("membership", f"end_{reason}", int(n))
    if len(run.audit):
        for kind, n in run.audit["kind"].value_counts().sort_index().items():
            add("audit", kind, int(n))
    add("price_records", "price_records", run.price_records["price_record_id"].nunique())
    add("price_records", "record_versions", len(run.price_records))
    multi = run.price_record_links.groupby("price_record_id")["liquidity_class"].nunique()
    add("price_records", "records_with_internal_and_external", int((multi > 1).sum()))
    for name, column in (("level_id", first["level_id"]), ("level_version_id", L["level_version_id"]),
                         ("range_version_id", run.ranges["range_version_id"]),
                         ("boundary_assignment_id", A["boundary_assignment_id"]),
                         ("consumption_transition_id", tr["transition_id"])):
        add("identity", f"{name}_sha256", _fingerprint(column))


def _prefix_cutoffs(run):
    """Cutoffs around an admission, an assignment consumption, a gap onset (and inside it) and a range change."""
    out = []
    one = pd.Timedelta(minutes=1)
    L = run.levels
    lv = L.iloc[len(L) // 2]["available_at"]
    out += [("admission_at", lv), ("admission_minus_1m", lv - one)]
    tr = run.consumption_transitions
    ba = tr[(tr["attr_object_kind"] == "BOUNDARY_ASSIGNMENT") & (tr["reason_code"] == "CONSUMED")]
    if len(ba):
        t = ba.sort_values("transition_at").iloc[len(ba) // 2]["transition_at"]
        out += [("assignment_consumption_at", t), ("assignment_consumption_minus_1m", t - one)]
    gaps = [e for e in run.tape.episodes if e.reset_reason == "DATA_GAP"]
    if gaps:
        g = gaps[len(gaps) // 2]
        out += [("gap_onset", g.reset_at), ("inside_gap", g.reset_at + pd.Timedelta(minutes=30))]
    R = run.ranges
    change = R[R["change_kind"] != "ESTABLISHED"]
    if len(change):
        out.append(("range_change_at", change.iloc[len(change) // 3]["available_at"]))
    return [(label, pd.Timestamp(t).tz_convert(NY)) for label, t in out]


if __name__ == "__main__":
    raise SystemExit(main())
