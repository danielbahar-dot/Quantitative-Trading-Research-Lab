# Project Overview

Related: [ARCHITECTURE_MAP](ARCHITECTURE_MAP.md) ·
[RESEARCH_GOVERNANCE](RESEARCH_GOVERNANCE.md) · [ROADMAP](ROADMAP.md) ·
root [README](../../README.md) (detailed platform reference).

## Mission

Support rigorous, causal, reproducible quantitative trading research: define
market concepts precisely, validate them visually and programmatically, and
only then test them as trading hypotheses under strict partition discipline.

This is a research environment. It is not a live-trading system and makes no
claim of future profitability.

## Major use cases

- Qualify and partition market data (currently MNQ 1-minute futures bars).
- Build and validate causal features, states, and signals with audit exports
  and chart-based human review.
- Execute strategy rules through a custom, auditable execution engine where
  intrabar/session/futures behavior matters.
- Run DEVELOPMENT exploration, robustness, candidate freeze, and confirmatory
  VALIDATION under Research Lifecycle V1.0.
- Register experiments, artifacts, and lineage; browse them in a read-only
  dashboard.
- Serve as a future regression/parity oracle for the NautilusTrader platform.

## Research philosophy

- No look-ahead; causal availability is explicit for every derived value.
- Deterministic rules; explicit timestamp and session semantics.
- Visual validation before trusting new signals; negative-case testing.
- Automated invariants and auditable intermediate outputs.
- Explicit DEVELOPMENT / VALIDATION / OOS separation.
- Frozen artifacts once a research stage closes.
- No performance optimization before the underlying feature/signal is
  validated. Performance is never evidence that a definition is correct.

## Conceptual pipeline

```text
Raw Data → Validated / Clean Data → Features → State Variables → Signals
→ Strategy Definition / Eligibility → Execution Engine → Completed Trades
→ Experiment Engine → Analytics → Experiment Ledger
→ Research Dashboard / Visual Validation
```

## Layer distinctions

**FEATURE ≠ STATE ≠ SIGNAL ≠ STRATEGY ≠ EXECUTION**

| Layer | Meaning | Example (existing) |
|---|---|---|
| Feature | Measurable market information; decides nothing | OR high/low/width; Asia/London/NY pre-market high/low |
| State | Causal condition at a decision timestamp | Causal OR-width percentile vs prior sessions |
| Signal | Auditable market event, recorded even if not traded | ORB PRINT/CLOSE breakout event |
| Strategy | Eligibility, entry/exit/risk rules combining components | MNQ ORB V0.1 candidate definitions |
| Execution | Fills, stops, targets, session exits, ambiguity | `src/backtesting/` custom engine |

## Role of VectorBT

VectorBT is used where vectorized assumptions are faithful: analytics,
parameter arrays, generic numerical cross-checks, drawdown checks, and
visualization. It is **not** the universal execution source of truth; ORB is not
forced into `Portfolio.from_signals()` because trade semantics would change.

## Role of custom execution

The custom engine (`src/backtesting/`) is authoritative whenever behavior
depends on intrabar order, entry-bar eligibility, next-bar fills, session
cutoffs, forced exits, trade limits, or ambiguity/exclusion rules. Completed
trades and candidate audits are canonical; equity curves and summaries are
derived.

## Relationship to NautilusTrader

A separate NautilusTrader-based platform is being developed as the eventual
execution/runtime architecture (see
`SYSTEM_DESIGN_AND_NAUTILUS_TRANSFER_ARCHITECTURE.md`, not modified here).

- This repository remains independently usable and the research source of
  truth for current work.
- Migration is **downstream**: validated reusable concepts may later be ported,
  with parity tests against this repository's batch implementations.
- No current refactoring toward Nautilus is authorized.

## Research families

| Family | Status | Notes |
|---|---|---|
| MNQ ORB (V0.1, V0.2) | `PARKED_AS_RESEARCH_CANDIDATE` | Frozen evidence; future parity oracle |
| ICT | Starting (Phase 1, feature-first) | Separate family; not an ORB extension |

## Repository boundaries

In scope: data qualification, features/states/signals, custom execution,
experiments, analytics, ledger, dashboard, viewers, research governance.

Out of scope here: live trading, broker connectivity, deployment, monitoring,
and the NautilusTrader runtime itself.
