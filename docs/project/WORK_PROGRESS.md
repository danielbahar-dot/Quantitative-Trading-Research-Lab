# Work Progress

Answers: **"Where exactly are we now?"** Update this after every meaningful
task. Keep entries short. History goes in [CHANGELOG](CHANGELOG.md) and
rationale in [DECISION_LOG](DECISION_LOG.md).

_Last updated: 2026-09-28_

## Current focus

Architecture cleanup before ICT liquidity work. Milestones proceed one at a
time with explicit approval (D-117). **M1, the generic session model, is
done.** ICT feature work is on hold until the next design run, which will
specify External and Internal Liquidity together.

## Last completed work

- **2026-09-28 — M1.1 stabilization** (uncommitted).
  - `is_maintenance_break()` now agrees with `session_status()`: it is True
    only for the Mon–Thu 17:00–18:00 break. Friday from 17:00 and Sunday
    before 18:00 are `NON_TRADING_DAY`. Added an explicit weekly-boundary
    test.
  - Four stale pre-Stage-3 test expectations reconciled with the verified
    current state. No production or ORB code changed.
  - Full suite is now green.
- **2026-09-28 — M1 generic session model** (uncommitted).
  - Added `config/sessions/cme_globex_et.json`,
    `config/sessions/cme_globex_et.overrides.json` (empty, coverage null),
    `src/data/sessions.py`, and `tests/test_sessions.py`.
  - No existing code changed.
  - Decisions D-110 to D-117 recorded.
- **2026-09-28 — Architecture / technical-debt closeout.** Delivered in chat.
  Its content is now recorded in `ARCHITECTURE_MAP` §A.11 and §B, and in
  DECISION_LOG (directives plus the PROPOSED list).
- **2026-09-24 — Onboarding documentation layer** (uncommitted).

## In progress

- None.

## Next approved task

- **None.** M2 or later needs explicit approval.
- Candidate order (see ROADMAP):
  1. M2 instrument metadata
  2. M3 timeframe builder (on demand)
  3. M4 derived-data persistence
  4. M5 generic session levels with ORB parity
  5. M6 level-interaction primitives with parity
  6. M7 State/Signal contracts
  7. M8 test tiers
  8. M9 legacy-ledger deprecation notice

## Blocked / unresolved (design-authority decisions)

1. **Holiday calendar source.** Coverage is null, so no date is
   calendar-verified yet. Missing sessions cannot be told apart from closures
   until this is populated.
2. **Level orientation.** What reference price makes a generic level
   "upper" or "lower", and how to treat a level exactly at price.
3. **REJECT / SWEEP.** Formal confirmation of the existing meanings (D-115).
4. **Incomplete HTF bars.** Emit them flagged (proposed) or drop them, and
   decide the default downstream consumption.
5. **Session-window completeness.** Keep the strict ORB rule or tolerate
   missing minutes.
6. **Parquet.** Approve `pyarrow` for derived data (PROPOSED).
7. **Generic overnight ID.** Proposed `overnight_1800_0700`. Also decide
   whether RTH is a generic window.
8. **Golden fixtures.** Whether small real-market-data samples may be
   committed (licensing).
9. **Signal contract.** Whether `first_executable_at` belongs in the signal
   or in the strategy layer.
10. **Generic interaction default.** Per-bar or window-aggregate evaluation.
11. **ICT partition plan.** Use of the exposed VALIDATION and OOS_BURNED
    ranges.
12. **Contract rolls, swings, MSS, EQ/REQ details.** Deferred to the next ICT
    design run (D-117).

## Validation pending

- M1 status: `TESTED` on synthetic data. It has not yet been checked against
  the dataset's `session_date` column. That integration check (real data,
  opt-in) should be part of a later milestone.
- No ICT primitive exists.

## Recent test status

- 2026-09-28 (M1.1), `tests/test_sessions.py`: **28 passed** (40 subtests).
- 2026-09-28 (M1.1), full suite (`.\.venv\Scripts\python.exe -m pytest -q`,
  ~8 min): **247 passed, 0 failed** (57 subtests). This is the clean
  repository baseline for M2.
- The earlier M1 run showed 4 failures, all stale pre-Stage-3 test
  expectations. They were fixed in M1.1 (see CHANGELOG).
- Tests do not read Git-ignored market data (see ARCHITECTURE_MAP §A.11).

## Open observations (no action taken)

- The ORB V0.2 Stage 3B record
  (`mnq_orb_v0_2_stage3b_london_interaction_event_characterization`) still
  has `status=running`, `decision=continue`. Its own notes say it stays
  running until representative human review is complete.
- The research closure (`d129a98`) did not finalize it.
- It is a frozen artifact and was left unchanged. Finalizing it needs a
  design-authority decision.
