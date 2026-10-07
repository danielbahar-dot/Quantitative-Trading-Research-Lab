# Roadmap

Related: [WORK_PROGRESS](WORK_PROGRESS.md) · [DECISION_LOG](DECISION_LOG.md) ·
[ARCHITECTURE_MAP](ARCHITECTURE_MAP.md).

High-level only. No deadlines. Status vocabulary: `DONE`, `ACTIVE`, `NEXT`,
`PLANNED`, `PARKED`, `DEFERRED`, `BLOCKED`.

| # | Workstream | Status |
|---|---|---|
| 0 | Platform foundations (data partitions, custom execution, ledger, dashboard, Lifecycle V1.0, registration API) | DONE |
| 1 | MNQ ORB research (V0.1 full cycle; V0.2 Stage 2 features + Stage 3A–3C) | DONE → **PARKED** |
| 1a | Keep ORB evidence frozen as the regression/parity oracle; migrate its reusable market context to generic code only after parity (D-110). Known historical limitation: previous-available-session "previous day" around roll gaps (D-121) | ACTIVE (maintenance only) |
| 2 | Architecture cleanup: reusable primitives (one milestone at a time, each separately approved) | **ACTIVE** |
| 2.M1 | Generic session model and calendar overrides | **DONE** (2026-09-28) |
| 2.M2 | Instrument metadata loader | **DONE** (2026-09-29) |
| 2.M3 | Generic timeframe builder, on demand (5m/15m/1H/4H/Daily) | **DONE** (2026-09-29) |
| 2.M3.1 | Completeness / source-data audit (DEVELOPMENT) | **DONE** (2026-09-29) |
| 2.M4 | Derived-timeframe persistence (Parquet + manifest) | **DONE** (2026-09-29) |
| 2.M5A | Generic Market Context library (Previous Day, Previous RTH, Asia, London, Overnight, Overnight Context, NY Pre-market); continuity-aware (D-123, D-124) | **DONE — APPROVED / FROZEN** (2026-09-30) |
| 2.M5B | ORB consumes the generic catalog: compatibility only for the legacy 18:00–09:30 overnight and previous-available-session selection; exact frozen parity (D-125) | **DONE** (2026-09-30; merged, PR #4) |
| 2.M6 | Generic level-interaction primitives (M6A generic engine; M6B ORB migration with parity); stateless, continuity-aware | **COMPLETE** (2026-10-01; D-126–D-128). M6A merged (PR #5): `src/features/level_interactions.py`. M6B merged (PR #6): ORB consumes it via `src/experiments/orb_level_interaction_compat.py`, with exact frozen parity on 234/234 columns |
| 2.M7 | Minimal State/Signal contracts; continuity-aware | **COMPLETE** (2026-10-01; D-129–D-132). M7A merged (PR #7): generic event-based State contract in `src/state/contract.py`. M7B merged (PR #8): generic Signal contract in `src/signals/contract.py`. These are envelopes only; no real State or Signal family is implemented |
| 2.M8 | Test tiers (unit / golden / integration) | PLANNED |
| 2.M9 | Legacy ledger deprecation notice | PLANNED |
| 3 | **Generic Market Structure & Liquidity**: methodology-neutral primitives usable by any strategy family (mean reversion, breakout, Wyckoff, SMC/ICT, order flow, statistical). Not ICT-specific (D-133). Continuity-aware; may proceed before D1 | **ACTIVE** |
| 3.1 | External Liquidity (static): complete Daily H/L, selected session/reference H/L, Daily and 4H EQ/REQ structures (`docs/project/EXTERNAL_LIQUIDITY_SPEC.md`; D-134) | **DONE — APPROVED / FROZEN** (2026-10-04). `src/liquidity/contract.py` + `src/features/external_liquidity.py`; frozen DEVELOPMENT baseline in spec §18 / D-134 freeze note |
| 3.2 | Swing Structure (generic market-structure primitive). Objectively defined and frozen **before** Internal Liquidity; not every swing is liquidity (D-133 clarification) | **DONE — APPROVED / FROZEN** (2026-10-05; `docs/project/SWING_STRUCTURE_SPEC.md` rev 3; D-135–D-138). `src/market_structure/{swing,swing_detector}.py`, 1m–1D with one detector; DEVELOPMENT 2/2 reference baseline 119,381 swings; fingerprint `b6876266…218f`; machine gates and human visual review PASS (SW-I0–SW-I3). May later be consumed by a separate generic Market Structure workstream (Structural Direction, Protected Swing, Structure Break, BOS / CHoCH / MSS), not implemented |
| 3.3 | Internal Liquidity (static): may consume lower-timeframe EQ/REQ and generic Swing High/Low structures (3.2); decides which swings qualify. Same member/structure envelope | **DONE — APPROVED / FROZEN** (2026-10-07; `docs/project/INTERNAL_LIQUIDITY_DESIGN.md` rev 4; D-143 – D-147; D-143 freeze note; merged via PR #16) |
| 3.4 | Shared Liquidity Lifecycle: consumes External (3.1) and Internal (3.3) members, using M6 and M7. Designed only after both static representations exist | PLANNED |
| 3.MS (draft numbering) | Generic Market Structure: neutral swing-referenced Structure Break, Protected Swing, Structural Direction, BOS, CHoCH (versioned classifications; consumes 3.2). MSS deferred (D-133 clarification 2026-10-05, K-12) | **DONE — APPROVED / FROZEN** (2026-10-06; spec rev 2.5; D-139–D-142; merged via PR #14, `434d919`). MS-I1 – MS-I3; frozen DEVELOPMENT baseline in the D-139 freeze note. Signal adapter (MS-I4), MSS, liquidity and hierarchy deferred |
| 4 | Methodology-specific feature families, downstream of 3 (e.g. ICT/SMC: FVG, IFVG, Order Block, Rejection Block, Mitigation Block). BOS / CHoCH are generic (3.MS, K-12). MSS stays deferred, including any displacement / FVG / liquidity qualification, and its placement remains open | **ACTIVE — FVG / IFVG / overlap / BPR: DESIGN APPROVED — IMPLEMENTATION AUTHORIZED** (2026-10-07; `docs/project/FVG_IFVG_BPR_DESIGN.md` rev 2.1; D-148 – D-152; branch `fvg-design`; not implemented / validated / frozen). Other families PLANNED |
| 5 | Visual and programmatic validation of each primitive, then freeze | PLANNED (per primitive) |
| 6 | Strategy/model construction (e.g. Turtle Soup / liquidity-raid candidate) | PLANNED; blocked on the required primitives. Final broad performance validation where roll periods matter needs D1 |
| 7 | Broader experiment work (more families/instruments, experiment runner) | PLANNED |
| 8 | NautilusTrader migration/parity using validated features and the ORB oracle | PLANNED (downstream; no refactor now) |
| **D1** | **Contract stitching / source-data repair + verified holiday / early-close calendar** (data-quality gate, not an architecture milestone; D-120 as revised by D-123) | **DEFERRED** until required for continuous-history research |
| — | Frozen ORB previous-day sensitivity analysis around roll gaps (D-121) | PARKED (future, needs authorization) |
| — | London ORB idea; NY pre-market opposite-side liquidity idea (`research_ideas.json`) | PARKED |

## D1: deferred, and what it gates

The M3.1 DEVELOPMENT audit found that:

- the Monday–Thursday sessions of every quarterly roll week are absent (16
  sessions);
- each roll Friday starts at 00:01;
- the holiday / early-close calendar is empty.

These gaps are a **known source-data limitation**. They are not repaired
now, and feature code must not silently work around them.

**Work that may proceed before D1:** M5, M6, M7, and the Generic Market
Structure & Liquidity library (3.x). These must be **continuity-aware** (D-123; checklist in
[QUALITY_CONTROL](QUALITY_CONTROL.md)):

- never substitute an older available session for a missing expected
  session;
- if an expected input session is absent, mark the feature unavailable with
  an explicit reason;
- never carry multi-session state across missing expected sessions
  implicitly;
- never aggregate across mixed contracts.

**D1 remains a required gate before:**

- research that assumes continuous history across contract rolls;
- final broad strategy-performance validation where roll periods matter;
- carrying cross-session or cross-contract structures through known
  source-data gaps;
- any methodology that needs a canonical stitched continuous contract.

The D1 technical solution is not defined. Contract-stitching design is a
future dedicated task.

## Sequencing rules

- Architecture milestones are approved and delivered one at a time.
- Reusable feature work (M5+) may proceed before D1 only if it is
  continuity-aware (D-123).
- Market-structure and liquidity work proceeds in this order (D-133, as
  clarified):
  1. External Liquidity (3.1), static;
  2. Swing Structure (3.2);
  3. Generic Market Structure (3.MS, draft numbering; administrative
     sequencing, N-4);
  4. Internal Liquidity (3.3), static;
  5. the Shared Lifecycle (3.4), designed only after both static liquidity
     representations exist.
- Strategy construction (6) does not start until the required primitives
  are `APPROVED`/`FROZEN` (see [QUALITY_CONTROL](QUALITY_CONTROL.md)).
- No ORB optimization cycle restarts without explicit authorization.
- Nautilus work consumes validated definitions; it does not drive changes
  here.
