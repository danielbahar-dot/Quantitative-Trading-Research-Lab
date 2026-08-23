# Project Memory

This is the durable handoff for validated state, research decisions, and
guardrails. It is intentionally not an experiment diary.

Update MEMORY only when a gate is implemented and validated, a durable platform
decision changes, a partition is opened/burned, or the authorized next step
changes. Put individual run parameters, metrics, charts, and conclusions in the
experiment ledger and project artifact directory.

## Platform objective

Build a reproducible quantitative trading research platform for multiple
strategy families and instruments/universes across futures, equities, ETFs, and
extensible future asset classes.

MNQ ORB V0.1 is the first reference project. It must remain reproducible, but
ORB timing, MNQ tick rules, and intraday limits are not platform-wide defaults.

## Durable platform guardrails

- Keep strategy, instrument/universe, dataset, partition, parameter, execution,
  cost, and code/environment identity separate.
- Signals record market conditions; execution records whether/how the strategy
  acts. Execution must not erase the signal record.
- Maintain candidate/audit records for invalid, ambiguous, excluded, or
  state-limit-rejected orders.
- The custom execution engine is authoritative when intrabar order, next-bar
  fills, session rules, ambiguity, or trade limits matter.
- Use VectorBT for faithful vectorized work, generic numeric cross-checks,
  parameter arrays, and visualization. Do not force ORB into
  `Portfolio.from_signals()` if trade semantics change.
- Canonical trades/audits are source artifacts; summaries/equity curves are
  derived.
- Raw data is immutable. Cleaned/processed data must be reproducible from a
  versioned source and transform.
- Every material run requires a config and ledger record with dataset ID/hash,
  partition, parameters, execution/costs, Git/source hash, environment,
  artifacts, status, and conclusion.
- A rerun creates a new `run_id`; completed history is never overwritten.
- Prefer stable parameter regions, temporal robustness, and economic rationale
  over the single best in-sample cell.

## Canonical architecture

```text
raw -> cleaned -> features/state -> signals -> candidates
-> strategy-aware execution -> completed trades/audit
-> analytics -> experiment artifacts/ledger -> gate decision
```

New strategy logic belongs in a strategy context. Instrument facts belong in
instrument/dataset configuration rather than strategy code.

## Partition policy

- Define DEVELOPMENT, VALIDATION, and OOS before inspecting results.
- DEVELOPMENT is the only place for parameter exploration.
- Freeze candidate and acceptance criteria before opening VALIDATION.
- VALIDATION is not a second development set; record failure before a new cycle.
- Open OOS only after final freeze.
- Relabel any period that influenced design/selection as burned; it is not
  untouched evidence.
- Assign by `session_date` unless an approved project specification says
  otherwise.

## Repository and artifact decisions

- Expected remote:
  `https://github.com/danielbahar-dot/Quantitative-Trading-Research-Lab.git`.
- Dataset configs: `config/datasets/`.
- Instrument configs: `config/instruments/`.
- Experiment grids: `config/experiments/`.
- Reviewed artifacts:
  `experiments/projects/<project_id>/<artifact_class>/`.
- Local runs: `experiments/runs/<run_id>/`.
- SQLite ledger/CSV mirror are generated local state; schema/templates are
  versioned.
- Preserve Python import paths during this housekeeping gate; do not move ORB
  modules solely for cosmetic abstraction.
- No `PROJECT_STATUS.md`; MEMORY owns current state.
- No `CHANGELOG.md` until releases/external consumers make it useful.

## Active reference project: `mnq_orb_v0_1`

### Validated timing

- MNQ one-minute NinjaTrader OHLC bars in Eastern Time.
- Dataset ID: `MNQ_1m_actual_contract_v1`.
- `timestamp_et = bar_end_time`.
- OR windows / first eligible bar:
  - 5m: 09:31-09:35 / 09:36.
  - 10m: 09:31-09:40 / 09:41.
  - 15m: 09:31-09:45 / 09:46.
  - 20m: 09:31-09:50 / 09:51.
  - 30m: 09:31-10:00 / 10:01.
- Signal cutoff is inclusive at 11:30 ET.

### Frozen baseline semantics

- Retain at most the first long and first short signal per session.
- PRINT enters at OR boundary on the signal bar with validated same-bar
  ambiguity rules.
- CLOSE enters at the immediately following bar's open; the signal bar never
  participates in execution or stop/target ambiguity.
- Baseline stop: OR midpoint. Target: 2R. Tick size: 0.25 points.
- Entry not beyond its stop is invalid.
- Execute earliest valid candidate only, maximum one trade/session per
  OR-duration/breakout variant.
- Invalid/ambiguous candidates do not consume the allowance. Rejected later
  candidates remain audited with `SESSION_TRADE_LIMIT`.
- SESSION_END, shortened sessions, holding time, MFE, and MAE are validated.
- No BE, trailing, FVG/EMA/VWAP, partial exits, commissions, or slippage.

Do not change these rules during analytics or Gate 6A. Rule changes require a
separately approved gate and strategy version when appropriate.

### Canonical local artifacts

- Bars: `data/MNQ_raw_cleaned_ET.csv`.
- OR levels: `data/processed/mnq_or_levels.csv`.
- Historical trades: `data/processed/orb_v01_completed_trades.csv`.
- Historical audit: `data/processed/orb_v01_candidate_audit.csv`.
- 20m DEV trades:
  `data/processed/orb_v01_20m_print_DEV_completed_trades.csv`.
- 20m DEV audit:
  `data/processed/orb_v01_20m_print_DEV_candidate_audit.csv`.
- Partitions:
  `config/datasets/mnq_1m_actual_contract_v1.partitions.json`.
- Reviewed outputs:
  `experiments/projects/mnq_orb_v0_1/baselines/`.

Market data, generated trade/audit tables, and local ledgers are ignored by Git.

### Counts and partition state

- Historical canonical table: 4,073 full-history trades across 5/10/15/30m
  PRINT and CLOSE.
- DEVELOPMENT: 2024-06-21 through 2025-06-30.
- VALIDATION: 2025-07-01 through 2025-12-31; do not inspect during development.
- OOS_BURNED: 2026-01-01 through 2026-08-17; full-history baseline performance
  was viewed before partitioning.
- Historical Gate 5B DEV diagnostics: 1,926 trades.
- Expanded comparison with 20m PRINT: 2,172 DEV trades; maximum session date
  2025-06-30.

### Durable Gate 5B interpretation

- All eight historical DEV variants had positive average R but -1R medians;
  larger winners offset frequent full losses.
- Profit factors were approximately 1.08-1.37.
- 15m/30m PRINT were descriptively strongest, but no duration was selected.
- Shorts were stronger in most variants; this does not authorize a side filter.
- Every variant had a negative rolling-50 window; seven ended negative on
  rolling-50 and only the 5m variants ended negative on rolling-100.
- DEV has 13 months and roughly 225-247 trades per historical variant;
  optimization capacity is limited.
- Decision: optimize PRINT only; keep CLOSE as historical benchmark.

## Current handoff

Gate 5C 20m PRINT is implemented and the 60-test behavior suite passes. Manually
verify representative 20m viewer sessions before Gate 6A. No sweep has run.

Gate 6A is exactly:

- DEVELOPMENT only; PRINT only.
- OR: 5, 10, 15, 20, 30 minutes.
- Stop fraction: 0.25 and 0.50.
  - Long = `OR_high - fraction * OR_width`.
  - Short = `OR_low + fraction * OR_width`.
- Target R: 1.0, 1.5, 2.0, 2.5, 3.0.
- Exactly 50 unique configurations.
- No signal change, CLOSE optimization, indicators, filters, BE, trailing,
  fixed-point targets, partial exits, walk-forward, or reserved-period access.

All five 50%-stop/2R controls must exactly reproduce DEV baselines before other
cells are interpreted. Produce response surfaces; do not auto-select a winner.

## Housekeeping verification

- Preserve all pre-existing uncommitted Gate 5C work.
- Make no strategy/execution logic changes.
- Keep validated source/data paths working unless explicitly reconciled.
- All 60 pre-housekeeping tests must pass afterward.
- `git diff --check` must be clean.
- Remote must match the Quantitative Trading Research Lab repository.
