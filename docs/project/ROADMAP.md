# Roadmap

Related: [WORK_PROGRESS](WORK_PROGRESS.md) · [DECISION_LOG](DECISION_LOG.md) ·
[ARCHITECTURE_MAP](ARCHITECTURE_MAP.md).

High-level only. No deadlines. Status vocabulary: `DONE`, `ACTIVE`, `NEXT`,
`PLANNED`, `PARKED`.

| # | Workstream | Status |
|---|---|---|
| 0 | Platform foundations (data partitions, custom execution, ledger, dashboard, Lifecycle V1.0, registration API) | DONE |
| 1 | MNQ ORB research (V0.1 full cycle; V0.2 Stage 2 features + Stage 3A–3C) | DONE → **PARKED** |
| 1a | Keep ORB evidence frozen as the regression/parity oracle; migrate its reusable market context to generic code only after parity (D-110) | ACTIVE (maintenance only) |
| 2 | Architecture cleanup: reusable primitives (one milestone at a time, each separately approved) | **ACTIVE** |
| 2.M1 | Generic session model and calendar overrides | **DONE** (2026-09-28) |
| 2.M2 | Instrument metadata loader | NEXT (awaiting approval) |
| 2.M3 | Generic timeframe builder, on demand (5m/15m/1H/4H/Daily) | PLANNED |
| 2.M4 | Derived-timeframe persistence and manifest | PLANNED (Parquet decision pending) |
| 2.M5 | Generic Market Context session levels + ORB parity tests | PLANNED |
| 2.M6 | Generic level-interaction primitives + ORB parity tests | PLANNED |
| 2.M7 | Minimal State/Signal contracts | PLANNED |
| 2.M8 | Test tiers (unit / golden / integration) | PLANNED |
| 2.M9 | Legacy ledger deprecation notice | PLANNED |
| 3 | ICT research family (separate from ORB) | ACTIVE (design) |
| 3.1 | External + Internal Liquidity, specified together (HTF context, LTF structure, timeframe hierarchy, contract rolls, swings, EQ/REQ) | NEXT design run |
| 3.2 | FVG, Rejection Block, MSS | PLANNED (after 3.1) |
| 4 | Visual and programmatic validation of each ICT primitive, then freeze | PLANNED (per primitive) |
| 5 | ICT Phase 2: strategy/model construction (Turtle Soup / liquidity-raid candidate) | PLANNED, blocked on Phase 1 |
| 6 | Broader experiment work (more families/instruments, experiment runner) | PLANNED |
| 7 | NautilusTrader migration/parity using validated features and the ORB oracle | PLANNED (downstream; no refactor now) |
| — | London ORB idea; NY pre-market opposite-side liquidity idea (`research_ideas.json`) | PARKED |

## Sequencing rules

- Architecture milestones are approved and delivered one at a time.
- ICT liquidity implementation waits for its joint External/Internal
  specification and the foundations it depends on: M1, the timeframe builder,
  and roll handling.
- Phase 2 does not start until the required Phase 1 primitives are
  `APPROVED`/`FROZEN` (see [QUALITY_CONTROL](QUALITY_CONTROL.md)).
- No ORB optimization cycle restarts without explicit authorization.
- Nautilus work consumes validated definitions; it does not drive changes
  here.
