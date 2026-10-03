# External Liquidity (static): Specification

**Status: DESIGN APPROVED — IMPLEMENTATION NEXT (2026-10-03; D-133,
D-134).** Nothing is implemented.

- **Workstream:** Generic Market Structure & Liquidity (ROADMAP 3.1). It is
  methodology-neutral; usable by mean-reversion, breakout, Wyckoff, SMC /
  ICT, order-flow, statistical and other strategy families. It is **not**
  an ICT feature.
- **Branch:** `m8a-external-liquidity-design`, from `main` `807c321` (M7
  complete). Some branch and decision names predate the renaming;
  documents use the generic names below.
- **Related decisions:**
  - D-104 (clarified by D-134), D-105, D-106;
  - D-113, D-116 / D-119, D-117, D-120 / D-123;
  - D-126 / D-127 (M6), D-129–D-132 (M7);
  - D-133 (classification and naming), D-134 (this definition).

**Sequence (ROADMAP 3.x):**

1. **3.1 External Liquidity:** static, this document.
2. **3.2 Internal Liquidity:** static.
3. **3.3 Swing Structure.**
4. **3.4 Shared Liquidity Lifecycle:** designed only after 3.1 and 3.2
   static representations exist.

Methodology-specific constructs (FVG, IFVG, Order / Rejection / Mitigation
Blocks …) form a separate downstream family (ROADMAP 4).

---

## 1. Scope

**Owned here:**

- which External Liquidity members exist;
- which EQ / REQ structures exist;
- exact member prices, causal availability, provenance and contract scope;
- immutable structure-version history.

**Not implemented or designed here:**

- **Liquidity layers:** lifecycle or any state machine; Internal Liquidity;
  Swing Structure.
- **Downstream use:** production Signals, Strategy, Execution.
- **Data:** D1 / stitching, tick ingestion.
- **Excluded constructs:** FVG, IFVG, Order / Rejection / Mitigation Blocks,
  MSS / BOS.
- **Infrastructure:** detector frameworks, registries, plugins, source
  graphs, event buses.

## 2. External Liquidity families (normative)

| Family | Canonical atom | Becomes liquidity |
|---|---|---|
| **A. Daily High / Low** | Every **complete** Daily bar's high (UPPER) and low (LOWER) | Immediately at Daily bar completion; standalone |
| **B. Session / reference High / Low** | Selected M5 extrema (§6) | Immediately at M5 availability; standalone |
| **C. Daily EQ / REQ** | Structures over **existing** family-A members | Additional groupings. They create no new liquidity |
| **D. 4H EQ / REQ** | 4H extremes that a confirmed structure promotes from candidate to member | Only at structure confirmation |

**Daily vs 4H (final).**

- A complete Daily high or low is canonical External Liquidity the moment
  the Daily bar is known. It needs no second bar, no EQ / REQ and no swing
  confirmation.
- An ordinary completed 4H high or low is **not** liquidity. It is only a
  **formation candidate**, and becomes a canonical member only when a later
  completed 4H observation confirms an EQ / REQ structure containing it.
- **Future 4H swing liquidity** would be a separate qualification path,
  owned by Swing Structure and not designed here. Not every 4H extreme is
  liquidity.

## 3. Source data

**Authority.**

- Canonical validated 1m (`timestamp_et = bar_end`) is the only price
  authority.
- Daily and 4H bars are built **only** by the existing
  `src/data/timeframes.build_timeframe()`. No other aggregator exists.
- Persisted M4 Parquet (`timeframe_store`) is a manifest-validated cache,
  never the authority.

**Bar definitions.**

- **Daily:** one bar per CME trading date, `[18:00 D−1, 17:00 D)` ET.
- **4H buckets:** 18:00–22:00, 22:00–02:00, 02:00–06:00, 06:00–10:00,
  10:00–14:00 and **14:00–17:00**.
  - The last bucket is intentionally clipped to the session close and
    flagged `is_session_truncated`.
  - When complete, it participates normally in 4H EQ / REQ.
  - Intentional clipping is not `is_complete=False`.
- **Availability:** every derived bar has `available_at = bar_end`, and
  every bar has a single contract (a mixed-contract bucket raises).

**DEVELOPMENT facts (read-only).**

| Item | Value |
|---|---|
| 1D bars | 248 (28 incomplete) |
| 4H bars | 1,472: 1,234 four-hour and 238 three-hour (14:00–17:00) |
| 4H incomplete | 29 |
| 4H start-time counts | 02:00 / 06:00 / 22:00 = 248, 10:00 = 247, 18:00 = 243, 14:00 = 238 |
| Contracts | 5 |

**Incomplete bars.** An incomplete Daily or 4H bar:

- produces **no** member or candidate;
- **breaks** EQ / REQ continuity;
- is never substituted.

## 4. Continuity segments

EQ / REQ links are allowed only **within one continuity segment per
timeframe**. A segment requires all three of:

1. **every expected source observation is present**;
2. **every source observation is complete** (`is_complete=True`);
3. **the contract is unchanged.**

**Expected-bucket continuity (clarification of D-134, 2026-10-03).**

- M3 emits **no row** for a bucket with zero source observations; empty
  buckets are never synthesized.
- Therefore **DataFrame row adjacency is not evidence of continuity**, and
  for 4H "same `trading_date`" is not evidence that two observed bars are
  consecutive.
- Both of these break the segment, and no candidate may link across either:
  - **(A)** an expected bucket emitted with `is_complete=False`;
  - **(B)** an expected bucket with **no row at all**.

**1D.** Two observed bars `p` → `q` are continuous only if:

- both are complete;
- the contract is unchanged;
- `previous_expected_session(q.trading_date).trading_date ==
  p.trading_date`.

A missing expected Daily session breaks the segment.

**4H.** Two observed bars `p` → `q` are continuous only if `q` is the
**next expected 4H bucket** after `p` under the existing M1 / M3 schedule,
both are complete, and the contract is unchanged.

- **Within a trading date**, the expected buckets are the M3 buckets:
  - anchored at the **regular** session open (18:00 ET);
  - `[anchor + k·240 min, anchor + (k+1)·240 min)`;
  - clipped to the **actual** session bounds from `session_bounds` with
    verified overrides applied;
  - buckets lying wholly outside the actual bounds do not exist.
  - On a regular day this gives 18:00, 22:00, 02:00, 06:00, 10:00 and
    14:00, the last clipped to 17:00. A verified shortened session yields
    its own, shorter schedule.
- **After the final expected bucket of a session**, the next expected
  bucket is the **first** bucket of the next **expected** trading session
  (`previous_expected_session` of that session is the earlier date).
- **Not allowed:**
  - computing continuity as "previous `bar_start` + 4 hours" across session
    boundaries;
  - hard-coding a permanent six-bucket day;
  - building another aggregator.

  The check runs over M3 outputs, with the M1 / M3 schedule as the
  authority.
- **Example:** 18:00–22:00 present, 22:00–02:00 absent (no row), 02:00–06:00
  present. The first and third bars are in **different** segments.

**Expected schedule source: resolved in stage EL-I0 (2026-10-03).** M3 now
exposes `src/data/timeframes.expected_timeframe_schedule(trading_dates,
timeframe, session_spec)`.

- It shares the bucket geometry with `build_timeframe` (same private
  helpers), and `build_timeframe` output is unchanged.
- It lists every expected bucket, including those with no source rows.
- External Liquidity continuity must use it, and must not re-derive the
  geometry.

**Fail closed.** A contract change, a missing expected session, a missing
expected bucket, a known roll gap or an incomplete bar ends the segment.
Nothing skips a gap, substitutes a source, or infers continuity from the
continuous symbol.

**DEVELOPMENT segment-break reasons: pre-amendment approximation.** These
counts were computed from row adjacency plus the session check, so they do
**not** count missing intra-session 4H buckets. The implementation
recomputes them under the rule above.

| | Contract change | Missing expected session | Incomplete bar | Segments (≥) |
|---|---|---|---|---|
| 1D | 4 | 3 | 43 | 51 |
| 4H | 4 | 3 | 50 | 58 |

**Continuity tests required at implementation** (synthetic):

1. complete adjacent 4H buckets → continuous;
2. middle 4H bucket emitted incomplete → break;
3. middle expected 4H bucket entirely absent → break;
4. two observed, non-adjacent 4H buckets on the same trading date → break;
5. final 14:00–17:00 bucket followed by the first bucket of the next
   expected trading session → continuous, when both are complete and the
   contract matches;
6. missing next expected trading session → break;
7. contract change between otherwise consecutive buckets → break;
8. a verified shortened-session schedule, when such a fixture exists, uses
   the actual expected schedule rather than a normal six-bucket day.

Plus the 1D equivalents: a consecutive expected session is continuous; a
missing expected session, an incomplete day or a contract change breaks.

**Daily sparsity.**

- Daily EQ / REQ is effectively absent on DEVELOPMENT.
- This is a **data-coverage limitation**: incomplete bars, an empty holiday
  / early-close calendar, roll gaps, and D1 deferred.
- The definition is **not** weakened to raise sample counts. Synthetic
  Daily fixtures validate the logic.

## 5. EQ / REQ formation (normative)

**Shared rules:**

- Highs compare only with highs (UPPER); lows only with lows (LOWER).
- Comparisons use integer ticks (`Decimal` tick from M2), and prices are on
  the tick grid.
- Adjacent bars are allowed. There is no pivot or fractal requirement and
  no lookahead.
- At least two members.

**EQ:** a tick distance of exactly 0.

**REQ:** neighbour distance ≤ **6 ticks**, joined by **chain
connectivity**: the connected components of the link graph.

- There is no averaged, centroid or mean level, and no first-member or
  last-member distance.
- Members keep their exact prices.
- There is no member cap.

**Formation barrier: pair-outer rule.** It is not an "untouched" rule. For
candidates `i < j` in the same segment and timeframe:

- **UPPER:** no source bar **strictly between** `i` and `j` has
  `high > max(price_i, price_j)`.
- **LOWER:** no source bar strictly between them has
  `low < min(price_i, price_j)`.
- Equality does not block. The confirming bar `j` is not tested. The rule
  is evaluated when `j` completes, using no future data.
- **EQ example:** A = B = 20,000 means no intervening high above 20,000.
- **REQ example:** A = 20,000 and B = 20,001.25. Movement inside the pair
  envelope is allowed; an intervening high above 20,001.25 blocks the link.

**Link and components.**

- `(i, j)` is a link iff tolerance holds **and** the barrier holds.
- At time `t`, the link graph contains the candidates with source
  completion ≤ `t`, and links decided at or before `t`. Links are decided
  only when the later endpoint completes.

**EQ vs REQ overlap.**

- EQ components use tolerance 0, and REQ components tolerance 6, under the
  same segment and barrier rules.
- An REQ component is emitted **only if it has ≥ 2 distinct prices.** A
  component with a single distinct price is EQ only.
  - `{100, 100}` → EQ.
  - `{100, 100, 102}` → EQ `{100, 100}` and REQ `{100, 100, 102}`.

**Growth.** A later candidate may extend a structure if it is in the same
segment and satisfies tolerance and the barrier with some current member.
There is no lifecycle-consumption cut-off in static discovery.

**Bridging.** A later member connecting two existing structures creates one
**MERGED** version (§9).

**DEVELOPMENT effect of the barrier** (structures with ≥ 2 members, before
the distinct-price rule):

| | REQ without barrier | REQ with barrier |
|---|---|---|
| 4H highs | 172 | 44 |
| 4H lows | 164 | 39 |

EQ goes from 17 to 1 (highs) and 19 to 3 (lows).

## 6. Session / reference liquidity

The definition is owned by External Liquidity and consumes M5 read-only.
**M5 is not modified**, and M6's target-session `market_context_levels`
helper is not reused, because liquidity has no time expiry.

| M5 context | Decision |
|---|---|
| `asia_2000_0000` | **Include** (H, L) |
| `london_0200_0500` | **Include** |
| `ny_premarket_0700_0900` | **Include** |
| `overnight_1800_0700` | **Include** |
| `previous_day` | **Reference / alias to the canonical Daily member** (§7); no separate member |
| `overnight_context_2000_0900` | **Exclude**: a composite overlapping the selected families |
| `previous_rth` | **Exclude initially**: not in the D-104 set. If added later, it is a separate semantic family with its own provenance (not excluded merely because its prices coincide with Daily) |

**What qualifies.** Only M5 `is_available` rows qualify, so incomplete or
missing windows produce no member. The member price is M5's observed
extreme, and `available_at` is M5's `available_at`.

**Entity grain.** One member per (context, target trading date, field). The
source ref is `M5_CONTEXT:<context_id>:<field>:<target_trading_date>` (M5's
natural key); M5's `source_trading_date` is kept for audit.

**Identical prices across families are not deduplicated.**

- London High = Overnight High means two members, each with its own
  provenance. A derived coincidence view may group them for display.
- DEVELOPMENT coincidences: London = Overnight on 62 highs / 54 lows; Asia
  = Overnight on 40 / 39.

## 7. Previous Day: reference to the canonical Daily member

- `previous_day.high` / `.low` for target D **is** the Daily high / low
  member of the previous expected trading session. **No duplicate member**
  is created.
- It is represented as a **derived reference view** (computed, not a
  canonical table, not an alias framework):

  | Column | Meaning |
  |---|---|
  | `target_trading_date` | M5 target D |
  | `previous_trading_date` | Previous expected trading date (M5 `source_trading_date`) |
  | `context_id` | `previous_day` |
  | `field` | `high` / `low` |
  | `m5_context_ref` | `M5_CONTEXT:previous_day:<field>:<D>` |
  | `member_id` | The canonical `DAILY_HIGH` / `DAILY_LOW` member of `previous_trading_date` |

- **Resolution:**
  - When M5's `previous_day` is unavailable (for example, a missing
    previous expected session), there is no reference row.
  - When it is available, the referenced Daily member **must** exist with
    the identical price. A mismatch raises; it is never silently resolved.

## 8. Canonical vs candidate; source time vs availability

**A liquidity member is a canonical liquidity fact, not any raw extreme.**

- Daily and selected session extrema are canonical immediately.
- A 4H extreme is canonical only once a confirmed EQ / REQ contains it.
  Unqualified 4H extrema are **transient candidates**: they appear in audit,
  charts and in-memory formation, never in `liquidity_members`.

| Member | `source_at` | `available_at` |
|---|---|---|
| Daily H / L | Daily `bar_end` | Daily `bar_end` |
| Session H / L | M5 window completion | M5 `available_at` (normally equal) |
| 4H EQ / REQ member | Its own 4H `bar_end` (t1) | Completion of the bar that **first** confirmed a structure containing it (t2 ≥ t1) |

- **Example:** A (high 20,000) closes at t1 and is only a candidate. B (high
  20,000) closes at t2 and forms an EQH with A. Then A has `source_at = t1`
  and `available_at = t2`; B has `source_at = available_at = t2`.
- There is no retrospective liquidity.
- **Later versions don't change a member.** Its `available_at` is that first
  confirmation and never changes; later versions reuse the member.
- Sequence pairs (`*_seq_domain`, `*_seq`) are null for the current bar
  data.

**Structure availability.**

- Formation: the confirming (second qualifying) member's completion.
- Extension: the new member's completion.
- Merge: the bridging member's completion.
- Never back-dated.

## 9. Immutable structure versions

- Every change of membership creates a new **content-addressed**
  `structure_id`. Earlier versions remain historical facts.
- `change_kind` is `FORMED`, `EXTENDED` (absorbs exactly one prior version)
  or `MERGED` (absorbs ≥ 2).
- `supersedes` is the canonical sorted tuple of the absorbed version ids.
- These describe **static version history only**, not lifecycle: no
  untouched, touched, swept, consumed or expired meaning.
- **No mutable or lineage id.** A merge selects no survivor. A lineage
  abstraction, if lifecycle needs one, is decided in 3.4.
- **REQ versions start at two distinct prices.** They are emitted only once
  the component has ≥ 2 distinct prices. The first emitted REQ version is
  `FORMED`, even when an equal-price component existed earlier; that
  history is the EQ structure's.

| Event (4H highs, one segment, barrier satisfied) | Emitted | `available_at` |
|---|---|---|
| A completes | nothing (candidate) | — |
| B links A | v1 {A,B} FORMED, supersedes () | B |
| C completes, no link | nothing (candidate) | — |
| D links B and C | v2 {A,B,C,D} EXTENDED, supersedes (v1) | D |
| Variant: {C,E} = v3 existed; D bridges | v4 {A,B,C,D,E} MERGED, supersedes (v1, v3) | D |

## 10. Canonical tables (two; no join table)

### `liquidity_members`

| Field | Class | Notes |
|---|---|---|
| `member_id` | generic | §11 |
| `liquidity_class` | generic (value `EXTERNAL`) | Internal uses `INTERNAL` |
| `member_kind` | generic field; External vocabulary | `DAILY_HIGH`, `DAILY_LOW`, `SESSION_REFERENCE_HIGH`, `SESSION_REFERENCE_LOW`, `HTF_EQREQ_HIGH`, `HTF_EQREQ_LOW` |
| `reference_family` | generic field; External values | `1D`, `4H`, or the M5 `context_id` |
| `orientation` | generic | `UPPER` / `LOWER` |
| `price` | generic | Exact tick-grid price |
| `source_ref` | generic | Canonical M7 `SourceRef` text: `HTF_BAR:<instrument>\|<contract>\|<tf>\|<bar_end UTC>` or `M5_CONTEXT:…` |
| `source_at`, `source_seq_domain`, `source_seq` | generic | Source observation completion |
| `available_at`, `available_seq_domain`, `available_seq` | generic | When it became liquidity |
| `instrument_id`, `contract_scope` (`SPECIFIC`), `contract` | generic | — |
| `definition_version` | generic | — |
| `source_trading_date`, `is_session_truncated` | External-specific audit (optional) | Not part of identity |

### `liquidity_structures` (EQ / REQ versions only)

| Field | Class | Notes |
|---|---|---|
| `structure_id` | generic | §11 |
| `liquidity_class` | generic | `EXTERNAL` |
| `structure_type` | generic | `EQ`, `REQ` |
| `reference_family` | generic | `1D` / `4H` |
| `orientation` | generic | — |
| `member_ids` | generic | Canonical sorted tuple |
| `available_at`, `available_seq_domain`, `available_seq` | generic | §8 |
| `instrument_id`, `contract_scope`, `contract` | generic | Shared by all members |
| `change_kind`, `supersedes` | generic | §9 |
| `definition_version` | generic | Tolerances and barrier live in the definition |

**Not stored:** min / max / outer price (derivable from members; add only if
performance needs it).

**No singleton structure rows** for Daily or session levels. The member is
the atom, and a uniform structure API gives no concrete simplification today
(3.4 lifecycle runs on members). If a future consumer proves otherwise, it
can be revisited then.

## 11. Identity (full SHA-256, M7 conventions)

**`member_id` = `"lm_" + sha256(json([...]))`** over:

- `definition_version`, `liquidity_class`, `member_kind`, `reference_family`,
  `orientation`;
- `instrument_id`, `contract_scope`, `contract`;
- the canonical `source_ref`.

Properties:

- **Source-identity based.** A promoted 4H member's id does **not** depend
  on its later `available_at`.
- **Timezone-canonical**, through canonical UTC inside refs.
- **Stable across** growth, merges and later versions.

**`structure_id` = `"ls_" + sha256(json([...]))`** over:

- `definition_version`, `liquidity_class`, `structure_type`,
  `reference_family`, `orientation`;
- `instrument_id`, `contract_scope`, `contract`;
- the canonical sorted `member_ids`.

It excludes `available_at`, `change_kind` and `supersedes`, and is
membership-order independent.

## 12. Contract scope and continuity

- `contract_scope = SPECIFIC` with an explicit contract, for every member
  and structure.
- There is no joining, stitching, or treating the continuous symbol as one
  physical history. A contract change breaks EQ / REQ continuity (§4).
- Session and Daily members are single-source facts (one contract). What
  happens to them after a roll is a 3.4 lifecycle question.

## 13. Relation to M6 / M7 (not integrated now)

**M6.** Future lifecycle feeds each active member directly:

- `level_id = member_id`;
- `level_value = price`;
- orientation;
- `available_at = member.available_at`;
- `contract_scope = SPECIFIC`;
- contract.

There is no reconstruction of formation time. For REQ, every exact member
price is independently evaluable.

**M7.**

- No State transitions or production Signals are created here.
- Shared Lifecycle (3.4) will use M7A over members. Structure status is
  derived from member states, which supports REQ partial consumption (e.g.
  REQH {100, 101, 102}: 100 consumed while 102 stays active).
- No lifecycle vocabulary is frozen here.

## 14. Common abstraction and future families

**Shared (small):**

- the two table schemas;
- deterministic `member_id` / `structure_id`;
- schema validation.

**External-specific:**

- the formation detector (segments, barrier, EQ / REQ, versions);
- the session adapter;
- the Previous Day reference view;
- the `member_kind` values.

There is **no** generic detector, registry, plugin, DSL or lifecycle engine.
Extraction is revisited when Internal Liquidity is the second real consumer.

**Internal Liquidity (3.2)** uses the same envelope, with
`liquidity_class=INTERNAL`, its own `reference_family` values (`1H`, `15m`,
`5m`, `1m`) and `member_kind` values. It is not pre-designed here.

**Swing Structure (3.3)** is a separate generic feature. It may later
qualify some HTF swings as External and lower-timeframe swings as Internal
Liquidity, with its own `member_kind`. That boundary is not decided here.

## 15. Audit outputs (implementation)

Dedicated audit outputs, not canonical tables, answer:

- the source observation behind each member, and its `source_at` vs
  `available_at`;
- candidates that never qualified;
- candidate pairs that failed tolerance or the **barrier**, and the
  blocking bar;
- formation, extension and merge events with supersession;
- segment breaks with their reasons;
- Previous Day reference resolution.

**Tracking.**

- **Tracked:** price-free CSVs of ids, kinds, families, timestamps, counts,
  change kinds and break reasons.
- **Local, Git-ignored:** price-bearing HTML or charts, following the M5 /
  M6 convention.

## 16. Visual validation (before freeze)

| Area | Cases |
|---|---|
| Daily | Standalone Daily High and Low; Daily EQH / EQL; Daily REQH / REQL; a structure confirmed over already-existing Daily members (synthetic fixtures where data is sparse) |
| 4H | Candidate High / Low that never qualifies; EQH / EQL confirmation; REQH / REQL confirmation; a historical candidate promoted later; `source_at` vs `available_at` |
| Barrier | Valid EQ with intervening touches only; EQ blocked by a strict trade-through; valid REQ with movement inside the pair envelope; REQ blocked beyond the outer pair price |
| Structures | Extension; merge; chain connectivity; an EQ subset inside a broader REQ; a pure-equal component producing EQ only |
| Session | Asia, London, NY Pre-market, Overnight; an identical price across two families; the Previous Day reference resolving to the canonical Daily member |
| Continuity | A contract boundary; a missing expected session; an incomplete Daily bar; an incomplete 4H bar; a valid 14:00–17:00 truncated 4H bucket |
| Timing | The source event; the confirmation event; the first causally eligible later consumer (strictly later, M6 / M7 rules) |

## 17. Resolved design questions (all closed 2026-10-03)

| # | Resolution |
|---|---|
| Q1 | Include Asia, London, NY Pre-market and Overnight (`overnight_1800_0700`). `previous_day` is a Daily reference. Exclude `overnight_context_2000_0900` and `previous_rth` |
| Q2 | Two tables; no join table |
| Q3 | A pure-equal component is EQ only; REQ needs ≥ 2 distinct prices |
| Q4 | Immutable content-addressed versions |
| Q5 | Bridge → one MERGED version; no survivor |
| Q6 | Members are lifecycle atoms; structure state is derived later (3.4) |
| Q7 | Canonical 1m → `build_timeframe`; M4 Parquet is a cache only |
| Q8 | Existing 4H buckets, including a complete 14:00–17:00 bucket |
| Q9 | Distinct session families are preserved; Previous Day is a Daily reference, not a duplicate |
| Q10 | Small common schemas plus ids only |
| Q11 | Pair-outer formation barrier |
| Q12 | Incomplete bars are excluded **and** break continuity |
| Q13 | Growth is allowed subject to continuity and the barrier; no lifecycle cut-off |
| Q14 | Generic Market Structure & Liquidity workstream (ROADMAP 3.x); no M8 numbering, no ICT prefix |

**No implementation-blocking questions remain.** Remaining choices are
implementation details within these rules: module and file placement,
function names, and the audit file layout.
