"""Generic Market Structure — MS-I3 DEVELOPMENT validation runner (machine validation; read-only).

Command (repository root)::

    .\\.venv\\Scripts\\python.exe -m src.experiments.market_structure_dev_validation

DEVELOPMENT partition only (path from the dataset partition config); explicit
structure definition ``structure-v1`` / ``swing-break-v1`` over the explicit
2/2 Swing reference (``swing-pivot-v1``); all six timeframes; explicit
``replay_cutoff`` = close of the DEVELOPMENT partition's declared last
session (2025-06-30 17:00 ET), never inferred from the data.

Production path: ``build_market_structure``.  Independent checks:
``structure_audit.reference_structure`` / ``reconcile`` and
``structure_invariants`` (INV-1 … INV-17); DEVELOPMENT prefix replays with
cutoffs inside real gaps.  Writes price-free tracked CSVs and a local,
Git-ignored visual HTML (prices) under ``reports/validation/``.  No PnL, no
strategy, no optimization, no backtest, no VALIDATION / OOS data.  It does
not freeze anything; it reports machine gates.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time

import pandas as pd

from src.data.sessions import load_session_spec
from src.experiments.market_structure_visual import build_cases, page
from src.experiments.swing_structure_dev_validation import (
    EXPECTED_CONTINUITY,
    EXPECTED_COUNTS,
    load_development_bars,
)
from src.market_structure.structure import RESET, StructureDefinitionSpec, build_market_structure
from src.market_structure.structure_audit import reconcile, reference_structure, structure_invariants
from src.market_structure.swing import SWING_TIMEFRAMES, SwingDefinitionSpec

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT = PROJECT_ROOT / "reports" / "validation"
NY = "America/New_York"
INSTRUMENT = "MNQ"
DEFINITION = StructureDefinitionSpec(
    definition_version="structure-v1", break_definition_version="swing-break-v1",
    swing_definition=SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2))
REPLAY_CUTOFF = pd.Timestamp("2025-06-30 17:00", tz=NY)   # DEVELOPMENT partition end: last session close
TABLES = ("swing_breaks", "episodes", "roles", "events", "anomalies", "direction_transitions", "role_transitions")
PRICE_COLUMNS = {"price", "open", "high", "low", "close", "level_ticks", "close_ticks", "swing_price_ticks"}
# reference reconciliation on 1m is bounded to every 4th continuity segment (runtime); all others are full
REFERENCE_FILTER = {"1m": lambda k: k % 4 == 0}


def main() -> int:
    started = time.perf_counter()
    spec = load_session_spec()
    bars = load_development_bars()
    rows, gates, invariants, reconciliations, timings = [], {}, [], [], []
    add = lambda section, tf, metric, value: rows.append(  # noqa: E731
        {"section": section, "timeframe": tf, "metric": metric, "value": value})
    add("source", "", "canonical_1m_rows", len(bars))
    add("source", "", "first_bar_end", bars.index.min().isoformat())
    add("source", "", "last_bar_end", bars.index.max().isoformat())
    add("source", "", "replay_cutoff", REPLAY_CUTOFF.isoformat())

    runs = {}
    swing_ok = episodes_ok = anomalies_ok = True
    for tf in SWING_TIMEFRAMES:
        t0 = time.perf_counter()
        run = build_market_structure(bars, tf, spec, DEFINITION, instrument_id=INSTRUMENT, replay_cutoff=REPLAY_CUTOFF)
        t1 = time.perf_counter()
        inv = structure_invariants(run, spec)
        t2 = time.perf_counter()
        ref = reference_structure(run, spec, episode_filter=REFERENCE_FILTER.get(tf))
        rec = reconcile(run, ref)
        rec.insert(0, "timeframe", tf)
        rec.insert(1, "replayed_segments", len(ref["segments"]))
        t3 = time.perf_counter()
        runs[tf] = run
        invariants.append(inv)
        reconciliations.append(rec)
        timings.append({"timeframe": tf, "engine_seconds": round(t1 - t0, 1), "invariants_seconds": round(t2 - t1, 1),
                        "reference_seconds": round(t3 - t2, 1)})
        print(f"{tf}: engine {t1 - t0:.1f}s invariants {t2 - t1:.1f}s reference {t3 - t2:.1f}s; "
              f"events {len(run.events)} roles {len(run.roles)}", flush=True)
        up, low = int((run.swings["orientation"] == "UPPER").sum()), int((run.swings["orientation"] == "LOWER").sum())
        swing_ok &= (up, low) == EXPECTED_COUNTS[tf]
        episodes_ok &= len(run.episodes) == EXPECTED_CONTINUITY[tf][1]
        anomalies_ok &= run.anomalies.empty
        _summarize(run, tf, add)
    gates["swings_equal_frozen_swing_baseline"] = swing_ok
    gates["episodes_equal_continuity_segments"] = episodes_ok
    gates["no_dual_establishment_anomalies"] = anomalies_ok
    invariant_frame = pd.concat(invariants, ignore_index=True)
    gates["all_invariants_zero"] = int(invariant_frame["violations"].sum()) == 0
    reconciliation_frame = pd.concat(reconciliations, ignore_index=True)
    gates["engine_equals_independent_reference"] = int(
        reconciliation_frame[["engine_only", "reference_only"]].to_numpy().sum()) == 0

    # --- DEVELOPMENT prefix replays (cutoffs inside real gaps and episodes) --------------------------
    prefix_rows = []
    prefix_ok = True
    for tf in ("4H", "1H"):
        for label, cutoff in _prefix_cutoffs(runs[tf]):
            run = build_market_structure(bars, tf, spec, DEFINITION, instrument_id=INSTRUMENT, replay_cutoff=cutoff)
            equal, detail = _restricted_equal(run, runs[tf], cutoff)
            prefix_ok &= equal
            prefix_rows.append({"timeframe": tf, "case": label, "replay_cutoff": cutoff.isoformat(),
                                "restricted_equal": equal, "detail": detail,
                                "episodes": len(run.episodes), "resets": int((run.events["kind"] == RESET).sum())})
    gates["prefix_replay_equivalence_development"] = prefix_ok

    # --- visual package (local HTML with prices) + price-free manifest -------------------------------
    t_visual = time.perf_counter()
    sections, cases = build_cases(runs, spec, DEFINITION)
    (OUT / "market_structure_visual_validation.html").write_text(page(sections, REPLAY_CUTOFF), encoding="utf-8")
    visual_seconds = time.perf_counter() - t_visual
    gates["visual_cases_generated"] = len({c["case_id"] for c in cases}) >= 18

    tracked = {
        "market_structure_dev_invariants.csv": invariant_frame,
        "market_structure_dev_reconciliation.csv": reconciliation_frame,
        "market_structure_dev_prefix_replay.csv": pd.DataFrame(prefix_rows),
        "market_structure_dev_runtime.csv": pd.DataFrame(timings),
        "market_structure_dev_episodes.csv": pd.concat([_episode_rows(runs[tf]) for tf in SWING_TIMEFRAMES],
                                                       ignore_index=True),
        "market_structure_visual_validation_cases.csv": pd.DataFrame(cases),
    }
    gates["no_validation_or_oos_data"] = True   # only the DEVELOPMENT partition file is read
    gates["no_strategy_pnl_backtest_or_optimization"] = True
    summary = pd.DataFrame(rows)
    tracked["market_structure_dev_summary.csv"] = summary
    gates["tracked_artifacts_price_free"] = all(not (PRICE_COLUMNS & set(f.columns)) for f in tracked.values())
    for name, ok in gates.items():
        summary.loc[len(summary)] = {"section": "machine_gate", "timeframe": "", "metric": name,
                                     "value": "PASS" if ok else "FAIL"}
    tracked["market_structure_dev_summary.csv"] = summary
    for name, frame in tracked.items():
        frame.to_csv(OUT / name, index=False)
    print(f"visual {visual_seconds:.1f}s; total {time.perf_counter() - started:.1f}s")
    for name, ok in gates.items():
        print(f"GATE {name}: {'PASS' if ok else 'FAIL'}")
    return 0 if all(gates.values()) else 1


# ---------------------------------------------------------------------------
# Summary metrics (price-free)
# ---------------------------------------------------------------------------


def _fingerprint(values) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def _summarize(run, tf, add) -> None:
    add("run", tf, "run_id", run.run_id)
    add("counts", tf, "swings", len(run.swings))
    add("counts", tf, "swing_breaks", len(run.swing_breaks))
    add("counts", tf, "episodes", len(run.episodes))
    for cause, count in run.episodes["opening_cause"].value_counts().sort_index().items():
        add("episodes", tf, f"opening_{cause}", int(count))
    add("episodes", tf, "opening_contract_changed", int(run.episodes["opening_contract_changed"].sum()))
    for (kind, direction), count in run.events.groupby(["kind", run.events["direction"].fillna("-")]).size().items():
        add("events", tf, f"{kind}_{direction}", int(count))
    for reason, count in run.events["reset_reason"].dropna().value_counts().sort_index().items():
        add("events", tf, f"RESET_reason_{reason}", int(count))
    for (prev, new), count in run.direction_transitions.groupby(["previous_state", "new_state"]).size().items():
        add("direction_transitions", tf, f"{prev}->{new}", int(count))
    kinds = dict(zip(run.roles["role_id"], run.roles["role_kind"]))
    exits = run.role_transitions.assign(kind=run.role_transitions["entity_id"].map(kinds))
    for kind, count in run.roles["role_kind"].value_counts().sort_index().items():
        add("roles", tf, f"{kind}_assigned", int(count))
    for (kind, state), count in exits.groupby(["kind", "new_state"]).size().items():
        add("roles", tf, f"{kind}_{state}", int(count))
    add("roles", tf, "active_at_cutoff", int(len(run.roles) - len(run.role_transitions)))
    add("anomalies", tf, "DUAL_ESTABLISHMENT", len(run.anomalies))
    for name, column in (("episode_id", run.episodes["episode_id"]), ("role_id", run.roles["role_id"]),
                         ("event_id", run.events["event_id"]), ("break_id", run.swing_breaks["break_id"])):
        add("identity", tf, f"{name}_sha256", _fingerprint(column))


def _episode_rows(run) -> pd.DataFrame:
    ep = run.episodes[["timeframe", "episode_id", "first_bar_end", "opening_cause", "previous_contract",
                       "opening_contract_changed", "contract"]].copy()
    resets = run.events[run.events["kind"] == RESET].set_index("episode_id")
    ep["reset_at"] = ep["episode_id"].map(resets["event_at"])
    ep["reset_reason"] = ep["episode_id"].map(resets["reset_reason"])
    return ep


# ---------------------------------------------------------------------------
# Prefix replay on DEVELOPMENT
# ---------------------------------------------------------------------------


def _prefix_cutoffs(run):
    """Cutoffs: inside the first contract-roll gap (after the DATA_GAP reset, before the new contract's first bar),
    exactly at a gap reset onset, one minute before it, and mid-episode."""
    ep = run.episodes.sort_values("first_bar_end").reset_index(drop=True)
    resets = run.events[run.events["kind"] == RESET].set_index("episode_id")
    roll = ep.index[ep["opening_contract_changed"].astype(bool)][0]
    before = ep.iloc[roll - 1]
    t_r = pd.Timestamp(resets.loc[before["episode_id"], "event_at"])
    first_new = pd.Timestamp(ep.iloc[roll]["first_bar_end"])
    gap = ep.index[(~ep["opening_contract_changed"].astype(bool)) & (ep.index > 0)][0]
    t_gap = pd.Timestamp(resets.loc[ep.iloc[gap - 1]["episode_id"], "event_at"])
    mid = pd.Timestamp(ep.iloc[2]["first_bar_end"]) + pd.Timedelta(days=3)
    return [("inside_roll_gap", t_r + (first_new - t_r) / 2), ("at_gap_reset_onset", t_gap),
            ("one_minute_before_gap_reset", t_gap - pd.Timedelta(minutes=1)), ("mid_episode", mid),
            ("at_new_contract_first_bar", first_new)]


def _restricted_equal(prefix, full, cutoff):
    for name in TABLES:
        a, b = getattr(prefix, name), getattr(full, name)
        column = "bar_end" if name == "anomalies" else "available_at"
        a = a.drop(columns=["run_id"]).reset_index(drop=True)
        b = b.loc[(pd.to_datetime(b[column], utc=True) <= cutoff).to_numpy()].drop(columns=["run_id"]).reset_index(drop=True)
        if a.empty and b.empty:
            continue
        try:
            pd.testing.assert_frame_equal(a, b)
        except AssertionError:
            return False, f"{name} differs"
    return True, ""


if __name__ == "__main__":
    raise SystemExit(main())
