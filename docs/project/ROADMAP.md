# Roadmap

Related: [WORK_PROGRESS](WORK_PROGRESS.md) · [DECISION_LOG](DECISION_LOG.md) ·
[ARCHITECTURE_MAP](ARCHITECTURE_MAP.md).

High-level only. No deadlines. Status vocabulary: `DONE`, `ACTIVE`, `NEXT`,
`PLANNED`, `PARKED`, `BLOCKED`, `REQUIRED GATE`.

| # | Workstream | Status |
|---|---|---|
| 0 | Platform foundations (data partitions, custom execution, ledger, dashboard, Lifecycle V1.0, registration API) | DONE |
| 1 | MNQ ORB research (V0.1 full cycle; V0.2 Stage 2 features + Stage 3A–3C) | DONE → **PARKED** |
| 1a | Keep ORB evidence frozen as the regression/parity oracle; migrate its reusable market context to generic code only after parity (D-110). Known limitation: dataset-previous "previous day" around missing roll-week sessions (D-121) | ACTIVE (maintenance only) |
| 2 | Architecture cleanup: reusable primitives (one milestone at a time, each separately approved) | **ACTIVE** |
| 2.M1 | Generic session model and calendar overrides | **DONE** (2026-09-28) |
| 2.M2 | Instrument metadata loader | **DONE** (2026-09-29) |
| 2.M3 | Generic timeframe builder, on demand (5m/15m/1H/4H/Daily) | **DONE** (2026-09-29) |
| 2.M3.1 | Completeness / source-data audit (DEVELOPMENT) | **DONE** (2026-09-29) |
| 2.M4 | Derived-timeframe persistence and manifest | NEXT (awaiting approval; Parquet decision pending). Allowed before D1 |
| **D1** | **Source data / contract-roll reconstruction + holiday / early-close calendar.** A data-quality / research-validity gate, not an architecture milestone (D-120) | **REQUIRED GATE** before M5 and before any liquidity research relies on source data |
| 2.M5 | Generic Market Context session levels (incl. Previous Day) + ORB parity tests | **BLOCKED by D1** |
| 2.M6 | Generic level-interaction primitives + ORB parity tests | PLANNED |
| 2.M7 | Minimal State/Signal contracts | PLANNED |
| 2.M8 | Test tiers (unit / golden / integration) | PLANNED |
| 2.M9 | Legacy ledger deprecation notice | PLANNED |
| 3 | ICT research family (separate from ORB) | ACTIVE (design) |
| 3.1 | External + Internal Liquidity, specified together (HTF context, LTF structure, timeframe hierarchy, contract rolls, swings, EQ/REQ). Design may proceed; research on source data waits for D1 | PLANNED, research **BLOCKED by D1** |
| 3.2 | FVG, Rejection Block, MSS | PLANNED (after 3.1) |
| 4 | Visual and programmatic validation of each ICT primitive, then freeze | PLANNED (per primitive) |
| 5 | ICT Phase 2: strategy/model construction (Turtle Soup / liquidity-raid candidate) | PLANNED, blocked on Phase 1 |
| 6 | Broader experiment work (more families/instruments, experiment runner) | PLANNED |
| 7 | NautilusTrader migration/parity using validated features and the ORB oracle | PLANNED (downstream; no refactor now) |
| — | Frozen ORB previous-day sensitivity analysis around roll weeks (D-121) | PARKED (future, needs authorization) |
| — | London ORB idea; NY pre-market opposite-side liquidity idea (`research_ideas.json`) | PARKED |

## Why D1 is a gate

The M3.1 DEVELOPMENT audit found that:

- the Monday–Thursday sessions of every quarterly roll week are absent (16
  sessions);
- each roll Friday starts at 00:01;
- the holiday / early-close calendar is empty.

This matters for four reasons:

- **Previous-day traversal.** Naïve previous-day traversal over missing
  roll-week sessions silently jumps to an older session.
- **Multi-session objects.** Liquidity and state objects that span several
  sessions could silently bridge missing data.
- **Daily/4H structure.** Daily and 4H structures around rolls can be
  structurally misleading.
- **Closure vs missing data.** Without a verified calendar, a legitimate
  exchange closure cannot be told apart from missing source data (D-113).

M4 may precede D1 because persistence should faithfully preserve the current
source and its completeness metadata. The D1 technical solution is not yet
defined; contract-roll reconstruction design is a future dedicated task.

## Sequencing rules

- Architecture milestones are approved and delivered one at a time.
- D1 must be completed before generic Market Context / Previous Day logic
  (M5), and before External/Internal Liquidity research relies on source data.
- ICT liquidity implementation waits for its joint External/Internal
  specification and the foundations it depends on: M1, the timeframe builder,
  D1, and roll handling.
- Phase 2 does not start until the required Phase 1 primitives are
  `APPROVED`/`FROZEN` (see [QUALITY_CONTROL](QUALITY_CONTROL.md)).
- No ORB optimization cycle restarts without explicit authorization.
- Nautilus work consumes validated definitions; it does not drive changes
  here.
