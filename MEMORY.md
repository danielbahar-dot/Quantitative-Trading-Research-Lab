# Project Memory

This is the durable handoff for the repository's validated state. Update it only
when a research gate has been implemented and validated.

## Frozen strategy and execution semantics

- Instrument/data: MNQ one-minute NinjaTrader bars in Eastern Time.
- `timestamp_et = bar_end_time`; a bar stamped 09:31 contains the minute that
  began at approximately 09:30.
- OR windows use bar-end stamps 09:31-09:35 (5m), 09:31-09:40 (10m),
  09:31-09:45 (15m), and 09:31-10:00 (30m).
- First eligible bars are 09:36, 09:41, 09:46, and 10:01 respectively.
- Signal cutoff is inclusive at 11:30 ET.
- Signal generation retains at most the first long and first short per session.
- PRINT entry: OR boundary on the signal bar. PRINT ambiguity remains excluded
  according to the validated same-bar rules.
- CLOSE entry: open of the immediately following one-minute bar. Signal-bar
  high/low never participates in execution or stop/target ambiguity.
- Stop: OR midpoint. Target: 2R. Tick size: 0.25 points.
- A candidate whose entry is not beyond its stop is explicitly invalid.
- Gate 4D executes the earliest valid candidate only, maximum one trade per
  session for each OR-duration/breakout variant. A rejected later candidate is
  retained with `SESSION_TRADE_LIMIT`. An invalid or ambiguous candidate does
  not consume the allowance.
- Exit simulation, SESSION_END exits, holding time, MFE, and MAE are validated.

Do not change these rules during analytics or parameter-sweep work without a
new, explicitly approved research gate.

## Canonical local artifacts

- Clean data: `data/MNQ_raw_cleaned_ET.csv`
- OR levels: `data/processed/mnq_or_levels.csv`
- Completed trades: `data/processed/orb_v01_completed_trades.csv`
- Candidate audit: `data/processed/orb_v01_candidate_audit.csv`
- Partition definition: `config/data_partitions.json`

The completed-trade table has 4,073 trades across 5/10/15/30-minute PRINT and
CLOSE variants. Market data, generated feature tables, completed trades, and
candidate audits stay local and are ignored by Git.

## Research isolation

- DEVELOPMENT: 2024-06-21 through 2025-06-30.
- VALIDATION: 2025-07-01 through 2025-12-31. Do not inspect during development.
- OOS_BURNED: 2026-01-01 through 2026-08-17. Full-history results were viewed
  before partitioning, so this is not untouched final OOS evidence.
- Gate 5B is DEVELOPMENT-only. It analyzed 1,926 trades and its maximum analyzed
  session date is 2025-06-30.

## Gate 5B interpretation

- All eight DEVELOPMENT variants had positive average R, but the medians were
  -1R; performance depends on the +2R winners offsetting frequent full losses.
- Profit factors ranged approximately from 1.08 to 1.37.
- The 15m and 30m PRINT variants showed the strongest descriptive DEVELOPMENT
  results, but no winning variant has been selected.
- Short-side results were stronger in most variants; the 5m CLOSE long subset
  was negative. This is diagnostic evidence, not authorization for a side filter.
- Every variant experienced a negative rolling 50-trade expectancy window.
  Seven of eight ended with a negative rolling-50 value, while only the two
  5-minute variants ended with negative rolling-100 expectancy. This suggests
  meaningful regime sensitivity and argues against choosing a single maximum.
- The DEVELOPMENT sample contains 13 calendar months and roughly 225-247 trades
  per variant, so optimization capacity is limited.

## Next proposed gate

Freeze this Gate 5B state before Gate 6. If approved, begin with a narrow
DEVELOPMENT-only target-distance sweep while preserving the OR-midpoint stop and
all validated execution semantics. A reasonable first grid is 1.0R, 1.5R, 2.0R,
2.5R, and 3.0R for all eight variants.

Before evaluating alternatives, the parameterized simulator must reproduce the
2R Gate 5B baseline exactly. Prefer stable parameter regions and robustness over
the single highest result. Use pandas/NumPy for canonical statistics and
VectorBT for generic cross-checks and visualization; do not use
`Portfolio.from_signals()` to reconstruct the custom execution model.

Do not analyze VALIDATION or OOS_BURNED, run a multidimensional sweep, add new
indicators, or select a preferred variant until a later gate explicitly permits
it.
