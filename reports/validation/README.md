# Validation reports

Tracked, compact validation evidence. These files contain no prices and are
derived from local, Git-ignored data.

## `m3_1_dev_daily_incompleteness.csv`

M3.1 audit of incomplete Daily derived bars (2026-09-29). There is one row
per incomplete Daily bar: 28 rows.

**Inputs**

- `data/processed/MNQ_raw_cleaned_ET_DEVELOPMENT.csv`: DEVELOPMENT partition
  only, 337,815 1m bars, 248 sessions from 2024-06-21 to 2025-06-30.
- Session model: `config/sessions/cme_globex_et.json` with an empty override
  calendar, so `calendar_verified` is False for every row.
- Builder: `src.data.timeframes.build_timeframe` (M3), timeframe `1D`.

**Method**

- For each trading date, the expected 1m bar-end grid runs from session open
  + 1 min through session close.
- Missing minutes are that grid minus the observed bars.
- Missing minutes are grouped into contiguous gaps. A gap is labeled start,
  end, or internal relative to the session.

**Classifications** (evidence-based; no holiday labels because the calendar
verifies nothing):

| Label | Meaning |
|---|---|
| `PARTIAL_DATASET_START` | Gap at the start of the first session in the partition |
| `LATE_SESSION_START` | Contiguous gap at session start |
| `EARLY_DATA_END` | Contiguous gap at session end |
| `MISSING_INTERNAL_MINUTES` | Gaps inside the session only |

- `contract_changed_vs_previous_present_session` is True when the contract
  differs from the previous session present in the data. It is empty for the
  first session.

**Cross-checks run with the audit** (not stored in the CSV):

- Per-bucket missing counts at 5m / 15m / 1H / 4H / 1D match an independent
  computation (0 mismatches).
- Observed totals equal the source rows.
- `session_date` matches the session model for all rows.

**Findings not visible in this file** (a session with no bars produces no
Daily bar):

- 19 weekday sessions are absent.
- 16 of them are Mon–Thu of each quarterly roll week.
- The other 3 (2024-12-25, 2025-01-01, 2025-04-18) are unverified closure
  candidates.

See DECISION_LOG D-120 / D-121.

## `m5a_market_context_visual_validation.html` / `_cases.csv`

M5A Generic Market Context visual validation (2026-09-30). DEVELOPMENT only;
source data was read, not modified.

**What the chart shows**

- 7 sessions:
  - 2 normal (2024-10-01, 2025-05-01);
  - a roll Friday (2024-12-20);
  - after a missing expected session (2025-01-02);
  - an incomplete window (2025-01-23);
  - 2 DST-adjacent sessions (2024-11-04, 2025-03-10).
- Each panel shows 1m candles plus levels taken **only** from
  `align_market_context` (status `AVAILABLE`), so it shows exactly what a
  consumer sees.
- A dotted line marks each `available_at`; ✖ marks the completing (`PENDING`)
  bar and ○ the first eligible bar.
- Unavailable contexts are listed in red and never drawn.

**The CSV (price-free)** has one row per session × context:

- availability and reason;
- window and `available_at`;
- expected and observed counts;
- the status of the completing bar (`PENDING`, `COMPLETING_BAR_ABSENT_FROM_DATA`,
  or `OUTSIDE_TARGET_SESSION` for Previous Day / RTH);
- the first exposed bar, its offset from `available_at`, and the number of
  exposed bars.

**Tracking policy:**

- The HTML was used for **manual visual validation**.
- It is **intentionally excluded from Git**, via an exact path in
  `.gitignore`, because it embeds raw 1m market prices (about 9.6k bars).
  It exists only locally.
- The price-free `m5a_market_context_visual_validation_cases.csv` is the
  **tracked audit artifact**.

Findings: `docs/project/M5_MARKET_CONTEXT_SPEC.md` §10.

## `m6a_level_interactions_*`

M6A Level Interaction validation (2026-10-01). Source: DEVELOPMENT only,
read-only, using generic M5 levels from `market_context_levels`.

- **`m6a_level_interactions_dev_summary.csv`** (tracked, price-free): pair
  counts and primitive True-counts by context × field × orientation × status
  × `approach_side` × `approach_relation`. Frequencies are not performance.
- **`m6a_level_interactions_visual_validation_cases.csv`** (tracked,
  price-free): 12 reviewed cases with timestamps, statuses, primitives and
  offset ticks. It contains no prices. The off-grid case uses a synthetic
  level (PDH − 0.125).
- **`m6a_level_interactions_visual_validation.html`** (local, Git-ignored,
  because it embeds raw prices): candle panels with the level, the case bar,
  ineligible bars greyed and `PENDING_LEVEL` bars in amber.

Findings: `docs/project/M6_LEVEL_INTERACTIONS_SPEC.md` §20.

## `external_liquidity_*`

External Liquidity (static) DEVELOPMENT audit (2026-10-03). This is the
frozen validation baseline: External Liquidity 3.1 is **APPROVED / FROZEN**
as of 2026-10-04. DEVELOPMENT only; the source is read, not modified.

- **`external_liquidity_dev_summary.csv`** (tracked, price-free). Counts
  per section (1D, 4H, session, Previous Day, invariants):
  - bars, completeness and expected-but-absent buckets;
  - segments and break reasons;
  - candidates and qualification;
  - EQ/REQ versions and change kinds;
  - members, session coincidence counts, Previous Day resolution;
  - barrier blocks and blocker checks (price-free tick distances);
  - invariant failures, including "version superseded by more than one
    later version";
  - the review sections `4H_absent`, `versions` and `promotion`.
- **`external_liquidity_dev_structures.csv`** (tracked, price-free). One row
  per structure version: id, type, family, orientation, contract,
  `available_at`, member count, change kind, supersedes count, segment.
- **`external_liquidity_dev_continuity_breaks.csv`** (tracked, price-free).
  One row per segment break: the timestamps on each side, the reason by
  precedence, and the counts of missing buckets, missing sessions and
  incomplete bars, plus the contract-change flag.
- **`external_liquidity_visual_validation_cases.csv`** (tracked,
  price-free). The reviewed cases, with `REAL` / `SYNTHETIC` source and
  ids/timestamps. The barrier case also carries `blocking_bar_end` and
  `blocking_excess_ticks`, and synthetic cases carry `synthetic_reason`.
- **`external_liquidity_visual_validation.html`** (local, Git-ignored,
  embeds prices). 31 charted cases (14 DEVELOPMENT, 17 labelled synthetic
  where DEVELOPMENT has no example, e.g. Daily EQ/REQ and merges).

Findings: `docs/project/EXTERNAL_LIQUIDITY_SPEC.md` §18.

## `swing_structure_*`

Swing Structure 3.2 SW-I3 validation (2026-10-04). This is the **frozen
validation baseline**: Swing Structure 3.2 is **APPROVED / FROZEN** as of
2026-10-05.

- All machine gates passed.
- The human visual review passed on 24 unique cases (13 REAL DEVELOPMENT,
  11 SYNTHETIC). The manifest has 33 rows because some cases carry more
  than one timeframe, swing or candidate record; that is intentional.
- The overall `swing_id` fingerprint is
  `b6876266800d56b3421dbfb5e4a4aa50b83140acdd409390d28b5f75427c218f`.

**Scope.**

- DEVELOPMENT only: `data/processed/MNQ_raw_cleaned_ET_DEVELOPMENT.csv`,
  337,815 canonical 1m bars, 248 sessions from 2024-06-21 to 2025-06-30.
  The source is read, not modified.
- Explicit **2/2 reference definition** (`swing-pivot-v1`,
  `left_depth = right_depth = 2`). This is a validation configuration, not
  a detector default.
- All six timeframes: 1m (canonical bars) and 5m / 15m / 1H / 4H / 1D (M3).
- **Reproduce with:**
  `.\.venv\Scripts\python.exe -m src.experiments.swing_structure_dev_validation`
- No PnL, strategy or optimization; no VALIDATION / OOS data.

**Tracked files** (all price-free):

- **`swing_structure_dev_summary.csv`** (`section, timeframe, orientation,
  metric, value`):
  - source facts, continuity (segments, segment bars, breaks by reason);
  - canonical swing counts by orientation, adjacent-plateau swings,
    separated-equal pairs, session-truncated 4H sources;
  - candidate-audit status counts with invalidation side and break-reason
    breakdowns;
  - audit ↔ canonical reconciliation;
  - the 1m direct-vs-M3 cross-check;
  - SHA-256 `swing_id` fingerprints per timeframe / orientation and
    overall (the regression fingerprint once frozen);
  - machine-gate PASS / FAIL.
- **`swing_structure_dev_invariants.csv`**: 17 independent invariants per
  timeframe × orientation (204 rows), with the violation count and the
  first violating `swing_id` as detail.
- **`swing_structure_dev_continuity_breaks.csv`**: one row per shared
  continuity break per timeframe.
- **`swing_structure_dev_cross_timeframe.csv`**: the spec §23 as-of study
  (4H→15m, 4H→5m, 1H→15m, 1H→5m) by orientation and ALL. It is
  descriptive only and never detector input.
- **`swing_structure_visual_validation_cases.csv`**: manifest of the 24
  visual cases (13 REAL, 11 SYNTHETIC normative examples), with no prices.

**Local, Git-ignored files** (they embed prices):

- `swing_structure_dev_candidate_audit.csv.gz`: the full candidate audit,
  one row per maximal plateau per orientation per timeframe.
- `swing_structure_visual_validation.html`: production detector plus
  candidate-audit charts.

**Machine results.** All 13 machine gates PASS:

- the continuity baseline is exact;
- canonical counts are exact (119,381 swings);
- plateau and separated-equal counts are exact;
- 67 of 367 4H swings have a session-truncated source;
- audit ↔ canonical reconciliation is exact;
- all invariants are 0;
- the 1m direct path matches the M3 1m path exactly;
- the fingerprints are generated;
- the cross-timeframe study reproduces spec §23;
- all 24 visual cases are present;
- the tracked artifacts are price-free.

Spec: `docs/project/SWING_STRUCTURE_SPEC.md`.

## `market_structure_*`

Generic Market Structure (3.MS) MS-I3 DEVELOPMENT validation (2026-10-05).
Status: **APPROVED / FROZEN** (2026-10-06; merged via PR #14, `434d919`). This is
the frozen validation baseline (D-139 freeze note).

**Scope.**

- DEVELOPMENT only (the same 337,815 canonical 1m bars as Swing). The source
  is read, not modified.
- Explicit definition `structure-v1` / `swing-break-v1` over the explicit 2/2
  Swing reference (`swing-pivot-v1`).
- All six timeframes.
- Explicit `replay_cutoff` = 2025-06-30 17:00 ET, the close of the
  DEVELOPMENT partition's declared last session.
- **Reproduce with:**
  `.\.venv\Scripts\python.exe -m src.experiments.market_structure_dev_validation`
  (about 18 minutes; 1m dominates).
- No PnL, strategy, backtest or optimization; no VALIDATION / OOS data.

**Tracked files** (all price-free):

- **`market_structure_dev_summary.csv`** (`section, timeframe, metric,
  value`):
  - counts of swings, breaks, episodes (by opening cause and contract
    change), events (by kind / direction and reset reason), direction
    transitions, and roles by kind and exit state;
  - anomalies;
  - SHA-256 fingerprints of the natural ids;
  - `run_id` per timeframe;
  - machine-gate PASS / FAIL.
- **`market_structure_dev_invariants.csv`**: INV-1 … INV-17 per timeframe
  (102 rows), with violation counts.
- **`market_structure_dev_reconciliation.csv`**: engine versus the independent
  reference replay (`structure_audit.reference_structure`).
  - Covers role exits, roles active at segment end, events and direction
    transitions.
  - 1m replays every 4th continuity segment (9 of 33) to bound runtime; the
    other timeframes replay all segments.
- **`market_structure_dev_prefix_replay.csv`**: DEVELOPMENT prefix runs on
  4H and 1H, with cutoffs placed:
  - inside a contract-roll gap;
  - at a gap-reset onset;
  - one minute before that onset;
  - mid-episode;
  - at the new contract's first bar.
- **`market_structure_dev_episodes.csv`**: every episode with its opening
  cause, contract provenance and reset.
- **`market_structure_dev_runtime.csv`**: engine, invariant and reference
  seconds per timeframe.
- **`market_structure_visual_validation_cases.csv`**: manifest of the 20
  visual cases (15 REAL DEVELOPMENT, 5 SYNTHETIC).

**Local, Git-ignored:** `market_structure_visual_validation.html`, which shows
the production engine's role, event and reset charts with prices.

**Machine results.** All 10 gates PASS:

- swings equal the frozen Swing baseline;
- episodes equal the continuity segments;
- no DUAL_ESTABLISHMENT anomalies;
- all invariants are 0;
- the engine equals the independent reference;
- DEVELOPMENT prefix replay is equivalent;
- the visual cases are generated;
- no VALIDATION / OOS data was read;
- no strategy, PnL, backtest or optimization;
- the tracked artifacts are price-free.

Spec: `docs/project/MARKET_STRUCTURE_SPEC.md` rev 2.5 (D-139–D-142).

## `internal_liquidity_*`

Internal Liquidity (3.3) IL-I4 DEVELOPMENT validation (2026-10-06).
Status: **APPROVED / FROZEN** (2026-10-07; human visual approval on the corrected package at
`9dd62ca`; merged via PR #16). This is the frozen validation baseline (D-143 freeze note).

**Scope.**

- DEVELOPMENT only (337,815 canonical 1m bars); explicit `replay_cutoff` =
  2025-06-30 17:00 ET.
- Internal formations on 5m / 15m / 1H (explicit 2/2 Swing reference; 1H
  candles), frozen External Daily / 4H objects, consumption on canonical 1m
  bars (internal 4 ticks, External 6 ticks, strict beyond θ).
- **Reproduce with:**
  `.\.venv\Scripts\python.exe -m src.experiments.internal_liquidity_dev_validation`
  (about 40 minutes; invariants and 7 prefix rebuilds dominate).
- No PnL, strategy, backtest or optimization; no VALIDATION / OOS data.

**Tracked files** (all price-free):

- **`internal_liquidity_dev_summary.csv`** (`section, metric, value`):
  baselines, level / version / grade counts, lifecycle exits by object kind,
  range versions by change kind, assignments by selection kind, range-status
  minutes, membership exits, price records, SHA-256 id fingerprints, `run_id`
  and machine-gate PASS / FAIL.
- **`internal_liquidity_dev_invariants.csv`**: IL-INV-1 … IL-INV-20 (IL-INV-15
  is the prefix file), with checked and violation counts.
- **`internal_liquidity_dev_reconciliation.csv`**: production versus the
  independent per-bar reference (`internal_liquidity_audit`): External
  outcomes, levels, level versions, range versions and terminations,
  assignments, and membership at sampled instants (every range-version
  instant plus seeded samples). Full coverage except membership sampling.
- **`internal_liquidity_dev_prefix_replay.csv`**: 7 DEVELOPMENT prefix rebuilds
  at / one minute before an admission and an assignment consumption, at a
  gap onset, inside the gap, and at a range change.
- **`internal_liquidity_dev_runtime.csv`**: stage seconds.
- **`internal_liquidity_visual_validation_cases.csv`**: manifest of the visual
  cases (ids and timestamps only).

**Local, Git-ignored:** `internal_liquidity_visual_validation.html` (prices).
Formation / confirmation cases shade each evidence atom's physical source
span and mark every `available_at` (▲). Tables separate the pre-state at
s(m), the evidence at bar m, the post-state at e(m), and later lifecycle
outcomes (after e(m)).

**Audit metric.** Consumption evidence carries `max_penetration_ticks`
(nonnegative depth beyond `p` before the end) and `max_signed_excursion_ticks`
(signed; negative means price never reached `p`).

**Boundary ties.** Resolved by first `available_at`, then first `source_at`
(a cluster version's earliest member `source_at`), then id. Every broken tie
is counted in the summary (`audit, BOUNDARY_TIE_BROKEN`).

**Coverage notes.** DEVELOPMENT contains no CONTRACT_CHANGE episode reset
(every roll falls inside a data gap), no bar consuming both boundaries, no
pinned assignment consumed while its live cluster stayed active, no
same-close admission that the admitting bar exceeds, and no coincident
internal / External pair with the internal consumed first; these paths are
covered by synthetic visual cases (E4, E12, E19, E23 – E25) and unit tests.
