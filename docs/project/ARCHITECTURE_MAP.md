# Architecture Map

Related: [PROJECT_OVERVIEW](PROJECT_OVERVIEW.md) · [ROADMAP](ROADMAP.md) ·
root [README](../../README.md).

This map describes the repository as inspected on 2026-09-24 and 2026-09-28
(base commit `e2f1474` plus the uncommitted M1 session model). Section A is
the current implementation. Section B is the target architecture; items there
do **not** exist yet unless marked implemented. Decisions: [DECISION_LOG](DECISION_LOG.md)
D-110 to D-117 and the PROPOSED list.

---

## A. CURRENT IMPLEMENTATION

### A.1 Top-level directories

| Path | Contents | Git |
|---|---|---|
| `src/` | Python library code (importable as `src.*`) | tracked |
| `notebooks/` | Numbered executable research scripts `01_…`–`31_…` (plain `.py`, not Jupyter); the de facto entry points | tracked |
| `tests/` | 31 pytest modules | tracked |
| `config/` | Instrument, dataset/partition, feature-window, component-registry, experiment configs (JSON) | tracked |
| `experiments/` | Schema, templates, reviewed project artifacts, local ledger/runs | partly |
| `strategies/` | Human-readable strategy-family READMEs only (`orb/`, `momentum/` placeholder) | tracked |
| `docs/` | Lifecycle and registration docs; `docs/project/` governance docs | tracked |
| `data/` | Local market data and processed tables | ignored |
| `reports/` | Placeholder (`.gitkeep`) | tracked |
| `backups/` | Local safety copies | ignored |
| root | `README.md`, `MEMORY.md`, `CLAUDE.md`, Nautilus architecture `.md`/`.docx` | tracked |

### A.2 Source modules

| Module | Role | Layer |
|---|---|---|
| `src/features/opening_range.py` | OR calculation for 5/10/15/20/30m (bar-end semantics) | Feature |
| `src/features/session_context.py` | **Generic Market Context (M5A, 2026-09-29):** registry loader, `build_market_context` (audit summary), `valid_context_levels`, `align_market_context`; previous-expected-session Previous Day / Previous RTH and named windows | Feature (generic Market Context) |
| `src/features/market_context.py` | ORB-oriented primitives: OR context, causal width history, Globex reopen / NY-open gaps, `level_interaction` (TOUCH / TRADE_THROUGH / CLOSE_THROUGH / REJECT / SWEEP vs OR). Legacy window helpers (`WindowDefinition`, `summarize_window`, …) are **no longer the market-context source** (M5B); they serve the ORB opening range, the ORB audit, and test references | Feature / State primitives (ORB) |
| `src/experiments/orb_market_context_compat.py` | **ORB compatibility layer (M5B):** maps ORB window features to the generic catalog, the legacy `orb_overnight_1800_0930` definition, the legacy previous-available-session selector, the ORB schema adapter, and a drift guard | Compatibility (ORB) |
| `src/experiments/mnq_orb_v02_features.py` | Builds the V0.2 feature audit. Window features (Asia/London/NY pre-market/overnight/overnight context/previous day/previous RTH) come **from the generic catalog via the compatibility layer**; OR context, gaps, liquidity path, key-level interactions and review queues stay ORB-specific; outcomes kept separate (`outcome_*`) | Feature assembly (ORB-scoped) |
| `src/experiments/mnq_orb_v02_*` (stage3a, width, or_structure, room_to_level, key_level_interaction, london_interaction_event, combined_state_hypothesis) | ORB V0.2 Stage 3 characterization | State / Signal research (ORB) |
| `src/experiments/orb_gate*.py`, `orb_v01_*.py` | ORB V0.1 gate analyses (sweeps, robustness, freeze, validation, post-mortem) | Experiment / Analytics (ORB) |
| `src/backtesting/candidate_entries.py` | Signals → entry/stop/target candidates; `round_to_tick` (tick size constant 0.25) | Strategy / Execution |
| `src/backtesting/completed_trades.py` | Forward simulation, stop/target/session-end, ambiguity codes | Execution |
| `src/backtesting/session_trade_limit.py` | One-trade-per-session eligibility with audit | Execution |
| `src/backtesting/orb_v01.py` | Early lean ORB V0.1 event simulation + legacy ledger usage | Execution (legacy) |
| `src/data/partitions.py` | Session-date partitioning + integrity checks + hashing | Data |
| `src/data/sessions.py` | **Generic session model (M1, 2026-09-28):** trading-date assignment, session bounds, maintenance break, calendar overrides, previous/next expected session | Data / session foundation |
| `src/data/timeframe_store.py` | **Derived-timeframe persistence (M4, 2026-09-29):** `materialize_timeframe` / `load_timeframe`, Parquet + manifest with provenance validation | Data / derived cache |
| `src/data/timeframes.py` | **Generic timeframe builder (M3, 2026-09-29):** `build_timeframe(bars, timeframe, session_spec)` for 5m/15m/1H/4H/1D or any `TimeframeSpec`; on demand, no persistence | Data / derived timeframes |
| `src/data/instruments.py` | **Generic instrument metadata (M2, 2026-09-29):** `load_instrument` → immutable `InstrumentSpec` with exact `Decimal` economics; `is_tick_aligned` | Data / instrument foundation |
| `src/experiments/experiment_index.py` | Read-only index, record validation, artifact discovery, lifecycle/component loaders | Experiment infra |
| `src/experiments/experiment_registration.py` | Prospective registration API (`create_experiment`, `register_artifact`, `finalize_experiment`, `ExperimentRun`) | Experiment infra |
| `src/research_harness.py` | Older SQLite + CSV `ExperimentLedger` (used by `orb_v01.py`, Gate 8A notebook) | Experiment infra (legacy) |
| `src/visualization/research_viewer.py`, `research_viewer_app.py` | Plotly candle viewer for OR/signals/candidates/trades + local HTTP app | Visual validation (ORB) |
| `src/visualization/feature_validation_viewer.py` | Streamlit feature-validation viewer (levels, classification panels) | Visual validation (ORB V0.2) |
| `src/visualization/research_dashboard.py` | Read-only Streamlit experiment/artifact dashboard | Dashboard |
| `src/strategies/` | Empty package (reserved) | — |

### A.3 Configuration

| File | Purpose |
|---|---|
| `config/instruments/mnq.json` | **Authoritative** MNQ metadata (tick 0.25, point value 2.0, tick value 0.5, USD, CME), consumed via `load_instrument` (M2). Content hash is recorded in the frozen Gate 6C provenance, so the file must not change without a decision. Its `research_timezone` / `regular_session` fields are legacy descriptive; session facts belong to `config/sessions/` |
| `config/sessions/cme_globex_et.json` | Authoritative generic session facts (M1) |
| `config/sessions/cme_globex_et.overrides.json` | Session override calendar (CLOSED / MODIFIED); currently empty, coverage null |
| `config/datasets/mnq_1m_actual_contract_v1.partitions.json` | DEVELOPMENT / VALIDATION / OOS(BURNED) session-date ranges |
| `config/features/mnq_orb_v0_2_preopen_windows.json` | Frozen ORB session windows (Asia, London, NY pre-market, overnight 18:00–09:30, overnight context); historical snapshot, not the generic source |
| `config/features/market_context_windows.json` | **Authoritative generic Market Context registry** (M5A): clock windows with explicit day offsets + contexts (`TARGET` / `PREVIOUS_EXPECTED` source session) |
| `config/features/market_context_compatibility.json` | ORB-only compatibility definitions (M5B): currently just `orb_overnight_1800_0930`; not for new strategies |
| `config/features/mnq_orb_v0_2_stage2_human_reviews.json` | Stage 2 human-review decisions |
| `config/components/research_components.json` | Reusable component registry (features/signals/strategy, with status) |
| `config/experiments/*.json` | Per-experiment/gate configurations |
| `experiments/schema/*.json`, `*.sql` | Experiment record, component, lifecycle schemas; ledger SQL |
| `experiments/templates/*.json` | Record and run-config templates |

Configuration flow: JSON configs are loaded directly by experiment modules and
notebooks (e.g. `load_context_windows(config)`, `load_partition_config()`).
There is no central config loader or instrument registry object.

### A.4 Data flow

```text
data/MNQ_raw_cleaned_ET.csv   (1m, ET, bar-end, actual contract column)
   └─ src/data/partitions.py → data/processed/MNQ_raw_cleaned_ET_{DEVELOPMENT,VALIDATION,OOS}.csv
         └─ feature builders read the DEVELOPMENT file (hard-bounded)
```

Other local CSVs exist at `data/` root (continuous-additive series, 10-day
samples). `data/raw/` and `data/cleaned/` are currently empty.

### A.5 Feature → state → signal flow (current, ORB-scoped)

```text
bars → market_context.summarize_window / calculate_or_context  (features)
     → mnq_orb_v02_features.build_feature_audit                 (feature table + audit)
     → add_causal_width_history, level_interaction              (causal states / primitive events)
     → mnq_orb_v02_stage3a / characterization modules           (signal/state research)
```

Signals for ORB V0.1: `research_viewer.find_orb_signals` and the Gate 3
notebooks. There is no generic `Signal` / `State` contract class yet;
representation is tabular (pandas) with column conventions.

### A.6 Execution flow (ORB V0.1)

```text
signals → candidate_entries.build_candidate_entries
        → completed_trades.simulate_completed_trades
        → session_trade_limit.apply_session_trade_limit
        → completed trades + candidate audit (canonical) → analytics / VectorBT
```

### A.7 Experiment flow

```text
config/experiments/<id>.json → runner (notebook / src/experiments module)
 → artifacts in experiments/projects/<project_id>/<class>/
 → records/<id>.json via experiment_registration
 → experiment_index.json refresh → research_dashboard (read-only)
```

### A.8 Visualization / validation flow

- Candle-level: `research_viewer*` (ORB V0.1), `feature_validation_viewer`
  launched via `notebooks/19_mnq_orb_v02_feature_viewer.py`.
- Audit exports and human review queues written as CSV/MD under
  `experiments/projects/mnq_orb_v0_2/features|signals/`.
- Dashboard: `notebooks/17_research_dashboard.py`.

### A.9 Utilities inventory (relevant to new work)

| Need | Exists? | Where / note |
|---|---|---|
| Generic session model / trading date | **Yes (M1)** | `src/data/sessions.py` + `config/sessions/`; not yet used by existing modules |
| Session/timezone windows | Yes (ORB-scoped) | `market_context.py` + ORB windows JSON; `ET_TIMEZONE` defined in 2 modules and `"America/New_York"` literal in ~8 more |
| Session-date ownership (18:01 reopen → next date) | Yes (data + config) | Dataset `session_date` column; the M1 bar-end rule follows the same documented convention (not yet checked row-by-row against the dataset) |
| Resampling to derived timeframes | **Yes (M3/M4)** | `src/data/timeframes.py` on demand; `src/data/timeframe_store.py` persists Parquet + manifest |
| Instrument / tick size | **Yes (M2)** | `src/data/instruments.py` + `config/instruments/`. Not yet consumed by existing code. Legacy duplicates still present: `TICK_SIZE = 0.25` in `candidate_entries.py` (guarded by a test), `"tick_size": 0.25` literal in `orb_gate6b_fixed_points.py` metadata, `tick_size` in `config/experiments/orb_gate6b_dev_fixed_target_stop.json`; notebook 14 embeds the raw `mnq.json` into the frozen V0.1 spec |
| Generic level lifecycle (ACTIVE/TAKEN) | **No** | `level_interaction` evaluates a level against the OR window only |
| Swing / EQ / REQ / FVG / MSS detection | **No** | Nothing ICT-related exists |

### A.10 Entry points

- Research scripts: `notebooks/NN_*.py` (run with the venv Python).
- Viewers: `streamlit run notebooks/19_mnq_orb_v02_feature_viewer.py`,
  `streamlit run notebooks/17_research_dashboard.py`.
- CLIs: `python -m src.data.partitions`, `python -m src.research_harness`.
- Tests: `python -m pytest -q`.

### A.11 Verified behavior of existing reusable logic (2026-09-28)

**Session windows** (`market_context.summarize_window`)

- A window uses bar-ends `start+1min` … `end`, drawn only from rows of the
  same `session_date`.
- It is **strictly complete-or-unavailable**: one missing bar makes it NaN
  with `INCOMPLETE_WINDOW`.
- `available_at` is the last expected bar-end.

**Previous Day H/L/C** (built in `mnq_orb_v02_features.build_feature_audit`)

- Uses a `trading_day` window 18:00 → 17:00 (offset -1) over the prior
  session: 1380 bars, strict completeness.
- "Prior" means the previous `session_date` **present in the dataset**, so a
  missing session silently falls back to an earlier one. This differs from
  D-113.
- `available_at` is 17:00 on the prior date. Previous RTH uses the same
  mechanism with 09:30 → 16:00.

**Frozen ORB windows**

- Asia 20:00–00:00, London 02:00–05:00, NY pre-market 07:00–09:00.
- `overnight` 18:00–09:30, which differs from the generic 18:00–07:00 in
  D-114.
- `overnight_context_2000_0900`.

**Level interaction** (`market_context.level_interaction`)

- Evaluates one aggregated OR window, not a bar sequence. Orientation comes
  from the OR open.
- For a level above the open:

| Event | Rule |
|---|---|
| TOUCH | `low <= level <= high` |
| TRADE_THROUGH | `high > level` |
| CLOSE_THROUGH | `close > level` |
| SWEEP | TRADE_THROUGH and `close <= level` |
| REJECT | TOUCH and `close <= level` |

- The rules mirror for levels below the open. If the open equals the level,
  every directional flag is False.

**Ledgers**

- `research_harness.ExperimentLedger` is used only by `orb_v01.py` and
  notebook 16 (Gate 8A).
- The registration API is used by notebooks 18, 20, 22, 29, 30, 31. It
  rejects duplicate experiment IDs, including across projects.

**Tests**

- A grep found **no** test reading Git-ignored market data. This corrects the
  2026-09-24 note.
- Tests use synthetic frames plus tracked reviewed artifacts and configs as
  golden evidence. There are no tiers or markers.
- 4 existing tests have stale expectations (see WORK_PROGRESS).

**Storage**

- CSV with ISO-8601 offsets.
- No Parquet was in use before M4. Since M4, derived timeframes are Parquet
  via `pyarrow` (pinned `25.0.1`); source data remains CSV.

---

## B. TARGET ARCHITECTURE (design; not implemented unless marked)

```text
validated 1m (canonical, immutable)
  → session model (M1, IMPLEMENTED) + instrument metadata
  → generic timeframe builder (derived bars = cache)
  → Market Context features + level-interaction primitives
  → States → Signals → Strategy eligibility → Execution → Trades → Experiments
```

Generic code is added alongside ORB. Frozen ORB outputs serve as the parity
oracle, and ORB migrates to the generic code only after parity is proven
(D-110).

### B.1 Session model — IMPLEMENTED (M1)

- `src/data/sessions.py` with `config/sessions/cme_globex_et.json` and
  `cme_globex_et.overrides.json` (D-111, D-112, D-113).
- API:
  - `load_session_spec`, `with_calendar_overrides`, `get_session_override`
  - `assign_trading_date`, `session_bounds`, `session_status`
  - `is_in_session`, `is_maintenance_break`
  - `previous_expected_session`, `next_expected_session`
- Timestamps may be `label="instant"` (default) or `label="bar_end"` with a
  `bar_interval`.

### B.2 Timeframe builder — IMPLEMENTED on demand (M3; D-116, D-119)

**API**

- `build_timeframe(bars, timeframe, session_spec, *, source_interval="1min")`
- `timeframe` is `"5m"`, `"15m"`, `"1H"`, `"4H"`, `"1D"`, or any
  `TimeframeSpec(id, minutes | None)`. `None` means one bar per session.
- `bars` must have a tz-aware bar-end `DatetimeIndex` and the columns open,
  high, low, close, volume and contract. An optional `session_date` column
  is checked against the session model.

**Bucketing**

- Buckets anchor at the regular session open (18:00 ET on the prior day) and
  are clipped to the actual session bounds.
- 5m, 15m and 1H divide the 1380-minute session exactly.
- 4H buckets start at 18/22/02/06/10/14. The final one ends at 17:00 and is
  flagged `is_session_truncated`.
- A 1m bar joins the bucket containing its bar-start.
- OHLCV is first / max / min / last / sum.
- Empty buckets produce no row. Mixed-contract buckets **raise** (roll
  handling deferred).

**Output fields**

- `timeframe`, `trading_date`, `contract`
- `bar_start`, `bar_end`, `available_at = bar_end`
- OHLCV
- `expected_bars`, `observed_bars`, `is_complete`, `is_session_truncated`
- The index `timestamp_et` equals `bar_end`.

**DEVELOPMENT smoke check (2026-09-29, read-only)**

- All 337,815 bars passed session validation, and every `session_date`
  matched the session model.
- No mixed-contract buckets occurred.
- Incomplete daily bars: 28 of 248 (11.3%).
- Each timeframe built in about 1 s.

**Consumption rule**

- An HTF bar is usable at base time t only if `available_at <= t`.
- Level interaction starts on the next base bar.

### B.3 Generic Market Context — M5A IMPLEMENTED (D-124)

Full specification: [M5_MARKET_CONTEXT_SPEC](M5_MARKET_CONTEXT_SPEC.md).

**Module and registry**

- Module `src/features/session_context.py`; registry
  `config/features/market_context_windows.json`.
- Generic contexts: `previous_day`, `previous_rth`, `asia_2000_0000`,
  `london_0200_0500`, `overnight_1800_0700`,
  `overnight_context_2000_0900`, `ny_premarket_0700_0900`.

**API**

- `load_market_context_windows` → registry.
- `build_market_context` → audit summary (`observed_*`, reasons).
- `valid_context_levels` → available only.
- `align_market_context` → per-bar values plus a status
  (`AVAILABLE` / `PENDING` / `UNAVAILABLE_CONTEXT` / `CONTRACT_MISMATCH`).

**Semantics**

- Computed from canonical 1m data with the M1 session model.
- Strict completeness and schedule clipping.
- Previous-expected-session selection with no fallback.
- `MIXED_CONTRACT` within a window.
- Causal `bar_start ≥ available_at`; target-session scope.

**Status and frozen ORB**

- **M5B (D-125): ORB consumes the catalog** through
  `orb_market_context_compat.py`. The only compatibility items are the
  legacy 18:00–09:30 overnight and the legacy previous-available-session
  selector.
- One evaluation engine, `evaluate_context`, with a pluggable source
  session.
- The migrated ORB audit matches the pre-migration output and the frozen
  oracle exactly (all 474 columns).
- Generic vs frozen-ORB differences are by design: Previous Day / RTH on 6
  dates (D-121); overnight 18:00–07:00 vs 18:00–09:30.

### B.4 Level interaction (D-115; API PROPOSED)

- `level_orientation(level, reference_price)`
- `eligible_bars(bars, level_available_at)`
- `interaction_flags(bars, level, orientation, tick_size)`, with integer-tick
  comparison and per-bar evaluation.
- `aggregate_window_ohlc` reproduces ORB exactly.
- The existing `level_interaction` stays as an ORB compatibility wrapper.
- Invariants:
  - CLOSE_THROUGH ⇒ TRADE_THROUGH ⇒ TOUCH
  - SWEEP ⇒ REJECT
  - every TOUCH is either a CLOSE_THROUGH or a REJECT

### B.5 State / Signal contracts (PROPOSED)

- A DataFrame column schema, a small frozen dataclass spec, and a validator.
  No Pydantic and no class hierarchy.
- Shared fields: id, name, `definition_version`, instrument, contract,
  timeframe, `observed_at`, `available_at` (>= `observed_at`), direction,
  `source_ids`, `causal`, and JSON `metadata`.
- States add `value` and `active`. Signals add `reason`.
- A Signal carries no order, price, or quantity fields.

### B.6 Other items

**Derived-data persistence — IMPLEMENTED (M4; D-122)**

- `materialize_timeframe(tf, partition=...)` and
  `load_timeframe(tf, partition=...)` in `src/data/timeframe_store.py`.
- Output is Parquet (`pyarrow`) plus a JSON manifest, under
  `data/derived/timeframes/<dataset_id>/<partition>/` (Git-ignored).
- The manifest records:
  - dataset and partition, instrument and contracts;
  - source path, SHA-256, row count and range;
  - timeframe, session fingerprint and calendar coverage;
  - conventions;
  - builder version, Git SHA, and library versions;
  - output SHA-256, rows and incomplete count.
- Loading validates the output hash, builder version, session fingerprint
  and source hash. A stale file raises; nothing is rebuilt silently.
- Reserved partitions need an explicit flag.
- DEVELOPMENT materialization (2026-09-29) reproduced the M3.1 row counts and
  incomplete counts exactly for all five timeframes, about 4.6 MB in total.

**Instrument metadata — IMPLEMENTED (M2)**

- `load_instrument(id, config_dir=...)` returns a frozen `InstrumentSpec`
  (`instrument_id`, `name`, `asset_class`, `exchange`, `currency`,
  `tick_size`, `point_value`, `tick_value`, `source_path`).
- Economics are parsed from the JSON text straight into `Decimal`, and
  `tick_value == tick_size × point_value` is checked exactly.
- Errors: `InstrumentError` ⊃ `InstrumentNotFoundError`,
  `InstrumentConfigError`. There are no defaults.
- `is_tick_aligned(price, tick_size)` is the only tick helper. Broader tick
  arithmetic belongs to the level-interaction milestone.
- Legacy `TICK_SIZE` and the `mnq.json` provenance hash are guarded by tests.
- Consumers are not migrated yet.

**Ledger**

- The registration API is canonical. `research_harness.py` is legacy: kept
  for reproducing old runs, with no new callers.

**Tests**

- Tiers: unit (synthetic, default), golden (tracked fixtures/artifacts), and
  integration (local data, opt-in, explicit skip).

### B.7 ORB reuse classification (for later parity milestones)

| Classification | Items |
|---|---|
| **Generalize** | `WindowDefinition`, `expected_bar_end_index`, `summarize_window`, timezone constant, `_direction`/`_safe_divide`/`interaction_state`, session-window and previous-day/RTH assembly, `round_to_tick` |
| **Wrap for compatibility** | `level_interaction`, `load_development_prices` |
| **Keep ORB-specific** | OR context, width history, `KEY_LEVEL_IDS`, breakout outcomes, review queues, characterization code, ORB viewers |
| **Generalize later** | gap measurement, `_liquidity_path` |
| **Deprecate later** | ORB constants in `market_context.py`, hard-coded DEV bounds, `research_harness`, `orb_v01.py` |

### B.8 Deferred to the next ICT design run (D-117)

- Contract rolls.
- External and Internal Liquidity, specified together: EQH/EQL, REQH/REQL,
  swings, lifecycle and consumption, and the cross-timeframe hierarchy.
- Then FVG, Rejection Block, MSS, and strategy rules.
- Nautilus migration is downstream (D-108).
