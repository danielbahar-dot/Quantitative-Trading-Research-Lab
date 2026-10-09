# Internal Changelog

Internal project log of meaningful changes to architecture, feature / state /
signal definitions, execution behavior, research methodology, data semantics,
validation tooling, and experiment infrastructure. Not a marketing changelog
and not a commit mirror — Git holds full history; the experiment ledger holds
run history.

Entry format: `YYYY-MM-DD — [AREA] summary (refs: commit / doc / decision)`.
Areas: `ARCH`, `FEATURE`, `STATE`, `SIGNAL`, `EXECUTION`, `METHOD`, `DATA`,
`VALIDATION-TOOLING`, `EXPERIMENT-INFRA`, `DOCS`.

## Unreleased

- 2026-10-09 — [VALIDATION-TOOLING] Order Block review corrections (PR #19 at `ae8a462`): exact ownership
  deadlines (only left-qualified swing candidates wait; §22 prose corrected), evidence never known before its
  episode (OB-INV-14), causally reconstructed visit prefix comparison, per category × timeframe reference coverage
  and an evidence-coverage CSV, visual package corrections. DEVELOPMENT evidence regenerated from `ae1462e`;
  pending human visual approval.

- 2026-10-08 — [FEATURE] Order Block / Breaker / Mitigation (ROADMAP 4, ICT
  family) implemented in `src/ict_blocks/` (D-153 – D-157; design rev 3 + §22).
  - Swing-episode discovery (N = 1), single terminal source candle (body ≥ 4
    ticks, no fallback), open-to-wick geometry, FVG departure within the
    inclusive window, persistent block lifecycle with parent-pinned BB / MB
    motifs, 1m stage interactions, gap / roll resets, M7A `ict.block` log.
  - DEVELOPMENT machine validation passed (independent reference on every
    timeframe, 0 mismatches; OB-INV-* = 0; prefix and shuffle checks).
    Pending human visual approval; not frozen.

- 2026-10-08 — [VALIDATION-TOOLING] FVG validation runner: fast tier and
  visual speed-up (`6bc7490`; no semantic change).
  - Visual case selection builds mover-provenance lookups once per run:
    7,303 s → 33 s on full DEVELOPMENT; output byte-identical.
  - `--fast` / `--start --end` run the same checks on a DEVELOPMENT window
    (full-DEV-only gates SKIPPED, not PASS; outputs Git-ignored); `--out`
    redirects outputs. Full tier unchanged (default), now ~45 minutes.
  - Full-tier re-verification: identical to the frozen FVG evidence except
    runtime and provenance rows.

- 2026-10-08 — [FEATURE] FVG / IFVG / FVG_OVERLAP / BPR / MTF_BPR (ROADMAP 4)
  is **APPROVED / FROZEN** (D-148 – D-152; D-148 freeze note; PR #17).
  - Human visual approval on the 34-case package from `4887537`.
  - Frozen DEVELOPMENT baseline: FVG-INV-1 … 27 = 0, full-run recomputation =
    production, overall fingerprint `4c182a8c9fc0eae3…`. Suite: 808 passed /
    6,345 subtests (+3 visual-helper tests).

- 2026-10-08 — [VALIDATION-TOOLING] FVG review corrections (PR #17 at `ee6eb27`).
  - Strategy views (`active_bprs`, `active_overlaps`, `active_fvg_zones`) are
    causal as-of projections; `bprs_as_of` / `episodes_as_of` /
    `stages_as_of` added; active views carry no exit metadata.
  - Prefix equivalence compares canonical payloads of every table plus the
    strategy views and ranks; duplicates counted separately; negative tests.
  - `src.fvg.audit_full`: full-run independent recomputation (0 mismatches on
    4,199,171 DEVELOPMENT rows); subset-reference coverage reported per
    category and timeframe.
  - Visual package: BPR / MTF_BPR cases selected and asserted by mover
    provenance (admission- and conversion-created separated); association
    record vs marker activation; capped tables labelled; BPR exit predicate;
    partner source spans; source provenance header. Evidence regenerated from
    `4887537`. Still pending human visual approval.

- 2026-10-07 — [FEATURE] FVG / IFVG / FVG_OVERLAP / BPR / MTF_BPR (ROADMAP 4,
  ICT family) implemented in `src/fvg/` (D-148 – D-152; design rev 2.1).
  - Formation with C2 body rule and rejection audit, normalized strength,
    1m mitigation by observation class, FVG → IFVG → RETIRED lifecycle,
    stage-keyed relationship episodes, independent BPR lifecycle, formation
    groups and grades, first-FVG leg association, M7A logs.
  - DEVELOPMENT machine validation passed (FVG-INV-1 … 27 = 0; engine =
    reference on 12 / 33 1m episodes; 13 prefix rebuilds, 0 mismatches).
    Pending human visual approval; not frozen.

- 2026-10-07 — [FEATURE] Internal Liquidity (3.3) is **APPROVED / FROZEN** (D-143 – D-147;
  D-143 freeze note; PR #16).
  - Shared tolerance consumption contract (internal 4 / External 6 ticks),
    5m / 15m / 1H formation atoms, price-anchored levels with grades, price
    records, External ranges with pinned boundary assignments, M7A lifecycles.
  - Human visual approval on the corrected package (`9dd62ca`); boundary tie
    order confirmed.
  - Frozen DEVELOPMENT baseline: IL-INV-1 … IL-INV-20 = 0, engine = reference,
    overall fingerprint `3727767b77fc0cd0…`. Suite: 758 passed / 590 subtests.
  - Next is FVG / IFVG / BPR (design).

- 2026-10-06 — [FEATURE] Generic Market Structure (3.MS) is **APPROVED /
  FROZEN** (D-139 – D-142; D-139 freeze note; PR #14, `434d919`).
  - Neutral swing breaks, structural direction, protected swing, BOS /
    CHoCH, and the reset adapter with an explicit replay cutoff.
  - Frozen DEVELOPMENT baseline: all six timeframes, INV-1 … INV-17 = 0, 0
    anomalies, overall fingerprint `03f0a2d92679c56f…`.
  - Suite: 702 passed / 493 subtests.
  - Next is 3.3 Internal Liquidity (design proposal).

- 2026-10-04 — [FEATURE] External Liquidity 3.1 is **APPROVED / FROZEN**
  (D-134 freeze note; spec §18).
  - Frozen DEVELOPMENT baseline:
    - 2,553 members and 86 structures;
    - 438 Previous Day references;
    - 3,326 candidates, 50 breaks, 412 barrier blocks;
    - 169 promoted 4H;
    - FORMED 84 / EXTENDED 2 / MERGED 0;
    - invariants 0.
  - Suite: 543 passed / 382 subtests.
  - Next is 3.2 Swing Structure (not started).

- 2026-10-03 — [VALIDATION-TOOLING] External Liquidity pre-freeze review
  corrections. There is no semantic change, and canonical DEVELOPMENT
  output is identical.
  - `canonical_id_tuple` now rejects duplicate `member_ids` /
    `supersedes` instead of deduplicating them.
  - `barrier_blocks` gains `blocking_bar_end` (nearest the later endpoint
    among equal extremes) and `blocking_excess_ticks`.
  - The generic SourceRef test is renamed to state that refs are opaque.
  - Added an audit invariant: a version is superseded at most once.
  - The visual now annotates the blocker and staggers labels.
  - Tests: 543 passed / 382 subtests.

- 2026-10-03 — [FEATURE] External Liquidity (static) implemented. It is
  **not frozen**: visual and design-authority validation is pending.
  - Added `src/liquidity/contract.py`, the generic member/structure
    envelope with SHA-256 ids and validation.
  - Added `src/features/external_liquidity.py`
    (`build_external_liquidity`). It produces:
    - Daily H/L members and session-reference members;
    - the Previous Day reference view;
    - continuity on the M3 expected schedule;
    - Daily/4H EQ/REQ immutable versions with the pair-outer barrier and
      4H promotion.
  - Added `tests/test_liquidity_contract.py` (13) and
    `tests/test_external_liquidity.py` (37). Full suite: 537 passed.
  - DEVELOPMENT audit CSVs (price-free) are in `reports/validation/`; the
    visual HTML is local.
  - Doc cleanups:
    - the EL-I0 test oracle is reworded as a "frozen pre-refactor
      geometry/aggregation reference for valid source fixtures";
    - roadmap sequencing is now External → Swing → Internal → Shared
      Lifecycle (D-133 clarification).

- 2026-10-03 — [DATA] EL-I0: M3 expected timeframe schedule API (a
  backward-compatible capability extension).
  - Added `src/data/timeframes.expected_timeframe_schedule()`. It returns
    the expected bucket geometry (`timeframe`, `trading_date`, `bar_start`,
    `bar_end`, `available_at`, `expected_bars`, `is_session_truncated`)
    without source data, including buckets with no observations.
  - `build_timeframe` now shares private geometry and metric helpers with
    it. Its output is unchanged: DEVELOPMENT 1D/4H/1H/15m/5m are exactly
    equal to a pre-refactor capture, and the M4 cache matches.
  - `TIMEFRAME_BUILDER_VERSION` is unchanged (1).
  - Added `tests/test_timeframe_schedule.py` (13 tests), including a frozen
    pre-refactor parity oracle.

- 2026-10-01 — [SIGNAL/ARCH] M7B generic Signal contract (D-132). M7 is
  complete.
  - Added `src/signals/contract.py`, which provides:
    - `SignalDefinitionSpec`, `SignalContractError`, `DIRECTIONS`,
      `FORBIDDEN_EXECUTION_FIELDS`;
    - `signal_id`, using the full SHA-256;
    - `assign_signal_ids` and `validate_signals`.
  - It reuses the public M7A primitives; M7A is unchanged.
  - Added `tests/test_signal_contract.py` (28 tests), synthetic definitions
    only.
  - Full suite: 474 passed.

- 2026-10-01 — [STATE/ARCH] M7A generic State contract (D-129).
  - Added `src/state/contract.py`. It provides:
    - `StateNamespaceSpec`, `AttributeSpec` and `SourceRef`;
    - `transition_id`, using the full SHA-256;
    - causal-key helpers;
    - `validate_transitions`, `state_as_of`,
      `materialize_state_to_observations` and `materialize_state_to_bars`.
  - The contract is event / observation based rather than bar-specific,
    with optional `(seq_domain, seq)` pairs.
  - Each transition has a required `trigger_ref`, and consumers are strict
    (D-130).
  - `validate_transitions` has no `decision_offset`; trigger eligibility is
    owned upstream (D-131).
  - Added `tests/test_state_contract.py` (46 tests), synthetic namespaces
    only.
  - M7 spec rev 3 is approved. No Signals yet, and M5, M6 and ORB are
    unchanged.
- 2026-10-01 — [FEATURE/ARCH] M6B ORB level-interaction migration (D-128).
  M6 is complete.
  - Added `src/experiments/orb_level_interaction_compat.py`. Each aggregated
    OR window is evaluated through the M6A engine. The only compatibility
    rule is open-at-level (AT → directional flags False). ORB distances and
    the 13-field schema are kept.
  - `build_feature_audit` now makes one batched M6A evaluation.
  - Removed `market_context.level_interaction`. The London characterization
    script and the ORB feature tests import the adapter's legacy-signature
    `level_interaction` instead.
  - Exact frozen parity on all 234 `level_*` columns (and all 474).
  - Added `tests/test_orb_level_interaction_compat.py` (19 tests).
  - Snapped two synthetic test fixtures to the 0.25 tick grid, with
    assertions unchanged.
  - Full suite: 400 passed.
- 2026-10-01 — [FEATURE] M6A generic Level Interaction catalog (D-126,
  D-127).
  - Added `src/features/level_interactions.py`, a stateless per-bar
    evaluator:
    - five primitives (TOUCH, TRADE_THROUGH, CLOSE_THROUGH, REJECT, SWEEP),
      using exact integer-tick rules that also handle off-grid levels;
    - UPPER / LOWER / NEUTRAL orientation, with `approach_side` /
      `approach_relation`;
    - `SPECIFIC` / `AGNOSTIC` contract scope and raw offset ticks;
    - `valid_from` / `valid_until` applicability bounds;
    - an M5 helper.
  - Added `tests/test_level_interactions.py` (29 tests).
  - Validation artifacts in `reports/validation/`:
    - `m6a_level_interactions_dev_summary.csv` and `*_cases.csv` (tracked,
      price-free);
    - the visual HTML (local, Git-ignored).
  - ORB unchanged.
- 2026-09-30 — [FEATURE/ARCH] M5B ORB Market Context migration.
  - ORB `build_feature_audit` now consumes the generic catalog through
    `src/experiments/orb_market_context_compat.py`.
  - Compatibility is only for genuine historical differences:
    - `orb_overnight_1800_0930`, in the new
      `config/features/market_context_compatibility.json`;
    - legacy previous-available-session selection for Previous Day / RTH.
  - `session_context.py` exposes `evaluate_context` / `prepare_context_bars`
    (behavior unchanged).
  - Exact frozen-ORB parity, with the oracle SHA-256 recorded.
  - Added `tests/test_orb_market_context_compat.py` (11 tests). Three ORB
    test fixtures moved from Sunday to weekday dates, with assertions
    unchanged. (D-125)

- 2026-09-29/30 — [FEATURE] M5A Generic Market Context.
  - Added `src/features/session_context.py` and the registry
    `config/features/market_context_windows.json`.
  - Contexts: `previous_day`, `previous_rth`, Asia, London,
    `overnight_1800_0700`, `overnight_context_2000_0900`, NY pre-market.
  - Behavior: previous-expected-session selection, strict completeness,
    controlled unavailable reasons, and causal, contract-aware alignment.
  - Added `tests/test_session_context.py` (33 tests) and
    `docs/project/M5_MARKET_CONTEXT_SPEC.md`.
  - DEVELOPMENT validation: exact frozen-ORB parity for the four identical
    windows; Previous Day / RTH differ only on the 6 D-121 dates. Visual
    validation artifacts are in `reports/validation/`.
  - No ORB code changed. (D-124)

- 2026-09-29 — [DATA/EXPERIMENT-INFRA] M4 derived-timeframe persistence.
  - Added `src/data/timeframe_store.py`: Parquet + JSON manifest,
    provenance-validated loads, a stale-cache error, a reserved-partition
    guard, and atomic writes.
  - `TIMEFRAME_BUILDER_VERSION` added to `timeframes.py`. `pyarrow==25.0.1`
    pinned. `data/derived/` Git-ignored.
  - Added `tests/test_timeframe_store.py` (17 tests).
  - DEVELOPMENT materialization matches M3.1 exactly. (D-122)

- 2026-09-29 — [DATA/METHOD] M3.1 DEVELOPMENT completeness audit.
  - Builder accounting reconciled independently (0 mismatches). All 337,815
    bars match the session model.
  - The 28 incomplete daily bars are source-data / calendar caused.
  - 16 roll-week Mon–Thu sessions are absent, and roll Fridays start at
    00:01.
  - Artifact: `reports/validation/m3_1_dev_daily_incompleteness.csv` plus a
    README.
  - Added the D1 data-quality gate to the roadmap (D-120). Recorded the
    frozen ORB previous-day limitation without changing ORB (D-121).

- 2026-09-29 — [DATA/ARCH] M3 generic timeframe builder (on demand).
  - Added `src/data/timeframes.py` and `tests/test_timeframes.py`
    (25 tests).
  - Additive vectorized `assign_trading_dates()` in `src/data/sessions.py`,
    parity-tested against the scalar rule. Existing session semantics are
    unchanged.
  - A DEVELOPMENT-only smoke check confirmed that the dataset `session_date`
    matches the session model.
  - No persistence. No ORB code changed. (D-119)

- 2026-09-29 — [DATA/ARCH] M2 generic instrument metadata.
  - Added `src/data/instruments.py`: `load_instrument` → frozen
    `InstrumentSpec` with exact `Decimal` economics, `is_tick_aligned`, and a
    small error hierarchy.
  - Added `tests/test_instruments.py` (19 tests), including guards for the
    legacy `TICK_SIZE` and the frozen `mnq.json` provenance hash.
  - `mnq.json` unchanged. No consumer migrated. No ORB code changed. (D-118)

- 2026-09-28 — [DATA/VALIDATION-TOOLING] M1.1 stabilization.
  - `is_maintenance_break()` is True only for the Mon–Thu between-session
    break. Friday ≥17:00 and Sunday <18:00 are `NON_TRADING_DAY`.
  - Stale pre-Stage-3 test expectations updated to the verified current
    state:
    - `test_experiment_index.py`: explicit V0.2 record identities instead of a
      count of 22;
    - `test_research_dashboard.py`: Stage 3 filter lists the three V0.2
      Stage 3 records;
    - `test_mnq_orb_v02_features.py`: manifest is `RESEARCH_PARKED`, not
      approved for the next phase, per closure commit `d129a98`.
  - Full suite: 247 passed, 0 failed. No production or ORB code changed.

- 2026-09-28 — [DATA/ARCH] M1 generic session model: `src/data/sessions.py`,
  `config/sessions/cme_globex_et.json`, empty override calendar
  `cme_globex_et.overrides.json`, `tests/test_sessions.py` (27 tests). No
  existing code changed. (D-111 – D-113)
- 2026-09-28 — [ARCH/METHOD] Architecture closeout: reusable-primitives
  target architecture, generic windows, level-interaction semantics, derived
  timeframe rules, deferrals recorded. (D-110, D-114 – D-117)

- 2026-09-24 — [DOCS] Documentation / project-memory layer added: `CLAUDE.md`,
  `docs/project/*`; `MEMORY.md` restructured; README documentation-ownership
  section updated. (D-109)
- 2026-09-24 — [METHOD] ICT research family opened as separate from ORB;
  feature-first Phase 1; External Liquidity direction recorded (not
  implemented). (D-102 – D-107)

## Historical milestones (high level)

- 2026-09-13 — [ARCH] NautilusTrader transfer architecture document added
  (reference only; no refactor). (`e2f1474`)
- 2026-09-06 – 09-07 — [STATE/SIGNAL] MNQ ORB V0.2 Stage 3A–3C
  characterization; research closed as `PARKED_AS_RESEARCH_CANDIDATE`.
  (`d542dd6` … `d129a98`; D-101)
- 2026-09-02 — [FEATURE] MNQ ORB V0.2 Stage 2 causal feature package
  validated and frozen (session windows, previous trading-day levels, gaps,
  causal width history, key-level interaction primitives). (`0120af8`; D-004)
- 2026-08-25 — [EXPERIMENT-INFRA/METHOD] Research Lifecycle V1.0 and Research
  Infrastructure V1.0 (registration API, component registry). (`5c74363`,
  `82f4247`)
- 2026-08-24 — [VALIDATION-TOOLING] Read-only research dashboard and
  experiment registry. (`a908160`)
- 2026-08-24 — [METHOD] ORB V0.1 candidate freeze, Gate 7 Validation
  (REVISE / REJECT / REJECT), Gate 8A diagnosis. (`b244538`–`be786fb`; D-005)
- 2026-08-23 – 08-24 — [METHOD] ORB V0.1 DEVELOPMENT diagnostics, parameter
  surfaces, robustness. (`8b8842f`–`8198f19`)
- 2026-08-21 — [DATA] Research data partitions. (`e056d61`; D-003)
- 2026-08-20 — [EXECUTION/DATA] NT8 bar-end timing correction; validated ORB
  V0.1 trade execution pipeline. (`71c96f0`, `188bf39`; D-002)
- 2026-08-19 — [ARCH] Initial validated ORB research platform baseline.
  (`3be81e2`)
