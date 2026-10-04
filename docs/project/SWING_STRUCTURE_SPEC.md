# Generic Swing Structure (3.2): Specification

**Status: DESIGN APPROVED — IMPLEMENTATION IN PROGRESS (rev 3,
2026-10-04; D-135 – D-138).**

- The semantic design is approved for implementation. The feature is
  **not frozen**.
- Implementation state (repository state only; semantics unchanged):
  - **SW-I0**, the shared continuity (D-137), is merged and complete
    (PR #12, `3b098f5`).
  - **SW-I1**, the canonical contract (`src/market_structure/swing.py`),
    is implemented, validated and design-authority approved, and
    committed on the active Swing implementation branch.
  - The swing detector is not implemented.
- Decisions **D-135 – D-138** (§26) are registered as ACTIVE — DESIGN
  APPROVED.

**Rev 3 changes (final design-authority decisions):**

- A plateau may span a session boundary: contiguity means consecutive
  expected observations in one segment (Q11).
- The source timing invariant is normative (§5).
- The `BAR_SPAN` format is fixed (Q9).
- The identity key is final.
- The shared continuity error is `ContinuityError` (Q12).
- Audit labels are intentionally not frozen (Q10).
- There are no implicit depth defaults. **2/2 is the explicit reference
  configuration** for validation on every timeframe (§6.1).

**Rev 2 changes:**

- Separated equal extremes are independent swings. Only a **strict**
  exceed fails a window. This replaces the rev 1 equality-blocking rule.
- A plateau is narrowly defined as the source of one extremum (§7.1).
- The canonical source identity is the **whole plateau** (`BAR_SPAN`), and
  `source_end_at` is canonical.
- 1m is included in v1 on canonical 1m bars.
- The shared continuity module goes to `src/data/continuity.py`.
- Table `swing_points`, orientation `UPPER` / `LOWER`.

**Context.**

- **Workstream:** Generic Market Structure & Liquidity (ROADMAP 3.2;
  D-133). The primitive is methodology-neutral, not an ICT feature.
- **Sequence:**
  1. 3.1 External Liquidity (APPROVED / FROZEN, D-134);
  2. **3.2 Swing Structure**;
  3. 3.3 Internal Liquidity;
  4. 3.4 Shared Liquidity Lifecycle.
- **Branch:** `swing-structure-design`, from `main` `db13d19`.
- **Inputs inspected:**
  - docs: ROADMAP, DECISION_LOG (D-104–D-107, D-113, D-116 / D-119,
    D-123, D-126 / D-127, D-129–D-134), ARCHITECTURE_MAP, WORK_PROGRESS,
    EXTERNAL_LIQUIDITY_SPEC;
  - code: `src/data/{sessions,timeframes,instruments}.py`,
    `src/state/contract.py`, `src/liquidity/contract.py`,
    `src/features/external_liquidity.py`;
  - tests: the M3 schedule, M7 State and External tests.

---

## 1. Purpose and architectural role

A **Swing High / Swing Low** is a generic, causally confirmed fact of market
structure. It is a source bar, or an equal-price plateau of consecutive
expected observations, whose
high (low) is not strictly exceeded by a fixed number of bars on each side,
on one timeframe.

```text
market observation (canonical 1m; M3 derived bars for higher timeframes)
    ↓
generic Swing Structure  (confirmed swing facts only)
    ↓
downstream classification (EQ/REQ, Internal / External Liquidity adapters, legs, ranges, BOS/MSS, trend …)
    ↓
State / Signal (M7)
    ↓
Strategy / Execution
```

A swing does **not** mean any of the following; all of them are downstream
interpretations:

- liquidity, support or resistance;
- a range boundary, target or invalidation;
- BOS, MSS or trend reversal;
- an entry or an order.

## 2. Non-scope

- No implementation, detector, persistence or adapter.
- No continuity extraction yet (§21 is a plan only).
- No Internal Liquidity, no Swing-based External Liquidity, no
  Swing-to-liquidity classification, no Shared Lifecycle.
- No BOS / MSS, trend-state machine, structural legs or zig-zag.
- No Range / Consolidation primitive (§7.1).
- No FVG / IFVG or Order / Rejection / Mitigation Blocks.
- No Signals, Strategy, Execution or D1.
- External Liquidity 3.1 (D-134) is frozen and untouched.

## 3. Terminology

| Term | Meaning |
|---|---|
| Timeframe bar | A canonical 1m bar (1m) or a `build_timeframe` row (5m–1D); `bar_end` labelled, ET |
| Segment | A fail-closed continuity segment of one timeframe: consecutive **expected** buckets, all present, all complete, one contract (§9) |
| Value | Integer tick index of `high` (UPPER) or of `low`, mirrored as `-low`, so that one "exceed = greater" rule serves both orientations (LOWER), as in External |
| Plateau | A maximal sequence of **consecutive expected source observations within one continuity segment** with exactly equal value on the tick grid (§7.1) |
| Candidate | A plateau whose left window is satisfied; transient and never canonical |
| Confirmed Swing | A candidate whose right window is satisfied; the only canonical fact |
| Strict exceed | A comparison bar with value strictly greater than the plateau value: a higher high, or a lower low |
| `L`, `R` | `left_depth`, `right_depth`: the number of bars required on each side |

## 4. Candidate Swing definition (confirmed pivot)

The definition is a **confirmed pivot / local extremum with delayed causal
availability**.

Within one segment, first identify the maximal plateau `P = [a..b]` with
value `h`.

- **Candidate:** `a − L ≥ 0` (the left window is inside the segment) and
  **no** value in `v[a−L .. a−1]` is **strictly greater** than `h`.
- **Confirmed** Swing (UPPER: Swing High; LOWER: Swing Low): `b + R` is
  inside the segment and **no** value in `v[b+1 .. b+R]` is **strictly
  greater** than `h`.
- **Equality in a window never fails a candidate.** A window bar equal to
  `h` can only be **non-adjacent**, because the plateau is maximal: the
  bars at `a−1` and `b+1` necessarily differ from `h`. Such a bar is a
  separate potential swing source (§7.2).
- Evaluation is deterministic: plateaus are found first, then each window
  is checked with integer tick comparisons. There is no epsilon.

**Why not the past-only structural extreme** ("this bar is higher than the
previous N")?

- It is a different primitive: a rolling or breakout extreme, knowable at
  bar close but asserting nothing about a turn.
- Most left-qualified bars are later strictly exceeded: 30,998 of 49,185
  candidates at 5m, N = 2 (§23).
- It may become a separately named feature later.
- No repository semantics conflict with delayed availability. External
  promotes a 4H candidate only at confirmation (D-134), and D-107 forbids
  look-forward.

## 5. Confirmation and causality (normative)

- **`source_at`** = `bar_end` of the **first** plateau bar `a`.
- **`source_end_at`** (canonical) = `bar_end` of the **last** plateau bar
  `b`. It equals `source_at` for a single-bar swing.
- **`available_at`** = `bar_end` of bar `b + R`, the final required
  confirming observation.
- **Source timing invariant (normative; a required future test).**
  Because `left_depth ≥ 1` and `right_depth ≥ 1`, every **confirmed**
  swing satisfies `source_at ≤ source_end_at < available_at`:
  - single-bar swing: `source_at == source_end_at < available_at`;
  - multi-bar plateau: `source_at < source_end_at < available_at`.
- A swing is **never** visible before `available_at`. Use at `source_at` is
  retrospective and forbidden.
- **Sequencing:** bars carry no sub-timestamp sequence, so both
  `*_seq_domain` / `*_seq` pairs are null. M7 `CausalKey` /
  `compare_causal` apply unchanged. There is no Swing-specific causal
  system.
- **Consumption:**
  - A **bar consumer** (M5 / M6 / M7 bar-boundary rule,
    `materialize_state_to_bars`) may see a swing iff
    `available_at ≤ bar_start`.
  - An **event consumer** obeys the M7 strict rule (`available_at` BEFORE
    `decision_at`).

## 6. Left / right depth

- **Two independent parameters, `left_depth ≥ 1` and `right_depth ≥ 1`.**
- **No implicit or hard-coded detector defaults.** Every Swing definition
  and generation request must supply both depths explicitly. There are no
  timeframe-specific constants.
- **`R = 0` is a different primitive** (the past-only extreme of §4).
- **`L = 0` is not a local extremum.** Every bar of a down-move followed
  by lower bars would qualify.

### 6.1 Reference Swing definition for validation

The **reference definition** is `left_depth = 2, right_depth = 2`. It is
the same on every supported timeframe (1m, 5m, 15m, 1H, 4H, 1D).

**What it is used for:**

- implementation validation;
- the DEVELOPMENT audit output;
- visual validation;
- regression baselines;
- initial cross-timeframe examples.

**What it is not:**

- It is **not** a claim that 2/2 is the universally correct or optimal
  swing scale.
- It is **not** hard-coded into the detector. Callers pass it explicitly.
- It does not imply timeframe-specific values (e.g. 5m = 3/3,
  4H = 1/1). Those exist only if a later explicit research definition
  requests them.

Other depths (e.g. 1/1, 3/3, 5/2) are legitimate explicit definitions
under the generic contract. They are separate research definitions,
outside the initial reference baseline.

Depths are **never** optimized with PnL or strategy performance during
Swing implementation.

## 7. Equality and plateau semantics

### 7.1 Adjacent equality is one plateau, and a plateau is not consolidation

**Definition (normative).** A Swing **plateau** is a maximal sequence of
**consecutive expected source observations within one continuity segment**
whose relevant extreme is **exactly equal on the instrument tick grid**:
equal highs for UPPER, equal lows for LOWER. It is only the source
representation of **one** swing fact.

- **Contiguity** means consecutive expected observations in one segment,
  not wall-clock adjacency.
- **Example:** in `105, 110, 110, 110, 106`, the three adjacent 110 highs
  form one plateau candidate.
- **Across a session boundary (Q11 resolved: YES).** A plateau may span a
  session boundary when all of the following hold:
  - the bars are consecutive expected observations in the same valid
    segment, for example a complete final 14:00–17:00 4H bucket followed
    by the next expected 18:00–22:00 bucket;
  - the relevant extreme is exactly equal;
  - both bars are complete;
  - the contract is the same;
  - no missing expected observation or session lies between them.
- **What does not break a plateau:**
  - the scheduled maintenance interval;
  - an expected weekend or session transition, when M1 / M3 identify the
    later bar as the next expected observation and continuity holds.
- **Any actual continuity break terminates the plateau.**
- **Swing price** is the shared exact source price, never averaged.
- **`source_at`** is the first plateau bar; **`source_end_at`** is the
  last.
- The **source identity** is the whole span (§15).
- **The plateau may extend while unconfirmed.** A further adjacent equal
  bar extends it, and confirmation counts `R` bars from the plateau's end.

**What a plateau is for.** It exists **only** to resolve the source
identity of **one** local extremum. It is **not**:

- consolidation, range or balance;
- accumulation, distribution or compression;
- support / resistance or liquidity.

Separated equal extremes are **not** one plateau. `110, 105, 110` contains
two potential Swing High sources.

**No range or consolidation concept enters Swing Structure.** There is no
`range_id`, `consolidation_id`, `range_high` / `range_low`,
`balance_state`, `inside_range` or `breakout_state`. A future generic Range
/ Consolidation primitive may consume confirmed swings, outside 3.2. The
design study found **no** dependency of swing detection on such a
primitive.

### 7.2 Separated equality gives independent swings

Equal extremes separated by lower price action (for highs), or higher
price action (for lows), are **independent** swing candidates.

- Each is evaluated on its own windows. An equal value is not a strict
  exceed, so **both** may confirm.
- Their equal price may later form **EQH / EQL** through the separate
  downstream EQ / REQ primitive. Swing Structure does not suppress
  turning-point facts because their prices are equal, and it does not
  classify them as EQ.

### 7.3 Required equality examples

Highs are shown for A, B and D, and lows for C.

| # | Bars | Depths | Result |
|---|---|---|---|
| A | `100, 110, 110, 105, 100` | `L=1, R=2` | **One** plateau Swing High at 110: `source_at` = t1, `source_end_at` = t2, available t4 |
| A′ | `105, 110, 110, 110, 106, 104` | `L=1, R=2` | One plateau t1–t3, available t5 |
| B | `100, 110, 105, 110, 100` | `L=R=1` | **Two** Swing Highs at 110: t1 (available t2) and t3 (available t4) |
| B′ | `98, 100, 110, 105, 110, 100, 99` | `L=R=2` | Two Swing Highs: t2 (available t4) and t4 (available t6). Each 110 lies in the other's window but is equal, not greater |
| C | lows `110, 100, 105, 100, 110` | `L=R=1` | **Two** Swing Lows at 100: t1 (available t2) and t3 (available t4) |
| D | `100, 110, 105, 111, 108, 107` | `L=1, R=2` | The 110 candidate is **invalidated**: 111 > 110 inside its right window. 111 is its own candidate and confirms at t5 |

EQ / REQ classification is downstream and independent of all of these.

## 8. Candidate invalidation

- A **strict exceed** in the right window means the candidate never
  becomes canonical. The exceeding bar is evaluated as its own candidate
  (Example B / D).
- A strict exceed in the left window means the bar is never a candidate.
- Candidates are transient. Invalid candidates are absent from the
  canonical table; their history is **audit-only** (§16).
- There are no candidate, invalidated or confirmed **states** in
  `swing_points`.

## 9. Continuity (fail closed)

- The whole window `a − L .. b + R` must lie inside **one** segment:
  - every expected bucket present;
  - every bar complete;
  - one contract.
- A missing expected bucket or session, an incomplete bar, or a contract
  change ends the segment.
- **No** substitution, stitching or continuous-symbol assumption.
- A candidate before a break cannot confirm with bars after it.
  **Example E:** `100, 103, 110, 106, ‖gap‖, 105` with `L=R=2`: t2 never
  confirms.
- A candidate whose left window would cross a segment start is not a
  candidate.
- Continuity follows the **expected** schedule, not wall time. So the
  14:00–17:00 bucket followed by the next session's 18:00 bucket is
  continuous, as is Friday close to Sunday open. This applies to windows
  and plateaus alike (§7.1).

## 10. Contract scope

`contract_scope = SPECIFIC`, and no swing spans a contract boundary.

- **Example F:** a candidate on contract A whose confirming bars are on B
  never confirms.
- On DEVELOPMENT every roll coincides with missing roll-week sessions.
- D1 (stitching) stays deferred.

## 11. Timeframe independence (normative)

The swing table of timeframe T is a function **only** of:

- T's canonical bars;
- T's `SwingDefinitionSpec`;
- T's completeness and continuity;
- T's contract history.

No other timeframe's swings affect whether a T-swing exists. The same input
and definition always give the same table. Detection is **not** top-down.

## 12. Cross-timeframe consumption

- A confirmed HTF swing may later be LTF context: an HTF boundary,
  reference level, range boundary, liquidity input, target or invalidation
  reference.
- Those meanings belong to the **consumer**. The canonical fact stays "a
  confirmed 4H Swing High".
- **No** interpretation columns: `is_boundary`, `is_liquidity`,
  `is_target`, `is_support`, `is_resistance`, `is_internal`,
  `is_external` or `liquidity_class` are all excluded.

## 13. HTF-to-LTF causal projection (normative)

**Example G:** a 4H source bar closes at 06:00. With `R = 2`, the
confirming bars are 06–10 and 10–14, so `available_at` = 14:00.

- 5m bars ending 06:05 … 14:00 **cannot** know it is a confirmed 4H swing.
  The historical source price existing is not the same as the swing
  classification being known.
- The first eligible 5m bar is 14:00–14:05 (`available_at ≤ bar_start`).
- It references the **same** `swing_id`. There is **no** 5m copy, and
  **no** `parent_swing_id` / `child_swing_id`.
- Provenance stays 4H. This is reference, not duplication, like Previous
  Day → Daily member in D-134.

**Future as-of view** (not implemented; no API name frozen): "HTF swings
confirmed as of t" is a filter on `timeframe`, `orientation` and
`available_at ≤ bar_start`. The schema already supports it.

## 14. Canonical schema: `swing_points`

The table holds confirmed swings only.

| Column | Type | Note |
|---|---|---|
| `swing_id` | str | `sw_` + full SHA-256 (§15) |
| `orientation` | `UPPER` / `LOWER` | Swing High / Swing Low. No HIGH / LOW alternative vocabulary |
| `timeframe` | str | `1m`, `5m`, `15m`, `1H`, `4H`, `1D` |
| `price` | float | The exact shared source extreme, on the M2 tick grid; off-grid fails. No averaging, no synthetic levels |
| `source_ref` | str | Plateau span ref (§15) |
| `source_at`, `source_seq_domain`, `source_seq` | tz, null, null | First plateau bar |
| `source_end_at` | tz | **Canonical.** Last plateau bar; equals `source_at` for a single bar |
| `available_at`, `available_seq_domain`, `available_seq` | tz, null, null | §5 |
| `instrument_id`, `contract_scope`, `contract` | str, `SPECIFIC`, str | §10 |
| `left_depth`, `right_depth` | int ≥ 1 | Persisted for direct auditability; part of identity |
| `definition_version` | str | E.g. `swing-pivot-v1`. It **fixes** the equality / plateau policy (§7); that policy is not a free parameter |

**Excluded:**

- **Derivable, so audit only:** source trading date,
  `is_session_truncated`, plateau bar count, segment index.
- **Interpretation, so never stored:** strength, major/minor,
  internal/external, liquidity class, parent/child, range or consolidation
  fields.
- **Lifecycle, so never stored:** any candidate status. There is no
  `supersedes`, no FORMED / EXTENDED / MERGED, and no lineage id.

**`SwingDefinitionSpec`** is a small, frozen builder input:
`definition_version`, `left_depth`, `right_depth` (validated ints ≥ 1).
There is no registry, no plugin framework and no per-timeframe config
machinery.

## 15. Identity

**Canonical plateau source ref** (Q9 resolved; format fixed):

```text
BAR_SPAN:<instrument_id>|<contract>|<timeframe>|<first_bar_end_utc>|<last_bar_end_utc>
```

- Both times use the existing canonical UTC serialization (M7
  `canonical_time`). The producer canonicalizes timezone, because M7 refs
  are opaque text.
- For a single-bar swing, `first_bar_end_utc == last_bar_end_utc`.
- `BAR_SPAN` identifies the canonical source observation span **only**.
  It does **not** contain orientation, price, depth, `available_at` or any
  liquidity classification. Those live in the identity key or schema as
  applicable.
- External Liquidity's frozen `HTF_BAR:` refs are **unchanged**.

**Natural key and id (final):**

```text
swing_id = "sw_" + sha256(canonical JSON of
    [definition_version, instrument_id, contract_scope, contract, timeframe,
     orientation, left_depth, right_depth, canonical BAR_SPAN source_ref])
```

**Excluded from the id:**

- `price` (validation checks it against the source bars);
- `available_at` (confirmation timing is not identity);
- candidate audit status;
- HTF / LTF context;
- liquidity interpretation.

**Consequences:**

- The plateau extent is part of identity. The same first bar with a
  different extent is a different source.
- Depths are part of identity. The same bar at `N = 2` and `N = 3` gives
  two facts.
- The id is order-independent and deterministic. It never depends on row
  order, file order, encounter order or audit order.

## 16. Candidate audit (audit-only, local)

The table is optional, local and never canonical.

**Required conceptual outcomes:**

- confirmed;
- invalidated by a strict exceed;
- insufficient left history;
- insufficient future coverage (data end);
- continuity break (segment end inside the right window).

**Q10 resolved: exact enum or string labels are intentionally not
frozen.**

- They are finalized during implementation. The audit only has to
  distinguish the five conceptual outcomes above.
- The candidate audit is **not** canonical swing state and has **no**
  downstream contract.
- Audit rows may carry prices locally, but never in tracked CSVs.

## 17. Timeframe support (v1)

- **Included:** 1m, 5m, 15m, 1H, 4H and 1D, with **identical** semantics.
- **1m** detection uses **canonical 1m bars directly**. They are not
  re-aggregated into another 1m dataset.
  - Continuity uses the expected schedule with a 1-minute bucket
    (`expected_timeframe_schedule` with `TimeframeSpec("1m", 1)`).
  - The trading date comes from `assign_trading_dates(..., label="bar_end")`.
  - Every observed canonical 1m bar is complete; a missing minute is a
    missing expected bucket.
  - The DEVELOPMENT cross-check matched the M3 path exactly: 33 / 33
    segments, identical breaks, identical highs and lows.
- **5m–1D** use M3 `build_timeframe` output. There is no new aggregator and
  no separate 4H / Daily derivation.
- 1D is sparse on DEVELOPMENT (28 incomplete days, 23 segments), a
  data-coverage limitation.

## 18. Nested swings, hierarchy and history

- **Nested swings** are expected and valid. There is no cross-timeframe
  deduplication: identical prices on different timeframes stay separate
  facts.
- **No parent/child links in v1.** If ever needed, a link would be a
  **derived** relation.
- **No strength or major/minor** classification.
- **No enforced high/low alternation.** Consecutive swing highs are
  allowed, and one bar may be both a Swing High and a Swing Low (an outside
  bar). Alternation is a downstream "legs" view.
- **No version history.** A confirmed swing is an immutable fact, and a
  later higher high does not erase it.

## 19. Relation to External / Internal Liquidity

- **External 3.1 is frozen and unchanged.** Ordinary 4H extremes become
  External Liquidity only through the approved 4H EQ / REQ path.
- A future Swing-based path would be a **separate** classification with
  `swing_id` provenance, never merged into the EQ / REQ promotion rule.
- **Internal Liquidity (3.3)** may classify selected swings through an
  adapter, without changing swing identity.
- EQH / EQL over separated equal swings is a downstream EQ / REQ concern
  (§7.2).

## 20. Relation to future BOS / MSS

- Future structural-break logic may consume confirmed swings (with source,
  availability and timeframe).
- Whether BOS / MSS is generic or ICT/SMC stays **open** (ROADMAP 4).

## 21. Shared continuity (decided; implemented and validated in SW-I0, merged in PR #12)

Swing is the **second real consumer**. The **first implementation
prerequisite** is to extract the continuity logic to
**`src/data/continuity.py`**. That is the data layer, next to
`timeframes.py` and `sessions.py`, which repository inspection favours.

**Generic content only:**

- expected-schedule segmentation;
- missing expected bucket;
- missing expected session;
- incomplete observation;
- contract change;
- the existing break precedence (`MISSING_EXPECTED_SESSION >
  MISSING_EXPECTED_BUCKET > INCOMPLETE_BAR > CONTRACT_CHANGE`), with the
  contract flag always kept;
- the break audit row.

**What is identical today and what is not.**

- `external_liquidity.continuity_segments` is already
  timeframe-parameterized with no External semantics. The probe ran it
  unchanged for canonical 1m and for 5m–1D.
- Only the exception type and the module location are External-specific.
- No segment object is needed: `list[DataFrame]` plus a break frame
  suffices.

**Error type (Q12 resolved).** The generic exception is `ContinuityError`,
in `src/data/continuity.py`. The generic continuity layer must **not**
depend on External Liquidity, Swing Structure, liquidity contracts or any
strategy concept.

**External compatibility.**

- External keeps a compatibility re-export or wrapper
  (`continuity_segments`, the break constants).
- Its boundary may catch `ContinuityError` and translate it to
  `ExternalLiquidityError` where needed, to preserve its frozen public
  behaviour.

**Parity proof required.**

- Exact frame equality with the frozen DEVELOPMENT baseline:
  - members 2,553;
  - structures 86;
  - Previous Day references 438;
  - candidates 3,326;
  - continuity breaks 50;
  - barrier blocks 412.
- Direct equality of the segments and breaks for 1D and 4H.
- The existing External tests and a full regression.

## 22. Validation plan (future implementation)

Workflow: specification → causal review → unit and invariant tests →
negative tests → audit exports → visual validation → human approval →
freeze → downstream use.

**Reference configuration.** The DEVELOPMENT audit, visual validation and
regression baselines use the explicit **2/2 reference definition** on
every timeframe (§6.1).

**Required tests:**

- every generation request requires explicit depths; there is no implicit
  default;
- valid high and valid low;
- strict invalidation plus the successor candidate;
- insufficient left history, and insufficient future coverage (data end
  and segment end);
- adjacent plateaus of 2 and 3 bars, with the exact `BAR_SPAN` ref and
  `source_end_at`;
- a plateau spanning the 14:00–17:00 → 18:00 expected session boundary is
  one plateau, while any actual continuity break terminates a plateau;
- separated equal highs and lows, **both** confirming inside each other's
  window (§7.3 B, B′, C);
- equality never invalidates, while a one-tick exceed does;
- missing expected bucket, missing session, incomplete bar and contract
  roll;
- a complete session-truncated 14:00–17:00 bucket, and a verified
  shortened session;
- 1m from canonical bars equals the M3 1m path;
- deterministic identity:
  - shuffled input;
  - a depth change gives a new id;
  - a plateau-extent change gives a new id;
  - price and `available_at` are excluded;
- the source timing invariant:
  - single bar: `source_at == source_end_at < available_at`;
  - plateau: `source_at < source_end_at < available_at`;
  - `available_at` is exactly `R` expected observations after
    `source_end_at`;
- no retrospective consumption (`available_at ≤ bar_start`);
- per-timeframe independence;
- HTF context unavailable before HTF `available_at`;
- no cross-timeframe duplicate rows;
- off-grid price fails;
- External parity for the continuity extraction, with `ContinuityError`
  translated at External's boundary.

## 23. DEVELOPMENT descriptive evidence (rev 2; read-only)

**Scope of the probe.**

- DEVELOPMENT only, in scratch, with no repository module added.
- 1m uses canonical 1m bars; 5m–1D use M3. All use the existing
  `continuity_segments`.
- `L = R = N`. No PnL, no performance, **no depth chosen**.
- **Continuity segments:** 1m 33, 5m 32, 15m 31, 1H 29, 4H 29, 1D 23.
- **Complete segment bars:** 337,815 / 67,552 / 22,506 / 5,614 / 1,443 /
  220.

**Amended rule.**

- Spacing is the median number of bars between source bars within a
  segment.
- "Plateau" is the number of adjacent-plateau swings.
- "Separated-equal" is the number of swings whose window contains a
  separated equal extreme (exactly the swings the rev 1 rule blocked).
- "Change" is the change vs the rev 1 blocking rule.

| tf | N | highs | lows | % bars | spacing H / L / any | plateau | separated-equal | change |
|---|---|---|---|---|---|---|---|---|
| 1m | 1 | 74,498 | 74,945 | 44.24 | 4 / 4 / 2 | 7,124 | 0 | 0 |
| 1m | 2 | 46,516 | 46,819 | 27.63 | 6 / 6 / 3 | 4,624 | 4,866 | +4,866 (+5.50 %) |
| 1m | 3 | 33,467 | 33,478 | 19.82 | 9 / 9 / 4 | 3,309 | 4,105 | +4,105 (+6.53 %) |
| 1m | 5 | 21,092 | 21,308 | 12.55 | 14 / 14 / 7 | 2,120 | 2,861 | +2,861 (+7.24 %) |
| 5m | 1 | 14,879 | 15,062 | 44.32 | 4 / 4 / 2 | 654 | 0 | 0 |
| 5m | 2 | 9,040 | 9,118 | 26.88 | 6 / 7 / 3 | 422 | 380 | +380 (+2.14 %) |
| 5m | 3 | 6,431 | 6,539 | 19.20 | 9 / 9 / 5 | 290 | 309 | +309 (+2.44 %) |
| 5m | 5 | 4,072 | 4,138 | 12.15 | 15 / 14 / 7 | 185 | 197 | +197 (+2.46 %) |
| 15m | 1 | 4,973 | 5,090 | 44.71 | 4 / 4 / 2 | 101 | 0 | 0 |
| 15m | 2 | 2,982 | 3,055 | 26.82 | 7 / 6 / 3 | 66 | 47 | +47 (+0.78 %) |
| 15m | 3 | 2,143 | 2,222 | 19.39 | 9 / 9 / 4 | 43 | 49 | +49 (+1.14 %) |
| 15m | 5 | 1,339 | 1,371 | 12.04 | 15 / 14 / 7 | 26 | 35 | +35 (+1.31 %) |
| 1H | 1 | 1,234 | 1,267 | 44.55 | 4 / 4 / 2 | 9 | 0 | 0 |
| 1H | 2 | 716 | 736 | 25.86 | 6 / 7 / 3 | 5 | 11 | +11 (+0.76 %) |
| 1H | 3 | 517 | 503 | 18.17 | 8 / 9 / 5 | 2 | 8 | +8 (+0.79 %) |
| 1H | 5 | 311 | 310 | 11.06 | 15 / 15 / 7 | 1 | 4 | +4 (+0.65 %) |
| 4H | 1 | 315 | 300 | 42.62 | 4 / 4 / 2 | 0 | 0 | 0 |
| 4H | 2 | 180 | 187 | 25.43 | 7 / 6 / 3 | 0 | 0 | 0 |
| 4H | 3 | 130 | 141 | 18.78 | 7 / 7 / 5 | 0 | 1 | +1 (+0.37 %) |
| 4H | 5 | 77 | 75 | 10.53 | 12 / 14 / 6 | 0 | 0 | 0 |
| 1D | 1 | 36 | 43 | 35.91 | 3 / 4 / 1.5 | 0 | 0 | 0 |
| 1D | 2 | 16 | 16 | 14.55 | 7 / 5 / 3.5 | 0 | 0 | 0 |
| 1D | 3 | 10 | 12 | 10.00 | 12 / 5.5 / 3.5 | 0 | 0 | 0 |
| 1D | 5 | 3 | 3 | 2.73 | 20 / 11 / 7 | 0 | 0 | 0 |

**Comparison with the rev 1 blocking rule.**

- The rev 1 totals were reproduced exactly.
- Every rev 1 swing is still a swing under rev 2. The amendment only
  **adds** facts.
- **N = 1 is unchanged.** With a one-bar window, an equal neighbour is
  always adjacent and therefore part of the plateau.
- **Added at N = 2 / 3 / 5:**
  - 1m: +5.5–7.2 %;
  - 5m: +2.1–2.5 %;
  - 15m: +0.8–1.3 %;
  - 1H: +0.7–0.8 %;
  - 4H: one swing (N = 3);
  - 1D: none.
- **Spacing** tightens by at most one bar at 1m and 5m. For example, 1m
  N = 2 same-side spacing went from 7 to 6.
- **Both members of a separated equal pair confirm** (the next swing on the
  same side starts within R bars of the previous plateau's end, at the same
  price):

  | N | 1m | 5m | 15m | 1H | 4H | 1D |
  |---|---|---|---|---|---|---|
  | 2 | 892 | 74 | 9 | 1 | 0 | 0 |
  | 3 | 968 | 68 | 8 | 1 | 0 | 0 |
  | 5 | 821 | 61 | 9 | 1 | 0 | 0 |

  These are exactly the "double top / bottom" facts that rev 1 suppressed.
  They are now exposed for downstream EQH / EQL.

**Other observations.**

- **Plateau lengths at N = 2:**
  - 1m: 4,410 of length 2, 202 of length 3, 12 of length 4;
  - 5m: 412 / 9 / 1;
  - 15m: 66 of length 2;
  - 1H: 5 of length 2;
  - 4H and 1D: none.
- **Delay** is `R` for a single bar, plus `plen − 1` for a plateau
  (maximum `R + 3`).
- **Density** is scale-free from 1m to 4H: about 43–45 / 25–28 / 18–20 /
  10.5–12.6 % for N = 1 / 2 / 3 / 5. 1D is lower because of short
  segments. Depth, not timeframe, governs density. This is descriptive
  only.
- **Continuity:** 11–44 candidates are lost per timeframe and depth at
  segment ends (1D 11–19; intraday 22–44). Insufficient left history at
  segment starts is about `N` × segments × 2.
- **Session-truncated 4H source bars** appear in 67 of 367 4H swings at
  N = 2 and participate normally.

**Cross-timeframe as-of study** (rev 2, N = 2, descriptive; HTF swings
never alter LTF detection).

| pair | HTF swings | median LTF bars between HTF `source_at` and `available_at` | HTF swings with an LTF swing at the same price in the HTF source bar | median lead (LTF available before HTF confirmation) | median LTF swings available in that interval |
|---|---|---|---|---|---|
| 4H→15m | 367 | 28 | 100 % | 9.50 h | 8 |
| 4H→5m | 367 | 84 | 100 % | 9.92 h | 24 |
| 1H→15m | 1,452 | 8 | 100 % | 2.00 h | 2 |
| 1H→5m | 1,452 | 24 | 100 % | 2.42 h | 7 |

**Samples.**

| pair / orientation | HTF `source_at` → `available_at` | LTF bars between | lead | LTF swings before / after (same span) |
|---|---|---|---|---|
| 4H→5m UPPER | 2024-12-13 10:00 → 17:00 | 84 | 7 h 00 m | 16 / 0 |
| 4H→5m UPPER | 2025-06-30 06:00 → 14:00 | 96 | 8 h 10 m | 24 / 11 |
| 4H→15m LOWER | 2024-06-24 17:00 → 06-25 02:00 | 32 | 9 h 15 m | 5 / 11 |
| 1H→15m LOWER | 2024-12-20 08:00 → 10:00 | 8 | 2 h 00 m | 0 / 1 |
| 1H→5m LOWER | 2025-06-30 15:00 → 17:00 | 24 | 2 h 05 m | 6 / 0 |

**Interpretation.** The HTF swing price was already an LTF swing hours
before the HTF swing was confirmed. Keying HTF context on `source_at`
would leak the HTF classification about 10 h (4H) or about 2 h (1H) early,
so HTF context must use `available_at`.

## 24. Visual evidence (local, Git-ignored)

The file is `reports/validation/swing_structure_design_visual.html`. It is
price-bearing, covered by an exact `.gitignore` entry, and opens
standalone. It was regenerated for rev 2 with 24 sections. It uses N = 2,
which is the 2/2 reference configuration (§6.1).

- **REAL DEVELOPMENT (13):**
  - HTF→LTF causal boundaries 4H→5m and 1H→15m, with the "not known" band
    and the LTF same-price pivot;
  - a clean 4H Swing High and a clean 4H Swing Low;
  - a swing on a session-truncated 4H bar;
  - an invalidated 1H candidate;
  - 15m two-bar and 5m three-bar plateaus;
  - separated equal highs giving two swings (15m);
  - separated equal lows giving two swings (5m);
  - a 4H continuity break and a 4H contract roll;
  - nested 4H / 1H / 5m swings.
- **SYNTHETIC (11), the exact normative examples:**
  - A (valid high), B (invalidation and successor), D (valid low);
  - Equality A, A′, B, B′, C and D (§7.3);
  - E (continuity break) and F (contract roll).

## 25. Design questions: all resolved

| # | Question | Resolution |
|---|---|---|
| Q1 | Default depths | No implicit or hard-coded default; every definition supplies both depths. 2/2 is the explicit **reference** configuration for validation on all timeframes (§6.1) |
| Q2 | Separated equal extremes | Independent swings (§7.2) |
| Q3 | `source_end_at` | Canonical (§5, §14) |
| Q4 | 1m | Included, on canonical 1m bars (§17) |
| Q5 | Shared continuity location | `src/data/continuity.py` (§21) |
| Q6 / Q9 | Plateau source ref | `BAR_SPAN:<instrument_id>\|<contract>\|<timeframe>\|<first_bar_end_utc>\|<last_bar_end_utc>`, format fixed (§15) |
| Q7 | Orientation | `UPPER` / `LOWER` |
| Q8 | Table | `swing_points` |
| Q10 | Audit labels | Intentionally not frozen; only the conceptual outcomes are required (§16) |
| Q11 | Plateau across a session boundary | Yes, within one continuity segment over consecutive expected observations; any actual break terminates it (§7.1) |
| Q12 | Continuity error | `ContinuityError` in `src/data/continuity.py`; External may translate it (§21) |

**No semantic questions remain open.** The rev 2 DEVELOPMENT evidence at
N = 2 (§23) already matches the 2/2 reference configuration. Its plateau
detection already treated consecutive expected observations within a
segment, including across session boundaries, as contiguous.

## 26. Final design and decisions (D-135 – D-138)

**Approved semantic design (rev 3):**

- **Definition:**
  - a confirmed pivot / local extremum;
  - explicit `left_depth ≥ 1` and `right_depth ≥ 1`, with no implicit
    defaults;
  - 2/2 is the explicit reference configuration for validation on all
    supported timeframes, not a hard-coded or universally preferred scale.
- **Equality:**
  - maximal equal extremes over consecutive expected observations form one
    plateau;
  - equality outside the plateau does not invalidate another swing;
  - only a strictly greater high (lower low) invalidates a window;
  - separated equal extremes may confirm independently.
- **Timing and identity:**
  - `source_at` = first plateau bar completion;
  - `source_end_at` = last plateau bar completion;
  - `available_at` = completion of the final required right-confirmation
    bar;
  - canonical source `BAR_SPAN`;
  - identity independent of `available_at`.
- **Timeframes:**
  - 1m / 5m / 15m / 1H / 4H / 1D;
  - 1m on canonical source bars, higher timeframes on M3 bars;
  - detection independent per timeframe.
- **Cross-timeframe use:**
  - causal as-of projection only;
  - the same `swing_id` is referenced, with no LTF copy.
- **Continuity and contract:**
  - `SPECIFIC` contract scope;
  - fail-closed continuity;
  - complete session-truncated bars are valid.
- **Excluded:**
  - no parent/child hierarchy;
  - no strength or major/minor classification;
  - no version DAG;
  - candidate history is audit-only;
  - no `liquidity_class`.
- **Naming:** table `swing_points`, orientation `UPPER` / `LOWER`.

**Registered decisions:** ACTIVE — DESIGN APPROVED (2026-10-04). They are
mirrored in DECISION_LOG, promoted from proposals P-SW-1 … P-SW-4.

- **D-135: canonical causal Swing Structure (plateau-aware confirmed
  pivot).**
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
- **D-136: timeframe independence and causal projection.**
  - The swings of a timeframe depend only on that timeframe's bars,
    definition, continuity and contract history.
  - A confirmed HTF swing may be referenced by an LTF bar consumer only
    when HTF `available_at ≤` LTF `bar_start`. Event consumers obey the M7
    strict causal rule.
  - The same `swing_id` is referenced. There are no LTF copies, no
    parent/child links, no strength or hierarchy, and no interpretation or
    liquidity columns.
- **D-137: shared expected-schedule continuity extraction.**
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
- **D-138: canonical Swing table and identity.**
  - The canonical table is `swing_points` (§14), with orientation
    `UPPER` / `LOWER`.
  - Builder input is a small `SwingDefinitionSpec(definition_version,
    left_depth, right_depth)`. The equality / plateau policy is fixed by
    `definition_version`. Depths are persisted on rows, and there is no
    registry.
  - The canonical source ref is
    `BAR_SPAN:<instrument_id>|<contract>|<timeframe>|<first_bar_end_utc>|<last_bar_end_utc>`,
    using the canonical UTC serialization. It contains no orientation,
    price, depth, `available_at` or classification. External's `HTF_BAR`
    refs are unchanged.
  - `swing_id` = `sw_` + full SHA-256 over `definition_version`,
    `instrument_id`, `contract_scope`, `contract`, `timeframe`,
    `orientation`, `left_depth`, `right_depth` and the canonical
    `BAR_SPAN` `source_ref`. It excludes price, `available_at`, candidate
    audit status, HTF / LTF context and liquidity interpretation.
