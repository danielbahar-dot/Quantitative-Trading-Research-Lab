# Project Memory

Answers: **"What must the next agent know?"** Durable state, decisions, and
guardrails — not an experiment diary. Run parameters/metrics belong in the
experiment ledger and project artifact directories.

Continuity set: [CLAUDE.md](CLAUDE.md) (behavior) · this file (durable state) ·
[WORK_PROGRESS](docs/project/WORK_PROGRESS.md) (where we are now) ·
[DECISION_LOG](docs/project/DECISION_LOG.md) (why). Other governance docs:
`docs/project/`.

Update MEMORY only when a stage is validated/frozen/closed, a durable decision
changes, a partition is opened/burned, or the authorized next step changes.

_Last restructured: 2026-09-24 (onboarding). Prior content was condensed;
detailed ORB gate history and metrics remain in README, Git history
(`d129a98` and earlier MEMORY versions), and project artifacts._

## 1. Repository purpose

The original Quantitative Trading Research Lab: causal, reproducible research
for multiple strategy families and instruments. VectorBT for analytics and
cross-checks; custom execution where intrabar/session/futures behavior matters.
It is the research source of truth for current work. A separate
NautilusTrader platform is the eventual runtime; migration is downstream and
not a current refactor (D-108).

Design authority lives outside Claude (ChatGPT, relayed by the user). Claude
implements; on ambiguity it stops and reports.

## 2. Current research status

| Family | Status |
|---|---|
| MNQ ORB V0.1 | Complete cycle. Gate 7: CAND_001 `REVISE`, CAND_002/003 `REJECT`. No OOS/production progression. |
| MNQ ORB V0.2 | Stage 2 features frozen (2026-09-02); Stage 3A–3C done; **`PARKED_AS_RESEARCH_CANDIDATE`** (2026-09-07). `HYP-ORB-STATE-01` potentially informative, unvalidated, parked. No new ORB optimization cycle. |
| ICT | **Active, new, separate family.** Phase 1 feature-first. Nothing implemented yet. |

ORB evidence is preserved as an infrastructure example and a future
regression/parity oracle. Closure note:
`experiments/projects/mnq_orb_v0_2/notes/mnq_orb_v0_2_final_development_research_conclusion.md`.

## 3. Current ICT initiative

Phase 1 primitives (in order under consideration): External Liquidity →
Internal Liquidity / meaningful swing structure → FVG → Rejection Block → MSS.
Phase 2 (a Turtle Soup / liquidity-raid model) is **not** to be implemented or
formalized until Phase 1 primitives are visually and programmatically validated.

External Liquidity design direction (historical; now implemented and frozen
as 3.1 under D-134, see below; details in DECISION_LOG D-104–D-106):

- Session references where already implemented: Previous Day H/L, Asia H/L,
  London H/L, NY Pre-market H/L, Overnight H/L.
- HTF: Daily EQH/EQL, Daily REQH/REQL, 4H EQH/EQL, 4H REQH/REQL.
  **1H EQ/REQ is not external liquidity** (likely Internal Liquidity).
- EQH/EQL: exact equality (0 ticks), no pivot, no look-forward, multiple
  candles strengthen one level, causal once enough history exists, touch does
  not consume, trade-through consumes, new extreme becomes the reference.
- REQH/REQL: a cluster (member prices preserved, never averaged), working
  tolerance 6 ticks for all included HTFs, chains allowed, no small member cap,
  partial consumption (outer active member keeps the cluster alive), consumed
  when the outer active extreme is traded through, no time expiry; any
  working-set horizon must not change historical ACTIVE/TAKEN state.
- Meaningful swing highs/lows and MSS are **not finalized** — do not invent.

## 4. Current next step

Architecture cleanup comes before ICT liquidity work. Milestones proceed one
at a time with explicit approval (D-117).

- **M1–M3.1 are merged into `main`** via PR #1 (merge commit `7dfa78b`).
  The unrelated Nautilus-doc commit `e2f1474` was never pushed; it is kept on
  the local branches `safety/pre-m1-local-main` and
  `safety/pre-m4-realign`.
- **M4, derived-timeframe persistence, is done** (2026-09-29): committed as
  `412dcd0` on branch `m4-derived-timeframe-persistence` (PR pending),
  `src/data/timeframe_store.py`.
  - Parquet (`pyarrow==25.0.1`) + JSON manifest under the Git-ignored
    `data/derived/timeframes/`.
  - Loads validate the output hash, `TIMEFRAME_BUILDER_VERSION`, session
    fingerprint and source hash. Stale data raises; nothing is rebuilt
    silently.
  - Reserved partitions need an explicit flag. (D-122)
- **D1 (contract stitching / source repair + holiday calendar) is DEFERRED**
  (D-123, revising D-120).
  - M5 Market Context, M6 Level Interactions, M7 State/Signal and the ICT
    feature library **may proceed before D1**, but must be
    **continuity-aware**:
    - never substitute an older available session for a missing expected
      session;
    - a missing expected input session → the feature is unavailable with an
      explicit reason;
    - no multi-session state is carried across missing expected sessions;
    - no aggregation across mixed contracts.
  - The roll gaps are a known limitation. Feature code must not silently work
    around them.
  - **D1 is still required before:**
    - research assuming continuous history across rolls;
    - final broad performance validation where roll periods matter;
    - carrying cross-session/contract structures through known gaps;
    - any canonical stitched continuous contract.
- **Frozen ORB limitation** (D-121): its previous-available-session "previous
  day" may skip missing roll-week sessions. This is a documented historical
  limitation; ORB stays frozen and unchanged.
- **M3, the generic timeframe builder, and the M3.1 audit are done**
  (2026-09-29): `src/data/timeframes.py`, on demand, no persistence.
  - Buckets anchor at the regular 18:00 open and are clipped to the actual
    session.
  - Incomplete buckets are emitted with flags; `available_at = bar_end`.
  - Mixed-contract buckets raise. (D-119)
  - A DEVELOPMENT smoke check confirmed that the dataset `session_date`
    matches the session model.
- **M2, generic instrument metadata, is done** (2026-09-29): committed as
  `241622a`, `src/data/instruments.py`.
  - `config/instruments/<id>.json` is authoritative, loaded into an immutable
    `InstrumentSpec` with exact `Decimal` economics. No silent defaults.
  - `mnq.json` must stay byte-identical: its hash is in the frozen Gate 6C
    provenance.
  - Legacy `TICK_SIZE` remains, guarded by a test. No consumers migrated.
    (D-118)
- **M5A, the Generic Market Context library, is done** (2026-09-29, branch
  `m5-generic-market-context`). Details: D-124 and
  `docs/project/M5_MARKET_CONTEXT_SPEC.md`.
  - `src/features/session_context.py` + `config/features/market_context_windows.json`.
  - **Generic contexts:** `previous_day`, `previous_rth` (validated
    09:30–16:00, close = 16:00 bar), `asia_2000_0000`, `london_0200_0500`,
    `overnight_1800_0700`, `overnight_context_2000_0900`,
    `ny_premarket_0700_0900`. Generic ≠ ORB-only.
  - Canonical 1m only. Strict completeness. Previous-expected-session
    selection with no fallback.
  - Summary reasons: `INSUFFICIENT_HISTORY`, `INSUFFICIENT_FUTURE_COVERAGE`,
    `MISSING_EXPECTED_SESSION`, `NOT_SCHEDULED`, `NO_OBSERVATIONS`,
    `MIXED_CONTRACT`, `INCOMPLETE_WINDOW`.
  - Alignment statuses: `AVAILABLE`, `PENDING`, `UNAVAILABLE_CONTEXT`,
    `CONTRACT_MISMATCH`. Visibility requires `bar_start ≥ available_at`, and
    context applies to the target session only.
  - Observed prices live only in the audit tier (`observed_*`). Consumers use
    `valid_context_levels` / `align_market_context`.
  - DEVELOPMENT check: exact parity with frozen ORB for Asia, London, NY
    pre-market and Overnight Context. Previous Day and Previous RTH differ
    only on the 6 D-121 dates.
- **M5A is APPROVED / FROZEN** (2026-09-30).
  - Visual validation (7 DEVELOPMENT sessions) and the semantic audit are
    complete. `MISSING_EXPECTED_SESSION` means the source session has no
    bars; `NO_OBSERVATIONS` means the session exists but the window is
    empty.
  - All invariants passed on 337,815 bars.
  - The visual HTML is local only and Git-ignored (raw prices). The
    price-free cases CSV is tracked.
  - Semantic changes need a new `definition_version`.
- **M5B, the ORB Market Context migration, is done** (2026-09-30, merged
  via PR #4; D-125).
  - The generic catalog is the authority. ORB consumes it via
    `src/experiments/orb_market_context_compat.py`.
  - Compatibility is limited to `orb_overnight_1800_0930`
    (`config/features/market_context_compatibility.json`) and
    `previous_available_session_legacy_orb` for Previous Day / RTH.
  - One engine: `session_context.evaluate_context`, with a pluggable source
    session.
  - Parity with frozen ORB is exact (all 474 audit columns; oracle SHA-256
    in M5 spec §11). M5A output is unchanged.
  - ORB context inputs now go through the CME session model (e.g. Sunday
    dates are rejected).
  - The window helpers in `market_context.py` are legacy, used only for the
    ORB opening range, the ORB audit and tests.
- **M6 (generic level interactions): COMPLETE.** M6A is in
  `src/features/level_interactions.py` (merged, PR #5) and is the sole
  generic authority. `docs/project/M6_LEVEL_INTERACTIONS_SPEC.md` rev 4.
  **M7A (generic State contract) is implemented and validated** in
  `src/state/contract.py` (D-129; spec rev 3, §0 normative; merged in PR
  #7). **M7B (generic Signal contract) is implemented** in
  `src/signals/contract.py` (D-132; merged in PR #8). **M7 is complete.**
- **Generic Market Structure & Liquidity (ROADMAP 3; D-133).** These are
  methodology-neutral primitives, **not** ICT features. ICT-type constructs
  (FVG, blocks …) form downstream family 4. There is no M8 naming.
  - **3.1 External Liquidity: APPROVED / FROZEN (2026-10-04)**
    (`docs/project/EXTERNAL_LIQUIDITY_SPEC.md` §18, D-134 freeze note).
    Semantic changes need a new decision; refactors must keep parity.
    - Frozen DEVELOPMENT baseline:
      - 2,553 members and 86 structures;
      - 438 Previous Day references;
      - 3,326 candidates, 50 breaks, 412 barrier blocks;
      - 169 promoted 4H members;
      - FORMED 84 / EXTENDED 2 / MERGED 0;
      - invariants 0;
      - suite 543 passed / 382 subtests.
    - Duplicate ids fail. `barrier_blocks` carries `blocking_bar_end` /
      `blocking_excess_ticks`.
    - Code: `src/liquidity/contract.py` (generic envelope) and
      `src/features/external_liquidity.py` (`build_external_liquidity`).
    - Complete Daily H/L are standalone members.
    - Session members: Asia, London, NY Pre-market, Overnight 18–07.
    - Previous Day is a derived reference to the Daily member.
    - A 4H H/L is a candidate until a confirmed EQ/REQ promotes it, with
      `available_at` = confirmation.
    - EQ is 0 ticks. REQ is a ≤ 6-tick chain with ≥ 2 distinct prices.
    - Pair-outer formation barrier.
    - Segments break on a contract change, a missing session or an
      incomplete bar.
    - Two tables (members + immutable structure versions), with full
      SHA-256 ids.
  - **3.2 Swing Structure: APPROVED / FROZEN (2026-10-05; spec rev 3;
    D-135–D-138).** Semantic changes need a new decision; refactors must
    keep the fingerprint.
    - One detector for 1m / 5m / 15m / 1H / 4H / 1D; canonical 1m
      directly, M3 for 5m–1D.
    - The 2/2 reference validation definition is explicit; it is not a
      default, not optimized and not a universal scale.
    - DEVELOPMENT: 119,381 swings; fingerprint
      `b6876266800d56b3421dbfb5e4a4aa50b83140acdd409390d28b5f75427c218f`.
    - Suite: 647 / 0 / 493. Machine gates and human visual review PASS
      (24 cases: 13 REAL, 11 SYNTHETIC).
    - Next: 3.3 Internal Liquidity: **IMPLEMENTED — MACHINE VALIDATION PASSED — PENDING HUMAN VISUAL APPROVAL; NOT FROZEN** (2026-10-06).
      - IL-I1 – IL-I4 on branch `internal-liquidity-design` (draft PR); all 11 DEVELOPMENT
        machine gates PASS; runner `src.experiments.internal_liquidity_dev_validation` (~40 min).
      - Awaiting human visual review; freeze and merge not authorized.
      - Spec rev 4 on branch `internal-liquidity-design`; D-143 – D-147.
      - Shared consumption predicate: strict beyond `p ± t` on 1m, with
        `t` = 4 internal and 6 External.
      - Pinned boundary assignments; price records with separate
        lifecycles; post-gap-only re-establishment.
    - That Market Structure workstream is **APPROVED / FROZEN** (2026-10-06).
      It was merged via PR #14 (`434d919`); the frozen baseline is in the
      D-139 freeze note.
      - Code: `src/market_structure/{swing_breaks,structure,structure_audit}.py`
        and the runner `src/experiments/market_structure_dev_validation.py`.
      - DEVELOPMENT: all 10 gates PASS; INV-1…17 are 0; the engine equals
        the independent reference.
      - The design was approved on 2026-10-05.
      - Spec `docs/project/MARKET_STRUCTURE_SPEC.md` rev 2.5; final
        review at `1b6d221`; **D-139–D-142**.
      - MS-I1 to MS-I3 are frozen; semantic changes need a new decision.
        MS-I4 (the Signal adapter) stays deferred.
      - BOS / CHoCH are generic; MSS is deferred.
      - Break evidence is native (`swing_breaks`): a close strictly beyond
        the level. M6 is unchanged.
      - Direction lives in M7A `structure.direction`. Each role
        assignment is its own `structure.role` entity.
      - Selection is a deterministic rescan with one post-close batch
        diff per bar.
      - T-1: a target confirmed at a failed close may be assigned at
        `e(N)`, but never classifies N.
      - CB-1 / CB-2: a gap then a roll gives a `DATA_GAP` reset at the
        onset, with the roll recorded later in the opening provenance. A
        pure roll resets at the first new-contract bar's close.
      - **Gap-reset adapter (§G.2a):**
        - resets come from the M3 schedule up to an explicit, required
          `replay_cutoff`;
        - frozen continuity is unchanged and is used only as a
          fail-closed agreement check and for opening provenance;
        - its break rows are retrospective and omit trailing gaps.
      - No stitching or roll calendar.
    - **SW-I2 (implemented, validated and design-authority approved;
      committed on `swing-structure-contract`):**
      `src/market_structure/swing_detector.py`
      `build_swing_points`.
      - One algorithm for all six timeframes; 1m comes directly from
        canonical bars, 5m–1D from M3.
      - Shared continuity, exact tick indices, maximal equal plateaus,
        strict-exceed windows.
      - Plus the public `validate_source_bars` in M3.
      - Full suite: 629 / 0 / 474.
    - **SW-I3 (implemented, machine-validated, human visually approved;
      committed):**
      - `src/market_structure/swing_audit.py` is the independent candidate
        audit and invariants. It is audit-only, with statuses CONFIRMED /
        INVALIDATED_STRICT_EXCEED / INSUFFICIENT_LEFT_HISTORY /
        INSUFFICIENT_FUTURE_COVERAGE / CONTINUITY_BREAK.
      - `src/experiments/swing_structure_dev_validation.py` is the
        DEVELOPMENT 2/2 runner.
      - All 13 machine gates PASS, with 119,381 swings matching the
        baseline exactly.
      - Human visual review: PASS (2026-10-05).
    - **SW-I1 (implemented, validated and design-authority approved;
      committed on the active Swing implementation branch
      `swing-structure-contract`; full suite 591 passed / 0 failed / 439
      subtests):** the canonical contract in
      `src/market_structure/swing.py`, with no detection. It provides:
      - `SwingDefinitionSpec`, `SWING_COLUMNS` and `bar_span_ref`;
      - `swing_id`, `assign_swing_ids` and `validate_swing_points`.
    - A plateau-aware confirmed pivot: a maximal equal run over
      consecutive expected observations in one segment is one source (it
      may cross a session boundary), and only a strict exceed fails a
      window.
    - Depths are explicit (≥ 1, no defaults). 2/2 is the reference
      validation configuration on all timeframes.
    - The `BAR_SPAN` format and the `sw_` key are final.
    - D-137: `ContinuityError` and `continuity_segments` now live in
      `src/data/continuity.py`. SW-I0 is merged and complete (PR #12,
      `3b098f5`).
      - It is extracted unchanged from External; External keeps a
        compatibility wrapper and translates the error.
      - Frozen External parity is exact.
      - The swing detector followed in SW-I2 and is frozen with Swing
        Structure 3.2.
    - Audit labels are not frozen.
    - Separated equal extremes are independent swings; EQ is downstream.
      A plateau is not consolidation or range.
    - `source_at` / `source_end_at` (canonical) / `available_at`, with
      `BAR_SPAN` plateau identity.
    - 1m (canonical bars) through 1D.
    - Detection is per timeframe only. HTF context is used by `swing_id`
      once `available_at ≤ bar_start`, with no copies.
    - Table `swing_points`, `UPPER` / `LOWER`.
    - First prerequisite (D-137): `src/data/continuity.py` extraction with
      exact External parity. This is SW-I0, merged (PR #12).
  - Next (D-133 sequencing clarification): 3.2 Swing Structure (frozen
    first), 3.3 Internal (static; may consume swings, but not every swing
    is liquidity), then 3.4 Shared Lifecycle.
  - A Signal is an immutable point event: no lifetime and no execution
    fields.
  - It reuses M7A's public `CausalKey` / `compare_causal` / `SourceRef`;
    no private State helpers.
  - The id is the full SHA-256 over type, version, instrument, scope,
    contract, subject, event key, direction, trigger and source refs, with
    no availability.
  - At most one Signal per semantic event key.
  - `trigger_ref` must not repeat in `source_refs`.
  - `SignalContractError(ValueError)`; State errors are translated.
  - The core is event-based: causal key `(at, seq_domain, seq)` (D-130).
    `compare_causal` returns BEFORE / AFTER / EQUAL / INCOMPARABLE.
    Sequences order only within the same domain; anything else at the same
    `at` is never ordered.
  - Each transition has a required `trigger_ref`; `source_refs` is
    optional, canonical provenance.
  - `validate_transitions(transitions, spec, entities)` has no
    `decision_offset` (D-131).
    - It validates log integrity, causality, provenance and replay.
    - Exact trigger-observation eligibility is owned by the upstream
      module (M6 for bars).
    - Exact windows are applied only by `state_as_of` and the
      materializers.
  - Consumers are strict (`state_as_of` = "available immediately before the
    query point"). Only `materialize_state_to_bars` applies the bar-boundary
    convention, and it needs an explicit `bar_start` or `bar_interval`.
  - Namespaces declare `initial_state` (no creation transition), edges
    (including skip edges, no self edges) and terminals (no exits).
  - Entities are a caller-provided applicability frame.
  - One transition per entity + namespace + causal source event.
  - Ids are the full SHA-256 of the natural key.
  - **M6B (D-128).** ORB consumes M6A via
    `src/experiments/orb_level_interaction_compat.py`, and
    `market_context.level_interaction` is removed.
    - Each OR is evaluated as one aggregated bar. This is an ORB consumer
      pattern, not the generic definition.
    - The only compatibility rule is open-at-level: AT forces the
      directional flags to False.
    - Parity with the frozen audit (`0120af8`) is exact: 234/234 `level_*`
      columns. Removing the AT rule breaks 718 rows.
    - New work must call M6A directly, never the adapter.
    - M6A requires on-grid bar prices, so synthetic fixtures must use the
      0.25 grid.
  - Applicability (D-127): optional immutable `valid_from` / `valid_until`.
    A bar is evaluated iff `bar_start ≥ max(available_at, valid_from)` and
    `bar_start < valid_until`. `PENDING_LEVEL` applies only to the
    confirming bar inside that window. M5 levels use the target session
    open / close.
  - D-126 applies. M6 is stateless and per bar, and its
    orientation is semantic: UPPER, LOWER or NEUTRAL.
  - Each bar has an `approach_side` (BELOW / ABOVE / AT, from the open) and
    an `approach_relation` (ORIGINAL_SIDE / FAR_SIDE), so far-side retests
    are supported. A directional open at the level counts as the original
    side.
  - Exact integer-tick rules use `f = floor(L/t)` and `c = ceil(L/t)`, so
    off-grid levels are allowed; bars must be on the grid.
  - Statuses: `EVALUATED`, `AMBIGUOUS_APPROACH` (NEUTRAL open at the level),
    `PENDING_LEVEL`, `CONTRACT_MISMATCH`.
  - Contract scope is `SPECIFIC` or `AGNOSTIC`. Offsets are raw
    `open/high/low/close_offset_ticks`. Invalid input raises.
- The next ICT design run will specify External and Internal Liquidity
  together, including contract rolls, swings, EQ/REQ, and the timeframe
  hierarchy.
- Target architecture: ARCHITECTURE_MAP §B. Directives: D-110 to D-117.

## 4a. Architecture directives (2026-09-28)

**Reusable primitives (D-110)**

- Reusable primitives live in generic layers, not strategy modules.
- ORB market context migrates to generic code only after parity is proven.

**Session model (D-111)**

- Session for trading date D = [18:00 ET on D-1, 17:00 ET on D).
- 17:00–18:00 is the maintenance break.
- Timezone-aware, DST via wall-clock rules.
- Single source: `config/sessions/cme_globex_et.json`.

**Calendar overrides (D-112)**

- Explicit `CLOSED` / `MODIFIED` overrides.
- The calendar is currently empty with null coverage; no holiday dates were
  invented.

**Previous day (D-113)**

- "Previous day" means the previous **expected** session.
- A missing expected session must be distinguished from a legitimate closure.
- No silent fallback. ORB's frozen dataset-previous behavior differs.

**Generic windows (D-114)**

- Overnight 18:00–07:00 and NY pre-market 07:00–09:00, non-overlapping.
- 09:00–09:30 is in neither window.
- Asia and London unchanged. Frozen ORB `overnight` stays 18:00–09:30.

**Level interaction (D-115)**

- TRADE_THROUGH = ≥1 tick beyond intrabar. CLOSE_THROUGH = close ≥1 tick
  beyond.
- A level never interacts with the bar that establishes it.

**Timeframes (D-116)**

- 1m is canonical; derived timeframes are cache.
- Session-anchored 5m/15m/1H/4H/Daily. 4H anchors: 18/22/02/06/10/14.
- No synthetic bars, and no HTF bar is used before it is complete.

## 5. Critical architectural constraints

- FEATURE ≠ STATE ≠ SIGNAL ≠ STRATEGY ≠ EXECUTION; contracts stay separate.
- Pipeline: `raw → validated/clean → features → causal state → signals →
  strategy definition → execution → completed trades/audit → experiments →
  analytics → ledger/dashboard → gate decision`.
- Prevent look-ahead at every boundary; signals are recorded even when not
  traded; execution never erases the signal record.
- Custom execution is authoritative when intrabar order, next-bar fills, session
  rules, ambiguity, or trade limits matter. Do not force ORB into
  `Portfolio.from_signals()`.
- Canonical trades/audits are source artifacts; summaries/equity are derived.
- Keep strategy, instrument, dataset, partition, parameter, execution/cost, and
  code identity separate. Instrument facts belong in instrument config.
- Raw data immutable; reruns get a new `run_id`; never overwrite history.
- New experiments register via `src/experiments/experiment_registration.py`;
  manual index editing is legacy backfill. Dashboard is read-only.
- Preserve existing Python import paths; do not move ORB modules cosmetically.
- Backtest observability is first-class: report ambiguity/exclusion rates and
  chronology sensitivity alongside any performance.

## 6. Important frozen assumptions

**Data / time (all research):**

- MNQ 1-minute NinjaTrader OHLC, Eastern Time, `timestamp_et = bar_end_time`.
  Conceptual `[start, end)` windows use bars `start+1min`…`end`. Bars from the
  18:01 reopen belong to the next CME trading `session_date`.
- Dataset ID `MNQ_1m_actual_contract_v1`; bars `data/MNQ_raw_cleaned_ET.csv`
  (actual contract, not back-adjusted). MNQ tick 0.25 points.

**Partitions** (`config/datasets/mnq_1m_actual_contract_v1.partitions.json`):

- DEVELOPMENT 2024-06-21 → 2025-06-30 (only exploration/tuning partition).
- VALIDATION 2025-07-01 → 2025-12-31 — exposed by ORB Gate 7/8A; burned for ORB
  V0.2 hypothesis generation; usable only for retrospective diagnosis there.
- OOS_BURNED 2026-01-01 → 2026-08-17 — full-history ORB results viewed before
  partitioning; not untouched evidence; do not access without human approval.

**Stage 2 frozen feature semantics (2026-09-02, human-validated 14/14):**

- Asia 20:00–00:00 ET, London 02:00–05:00 ET, NY pre-market 07:00–09:00 ET
  (`NY PM` = New York pre-market, never afternoon).
- `OVERNIGHT_CONTEXT_2000_0900` is a continuous context range
  (`combined_preopen` = migration alias only). Separate `overnight` window:
  18:01–09:30 bar-ends (dataset-verified).
- Previous full futures trading-day H/L/C are the primary prior-day references;
  previous RTH H/L/C remain available.
- `GLOBEX_REOPEN_GAP` (prior 17:00 close vs 18:01 reopen) and `NY_OPEN_GAP`
  (prior 16:14 close vs current 09:31 open) are distinct; missing bars are not
  substituted.
- TOUCH, TRADE_THROUGH, CLOSE_THROUGH, REJECT, SWEEP are neutral primitive
  key-level events (SWEEP implies TRADE_THROUGH and REJECT) — ORB-OR-scoped.
- Price-normalized values stored as decimal ratios; raw points kept separately.
- Causal OR-width percentile uses 5/10/15/20 prior same-duration sessions,
  explicit warm-up, no backfill.
- Config: `config/features/mnq_orb_v0_2_preopen_windows.json`.

**ORB V0.1 frozen timing/semantics** (full detail in README): OR windows start
09:31 bar-end (5/10/15/20/30m; first eligible bars 09:36/09:41/09:46/09:51/
10:01); signal cutoff 11:30 inclusive; PRINT enters at OR boundary on signal
bar, CLOSE at next bar open; baseline stop OR midpoint, 2R target; one trade per
session per variant; no costs/slippage. V0.1 frozen candidates: CAND_001
15m/fixed-50/75pt, CAND_002 20m/midpoint/75pt, CAND_003 30m/fixed-40/75pt.

**Durable ORB learnings:** strongest DEVELOPMENT regions did not persist in
VALIDATION; ambiguity did not explain degradation; OR width is nonlinear and
state-dependent; parameter maxima alone are insufficient evidence.

## 7. Known issues / technical debt

- Reusable session-level construction (previous day, Asia, London, NY
  pre-market, overnight) lives in the ORB-named module
  `src/experiments/mnq_orb_v02_features.py`; generic primitives are in
  `src/features/market_context.py` (which also carries ORB constants).
- **Source-data gap at contract rolls** (M3.1, DEVELOPMENT):
  - Mon–Thu of every quarterly roll week is absent (16 sessions), and each
    new contract starts at 00:01 on the roll Friday (18:01–00:00 missing).
  - These are missing expected sessions, not closures.
  - It affects the future PDH/PDL and roll design. Frozen ORB used the prior
    week's Friday as "previous day" on those Fridays.
  - Detail: WORK_PROGRESS and
    `reports/validation/m3_1_dev_daily_incompleteness.csv`.
- Derived-timeframe persistence exists (M4); no generic level-lifecycle
  (ACTIVE/TAKEN) model.
- Legacy tick-size duplicates remain as temporary compatibility artifacts,
  pending consumer migration:
  - `TICK_SIZE = 0.25` in `candidate_entries.py` (guarded by a test);
  - a `0.25` literal in `orb_gate6b_fixed_points.py` metadata;
  - `tick_size` in `config/experiments/orb_gate6b_dev_fixed_target_stop.json`.
  - The authoritative source is `config/instruments/mnq.json` via
    `load_instrument` (M2).
- Two ledger mechanisms: legacy `src/research_harness.py` (SQLite/CSV; used
  only by `orb_v01.py` and notebook 16) and the V1.0 registration API
  (canonical going forward, PROPOSED).
- `ET_TIMEZONE` constant defined in 2 modules; `"America/New_York"` literal in
  ~8 more. New code must use `src/data/sessions.py` instead.
- Previous-day levels in ORB use "previous session present in data" (silent
  fallback if a session is missing) — frozen; generic rule is D-113.
- Test baseline is green as of M1.1 (2026-09-28): 247 passed, 0 failed.
  Tests do **not** read Git-ignored market data (this corrects the
  2026-09-24 note).
- ORB V0.2 Stage 3B record is still `status=running` (human review pending
  per its notes). It is frozen and left unchanged; finalizing it needs a
  design-authority decision.
- `src/strategies/` empty; `strategies/momentum/` is a placeholder.
- Extra ad-hoc CSVs at `data/` root; `data/raw/` and `data/cleaned/` empty.
- `experiments/projects/mnq_orb_v0_2/research_ideas.json` still labels
  `research_stage` as `STAGE_2_FEATURES` (frozen artifact; left unchanged).

## 8. Pending decisions

See WORK_PROGRESS "Blocked / unresolved" for the full list. Headline items:

- holiday calendar source (override coverage);
- level orientation reference;
- incomplete-HTF-bar policy;
- generic overnight ID;
- ICT partition plan;
- contract rolls and swing/MSS/EQ/REQ (next ICT design run).

## 9. Repository conventions

- Remote: `https://github.com/danielbahar-dot/Quantitative-Trading-Research-Lab.git`.
- Configs: `config/datasets/`, `config/instruments/`, `config/features/`,
  `config/experiments/`, `config/components/`.
- Reviewed artifacts: `experiments/projects/<project_id>/<artifact_class>/`;
  local runs `experiments/runs/<run_id>/`. SQLite ledger/CSV mirror, market data,
  and generated tables are Git-ignored.
- Documentation: README = platform reference; MEMORY = durable state;
  `docs/project/` = governance, progress, decisions, internal changelog (D-109
  supersedes the former "no PROJECT_STATUS / no CHANGELOG" rule).
