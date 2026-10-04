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
