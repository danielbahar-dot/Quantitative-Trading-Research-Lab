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
- **Update 2026-10-03:** clarified and extended by **D-134** (the complete
  Daily H/L, the 4H candidate-only rule, the Previous Day reference, and
  the session allowlist). The text above is kept as the historical record.

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
- **Update 2026-10-03:** (b) and (c) are refined by **D-133**.
  - External and Internal Liquidity are designed as separate static
    milestones, with a shared lifecycle designed after both.
  - Liquidity and swing structure are generic market-structure primitives,
    not ICT features.
  - (a) is unchanged: there is still no cross-contract liquidity before
    roll handling.

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
- **Status:** REVISED by D-123 (2026-09-29). D1 is no longer a prerequisite
  for M5–M7 or the ICT feature library, and it is now DEFERRED. The finding
  and gate rationale above remain valid.
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

### D-123 — D1 deferred; continuity-aware feature work may proceed
- **Date:** 2026-09-29
- **Decision:**
  1. **D1 (contract stitching / source-data repair + holiday calendar) is
     DEFERRED** until continuous-history research requires it. It is not
     implemented, and no source data is modified.
  2. **M5** Generic Market Context, **M6** Generic Level Interactions,
     **M7** State/Signal Contracts, and later reusable feature-library work
     (including ICT) **may proceed before D1**.
  3. **Known limitation.** The current roll gaps are a known source-data
     limitation. Feature code must not silently work around them.
  4. **Continuity-aware generic components.** Generic components must:
     - never substitute an older available session for a missing expected
       session;
     - when an expected input session is absent, expose the feature as
       unavailable with an explicit reason;
     - never implicitly carry multi-session state across missing expected
       sessions;
     - never aggregate across mixed contracts.
  5. **D1 remains a required gate before:**
     - research assuming continuous history across contract rolls;
     - final broad strategy-performance validation where roll periods
       matter;
     - carrying cross-session or cross-contract structures through known
       source-data gaps;
     - any methodology requiring a canonical stitched continuous contract.
  6. **Frozen ORB is unchanged.** Its previous-available-session behavior
     around roll gaps remains a documented historical limitation (D-121).
- **Reason:** Design-authority decision. Reusable primitives can be built and
  validated correctly on gapped data if continuity is explicit. Stitching is
  only essential where continuous history is assumed.
- **Alternatives considered:** Keep D1 as a gate before M5 (D-120, superseded
  in part).
- **Consequences:**
  - M5 is NEXT.
  - Continuity-awareness is a required review item (QUALITY_CONTROL §1–2).
  - M3/M4 already comply for aggregation: mixed-contract buckets raise, and
    empty buckets are not synthesized.
  - D-113 (previous *expected* session; missing ≠ closure) is the governing
    rule for Previous Day in M5.
  - Because the calendar is still empty, an absent expected session cannot
    be verified as a legitimate closure. It must surface as unavailable or
    unverified, never be skipped.
- **Status:** ACTIVE
- **Revisit trigger:** Research that needs continuous history across rolls,
  or final performance validation over roll periods.

### D-124 — Generic Market Context library (M5A)
- **Date:** 2026-09-29
- **Decision:** Generic Market Context lives in
  `src/features/session_context.py` with the registry
  `config/features/market_context_windows.json`. Full specification:
  [M5_MARKET_CONTEXT_SPEC](M5_MARKET_CONTEXT_SPEC.md).
  - **Generic contexts:** `previous_day`, `previous_rth`, `asia_2000_0000`,
    `london_0200_0500`, `overnight_1800_0700`,
    `overnight_context_2000_0900`, `ny_premarket_0700_0900`.
  - **Generic ≠ ORB-only.** A concept is not ORB-specific because ORB uses
    it. **Previous Day, Previous RTH and `overnight_context_2000_0900` are
    generic.** ORB compatibility definitions exist only where frozen ORB
    semantics genuinely differ (M5B).
  - **Previous RTH** uses the existing validated definition, confirmed
    unambiguous from repository evidence: 09:30→16:00 ET, bar-ends
    09:31…16:00 (390), close = the 16:00 bar, available at 16:00 of the
    source session.
  - **Registry shape:** clock windows with explicit day offsets for both
    ends, plus contexts pairing a window with a `TARGET` or
    `PREVIOUS_EXPECTED` source session. Previous Day is code-defined as the
    full previous expected session.
  - **Canonical 1m source**, not the M4 cache.
  - **Strict completeness.** Verified overrides clip the window
    (`is_schedule_clipped`); zero scheduled minutes gives `NOT_SCHEDULED`;
    an unverified early end is `INCOMPLETE_WINDOW`.
  - **Summary reasons,** by precedence: `INSUFFICIENT_HISTORY`,
    `INSUFFICIENT_FUTURE_COVERAGE`, `MISSING_EXPECTED_SESSION`,
    `NOT_SCHEDULED`, `NO_OBSERVATIONS`, `MIXED_CONTRACT`,
    `INCOMPLETE_WINDOW`. `calendar_verified` is metadata only.
  - **Three tiers:** audit summary (`observed_*` only), valid levels
    (available only), and bar alignment.
  - **Alignment statuses:** `AVAILABLE`, `PENDING`, `UNAVAILABLE_CONTEXT`,
    `CONTRACT_MISMATCH`. Visibility requires `bar_start ≥ available_at`.
    Scope is the target session only. A contract mismatch hides the value
    but leaves the summary valid.
  - **Previous Day / Previous RTH** select the previous **expected**
    session and never fall back.
- **Reason:** Design-authority M5A instruction (2026-09-29).
- **Alternatives considered:** Classifying Previous RTH /
  `overnight_context_2000_0900` as ORB-only (rejected: strategy-independent);
  computing from the M4 cache (rejected: canonical 1m is the source of
  truth); a single reason covering alignment states (rejected: summary
  validity ≠ consumer compatibility).
- **Consequences:**
  - The DEVELOPMENT read-only check shows exact frozen-ORB parity for Asia,
    London, NY pre-market and Overnight Context.
  - Previous Day and Previous RTH differ from ORB only on the 6 intentional
    D-121 dates.
  - ORB is not rewired. M5B (compatibility and migration) is separate.
- **Status:** ACTIVE. **M5A APPROVED / FROZEN** (2026-09-30).
  - Visual validation, the semantic audit
    (`MISSING_EXPECTED_SESSION` vs `NO_OBSERVATIONS`), and all
    causal / contract / session invariants passed.
  - M5B is optional compatibility work and does not block the generic
    catalog.
  - Semantic changes require a new `definition_version`.
- **Revisit trigger:** M5B, a verified holiday calendar, or D1.

### D-125 — ORB consumes the generic Market Context catalog (M5B)
- **Date:** 2026-09-30
- **Decision:** The generic catalog (D-124) is the authority for market
  context. Frozen ORB V0.2 consumes it through
  `src/experiments/orb_market_context_compat.py`.
  - **Identical definitions are reused directly:** Asia, London, NY
    pre-market, `overnight_context_2000_0900`, and the Previous RTH window.
  - **Compatibility exists only for genuine historical differences:**
    - `orb_overnight_1800_0930`, in the separate
      `config/features/market_context_compatibility.json`;
    - `previous_available_session_legacy_orb`, the legacy
      previous-AVAILABLE selection for Previous Day / RTH;
    - a thin schema adapter to frozen ORB's `summarize_window` output
      (legacy availability = completeness).
  - **One evaluation engine:** `evaluate_context` is exposed from the generic
    module with a pluggable source session. There is no duplicated
    aggregation.
  - **Input contract:** ORB context inputs are now validated by the CME
    session model. Three synthetic ORB test fixtures using Sunday dates were
    moved to weekdays, with assertions unchanged (design-authority choice
    over a looser bypass).
- **Reason:** Remove duplicated ownership of generic market facts from ORB
  while keeping frozen research reproducible.
- **Alternatives considered:**
  - Keep ORB's own window computation (rejected: duplicate ownership).
  - Switch ORB to generic semantics (rejected: changes frozen results).
  - Bypass the session model for ORB (rejected: a looser second path).
- **Consequences:**
  - DEVELOPMENT parity is exact against both the pre-migration
    implementation (744 × 474) and the frozen oracle, whose SHA-256 is
    recorded in the M5 spec §11.
  - M5A generic output is unchanged.
  - The retained `market_context.py` window helpers serve only the ORB
    opening range, the ORB audit, and the tests.
  - Market Context migration is complete; M6 is next.
- **Status:** ACTIVE (implemented 2026-09-30)
- **Revisit trigger:** An ORB reopening; any change to the catalog
  definitions that ORB maps to (the drift guard will fail).

### D-126 — M6 level-interaction design decisions (spec rev 2)
- **Date:** 2026-09-30
- **Decision:** For the generic, stateless per-bar Level Interaction catalog
  (`docs/project/M6_LEVEL_INTERACTIONS_SPEC.md`):
  1. **Far-side interactions are supported** via a per-bar `approach_side`
     (`BELOW` / `ABOVE` / `AT`, from the bar open) and `approach_relation`
     (`ORIGINAL_SIDE` / `FAR_SIDE`). The level `orientation` stays semantic
     and immutable, never inferred.
  2. **Gaps.** A bar opening beyond a level is not itself a TOUCH or
     TRADE_THROUGH. If it returns to the level, that is a far-side
     interaction. `GAP_THROUGH` is deferred because it needs prior-bar
     state.
  3. **`NEUTRAL` orientation** covers genuinely non-directional reference
     levels. For NEUTRAL with `open == level`, no direction is invented; the
     row gets the explicit status `AMBIGUOUS_APPROACH`.
  4. **`valid_until`** (optional) is immutable applicability metadata, not
     lifecycle state.
  5. **Invalid input raises.** Schema, OHLC and input errors are never
     evaluator statuses.
  6. **Off-grid derived levels are allowed.** Bar prices must be on the tick
     grid. First tradable prices strictly above and below the level are
     computed with exact arithmetic (`f = floor(L/t)`, `c = ceil(L/t)`).
  7. **UPPER/LOWER `open == level`** counts as the original side. ORB's
     different `AT` behavior is preserved only in the M6B compatibility
     adapter, if parity requires it.
  8. **Explicit contract scope** (`SPECIFIC` / `AGNOSTIC`). A null contract
     is never silently treated as agnostic.
  9. **Measurements** are raw signed, unclipped
     `open/high/low/close_offset_ticks`.
- **Reason:** Design-authority answers to the M6 draft questions.
- **Consequences:**
  - ORB `start_side` equals the generic `approach_side`, so M6B's
    compatibility reduces to the legacy `AT` rule and schema mapping.
  - Evaluator statuses: `EVALUATED`, `AMBIGUOUS_APPROACH`, `PENDING_LEVEL`,
    `CONTRACT_MISMATCH`.
- **Status:** ACTIVE (implemented in M6A; ORB migrated in M6B, D-128).
- **Revisit trigger:** M6A validation findings; State-layer design
  (retests, `GAP_THROUGH`).
- **Update 2026-10-01:** final answers a/b/c applied, with `valid_until`
  completed by `valid_from` (D-127). M6A is implemented and validated.

### D-127 — Level applicability bounds: `valid_from` / `valid_until` (M6A)
- **Date:** 2026-10-01
- **Decision:**
  - `available_at` is the causal knowledge time.
  - `valid_from` and `valid_until` are optional, immutable static
    applicability bounds, not lifecycle state.
  - A bar is evaluated iff `bar_start ≥ max(available_at, valid_from)` and,
    when set, `bar_start < valid_until`. `bar_end ≤ valid_until` is **not**
    the generic end rule.
  - `PENDING_LEVEL` is emitted only for the confirming bar, and only when
    that bar itself lies inside the static window. This is enforced in the
    generic engine, not only by helpers.
  - M5-derived levels set `valid_from` / `valid_until` to the target trading
    session open / close.
- **Reason:** M6A DEV validation found `previous_rth` levels (available
  16:00 on D−1) evaluated on D−1 16:01–17:00 bars, outside their target
  session. Helper-only filtering was rejected.
- **Consequences:**
  - The output carries `valid_from` / `valid_until`.
  - Input validation raises if `valid_until < available_at` or
    `valid_until ≤ valid_from`.
  - DEVELOPMENT shows zero cross-target-session rows.
- **Status:** ACTIVE (implemented in `src/features/level_interactions.py`,
  M6A validated).
- **Revisit trigger:** level types with non-session applicability (swings,
  FVG) during State-layer design.

### D-128 — ORB consumes the generic Level Interaction catalog (M6B)
- **Date:** 2026-10-01
- **Decision:**
  - M6A (`src/features/level_interactions.py`) is the sole authority for
    level-interaction primitives.
  - Frozen ORB V0.2 consumes it through
    `src/experiments/orb_level_interaction_compat.py`. The legacy
    `market_context.level_interaction` is removed.
  - Aggregated OR-window evaluation is an **ORB consumer pattern**, not the
    generic primitive definition: one explicit aggregated bar, with
    `valid_from` / `valid_until` = the window and `available_at` = the
    window start (ORB's historical contract).
  - The **only compatibility rule** is open-at-level: `approach_side == AT`
    forces the four directional flags to False.
  - ORB distances, `available`, the schema and its order stay in the
    adapter. Stateful first-interaction logic stays in the London
    characterization script.
- **Reason:** Remove duplicated interaction mathematics while preserving
  frozen research exactly.
- **Consequences:**
  - Exact parity on all 234 `level_*` oracle columns (and all 474), with 0
    mismatches.
  - Removing the AT rule breaks 718 frozen rows; a test guards this.
  - Synthetic ORB / London test fixtures were snapped to the 0.25 tick grid,
    with assertions unchanged (design-authority choice).
  - M6 is complete; M7 is next.
- **Status:** ACTIVE.
- **Revisit trigger:** any new ORB work. It must use the generic API, not
  the adapter.

### D-129 — M7 State contract: event-based transition log (M7 spec rev 3)
- **Date:** 2026-10-01
- **Decision** (design-authority approval of
  `docs/project/M7_STATE_SIGNAL_CONTRACTS_SPEC.md` §0):
  1. State is a **generic envelope**. There is no global vocabulary, reset,
     persistence or SUSPENDED state; namespaces are module-owned.
  2. A **transition log** is canonical, and per-observation / per-bar views
     are derived.
  3. The core is **event / observation based**, with causal key
     `(at, seq)`:
     - strict `≺`;
     - same `at` without a reliable sequence is simultaneous and never
       ordered;
     - sequenced same-timestamp events may be ordered.
  4. `StateNamespaceSpec`:
     - fields: `namespace`, `entity_kind`, **required `initial_state`**,
       states, edges, terminals, version, typed `attr_*`;
     - **no creation transition**;
     - no self edges;
     - terminal states have no outgoing edges.
  5. A caller-provided **entity applicability frame** (`available_at[/seq]`,
     `valid_from`, `valid_until`, scope / contract). No state exists outside
     applicability.
  6. **One transition per entity + namespace + causal source event.**
     There are no same-event chains. Skip edges must be declared.
  7. `transition_at` / `available_at` (with optional sequences) are
     distinct. **The source observation that creates a transition cannot
     consume it.** Bars keep `bar_start ≥ available_at` through an explicit
     bar-boundary convention in the bar wrapper.
  8. Transition id = **full SHA-256** of the natural key (namespace,
     version, entity, previous / new state, transition key, canonical
     source refs).
  9. A typed `SourceRef(kind, key)`, not bar-specific, with no row numbers.
     M5 and M6 are unchanged.
  10. Utilities: `validate_transitions`, `state_as_of`,
      `materialize_state_to_observations` (the generic core) and
      `materialize_state_to_bars` (a wrapper) only.
- **Reason:** reusable, auditable State for future liquidity / FVG / swing
  modules without assuming 1-minute bars.
- **Consequences:**
  - M7A is implemented in `src/state/`.
  - M7B (Signals) follows the approved §11–§16 design, adjusted to the same
    causal key, SourceRef and identity rules.
- **Status:** ACTIVE.
- **Revisit trigger:**
  - the first real state module;
  - the first sequenced source, at which point the sequence domain (Q13)
    is decided.
- **Update:** the sequence domain was decided early, in D-130.

### D-130 — M7A validation amendments (spec rev 3.1)
- **Date:** 2026-10-01
- **Decision** (design-authority answers during M7A final validation;
  supersedes the matching parts of D-129 / rev 3):
  1. **Sequence domain now.**
     - Causal keys are `(at, seq_domain, seq)`, with domain and sequence
       co-null.
     - At equal `at`, ordering requires both sequences in the same domain;
       otherwise the keys are `EQUAL` (both unsequenced, or the same domain
       and sequence) or `INCOMPARABLE`.
     - Domain/sequence pairs exist on transitions, entities, observations
       and `state_as_of` queries.
     - The domain is part of identity.
  2. **Required `trigger_ref`** for the single causal source event.
     - `source_refs` is optional, canonicalized supporting provenance.
     - Only one transition is allowed per entity + namespace +
       `trigger_ref`.
     - The SHA-256 natural key includes `trigger_ref` and the canonical
       `source_refs`.
  3. **Strict consumers.**
     - `state_as_of` returns the state "available immediately before the
       query causal point", and `materialize_state_to_observations` is
       strict too; there is no inclusive mode.
     - The bar-boundary equality convention exists only in
       `materialize_state_to_bars`.
- **Reason:**
  - It prevents same-event consumption and the inference of order across
    feeds.
  - The causal event is identified explicitly.
- **Consequences:**
  - `validate_transitions` is causally strict. `decision_offset` initially
    affected only the static window check; it was later removed (D-131).
  - `materialize_state_to_bars` requires an explicit `bar_start` or
    `bar_interval`, with no 1-minute default.
- **Status:** ACTIVE.

### D-131 — `validate_transitions` does not re-evaluate trigger eligibility (spec rev 3.2)
- **Date:** 2026-10-01
- **Decision:**
  - `decision_offset` is removed. The signature is
    `validate_transitions(transitions, spec, entities) -> DataFrame`, with
    no source-duration parameter and no batch-level workaround.
  - `validate_transitions` validates the integrity, causality, provenance
    and replay consistency of the transition log. It does **not**
    independently re-evaluate whether the upstream trigger observation was
    eligible to interact with the entity; that is owned by the source
    feature / interaction module (M6 for bars, future modules for ticks).
  - Retained, because they hold for any observation type:
    - a well-formed entity applicability record;
    - entity identity, and instrument / scope / contract consistency;
    - entity availability `≺` transition key;
    - `transition_at ≥ valid_from`.
  - There is no upper-bound rule on `transition_at`.
  - Exact windows stay in `state_as_of` and the observation / bar
    materializers.
  - No `trigger_decision_at` field is added in M7A. It may be reconsidered
    only if a concrete second use case needs transition-level
    revalidation.
- **Reason:**
  - Observation geometry (tick time, or `bar_start = bar_end − interval`)
    belongs to the Feature / Interaction layer.
  - A scalar offset could not support mixed granularities.
- **Status:** ACTIVE.

### D-132 — M7B generic Signal contract (spec "M7B FINAL CONTRACT", B.0)
- **Date:** 2026-10-01
- **Decision:** A Signal is an immutable point event describing what
  happened, never a trade.
  - **`SignalDefinitionSpec`:**
    - `signal_type`, a required `subject_kind`, `definition_version`;
    - `allowed_directions`, a subset of BULLISH / BEARISH / NEUTRAL. Empty
      means the direction is null; otherwise it must be exactly one of the
      declared values;
    - typed `AttributeSpec` attributes, with forbidden execution names
      rejected.
  - **Row:**
    - `signal_id`, type and version, a free-form stable `subject_id`;
    - event and availability M7A causal keys;
    - instrument / scope / contract;
    - `direction`;
    - a required `trigger_ref` and optional `source_refs`, which must not
      overlap;
    - typed `attr_*` columns.

    There is no `reason_code` and no validity window.
  - **Causality.** It reuses M7A `CausalKey` / `compare_causal`: the event
    must be BEFORE or EQUAL to availability. A Signal may be created at the
    same causal event as a StateTransition it describes; consumption needs
    a later observation.
  - **Identity.** Full SHA-256 over type, version, instrument, scope,
    contract, subject, the event key, direction, `trigger_ref` and
    canonical `source_refs`. Availability and attributes are excluded.
  - **Uniqueness.** Duplicate ids are rejected, plus at most one Signal per
    semantic event key: identity minus provenance.
  - **Boundary.** `validate_signals` does not check trigger eligibility,
    subject resolution, cross-layer source timing, or strategy / execution
    eligibility. There is no materialization utility.
  - **Execution fields.** A finite forbidden list, checked directly and as
    `attr_*`.
  - **Errors.** `SignalContractError(ValueError)`; M7A errors are
    translated with chaining.
  - **Reuse.** Only public M7A primitives are reused, and M7A is not
    refactored.
- **Reason:** a reusable event envelope aligned exactly with the
  implemented M7A causal, provenance and identity model, with no execution
  semantics.
- **Status:** ACTIVE.

### D-133 — Generic Market Structure & Liquidity workstream (classification and naming)
- **Date:** 2026-10-03
- **Decision:**
  - External Liquidity, Internal Liquidity, EQ/REQ and Swing Structure are
    **generic, methodology-neutral market-structure primitives**, usable by
    mean-reversion, breakout, Wyckoff, SMC/ICT, order-flow, statistical and
    other families. They are **not** ICT features and are not placed under
    an ICT hierarchy or prefix.
  - **Roadmap 3, Generic Market Structure & Liquidity:**
    - 3.1 External Liquidity (static);
    - 3.2 Internal Liquidity (static);
    - 3.3 Swing Structure;
    - 3.4 Shared Liquidity Lifecycle, designed only after 3.1 and 3.2.
  - **Roadmap 4** is a separate, downstream methodology-specific family:
    FVG, IFVG, Order / Rejection / Mitigation Blocks, etc. MSS / BOS
    classification stays open.
  - There is no "M8A/M8B/M8C" naming, because 2.M8 / 2.M9 are taken. The
    spec file is `docs/project/EXTERNAL_LIQUIDITY_SPEC.md`.
- **Reason:**
  - These concepts are reused across strategy families.
  - The previous M-number naming collided with the roadmap.
- **Consequences:**
  - Refines D-103 / D-117 (b, c).
  - The branch name `m8a-external-liquidity-design` predates this decision
    and is not renamed.
- **Status:** ACTIVE.
- **Clarification 2026-10-03: sequencing.** The design authority
  subsequently changed the implementation **sequencing** to External →
  Swing → Internal → Shared Lifecycle:
  - 3.1 External Liquidity;
  - 3.2 Swing Structure;
  - 3.3 Internal Liquidity;
  - 3.4 Shared Liquidity Lifecycle.

  **Reason:**
  - Swing Structure is a generic primitive that Internal Liquidity may
    consume, alongside lower-timeframe EQ/REQ.
  - It must therefore be objectively defined and frozen before Internal
    Liquidity decides which swings qualify. Swings are not defined inside
    Internal Liquidity, and not every swing becomes liquidity.

  The generic classification above is **unchanged**, and no External
  Liquidity rule (D-134) changes. The decision list above keeps its
  original order as the historical record.
- **Clarification 2026-10-05: BOS / CHoCH classification (design review
  K-12).** This resolves the "MSS / BOS classification stays open" point
  above, for BOS and CHoCH only:
  - The **neutral swing-referenced Structure Break, BOS, CHoCH, Protected
    Swing and Structural Direction belong to Generic Market Structure.**
    They are methodology-neutral and consume Swing Structure 3.2. They
    are explicitly versioned classifications, not ICT features.
  - **MSS stays deferred.** That includes any displacement, FVG or
    liquidity dependency. Its generic-versus-methodology placement
    remains open.
  - The full design (approved semantics D1–D17 and the K-1 … K-14 design
    decisions) is in `docs/project/MARKET_STRUCTURE_SPEC.md`. It is a
    **design draft**: not approved as a whole, not implemented, not
    frozen.
  - D-numbers are registered when the design is approved, following the
    Swing precedent (P-SW → D-135–D-138).
- **Clarification 2026-10-05: Market Structure semantic review complete
  (rev 2.4).** The design authority approved:
  - **T-1:** same-close target admission after a failed establishment.
  - **CB-1, gap followed by a contract change:**
    - a `DATA_GAP` reset at the first missing observation's expected
      completion;
    - the contract change is recorded only when new-contract evidence
      exists, in the new episode's opening provenance;
    - the earlier reset is never retroactively modified.
  - **CB-2, pure contract change:**
    - reset at the first new-contract bar's close;
    - no new-contract observation is ever classified against
      old-contract state;
    - all state and references stay contract-specific.
  - No stitching, price adjustment or roll calendar is introduced.
  - **Status:** final design approval, D-number registration,
    implementation and freeze remain **pending**. Details are in
    `MARKET_STRUCTURE_SPEC.md` §K.2b–§K.2c.
  - **Update 2026-10-05:** the design is approved and registered as
    **D-139–D-142**. Implementation and freeze remain pending.

### D-134 — External Liquidity (static) final definition (clarifies D-104)
- **Date:** 2026-10-03
- **Decision** (full rules in `docs/project/EXTERNAL_LIQUIDITY_SPEC.md`):
  1. **Families.**
     - **(A)** Every **complete Daily** high/low is a standalone External
       Liquidity member, available at the Daily `bar_end`.
     - **(B)** Selected session/reference highs/lows: Asia, London, NY
       Pre-market and Overnight 18:00–07:00. `overnight_context_2000_0900`
       and `previous_rth` are excluded initially; Previous RTH may be added
       later as its own family.
     - **(C)** Daily EQ/REQ are **additional** structures over the existing
       Daily members.
     - **(D)** 4H EQ/REQ: an ordinary 4H high/low is only a **formation
       candidate**. It becomes a canonical member only when a later
       complete 4H bar confirms an EQ/REQ containing it. Then `source_at`
       is its own `bar_end`, and `available_at` is the first confirmation.
     - Future swing-based 4H liquidity is a separate path (Swing
       Structure).
  2. **Previous Day.** `previous_day` H/L is a **derived reference** to the
     canonical Daily member of the previous expected session, not a
     duplicate member. A price mismatch raises.
  3. **No price deduplication** across distinct session families.
  4. **EQ and REQ.**
     - EQ: exact (0 ticks).
     - REQ: ≤ 6-tick chain connectivity, members preserved, and ≥ 2
       **distinct** prices. A pure-equal component is EQ only.
     - Highs only with highs; integer ticks; no pivot or lookahead.
  5. **Pair-outer formation barrier.** No bar strictly between `i < j` has
     `high > max(p_i, p_j)` (UPPER) / `low < min(p_i, p_j)` (LOWER).
  6. **Continuity segments.** Same contract, no missing expected session,
     all bars complete. An incomplete bar is excluded **and** breaks the
     segment. The existing 4H buckets are used, including a complete
     14:00–17:00 bucket.
  7. **Two canonical tables.** `liquidity_members` (atoms) and
     `liquidity_structures` (EQ/REQ immutable content-addressed versions:
     FORMED / EXTENDED / MERGED, `supersedes`). There is no join table, no
     singleton structure rows, and no survivor or lineage id. Change kinds
     are static history, not lifecycle.
  8. **Identity** is full SHA-256: `lm_` (source identity, independent of
     availability) and `ls_` (sorted member ids). `SPECIFIC` contract
     scope. Fail closed on missing data.
  9. **Out of scope:** lifecycle, Signals, Internal Liquidity, Swing
     Structure, M6 integration.
  10. Sparse Daily EQ/REQ on DEVELOPMENT is a data-coverage limitation. The
      definition is not weakened.
- **Reason:** design-authority final design, 2026-10-03.
- **Status:** ACTIVE (design approved). **Implementation status
  2026-10-03:** implemented as specified, with no new semantic decision
  (spec §18). Visual / design-authority validation is pending; not frozen.
  (Superseded by the 2026-10-04 freeze note below.)
- **Clarification 2026-10-03: expected-bucket continuity.**
  - Row adjacency is not continuity; M3 emits no row for empty buckets.
  - A segment needs every **expected** observation present, every
    observation complete, and an unchanged contract. Both an incomplete
    expected bucket and an absent expected bucket (no row) break it.
  - **1D:** continuous only if both bars are complete, the contract is
    unchanged, and the later date's previous expected session is the
    earlier date.
  - **4H:** continuous only if the later bar is the **next expected
    bucket** under the existing M1/M3 schedule. That schedule is anchored
    at the regular open and clipped to the actual (override-applied)
    session bounds, and it continues to the first bucket of the next
    expected session. It is not "+4h" and not a hard-coded six-bucket day.
    This is a check over M3 outputs, not a new aggregator.
  - **Tests:** the eight synthetic continuity tests are required at
    implementation (spec §4).
  - **Implementation note:** a small additive public schedule helper in
    `src/data/timeframes.py` (reusing M3's private schedule logic) is
    recommended, and will be authorized with the implementation task.
  - No other External Liquidity decision changes.
- **Implementation / freeze note 2026-10-04.**
  - The work is complete:
    - implementation (`src/liquidity/contract.py`,
      `src/features/external_liquidity.py`);
    - programmatic validation;
    - visual and design-authority review, including the pre-freeze
      contract/audit/visual quality corrections in spec §18.
  - **External Liquidity 3.1 is APPROVED / FROZEN.**
  - **Frozen canonical DEVELOPMENT counts:**
    - 2,553 members and 86 structures;
    - 438 Previous Day references (0 mismatch);
    - 3,326 candidates, 50 continuity breaks, 412 barrier blocks;
    - 169 promoted 4H members;
    - FORMED 84 / EXTENDED 2 / MERGED 0;
    - all invariants 0.
  - No Daily EQ/REQ on DEVELOPMENT is a data-coverage limitation, not a
    semantic exception.
  - Full suite: 543 passed / 0 failed / 382 subtests.
  - Any future semantic change to these rules requires a new decision.
    Refactoring must preserve frozen parity.

### D-135 — Canonical causal Swing Structure
- **Date:** 2026-10-04
- **Decision** (promoted from P-SW-1; full rules in
  `docs/project/SWING_STRUCTURE_SPEC.md` rev 3). The Swing is a
  plateau-aware confirmed pivot / local extremum:
  - **Plateau.** A Swing plateau is a maximal sequence of consecutive
    expected source observations within one continuity segment whose
    relevant extreme (UPPER: high; LOWER: low) is exactly equal on the
    instrument tick grid.
    - It is only the source representation of one swing fact. It is not
      consolidation, range, balance or liquidity.
    - It may span an expected session boundary, a maintenance interval or
      a weekend transition. Any actual continuity break terminates it.
  - **Candidate.** No value in the `left_depth` observations before the
    plateau is strictly greater (lower, for LOWER).
  - **Confirmation.** No value in the `right_depth` observations after it
    is strictly greater (lower). Both windows lie in the same segment.
  - **Equality.** Equality outside the plateau never invalidates.
    Separated equal extremes are independent swings; EQ / REQ is
    downstream.
  - **Depths.** `left_depth ≥ 1` and `right_depth ≥ 1` are always supplied
    explicitly, with no implicit default. 2/2 is the explicit reference
    configuration for validation, audits, visuals and regression baselines
    on every timeframe. It is not a preferred scale, and depths are never
    optimized with PnL.
  - **Timing.** `source_at` = completion of the first plateau bar;
    `source_end_at` = completion of the last; `available_at` = completion
    of the final required right-confirmation bar.
  - **Invariant.** `source_at ≤ source_end_at < available_at`: equality on
    the left for a single bar, strict for a multi-bar plateau.
  - **Facts.** Confirmed, immutable facts only. `SPECIFIC` contract scope.
    Fail-closed expected-schedule continuity. Complete session-truncated
    bars are valid. Candidate history is audit-only, with exact labels not
    frozen.
  - **Timeframes.** Identical semantics on 1m (canonical source bars) and
    on 5m, 15m, 1H, 4H and 1D (M3 bars).
- **Reason:** the design-authority-approved Swing Structure 3.2 design (spec
  rev 1–3, DEVELOPMENT design evidence in spec §23).
- **Status:** ACTIVE. The Swing Structure 3.2 implementation is
  **APPROVED / FROZEN (2026-10-05)**.
- **Freeze note 2026-10-05:** implemented (SW-I0 to SW-I3), machine
  validation passed (all gates), and the human visual review passed.
  - **Frozen facts:**
    - 1m / 5m / 15m / 1H / 4H / 1D with one detector;
    - canonical 1m directly, M3 for 5m–1D;
    - explicit 2/2 reference validation definition (not a default, not
      optimized, not a universal scale);
    - DEVELOPMENT total 119,381 swings;
    - fingerprint
      `b6876266800d56b3421dbfb5e4a4aa50b83140acdd409390d28b5f75427c218f`;
    - full suite 647 passed / 0 failed / 493 subtests.
  - The decision text is unchanged. Future semantic changes require a new
    decision.
- **Implementation note 2026-10-04 (SW-I2):** implemented, validated and
  design-authority approved; committed on the active Swing implementation
  branch.
  - The generic detector `build_swing_points` is in
    `src/market_structure/swing_detector.py`. It is one algorithm for 1m /
    5m / 15m / 1H / 4H / 1D (direct canonical 1m; M3 for 5m–1D).
  - SW-I3 (audit, DEVELOPMENT baseline, visual validation) is complete;
    see the freeze note above. The decision text is unchanged.

### D-136 — Timeframe independence and causal projection
- **Date:** 2026-10-04
- **Decision** (promoted from P-SW-2):
  - The swings of a timeframe depend only on that timeframe's bars,
    definition, continuity and contract history.
  - A confirmed HTF swing may be referenced by an LTF bar consumer only
    when HTF `available_at ≤` LTF `bar_start`. Event consumers obey the M7
    strict causal rule.
  - The same `swing_id` is referenced. There are no LTF copies, no
    parent/child links, no strength or hierarchy, and no interpretation or
    liquidity columns.
- **Reason:** determinism, independent testing and no hidden HTF
  dependency. DEVELOPMENT evidence: keying on HTF `source_at` would leak
  the HTF classification about 10 h (4H) or about 2 h (1H) early (spec
  §23).
- **Status:** ACTIVE — DESIGN APPROVED.
  - SW-I2 implements per-timeframe-independent detection (no
    cross-timeframe input). It is part of the APPROVED / FROZEN Swing
    Structure 3.2 (2026-10-05).
  - Cross-timeframe projection is a downstream concern and is not
    implemented.

### D-137 — Shared expected-schedule continuity extraction
- **Date:** 2026-10-04
- **Decision** (promoted from P-SW-3):
  - The first implementation prerequisite is a small generic module
    `src/data/continuity.py`. It provides:
    - expected-schedule segmentation;
    - missing expected bucket and missing expected session;
    - incomplete observation and contract change;
    - the existing break precedence;
    - the generic `ContinuityError`.
  - It must not depend on External Liquidity, Swing Structure, liquidity
    contracts or strategy concepts.
  - External may keep a compatibility re-export or wrapper and translate
    `ContinuityError` to `ExternalLiquidityError`.
  - Exact frozen External parity is required (members 2,553, structures
    86, Previous Day references 438, candidates 3,326, continuity breaks
    50, barrier blocks 412), together with the existing tests and a full
    regression.
- **Reason:** Swing Structure is the second real consumer of the
  expected-schedule continuity first proven in External Liquidity (D-134).
- **Status:** ACTIVE — DESIGN APPROVED.
  - The SW-I0 implementation is merged and complete (commit `0087e5d`;
    PR #12 merged into `main` at `3b098f5`), with exact External parity
    proven.
  - Swing Structure 3.2 is APPROVED / FROZEN (2026-10-05).
- **Implementation note 2026-10-04 (SW-I0):** implemented, validated,
  design-authority approved and merged (PR #12, `3b098f5`).
  - `src/data/continuity.py` holds `continuity_segments`, the break
    vocabulary, `BREAK_PRECEDENCE` and `ContinuityError`. The logic is
    extracted unchanged from External.
  - External keeps a compatibility wrapper and re-exports, and translates
    `ContinuityError` to `ExternalLiquidityError`.
  - Frozen External parity is exact on DEVELOPMENT (2,553 / 86 / 438 /
    3,326 / 50 / 412). The regenerated External validation CSVs are
    identical.
  - The decision text is unchanged.

### D-138 — Canonical Swing table and identity
- **Date:** 2026-10-04
- **Decision** (promoted from P-SW-4):
  - The canonical table is `swing_points`, with orientation
    `UPPER` / `LOWER`. Its columns are:
    - `swing_id`, `orientation`, `timeframe`, `price`;
    - `source_ref`, `source_at`, `source_seq_domain`, `source_seq`,
      `source_end_at`;
    - `available_at`, `available_seq_domain`, `available_seq`;
    - `instrument_id`, `contract_scope`, `contract`;
    - `left_depth`, `right_depth`, `definition_version`.
  - Builder input is a small `SwingDefinitionSpec(definition_version,
    left_depth, right_depth)`. The equality / plateau policy is fixed by
    `definition_version`. Depths are persisted on rows, and there is no
    registry.
  - The canonical source ref is
    `BAR_SPAN:<instrument_id>|<contract>|<timeframe>|<first_bar_end_utc>|<last_bar_end_utc>`,
    using the canonical UTC serialization. For one source observation,
    `first_bar_end_utc == last_bar_end_utc`. It contains no orientation,
    price, depth, `available_at` or classification. External's `HTF_BAR`
    refs are unchanged.
  - `swing_id` = `sw_` + full SHA-256 over `definition_version`,
    `instrument_id`, `contract_scope`, `contract`, `timeframe`,
    `orientation`, `left_depth`, `right_depth` and the canonical
    `BAR_SPAN` `source_ref`. It excludes price, `available_at`, candidate
    audit status, HTF / LTF context and liquidity interpretation.
- **Reason:** a minimal, stable canonical fact. Identity is source-based
  and independent of confirmation timing, consistent with liquidity member
  identity (D-134).
- **Status:** ACTIVE. Part of the APPROVED / FROZEN Swing Structure 3.2
  (2026-10-05).
- **Implementation note 2026-10-04 (SW-I1):** implemented, validated and
  design-authority approved; committed on the active Swing implementation
  branch.
  - The contract is implemented in `src/market_structure/swing.py`:
    `SwingDefinitionSpec`, `SWING_COLUMNS`, `bar_span_ref`, `swing_id`,
    `assign_swing_ids` and `validate_swing_points`.
  - There is no detection yet. The decision text is unchanged.

### D-139 — Neutral Structure Break and BOS / CHoCH classification
- **Date:** 2026-10-05
- **Decision** (full rules in `docs/project/MARKET_STRUCTURE_SPEC.md`;
  final review at `1b6d221f5b819a017940f7d3200352e6a76f96c4`):
  - **Structure Break.** The first completed observation, in the swing's
    own continuity segment with `bar_start ≥ swing.available_at`, whose
    close is **strictly** beyond the swing price in exact ticks.
    - Wicks and equality never break.
    - A breach belongs to the `swing_id` and is permanent.
    - Later equal-price swings are independent.
  - **Evidence.** It is computed natively (`swing_breaks`, `sb_` ids) from
    actual bar geometry. Frozen M6 is unchanged, because its
    `close_through` is approach-relative and it assumes fixed-length bars.
  - **Classification.** BOS (a close beyond the active TARGET) and CHoCH (a
    close beyond the active PROTECTION) are explicitly versioned Generic
    Market Structure classifications.
    - Event direction is the break direction, with pre / post direction
      recorded.
    - No opposite establishment is implied.
  - **MSS** stays deferred.
- **Reason:** a methodology-neutral, causal, reproducible break primitive
  consuming frozen Swing Structure (D-135–D-138).
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Generic Market Structure (2026-10-06; merged via PR #14, `434d919`).
- **Implementation note 2026-10-05 (MS-I1 – MS-I3):** implemented on `market-structure-design`
  (`src/market_structure/{swing_breaks,structure,structure_audit}.py`, DEVELOPMENT runner
  `src/experiments/market_structure_dev_validation.py`). **MACHINE VALIDATION PASSED; HUMAN VISUAL APPROVAL PASSED (2026-10-06).** The decision text is unchanged.

- **Freeze note 2026-10-06 (Generic Market Structure, D-139 – D-142):**
  - Implemented MS-I1 to MS-I3, merged to `main` via PR #14 (merge commit
    `434d919`).
  - Machine validation passed (all 10 gates). Human visual review passed on
    20 cases (15 REAL DEVELOPMENT, 5 SYNTHETIC).
  - Full suite: 702 passed / 0 failed / 493 subtests.
  - **Frozen DEVELOPMENT baseline:**
    - definition `structure-v1` / `swing-break-v1` over the 2/2 `swing-pivot-v1`
      reference;
    - replay cutoff 2025-06-30 17:00 ET;
    - INV-1 … INV-17 = 0 on every timeframe;
    - 0 anomalies.

    | tf | swings | breaks | episodes | event_id SHA-256 | role_id SHA-256 |
    |---|---|---|---|---|---|
    | 1m | 93335 | 90199 | 33 | b34169379d5c44bd… | bd309e5f11cf8807… |
    | 5m | 18158 | 16783 | 32 | 74f85aa49b6a13d8… | 10d6b5d5081d7b2b… |
    | 15m | 6037 | 5269 | 31 | 1a3c962c09e4af43… | ee1195006646d553… |
    | 1H | 1452 | 1102 | 29 | 986aca1d5c522916… | 3a6222df0218179e… |
    | 4H | 367 | 215 | 29 | 2c79e6f1d5b5e5ab… | 8e4001f3677e4ed6… |
    | 1D | 32 | 10 | 23 | fa741ccbececa209… | d53669f3e5875c55… |

    - The full per-timeframe fingerprints (episode, role, event and
      break_id) are in `reports/validation/market_structure_dev_summary.csv`.
    - Overall fingerprint = SHA-256 of the 24 per-timeframe identity values,
      ordered by timeframe (1m, 5m, 15m, 1H, 4H, 1D) then by `episode_id`,
      `role_id`, `event_id`, `break_id`, joined by newlines:
      `03f0a2d92679c56f97600c6e54934a38b5f86981e60266befbf2bb5f2a05163d`.
  - The decision texts of D-139 – D-142 are unchanged. Future semantic changes
    require a new decision.

### D-140 — Structural Direction, Protected Swing and causal selection
- **Date:** 2026-10-05
- **Decision** (spec §E):
  - **Directions:** UNDEFINED / BULLISH / BEARISH, with no direct
    BULLISH↔BEARISH edge.
  - **Establishment** requires:
    - a close beyond the candidate target;
    - with the deepest pullback after it strictly beyond the anchor;
    - and, after a CHoCH, that pullback must be fresh
      (`source_at > e(X)`).
    - The deepest is chosen first; a stale or non-qualifying deepest
      blocks.
  - **Failure:** the target is retired, the anchor is kept, and the side
    waits.
    - A target confirmed at the failing close may be assigned in the same
      batch, but never classifies that close (T-1).
  - **BOS** consumes the target and replaces protection only with a
    different, strictly tighter deepest pullback. Otherwise the same
    protection entity is retained.
  - **CHoCH** returns the direction to UNDEFINED and rescopes historical
    reuse to `source_at ≥ broken_protection.source_at`.
  - **Selection** is a deterministic rescan:
    - anchors and targets: the most extreme, then first eligible;
    - pullbacks: the deepest, then earliest source.
  - **Since-expansion targets:** straddlers are included; progression is
    strict versus the consumed baseline.
  - **Dual qualification** is argued unreachable. It falls back to
    anomaly evidence and fails validation.
- **Reason:** the D1–D16 handoff semantics as refined by design review
  K-1 … K-4, K-7, K-8, K-11, N-1, T-1 and the rev 2.2 corrections.
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Generic Market Structure (2026-10-06; merged via PR #14, `434d919`).
- **Implementation note 2026-10-05 (MS-I1 – MS-I3):** implemented on `market-structure-design`
  (`src/market_structure/{swing_breaks,structure,structure_audit}.py`, DEVELOPMENT runner
  `src/experiments/market_structure_dev_validation.py`). **MACHINE VALIDATION PASSED; HUMAN VISUAL APPROVAL PASSED (2026-10-06).** The decision text is unchanged.

### D-141 — Structure state representation, identity and provenance
- **Date:** 2026-10-05
- **Decision** (spec §C, §F):
  - **Episodes** are M7A `structure.direction` entities.
  - **Each role assignment** (anchor, candidate target, protection,
    target) is a separate `structure.role` entity:
    - a candidate target's parent is its anchor assignment;
    - a protection's parent is its promotion event;
    - a target's parent is its expansion leg.
  - **Batch post-close processing per observation:**
    1. classify against the pre-state;
    2. breaches;
    3. admissions;
    4. rescan;
    5. a set-based diff.
    - No entity is created and exited at one timestamp.
    - Each transition has one trigger: the observation `BAR_SPAN`, or the
      reset's `CONTINUITY_BREAK`.
  - **Identity:** natural ids (`sb_` / `se_` / `sr_` / `sx_`) are kept
    separate from `run_id` and `fact_hash`. Facts are pinned, and
    revisions create new runs.
- **Reason:** design review K-10, K-13, N-3 and N-5; M7A compatibility.
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Generic Market Structure (2026-10-06; merged via PR #14, `434d919`).
- **Implementation note 2026-10-05 (MS-I1 – MS-I3):** implemented on `market-structure-design`
  (`src/market_structure/{swing_breaks,structure,structure_audit}.py`, DEVELOPMENT runner
  `src/experiments/market_structure_dev_validation.py`). **MACHINE VALIDATION PASSED; HUMAN VISUAL APPROVAL PASSED (2026-10-06).** The decision text is unchanged.

### D-142 — Structure lifecycle, resets and contract boundaries
- **Date:** 2026-10-05
- **Decision** (spec §G):
  - **Gap resets** (`DATA_GAP`) happen at the expected completion of the
    first missing or incomplete observation (scheduled replay). Scheduled
    closures never reset.
  - **CB-1, gap followed by a contract change:**
    - `DATA_GAP` reset at the gap onset;
    - the change is recorded only when new-contract evidence exists, in
      the new episode's opening provenance (`opening_ref`,
      `previous_contract`, `opening_contract_changed`,
      `opening_contract_change_ref`);
    - the reset is never retroactively modified.
  - **CB-2, pure contract change:**
    - reset at the first new-contract bar's close;
    - no cross-contract classification;
    - everything contract-specific.
  - **Reset-detection adapter (spec §G.2a).** Resets are detected from the
    M3 expected schedule up to an explicit, required `replay_cutoff`
    recorded in the run manifest.
    - Frozen continuity (D-137) is unchanged and remains the segmentation
      authority, checked fail-closed for agreement.
    - Its retrospective break rows supply only the opening provenance at
      `first_bar_end`.
    - Trailing gaps reset without a break row.
  - **Prefix equivalence:** a run at cutoff `C1` equals any later-cutoff
    run restricted to `available_at ≤ C1`, including inside gaps.
  - **Not introduced:** stitching, price adjustment or a roll calendar.
- **Reason:** design review K-5, CB-1 and CB-2, plus the final-review
  clarification of the gap-reset adapter (rev 2.5).
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Generic Market Structure (2026-10-06; merged via PR #14, `434d919`).
- **Implementation note 2026-10-05 (MS-I1 – MS-I3):** implemented on `market-structure-design`
  (`src/market_structure/{swing_breaks,structure,structure_audit}.py`, DEVELOPMENT runner
  `src/experiments/market_structure_dev_validation.py`). **MACHINE VALIDATION PASSED; HUMAN VISUAL APPROVAL PASSED (2026-10-06).** The decision text is unchanged.

### D-143 — Shared liquidity consumption contract
- **Date:** 2026-10-06
- **Decision** (`docs/project/INTERNAL_LIQUIDITY_DESIGN.md` rev 4 §3.1;
  IL-D0, IL-D1/2, IL-D12, OI-1, A-19):
  - **One narrow, shared consumption predicate** is used by Internal
    Liquidity and by a derived lifecycle view over frozen External objects.
    The broader 3.4 lifecycle stays deferred, and frozen formation facts are
    unchanged.
  - **Observation.** Canonical 1m bars. Bar `m` uses the object version
    available at `s(m)`. Consumption is recorded at `e(m)`, with no intrabar
    order.
  - **Threshold.** UPPER `θ = p + t`, LOWER `θ = p − t`. Consumption requires
    strict penetration (`h > θ` / `l < θ`); equality never consumes.
  - **Tolerances `t`:**
    - Internal 1H candle, 5m / 15m / 1H swing, EQ and REQ: 4 ticks.
    - External Daily / 4H standalone, EQ and REQ: 6 ticks.
    - EQ formation stays exact.
  - **Clusters** are consumed beyond their current definitive price plus
    tolerance. A within-tolerance excursion contributes only after a
    qualifying confirmation, and later confirmation never undoes
    consumption.
  - **Boundary assignments** are consumable objects pinned to one version,
    evaluated independently of their live cluster.
  - **Evidence:** the consuming bar ref, o / h / l / c, `p`, `t`, `θ`,
    excess ticks, gap-through, and the version evaluated.
- **Reason:** design-authority approval of rev 4, 2026-10-06.
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Internal Liquidity (2026-10-07; merged via PR #16).

### D-144 — Internal formation atoms
- **Date:** 2026-10-06
- **Decision** (rev 4 §3.2; IL-D6/7/8, OI-1):
  - Internal atoms reuse the frozen `liquidity_members` /
    `liquidity_structures` envelope with `liquidity_class = INTERNAL`.
  - **Families:**
    - complete 1H candle highs / lows;
    - confirmed swings on 5m, 15m and 1H, using the explicit frozen
      `swing-pivot-v1` 2/2 definition;
    - EQ / REQ clusters of confirmed swings, per side and timeframe.
  - **Cluster grammar:** D-134 at the internal grain:
    - EQ exact;
    - REQ link ≤ 4 ticks with chain connectivity and ≥ 2 distinct prices;
    - pair-outer barrier on the timeframe's bars;
    - one continuity segment and contract;
    - immutable FORMED / EXTENDED / MERGED versions, never back-dated.
- **Reason:** design-authority approval of rev 4, 2026-10-06.
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Internal Liquidity (2026-10-07; merged via PR #16).

### D-145 — Internal levels, price records and grading
- **Date:** 2026-10-06
- **Decision** (rev 4 §3.3 – §3.5; IL-D9/10/11, OI-2, OI-6):
  - **Definitive price:** a single source's price; the common exact price
    for EQ; the outermost constituent for REQ.
  - **One active internal level per (contract, side, price).** It
    consolidates coincident candidates with multiple evidence references.
  - **Identity:** `il_` anchored on the first evidence. A level is terminal
    after consumption or termination. A genuinely new formation creates a
    new id at the same price.
  - **Versions:** immutable and prospective.
  - **Price records.** Coincident internal and External objects share one
    actionable price record (`lp_`) but keep separate lifecycles and
    thresholds. Valid internal membership is not suppressed.
  - **Confluence** counts distinct physical extremes once.
  - **Grades:** an attribute profile with ordered tiers, timeframe first,
    then family. Within a timeframe: ordinary H/L < REQ < EQ. Within 1H:
    candle < swing < REQ < EQ. Proximity and direction are excluded.
- **Reason:** design-authority approval of rev 4, 2026-10-06.
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Internal Liquidity (2026-10-07; merged via PR #16).

### D-146 — External ranges and pinned boundary assignments
- **Date:** 2026-10-06
- **Decision** (rev 4 §3.6; IL-D3/4/5, OI-4, OI-5, A-19):
  - **Boundary candidates:**
    - External Daily H/L member objects;
    - External 4H / Daily EQ / REQ cluster lineages (`xc_`), priced at
      their current version.
  - **Establishment:** the closest eligible candidates. The upper side may be
    unbounded; with no lower, the status is `INSUFFICIENT_BOUNDARY_DATA`.
  - **Pinned assignments (`ba_`).** A selected boundary is pinned to its
    formation version, price and threshold. Cluster extensions and merges
    never move it.
  - **At an assignment-consumption event:**
    - the consumed side advances outward to the closest eligible candidate
      beyond the pinned price;
    - the opposite side is reselected to the closest eligible candidate only
      if strictly closer, and otherwise retained;
    - there is no reselection between events.
  - **Membership:** strictly inside the pinned boundaries; equality is
    excluded; historical, known, unconsumed levels qualify.
- **Reason:** design-authority approval of rev 4, 2026-10-06.
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Internal Liquidity (2026-10-07; merged via PR #16).

### D-147 — Internal Liquidity lifecycle, gaps, causality and outputs
- **Date:** 2026-10-06
- **Decision** (rev 4 §3.7 – §3.9; IL-D13/14, OI-3):
  - **Data gaps** (the 1m §G.2a onset) terminate every affected level,
    External object, assignment and range as data uncertainty, not
    consumption. Re-establishment uses post-gap formations only, and no
    pre-gap identity revives.
  - **Contracts stay isolated.**
  - **Causal batch per 1m bar:** consumption first, then admissions, then the
    range update, then memberships.
  - **Outputs:**
    - the reused formation tables;
    - internal level versions;
    - price records;
    - range versions;
    - boundary assignments;
    - the `liquidity.consumption` and `liquidity.internal_range` M7A
      lifecycle logs;
    - a derived membership view and a causal active-level view;
    - an explicit `replay_cutoff`, with prefix equivalence.
- **Reason:** design-authority approval of rev 4, 2026-10-06.
- **Status:** ACTIVE. Part of the **APPROVED / FROZEN** Internal Liquidity (2026-10-07; merged via PR #16).
- **Implementation note (D-143 – D-147, 2026-10-06):** MACHINE VALIDATION PASSED; HUMAN VISUAL APPROVAL PASSED (2026-10-07).
  - Implemented on branch `internal-liquidity-design` (IL-I1 `683da5a`,
    IL-I2 `e6cfbec`, IL-I3 `617e983`, IL-I4 `52291d1`, review fixes
    `9dd62ca`) as separate modules; no frozen module was changed (gate
    `frozen_sources_unchanged_vs_main`).
  - DEVELOPMENT validation (`reports/validation/internal_liquidity_dev_*`):
    11/11 machine gates PASS; IL-INV-1 – 20 all 0; engine equals the
    independent per-bar reference; 7 prefix replays equivalent.
  - **Boundary tie order (D-146; confirmed by the design authority,
    2026-10-07):** first ascending `available_at` of the candidate's current formation version; then ascending `source_at` (a Daily member's own `source_at`; for a cluster version, the earliest constituent member `source_at`); then ascending stable candidate id. (The first IL-I4 commit used the latest member
    `source_at`; corrected in `9dd62ca` with tie regression tests.) Every
    broken tie is audited (`BOUNDARY_TIE_BROKEN`, with the deciding key); 5
    on DEVELOPMENT (4 by `available_at`, 1 by `source_at`).
  - Consumption audit metric: `max_signed_excursion_ticks` (signed distance
    beyond `p` before the object's end, per bar against the version in effect;
    negative = price never reached `p`) and `max_penetration_ticks`
    (nonnegative, `max(0, signed)`). These replace the earlier, misleadingly
    named `max_excursion_ticks`.
  - Other representation choices (no semantic change): membership rows are
    contiguous intervals per (range, level), keyed by the range version where
    they began; the range status view starts at each episode's first 1m bar
    end.
- **Freeze note 2026-10-07 (Internal Liquidity, D-143 – D-147):**
  - Human visual review passed (2026-10-07) on the corrected 23-case package
    (17 REAL DEVELOPMENT, 6 SYNTHETIC) at checkpoint `9dd62ca`, the reviewed
    PR #16 head; merged to `main` via PR #16. No change after the reviewed
    checkpoint other than this closure documentation.
  - Machine validation: all 11 gates PASS; IL-INV-1 … IL-INV-20 = 0; engine =
    independent reference (0 mismatches); 7 DEVELOPMENT prefix replays
    equivalent. Full suite at `9dd62ca`: 758 passed / 0 failed / 590 subtests.
  - **Frozen DEVELOPMENT baseline** (cutoff 2025-06-30 17:00 ET; `run_id`
    `ilr_b1c4387b5b9f6515c5af7054babf556e9d4b9f2767a979ad11a077301e53e239`;
    includes the tie-corrected boundary selection):

    | metric | value |
    |---|---|
    | levels / level versions | 20,922 / 35,800 |
    | ranges / range versions | 62 / 117 |
    | boundary assignments | 170 (cluster: 10 ESTABLISHED, 1 ADVANCED_OUTWARD, 3 OPPOSITE_RESELECTED; Daily: 111 / 31 / 14) |
    | membership intervals | 17,199 |
    | price records | 17,939 |
    | broken boundary ties | 5 |
    | `level_id` SHA-256 | `64851d729e4729af…` |
    | `level_version_id` SHA-256 | `9ff34459f4cbd974…` |
    | `range_version_id` SHA-256 | `af1576c11f650f61…` |
    | `boundary_assignment_id` SHA-256 | `8696e8e0cc687e9c…` |
    | consumption `transition_id` SHA-256 | `2fb4f2fe71fc8f59…` |

    - Full fingerprints: `reports/validation/internal_liquidity_dev_summary.csv`.
    - Overall fingerprint = SHA-256 of the five identity values in the order
      above, joined by newlines: `3727767b77fc0cd07bc4d28a76fccd8238cad7849a54b6e484b87bb52d4bd212`.
  - The decision texts of D-143 – D-147 are unchanged (plus the confirmed tie
    order above). Future semantic changes require a new decision.

### D-148 — FVG formation and immutable zone facts
- **Date:** 2026-10-07
- **Decision** (`docs/project/FVG_IFVG_BPR_DESIGN.md` rev 2.1 §3.1 – §3.3, §3.13):
  - Six timeframes processed independently (1m canonical; 5m–1D via M3);
    three consecutive complete observations of one continuity segment.
  - **Wick gap** of at least one tick (bullish `low(C3) > high(C1)`, bearish
    `high(C3) < low(C1)`); equality is not an FVG.
  - **C2 directional body spans the gap** (bullish `close > open`,
    `open ≤ high(C1)`, `close ≥ low(C3)`; bearish mirrored). C1 / C3 any
    colour; a doji C2 fails. Rejections are audited. No size or
    displacement threshold.
  - Available at C3 close; never tested by its formation bars. Exact bounds,
    original width, exact (half-tick) midpoint; source-span evidence;
    `fz_` source-based identity.
  - **Normalized gap strength** = width / simple ATR of the 14 observations
    before C1 (15 consecutive observations of the segment required);
    exact rational; `INSUFFICIENT_HISTORY` / `ZERO_BASELINE` statuses with
    null strength.
- **Reason:** design-authority authorization of rev 2, 2026-10-07 (ICT
  wick-gap geometry; C2 rule as the approved operational rule).
- **Status:** ACTIVE — APPROVED / FROZEN (2026-10-08; D-148 freeze note).

### D-149 — FVG interaction and lifecycle
- **Date:** 2026-10-07
- **Decision** (rev 2.1 §3.4 – §3.6):
  - Lifecycle `FVG → IFVG → RETIRED` on own-timeframe complete closes
    strictly beyond the far bound; no repeated inversion; IFVG inherits the
    bounds and reverses direction.
  - Mitigation on canonical 1m by observation class (`ZONE_TRADE`,
    `SPANNING`, `FAR_CONTACT`, `NEAR_CONTACT`, `BEYOND`); strict initial
    penetration, inclusive midpoint / full reach; `GAP_THROUGH` evidence
    without inference; stage-separated records.
  - Causal batch: step-0 resets and basis guards, then 1m mitigation,
    close classification, admissions, relationship reassessment,
    associations, grades. One exit per entity and instant.
- **Reason:** design-authority authorization of rev 2, 2026-10-07.
- **Status:** ACTIVE — APPROVED / FROZEN (2026-10-08; D-148 freeze note).

### D-150 — FVG relationships, BPR and grading
- **Date:** 2026-10-07
- **Decision** (rev 2.1 §3.7 – §3.9):
  - Relationship episodes keyed by parent stage identities, positive-width
    intersections only; labels `FVG_OVERLAP` / `BPR` / `MTF_BPR`.
  - Admission- and conversion-created BPRs; the unique mover fixes BPR
    direction and governing timeframe; two movers → `UNDEFINED`
    (descriptive). Final-batch reassessment; no transient episodes.
  - BPR lifecycle independent of parents (governing-timeframe strict close
    beyond its far bound).
  - Zone priority: timeframe → same-direction formation-group overlap
    contribution (source-span connected components) → normalized strength
    (nulls below values) → original width → `available_at`, `zone_id`.
    BPRs ranked separately (governing timeframe → width → `available_at`,
    `bpr_id`).
- **Reason:** design-authority authorization of rev 2, 2026-10-07.
- **Status:** ACTIVE — APPROVED / FROZEN (2026-10-08; D-148 freeze note).

### D-151 — First FVG in a directional swing leg
- **Date:** 2026-10-07
- **Decision** (rev 2.1 §3.10): same-timeframe frozen 2/2 swings; C2
  anchor; origin = most extreme same-side swing since the last opposite
  swing (a higher low / lower high does not restart, a more extreme origin
  does); exact candidate-resolution deadline; separate formation and
  association availability; marker active only in the FVG stage, ends at
  conversion, never on the IFVG, no promotion.
- **Reason:** design-authority authorization of rev 2, 2026-10-07.
- **Status:** ACTIVE — APPROVED / FROZEN (2026-10-08; D-148 freeze note).

### D-152 — FVG data quality, price basis and outputs
- **Date:** 2026-10-07
- **Decision** (rev 2.1 §3.11 – §3.12):
  - 1m `DATA_GAP` onsets terminate every active FVG object; nothing is
    inferred inside gaps; post-gap re-establishment only.
  - Pure rolls (CB-2): old-contract objects become `PENDING_ADJUSTMENT`;
    the first new-contract bar never evaluates them.
  - Raw values with source contract and `basis_id`; no raw cross-contract
    comparison; explicit pending comparisons. The shared adjustment method
    is deferred; the compatibility contract (P1 – P5 plus the rev 2.1
    clarification on midpoints, widths, normalization and intersections)
    governs any future adjusted basis.
  - Fixed output schemas; empty zone-dependent outputs when no zone forms;
    data warnings and the manifest are always written.
- **Reason:** design-authority authorization of rev 2, 2026-10-07.
- **Status:** ACTIVE — APPROVED / FROZEN (2026-10-08; D-148 freeze note).

- **Implementation note (D-148 – D-152, 2026-10-07):** FVG-I1 – FVG-I5
  implemented on `fvg-design` in `src/fvg/` (`formation`, `engine`,
  `association`, `pipeline`, `audit`) with tests `tests/test_fvg_*.py`.
  - DEVELOPMENT machine validation (`src.experiments.fvg_dev_validation`;
    corrected 2026-10-08 after review of PR #17 at `ee6eb27`):
    - FULL RUN: FVG-INV-1 … 27 = 0; independent recomputation
      (`src.fvg.audit_full`) equals production on every episode and
      timeframe (4,199,171 rows in 10 categories, 0 mismatches).
    - SUBSET: naive all-pairs reference on 12 of 33 1m episodes (4.48 % of
      1m bars), 0 mismatches; 14 category × timeframe cells uncovered.
    - PREFIX: 13 early DEVELOPMENT rebuilds, payload-level comparison against
      the as-of projection, 0 mismatches.
    - Frozen Swing / continuity baselines and frozen sources unchanged;
      scratch §5.14 evidence reproduced (91 / 91).
  - Strategy views are causal as-of projections (no future exit metadata);
    the engine tables keep the full audit history.
  - Evidence and the visual package (34 cases) were regenerated from code
    commit `4887537` with a clean code worktree (provenance recorded).
  - Implementation validation is distinct from feature freeze: human visual
    approval of `fvg_visual_validation.html` is pending; nothing is frozen.
  - No trading-definition decision changed.

- **Freeze note 2026-10-08 (FVG / IFVG / FVG_OVERLAP / BPR / MTF_BPR, D-148 – D-152):**
  - Human visual review passed (2026-10-08) on the corrected 34-case package
    (23 DEVELOPMENT, 11 SYNTHETIC) generated from code commit `4887537` (code
    worktree clean; evidence commit `ec2d47d`, the reviewed PR #17 head);
    merged to `main` via PR #17. No change after the reviewed checkpoint other
    than this closure documentation.
  - Machine validation: all 12 gates PASS; FVG-INV-1 … 27 = 0; full-run
    independent recomputation = production (4,199,171 rows, 0 mismatches);
    naive subset reference = production (12 / 33 1m episodes); 13 payload-level
    DEVELOPMENT prefix rebuilds equivalent; scratch §5.14 reproduced. Full suite:
    808 passed / 0 failed / 6,345 subtests, plus `tests/test_fvg_visual.py` 3
    passed.
  - **Frozen DEVELOPMENT baseline** (cutoff 2025-06-30 17:00 ET; `run_id`
    `fvr_8c45a0a5008696fcfafa679aa9edf06563928bc1e85f062976bd95ab1b06ff28`;
    FVG source SHA-256 `99642ca9e22a6e37…`):

    | metric | value |
    |---|---|
    | zones | 77,558 (1m 59,661 · 5m 12,268 · 15m 4,223 · 1H 1,090 · 4H 285 · 1D 31) |
    | rejected wick gaps | 7,548 |
    | zone transitions | 151,460 |
    | mitigation records | 2,020,702 (zones 868,797; BPRs 1,151,905) |
    | relationship episodes | 472,007 |
    | BPR objects | 211,112 |
    | grade versions | 595,052 |
    | associations | 68,680 |
    | `zone_id` SHA-256 | `735995a88d72336e…` |
    | `relationship_id` SHA-256 | `e95164b7b9826c2c…` |
    | `bpr_id` SHA-256 | `aed25f755b578f91…` |
    | zone `transition_id` SHA-256 | `57bb761b90e08daa…` |
    | mitigation `event_id` SHA-256 | `8e8cedecadf00094…` |
    | `grade_version_id` SHA-256 | `36c9157923606ba9…` |
    | `association_id` SHA-256 | `ad2568f4f80d2db7…` |

    - Full fingerprints: `reports/validation/fvg_dev_summary.csv`.
    - Overall fingerprint = SHA-256 of the seven identity values in the order
      above, joined by newlines: `4c182a8c9fc0eae3af811cee19bedaaf8e89d4b98cd8db5fff66b12ed6276f3a`.
  - Known limits at freeze: no CONTRACT_CHANGE reset or ZERO_BASELINE on
    DEVELOPMENT (synthetic coverage only); adjustment method deferred (raw
    basis only); visual case selection is slow on full DEVELOPMENT
    (performance-only follow-up, no semantic change).
  - The decision texts of D-148 – D-152 are unchanged. Future semantic changes
    require a new decision.

### D-153 — Order Block scope, source and geometry
- **Date:** 2026-10-08
- **Decision** (`docs/project/ORDER_BLOCK_BREAKER_MITIGATION_DESIGN.md` rev 3 §1, §5, §20, §22):
  - Independent ICT feature layer (`src/ict_blocks/`): ordinary OB, BREAKER, MITIGATION only; rejection,
    morning/evening star, reclaimed, propulsion and vacuum blocks deferred.
  - Dependencies: Swing (public detector, OB default left_depth = right_depth = 1, configurable) and raw accepted
    FVG facts (`fvg-v1`). No liquidity, generic BOS/CHoCH/MSS or strategy inputs.
  - One last source candle: the terminal member of the anchor swing's source span. Bullish OB needs a bearish
    candle, bearish OB a bullish candle; body ≥ 4 ticks (exactly 4 qualifies); no earlier substitute, no
    aggregation, no morning-star exception.
  - Geometry: bullish [source.low, source.open]; bearish [source.open, source.high]; exact ticks, half-tick zone
    midpoint distinct from the source-body midpoint; successors inherit the exact interval.
- **Reason:** design-authority revision 3 with user-confirmed requirements.
- **Status:** ACTIVE — DESIGN APPROVED — IMPLEMENTATION AUTHORIZED; NOT VALIDATED / NOT FROZEN.

### D-154 — Order Block discovery and ordinary formation
- **Date:** 2026-10-08
- **Decision** (rev 3 §6, §22):
  - Swing-episode driven: each confirmed LOWER swing opens one bullish episode, each UPPER swing one bearish
    episode; opposing ordinary OBs coexist; an admitted episode is latched (later FVGs never restart source
    selection or duplicate); lifecycle monitoring continues.
  - Departure window (user decision 2026-10-08): from the source to the source end of the first opposite swing
    after it, inclusive (and before a new same-side swing's span). First same-timeframe FVG in the OB direction
    with source < C2 ≤ window end (no adjacency or price overlap required); a strict close beyond the source's
    far wick (bullish: above source.high) within the same window; no adverse close through admission.
  - ordinary_available_at = max(swing, FVG, validation close, ownership deadline); rejection only when knowable.
- **Reason:** design-authority revision 3 plus the 2026-10-08 window clarification.
- **Status:** ACTIVE — DESIGN APPROVED — IMPLEMENTATION AUTHORIZED; NOT VALIDATED / NOT FROZEN.

### D-155 — Order Block lifecycle, Breaker and Mitigation
- **Date:** 2026-10-08
- **Decision** (rev 3 §7, §8, §22):
  - One persistent block_id; immutable stage epochs. BREAKER / MITIGATION are alternative successors of an
    admitted ordinary parent (no direct-motif admission; NO_ORDINARY_PARENT is audit only).
  - Ordinary failure: strict own-timeframe close beyond the far boundary; actionability ends immediately.
  - Motif for a bearish successor (bullish mirrored): B = pinned anchor; A = latest opposite swing strictly before
    B; C = most extreme opposite swing strictly between B and the reversal close x; raid = a high strictly above A
    after B through x. C > A → BREAKER; C < A without raid → MITIGATION; otherwise FAILED_FINAL with reason.
  - successor_available_at = max(x, A/B/C availability, resolution); FAILED_AWAITING_CLASSIFICATION while unresolved
    (unreachable at N = 1); invalid-before-admission recorded; no backdating, same-close retest or re-inversion;
    successors retire on a strict close beyond their own far boundary.
- **Reason:** design-authority revision 3.
- **Status:** ACTIVE — DESIGN APPROVED — IMPLEMENTATION AUTHORIZED; NOT VALIDATED / NOT FROZEN.

### D-156 — Order Block interactions
- **Date:** 2026-10-08
- **Decision** (rev 3 §9): canonical 1m observations from each stage's availability; touch (closed interval),
  interior penetration, midpoint / distal / full-span observed (inclusive, doubled ticks), interior depth and
  uncapped adverse excursion, gap-beyond evidence, visits (contiguous intersecting minutes; a scheduled closure
  breaks a visit); touches never retire a stage; no inferred intrabar order.
- **Reason:** design-authority revision 3.
- **Status:** ACTIVE — DESIGN APPROVED — IMPLEMENTATION AUTHORIZED; NOT VALIDATED / NOT FROZEN.

### D-157 — Order Block data quality, basis and outputs
- **Date:** 2026-10-08
- **Decision** (rev 3 §10 – §13): causal batch order; 1m DATA_GAP onsets terminate active stages, waiting
  episodes and motifs; pure rolls → PENDING_ADJUSTMENT with explicit pending comparisons; raw basis only
  (adjustment deferred); fixed schemas, natural ids, M7A lifecycle, as-of causal views; no age limits.
- **Reason:** design-authority revision 3.
- **Status:** ACTIVE — DESIGN APPROVED — IMPLEMENTATION AUTHORIZED; NOT VALIDATED / NOT FROZEN.

### PROPOSED items awaiting design-authority approval (2026-09-28)
Claude recommendations from the architecture closeout; **not decisions**:
~~Market Context as tidy-DataFrame functions (no MarketContext object)~~
(adopted in D-124);
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
