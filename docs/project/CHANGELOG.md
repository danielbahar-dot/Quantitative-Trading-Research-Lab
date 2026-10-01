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
