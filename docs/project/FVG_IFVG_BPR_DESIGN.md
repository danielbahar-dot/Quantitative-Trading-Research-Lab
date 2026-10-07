# FVG / IFVG / Overlap / BPR (ROADMAP: ICT family after liquidity): Consolidated Design (rev 1, draft)

**Status: DESIGN DRAFT FOR REVIEW — NOT APPROVED, NOT IMPLEMENTED, NOT FROZEN (2026-10-07).**

- Branch `fvg-design`, created from `main` at `6c3c909` (after the Internal
  Liquidity freeze).
- This document specifies the design only. No FVG code exists. No frozen
  module (M3, continuity, Swing, Market Structure, External / Internal
  Liquidity, M7) changes.
- The settled requirements (§1) are treated as approved input. Routine
  representation choices are made and documented (§3). Genuine unresolved
  semantic choices are gathered in one dependency-ordered list (§9), with
  recommendations, tradeoffs and worked examples.
- Every worked example (§5) was **executed** against the frozen M3 builder,
  continuity segmentation, 1m reset adapter and Swing detector with a
  scratch verification prototype (not committed). The DEVELOPMENT design
  evidence (§5.9) comes from the same prototype. §10 separates arguments,
  planned tests and executed checks.

---

## 0. Contents

1. Settled requirements and existing contracts relied on
2. Requirement → section mapping
3. Design
   - 3.1 Observations, ticks and continuity
   - 3.2 Formation and the zone fact
   - 3.3 Volatility-normalized width (descriptive; recommendation)
   - 3.4 Directional lifecycle: FVG → IFVG → RETIRED
   - 3.5 Mitigation (1m)
   - 3.6 Causal batch and timestamp semantics
   - 3.7 Overlap relationships: FVG_OVERLAP, BPR, MTF_BPR
   - 3.8 BPR objects and lifecycle
   - 3.9 Priority and grading
   - 3.10 First FVG in a directional swing leg
   - 3.11 Missing data, contract changes, price basis and future adjustment
   - 3.12 Output tables, M7A namespaces and strategy-facing views
   - 3.13 Identity, immutable versions and provenance
4. Consistency check
5. Worked examples (executed)
6. Invariants
7. Planned tests, prefix replays and visual-validation cases
8. Integration and implementation milestones
9. Genuine unresolved decisions (dependency order)
10. Arguments vs planned tests vs executed checks

---

## 1. Settled requirements and existing contracts relied on

### 1.1 Settled requirements (from the design authority, 2026-10-07)

| Id | Requirement (abridged; the request text is authoritative) |
|---|---|
| R-A1 | Six timeframes independently: 1m, 5m, 15m, 1H, 4H, 1D |
| R-A2 | Three consecutive complete observations within valid continuity; bullish `low(C3) > high(C1)`, bearish `high(C3) < low(C1)`; ≥ 1 tick; equality is not an FVG; no displacement, body or size filter |
| R-A3 | Available only when C3 closes; never used before confirmation; never tested against its own formation bars |
| R-A4 | Original and current direction; lower, midpoint, upper; original width in ticks and points; source timeframe; three-bar evidence; source span; `available_at`; stable identity; causal lifecycle / provenance |
| R-A5 | Exact midpoint (half-tick valid; never rounded) |
| R-A6 | Retracement evaluation order: bullish upper → midpoint → lower; bearish lower → midpoint → upper |
| R-B1 | Lifecycle `FVG → IFVG → RETIRED`; mitigation is an attribute within a stage, not an exit |
| R-B2 | Mitigation on canonical 1m; strict wick / range penetration; near-boundary touch is not mitigation; record first mitigation time, penetration depth, midpoint reach and full-zone reach separately; distinguish FVG and IFVG stages |
| R-B3 | Conversion / retirement by a close on the zone's own timeframe, strictly beyond the far bound; equality and wicks never convert or retire |
| R-B4 | IFVG inherits bounds and reverses direction; no repeated inversion (an invalidated IFVG retires) |
| R-B5 | The conversion bar is never a subsequent IFVG retest; same-close ordering consistent with classify-before-admit; simultaneous mitigation and conversion explained |
| R-B6 | Retired zones stay for audit, not actionable |
| R-C1 | Explicit deterministic priority: 1. timeframe, 2. qualifying overlap / confluence, 3. original width (all ascending in priority) |
| R-C2 | Record component attributes; original width preserved through inversion; mitigation never rewrites bounds or width |
| R-C3 | Volatility-normalized width as descriptive data only, parameters as recommendations |
| R-C4 | No proximity, directional bias, profitability or arbitrary weights |
| R-D1 | Zones stay separate; same-direction overlap `FVG_OVERLAP`; opposite-direction `BPR`; cross-timeframe opposite `MTF_BPR` |
| R-D2 | BPR bounds = positive-width intersection (max of lowers, min of uppers, exact midpoint); zero-width contact is not BPR |
| R-D3 | BPR direction = later parent's direction by causal `available_at`; later parent's timeframe governs invalidation; simultaneous availability → direction undefined / descriptive |
| R-D4 | Earlier parent may be active FVG or IFVG; a retired parent cannot create relationships or contribute to grading; history preserved |
| R-D5 | A formed BPR has its own lifecycle, independent of later parent retirement: retires on a governing-timeframe close strictly beyond its opposing far boundary; never inverts |
| R-D6 | Causal relationship creation, immutable parent refs, unique ids, deduplication, prospective grading updates, no confluence inflation from repeated versions of one physical zone |
| R-E1 | No age limit and no same-contract-only limit |
| R-E2 | Future shared contract adjustment must propagate to every POI; preserve raw values and source contract; record basis and adjustment version; compare cross-contract only on a valid shared adjusted basis; never compare raw prices across contracts or invent a local adjustment; expose pending comparisons; preserve previous runs |
| R-E3 | Distinguish rollover from missing data; missing / incomplete data → terminate affected actionable continuity-dependent state, flag, re-establish from valid subsequent data; never infer events inside unobserved intervals or revive terminated zones |
| R-F1 | Mark the first qualifying directional FVG in a swing leg using the same-timeframe confirmed Swing; causal; association time separate from formation time; no rewriting of historical strategy-visible state |
| R-F2 | Marker survives mitigation while the FVG is active; ends at conversion; IFVG does not inherit it; no promotion of a later FVG; original association preserved |

### 1.2 Existing contracts relied on (all frozen or approved; unchanged)

| Contract | Decision | What FVG uses |
|---|---|---|
| Canonical 1m bars; bar-end labelling; ET | CLAUDE.md, D-111 | Mitigation source; `timestamp_et = bar_end` |
| M3 timeframe builder | D-116, D-119 | 5m–1D observations, `is_complete`, `available_at = bar_end`, regular-session anchoring; a bucket mixing contracts **raises** |
| Expected-schedule continuity | D-137 | Segments define "consecutive complete observations within valid continuity" |
| Swing Structure (2/2 reference `swing-pivot-v1`) | D-135 – D-138 | Leg boundaries for the first-FVG marker; `BAR_SPAN` source refs |
| Market Structure batch and resets | D-141, D-142 | Classify-before-admit batch; §G.2a reset adapter (`DATA_GAP`, `CONTRACT_CHANGE`, CB-1 / CB-2); explicit `replay_cutoff`; prefix equivalence |
| M7A State contract | D-129 – D-131 | Lifecycle namespaces, causal keys, one transition per entity and trigger |
| Conservative gap treatment | D-142, D-147 | Termination at the 1m gap onset; post-gap re-establishment only |

Not used: the liquidity consumption predicate (D-143) is tolerance-based and
liquidity-specific; FVG mitigation is a strict penetration without
tolerance. Frozen M6 level interactions are not used (they assume fixed
approach semantics; same reasoning as D-139).

---

## 2. Requirement → section mapping

| Requirement | Sections | Examples | Invariants | Planned tests |
|---|---|---|---|---|
| R-A1 | 3.1, 3.6 | W1, W2, W4, §5.9 | FVG-INV-1 | T-F1, T-F9 |
| R-A2 | 3.1, 3.2 | W1, W3 | FVG-INV-1, -2 | T-F2 … T-F5 |
| R-A3 | 3.2, 3.6 | W1, W2 | FVG-INV-3 | T-F6, T-L2 |
| R-A4, R-A5 | 3.2, 3.13 | W1, W3 | FVG-INV-2, -4 | T-F7, T-F8 |
| R-A6 | 3.5 | W1 | FVG-INV-7 | T-M1 |
| R-B1, R-B2 | 3.4, 3.5 | W1, W2 | FVG-INV-6 … -8 | T-M1 … T-M6 |
| R-B3, R-B4 | 3.4 | W1, W4 | FVG-INV-9, -10 | T-L1 … T-L5 |
| R-B5 | 3.6 | W2 | FVG-INV-11 | T-L6, T-L7 |
| R-B6 | 3.4, 3.12 | W1 | FVG-INV-12 | T-L8 |
| R-C1 … R-C4 | 3.9, 3.3 | W5, §5.7 | FVG-INV-17, -18 | T-G1 … T-G6 |
| R-D1, R-D2 | 3.7 | W4, W5 | FVG-INV-13, -14 | T-O1 … T-O4 |
| R-D3 | 3.7.4 | §5.6 | FVG-INV-15 | T-O5, T-O6 |
| R-D4 … R-D6 | 3.7, 3.8, 3.13 | W4 | FVG-INV-15, -16 | T-O7 … T-O10, T-B1 … T-B4 |
| R-E1 … R-E3 | 3.11 | W7, W8 | FVG-INV-19 … -21 | T-D1 … T-D6 |
| R-F1, R-F2 | 3.10 | W6a, W6b | FVG-INV-22 … -24 | T-S1 … T-S7 |

---

## 3. Design

### 3.1 Observations, ticks and continuity

- **Observations.** 1m: canonical 1m bars (as Swing). 5m, 15m, 1H, 4H, 1D:
  M3 observations (`build_timeframe`). Each timeframe is processed
  independently (D-136 style); no cross-timeframe input enters formation.
- **Tick grid.** All comparisons are integer ticks from the instrument
  metadata (MNQ 0.25). Bounds are tick-aligned because they are observed
  highs / lows. A non-aligned source price fails closed.
- **Complete and consecutive.** C1, C2, C3 are three consecutive expected
  observations of one continuity segment (`continuity_segments`, D-137):
  all present, all `is_complete`, one contract. Complete session-truncated
  bars are valid (as for Swing).
  - A triple may span an expected session boundary or the weekend, because
    expected-schedule continuity does (a Friday–Monday Daily triple is
    valid; so is a 16:55 / 17:00 / 18:05 5m triple). This follows from
    "within valid continuity" and is not a new rule.
  - A missing or incomplete observation or a contract change ends the
    segment, so no triple spans it.
- **Mixed-contract buckets.** Frozen M3 raises on a bucket that mixes
  contracts (D-119). A pure intraday roll that is not on a bucket boundary
  therefore fails closed for the affected timeframes until shared roll
  handling exists. FVG does not work around it. On DEVELOPMENT every roll
  falls inside a missing session, so no bucket mixes contracts (verified
  by the frozen External / Swing baselines).

### 3.2 Formation and the zone fact

For consecutive complete observations C1, C2, C3 in one segment, in ticks:

| Direction | Condition | `lower` | `upper` |
|---|---|---|---|
| BULLISH | `low(C3) − high(C1) ≥ 1` | `high(C1)` | `low(C3)` |
| BEARISH | `low(C1) − high(C3) ≥ 1` | `high(C3)` | `low(C1)` |

- Equality (`low(C3) = high(C1)` or `high(C3) = low(C1)`) is not an FVG.
- At most one direction per triple: both would need
  `high(C3) < low(C1) ≤ high(C1) < low(C3) ≤ high(C3)`, a contradiction.
- Every triple is evaluated; consecutive triples can each form a zone
  (zones overlap only through §3.7).
- **Width:** `width_ticks = upper − lower ≥ 1`; `width_points =
  width_ticks × tick`.
- **Midpoint (exact):** `midpoint_half_ticks = lower + upper` (integer, in
  half-ticks) and `midpoint = midpoint_half_ticks × tick / 2` as an exact
  decimal (e.g. 20,101.625). Odd widths give half-tick midpoints (51–53 % of
  DEVELOPMENT zones below 1D, §5.9). Midpoints are never rounded.
  Comparisons with a midpoint use doubled tick values (`2 × price_ticks` vs
  `midpoint_half_ticks`).
- **Timing.**
  - `source_at` = `bar_end(C1)`; `source_end_at` = `bar_end(C3)`.
  - `available_at` = `bar_end(C3)` (= C3 close). No earlier consumer sees
    the zone.
  - Source span = `[bar_start(C1), bar_end(C3))`.
- **Evidence:** the three observations' OHLC and `BAR_SPAN` refs (per bar)
  and a triple ref `BAR_SPAN:<instrument>|<contract>|<tf>|<C1 end>|<C3 end>`
  (frozen `bar_span_ref` format, D-138).
- **Immutable formation fact.** Bounds, midpoint, width, original direction,
  evidence and timing never change. Stage, mitigation and grades live in
  separate, versioned records (§3.4 – §3.9). R-C2 holds by construction.

### 3.3 Volatility-normalized width (descriptive only; parameters need approval)

- `width_atr_ratio = width_points / ATR_N`, where `ATR_N` is the simple mean
  true range of the last N complete observations of the zone's own
  timeframe **ending with C3**, all in C3's continuity segment. True range
  uses the previous observation's close within the segment (the first bar of
  a segment uses `high − low`).
- Known at C3 close (causal). Null when the segment has fewer than N
  observations up to C3 (no padding across gaps).
- **Recommended parameters (require approval; decision V-1, §9):** N = 14;
  simple mean; the formation bars included.
- Descriptive column only. It never enters priority (R-C3).

### 3.4 Directional lifecycle: FVG → IFVG → RETIRED

M7A namespace `fvg.zone`; entity = `zone_id`; initial state `FVG`.

| From | To | Trigger (own timeframe close `c`, bar `X` with `bar_start(X) ≥ stage_start`) | `reason_code` |
|---|---|---|---|
| FVG (bullish) | IFVG (bearish) | `c < lower` (strict) | `CONVERTED` |
| FVG (bearish) | IFVG (bullish) | `c > upper` (strict) | `CONVERTED` |
| IFVG (bullish) | RETIRED | `c < lower` (strict) | `RETIRED` |
| IFVG (bearish) | RETIRED | `c > upper` (strict) | `RETIRED` |
| FVG / IFVG | TERMINATED | 1m §G.2a gap onset | `DATA_GAP` |
| FVG / IFVG | PENDING_ADJUSTMENT | first new-contract bar close with no gap (CB-2) | `CONTRACT_CHANGE` |

- Terminal states: RETIRED, TERMINATED, PENDING_ADJUSTMENT (terminal within
  a raw-basis run; §3.11).
- `stage_start` = `available_at` for the FVG stage and the conversion close
  for the IFVG stage. Formation bars and the conversion bar are never
  classified again.
- The IFVG keeps `lower`, `upper`, `midpoint` and `original_width`; only the
  current direction reverses (`current_direction` attribute on the
  transition). There is no IFVG → FVG edge (no repeated inversion).
- Equality at the far bound and wicks beyond it never convert or retire
  (W1: a wick to 20,100.75 below the lower bound 20,101.00 and a close at
  exactly 20,101.00 do not convert; the next close 20,100.50 does).
- Consequence (not a rule): a zone's own-timeframe close strictly beyond the
  far bound is the only conversion path, so a 1D zone converts only on a
  Daily close.

### 3.5 Mitigation (canonical 1m)

Per zone and stage, using the stage's current direction; 1m bars `m` with
`bar_start(m) ≥ stage_start` (so formation bars and the conversion bar never
count for the next stage).

| Current direction | Near boundary | Penetration (strict) | Depth (ticks) | Midpoint reach | Full-zone reach |
|---|---|---|---|---|---|
| BULLISH (retracement from above) | `upper` | `low(m) < upper` | `upper − low(m)` | `2·low(m) ≤ midpoint_half_ticks` | `low(m) ≤ lower` |
| BEARISH (retracement from below) | `lower` | `high(m) > lower` | `high(m) − lower` | `2·high(m) ≥ midpoint_half_ticks` | `high(m) ≥ upper` |

- The order upper → midpoint → lower (bullish) and lower → midpoint → upper
  (bearish) is the evaluation order of these three tests (R-A6). One bar may
  satisfy several; each is recorded at that bar's `e(m)`.
- Midpoint and full-zone reach shown **inclusive** (touch counts). This is
  decision **M-1** (§9): it changes results only for even widths
  (integer-tick midpoints) and exact far-bound touches. Half-tick midpoints
  can never be touched exactly.
- **Recorded per (zone, stage):** first penetration time and bar; midpoint
  reach time; full-zone reach time; and the running maximum depth (a new
  record each time the depth grows, so the depth as of any instant is
  causal). Depth is uncapped and may exceed the width (W2: 7 ticks into a
  5-tick zone).
- Mitigation never changes bounds, width, stage or grade inputs (R-C2).
- Mitigation is not tolerance-based (unlike D-143) and is independent of the
  close-based lifecycle.

### 3.6 Causal batch and timestamp semantics

All instants are bar ends (UTC canonical; ET for display). At each instant
`t`, the batch runs in this order; every step reads the state left by the
previous steps:

1. **(a) 1m mitigation.** For the 1m bar ending at `t`: every zone and BPR
   active at `s(m)` is tested with its **stage at `s(m)`**.
2. **(b) Own-timeframe close classification.** For every timeframe bar `X`
   ending at `t` (complete only): zones of that timeframe with
   `stage_start ≤ s(X)` are classified (FVG → IFVG, IFVG → RETIRED). BPRs
   governed by that timeframe are classified (retirement).
3. **(c) Resets.** 1m §G.2a onsets at `t` (`DATA_GAP`) and pure contract
   changes at `t` (`CONTRACT_CHANGE`; CB-2) end actionable state (§3.11).
4. **(d) Admissions.** Zones whose C3 closes at `t` (all timeframes) and
   swings confirmed at `t` (frozen detector).
5. **(e) Relationships.** New zones against the post-(b)/(c) active set and
   against each other (§3.7). New BPR objects.
6. **(f) Swing-leg associations and first-FVG markers** (§3.10).
7. **(g) Grade versions** for every zone whose components changed (§3.9).

- **Classify-before-admit.** Steps (a)–(c) use only state that existed
  before `t`; admissions in (d) are never classified by the bar that closes
  at `t` (R-A3). This is the Market Structure post-close pattern (D-141).
- **Conversion-bar ordering (R-B5).** If the 1m bar ending at `t` penetrates
  a bullish FVG and its own timeframe closes below `lower` at the same `t`:
  (a) records FVG-stage mitigation at `t`, (b) converts at `t`, and the IFVG
  stage starts at `t`. IFVG mitigation is tested only from the next 1m bar
  (`bar_start ≥ t`). W2 (1m zone) and W4 (5m zone) show it. The conversion
  bar's range never counts as an IFVG retest.
- **Visibility.** A bar starting at `t` sees every fact with
  `available_at ≤ t` (bar-boundary rule). Event consumers use the strict M7A
  rule.
- **Explicit `replay_cutoff`.** Required, recorded in the manifest; nothing
  after it is read. Prefix equivalence (FVG-INV-21) holds for every cutoff,
  including inside gaps.

### 3.7 Overlap relationships: FVG_OVERLAP, BPR, MTF_BPR

#### 3.7.1 Creation

A relationship is created at `e = available_at(Z)` when a new zone `Z` is
admitted, for each partner `P` such that:

- `P` is active at `e` after steps (b) and (c) (stage FVG or IFVG; not
  RETIRED, TERMINATED or PENDING_ADJUSTMENT);
- `P` and `Z` share a comparable price basis (§3.11; on the raw basis: the
  same contract);
- the intersection has positive width:
  `i_lower = max(P.lower, Z.lower)`, `i_upper = min(P.upper, Z.upper)`,
  `i_upper − i_lower ≥ 1` tick. Contact (`= 0`) is not a relationship.

There is no age limit (R-E1): any active, comparable partner qualifies.

#### 3.7.2 Labels (fixed at creation)

| Partners' current directions at `e` | Same timeframe | Different timeframes |
|---|---|---|
| Same | `FVG_OVERLAP` | `FVG_OVERLAP` (with `cross_timeframe = true`) |
| Opposite | `BPR` | `MTF_BPR` |

- `P` may be an FVG or IFVG (R-D4); its **current** direction is used.
- Relationship rows are immutable: parent ids, parents' stage and current
  direction at `e`, intersection bounds and exact midpoint, label, earlier /
  later parent, governing timeframe (BPR only).
- What happens to an existing relationship when a parent later changes stage
  is decision **O-2** (§9). Recommended: labels never change and inversion
  creates no new relationship; an `FVG_OVERLAP` stops qualifying for
  grading when its parents' current directions diverge.

#### 3.7.3 Deduplication and identity

- One relationship per unordered pair of zones per price basis:
  `relationship_id = fo_ + SHA-256(definition_version, basis_id, sorted
  zone ids)`. A pair is created at most once (when the later zone is
  admitted). Stage changes never create a second relationship for the same
  pair.
- Zones are unique physical formations (one id per triple and timeframe),
  so FVG and IFVG stages of one zone are never two partners.

#### 3.7.4 Later parent and simultaneous availability

- "Later" is decided by causal `available_at`, never by source timestamps.
- **Simultaneous availability** (equal `available_at`) can only occur across
  timeframes (one triple per bar end per timeframe). Then `direction =
  UNDEFINED`, `earlier_parent` / `later_parent` are null and no governing
  timeframe is invented (decision **O-3** for its lifecycle).
- **Reachability (argued and checked).** If a lower-timeframe zone and a
  higher-timeframe zone become available at the same instant and the HTF C3
  bucket contains at least three LTF buckets, the LTF zone lies inside
  `[low(HTF C3), high(HTF C3)]`, while either HTF zone lies outside it
  (bullish below `low(C3)`, bearish above `high(C3)`). The intersection is
  ≤ 0, so no relationship of any label can form.
  - On the DEVELOPMENT expected schedule, every HTF bucket holds at least 3
    buckets of every lower timeframe (minimum 1H per 4H = 3; §5.9).
    Simultaneous relationships are therefore **unreachable on the current
    schedule**.
  - They become reachable only with calendar-truncated buckets holding fewer
    than three LTF buckets (an early close once the holiday calendar is
    populated). The design still specifies them (§3.8, O-3).

### 3.8 BPR objects and lifecycle

- Every `BPR` / `MTF_BPR` relationship creates one BPR object
  `bpr_id = fb_ + SHA-256(relationship_id)` with the intersection bounds,
  exact midpoint, width, `available_at = e`, direction (= the later parent's
  current direction at `e`), and governing timeframe (= the later parent's
  timeframe).
- M7A namespace `fvg.bpr`; initial `ACTIVE`.

| From | To | Trigger | `reason_code` |
|---|---|---|---|
| ACTIVE (bullish) | RETIRED | governing-timeframe close `< lower` | `RETIRED` |
| ACTIVE (bearish) | RETIRED | governing-timeframe close `> upper` | `RETIRED` |
| ACTIVE | TERMINATED | 1m gap onset | `DATA_GAP` |
| ACTIVE | PENDING_ADJUSTMENT | pure contract change | `CONTRACT_CHANGE` |

- Governing-timeframe bars with `bar_start ≥ e` only. No inversion.
- **Independent of parents (R-D5):** parent conversion, retirement or
  grading changes never end a BPR. W4 (executed): parent A inverts at 19:20
  and retires at 19:25 while the MTF_BPR survives until its own 15m close
  at 19:45.
  - Shown only for a parent on a lower timeframe than the governing one: a
    same-or-higher-timeframe parent's retirement close is, by construction,
    also a governing-timeframe close beyond the BPR's far bound (§4.3).
- Mitigation is recorded for BPRs exactly as for zones (§3.5, with the BPR's
  direction), as descriptive data.
- **Simultaneous-parent BPR** (direction UNDEFINED): decision O-3.
  Recommended: descriptive only (not actionable, not graded, no close-based
  retirement); ends only by data gap or contract change.

### 3.9 Priority and grading

**Components** (recorded per zone grade version, all explicit):

- `timeframe_rank`: 1m = 1, 5m = 2, 15m = 3, 1H = 4, 4H = 5, 1D = 6.
- `qualifying_overlap_count`: the number of distinct qualifying partner
  zones at the version's instant, plus their ids. What qualifies is
  decision **O-1** (§9): partner direction, and whether nested partners
  from the same physical displacement count.
- `original_width_ticks` (never changes through mitigation or inversion).
- Descriptive only: `width_atr_ratio`, stage, mitigation summary.

**Ordering (R-C1):** sort actionable zones by `timeframe_rank` descending,
then `qualifying_overlap_count` descending, then `original_width_ticks`
descending, then `available_at` ascending, then `zone_id` (the last two are
deterministic tiebreaks only; they do not express preference).

- No score, weight, proximity, direction bias or outcome input (R-C4).
- **Prospective updates.** A new grade version (`fg_` id, `available_at = t`)
  is written whenever a component changes:
  - admission;
  - a relationship created or ending qualification;
  - a partner retiring, terminating or becoming pending;
  - the zone's own stage change (the actionable flag and partner validity
    may change).

  Earlier versions are never rewritten.
- **Deduplication (R-D6).** Partners are counted by `zone_id`, so a
  partner's stages or grade versions never count twice. BPR objects are
  never partners of their own parents.
- **BPR priority:** governing `timeframe_rank`, then `width_ticks`
  (intersection), then `available_at`, `bpr_id`. BPRs have no partner count
  in this draft (part of decision O-1).

### 3.10 First FVG in a directional swing leg

Inputs: the zone's own-timeframe `swing_points` from the frozen detector
under the explicit 2/2 reference definition (`swing-pivot-v1`), in the
zone's continuity segment.

**Algorithm (recommended options shown; choices F-1 and F-2 in §9):**

1. **Leg orientation.** Bullish zones use bullish legs (origin: LOWER swing;
   terminator: UPPER swing). Bearish zones mirror this.
2. **Anchor bar** of zone `F`: its displacement candle **C2** (decision F-2;
   alternative C1).
3. **Leg membership.** Let `U` be the last opposite (UPPER) swing with
   `source_end_at < anchor_end`. The candidate origins are the LOWER swings
   in the segment with `source_at ≤ anchor_end` and `source_at >
   U.source_end_at`. The leg origin `O` is the **lowest** candidate (ties:
   earliest `source_at`) (decision F-1; alternative: the most recent).
   No candidate means `F` belongs to no leg.
4. **First.** `F` is the first FVG of leg `O` iff no other bullish zone of
   the same timeframe in leg `O` has an earlier `available_at` (ties: earlier
   anchor, then `zone_id`).
5. **Association time.** `association_available_at = max(F.available_at,
   O.available_at, t_complete)`, where `t_complete` is the first instant at
   which no unconfirmed swing can still change steps 3–4.
   - A swing that matters has its plateau start at or before the anchor.
     Its plateau can extend past the anchor only through observations whose
     low (bullish case) equals the anchor's low.
   - Let `P` be the last observation of that equal-low run starting at the
     anchor (`P` = anchor when the next observation's low differs). Then
     `t_complete = e(P + right_depth)`, the latest confirmation instant of
     any such swing. Opposite swings with `source_end_at < anchor` are
     confirmed earlier.
   - With 2/2: C1 anchoring gives `t_complete = e(C3) = F.available_at`
     unless `low(C2) = low(C1)`. C2 anchoring gives `e(C4)`, one bar after
     formation.
   - DEVELOPMENT confirms that lags happen even with C1 anchoring: 42 5m
     cases where the plateau runs into C2 (§5.9).
   - The association row records `formation_available_at` and
     `association_available_at` separately (R-F1). Nothing is shown before
     the latter. No provisional marker is ever exposed.

**Marker lifecycle** (M7A namespace `fvg.first_marker`; entity =
`association_id`; available at `association_available_at`):

- ACTIVE while the zone is in the FVG stage, through mitigation (R-F2).
- Ends with `CONVERTED` at the conversion (the IFVG does not inherit it),
  or with `DATA_GAP` / `CONTRACT_CHANGE`.
- If the zone converted, terminated or became pending at or before
  `association_available_at`, the marker never becomes active.
  - The association row records `marker_never_active` with the reason.
  - No later FVG is promoted (R-F2).
- Batch step (f) runs after (b), so a conversion at the same instant
  prevents activation.
- Later swing confirmations never rewrite earlier strategy-visible states.
  The marker becomes visible only at `association_available_at`.

**Leg end.** A leg ends at its first opposite swing (the next UPPER swing
with `source_at > O.source_end_at`). A zone anchored after that swing's
plateau belongs to the next leg (or none). A new lower LOWER swing before any
UPPER swing starts a new leg (option F-1 recommended; under the alternative,
every LOWER swing starts one).

### 3.11 Missing data, contract changes, price basis and future adjustment

#### 3.11.1 Missing or incomplete data (R-E3)

- **Onset.** At every 1m §G.2a `DATA_GAP` onset (the expected completion of
  the first missing or incomplete 1m observation; frozen adapter), every
  active zone, BPR and first-FVG marker of **every** timeframe terminates
  with `DATA_GAP`, and a missing-data warning row is written. Mitigation is
  observed on 1m for all timeframes, so a 1m gap can hide a mitigation, a
  conversion close or a retirement for any of them; that makes every zone
  "affected".
- **No inference.** Nothing is recorded for the unobserved interval: no
  mitigation, conversion or retirement. W7 (executed): a zone with a
  recorded penetration at 18:21 terminates at 18:26. Post-gap prices below
  its lower bound are never applied to it.
- **Re-establishment.** Formation resumes only from triples inside post-gap
  segments (automatic, because a missing or incomplete observation ends the
  segment). Pre-gap zones never revive, and their ids are never re-admitted.
- **Consequence.** Zone lifetime is bounded by the next 1m gap (33 1m
  episodes on DEVELOPMENT). This is the data rule, not an age limit.

#### 3.11.2 Contract rollover is not missing data

| Case | Detection (frozen adapter) | FVG effect |
|---|---|---|
| CB-1: gap, then a new contract | `DATA_GAP` at the gap onset; the contract change is recorded only in the next episode's opening provenance | Termination `DATA_GAP` (the gap dominates; §3.11.1) |
| CB-2: pure change, no missing data | `CONTRACT_CHANGE` at the first new-contract 1m bar's close | Old-contract zones, BPRs and markers move to `PENDING_ADJUSTMENT`; they are **not** terminated and **not** tested against new-contract prices |

- On DEVELOPMENT every roll is CB-1 (the rolls fall inside missing
  sessions).
- `PENDING_ADJUSTMENT` keeps the zone and all its evidence. It is
  non-actionable on the raw basis and listed in the pending-comparison view.

#### 3.11.3 Price basis

- Every price-bearing value is stored **raw**, with its `source_contract`.
  Each value set carries `basis_id`:
  - `RAW:<contract>` today;
  - `ADJ:<method>:<adjustment_version>` once the shared process exists.
- Zone facts are basis-independent (identity from the source triple).
  Basis-dependent values (bounds, midpoint, BPR / overlap intersections)
  live in `fvg_price_values` keyed by `(object_id, basis_id)`.
- **Comparable** = two objects, and the bars that test them, share one
  `basis_id`. On the raw basis this means the same contract. Raw prices of
  different contracts are never compared, and FVG never derives an
  adjustment itself.

#### 3.11.4 Future shared adjustment: how it coexists with the data rules

- An adjusted run is a **new run** (`run_id` includes `basis_id` and the
  adjustment version). Previous raw and adjusted runs are preserved, and
  natural ids of zones do not change (they are source-based).
  Relationship and BPR ids include `basis_id`, so they never collide across
  bases.
- **Data-quality rules are basis-independent.** A 1m gap terminates
  actionable state in every basis, because the missing interval is
  unobserved whatever the price basis.
- **A pure contract change** is a reset only on the raw basis. On an
  adjusted basis that the shared process declares continuous across the
  roll, zones continue (no `PENDING_ADJUSTMENT`), and cross-contract
  overlaps are created like any other.
- **Formation triples** still never span a contract change. M3 and
  continuity are frozen and segment at contract changes. Changing that is
  part of the shared process, not FVG.
- **Precondition for the shared process:** to preserve FVG's tick-exact
  semantics (≥ 1 tick gap, strict penetration, strict closes, half-tick
  midpoints), the adjustment must map each contract's prices by a
  whole-tick additive offset. Decision **A-1** (§9) records this as a
  requirement on the future process.

#### 3.11.5 Pending comparisons (explicit, not discarded)

`fvg_pending_comparisons` lists, at each instant where an object is
admitted or becomes pending, the objects whose comparison is unavailable on
the run's basis: `(object_id, pending_object_id, reason =
BASIS_MISMATCH, since_at)`. The strategy-facing view exposes
`pending_cross_contract_count`. No history is discarded by a contract
restriction.

### 3.12 Output tables, M7A namespaces and strategy-facing views

All tables carry `instrument_id`, `contract_scope = SPECIFIC`, `contract`,
`definition_version`, `run_id` and `fact_hash`. Times are UTC tz-aware;
prices are exact decimals with integer tick (or half-tick) twins. Every
table has a fixed column schema, empty tables included.

| Table | Grain | Key columns |
|---|---|---|
| `fvg_zones` | one immutable row per zone | `zone_id`, `timeframe`, `original_direction`, `lower_ticks`, `upper_ticks`, `midpoint_half_ticks`, `lower`, `upper`, `midpoint`, `width_ticks`, `width_points`, `c1_ref`, `c2_ref`, `c3_ref`, `source_ref`, `source_at`, `source_end_at`, `span_start`, `available_at`, `segment_ref`, `atr_n`, `width_atr_ratio`, `basis_id` |
| `fvg_zone_transitions` | M7A `fvg.zone` log | standard M7A columns, plus `attr_current_direction`, `attr_close_ticks`, `attr_timeframe` |
| `fvg_mitigation_events` | first-time events and depth records per (zone, stage) | `zone_id`, `stage`, `kind` (`PENETRATION` / `MIDPOINT` / `FULL` / `DEPTH`), `at`, `bar_ref`, `depth_ticks`, `bar_ohlc` |
| `fvg_overlaps` | one immutable row per relationship | `relationship_id`, `label`, `zone_a`, `zone_b`, `earlier_zone`, `later_zone`, `simultaneous`, `cross_timeframe`, `i_lower`, `i_upper`, `i_midpoint_half_ticks`, `created_at`, `parents_stage_at_creation`, `parents_direction_at_creation`, `basis_id` |
| `fvg_overlap_transitions` | M7A `fvg.overlap` (QUALIFYING → ENDED) | reasons `PARENT_RETIRED`, `PARENT_TERMINATED`, `PARENT_PENDING`, `DIRECTION_DIVERGED` (O-2) |
| `bpr_zones` | one immutable row per BPR | `bpr_id`, `relationship_id`, `label`, `direction`, `governing_timeframe`, bounds, midpoint, width, `available_at` |
| `bpr_transitions` | M7A `fvg.bpr` | as in §3.8 |
| `fvg_grade_versions` | one row per component change | `grade_version_id`, `zone_id`, `available_at`, `timeframe_rank`, `qualifying_overlap_count`, `qualifying_partner_ids`, `original_width_ticks`, `actionable`, `supersedes` |
| `fvg_swing_associations` | one row per zone with a leg | `association_id`, `zone_id`, `leg_origin_swing_id`, `leg_rule_version`, `is_first`, `formation_available_at`, `association_available_at`, `marker_never_active`, `reason` |
| `fvg_first_marker_transitions` | M7A `fvg.first_marker` | `CONVERTED`, `DATA_GAP`, `CONTRACT_CHANGE` |
| `fvg_price_values` | per object and basis | `object_id`, `basis_id`, `adjustment_version`, `lower`, `upper`, `midpoint` |
| `fvg_pending_comparisons` | §3.11.5 | |
| `fvg_data_warnings` | one row per gap onset | `at`, `reason`, `reset_ref`, `terminated_count` |

**Strategy-facing causal views** (bar-boundary rule: inputs with
`available_at ≤ t`):

- `active_fvg_zones(t)`: one row per zone in stage FVG or IFVG at `t`. It
  carries current direction, bounds, exact midpoint, original width, stage,
  stage start and the stage's mitigation summary as of `t` (first
  penetration, max depth, midpoint / full reach). It also carries the
  first-FVG marker if active at `t`, the latest grade components and the
  priority rank. No proximity or direction-bias columns.
- `active_bprs(t)`, `qualifying_overlaps(t)` and
  `pending_comparisons(t)`.
- Retired, terminated and pending objects appear only in audit views.

### 3.13 Identity, immutable versions and provenance

| Object | Id | Natural key (SHA-256) | Excludes |
|---|---|---|---|
| Zone | `fz_` | `definition_version`, `instrument_id`, `contract_scope`, `contract`, `timeframe`, `original_direction`, triple `source_ref` | prices, basis, `available_at`, stage, grade |
| Relationship | `fo_` | `definition_version`, `basis_id`, sorted zone ids | label (derived), times |
| BPR | `fb_` | `relationship_id` | |
| Grade version | `fg_` | `zone_id`, canonical `available_at`, sorted qualifying partner ids, `actionable` | |
| Association | `fa_` | `zone_id`, `leg_origin_swing_id`, `leg_rule_version` | |
| Mitigation event | `fm_` | `zone_id`, `stage`, `kind`, canonical `at` | |
| M7A transitions | `st_` | the frozen M7A natural key | |

- `run_id` = hash of the manifest:
  - definition versions;
  - the Swing reference definition;
  - `replay_cutoff`;
  - `basis_id` and adjustment version;
  - source fingerprint;
  - instrument tick.
- `fact_hash` = content hash per row. Natural ids never contain `run_id`.
  Revisions create new runs (D-141 pattern).
- Every M7A transition has exactly one trigger, chosen per event type:
  - mitigation: the 1m `BAR_SPAN`;
  - conversion / retirement: the timeframe `BAR_SPAN`;
  - data gap: `CONTINUITY_BREAK`;
  - contract change: the first new-contract bar's `BAR_SPAN`;
  - marker end: the conversion `BAR_SPAN`.

---

## 4. Consistency check

### 4.1 Formation ↔ availability ↔ lifecycle

- A zone is admitted at step (d) of `e(C3)`. Steps (a) and (b) at `e(C3)`
  ran before it existed, so neither the 1m bars inside C3 nor C3's own
  close can mitigate or convert it.
  - The first conversion candidate is the observation after C3; the first
    mitigation candidate is the 1m bar starting at `e(C3)`.
  - Argument; W1 and W2 executed.
- M7A requires entity availability strictly before every transition:
  - conversion at `e(X)` with `bar_start(X) ≥ e(C3)` gives
    `e(X) > available_at`;
  - a gap onset is a later expected completion;
  - CB-2 fires at a later bar close.

  All valid.

### 4.2 Mitigation ↔ conversion ordering

- (a) precedes (b) at the same instant. FVG-stage mitigation by the
  conversion bar is therefore recorded with stage FVG, and the IFVG stage
  starts at the conversion close. The two are separate M7A entities /
  tables, so there is no one-transition-per-trigger conflict.
  - For a 1m zone, the 1m bar and the timeframe bar are the same bar:
    mitigation (a), then conversion (b). Executed in W2.

### 4.3 BPR ↔ parents

- BPR direction = the later parent's current direction at creation. The
  later parent was just admitted, so it is always in its FVG stage and its
  current direction equals its original direction.
- **Parent retirement implies BPR retirement unless the retiring parent is
  on a lower timeframe than the governing one** (argument).
  - Bearish BPR: `upper = min(A.upper, C.upper)`. Any parent retirement or
    conversion close that ends a bearish-current parent requires a close
    `> parent.upper ≥ BPR.upper`.
  - If that close is on the governing timeframe or a higher one, it is also
    a governing-timeframe close above `BPR.upper` (an HTF close is the
    close of its last governing bar). The BPR retires at the same instant.
  - Only a lower-timeframe parent close can exceed the parent's far bound
    while the governing bar later closes back inside. W4 executed it.
- Parent **inversion** never ends a BPR (W4: A inverts at 19:20; the BPR
  survives).

### 4.4 Overlap ↔ grading ↔ dedup

- Partners are counted by `zone_id`, so the FVG / IFVG stages of one zone
  never count twice. Relationships are created once per pair.
- W5 (executed) shows the remaining inflation risk: one 15m displacement
  overlaps three 5m zones of the same move (their source spans lie inside
  the 15m triple's span). Counting all three as confluence would inflate the
  15m zone's priority. Decision O-1(b).

### 4.5 Swing association ↔ formation ↔ causality

- Association uses only swings with `source_at ≤ anchor` (and their
  opposite terminators). The association time is the maximum of the
  formation time, the origin's confirmation time and the confirmation
  deadline for the anchor window. No view before that instant shows the
  marker.
- DEVELOPMENT shows that this time can exceed formation time even with C1
  anchoring: 42 of the 5m first-FVG associations. The cause is plateaus
  extending into C2 (§5.9). Association time is therefore stored
  separately, not assumed equal.
- Conversion at or before the association instant: the marker never
  activates, and no later FVG is promoted.

### 4.6 Missing data ↔ adjustment

- A gap terminates in every basis. A pure roll suspends (raw) or continues
  (adjusted, once supported). The two rules never apply to the same instant
  in conflicting ways: CB-1 records only `DATA_GAP` at the onset (frozen
  adapter); CB-2 has no missing data.

### 4.7 Empty input / no zones

- `replay_cutoff` before the first bar, fewer than three observations in
  every segment, or no qualifying triple: every table is empty with its
  fixed schema. The views return empty frames with fixed columns, and the
  manifest is still written (FVG-INV-25).

### 4.8 Contradiction search result

- No contradiction among the settled requirements was found.
- Two settled items are vacuous on today's schedule:
  - simultaneous-parent relationships (§3.7.4);
  - parent retirement with a surviving BPR when the parent is on the same or
    a higher timeframe than the governing one (§4.3).
- They are specified anyway and covered by synthetic tests where reachable.

---

## 5. Worked examples (executed)

All examples use 5m observations (W2 uses 1m) built by the frozen M3
builder from 1m bars. The first minute carries the observation's O / H / L
/ C and the remaining minutes sit at the close (fixture `ohlc_bars`).
Prices are 20,000 + the shown value. Times are ET on Sunday 2026-09-13,
the session opening 18:00. Every claim below was printed by the scratch
verification prototype.

### 5.1 W1: bullish formation, half-tick midpoint, mitigation, wick vs close, conversion, IFVG retirement (5m)

| k | bar end | O | H | L | C | event |
|---|---|---|---|---|---|---|
| 0 | 18:05 | 100.00 | 101.00 | 99.00 | 100.75 | C1 |
| 1 | 18:10 | 100.75 | 104.00 | 100.50 | 103.75 | C2 |
| 2 | 18:15 | 103.75 | 105.00 | 102.25 | 104.50 | C3 → **bullish FVG [101.00, 102.25]**, width 5 ticks (1.25 pt), midpoint **101.625**, available 18:15 |
| 3 | 18:20 | 104.50 | 104.75 | 102.25 | 103.00 | low = upper: touch, **no** mitigation |
| 4 | 18:25 | 103.00 | 103.25 | 102.00 | 102.50 | FVG penetration at 18:21, depth 1 |
| 5 | 18:30 | 102.50 | 102.75 | 101.50 | 102.00 | midpoint reached at 18:26 (101.50 < 101.625) |
| 6 | 18:35 | 102.00 | 102.25 | 100.75 | 101.25 | full-zone reach at 18:31 (wick below lower); close inside: **no conversion** |
| 7 | 18:40 | 101.25 | 101.50 | 101.00 | 101.00 | close = lower: **no conversion** (equality) |
| 8 | 18:45 | 101.00 | 101.25 | 100.25 | 100.50 | close < lower: **converted** to bearish IFVG at 18:45 |
| 9 | 18:50 | 100.50 | 101.00 | 100.25 | 100.75 | high = lower (IFVG near boundary): touch, no IFVG mitigation |
| 10 | 18:55 | 100.75 | 101.75 | 100.50 | 101.50 | IFVG penetration and midpoint at 18:51 (depth 3) |
| 11 | 19:00 | 101.50 | 102.50 | 101.25 | 102.25 | IFVG full reach at 18:56; close = upper: **no retirement** |
| 12 | 19:05 | 102.25 | 103.00 | 102.00 | 102.75 | close > upper: **IFVG retired** at 19:05 |

- **Side effect (expected):** k9–k11 and k10–k12 form two further one-tick
  bullish 5m zones, [101.00, 101.25] (midpoint 101.125) and
  [101.75, 102.00] (midpoint 101.875).
- **Swings:** UPPER 105.00 (source 18:15, available 18:25) and LOWER 100.25
  (plateau 18:45–18:50, available 19:00).

### 5.2 W2: conversion-bar ordering on a 1m zone

| k | bar end | O | H | L | C | event |
|---|---|---|---|---|---|---|
| 0–2 | 18:01–18:03 | as W1 rows 0–2 | | | | 1m bullish FVG [101.00, 102.25], available 18:03 |
| 3 | 18:04 | 104.50 | 104.75 | 100.50 | 100.75 | (a) FVG-stage penetration, midpoint and full reach at 18:04 (depth 7); (b) conversion at 18:04 |
| 4 | 18:05 | 100.75 | 101.50 | 100.50 | 101.25 | first IFVG-stage test: penetration at 18:05 (depth 2) |

Bar 3's range is never an IFVG retest (R-B5).

### 5.3 W3: bearish one-tick zone and equality

| k | bar end | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 18:05 | 105.00 | 106.00 | 104.00 | 104.25 |
| 1 | 18:10 | 104.25 | 104.50 | 101.00 | 101.25 |
| 2 | 18:15 | 101.25 | 103.75 | 100.50 | 101.00 |
| 3 | 18:20 | 101.00 | 101.50 | 99.00 | 99.25 |
| 4 | 18:25 | 99.25 | 101.00 | 98.00 | 100.75 |

- Bearish FVG [103.75, 104.00], width 1 tick, midpoint 103.875 (half-tick),
  available 18:15.
- Triples k1–k3 and k2–k4 form nothing. k2–k4 is exact equality:
  `high(k4) = 101.00`, `low(k2) = 100.50`. It is not bearish, because
  101.00 is not below 100.50.

### 5.4 W4: MTF_BPR, parent inversion and retirement, independent BPR retirement

5m rows: k0–k2 as W1, then (each `O H L C`):

| k | bar end | O | H | L | C |
|---|---|---|---|---|---|
| 3 | 18:20 | 104.50 | 105.50 | 104.00 | 105.00 |
| 4 | 18:25 | 105.00 | 106.00 | 104.50 | 105.50 |
| 5 | 18:30 | 105.50 | 106.50 | 105.00 | 106.00 |
| 6 | 18:35 | 106.00 | 106.50 | 103.25 | 104.00 |
| 7 | 18:40 | 104.00 | 104.50 | 103.00 | 103.50 |
| 8 | 18:45 | 103.50 | 104.00 | 103.25 | 103.75 |
| 9 | 18:50 | 103.75 | 103.75 | 102.00 | 102.25 |
| 10 | 18:55 | 102.25 | 102.50 | 101.50 | 101.75 |
| 11 | 19:00 | 101.75 | 102.00 | 101.25 | 101.50 |
| 12 | 19:05 | 101.50 | 101.75 | 101.25 | 101.50 |
| 13 | 19:10 | 101.50 | 101.75 | 101.25 | 101.25 |
| 14 | 19:15 | 101.25 | 101.50 | 101.00 | 101.25 |
| 15 | 19:20 | 101.25 | 101.25 | 100.50 | 100.75 |
| 16 | 19:25 | 100.75 | 102.75 | 100.75 | 102.50 |
| 17 | 19:30 | 102.50 | 102.50 | 101.75 | 102.00 |
| 18 | 19:35 | 102.00 | 102.25 | 101.75 | 102.25 |
| 19 | 19:40 | 102.25 | 102.50 | 102.00 | 102.25 |
| 20 | 19:45 | 102.25 | 103.00 | 102.25 | 102.75 |

Executed results:

- **A:** 5m bullish [101.00, 102.25], available 18:15.
- **C:** 15m bearish [101.75, 103.00]. 15m C1 = 18:30–18:45 (low 103.00),
  C3 = 19:00–19:15 (high 101.75). Available 19:15.
  - C is the later parent. A is still FVG (bullish) at 19:15: closes stayed
    ≥ 101.00.
- **MTF_BPR** [101.75, 102.25], midpoint 102.00, direction bearish (C),
  governing 15m, available 19:15.
- A converts at 19:20 (5m close 100.75 < 101.00); the BPR survives
  (bearish BPR, not affected by a close below).
- A (now bearish IFVG) retires at 19:25 (5m close 102.50 > 102.25). The 15m
  bar 19:15–19:30 closes 102.00 ≤ 102.25: **the BPR survives** its parent's
  retirement.
- The BPR retires at 19:45 (15m close 102.75 > 102.25).
- C (15m) is never converted (102.75 ≤ 103.00).
- Other zones formed (not used): 5m bearish [104.50, 105.00],
  [102.50, 103.25]; 5m bullish [101.25, 101.75]; 15m bearish
  [103.75, 104.00].

### 5.5 W5: same-direction overlap from one displacement (5m and 15m)

| k | bar end | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 18:05 | 100.00 | 100.50 | 99.50 | 100.25 |
| 1 | 18:10 | 100.25 | 100.75 | 100.00 | 100.50 |
| 2 | 18:15 | 100.50 | 101.00 | 100.25 | 100.75 |
| 3 | 18:20 | 100.75 | 103.00 | 100.75 | 102.75 |
| 4 | 18:25 | 102.75 | 105.00 | 102.50 | 104.75 |
| 5 | 18:30 | 104.75 | 107.00 | 104.50 | 106.75 |
| 6 | 18:35 | 106.75 | 108.00 | 106.00 | 107.50 |
| 7 | 18:40 | 107.50 | 108.50 | 107.00 | 108.00 |
| 8 | 18:45 | 108.00 | 109.00 | 107.25 | 108.50 |

- 5m bullish zones:
  - [101.00, 102.50], available 18:25;
  - [103.00, 104.50], available 18:30;
  - [105.00, 106.00], available 18:35.
- 15m bullish [101.00, 106.00], width 20, available 18:45.
- Each 5m zone overlaps the 15m zone (`FVG_OVERLAP`, cross-timeframe), and
  each 5m triple's source span lies inside the 15m triple's span.
- **This is the confluence-inflation case for decision O-1(b).**
  - Naive counting gives the 15m zone 3 partners from one physical
    displacement.
  - The recommended nested-span exclusion gives it 0.

### 5.6 Simultaneous relationships

- Not constructible on the current schedule (§3.7.4). Every HTF bucket holds
  ≥ 3 buckets of each lower timeframe (§5.9), so a simultaneously available
  LTF zone lies inside the HTF C3 range while the HTF zone lies outside.
- A synthetic test with a truncated HTF bucket is planned (T-O6). It needs a
  calendar override fixture; none is in the frozen data today.

### 5.7 W6a: anchor C1 vs C2 when the swing low is the displacement candle (decision F-2)

| k | bar end | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 18:05 | 110.00 | 111.00 | 108.00 | 109.00 |
| 1 | 18:10 | 109.00 | 109.50 | 105.00 | 105.50 |
| 2 | 18:15 | 105.50 | 112.50 | 100.00 | 112.00 |
| 3 | 18:20 | 112.00 | 115.00 | 110.00 | 114.50 |
| 4 | 18:25 | 114.50 | 116.00 | 113.00 | 115.50 |
| 5 | 18:30 | 115.50 | 119.00 | 115.25 | 118.50 |
| 6 | 18:35 | 118.50 | 121.00 | 117.00 | 120.50 |

Frozen 2/2 swings: LOWER 100.00, source 18:15 (k2), available 18:25.
Bullish 5m zones:

- **F1** [109.50, 110.00]: C1 k1, C2 = k2 (the swing low), available 18:20;
- **F2** [112.50, 113.00]: C1 = k2, available 18:25;
- [115.00, 115.25] (available 18:30) and [116.00, 117.00] (available 18:35).

Results:

- Anchor **C2** (recommended): **F1** is first. Formation 18:20; association
  knowable 18:25 (swing confirmation). F1's marker becomes visible at 18:25,
  not at 18:20.
- Anchor **C1**: F1 belongs to no leg (C1 precedes the swing), so **F2** is
  first, with association at 18:25 = F2's availability.

### 5.8 W6b: leg origin "lowest since last opposite swing" vs "most recent" (decision F-1)

| k | bar end | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 18:05 | 104.00 | 105.00 | 103.00 | 104.00 |
| 1 | 18:10 | 104.00 | 104.50 | 102.00 | 102.50 |
| 2 | 18:15 | 102.50 | 103.00 | 100.00 | 102.75 |
| 3 | 18:20 | 102.75 | 104.00 | 101.00 | 103.75 |
| 4 | 18:25 | 103.75 | 108.00 | 103.50 | 107.75 |
| 5 | 18:30 | 107.75 | 110.00 | 105.00 | 109.50 |
| 6 | 18:35 | 109.50 | 111.00 | 104.50 | 105.00 |
| 7 | 18:40 | 105.00 | 112.00 | 104.00 | 111.50 |
| 8 | 18:45 | 111.50 | 113.00 | 104.25 | 112.75 |
| 9 | 18:50 | 112.75 | 114.00 | 104.50 | 113.50 |
| 10 | 18:55 | 113.50 | 117.00 | 113.25 | 116.50 |

- Frozen 2/2 swings:
  - L1 = LOWER 100.00 (k2, available 18:25);
  - L2 = LOWER 104.00 (k7, available 18:50).
  - No UPPER swing exists: every bar makes a higher high.
- Bullish zones:
  - [103.00, 103.50] (C1 k2, C2 k3, available 18:25);
  - [104.00, 105.00] (C2 k4, available 18:30);
  - **Fb** [113.00, 113.25] (C1 k8, C2 k9, available 18:55).
- **Lowest since last opposite swing** (recommended): the leg is L1
  throughout. The first FVG is [103.00, 103.50]; Fb is not first.
- **Most recent swing**: L2 starts a new leg, so **Fb** is also marked
  first, even though no swing high ended L1's leg.

### 5.9 DEVELOPMENT design evidence (scratch prototype; formation only)

DEVELOPMENT partition (337,815 1m bars, 2024-06-21 to 2025-06-30). These
are not baselines or validation:

| tf | segments | triples | FVG (bull / bear) | equality-only triples | one-tick | half-tick midpoints | median width |
|---|---|---|---|---|---|---|---|
| 1m | 33 | 337,750 | 66,328 (34,387 / 31,941) | 7,302 | 6,509 | 52.8 % | 8 t |
| 5m | 32 | 67,488 | 12,862 (6,892 / 5,970) | 601 | 570 | 51.3 % | 18 t |
| 15m | 31 | 22,445 | 4,404 (2,428 / 1,976) | 106 | 101 | 51.8 % | 33 t |
| 1H | 29 | 5,556 | 1,153 (640 / 513) | 12 | 10 | 48.6 % | 66 t |
| 4H | 29 | 1,385 | 319 (184 / 135) | 1 | 3 | 51.4 % | 185 t |
| 1D | 23 | 175 | 40 (24 / 16) | 0 | 0 | 35.0 % | 482 t |

- **Minimum expected LTF buckets per HTF bucket.** 1m / 5m: 5; 5m / 15m:
  3; 15m / 1H: 4; 1H / 4H: 3; 4H / 1D: 6. All ≥ 3, so simultaneous
  relationships are unreachable (§3.7.4).
- **First-FVG association choices** (5m / 15m / 1H; see §9 F-1, F-2):

| tf | zones | (C1, most recent) | (C1, lowest since opposite) | (C2, most recent) | (C2, lowest since opposite) | zones whose marker differs from (C1, most recent): C1/lowest · C2/recent · C2/lowest |
|---|---|---|---|---|---|---|
| 5m | 12,862 | 7,072 | 6,821 | 7,281 | 7,028 | 251 · 769 · 888 |
| 15m | 4,404 | 2,362 | 2,279 | 2,420 | 2,345 | 83 · 324 · 355 |
| 1H | 1,153 | 591 | 558 | 617 | 586 | 33 · 82 · 105 |

- Associations knowable only after formation, counting only
  `max(formation, origin)`:
  - 5m: 42 / 37 / 732 / 547 (in the column order above);
  - 15m: 7 / 6 / 279 / 199;
  - 1H: 0 / 0 / 80 / 60.
- Both choices change several percent of the markers. The anchor (F-2)
  matters most.
- Prototype limits:
  - continuity is approximated by a 4-day proximity window, not exact
    segments;
  - the lag count omits `t_complete`.

  The figures are indicative only.

- Equality-only triples (7,302 on 1m) are correctly not zones; they are
  test material for R-A2.

### 5.10 W7: missing data (W1 rows with the 18:25–18:30 5m bar absent)

- **Frozen 1m adapter.** Episode 0 runs 18:01 … `DATA_GAP` reset at
  **18:26** (expected completion of the first missing minute). Episode 1
  starts at 18:31.
- The bullish zone [101.00, 102.25] (available 18:15) records its
  penetration at 18:21 (depth 1). It then **terminates `DATA_GAP` at 18:26**,
  with a missing-data warning.
- The later 5m closes below 101.00 (18:45) are **not** applied to it: no
  conversion and no further mitigation (no inference, no revival).
- Post-gap formation is from segment 1 only: [101.00, 101.25] (available
  19:00) and [101.75, 102.00] (available 19:05) are new zones with new ids.

### 5.11 W8: pure contract change (W1 rows; k0–k5 `MNQ 09-26`, k6 onward `MNQ 12-26`, no gap)

- **Frozen adapter.** `CONTRACT_CHANGE` reset at **18:31**, the first
  new-contract 1m bar's close (CB-2).
- The old-contract zone [101.00, 102.25] becomes **`PENDING_ADJUSTMENT`** at
  18:31. The 18:31 bar never tests it. It is not terminated, and its
  evidence stays queryable.
- New-contract zones [101.00, 101.25] and [101.75, 102.00] (`MNQ 12-26`)
  form normally. Their comparison with the pending old-contract zone is
  listed in `fvg_pending_comparisons` (`BASIS_MISMATCH`). There is no raw
  overlap, even though the raw ranges intersect.
- **M3 note (executed).** The 15m build succeeds because the switch is on a
  15m bucket boundary (18:30). A switch inside a bucket would raise
  (frozen M3, §3.1).

---

## 6. Invariants (each must have 0 violations)

| Id | Invariant |
|---|---|
| FVG-INV-1 | Every zone's C1–C3 are consecutive complete expected observations of one continuity segment and one contract |
| FVG-INV-2 | Bounds equal the defining highs / lows; `width_ticks ≥ 1`; `midpoint_half_ticks = lower + upper`; no rounding |
| FVG-INV-3 | `available_at = bar_end(C3)`; no event references a zone before it; no formation bar tests its zone |
| FVG-INV-4 | Zone facts are immutable across versions; ids follow §3.13; no duplicate ids |
| FVG-INV-5 | Equality triples never produce zones; every strict triple does (independent recomputation) |
| FVG-INV-6 | Mitigation uses 1m bars with `bar_start ≥ stage_start`, strict penetration of the near boundary of the stage's current direction; touches never record |
| FVG-INV-7 | Per stage: first penetration ≤ midpoint reach ≤ full reach in time when present; depth records are nondecreasing |
| FVG-INV-8 | Mitigation never changes bounds, width, stage or grade inputs |
| FVG-INV-9 | Conversions / retirements occur only on own-timeframe complete closes strictly beyond the far bound, with `bar_start ≥ stage_start` |
| FVG-INV-10 | Stage sequence is a prefix of FVG → IFVG → RETIRED plus at most one terminal TERMINATED / PENDING_ADJUSTMENT; never IFVG → FVG |
| FVG-INV-11 | No IFVG mitigation from bars with `bar_start <` conversion close |
| FVG-INV-12 | RETIRED / TERMINATED / PENDING objects never appear in actionable views or new relationships after their exit |
| FVG-INV-13 | Every relationship has positive intersection equal to max / min of parent bounds; contact never creates one |
| FVG-INV-14 | Labels match parents' current directions and timeframes at creation |
| FVG-INV-15 | Later parent by `available_at`; simultaneous → direction UNDEFINED, no governing timeframe |
| FVG-INV-16 | At most one relationship per pair and basis; parents active and comparable at creation |
| FVG-INV-17 | Grade components recomputed independently equal the recorded ones; ordering is the lexicographic key of §3.9 |
| FVG-INV-18 | Original width is constant across a zone's versions and stages |
| FVG-INV-19 | No raw cross-contract comparison anywhere; pending comparisons listed |
| FVG-INV-20 | At every 1m gap onset all active objects terminate; no event inside the unobserved interval; no pre-gap id after the gap |
| FVG-INV-21 | Prefix equivalence for every tested cutoff (including inside gaps) |
| FVG-INV-22 | Each leg has at most one first marker; association uses only swings with `source_at ≤` anchor; association time ≥ formation and origin times |
| FVG-INV-23 | A marker is active only during the FVG stage at or after `association_available_at`; never on an IFVG |
| FVG-INV-24 | No later FVG gets the marker because the first failed |
| FVG-INV-25 | Empty inputs give empty tables with the fixed schemas |
| FVG-INV-26 | M7A validity of every namespace |

---

## 7. Planned tests, prefix replays and visual-validation cases (none implemented)

**Formation (T-F):**

- T-F1: six timeframes, independently.
- T-F2: bullish formation.
- T-F3: bearish formation.
- T-F4: equality is not an FVG.
- T-F5: one-tick gap.
- T-F6: availability at C3 close; no earlier visibility.
- T-F7: half-tick midpoint, exact.
- T-F8: ids are stable across runs and cutoffs.
- T-F9: a triple across a session boundary or weekend is valid; across a
  gap or incomplete bar it is invalid.

**Mitigation (T-M):**

- T-M1: touch vs penetration, both directions.
- T-M2: midpoint reach, with odd / even width (M-1).
- T-M3: full reach and wick beyond.
- T-M4: depth records.
- T-M5: FVG vs IFVG stage separation.
- T-M6: mitigation does not change grades.

**Lifecycle (T-L):**

- T-L1: conversion on a strict close.
- T-L2: no conversion on the C3 close or on formation bars.
- T-L3: equality at the far bound.
- T-L4: a wick beyond does not convert.
- T-L5: IFVG retirement; no re-inversion.
- T-L6: conversion-bar ordering on a 1m zone (W2).
- T-L7: conversion-bar ordering on a 5m zone.
- T-L8: retired zones are audit-only.

**Overlap (T-O):**

- T-O1: FVG_OVERLAP same timeframe.
- T-O2: FVG_OVERLAP cross-timeframe.
- T-O3: BPR same timeframe.
- T-O4: MTF_BPR.
- T-O5: later parent by `available_at`, not source time.
- T-O6: simultaneous parents with a truncated-bucket fixture.
- T-O7: an earlier IFVG parent.
- T-O8: a retired parent creates nothing.
- T-O9: deduplication across stages.
- T-O10: nested-displacement counting (O-1).

**BPR (T-B):**

- T-B1: BPR retirement on the governing timeframe only.
- T-B2: survives parent inversion.
- T-B3: survives a lower-timeframe parent retirement (W4).
- T-B4: never inverts.

**Grading (T-G):**

- T-G1: lexicographic order.
- T-G2: partner add / end creates new versions; old versions unchanged.
- T-G3: width preserved through inversion.
- T-G4: no proximity / outcome columns.
- T-G5: ATR descriptor causal and null without history.
- T-G6: BPR ordering.

**Data and contracts (T-D):**

- T-D1: gap terminates every timeframe.
- T-D2: no inference inside a gap (W7).
- T-D3: post-gap re-establishment only.
- T-D4: trailing missing data.
- T-D5: CB-2 → PENDING_ADJUSTMENT and pending comparisons (W8).
- T-D6: CB-1 → DATA_GAP only.

**Swing association (T-S):**

- T-S1: W6a under both anchors.
- T-S2: W6b under both origins.
- T-S3: association after formation.
- T-S4: conversion before association.
- T-S5: marker ends at conversion.
- T-S6: IFVG never marked.
- T-S7: no promotion.

**Other:**

- Empty input and no-zone schemas.
- M7A validation of all namespaces.

**Independent reference.** A per-bar replay with naive formation, naive
pairwise overlap and per-bar lifecycle, reconciled against production
(the Internal Liquidity pattern).

**Prefix replays.** Cutoffs on DEVELOPMENT:

- at and one minute before a zone admission;
- at a mitigation;
- at a conversion close;
- at and inside a gap;
- at a relationship creation;
- at a BPR retirement;
- at a swing confirmation that creates an association;
- at a contract change, if any.

**Visual cases** (local HTML with prices; price-free manifest):

- W1–W8.
- From DEVELOPMENT, at least one of each:
  - bullish / bearish formation;
  - half-tick midpoint;
  - mitigation by penetration;
  - midpoint / full reach;
  - conversion;
  - IFVG retest;
  - retirement;
  - FVG_OVERLAP;
  - BPR;
  - MTF_BPR;
  - first-FVG marker before / after association;
  - gap termination;
  - per-timeframe examples (1m … 1D).
- Source spans and `available_at` markers are drawn.
- Tables separate the pre-state at `s(m)`, the evidence, the post-state at
  `e(m)` and later lifecycle.

---

## 8. Integration and implementation milestones (not authorized)

| Step | Content |
|---|---|
| FVG-I0 | Design approval after §9 decisions; D-number registration |
| FVG-I1 | Formation and zone facts for six timeframes, price-basis table, ids, empty schemas, tests |
| FVG-I2 | 1m mitigation, own-timeframe lifecycle, resets (DATA_GAP / PENDING_ADJUSTMENT), M7A logs, tests |
| FVG-I3 | Relationships, BPR objects and lifecycle, grading versions, strategy views, tests |
| FVG-I4 | Swing-leg association and first-FVG marker, tests |
| FVG-I5 | Independent reference, invariants, DEVELOPMENT validation, prefix replays, visual package |

- Module family: `src/fvg/` (new; ICT family, not an extension of ORB or of
  liquidity modules).
- It reuses frozen M3, continuity, the §G.2a adapter, the Swing detector and
  the M7A validators read-only.

---

## 9. Genuine unresolved decisions (dependency order)

Each decision changes outputs. The recommendation is used in the draft
text; alternatives are concrete.

1. **M-1: midpoint and full-zone reach — inclusive (touch) or strict?**
   - **Recommendation: inclusive.** Penetration is already strict (R-B2);
     "reach" means price attained the level.
   - Matters only for even widths (integer-tick midpoints, about half of
     zones) and exact touches of the far bound.
   - Strict would make an exact far-bound touch "not full", while the zone
     is still unconverted either way.
2. **O-1: what counts as qualifying overlap for zone priority.**
   - **(a) Partner direction.** Recommendation: count same-direction
     (`FVG_OVERLAP`) partners only. BPRs are graded as their own objects.
     - Alternative: count any partner (opposite partners raise priority).
     - Tradeoff: an opposite-direction overlap signals conflict. Counting
       it would make a zone more important because an opposing zone
       overlaps it.
   - **(b) Nested displacement.** Recommendation: exclude a partner whose
     triple source span lies within the subject's span (or vice versa),
     since it is the same physical displacement. Partners whose source
     spans overlap each other count once (as connected components, the
     Internal Liquidity confluence rule).
     - W5: the naive count gives the 15m zone 3; the recommended count
       gives 0.
     - Alternative: count all distinct zones. Simpler, but it inflates HTF
       zones with their own LTF fragments.
3. **O-2: a parent's later stage change and existing relationships.**
   - **Recommendation:** the label is a formation fact. An `FVG_OVERLAP`
     stops qualifying (`DIRECTION_DIVERGED`) when its parents' current
     directions differ. A conversion never creates a new BPR (BPRs form
     only at the later parent's admission).
   - Alternative: a conversion re-evaluates pairs and creates a new
     relationship / BPR at the conversion close. That gives more BPRs and
     needs its own id basis (stage-specific).
4. **O-3: lifecycle of a simultaneous-parent BPR (direction UNDEFINED).**
   - **Recommendation:** descriptive only — not actionable, not graded, no
     close-based retirement. It ends by data gap or contract change.
   - Alternative: retire on a close beyond either bound on the higher
     parent timeframe. That invents a rule.
   - Unreachable today (§3.7.4), so the impact is nil until a holiday
     calendar adds truncated buckets.
5. **F-2: membership anchor for the first-FVG marker — C2 or C1.**
   - **Recommendation: C2** (the displacement candle). It includes the
     V-reversal FVG whose C2 is the swing extreme (W6a: F1). The
     association can lag formation by up to `right_depth − 1` bars.
   - Alternative C1: excludes it and marks the next FVG (W6a: F2). The
     association is usually knowable at formation.
   - DEVELOPMENT impact: switching C1 → C2 changes the marker on 769
     (5m), 324 (15m) and 82 (1H) zones (§5.9).
6. **F-1: leg origin — lowest (highest) swing since the last opposite
   swing, or the most recent swing.**
   - **Recommendation: lowest since the last opposite swing.** A higher low
     without an intervening swing high continues the leg (W6b), so a leg
     really is swing extreme → opposite swing.
   - Alternative: the most recent swing. Every confirmed swing starts a
     leg, which gives more "first" markers (W6b: Fb).
   - Depends on F-2 only through the anchor time.
   - DEVELOPMENT impact with C1: 251 (5m), 83 (15m) and 33 (1H) zones
     change (§5.9).
7. **V-1: volatility normalization parameters.**
   - **Recommendation:** ATR with N = 14, simple mean of true range on the
     zone's timeframe, the formation bars included, within C3's segment;
     null with fewer than N bars.
   - Alternatives: N = 20; Wilder smoothing; excluding the formation bars
     (pre-formation volatility).
   - Descriptive only.
8. **A-1: precondition on the future shared adjustment (not FVG behavior
   today).**
   - **Recommendation:** require whole-tick additive per-contract offsets,
     so that every tick-exact FVG rule is invariant within a contract and
     well defined across contracts.
   - Alternative: ratio adjustment. It needs an explicit rounding / tolerance
     policy for gaps, penetration and closes before FVG may consume it.

No other open semantic choice was found. Representation choices made in
this draft, which do not change semantics, are §3.12 and §3.13:
- table split;
- id prefixes;
- depth records;
- `PENDING_ADJUSTMENT` naming;
- BPR mitigation recorded as descriptive data;
- the deterministic final tiebreaks.

---

## 10. Arguments vs planned tests vs executed checks

**Executed (2026-10-07):**

- **Scratch verification prototype.** Not committed and not the
  implementation. It uses the frozen `build_timeframe`,
  `continuity_segments`, `build_minute_tape` / §G.2a adapter and
  `build_swing_points`, and it:
  - printed every result in §5 (W1–W8, W6a, W6b);
  - confirmed the CB-2 reset time and that M3 builds 15m when the roll is
    on a bucket boundary.
- **DEVELOPMENT design evidence (§5.9):**
  - formation counts on six timeframes;
  - equality and one-tick counts;
  - half-tick share;
  - the expected-bucket nesting minimums;
  - first-FVG marker counts under the four F-1 × F-2 combinations.
- No repository test was added or run for FVG (design only). The repository
  suite was not re-run: no code changed on this branch.

**Arguments (not tests):**

- §3.2 single direction per triple;
- §3.7.4 simultaneous-overlap impossibility with ≥ 3 nested buckets;
- §4.1 classify-before-admit timing;
- §4.3 BPR survival only for lower-timeframe parents;
- §3.10 association deadline.

**Planned (§6, §7):**

- the invariants;
- unit / synthetic tests;
- independent reference;
- prefix replays;
- visual cases.

None is implemented.
