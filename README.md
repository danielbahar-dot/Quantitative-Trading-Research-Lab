# VectorBT Research Harness v1

A small, transparent experiment ledger for ORB and momentum backtests. It uses
Python's standard library only: SQLite is the durable ledger, while a CSV mirror
keeps every run easy to inspect in Excel or a text editor.

## Project layout

```text
vectorbt-lab/
|-- data/
|   |-- raw/                 # Original NinjaTrader exports (never edit in place)
|   `-- processed/           # Cleaned/session-normalized datasets
|-- experiments/
|   |-- experiment_ledger.sqlite
|   |-- ledger.csv
|   |-- run_config.template.json
|   |-- schema.sql
|   `-- runs/<run_id>/       # Config snapshots and backtest artifacts
|-- notebooks/               # Research and validation scripts
|-- src/
|   |-- data/                # Data ingestion, validation, and cleaning
|   |-- features/            # Reusable feature engineering
|   |-- strategies/          # Strategy definitions
|   |-- backtesting/         # VectorBT engines and helpers
|   |-- experiments/         # Experiment orchestration
|   |-- visualization/       # Charts and NT8 export preparation
|   `-- research_harness.py  # Existing experiment ledger
|-- nt8/                     # NinjaTrader validation/display integration
|-- strategies/              # Existing strategy package (preserved)
|-- reports/
`-- tests/
```

## First run

From the `vectorbt-lab` directory:

```powershell
python src/research_harness.py init
Copy-Item experiments/run_config.template.json experiments/orb_trial.json
```

Edit `experiments/orb_trial.json` so it describes the exact hypothesis, data,
session rules, parameters, trading costs, and planned outputs. Then register it:

```powershell
python src/research_harness.py create --config experiments/orb_trial.json
```

The command prints a unique `run_id` and its artifact folder. Use that folder for
the VectorBT results from that run. When the backtest finishes, update the run:

```powershell
python src/research_harness.py update `
  --run-id ORB_20260817T120000000000Z_a1b2c3d4 `
  --results-json '{"total_return_pct": 8.4, "profit_factor": 1.37, "trades": 62}' `
  --notes "First pass; inspect performance by month." `
  --artifact trades=experiments/runs/ORB_.../trades.parquet `
  --artifact equity=experiments/runs/ORB_.../equity.parquet
```

`--results-json` may be inline JSON or the path to a JSON file. Repeat
`--artifact key=path` for each output. To inspect one run:

```powershell
python src/research_harness.py show --run-id ORB_...
```

## Using it from a backtest

```python
from pathlib import Path
from src.research_harness import ExperimentLedger

root = Path(__file__).resolve().parents[1]
ledger = ExperimentLedger(root)

run_id, run_dir = ledger.create_run("experiments/orb_trial.json")

# Run VectorBT here and save outputs beneath run_dir.

ledger.update_run(
    run_id,
    results_summary={"total_return_pct": 8.4, "profit_factor": 1.37},
    notes="Initial ORB baseline.",
    artifact_paths={"trades": run_dir / "trades.parquet"},
)
```

## Recommended workflow

1. Put untouched NT8 CSV exports in `data/raw/`.
2. Save cleaned, timezone-aware, session-normalized data in `data/processed/`.
3. Copy the config template and state one falsifiable hypothesis per run.
4. Register the run before calculating results; never reuse a `run_id`.
5. Save trades, equity, statistics, and charts inside that run's folder.
6. Update the ledger with the final summary and honest notes, including failures.
7. Compare runs in `experiments/ledger.csv`, but treat SQLite as authoritative.

The harness automatically records a UTC timestamp, the current Git commit when
available, and a SHA-256 hash of Python files under `src/` and `strategies/`.
This makes results reproducible without introducing MLflow or another service.

