# VectorBT ORB Research Lab

A reproducible quantitative-research project for validating and analyzing an
Opening Range Breakout (ORB) strategy on MNQ one-minute NinjaTrader data. The
repository keeps strategy construction, execution simulation, analytics, and
research artifacts separate so each gate can be validated before the next one.

## Current validated state

Gates 1 through 4D are frozen and validated:

- NinjaTrader timestamps are interpreted as one-minute **bar-end times**.
- Opening ranges are available for 5, 10, 15, and 30 minutes from 09:30 ET.
- PRINT and CLOSE breakout signals retain the first long and first short signal
  per session through the inclusive 11:30 ET cutoff.
- PRINT entries occur at the breached OR boundary on the signal bar; existing
  same-bar ambiguity handling is preserved.
- CLOSE entries occur at the immediately following bar's open. The signal bar
  is never treated as an executable bar.
- Initial stop is the OR midpoint and initial target is 2R. Calculated prices
  are rounded to the MNQ 0.25-point tick.
- Exit simulation, SESSION_END behavior, MFE/MAE, and a maximum of one valid
  executed trade per session and variant are implemented.
- The canonical completed-trade table contains 4,073 full-history trades across
  the eight OR-duration/breakout variants.

Gate 5B DEVELOPMENT-only diagnostics are also implemented. They analyze 1,926
trades from 2024-06-21 through 2025-06-30 without inspecting reserved-period
performance.

## Research partitions

The formal boundaries are defined in `config/data_partitions.json`:

| Partition | Dates | Permitted use |
|---|---|---|
| DEVELOPMENT | 2024-06-21 to 2025-06-30 | Research and parameter development |
| VALIDATION | 2025-07-01 to 2025-12-31 | Reserved for a later validation gate |
| OOS_BURNED | 2026-01-01 to 2026-08-17 | Robustness/learning only; not untouched OOS evidence |

Do not inspect VALIDATION or OOS_BURNED performance while developing or
selecting parameters. Raw/processed market data and completed-trade CSVs remain
local and are intentionally excluded from Git.

## Project layout

```text
vectorbt-lab/
|-- config/                  # Research partition definitions
|-- data/
|   |-- raw/                 # Local source exports; never edit in place
|   `-- processed/           # Local derived features, trades, and audits
|-- experiments/
|   |-- baselines/           # Versioned baseline summary tables and charts
|   `-- runs/                # Local generated experiment runs
|-- notebooks/               # Executable research/viewer entry points
|-- src/
|   |-- backtesting/         # Candidate, execution, exit, and daily-limit logic
|   |-- data/                # Partition utilities
|   |-- experiments/         # Reproducible analytics
|   |-- features/            # Opening-range features
|   `-- visualization/       # Research Viewer
|-- strategies/              # Strategy notes/packages
|-- tests/                   # Repository test suite
|-- MEMORY.md                # Durable project state and research guardrails
`-- README.md
```

## Local data prerequisites

These local files are required by the relevant scripts but are intentionally
not committed:

```text
data/MNQ_raw_cleaned_ET.csv
data/processed/mnq_or_levels.csv
data/processed/orb_v01_completed_trades.csv
data/processed/orb_v01_candidate_audit.csv
```

The source data must retain `timestamp_et` as the NinjaTrader bar-end timestamp.

## Common commands

Run these from the repository root with the project's virtual environment:

```powershell
# Complete test suite
.\.venv\Scripts\python.exe -m pytest -q

# Interactive Research Viewer (http://127.0.0.1:8050)
.\.venv\Scripts\python.exe notebooks\03_orb_signal_visual.py

# Rebuild the canonical Gate 4D completed trades and candidate audit
.\.venv\Scripts\python.exe notebooks\04_orb_v01_completed_trades.py

# Full-history baseline cross-check (historical artifact; not for selection)
.\.venv\Scripts\python.exe notebooks\05_orb_v01_vectorbt_baseline.py

# Gate 5B DEVELOPMENT-only diagnostics
.\.venv\Scripts\python.exe notebooks\06_orb_v01_development_diagnostics.py
```

VectorBT is used for generic analytics cross-checks and interactive
visualization. The validated completed-trade table remains the source of truth;
`Portfolio.from_signals()` is not used to reconstruct execution.

## Gate 5B outputs

Versioned DEVELOPMENT-only outputs live under `experiments/baselines/` and use
the `orb_v01_DEV_` prefix. They include baseline and monthly summaries,
cumulative-R equity curves, rolling expectancy, R-distribution statistics,
month-consistency statistics, and interactive HTML charts.

## Research workflow

1. Keep validated upstream layers frozen while working on a new gate.
2. Make the DEVELOPMENT boundary an executable assertion, not just a convention.
3. Reproduce the existing baseline exactly before testing any parameter change.
4. Save generated results with an explicit scope such as `DEV` in the filename.
5. Run the complete test suite before committing a gate.
6. Do not select a preferred variant from reserved-period results.

The next proposed milestone is a narrow DEVELOPMENT-only Gate 6 parameter sweep.
It has not been implemented.
