# Work Progress

Answers: **"Where exactly are we now?"** Update this after every meaningful
task. Keep entries short. History goes in [CHANGELOG](CHANGELOG.md) and
rationale in [DECISION_LOG](DECISION_LOG.md).

_Last updated: 2026-10-04_

## Current focus

Architecture cleanup before ICT liquidity work. Milestones proceed one at a
time with explicit approval (D-117).

- **M1–M6A are merged into `main`:** PR #1 (`7dfa78b`), PR #2 (`e47d7de`),
  PR #3 (`30a87cf`, M5A approved / frozen), PR #4 (`8fea836`, M5B: ORB
  consumes the generic catalog, D-125) and PR #5 (`372c9e2`, M6A generic
  level interactions, D-126 / D-127).
- **M6 is complete** and merged (PR #6, `0d0e917`; M6B: ORB consumes M6A
  with exact frozen parity, D-128).
- **M7A (generic State contract) is implemented, validated and merged**
  (PR #7, `4a0d674`; D-129–D-131).
- **M7B (generic Signal contract) is merged** (PR #8, `807c321`; D-132).
  **M7 is complete.** Both contracts are envelopes; no real State
  lifecycle or Signal family exists yet.
- **D1 is DEFERRED** (D-123). Feature work must be continuity-aware.
- **External Liquidity (ROADMAP 3.1, Generic Market Structure &
  Liquidity): DONE — APPROVED / FROZEN** (2026-10-04; D-133, D-134
  freeze note).
  - Design and EL-I0 merged (PR #9, `27f493b`).
  - The implementation and freeze are merged (PR #10, `db13d19`):
    - `src/liquidity/contract.py` and `src/features/external_liquidity.py`;
    - tests: 15 contract + 41 External;
    - full suite: 543 passed / 0 failed / 382 subtests.
  - Frozen DEVELOPMENT baseline:
    - 2,553 members and 86 structures;
    - 438 Previous Day references;
    - 3,326 candidates, 50 breaks, 412 barrier blocks;
    - FORMED 84 / EXTENDED 2 / MERGED 0.
  - The final review corrections are part of the freeze (no semantic
    change; canonical DEVELOPMENT output is identical):
    - duplicate ids now raise;
    - an accurate opaque-SourceRef test;
    - barrier blocker provenance;
    - visual blocker annotation and label staggering;
    - a single-predecessor history invariant (0 violations).
  - DEVELOPMENT audit:
    - 440 Daily members;
    - 1,944 session members across Asia / London / NY Pre-market /
      Overnight;
    - 438 Previous Day references, 0 mismatches;
    - 169 promoted 4H members;
    - 86 4H structure versions (EQ 1/3, REQ 46/36); no Daily structures (a
      data-coverage limitation);
    - all invariants 0.

    Details are in spec §18.
  - The visual HTML is local (31 cases). Price-free audit CSVs are in
    `reports/validation/external_liquidity_*`.
  - Next in the workstream (D-133 sequencing clarification): Swing
    Structure (3.2), Internal Liquidity (3.3), then the Shared Lifecycle
    (3.4).
- **Swing Structure (ROADMAP 3.2): DESIGN APPROVED — IMPLEMENTATION
  NEXT** (D-135–D-138). The swing detector is not implemented, and nothing
  is frozen.
  - The design was merged in PR #11 (`d4c0ce8`).
  - **SW-I0 (D-137) is implemented, validated, committed (`0087e5d`) and
    design-authority approved on `swing-structure-implementation`;
    pending PR / merge.**
    - The shared `src/data/continuity.py` (`continuity_segments`, break
      vocabulary, `ContinuityError`) is extracted unchanged from External.
    - External keeps a compatibility wrapper.
    - Frozen External parity is exact.
  - Spec: `docs/project/SWING_STRUCTURE_SPEC.md`, **rev 3**, with the final
    design-authority decisions. It specifies:
    - a plateau-aware confirmed pivot, failing only on a strict exceed;
    - a plateau over consecutive expected observations in one segment
      (session boundaries allowed);
    - separated equal extremes as independent swings;
    - the source timing invariant;
    - a fixed `BAR_SPAN` format and a final `sw_` identity key;
    - explicit depths ≥ 1 with no defaults, and 2/2 as the reference
      validation configuration on all timeframes;
    - 1m (canonical bars) through 1D;
    - per-timeframe detection with causal `swing_id` projection;
    - `src/data/continuity.py` with `ContinuityError` as the first
      prerequisite.
  - Decisions D-135–D-138 (promoted from P-SW-1…4) are ACTIVE — DESIGN
    APPROVED.
  - Next, after the SW-I0 merge: the swing implementation (D-135, D-136,
    D-138).

## Last completed work

- **2026-10-04 — SW-I0 shared continuity extraction.** Implemented,
  validated, committed (`0087e5d`) and design-authority approved on
  `swing-structure-implementation`; pending PR / merge.
  - Added `src/data/continuity.py` and `tests/test_continuity.py` (20
    tests).
  - `src/features/external_liquidity.py` now uses a compatibility wrapper.
  - DEVELOPMENT parity is exact:
    - External members 2,553, structures 86, Previous Day references 438,
      candidates 3,326, breaks 50, barrier blocks 412;
    - `continuity_segments` output is identical for 1m–1D;
    - the regenerated External validation CSVs are identical.

- **2026-10-04 — Swing Structure 3.2 design registered.**
  - P-SW-1…4 were promoted to D-135–D-138 (ACTIVE — DESIGN APPROVED).
  - The design commits were merged into `main` via PR #11
    (`d4c0ce8b3aa65752fc2ce3cfc2dc2e02eef77286`).

- **2026-10-04 — Swing Structure 3.2 final design decisions (rev 3)**
  (design-only phase; now incorporated into the registered design).
  - Q1 and Q9–Q12 resolved; no semantic questions remain.
  - Spec status is DESIGN APPROVED.

- **2026-10-04 — Swing Structure 3.2 design review amendment (rev 2)**
  (design-only phase; now incorporated into the registered design).
  - The equality rule changed: separated equal extremes now both confirm.
    This adds 0 swings at N = 1 and +0.7–7.2 % at N = 2 to 5 on 1m–1H; 4H
    and 1D are essentially unchanged.
  - Plateau identity is now `BAR_SPAN`; 1m is included; continuity goes to
    `src/data/continuity.py`.
- **2026-10-04 — Swing Structure 3.2 design draft** (design-only phase;
  now incorporated into the registered design).
  - Read-only DEVELOPMENT probe (1m–1D, N = 1 / 2 / 3 / 5), equality
    policy comparison, and a cross-timeframe as-of study.
  - Local visual `reports/validation/swing_structure_design_visual.html`
    (Git-ignored).

- **2026-10-04 — External Liquidity 3.1 APPROVED / FROZEN.**
  - Recorded the freeze (spec status and §18 baseline, the D-134 freeze
    note, ROADMAP, MEMORY).
  - Two commits (implementation + tests; validation + governance), merged
    to `main` via PR #10 (`db13d19`).

- **2026-10-03 — External Liquidity pre-freeze review corrections**
  (uncommitted, not frozen). These are contract / audit / test / visual
  quality fixes only.
  - Code: `canonical_id_tuple` rejects duplicate ids, and
    `barrier_blocks` gains `blocking_bar_end` / `blocking_excess_ticks`.
  - Canonical DEVELOPMENT parity is exact: 2,553 members, 86 structures,
    438 Previous Day references.
  - Tests: 543 passed / 382 subtests.

- **2026-10-03 — External Liquidity implementation (EL-I1 to EL-I4)**
  (uncommitted, not frozen).
  - Generic liquidity envelope plus the External extraction, continuity,
    EQ/REQ, promotion and versions.
  - DEVELOPMENT audit and visual artifact.
  - Doc cleanups: the EL-I0 test wording, and the Swing-before-Internal
    sequencing (D-133 clarification).
  - Tests: 537 passed / 382 subtests (baseline 487 / 376).
- **2026-10-01 — M7A generic State contract** (uncommitted).
  - The spec was updated first (rev 3, §0 normative), and D-129 recorded.
  - Added `src/state/__init__.py`, `src/state/contract.py` and
    `tests/test_state_contract.py` (46 tests / 40 subtests).
  - `decision_offset` was removed (D-131). `validate_transitions` checks log
    integrity, causality, provenance and replay; exact trigger eligibility
    is owned upstream.
  - The final-validation amendments are D-130 (rev 3.1): a sequence domain,
    a required `trigger_ref`, strict consumers, and no default bar
    timeframe.
  - **Contract:**
    - an event-based transition log with causal keys
      `(at, seq_domain, seq)`;
    - a `StateNamespaceSpec` with a required `initial_state` and no
      creation transition;
    - a caller-provided entity applicability frame;
    - one transition per entity + namespace + causal source event;
    - full SHA-256 ids and a typed `SourceRef`.
  - **Utilities:** `validate_transitions`, `state_as_of`,
    `materialize_state_to_observations` (the generic core) and
    `materialize_state_to_bars` (a `BAR_END` wrapper that keeps
    `bar_start ≥ available_at`).
  - Validation is synthetic only; no real lifecycle exists yet. M5 and M6
    are unchanged.
- **2026-10-01 — M6B ORB level-interaction migration** (uncommitted).
  - Added `src/experiments/orb_level_interaction_compat.py` and
    `tests/test_orb_level_interaction_compat.py` (19 tests).
  - `build_feature_audit` evaluates aggregated OR windows through M6A.
    `market_context.level_interaction` is removed.
  - The only compatibility rule is open-at-level. Distances and the schema
    stay in the adapter.
  - **Exact parity** with the frozen audit (`0120af8`, SHA-256 `754357…`):
    234/234 `level_*` columns and 474/474 overall. Removing the AT rule
    breaks 718 frozen rows.
  - M6A unchanged; its regenerated DEV summary is identical.
  - Two synthetic fixtures were snapped to the 0.25 grid, with assertions
    unchanged (design-authority choice).
  - Full suite: 400 passed (381 + 19).
- **2026-10-01 — M6A generic Level Interaction catalog** (merged, PR #5).
  - Added `src/features/level_interactions.py` and
    `tests/test_level_interactions.py` (29 tests / 35 subtests).
  - Applicability bounds (D-127): `bar_start ≥ max(available_at, valid_from)`
    and `bar_start < valid_until`. Pending rows only for the confirming bar
    inside the window.
  - Full suite: 381 passed, 215 subtests. That is the M5B baseline of 352
    plus 29 M6A tests.
  - DEVELOPMENT, read-only: 3,379,242 pairs with zero invariant, causality,
    window, scope, contract or NA-shape failures. There are 0
    `CONTRACT_MISMATCH` rows and no off-grid levels in the data.
  - Visual review of 12 cases passes. HTML is local; price-free CSVs are in
    `reports/validation/m6a_*`.
  - ORB untouched.
- **2026-09-30 — M6 specification rev 2** (docs only). All nine
  design-authority decisions are incorporated (D-126):
  - far-side support via `approach_side`;
  - `NEUTRAL` orientation with `AMBIGUOUS_APPROACH`;
  - `valid_until`;
  - off-grid levels using exact first-tradable prices;
  - `SPECIFIC` / `AGNOSTIC` contract scope;
  - raw offset ticks.
  Three minor questions remain (spec §19 a–c). M6A awaits final approval.
- **2026-09-30 — M5B ORB Market Context migration** (merged, PR #4).
  - Added `src/experiments/orb_market_context_compat.py`,
    `config/features/market_context_compatibility.json`, and
    `tests/test_orb_market_context_compat.py` (11 tests).
  - `session_context.py` exposes the engine as `evaluate_context` and
    `prepare_context_bars`; M5A output is byte-identical.
  - ORB `build_feature_audit` consumes the generic catalog.
  - Compatibility is limited to `orb_overnight_1800_0930` and the legacy
    previous-available-session selector.
  - **Exact parity**, on DEVELOPMENT: vs the pre-migration output
    (744 × 474) and vs the frozen oracle (all 474 columns; SHA-256 recorded
    in M5 spec §11).
  - Three synthetic ORB test fixtures moved from Sunday to weekday dates,
    with assertions unchanged (design-authority choice).
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
  5. ~~M5B ORB Market Context migration~~ (merged 2026-09-30)
  6. **M6** level-interaction primitives: **COMPLETE** (M6A merged; M6B
     exact ORB parity)
  7. M7 State/Signal contracts: **COMPLETE** (M7A and M7B merged)
  8. Generic Market Structure & Liquidity (ROADMAP 3, D-133): External
     Liquidity design approved, implementation next; then Internal
     Liquidity, Swing Structure and the Shared Lifecycle
  9. M8 test tiers
  10. M9 legacy-ledger deprecation notice

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

- 2026-10-01 (M7B), `tests/test_signal_contract.py`: **28 passed** (88
  subtests). Full suite: **474 passed, 0 failed** (343 subtests). That is
  the post-M7A baseline of 446 / 255 plus 28 / 88. This is the current
  baseline.
- 2026-10-01 (M7A), `tests/test_state_contract.py`: **46 passed** (40
  subtests). Full suite: **446 passed, 0 failed** (255 subtests).
- 2026-10-01 (M6A), `tests/test_level_interactions.py`: **29 passed**
  (35 subtests).
- 2026-10-01 (M6B), `tests/test_orb_level_interaction_compat.py`: **19
  passed**, including frozen-oracle parity and the compat-removal negative
  test (both skip if local DEVELOPMENT data is absent). ORB feature, London
  and key-level characterization tests all pass.
- 2026-10-01 (M6B), full suite: **400 passed, 0 failed** (215 subtests).
  That is the post-M6A baseline of 381 plus the 19 new M6B tests.
- 2026-10-01 (M6A), full suite: **381 passed, 0 failed** (215 subtests).
  That is the M5B baseline of 352 plus the 29 new M6A tests, and the
  subtests are 180 + 35. This was the baseline before M6B.
- 2026-09-30 (M5B), `tests/test_orb_market_context_compat.py`: **11 passed**
  (6 subtests), including the frozen-oracle parity test (it skips if local
  DEVELOPMENT data is absent).
- 2026-09-30 (M5B), `tests/test_mnq_orb_v02_features.py` **26 passed**;
  `tests/test_session_context.py` **33 passed**.
- 2026-09-30 (M5B), full suite: **352 passed, 0 failed** (180 subtests).
  That is the 341 baseline plus the 11 new tests. This was the last frozen
  baseline before M6A.
- 2026-09-29 (M5A), `tests/test_session_context.py`: **33 passed**
  (39 subtests).
- 2026-09-29 (M5A), full suite: **341 passed, 0 failed** (174 subtests).
  That is the 308 baseline plus the 33 new tests.

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
