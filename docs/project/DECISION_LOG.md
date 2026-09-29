# Decision Log

Answers: **"Why did we choose this?"** Architectural and research decisions
only. Decisions are made by the design authority (outside Claude); Claude
records them and never invents them.

Status values: `ACTIVE`, `PENDING` (direction set, details open), `SUPERSEDED`,
`REVOKED`.

Dates: for D-001–D-005 the date is when the decision was first recorded in the
repository. For D-101 onward the date is when it was recorded here
(2026-09-24 or 2026-09-28); the decision itself may predate that.

---

## Historical decisions (already recorded in README / MEMORY / configs)

### D-001 — Custom execution is authoritative where semantics matter
- **Date:** by 2026-08-19 (initial baseline `3be81e2`; README/MEMORY)
- **Decision:** The custom engine is the source of truth when intrabar order,
  next-bar fills, session rules, ambiguity, or trade limits matter. VectorBT is
  used for faithful vectorized work, cross-checks, parameter arrays, and charts.
- **Reason:** `Portfolio.from_signals()` would change ORB trade semantics.
- **Alternatives considered:** VectorBT-only execution.
- **Consequences:** Completed trades/audits are canonical; summaries derived.
- **Status:** ACTIVE
- **Revisit trigger:** A gate proving trade-level equivalence, or Nautilus parity.

### D-002 — Timestamp semantics: NT8 bar-end labels in Eastern Time
- **Date:** 2026-08-20 (commit `71c96f0`)
- **Decision:** `timestamp_et = bar_end_time`; a conceptual `[start, end)` window
  uses bars stamped `start+1min` through `end`. Bars from the 18:01 reopen belong
  to the next CME trading `session_date`.
- **Reason:** Correct ORB timing for NinjaTrader exports.
- **Alternatives considered:** Bar-start labeling.
- **Consequences:** All windows/features must follow this; changes need approval.
- **Status:** ACTIVE
- **Revisit trigger:** New data vendor or bar source.

### D-003 — Partition policy and burned evidence
- **Date:** 2026-08-21 (commit `e056d61`; partition config)
- **Decision:** DEVELOPMENT 2024-06-21–2025-06-30; VALIDATION 2025-07-01–
  2025-12-31; OOS 2026-01-01–2026-08-17 labeled `OOS_BURNED` (full-history ORB
  results were viewed before partitioning). VALIDATION was exposed by ORB Gate
  7/8A and is burned for ORB V0.2 hypothesis generation.
- **Reason:** Confirmatory discipline; honest evidence labeling.
- **Alternatives considered:** —
- **Consequences:** How ICT uses these partitions is an open question (see
  WORK_PROGRESS).
- **Status:** ACTIVE
- **Revisit trigger:** New data extension or new research family partition plan.

### D-004 — Session windows frozen (Stage 2, ORB V0.2)
- **Date:** 2026-09-02
- **Decision:** Asia 20:00–00:00 ET, London 02:00–05:00 ET, NY pre-market
  07:00–09:00 ET (`NY PM` = pre-market), `OVERNIGHT_CONTEXT_2000_0900`;
  previous full futures trading-day H/L are the primary prior-day references.
- **Reason:** Human visual review (14/14 cases passed).
- **Alternatives considered:** `combined_preopen` (now migration alias only).
- **Consequences:** Defined in `config/features/mnq_orb_v0_2_preopen_windows.json`.
- **Status:** ACTIVE (frozen)
- **Revisit trigger:** Explicit design-authority change.

### D-005 — MNQ ORB V0.1 decision
- **Date:** 2026-08-24 (Gate 7, commit `8c9295e`)
- **Decision:** CAND_001 `REVISE`; CAND_002 and CAND_003 `REJECT`. No OOS or
  production progression.
- **Reason:** Development edge did not persist through VALIDATION.
- **Status:** ACTIVE (final)
- **Revisit trigger:** None (a revision is a new version).

---

## Decisions recorded 2026-09-24 (supplied by design authority)

### D-101 — ORB is parked
- **Date:** 2026-09-07 (closure note) / recorded 2026-09-24
- **Decision:** MNQ ORB V0.2 is `PARKED_AS_RESEARCH_CANDIDATE`. Preserve all
  features, frozen artifacts, tests, and evidence. No new ORB optimization cycle.
  `HYP-ORB-STATE-01` is `POTENTIALLY_INFORMATIVE`, `UNVALIDATED`, parked.
- **Reason:** No sufficiently stable causal participation state (Stage 3C).
- **Alternatives considered:** Promote the 5-session lookback (rejected as
  post-hoc selection).
- **Consequences:** ORB serves as infrastructure example and future
  regression/parity oracle.
- **Status:** ACTIVE
- **Revisit trigger:** Explicit authorization to reopen ORB research.

### D-102 — ICT is a separate research family from ORB
- **Date:** 2026-09-24
- **Decision:** ICT research is a new family; it must not be implemented as an
  extension of the ORB strategy family or its modules.
- **Reason:** Keep research lineage, frozen ORB evidence, and concepts separate.
- **Alternatives considered:** Extending ORB V0.2 feature modules.
- **Consequences:** Generic ORB infrastructure may be reused only as explicitly
  authorized; ICT gets its own project/modules (location to be decided).
- **Status:** ACTIVE
- **Revisit trigger:** —

### D-103 — Feature-first approach for ICT
- **Date:** 2026-09-24
- **Decision:** Phase 1 defines and validates reusable primitives (External
  Liquidity, Internal Liquidity / swing structure, FVG, Rejection Block, MSS).
  Strategy/model construction (Phase 2, e.g. Turtle Soup / liquidity raid) waits
  until primitives are visually and programmatically validated.
- **Reason:** Performance must not be used to justify feature definitions.
- **Alternatives considered:** Strategy-first prototyping.
- **Consequences:** No ICT strategy code or performance testing now.
- **Status:** ACTIVE
- **Revisit trigger:** Required Phase 1 primitives reach `FROZEN`.

### D-104 — External Liquidity reference set
- **Date:** 2026-09-24
- **Decision:** External liquidity includes session references (Previous Day
  H/L, Asia H/L, London H/L, NY Pre-market H/L, Overnight H/L, where already
  implemented) and HTF equal/relative-equal levels: Daily EQH/EQL, Daily
  REQH/REQL, 4H EQH/EQL, 4H REQH/REQL. **1H EQ/REQ is excluded** from external
  liquidity; 1H structures more likely belong to Internal Liquidity.
- **Reason:** Design-authority classification.
- **Alternatives considered:** Including 1H EQ/REQ.
- **Consequences:** HTF resampling utility needed; overnight definition to
  confirm.
- **Status:** ACTIVE (HTF details PENDING)
- **Revisit trigger:** Internal Liquidity definition work.

### D-105 — EQH / EQL semantics
- **Date:** 2026-09-24
- **Decision:** Exact equality (zero-tick tolerance); no pivot requirement;
  multiple candles sharing the exact extreme strengthen the same level; no
  look-forward requirement; becomes relevant causally once sufficient historical
  observations exist; touching does not consume; trading through consumes; after
  consumption the new extreme becomes the reference for future structures.
- **Reason:** Design-authority definition.
- **Alternatives considered:** Pivot-confirmed equal highs/lows.
- **Consequences:** Needs precise "sufficient observations" and "trade through"
  rules before implementation.
- **Status:** PENDING (core direction ACTIVE; details open)
- **Revisit trigger:** Formal specification task.

### D-106 — REQH / REQL semantics and 6-tick tolerance
- **Date:** 2026-09-24
- **Decision:** REQ is a **cluster**, not an averaged price. Current working
  tolerance: **6 ticks** for all included HTFs. Member prices are preserved.
  Chain/pyramiding structures allowed; linked nearby members keep a member in
  the cluster; no arbitrary small member cap. Partial consumption possible: if
  lower members of an REQH are removed but a higher active member remains, the
  cluster remains active (inverse for REQL). Trading through the current outer
  active extreme consumes the pool; new extremes may form new structures. No
  semantic time expiry while untouched; a performance working-set horizon may be
  used but must not alter historical ACTIVE/TAKEN state.
- **Reason:** Design-authority definition.
- **Alternatives considered:** Averaged single-price REQ level; capped member
  count; time expiry.
- **Consequences:** Needs a precise linkage rule (see WORK_PROGRESS).
- **Status:** ACTIVE (tolerance is a working value)
- **Revisit trigger:** Visual validation results or spec review.

### D-107 — No look-forward for immediate swing candidates (where later specified)
- **Date:** 2026-09-24
- **Decision:** Where immediate swing candidates are later specified, they must
  not require look-forward confirmation.
- **Reason:** Causality.
- **Alternatives considered:** Pivot-style right-side confirmation.
- **Consequences:** Meaningful swing and MSS definitions are **not finalized**;
  do not invent them.
- **Status:** PENDING
- **Revisit trigger:** Internal Liquidity / swing specification.

### D-108 — Nautilus migration is downstream
- **Date:** 2026-09-24
- **Decision:** This repository stays the research source of truth and is not
  refactored toward NautilusTrader now. Validated concepts may migrate later
  with parity tests.
- **Reason:** Keep current research independently usable and stable.
- **Alternatives considered:** Refactor now to Nautilus contracts.
- **Consequences:** The Nautilus transfer document is reference-only here.
- **Status:** ACTIVE
- **Revisit trigger:** Explicit migration task.

### D-109 — Documentation / project-memory layer
- **Date:** 2026-09-24
- **Decision:** Adopt `CLAUDE.md` + `MEMORY.md` + `docs/project/WORK_PROGRESS.md`
  + `docs/project/DECISION_LOG.md` as the continuity set, plus an internal
  `docs/project/CHANGELOG.md`.
- **Reason:** Multi-agent workflow (design authority external, Claude as
  implementer) needs durable session continuity.
- **Alternatives considered:** MEMORY-only (previous README/MEMORY rule: "No
  PROJECT_STATUS.md", "No CHANGELOG.md until releases").
- **Consequences:** Supersedes that previous rule; README/MEMORY updated.
- **Status:** ACTIVE
- **Revisit trigger:** Documentation becomes duplicated or stale.

---

## Decisions recorded 2026-09-28 (architecture closeout + M1 approval)

### D-110 — Reusable primitives architecture; ORB migrates after parity
- **Date:** 2026-09-28
- **Decision:** Generally useful market concepts live in reusable layers
  (`src/data/` for session/timeframe foundations, `src/features/` for Market
  Context and level interaction), not inside strategy or experiment modules.
  The target pipeline is raw → validated → derived timeframes → features /
  market context → states → signals → strategy eligibility → execution →
  trades → experiments. The long-term intention **is** to migrate reusable ORB
  market-context behavior to generic infrastructure, but only after parity /
  regression tests prove identical historical outputs.
- **Reason:** Avoid duplicating concepts across families while keeping frozen
  ORB results reproducible.
- **Alternatives considered:** ORB permanently independent; immediate refactor.
- **Consequences:** Generic code is built alongside ORB first; frozen ORB
  outputs act as the parity oracle; no ORB code changes until a separately
  approved milestone.
- **Status:** ACTIVE
- **Revisit trigger:** A parity milestone is approved.

### D-111 — Single generic session model (M1)
- **Date:** 2026-09-28
- **Decision:** `config/sessions/cme_globex_et.json` + `src/data/sessions.py`
  are the single authoritative source for generic session facts: timezone
  `America/New_York`; session for trading_date D = [18:00 ET on D-1, 17:00 ET
  on D); 17:00–18:00 maintenance break (instants there belong to no session);
  an instant at/after 18:00 belongs to the next date, before 17:00 to its own
  date; Mon–Fri trading dates. Weekly boundary: Mon–Thu 17:00–18:00 is
  `MAINTENANCE_BREAK`; Friday from 17:00, all of Saturday, and Sunday before
  18:00 are `NON_TRADING_DAY` (no Friday evening open); Sunday 18:00 opens the
  Monday session (clarified in M1.1); DST handled via timezone-aware wall-clock rules,
  never fixed UTC offsets. Bar-labelled data is evaluated on its bar-start
  instant (NT8 bar-end label minus interval). Strategy/market-context windows
  are not part of this config.
- **Reason:** Replace duplicated timezone/session constants with one source.
- **Alternatives considered:** Keep per-module constants; external calendar
  library.
- **Consequences:** New code must use this module. Existing duplicated
  `ET_TIMEZONE` constants and ORB session behavior are untouched for now.
- **Status:** ACTIVE (implemented 2026-09-28)
- **Revisit trigger:** A non-CME session model is needed.

### D-112 — Calendar override architecture
- **Date:** 2026-09-28
- **Decision:** Base regular weekly session + explicit overrides behind one
  API. Override kinds: `CLOSED` (full closure) and `MODIFIED` (shortened
  session — later open and/or earlier close, strictly within regular bounds).
  Overrides live in `config/sessions/cme_globex_et.overrides.json` with a
  declared coverage range; `with_calendar_overrides()` replaces the calendar
  without changing downstream APIs. No external calendar dependency.
- **Reason:** Represent holidays/early closes explicitly and replaceably.
- **Alternatives considered:** `pandas_market_calendars` or similar
  dependency.
- **Consequences:** The override calendar is currently **empty with null
  coverage** — no holiday dates were invented. Populating it requires an
  authoritative exchange calendar.
- **Status:** ACTIVE (mechanism implemented; data not populated)
- **Revisit trigger:** Holiday data source approved.

### D-113 — Previous trading session = previous EXPECTED session
- **Date:** 2026-09-28
- **Decision:** Generic "previous day" must refer to the previous **expected**
  trading session (weekly schedule + overrides), not the previous session
  present in a DataFrame. Downstream code must distinguish MISSING EXPECTED
  SESSION from LEGITIMATE EXCHANGE CLOSURE. No silent fallback to older
  sessions.
- **Reason:** The ORB implementation silently uses an earlier session if a
  session is absent from the data.
- **Alternatives considered:** Keep dataset-previous semantics.
- **Consequences:** `previous_expected_session()` / `next_expected_session()`
  exist in M1 and return `calendar_verified=False` when any examined date lies
  outside override coverage. Generic PDH/PDL is **not** implemented yet. ORB's
  historical (dataset-previous) behavior stays frozen and will differ from the
  generic rule wherever a session is missing — parity work must account for it.
- **Status:** ACTIVE
- **Revisit trigger:** Market Context milestone.

### D-114 — Generic context windows (design directive; not implemented)
- **Date:** 2026-09-28
- **Decision:** For the future generic Market Context: Overnight 18:00→07:00
  ET and NY Premarket 07:00→09:00 ET are separate, non-overlapping windows;
  09:00–09:30 is outside both. Asia and London keep the existing validated
  definitions (20:00–00:00, 02:00–05:00). Frozen ORB windows (including ORB
  `overnight` = 18:00–09:30) are not reinterpreted.
- **Reason:** Design-authority directive.
- **Consequences:** The generic overnight needs a distinct ID from ORB's
  `overnight` (proposed `overnight_1800_0700`; confirmation pending).
- **Status:** ACTIVE (not implemented)
- **Revisit trigger:** Market Context milestone.

### D-115 — Level-interaction semantics (design directive; not implemented)
- **Date:** 2026-09-28
- **Decision:** TOUCH = price reaches the level. TRADE_THROUGH = at least one
  tick beyond intrabar (upper: `high >= level + tick`; lower:
  `low <= level - tick`); a close beyond is not required. CLOSE_THROUGH is
  stricter (upper: `close >= level + tick`; lower: `close <= level - tick`), so
  CLOSE_THROUGH ⇒ TRADE_THROUGH. A newly created/confirmed level cannot
  interact with the bar that establishes it; interaction begins on the next
  eligible base bar. REJECT and SWEEP keep their existing repository meaning
  (REJECT = touched and closed back on/at the original side; SWEEP =
  traded through and closed back on/at the original side), pending formal
  confirmation.
- **Reason:** Design-authority directive; generic, strategy-independent.
- **Consequences:** On a 0.25 tick grid the existing ORB strict comparisons
  (`high > level`, `close > level`) are equivalent. Orientation reference
  price (what makes a level "upper"/"lower") is still open.
- **Status:** ACTIVE (REJECT/SWEEP formalization and orientation PENDING)
- **Revisit trigger:** Level-interaction milestone.

### D-116 — Derived timeframes (design directive; not implemented)
- **Date:** 2026-09-28
- **Decision:** Validated 1m data remains the canonical immutable source. A
  generic deterministic timeframe builder (not hard-coded to Daily/4H) derives
  5m, 15m, 1H, 4H and Daily bars; persisted derived files are cache, never
  authoritative. Daily = 18:00 prior day → 17:00 trading date. 4H anchored to
  18:00: 18:00, 22:00, 02:00, 06:00, 10:00, 14:00 (final segment ends 17:00).
  Smaller bars align to the same session anchor. No dynamic anchoring from the
  first observed record; no synthetic bars over missing periods or holidays.
  Downstream features never receive an HTF bar before it is complete.
- **Reason:** Design-authority directive.
- **Consequences:** Builds on the M1 session model.
- **Status:** ACTIVE (not implemented)
- **Revisit trigger:** Timeframe-builder milestone.

### D-117 — Deferrals and sequencing
- **Date:** 2026-09-28
- **Decision:** (a) Contract-roll handling is required before liquidity
  objects may span contract boundaries; current data is not back-adjusted;
  design deferred to the next ICT design run. (b) External and Internal
  Liquidity will be specified **together** (timeframe hierarchy, rolls,
  swings, EQ/REQ behavior). (c) FVG, Rejection Block, MSS and strategy rules
  come after the liquidity/structure foundations. (d) Architecture milestones
  proceed one at a time with explicit approval (M1 approved 2026-09-28).
- **Status:** ACTIVE
- **Revisit trigger:** Next ICT design run.

### D-118 — Authoritative instrument metadata (M2)
- **Date:** 2026-09-29
- **Decision:** `config/instruments/<instrument_id>.json` is the single
  authoritative source for instrument economics, consumed through
  `src/data/instruments.load_instrument()` into an immutable `InstrumentSpec`.
  - Tick size, point value, and tick value are exact `Decimal`s parsed from
    the JSON text (never via binary floats).
  - `tick_value == tick_size × point_value` must hold exactly.
  - Missing, invalid, or inconsistent metadata fails explicitly. There are no
    Python defaults and no substitute instruments.
  - The canonical schema keeps the existing `mnq.json` field names
    (`tick_size_points`, `point_value_usd`, `tick_value_usd`).
  - `instrument_id` is the root (e.g. `MNQ`), not a dated contract.
- **Reason:** Remove duplicated, hard-coded instrument facts.
- **Alternatives considered:** Renaming the `mnq.json` fields to a new schema.
  Rejected because the file's SHA-256 is recorded in the frozen Gate 6C
  provenance.
- **Consequences:**
  - Legacy constants (`candidate_entries.TICK_SIZE`, experiment-metadata
    literals) remain temporarily for ORB compatibility. They are guarded by
    tests and are not independent sources.
  - Consumers are not migrated in M2.
  - Contract identity beyond the root, and all roll behavior, remain deferred
    (D-117).
- **Status:** ACTIVE (implemented 2026-09-29)
- **Revisit trigger:** First consumer migration, or a non-USD instrument.

### D-119 — Timeframe builder policies (M3)
- **Date:** 2026-09-29
- **Decision:** `src/data/timeframes.build_timeframe()` implements D-116 on
  demand, with no persistence.
  - **Anchoring:** buckets anchor at the *regular* session open. They are
    clipped to the actual session bounds (overrides applied) and flagged
    `is_session_truncated`.
  - **Incomplete buckets** are **emitted with flags** (`expected_bars`,
    `observed_bars`, `is_complete=False`). Downstream consumption policy is
    decided per milestone.
  - **Availability:** `available_at = bar_end` (nominal, clipped), even for
    incomplete bars.
  - **Empty buckets** produce no row.
  - **Mixed contracts:** a bucket mixing contracts **raises** until roll
    handling exists (D-117).
  - **Source validation:** bars must lie inside session bounds. An optional
    `session_date` column must match the session model.
  - Trading-date ownership comes from the new vectorized
    `sessions.assign_trading_dates()`, which is parity-tested against the
    scalar rule.
- **Reason:** Design-authority answers of 2026-09-29 on the two open
  policies.
- **Alternatives considered:** Drop incomplete buckets (the strict ORB-window
  style); emit and flag mixed-contract buckets.
- **Consequences:** Without a populated holiday calendar, early-close
  sessions appear as incomplete rather than truncated. On DEVELOPMENT data,
  11.3% of daily bars are incomplete.
- **Status:** ACTIVE (implemented 2026-09-29)
- **Revisit trigger:** Holiday calendar populated; roll design; M4
  persistence.

### D-120 — D1 data-quality gate: roll reconstruction + holiday calendar
- **Date:** 2026-09-29
- **Decision:** Add **D1 — Source Data / Contract-Roll Reconstruction +
  Holiday / Early-Close Calendar** as a data-quality / research-validity gate.
  - It is not an architecture milestone.
  - D1 must be completed before generic Market Context / Previous Day (M5),
    and before External/Internal Liquidity research relies on source data.
  - M4 (persistence) may precede D1.
  - The D1 technical solution is **not** defined here.
- **Reason:** The M3.1 DEVELOPMENT audit (all builder accounting reconciled,
  0 mismatches; all 337,815 bars match the session model) found:
  - 16 absent Mon–Thu sessions in quarterly roll weeks;
  - roll Fridays starting at 00:01 (360 minutes missing);
  - 3 further absent weekdays that are unverified closure candidates;
  - early data ends that the empty override calendar cannot verify.
- **Consequences:**
  - Naïve previous-day traversal jumps over missing sessions.
  - Multi-session liquidity/state objects could span missing data.
  - Daily/4H structures around rolls may mislead.
  - Missing data cannot be told apart from closures until the calendar is
    verified.
- **Alternatives considered:** Proceed to Market Context on current data
  (rejected: invalid previous-day semantics); block M4 as well (rejected:
  persistence preserves source faithfully with completeness metadata).
- **Status:** ACTIVE (gate open; solution to be designed)
- **Revisit trigger:** D1 design task.

### D-121 — Frozen ORB previous-day limitation (documented, not changed)
- **Date:** 2026-09-29
- **Decision:** Frozen ORB research remains historical evidence and is
  **not** reopened or changed.
  - Known limitation: its previous-day logic uses the prior session
    *present in the dataset*.
  - Around missing roll-week sessions, it may therefore reference an older
    session than the expected immediately-prior CME session. For example, a
    roll Friday references the previous week's Friday.
- **Reason:** M3.1 finding. Changing frozen outputs would rewrite historical
  evidence.
- **Consequences:**
  - Recorded as a known limitation and a future, separately authorized
    sensitivity-analysis item.
  - ORB conclusions are unchanged by this task.
  - Future ORB parity tests must account for this intended difference from
    D-113.
- **Status:** ACTIVE
- **Revisit trigger:** D1 completion or any ORB reopening.

### D-122 — Derived-timeframe persistence: Parquet + manifest (M4)
- **Date:** 2026-09-29
- **Decision:** Derived timeframes are persisted by
  `src/data/timeframe_store.py` as a Parquet file plus a sibling JSON
  manifest.
  - **Engine:** `pyarrow`, now pinned in `requirements.txt` as `25.0.1`, the
    version already installed via streamlit.
  - **Layout:** `data/derived/timeframes/<dataset_id>/<partition>/<dataset_id>__<partition>__<tf>__tfb-v<N>.parquet`
    plus `.manifest.json`. The folder is Git-ignored.
  - **Source:** the partition file declared in the dataset partition config.
  - **Partition guard:** only DEVELOPMENT-role partitions are processed
    unless `allow_reserved_partition=True` is passed explicitly.
  - **Validity:** a persisted file is returned only if its manifest matches
    the Parquet SHA-256, the current `TIMEFRAME_BUILDER_VERSION`, the
    effective session-model fingerprint (including overrides), and, by
    default, the source SHA-256.
  - **Mismatch:** raises `StaleDerivedTimeframeError`. There is no silent
    rebuild on read. `materialize_timeframe()` reuses valid files and
    replaces stale ones.
  - **Writes:** atomic (temp file, then replace). Parquet is written before
    the manifest.
  - **Git SHA and dirty flag:** recorded for provenance, but not a validity
    criterion.
- **Reason:** Design-authority approval of Parquet + manifest (2026-09-29).
  Parquet preserves the tz-aware timestamps, dates, ints and bools exactly;
  a round-trip test shows strict frame equality.
- **Alternatives considered:** CSV + manifest (loses dtypes, larger);
  silent rebuild on read (hides provenance changes).
- **Consequences:**
  - Derived files are cache, never authoritative, and are rebuildable from
    the 1m source.
  - Bumping `TIMEFRAME_BUILDER_VERSION` changes file names, so old versions
    are never returned.
  - M4 precedes D1 by design (D-120): it faithfully preserves current
    source completeness.
- **Status:** ACTIVE (implemented 2026-09-29)
- **Revisit trigger:** D1 source rebuild (new source hash); a builder
  semantic change.

### PROPOSED items awaiting design-authority approval (2026-09-28)
Claude recommendations from the architecture closeout; **not decisions**:
Market Context as tidy-DataFrame functions (no MarketContext object);
level-interaction API with integer-tick comparison and per-bar plus
window-aggregate modes; minimal State/Signal contracts as a DataFrame column
schema + small frozen dataclass spec (Signal has no order fields);
registration API as the canonical ledger (`research_harness.py` legacy);
unit / golden / integration test tiers. Details: ARCHITECTURE_MAP §B.

---

## Template

```markdown
### D-NNN — Title
- **Date:**
- **Decision:**
- **Reason:**
- **Alternatives considered:**
- **Consequences:**
- **Status:**
- **Revisit trigger:**
```
