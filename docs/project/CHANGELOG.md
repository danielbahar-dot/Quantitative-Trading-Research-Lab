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
