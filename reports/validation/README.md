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

## `fvg_*`

FVG / IFVG / FVG_OVERLAP / BPR / MTF_BPR (ROADMAP 4, ICT family) FVG-I5
DEVELOPMENT validation (2026-10-07; corrected 2026-10-08 after review of PR #17
at `ee6eb27`). Status: **APPROVED / FROZEN** (2026-10-08; human visual approval on the
34-case package from `4887537`; merged via PR #17). This is the frozen
validation baseline (D-148 freeze note). Design: `docs/project/FVG_IFVG_BPR_DESIGN.md` rev 2.1;
D-148 – D-152.

**Scope.**

- DEVELOPMENT only (337,815 canonical 1m bars); explicit `replay_cutoff` =
  2025-06-30 17:00 ET. Six timeframes (1m, 5m, 15m, 1H, 4H, 1D), raw price
  basis, canonical 1m interaction, explicit 2/2 Swing reference for leg
  association. No age cutoffs; no history discarded.
- **Reproduce with (FULL tier, final evidence):**
  `.\.venv\Scripts\python.exe -m src.experiments.fvg_dev_validation`
  (about 45 minutes and 4.6 GB peak RSS since `6bc7490`; 3.1 hours at
  `4887537` before the visual case-selection fix; run it alone, not beside
  the test suite).
- **FAST tier (iteration only):** `--fast` (DEVELOPMENT week 2024-08-05 –
  2024-08-09: about 4 minutes, under 300 MB) or `--start / --end` for any
  DEVELOPMENT window (windows outside DEVELOPMENT are refused). Same checks;
  full-DEV-only gates (frozen Swing / continuity baselines, scratch §5.14) are
  reported SKIPPED, never PASS; the naive subset reference covers every
  episode of the window; missing DEVELOPMENT visual cases are listed; outputs
  go to the Git-ignored `reports/validation/fvg_fast/`. Fast-tier output is
  never committed evidence.
- **Re-verification at `6bc7490`** (full tier, `--out` to the Git-ignored
  folder): all 12 gates PASS; every tracked CSV is identical to the frozen
  evidence except runtime seconds and the provenance rows (run_id and all
  identity fingerprints identical); the HTML is identical to the approved
  package outside its provenance header. The frozen files were not
  regenerated.
- No PnL, strategy, backtest or optimization; no VALIDATION / OOS data.

**Evidence classes** (kept distinct; `method` column where applicable):

| Class | What | Coverage |
|---|---|---|
| FULL RUN | FVG-INV-1 … 27 (`src.fvg.audit.invariants`) | every object |
| FULL RUN | Independent recomputation `src.fvg.audit_full`: formation and rejections, zone transitions, zone mitigation, relationship episodes, BPR objects and exits, BPR mitigation, grade versions, groups, associations | every episode, every timeframe: 4,199,171 rows, 0 mismatches |
| SUBSET | Naive all-pairs replay `src.fvg.audit.reference` | 12 of 33 1m episodes (≤ 3,600 bars; 4.48 % of 1m bars); 14 category × timeframe cells have zero coverage (all 1D cells; 4H BPRs, BPR mitigation and same-timeframe BPR episodes) |
| PREFIX | 13 DEVELOPMENT rebuilds, payload comparison | early DEVELOPMENT cutoffs only (within the first seven 1m episodes) |
| SYNTHETIC | Unit tests, synthetic visual cases | contract change, pending adjustment, zero baseline (absent from DEVELOPMENT) |

The full-run recomputation shares only frozen inputs (M3 observations in
continuity segments, the §G.2a 1m episodes, frozen swing points) and identity
formulas with production. Its restrictions are exact and never truncate active
state: a zone's lifecycle and mitigation depend only on its own bars (per-zone
replay over its whole life); episodes come from an interval sweep over the
reference's own stage intervals; BPRs from a per-object replay on the
governing timeframe; grades / groups from per-zone partner timelines with
union-find over source spans; associations from a two-pointer sweep.

**Tracked files** (all price-free):

- **`fvg_dev_summary.csv`** (`section, timeframe, metric, value`): formation
  counts, rejection reasons, normalization statuses and strength quantiles,
  lifecycle transitions, mitigation by stage / event / observation class,
  relationship episodes (admission- vs conversion-created) and end reasons,
  BPR objects by label / direction / exit, grade versions, associations and
  first markers, data-gap warnings, SHA-256 id fingerprints, `run_id`,
  full-run and subset reference figures, machine-gate PASS / FAIL.
- **`fvg_dev_invariants.csv`**: FVG-INV-1 … FVG-INV-27 (INV-21 is the prefix
  file; INV-25, empty input, is a unit test) with checked and violation counts.
- **`fvg_dev_full_reconciliation.csv`**: FULL RUN — reference vs production
  by category and timeframe (episodes by label and parent timeframes).
- **`fvg_dev_reconciliation.csv`**: SUBSET — naive reference vs production.
- **`fvg_dev_reference_coverage.csv`**: SUBSET coverage by category and
  timeframe, including zero-covered rows.
- **`fvg_dev_prefix_replay.csv`**: 13 DEVELOPMENT prefix rebuilds at / around
  a 5m admission, a mitigation, a conversion, a conversion-created BPR, a
  relationship change, a BPR retirement, a gap onset, inside the gap, and an
  association deadline. Every output table is compared payload for payload
  (canonical rows, all columns) against the full run's as-of projection at the
  cutoff (later exits nulled); duplicates of ids and rows are counted
  separately; the strategy views and ranks are compared at the cutoff.
- **`fvg_dev_scratch_reconciliation.csv`**: production versus the design's
  scratch evidence (§5.14): 91 / 91 metrics equal. "Pending candidates" uses
  the scratch scope (all zones); the summary also reports the in-leg subset.
- **`fvg_dev_runtime.csv`**: stage seconds and peak RSS.
- **`fvg_visual_validation_cases.csv`**: manifest of the visual cases (ids and
  timestamps only).

**Causal views.** `active_fvg_zones`, `active_bprs` and `active_overlaps` are
built from as-of projections (`bprs_as_of`, `episodes_as_of`, `stages_as_of`):
no exit metadata after the query time is visible, and the active views carry no
exit columns. The engine tables keep the complete audit history. Regression:
`tests/test_fvg_views.py` compares full-run historical queries with genuinely
truncated runs at every cutoff and every earlier query time.

**Local, Git-ignored:** `fvg_visual_validation.html` (prices). The header
records the source revision (`git_head`), branch, code-worktree state, other
worktree changes and a SHA-256 of the FVG sources (line-ending independent);
the same values are in `fvg_dev_summary.csv` (`provenance`). Each case shows
the own-timeframe candles, formation candles C1 – C3 with the C2 body
outlined, shaded source spans, exact bounds and midpoint, availability markers
(▲), and tables separating pre-state, evidence, post-state and later
lifecycle. Capped tables state displayed / total counts and always include the
focal rows (no capped table is called complete history).

- DEVELOPMENT cases: all six timeframes, mitigation classes, retirement, IFVG
  retest, a data gap, normalization statuses, an overlap group with the
  partners' source spans, and BPR cases selected and asserted by mover
  provenance — admission-created BPR and MTF_BPR, and separately
  conversion-created BPR and MTF_BPR — each with the governing exit bar and
  retirement predicate.
- Association cases separate the association record from marker activation:
  immediate (active at formation), delayed and active while still FVG, and
  delayed but never active (FVG stage ended at or before the association).
- Synthetic cases (isolated fixtures, no frozen calendar altered) cover the
  worked examples W1, W2, W4a – c, W5, W7 (conversion-created MTF_BPR, asserted),
  W9D, W10 – W12.

**Remaining limits.** DEVELOPMENT contains no CONTRACT_CHANGE episode reset
(every roll falls inside a data gap) and no ZERO_BASELINE normalization; those
paths, the pure-roll guard and pending adjustment are covered by synthetic
fixtures and unit tests only. DEVELOPMENT prefix rebuilds are early cutoffs
(the full-run recomputation and the synthetic every-cutoff prefix tests cover
later behaviour). The naive subset reference does not reach 1D, 4H BPRs or
the long episodes; the full-run recomputation does.

## `ob_*`

Order Block / Breaker / Mitigation (ROADMAP 4, ICT family) OB-I5 DEVELOPMENT
validation (2026-10-08; corrected 2026-10-09 after review of PR #19 at
`ae8a462`). Status: **MACHINE VALIDATION PASSED — PENDING HUMAN VISUAL
APPROVAL**. Not frozen. Design: `docs/project/ORDER_BLOCK_BREAKER_MITIGATION_DESIGN.md`
rev 3 (+ §22 binding, corrected ownership rule; §23 status); D-153 – D-157.

**Scope and provenance.** DEVELOPMENT only (337,815 canonical 1m bars);
explicit `replay_cutoff` 2025-06-30 17:00 ET; six timeframes; OB Swing depths
1/1 (public detector); raw `fvg-v1` formations; raw basis. Evidence generated
from code `ae1462e` with a clean worktree (`provenance` rows in the summary and
the HTML header; OB source SHA-256 `607a7d85…`). The earlier evidence from
`7e53b43` is superseded (production discovery timing changed).

- **Reproduce (FULL tier):** `.\.venv\Scripts\python.exe -m src.experiments.ob_dev_validation`
  (about 46 minutes, 1.7 GB peak RSS; run alone).
- **FAST tier:** `--fast` (DEVELOPMENT week 2024-08-05 – 2024-08-09, about
  1.5 minutes) or `--start / --end`; full-DEV-only gates SKIPPED; outputs
  Git-ignored under `reports/validation/ob_fast/`.
- No PnL, strategy, backtest or optimization; no VALIDATION / OOS data.

**Evidence classes** (`ob_dev_evidence_coverage.csv`, `evidence_class`):

| Class | What | Scope |
|---|---|---|
| FULL_DEV | every lifecycle / rejection path × timeframe count (zero cells kept) | whole partition |
| FULL_DEV_REFERENCE | independent causal reference vs production per category × timeframe, with the compared fields | whole partition, every timeframe |
| PREFIX_EARLY_DEV | 9 payload-level prefix rebuilds (all tables, causally reconstructed visits, active-block and discovery views) | early DEVELOPMENT cutoffs only |
| SHUFFLE_WINDOW | shuffled dependency rows, two seeds, outputs identical | DEVELOPMENT 2024-09-02 – 2024-09-30 |
| SYNTHETIC | isolated fixtures per path (`tests/ob_fixtures.py`, `tests/test_ob_deadlines.py`) | paths absent from DEVELOPMENT |

**Compared fields** (independent reference; object key = timeframe, direction,
source bar end): episodes (anchor, status, decided_at, reason); blocks
(ordinary_available_at, lower / upper ticks, formation FVG); lifecycle (from,
to, at, reason); motifs (outcome, reason, A and C swing ids, raid observed);
stages (kind, direction, available_at, ended_at, end reason); interactions
(kind, at); visits (start, end, bars, penetration / midpoint / distal /
full-span flags, max depth, max adverse excursion); depth versions (at, running
maxima). Ids, refs, contract / basis labels, price floats, evidence rows and the
M7A log are checked by invariants, schema validation and prefix comparison, not
by the reference.

**Tracked files** (price-free): `ob_dev_summary.csv`, `ob_dev_invariants.csv`
(OB-INV-1 … 14), `ob_dev_reconciliation.csv` (48 category × timeframe rows),
`ob_dev_evidence_coverage.csv`, `ob_dev_prefix_replay.csv`, `ob_dev_runtime.csv`,
`ob_visual_validation_cases.csv`.

**Results.** All 12 gates PASS. 192,642 episodes; 17,929 ordinary blocks
(1m 13,303 · 5m 3,204 · 15m 1,104 · 1H 251 · 4H 63 · 1D 4); 16,553 failures →
14,690 BREAKER, 1,761 MITIGATION, 102 FAILED_FINAL (EQUAL_EXTREME 62,
NO_REVERSAL_SWING 20, NO_PRIOR_EXTREME 11, RAID_WITH_LESS_EXTREME_C 8,
EQUAL_EXTREME_WITH_RAID 1); 0 FAILED_AWAITING_CLASSIFICATION (N = 1);
reference 0 mismatches over all 48 cells; OB-INV-1 … 14 = 0; prefix 0
mismatches; shuffle identical.

**Not covered on DEVELOPMENT** (synthetic only): pure contract change /
PENDING_ADJUSTMENT; FAILED_AWAITING_CLASSIFICATION and
QUALIFIED_BUT_INVALID_BEFORE_ADMISSION (N = 2 only); ALREADY_INVALID_BEFORE_ADMISSION
(0 after the exact-deadline correction). Daily: 4 ordinary blocks and no
motifs, interactions, visits or depth versions (reference cells are zero, not
compared). Prefix cutoffs are early in DEVELOPMENT.

**Local, Git-ignored:** `ob_visual_validation.html` — 24 DEVELOPMENT cases and
13 synthetic cases (ordinary / Breaker / Mitigation in both directions, equal
extreme, outside reversal bar, N = 2 delayed and invalid-before-admission,
concurrent pair, 3-tick source, pure roll). Formation and lifecycle panels keep
the focus inside a plotted window; omitted context is listed; tables carry the
numerical decision evidence and separate later audit outcomes from what was
known at the focus.
