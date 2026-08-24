# Quantitative Trading Research Lab

A reproducible platform for discovering, developing, validating, and comparing
systematic trading strategies across instruments, universes, asset classes, and
timeframes.

The intended scope includes futures, equities, ETFs, and future asset classes
that satisfy the platform's data and execution contracts. MNQ Opening Range
Breakout (ORB) V0.1 is the first validated reference project; it is not the
scope or identity of the platform.

This repository is a research environment, not a live-trading system or a claim
of future profitability.

## Current status

- Platform foundations: data partitions, a custom execution pipeline,
  experiment tracking, analytics, tests, and an interactive research viewer.
- Reference project: `mnq_orb_v0_1`.
- Frozen reference baseline: 5/10/15/30-minute PRINT and CLOSE variants with
  4,073 completed full-history trades.
- Gate 5B: DEVELOPMENT-only diagnostics for the eight historical variants,
  covering 1,926 trades.
- Gate 5C: 20-minute PRINT is implemented as a DEVELOPMENT-only supplement.
  The expanded DEVELOPMENT comparison contains 2,172 trades.
- Gate 6A: the DEVELOPMENT-only 40-cell PRINT static-stop x R-target sweep has
  run and all four midpoint/2R controls reproduced the validated baselines.
  Results await manual interpretation; no configuration has been selected.
- Gate 6A.1: the separate DEVELOPMENT-only 25%-stop entry-bar ambiguity
  sensitivity has run across 20 configurations and three chronology scenarios.
  Gate 6A artifacts remained byte-for-byte unchanged.
- Gate 6B: the DEVELOPMENT-only 75-cell fixed-point target x stop study has run
  for 15m/20m/30m PRINT. OR-width diagnostics are preserved for Gate 6B.1;
  no parameter combination or OR-width rule has been selected.
- Gate 6B.1: OR width has been mapped as a DEVELOPMENT-only diagnostic using
  duration-specific quintiles. It remains a candidate state variable, not a
  strategy filter.
- Gate 6B.2: all 75 Gate 6B cells have been tested under EXCLUDED, ENTRY_FIRST,
  and ADVERSE_MOVE_FIRST entry-bar chronology conventions.
- Gate 6C: human review approved three distinct candidates. The DEVELOPMENT
  package is frozen for Validation; HYP_001/HYP_002 remain research history and
  are excluded. Gate 7's decision protocol is predeclared and locked before
  reserved-period execution.
- Gate 7: confirmatory VALIDATION is complete for exactly the three frozen
  candidates. CAND_001 is `REVISE`; CAND_002 and CAND_003 are `REJECT`. No
  Validation retuning or OOS_BURNED access occurred; the next action requires
  human review.

The authoritative handoff and research guardrails are in [MEMORY.md](MEMORY.md).
Run history belongs in the experiment ledger, not in MEMORY.

## Platform model

The lab treats four concepts as independent:

1. **Strategy family** — reusable market logic such as ORB, momentum, mean
   reversion, trend following, or relative value.
2. **Instrument or universe** — a contract, security, ETF, continuous series,
   or explicitly versioned symbol collection.
3. **Dataset snapshot** — immutable source/cleaned data with timestamp,
   session, adjustment, and provenance semantics.
4. **Experiment** — one reproducible hypothesis test using a frozen strategy
   version, instrument/universe, dataset, partition, parameters, execution
   model, costs, and code version.

```text
Experiment
= Strategy specification
x Instrument or universe specification
x Dataset snapshot
x Research partition
x Parameter set
x Execution and cost model
x Code/environment version
```

A research **project** may bind those objects for a line of work, as
`mnq_orb_v0_1` does, without turning that binding into a platform-wide rule.
Avoid permanently isolated implementations such as `MNQ_ORB_strategy` and
`SPY_momentum_strategy` when a reusable strategy and separate instrument
configuration express the distinction.

## Research architecture

```text
Raw Data
   ↓
Validated / Clean Data
   ↓
Features
   ↓
State Variables
   ↓
Signals
   ↓
Strategy Definition
   ↓
Execution Engine
   ↓
Completed Trades
   ↓
Experiment Engine
   ↓
Analytics / VectorBT
   ↓
Experiment Ledger
   ↓
Research Dashboard
```

Each layer must be inspectable and testable. Downstream analytics must not
rewrite upstream signals, entries, exits, exclusions, or partition membership.

- **Features** describe measurable market information without deciding whether
  to trade.
- **State variables** are derived states available at the decision timestamp;
  their construction must be causal and reproducible.
- **Signals** record market events or conditions and remain auditable even when
  no trade is accepted.
- **Strategy rules** decide whether and how eligible signals become candidate
  trades.
- **Execution semantics** determine fills, stops, targets, session state, and
  ambiguity independently from signal generation.

### Strategy and instrument separation

A strategy specification owns feature requirements, signal/eligibility rules,
parameter domains, entry/exit/sizing rules, ambiguity policy, data constraints,
version, and validation status.

An instrument or universe specification owns its stable ID, asset class,
exchange, symbol/contract semantics, tick/multiplier/currency facts, calendar,
session, timezone, adjustment or futures-roll policy, and data-quality
expectations.

An experiment combines the two. Instrument facts must not become general
strategy facts, and ORB-specific behavior must not leak into platform-wide
execution or analytics APIs.

## Data architecture

| Layer | Purpose | Mutation rule |
|---|---|---|
| `raw` | Vendor/broker exports exactly as received | Immutable; never edit in place |
| `cleaned` | Canonical timestamps, columns, sessions, and corrections | Rebuild from raw with a versioned transform |
| `processed` | Features, signals, candidates, trades, audits, partitions | Derived and reproducible |
| `experiments` | Configs, summaries, charts, logs, and decisions | Scoped to a run/project and partition |

Every dataset used by an experiment should have a stable `dataset_id` plus its
source, instrument/universe, timeframe, timezone, timestamp meaning, calendar,
adjustment/roll method, date range, row count, schema/quality report, and content
hash.

Current MNQ files predate the final directory convention and remain at their
validated paths to avoid breaking the reference pipeline. New datasets should
use asset-class/instrument subdirectories. Migrate existing large/local data
only through a dedicated gate with hashes and row-level reconciliation.

## Experiment object and ledger

Every material run starts from a saved configuration and ends with one ledger
record. A complete object contains:

```json
{
  "experiment_id": "orb_gate6a_dev_print_static_r",
  "project_id": "mnq_orb_v0_1",
  "strategy_family": "ORB",
  "strategy_version": "0.1.0",
  "asset_class": "futures",
  "instrument_id": "MNQ",
  "universe_id": null,
  "dataset_id": "MNQ_1m_actual_contract_v1",
  "dataset_path": "data/MNQ_raw_cleaned_ET.csv",
  "dataset_hash": "<sha256>",
  "partition": "DEVELOPMENT",
  "timeframe": "1 minute",
  "hypothesis": "<falsifiable statement>",
  "parameters": {},
  "execution_model": {},
  "costs_slippage": {},
  "code_version": "<git commit>",
  "code_hash": "<source hash>",
  "environment": {},
  "status": "PLANNED|RUNNING|COMPLETED|REJECTED|INVALIDATED",
  "results_summary": {},
  "artifact_paths": {},
  "conclusion": "<decision tied to the hypothesis>",
  "notes": "<limitations and anomalies>"
}
```

Stable IDs identify reusable objects; `run_id` identifies one execution. A
rerun creates a new record instead of overwriting history. The local SQLite
ledger is the operational store and `experiments/ledger.csv` its readable
mirror. Generated ledgers and run folders remain local; reviewed compact
summaries may be committed under the project artifact directory.

## Partition methodology

Every project defines partitions before inspecting results. Assign membership
from the strategy decision/session date, not opportunistically from entry or
exit timestamps.

- **DEVELOPMENT:** features, diagnostics, parameter exploration, debugging, and
  robustness analysis. Iteration is expected but still requires hypotheses and
  capacity discipline.
- **VALIDATION:** hidden until candidate and acceptance criteria are frozen.
  It is not a second optimization set. Record a failure before defining a new
  research cycle.
- **OOS:** one final frozen evaluation. If it influenced design or selection,
  relabel it (for example `OOS_BURNED`) and never call it untouched evidence.

Walk-forward folds must preserve these temporal roles and record purge/embargo
rules where applicable.

The current executable MNQ definition is
`config/datasets/mnq_1m_actual_contract_v1.partitions.json`.

| Partition | Inclusive sessions | Permitted use |
|---|---|---|
| DEVELOPMENT | 2024-06-21 to 2025-06-30 | Current research and parameter development |
| VALIDATION | 2025-07-01 to 2025-12-31 | Reserved for an explicitly approved gate |
| OOS_BURNED | 2026-01-01 to 2026-08-17 | Supporting learning only; not untouched evidence |

Do not use VALIDATION or OOS_BURNED for DEVELOPMENT parameter selection.

## Reusable research lifecycle

1. **Data preparation** — record provenance, clean deterministically, validate
   timestamps/sessions, and version the dataset.
2. **Partition before research** — predeclare DEVELOPMENT, VALIDATION, and OOS.
3. **Signal validation** — prove no lookahead and perform visual/manual checks
   where bar semantics or event timing require them.
4. **Execution validation** — validate entries, stops, targets, session rules,
   shortened sessions, trade limits, and ambiguity handling.
5. **DEVELOPMENT research** — baseline diagnostics, response surfaces,
   robustness analysis, and causal feature discovery.
6. **DEVELOPMENT freeze** — predeclare a small candidate set and acceptance
   criteria before opening reserved data.
7. **VALIDATION** — evaluate only frozen candidates; never rerun broad
   optimization on Validation.
8. **Strategy decision** — record `PASS`, `REVISE`, or `REJECT`.
9. **Strategy specification** — for an accepted strategy, freeze a
   machine-readable strategy version and execution contract.
10. **OOS** — perform one final frozen evaluation on untouched data.

The MNQ ORB final partition is labeled `OOS_BURNED` because full-history results
were viewed before formal partitioning. It remains useful for testing the
platform workflow, but it is not pristine statistical evidence.

## Execution engine and VectorBT

> Use VectorBT execution when its assumptions faithfully match the strategy.
> Use custom execution when session rules, intrabar ordering, order semantics,
> or ambiguity require greater control.

The custom engine is authoritative when behavior depends on intrabar order,
entry-bar eligibility, next-bar fills, session cutoffs, forced exits, stateful
trade limits, or ambiguity/exclusion rules.

Use VectorBT where vectorized behavior is faithful and for generic aggregation,
drawdown cross-checks, parameter arrays, and visualization. Do not replace the
validated ORB simulator with `Portfolio.from_signals()` unless a gate proves
trade-level equivalence. Completed trades and candidate audits are canonical;
equity curves and summaries are derived. For MNQ ORB, the custom engine is the
source of truth; VectorBT, pandas, and NumPy support analytics, cross-checks,
parameter research, and visualization rather than defining the platform.

## Research gates

A gate states its hypothesis, allowed partition, frozen upstream behavior,
exact parameter space, outputs, acceptance criteria, tests, manual checks,
conclusion, and next permitted action.

```text
data contract
-> feature validation
-> signal validation
-> candidate/execution validation
-> baseline analytics
-> DEVELOPMENT diagnostics
-> controlled parameter study
-> candidate freeze
-> VALIDATION
-> final specification
-> OOS evaluation
```

No later gate may silently reinterpret a frozen gate.

## Artifact conventions

Prefer:

```text
experiments/projects/<project_id>/<artifact_class>/
<project-or-strategy>_<gate-or-experiment>_<partition>_<artifact>.<ext>
```

The file or adjacent metadata should identify project, experiment/run, strategy
version, dataset ID/hash, partition, parameters, code version, creation time,
and whether it is canonical, diagnostic, or superseded. Never overwrite a
frozen baseline or use unscoped durable names such as `results.csv`.

## Repository layout

```text
Quantitative-Trading-Research-Lab/
|-- config/
|   |-- datasets/           # Dataset partitions/provenance
|   |-- experiments/        # Approved or planned experiment grids
|   `-- instruments/        # Instrument/universe metadata
|-- data/
|   |-- raw/                # Immutable local sources
|   |-- cleaned/            # Canonical local data for new datasets
|   `-- processed/          # Local features, trades, and audits
|-- experiments/
|   |-- projects/           # Reviewed artifacts by project
|   |-- runs/               # Local run snapshots/large artifacts
|   |-- schema/             # Ledger schema
|   `-- templates/          # Experiment config templates
|-- notebooks/              # Existing executable research entry points
|-- reports/                # Curated cross-project reports
|-- src/
|   |-- backtesting/        # Candidate/execution/state machinery
|   |-- data/               # Data and partition utilities
|   |-- experiments/        # Reproducible analytics
|   |-- features/           # Reusable features
|   |-- strategies/         # Strategy-family implementations as they mature
|   `-- visualization/      # Viewer/dashboard components
|-- strategies/             # Human-readable strategy specifications
|-- tests/
|-- MEMORY.md
|-- requirements.txt
|-- requirements-dev.txt
`-- README.md
```

Source modules retain their current import paths during this housekeeping gate.
Moving ORB code deeper before a second strategy exists would create import churn
without research benefit. New strategy logic should use
`src/strategies/<family>/`; keep generic execution/data machinery separate.

## Reusable platform libraries

| Layer | Status | Direction |
|---|---|---|
| Data Library | Partially implemented | Generalize provenance, validation, partitions, and dataset registries across asset classes |
| Feature Library | Partially implemented | Promote causal reusable features and state-variable contracts beyond ORB |
| Signal Library | Partially implemented | Preserve strategy-independent event records and validation tooling |
| Execution Library | Implemented for validated ORB semantics; reusable core partial | Extend explicit fill, session, ambiguity, and cost models without weakening auditability |
| Strategy Library | Partially implemented | Add versioned strategy-family specifications and reusable composition |
| Experiment Engine | Partially implemented | Standardize configs, deterministic runs, parameter surfaces, and robustness gates |
| Experiment Ledger | Partially implemented | Make the ledger the authoritative searchable history of individual experiments |
| Research Dashboard | Planned | Build a cross-project artifact/ledger browser without changing research results |

These labels describe the current repository honestly; planned layers are not
claimed as completed platform capabilities.

## Reference project: MNQ ORB V0.1

### Frozen timing

- MNQ one-minute NinjaTrader OHLC bars in Eastern Time.
- `timestamp_et` is bar-end time; 09:31 contains the minute beginning around
  09:30.
- OR windows: 09:31-09:35 (5m), 09:31-09:40 (10m), 09:31-09:45
  (15m), 09:31-09:50 (20m), and 09:31-10:00 (30m).
- First eligible bars: 09:36, 09:41, 09:46, 09:51, and 10:01.
- Signal cutoff is inclusive at 11:30 ET.

### Frozen signals and execution

- Historical baseline: 5/10/15/30m PRINT and CLOSE.
- Current Gate 6 research path: 15/20/30m PRINT. Earlier 5m/10m and CLOSE
  results remain historical benchmarks and are not part of the current surface.
- Retain at most the first long and first short signal per session.
- PRINT enters at the breached OR boundary on the signal bar with validated
  conservative same-bar ambiguity rules.
- CLOSE enters at the immediately following bar's open. Its signal bar is never
  executable and cannot create stop/target ambiguity.
- Baseline stop is the OR midpoint; target is 2R; tick size is 0.25 points.
- A candidate whose entry is not beyond its stop is invalid.
- Execute the earliest valid candidate, maximum one trade/session per
  OR-duration/breakout variant. Invalid/ambiguous candidates do not consume the
  allowance; rejected later candidates remain audited.
- SESSION_END, shortened sessions, holding time, MFE, and MAE are validated.
- No BE, trailing, FVG, EMA, VWAP, partial exits, commissions, or slippage.

### Canonical local data

```text
data/MNQ_raw_cleaned_ET.csv
data/processed/mnq_or_levels.csv
data/processed/orb_v01_completed_trades.csv
data/processed/orb_v01_candidate_audit.csv
data/processed/orb_v01_20m_print_DEV_completed_trades.csv
data/processed/orb_v01_20m_print_DEV_candidate_audit.csv
```

These remain ignored by Git. The historical completed-trade table is unchanged;
20m PRINT is a DEVELOPMENT-only supplement.

### Gate 6A DEVELOPMENT response surface

```text
4 OR durations x 2 static stops x 5 R targets = 40 configurations
```

- OR: 10, 15, 20, 30 minutes. The 5-minute duration was intentionally excluded.
- Breakout: PRINT only.
- Stop retracement: 25% or 50% from the breached boundary.
  - Long: `OR_high - stop_fraction * OR_width`.
  - Short: `OR_low + stop_fraction * OR_width`.
  - 50% is the existing midpoint control.
- Target: 1R, 1.5R, 2R, 2.5R, 3R from each trade's initial risk.

All four midpoint/2R control cells exactly reproduce DEVELOPMENT baselines.
The canonical 40-row table, trade/candidate audit tables, metadata, and five
interactive heatmaps are under `experiments/projects/mnq_orb_v0_1/sweeps/`.
No winner is selected; interpret broad stable regions rather than isolated maxima.

## Setup and commands

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q

# Standard-library fallback when pytest is unavailable
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

.\.venv\Scripts\python.exe notebooks\02_orb_features.py
.\.venv\Scripts\python.exe notebooks\03_orb_signal_visual.py
.\.venv\Scripts\python.exe notebooks\04_orb_v01_completed_trades.py
.\.venv\Scripts\python.exe notebooks\05_orb_v01_vectorbt_baseline.py
.\.venv\Scripts\python.exe notebooks\06_orb_v01_development_diagnostics.py
.\.venv\Scripts\python.exe notebooks\07_orb_v01_20m_print_development.py
.\.venv\Scripts\python.exe notebooks\08_orb_gate6a_development_sweep.py
.\.venv\Scripts\python.exe notebooks\09_orb_gate6a1_ambiguity_sensitivity.py
.\.venv\Scripts\python.exe notebooks\10_orb_gate6b_fixed_target_stop.py
.\.venv\Scripts\python.exe notebooks\11_orb_gate6b1_or_width_analysis.py
.\.venv\Scripts\python.exe notebooks\12_orb_gate6b2_ambiguity_robustness.py
.\.venv\Scripts\python.exe notebooks\13_orb_gate6c_candidate_reduction.py
.\.venv\Scripts\python.exe notebooks\14_finalize_orb_v01_development_freeze.py
.\.venv\Scripts\python.exe notebooks\15_orb_gate7_validation.py
```

The full-history baseline command is a historical cross-check, never a source
for parameter selection.

## Testing guardrails

- Assert timestamp/session semantics at data boundaries.
- Test exact OR membership and first eligible bars for every duration.
- Test long/short stop and target formulas independently.
- Test invalid, missing-bar, ambiguous, shortened-session, and SESSION_END paths.
- Preserve candidate/completed-trade auditability and one-trade/session rules.
- Assert partition exclusivity, coverage, and maximum analyzed date.
- Hash/reconcile source data when partitioning or migrating paths.
- Reproduce frozen controls before accepting a parameterized engine.
- Run the full suite before and after structural changes.
- Manually inspect viewer timing/execution changes even when tests pass.

## Visualization direction

The current viewer audits bars, OR shading, signals, candidates, stops/targets,
and exits. A future cross-project dashboard should read ledger/artifact metadata
and filter by project, strategy, instrument/universe, dataset, partition,
parameters, and code version. It should emphasize drawdown/equity paths,
rolling expectancy, distributions, monthly/regime behavior, parameter surfaces,
and trade audits, while clearly labeling DEVELOPMENT, VALIDATION, OOS, and
burned evidence. It must never silently combine incompatible experiments.

## Documentation ownership

- `README.md`: platform architecture, usage, methodology, and reference project.
- `MEMORY.md`: concise durable decisions, validated state, and handoff.
- Ledger/config/artifacts: experiment history, parameters, metrics, evidence,
  and conclusions.
- Git: implementation history.

No `PROJECT_STATUS.md` is maintained because it would duplicate MEMORY. Add a
`CHANGELOG.md` only when releases or external users need curated history beyond
Git and the experiment ledger.
