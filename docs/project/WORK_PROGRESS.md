# Work Progress

Answers: **"Where exactly are we now?"** Update this after every meaningful
task. Keep entries short. History goes in [CHANGELOG](CHANGELOG.md) and
rationale in [DECISION_LOG](DECISION_LOG.md).

_Last updated: 2026-09-29_

## Current focus

Architecture cleanup before ICT liquidity work. Milestones proceed one at a
time with explicit approval (D-117).

- **M1–M4 are merged into `main`:** PR #1 (`7dfa78b`) and PR #2 (`e47d7de`,
  M4 + D1 deferral).
- **M5A (Generic Market Context library) is APPROVED / FROZEN**
  (2026-09-30). It is staged for commit on branch
  `m5-generic-market-context` (based on `e47d7de`).
- **M5B** (ORB compatibility / migration) is **optional**. It is not required
  before continuing the generic catalog (M6+).
- **D1 is DEFERRED** (D-123). Feature work must be continuity-aware.
- ICT feature work is on hold until the next design run, which will specify
  External and Internal Liquidity together.

## Last completed work

- **2026-09-30 — M5A final validation and close-out** (no code changed).
  M5A is approved and frozen. The visual HTML is Git-ignored; the price-free
  CSV is tracked.
  - Visual review of 7 DEVELOPMENT sessions.
  - `MISSING_EXPECTED_SESSION` vs `NO_OBSERVATIONS` semantics verified.
  - All invariants pass on every DEVELOPMENT bar.
  - Artifacts are in `reports/validation/`.
- **2026-09-29 — M5A Generic Market Context** (uncommitted). Specification:
  `docs/project/M5_MARKET_CONTEXT_SPEC.md` (D-124).
  - Added `src/features/session_context.py`,
    `config/features/market_context_windows.json`, and
    `tests/test_session_context.py` (33 tests).
  - Generic contexts: `previous_day`, `previous_rth` (validated 09:30–16:00
    definition), Asia, London, `overnight_1800_0700`,
    `overnight_context_2000_0900`, NY pre-market.
  - DEVELOPMENT read-only validation: exact frozen-ORB parity for Asia,
    London, NY pre-market and Overnight Context. Previous Day and Previous
    RTH differ only on the 6 intentional D-121 dates.
  - No ORB code changed.
- **2026-09-29 — Roadmap adjustment** (governance only; committed in
  `c1c9a8a`).
  - D1 deferred; continuity-aware rules recorded (D-123); D-120 marked
    revised.
  - ROADMAP updated with M5 next and D1 deferred.
  - QUALITY_CONTROL gains continuity checks. No code changed.

- **2026-09-29 — M4 derived-timeframe persistence** (merged via PR #2).
  - Added `src/data/timeframe_store.py` (Parquet + manifest,
    provenance-validated loads, stale-cache error, reserved-partition guard)
    and `tests/test_timeframe_store.py`.
  - Other changes: `TIMEFRAME_BUILDER_VERSION`, `pyarrow==25.0.1` pinned,
    `data/derived/` Git-ignored. (D-122)
  - DEVELOPMENT materialization of all five timeframes reproduced the M3.1
    row counts and incomplete counts exactly. The local cache is about
    4.6 MB.
- **2026-09-29 — M3.1 incompleteness audit** (DEVELOPMENT only, read-only).
  - **Builder accounting verified:** per-bucket missing counts match an
    independent computation at every timeframe (0 mismatches). Observed
    totals equal the source rows. No incomplete lower-timeframe bucket
    occurs on a complete day. All 238 14:00–17:00 4H buckets are
    `expected=180`; 237 are complete.
  - **The 28 incomplete daily bars are all source-data or calendar causes:**

    | Count | Cause | Status |
    |---|---|---|
    | 10 | Data ends early (13:00 / 13:15 / 09:30) | Consistent with exchange early closes, but calendar-unverified |
    | 5 | Roll Fridays: 18:01–00:00 missing when a new contract starts | 4 roll Fridays + dataset start |
    | 13 | Small minute gaps (1–18 min) | Source minutes absent |

  - **19 weekday sessions are entirely absent:** 16 are the Mon–Thu of every
    quarterly roll week; the other 3 are 12-25, 01-01 and 04-18.
  - Diagnostic: `reports/validation/m3_1_dev_daily_incompleteness.csv`
    (+ README). No code changed.
  - Governance follow-up: D1 gate added (D-120); frozen ORB previous-day
    limitation recorded, ORB unchanged (D-121).
- **2026-09-29 — M3 generic timeframe builder.**
  - Added `src/data/timeframes.py` and `tests/test_timeframes.py`, plus the
    additive `assign_trading_dates()` in `sessions.py`.
  - Policies (D-119): incomplete buckets are emitted with flags;
    mixed-contract buckets raise; `available_at = bar_end`.
  - DEVELOPMENT smoke check (read-only): all 337,815 bars valid, every
    `session_date` matches, no mixed contracts, 28 of 248 daily bars
    incomplete.
- **2026-09-29 — M2 generic instrument metadata** (committed in `241622a`).
  - Added `src/data/instruments.py` and `tests/test_instruments.py`.
  - `config/instruments/mnq.json` is authoritative and was left
    byte-identical: its SHA-256 is recorded in the frozen Gate 6C provenance.
  - Legacy `TICK_SIZE` is kept and guarded by a test. No consumers migrated.
    No ORB code changed. (D-118)
- **2026-09-28 — M1.1 stabilization** (committed in `d7b59fc`).
  - `is_maintenance_break()` now agrees with `session_status()`: it is True
    only for the Mon–Thu 17:00–18:00 break. Friday from 17:00 and Sunday
    before 18:00 are `NON_TRADING_DAY`. Added an explicit weekly-boundary
    test.
  - Four stale pre-Stage-3 test expectations reconciled with the verified
    current state. No production or ORB code changed.
  - Full suite is now green.
- **2026-09-28 — M1 generic session model** (committed in `d7b59fc`).
  - Added `config/sessions/cme_globex_et.json`,
    `config/sessions/cme_globex_et.overrides.json` (empty, coverage null),
    `src/data/sessions.py`, and `tests/test_sessions.py`.
  - No existing code changed.
  - Decisions D-110 to D-117 recorded.
- **2026-09-28 — Architecture / technical-debt closeout.** Delivered in chat.
  Its content is now recorded in `ARCHITECTURE_MAP` §A.11 and §B, and in
  DECISION_LOG (directives plus the PROPOSED list).
- **2026-09-24 — Onboarding documentation layer** (committed in `d7b59fc`).

## In progress

- None.

## Next approved task

- **None.** Any further milestone needs explicit approval.
- Candidates (see ROADMAP):
  1. ~~M2 instrument metadata~~ (done 2026-09-29)
  2. ~~M3 timeframe builder (on demand)~~ (done 2026-09-29)
  3. ~~M4 derived-data persistence~~ (done 2026-09-29)
  4. ~~M5A generic Market Context library~~ (approved / frozen 2026-09-30)
  5. M6 level-interaction primitives (generic catalog; not blocked by M5B)
  6. M7 State/Signal contracts
  7. ICT reusable feature library (after the joint External/Internal
     Liquidity design)
  8. M8 test tiers
  9. M9 legacy-ledger deprecation notice
  - Optional at any point: **M5B** ORB compatibility / migration (parity
    harness and legacy adapters only where semantics differ).

## Blocked / unresolved (design-authority decisions)

1. **Holiday calendar source.** Part of D1, which is deferred (D-123).
   Coverage is null, so no date is calendar-verified. Until it is populated,
   an absent expected session must surface as unavailable or unverified in
   M5+, never be skipped.
2. **Level orientation.** What reference price makes a generic level
   "upper" or "lower", and how to treat a level exactly at price.
3. **REJECT / SWEEP.** Formal confirmation of the existing meanings (D-115).
4. **Incomplete HTF bars: consumption.** The builder emits them flagged
   (D-119). Each downstream feature still has to decide whether it consumes
   incomplete bars.
5. **Session-window completeness.** Keep the strict ORB rule or tolerate
   missing minutes.
6. ~~**Parquet.**~~ Approved and implemented in M4 (D-122).
7. **Generic overnight ID.** Proposed `overnight_1800_0700`. Also decide
   whether RTH is a generic window.
8. **Golden fixtures.** Whether small real-market-data samples may be
   committed (licensing).
9. **Signal contract.** Whether `first_executable_at` belongs in the signal
   or in the strategy layer.
10. **Generic interaction default.** Per-bar or window-aggregate evaluation.
11. **ICT partition plan.** Use of the exposed VALIDATION and OOS_BURNED
    ranges.
12. **Swings, MSS, EQ/REQ details.** Deferred to the next ICT design run
    (D-117). Contract stitching is deferred to D1 (D-123). Features must stay
    continuity-aware in the meantime.

Items 5 and 7 and the reason vocabulary were settled for M5A (D-124):

- strict completeness;
- `overnight_1800_0700`;
- `previous_rth` is generic;
- controlled reasons and alignment statuses.

## Validation pending

- **M5A Market Context:** nothing pending. It is **APPROVED / FROZEN**
  (2026-09-30).
  - Visual validation and the semantic audit are complete, and all
    invariants passed (spec §10).
  - The visual HTML stays local (Git-ignored: it embeds raw prices).
  - The price-free `reports/validation/m5a_market_context_visual_validation_cases.csv`
    is the tracked evidence.

- M1 status: `TESTED` on synthetic data and checked against the real
  DEVELOPMENT `session_date` column (0 mismatches in M3/M3.1). This was a
  one-off script; there is no committed integration test yet (M8 test
  tiers).
- No ICT primitive exists.

## Recent test status

- 2026-09-29 (M5A), `tests/test_session_context.py`: **33 passed**
  (39 subtests).
- 2026-09-29 (M5A), full suite: **341 passed, 0 failed** (174 subtests).
  That is the 308 baseline plus the 33 new tests. This is the current
  baseline.

- 2026-09-29 (M4), `tests/test_timeframe_store.py`: **17 passed**
  (7 subtests).
- 2026-09-29 (M4), full suite: **308 passed, 0 failed** (135 subtests). That
  is the 291 baseline plus the 17 new tests. This is the current baseline.

- 2026-09-29 (M3), `tests/test_timeframes.py` + `tests/test_sessions.py`:
  **53 passed** (64 subtests).
- 2026-09-29 (M3), full suite: **291 passed, 0 failed** (128 subtests). That
  is the 266 baseline plus the 25 new tests. This is the baseline for M4.
- 2026-09-29 (M2), `tests/test_instruments.py`: **19 passed** (47 subtests).
- 2026-09-29 (M2), full suite: **266 passed, 0 failed** (104 subtests).
  That is the 247 baseline plus the 19 new tests. This was the pre-M3
  baseline.
- 2026-09-28 (M1.1), `tests/test_sessions.py`: **28 passed** (40 subtests).
- 2026-09-28 (M1.1), full suite (`.\.venv\Scripts\python.exe -m pytest -q`,
  ~8 min): **247 passed, 0 failed** (57 subtests). This was the pre-M2
  baseline.
- The earlier M1 run showed 4 failures, all stale pre-Stage-3 test
  expectations. They were fixed in M1.1 (see CHANGELOG).
- Tests do not read Git-ignored market data (see ARCHITECTURE_MAP §A.11).

## Open observations (no action taken)

- **Source-data gap at contract rolls (M3.1):** in DEVELOPMENT, the Mon–Thu
  sessions of each quarterly roll week are absent, and the new contract's
  first session starts at 00:01 Friday.
  - Under D-113 these are *missing expected sessions*, not closures.
  - It is a **known limitation**. D1 (stitching / repair) is **deferred**
    (D-123). Feature code must not silently work around it.
  - It was not investigated in VALIDATION or OOS.
- **Frozen ORB limitation (D-121):** ORB's dataset-previous "previous day"
  may reference an older session around missing roll-week sessions (e.g. a
  roll Friday referencing the prior week's Friday).
  - Documented only; ORB is unchanged.
  - A sensitivity analysis is a future item that needs authorization.

- The ORB V0.2 Stage 3B record
  (`mnq_orb_v0_2_stage3b_london_interaction_event_characterization`) still
  has `status=running`, `decision=continue`. Its own notes say it stays
  running until representative human review is complete.
- The research closure (`d129a98`) did not finalize it.
- It is a frozen artifact and was left unchanged. Finalizing it needs a
  design-authority decision.
