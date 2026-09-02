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
- Gate 8A: the full frozen 75-cell surface has been replayed on VALIDATION for
  retrospective failure diagnosis only. The outputs compare DEVELOPMENT with
  VALIDATION, create no new candidate, and leave OOS_BURNED unopened.
- Research Dashboard V0.1: a read-only Streamlit experiment ledger and artifact
  explorer indexes the reviewed MNQ ORB lifecycle without changing research
  results or duplicating canonical artifacts.
- Research Lifecycle V1.0: the platform now has a strategy-independent 12-stage
  evidence lifecycle, V1.0 experiment-package schema, and reusable component
  registry. MNQ ORB V0.1 is mapped as a 19-record reference history rather than
  used as the architectural definition.
- Research Infrastructure V1.0: future experiment runners can create records,
  register canonical artifacts, preserve failures, finalize metadata, and
  refresh the existing dashboard index programmatically.
- MNQ ORB V0.2 Stage 2 freeze: Asia 20:00-00:00, London 02:00-05:00,
  and New York pre-market 07:00-09:00 ET definitions are human-validated.
  The completion evidence adds full previous-trading-day levels, a distinct
  NY-open gap, 5/10/15/20-session causal width history, signal-bar descriptive
  excursion, missing-data diagnosis, and expanded viewer validation support.
  All 14 representative reviews passed on 2026-09-02. The final review queue
  stores an exact machine-stable `trigger_id`, and multi-predicate review cases
  must reconcile on that same reference level. Stage-2 features are frozen;
  no V0.2 strategy rule or performance result exists.

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
- **Experiments** test a declared hypothesis at one canonical lifecycle stage
  using explicit data, partition, configuration, code, and evidence lineage.

Features measure; state variables describe current conditions; signals identify
events; strategies combine components with eligibility, execution, and risk
rules; experiments test those versioned definitions. The reusable component
contract is defined in `experiments/schema/research_component.schema.json` and
the first reference components are registered in
`config/components/research_components.json`.

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

### Feature causality and normalization

Every reusable feature records its calculation window, Eastern Time
availability, warm-up, causal status, source columns, normalization, and
missing-data behavior. NinjaTrader one-minute timestamps are bar-end labels;
for example, the conceptual 07:00-09:00 New York pre-market window uses bars
stamped 07:01 through 09:00. In this project, `NY PM` means **New York
pre-market**, never the afternoon session.

Price-normalized values are stored as decimal ratios (`0.0035 = 0.35%`) while
raw point values remain separate. Window and session ranges use the relevant
window open as their reference price, OR values use OR open, and signed
key-level distances use OR midpoint. Denominators are never silently mixed.

Causal OR-width percentiles use only prior valid sessions of the same OR
duration. The 5/10/15/20-session alternatives use deterministic midrank empirical
percentiles, remain null until their full warm-up exists, and are feature
lookbacks rather than selected strategy parameters.

For V0.2, the primary generic prior-day key levels are the high, low, and close
of the complete prior futures trading day (18:01 prior-calendar-day through
17:00 trading-date bar ends). Previous RTH references remain optional. The
20:00-09:00 continuous range is named `OVERNIGHT_CONTEXT_2000_0900`;
`combined_preopen` is retained only as migration metadata. `GLOBEX_REOPEN_GAP`
uses the prior 17:00 close and 18:01 reopen, while `NY_OPEN_GAP` uses the prior
16:14 bar close and current 09:31 bar open (the 09:30 market open).

Launch the DEVELOPMENT-only validation viewer with:

```powershell
.\.venv\Scripts\python.exe -m streamlit run notebooks\19_mnq_orb_v02_feature_viewer.py
```

The viewer provides selectable presets, independent X/Y navigation, an
interactive legend, prior-session context, end times through 16:00, and a
strategy-neutral key-level classification panel.

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
  "strategy_id": "opening_range_breakout",
  "strategy_version": "V0.1",
  "research_stage": "STAGE_6_EXPLORATION",
  "gate": "6A",
  "hypothesis": "<falsifiable statement>",
  "scope": {"instrument_id": "MNQ", "asset_class": "futures", "timeframe": "1 minute", "partition": "DEVELOPMENT"},
  "lineage": {"parent_experiment_ids": [], "source_gates": []},
  "reproducibility": {"dataset_id": "MNQ_1m_actual_contract_v1", "data_hash": "<sha256>", "config_path": "<path>", "git_sha": "<commit>", "run_timestamp": "<UTC time>"},
  "data_references": [],
  "configuration": {"path": "<path>", "parameters": {}},
  "status": "planned|running|complete|failed",
  "decision": "continue|freeze|pass|revise|reject|diagnostic|none",
  "confirmatory": false,
  "reserved_data_exposed": false,
  "summary_metrics": {},
  "artifacts": [],
  "known_limitations": [],
  "notes": null
}
```

Stable IDs identify reusable objects; `run_id` identifies one execution. A
rerun creates a new record instead of overwriting history. The local SQLite
ledger is the operational store and `experiments/ledger.csv` its readable
mirror. Generated ledgers and run folders remain local; reviewed compact
summaries may be committed under the project artifact directory. Reviewed
project indexes at `experiments/projects/<project_id>/experiment_index.json`
provide the portable dashboard catalog and preserve explicit unknown values for
historical experiments that predate the final run-ledger contract.
The reviewed package standard is V1.0 and is documented in
`experiments/README.md`; project-specific gates never replace the canonical
`research_stage`.

### Automatic Experiment Registration

New experiment runners use the strategy-independent API in
`src/experiments/experiment_registration.py`:

```text
create experiment -> write canonical artifacts -> register artifacts
-> update metrics/notes -> finalize -> refresh experiment_index.json
-> dashboard discovers the run
```

`create_experiment()` records identity, lifecycle stage, lineage, partition
exposure, configuration, dataset references, Git state, and start time.
`register_artifact()` references the canonical file without copying it.
`update_experiment()` permits only declared mutable run metadata, while
identity and provenance remain protected. `finalize_experiment()` validates
required artifacts and atomically updates the existing project index. The
optional `ExperimentRun` context manager records failures and re-raises the
original exception.

The dashboard remains read-only: it discovers registered records but cannot
create, run, finalize, or edit experiments. Historical hand-written index
records remain supported as backfill; manual index editing is not the intended
workflow for future experiments. See
[`docs/AUTOMATIC_EXPERIMENT_REGISTRATION.md`](docs/AUTOMATIC_EXPERIMENT_REGISTRATION.md).

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

## Research Lifecycle V1.0

Research Lifecycle V1.0 is canonical across every strategy, instrument, and
asset class. Local gates may divide work more finely, but every experiment maps
to exactly one lifecycle stage.

| Stage | Name | Evidence objective |
|---:|---|---|
| 0 | Research Idea / Hypothesis | Declare mechanism, scope, data needs, bias risks, and falsification criteria before implementation. |
| 1 | Data Qualification | Qualify provenance, mappings, timestamps, sessions, quality, adjustments/rolls, biases, and partitions. |
| 2 | Feature Validation | Prove mathematical definition, causal timing, information availability, invariants, and representative observations. |
| 3 | Signal Validation | Verify the exact intended event, direction, eligibility, first executable time, edge cases, and signal audit before performance testing. |
| 4 | Execution Model Validation | Validate fills, timing, stops, targets, limits, tick rounding, costs, session behavior, chronology, and ambiguity separately from signals. |
| 5 | Development Baseline | Describe the simplest meaningful DEVELOPMENT baseline and its temporal/distribution behavior. |
| 6 | Development Exploration | Map response surfaces, interactions, boundaries, trade-offs, sample size, and observability without selecting a maximum cell. |
| 7 | Robustness / Sensitivity | Distinguish observed performance from robust evidence through perturbation, chronology, temporal, and state sensitivity. |
| 8 | Candidate Reduction & Freeze | Predeclare candidates and criteria; freeze configuration, code, data boundary, hash, and protocol before VALIDATION. |
| 9 | Confirmatory Validation | Run frozen candidates on VALIDATION without tuning and record `PASS`, `REVISE`, or `REJECT`. |
| 10 | Post-Validation Diagnosis | Explain Validation retrospectively without changing its decision or manufacturing confirmatory evidence. |
| 11 | Research Decision | Record `REJECTED`, `REVISE / NEW VERSION`, or `APPROVED FOR NEXT PHASE` and the next permitted action. |

The formal definition and stage evidence requirements are in
[`docs/RESEARCH_LIFECYCLE_V1.md`](docs/RESEARCH_LIFECYCLE_V1.md) and
`experiments/schema/research_lifecycle_v1.json`.

Signal validation is a hard prerequisite for performance testing. DEVELOPMENT
is the only exploration/tuning partition. A revision creates a new strategy
version and research cycle rather than silently changing a frozen candidate.
Post-validation diagnostics retain their retrospective label and never rewrite
the confirmatory decision.

### Future strategy lifecycle — reserved, not implemented

`APPROVED FOR NEXT PHASE` is not a live-trading authorization and is not the end
of a strategy's lifetime. A future lifecycle is reserved for implementation
verification, simulation/paper trading, deployment approval, live deployment,
monitoring, periodic review, revalidation, version migration, suspension, and
retirement. Detailed monitoring thresholds, broker connectivity, and live
operations are deliberately outside Research Lifecycle V1.0.

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
|   |-- components/         # Reusable feature/signal/state/strategy registry
|   |-- datasets/           # Dataset partitions/provenance
|   |-- experiments/        # Approved or planned experiment grids
|   `-- instruments/        # Instrument/universe metadata
|-- data/
|   |-- raw/                # Immutable local sources
|   |-- cleaned/            # Canonical local data for new datasets
|   `-- processed/          # Local features, trades, and audits
|-- experiments/
|   |-- README.md           # Experiment package and folder conventions
|   |-- projects/           # Reviewed artifacts by project
|   |-- runs/               # Local run snapshots/large artifacts
|   |-- schema/             # Ledger schema
|   `-- templates/          # Experiment config templates
|-- notebooks/              # Existing executable research entry points
|-- docs/                   # Canonical lifecycle and platform documents
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
| Experiment Ledger | Reviewed indexing and prospective automatic registration implemented; SQLite mirroring remains partial | Adopt the registration API in future experiment runners |
| Research Dashboard | V0.1 implemented | Extend the read-only cross-project explorer as new strategy families are registered |

These labels describe the current repository honestly; planned layers are not
claimed as completed platform capabilities.

## Reference project: MNQ ORB V0.1

MNQ ORB V0.1 is a completed reference research cycle and infrastructure test
case. Its project gates are preserved and mapped rather than renumbered:

| Canonical stage | MNQ ORB V0.1 evidence |
|---|---|
| 0 Idea | Historical ORB research specification |
| 1 Data | Gate 1 data qualification and partition contract |
| 2 Features | Gate 2 OR feature/timing validation |
| 3 Signals | Gate 3 PRINT/CLOSE signal validation and visual review tooling |
| 4 Execution | Gates 4A/4B candidates, 4C exits, and 4D one-trade/session completion |
| 5 DEV Baseline | Gates 5, 5B, and 5C |
| 6 Exploration | Gates 6A and 6B response surfaces |
| 7 Robustness | Gates 6A.1, 6B.1, and 6B.2 |
| 8 Freeze | Gate 6C |
| 9 Validation | Gate 7 |
| 10 Diagnosis | Gate 8A |
| 11 Decision | V0.1 `REVISE / NEW VERSION`; no OOS or production progression |

Historical manual-validation records link only to surviving source, tests,
notebooks, configurations, and local audits. They contain no manufactured
metrics or timestamps.

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
.\.venv\Scripts\python.exe notebooks\18_mnq_orb_v02_feature_validation.py

# Separate DEVELOPMENT-only feature-validation viewer
.\.venv\Scripts\python.exe -m streamlit run notebooks\19_mnq_orb_v02_feature_viewer.py

# Read-only experiment ledger and artifact explorer
.\.venv\Scripts\python.exe -m streamlit run notebooks\17_research_dashboard.py
```

The full-history baseline command is a historical cross-check, never a source
for parameter selection.

## Research Dashboard

Research Dashboard V0.1 is the read-only interface for navigating projects,
strategy versions, experiments, lineage, decisions, dataset provenance, and
their canonical artifacts. It is distinct from the Research Viewer:

- **Research Dashboard:** experiment ledger, charts, reports, metadata, bounded
  CSV previews, lineage, and compatible-metric comparison.
- **Research Viewer:** candle-level visual validation of OR ranges, signals,
  entries, stops, targets, and completed trades.

The dashboard loads reviewed experiment records through the reusable
`load_experiment_index()`, `get_experiment()`, and `list_artifacts()` APIs.
It also loads the canonical lifecycle and reusable component registry. The
overview shows complete/current/not-started lifecycle states; experiment tables
display canonical stages separately from project gates; strategy versions show
a chronological research history with direct output inspection; and the
partition view labels burned evidence without loading its performance.
Explicit metadata artifact declarations take priority; historical records may
use controlled project-relative discovery patterns. HTML charts can be embedded
on demand or opened from their canonical local path. CSV previews are bounded,
and large audit files are never preloaded at dashboard startup.

V0.1 cannot run experiments, edit parameters or strategies, mutate partitions,
delete artifacts, or perform Git actions.

## Current automation boundaries

The platform currently automates deterministic research calculations, artifact
generation, prospective experiment registration/finalization, reviewed-index
refresh, bounded previews, tests, and read-only navigation. Human authorization remains required for
candidate selection, partition opening, strategy decisions, new-version scope,
and progression beyond research. There is no experiment runner in the
dashboard, broker connection, live execution, deployment approval, strategy
monitoring, automatic revalidation, or retirement workflow.

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

The Research Viewer audits bars, OR shading, signals, candidates, stops/targets,
and exits. The Research Dashboard indexes cross-project experiment metadata and
artifacts while clearly labeling DEVELOPMENT, VALIDATION, OOS, and burned
evidence. Comparison is intentionally limited to matching metric keys; the UI
must never silently combine incompatible experiments.

## Documentation ownership

- `README.md`: platform architecture, usage, methodology, and reference project.
- `MEMORY.md`: concise durable decisions, validated state, and handoff.
- Ledger/config/artifacts: experiment history, parameters, metrics, evidence,
  and conclusions.
- Git: implementation history.

No `PROJECT_STATUS.md` is maintained because it would duplicate MEMORY. Add a
`CHANGELOG.md` only when releases or external users need curated history beyond
Git and the experiment ledger.
