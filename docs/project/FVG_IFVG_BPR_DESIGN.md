# FVG / IFVG / Overlap / BPR (ROADMAP 4, ICT family): Consolidated Design (rev 2)

**Status: DESIGN APPROVED — IMPLEMENTATION AUTHORIZED; NOT IMPLEMENTED / NOT VALIDATED / NOT FROZEN (2026-10-07).**

- The design authority authorized implementation of rev 2 (FVG-I1 – FVG-I5) on 2026-10-07; the decisions are
  registered as **D-148 – D-152**. Design approval is distinct from implementation validation (machine checks
  plus human visual review) and from feature freeze; neither has happened.
- Rev 2.1 (same date) adds only the §3.11.4 adjustment-compatibility clarification; no formation, interaction,
  lifecycle, relationship, grading or association rule changed.

- Branch `fvg-design` (from `main` `6c3c909`, after the Internal Liquidity
  freeze). Rev 1: `49717c2`. This revision applies every confirmed
  decision (§1.3) and corrects the defects found in rev 1 (§1.4).
- Design only. No FVG code exists. No frozen module changes: M3,
  continuity, the §G.2a reset adapter, Swing, Market Structure,
  External / Internal Liquidity and M7.
- No user-facing semantic choice remains open. Routine representation
  choices are resolved deterministically and listed in §9.2.
- Every worked example (§5) was **executed** with a scratch verification
  prototype built on the frozen M3 builder, continuity segmentation,
  §G.2a adapter and Swing detector. The prototype is not committed and is
  not the implementation. §10 separates source-supported definitions,
  approved operational rules, arguments, executed scratch checks and
  planned validation.

---

## 0. Contents

1. Sources, confirmed decisions, rev 1 corrections, frozen contracts
2. Requirement → section mapping
3. Design
   - 3.1 Observations, ticks and continuity
   - 3.2 Formation: C1/C3 wick gap with a C2 directional body
   - 3.3 Normalized gap strength
   - 3.4 Directional lifecycle: FVG → IFVG → RETIRED
   - 3.5 Mitigation observation on canonical 1m
   - 3.6 Causal batch, eligibility guards and exit precedence
   - 3.7 Relationship episodes: FVG_OVERLAP, BPR, MTF_BPR
   - 3.8 BPR objects and their independent lifecycle
   - 3.9 Priority, formation groups and BPR ranking
   - 3.10 First FVG in a directional swing leg
   - 3.11 Missing data, contract changes, price basis and future adjustment
   - 3.12 Output tables, M7A namespaces and strategy-facing views
   - 3.13 Identity, immutable versions and provenance
4. Consistency review
5. Worked examples (executed)
6. Invariants
7. Planned tests, prefix replays and visual-validation cases
8. Integration and implementation milestones
9. Decision outcomes and routine representation choices
10. Evidence classes

---

## 1. Sources, confirmed decisions, rev 1 corrections, frozen contracts

### 1.1 Source-supported definitions

As characterized by the design authority's source review:

- [ICT Month 04 FVG lesson](https://www.youtube.com/watch?v=FgacYSN9QEo);
- [ICT 2022 Mentorship Episode 6](https://www.youtube.com/watch?v=Bkt8B3kLATQ).

| Element | Source support |
|---|---|
| Three-candle pattern whose gap is between C1's wick and C3's wick (bullish: C3 low above C1 high; bearish: C3 high below C1 low) | ICT teaching |
| Candles of mixed body direction may form the pattern | ICT teaching |
| Any numerical displacement / size threshold | **Not attributed to ICT.** This design has none |

### 1.2 Approved operational rules (ours, deterministic)

- At least one tick of gap; equality is not an FVG.
- **C2 directional body spans the gap** (§3.2). This is our deterministic
  operational rule, not an ICT quote. C1 and C3 may be any colour,
  including doji. A doji C2 fails.
- Mitigation is observed on canonical 1m.
  - Initial mitigation is strict observed penetration past the near
    boundary.
  - Exact touch counts as midpoint / far-boundary reach.
- Conversion and retirement require a strict close beyond the far boundary
  on the governing timeframe. Wicks and equality never convert.
- Priority: timeframe → same-direction formation-group overlap contribution
  → normalized gap strength → raw width → deterministic tiebreaks.
- Strength = gap width / simple ATR(14) of the observations before C1.
- First FVG in a swing leg: C2 anchor; leg origin = most extreme same-side
  confirmed swing since the last opposite swing.
- Conservative missing-data termination; pure rolls → pending adjustment;
  no raw cross-contract comparison.

### 1.3 Confirmed decision outcomes (closed; were rev 1 §9)

| Rev 1 item | Outcome | Sections |
|---|---|---|
| Formation (new) | C2 directional body must span the gap | 3.2, W3 |
| M-1 midpoint / full reach | Inclusive (exact touch counts); penetration stays strict | 3.5, W1, W4 |
| O-1(a) partner direction | Only same-current-direction overlap raises a zone's priority; BPRs ranked separately | 3.9 |
| O-1(b) nested formations | Overlapping formations of one **formation group** contribute once (neither every fragment, nor none) | 3.9.2, W5 |
| O-2 parent stage change | Reassess prospectively. A conversion that makes a pair opposite creates a new BPR / MTF_BPR (converting parent's new direction, conversion instant, its timeframe); relationship episodes keyed by parent stages | 3.7, W7, W8 |
| O-3 undefined direction | Descriptive only (not actionable, not ranked, no close-based retirement) | 3.7.5, 3.8 |
| F-2 anchor | C2 | 3.10, W9a |
| F-1 leg origin | Most extreme same-side swing since the last opposite swing; a higher low (lower high) does not restart a leg; a more extreme origin starts a new leg | 3.10, W9b, W9c |
| V-1 volatility | Replaced by **normalized gap strength** (pre-C1 ATR(14)); it enters priority as key 3 | 3.3, W10 |
| A-1 adjustment method | **Deferred** to the shared adjustment process; FVG states the compatibility properties it requires | 3.11.4 |

### 1.4 Rev 1 defects corrected

| Defect | Correction | Sections |
|---|---|---|
| One-sided mitigation predicates counted a bar wholly beyond the zone as penetration | Observation classes (zone trade, near contact, far contact, spanning, beyond) and gap-through evidence; milestones only from observed zone trades | 3.5, W4 |
| Blanket claim that a BPR survives a parent retirement only when the parent is on a lower timeframe | Explicit direction / bound / timeframe / eligibility conditions; same-timeframe opposite-direction example | 3.8.2, W1, W6 |
| Contract change processed after classification; first new-contract bar could evaluate old objects | Basis-eligibility guard and resets at batch step 0; single-exit precedence | 3.6, W12 |
| W3 "equality" fixture was not an equality | True wick-boundary equality fixtures (both directions) | W3 |
| "Every table is empty" for no-zone input | Zone-dependent outputs empty with fixed schemas; data warnings may exist; manifest exists | 3.12.3 |
| Approximate association statistics (proximity proxy) | Exact segments and exact causal deadline; causal self-check | 3.10, 5.14 |
| Rev 1 formation counts (no C2 rule) | Recomputed; rev 1 counts kept only as labelled superseded figures | 5.14 |

### 1.5 Frozen contracts relied on (unchanged)

| Contract | Decision | Use |
|---|---|---|
| Canonical 1m bars, bar-end labels, ET | CLAUDE.md, D-111 | Mitigation source |
| M3 timeframe builder | D-116, D-119 | 5m–1D observations, `is_complete`, `available_at = bar_end`; mixed-contract buckets raise |
| Expected-schedule continuity | D-137 | "Consecutive complete observations within valid continuity" |
| Swing (explicit 2/2 reference `swing-pivot-v1`) | D-135 – D-138 | Leg origins / terminators; `BAR_SPAN` refs |
| Market Structure batch and resets | D-141, D-142 | Classify-before-admit; §G.2a `DATA_GAP` / `CONTRACT_CHANGE` (CB-1 / CB-2); `replay_cutoff`; prefix equivalence |
| M7A State contract | D-129 – D-131 | Lifecycle logs; causal keys; one transition per entity and trigger |
| Conservative gap treatment | D-142, D-147 | Termination at the 1m onset; post-gap re-establishment only |

---

## 2. Requirement → section mapping

| Requirement / outcome / correction | Sections | Examples | Invariants | Tests |
|---|---|---|---|---|
| Six timeframes, independent | 3.1 | W2, W6, 5.14 | FVG-INV-1 | T-F1 |
| Wick gap ≥ 1 tick, equality excluded | 3.2 | W3 | FVG-INV-2, -5 | T-F2 … T-F4 |
| C2 directional body spans gap; C1 / C3 any colour; doji C2 fails | 3.2 | W3 | FVG-INV-5 | T-F5 … T-F8 |
| Complete, continuous, available at C3 close, no retrospective test | 3.1, 3.2, 3.6 | W1, W2 | FVG-INV-1, -3 | T-F9, T-L2 |
| Bounds, exact midpoint, width, evidence, span, ids | 3.2, 3.13 | W1, W3 | FVG-INV-2, -4 | T-F10, T-F11 |
| Normalized gap strength, insufficient / zero baseline | 3.3, 3.9 | W10 | FVG-INV-18 | T-G3 … T-G5 |
| Lifecycle FVG → IFVG → RETIRED; strict closes; no re-inversion | 3.4 | W1, W2 | FVG-INV-9, -10 | T-L1 … T-L5 |
| Mitigation classes, inclusive reach, gap-through | 3.5 | W1, W4 | FVG-INV-6 … -8 | T-M1 … T-M9 |
| Conversion-bar ordering, same-close rules | 3.6 | W2, W7 | FVG-INV-11 | T-L6, T-L7 |
| Contract guard, single exit per instant | 3.6.2, 3.6.3 | W12 | FVG-INV-12, -27 | T-D5, T-D7 |
| FVG_OVERLAP / BPR / MTF_BPR; episodes; conversion-created BPR | 3.7 | W5 … W8 | FVG-INV-13 … -16 | T-O1 … T-O12 |
| BPR independent lifecycle | 3.8 | W1, W6 | FVG-INV-17 | T-B1 … T-B5 |
| Priority, formation groups, BPR ranking | 3.9 | W5, W10 | FVG-INV-18, -19 | T-G1 … T-G8 |
| First FVG (C2 anchor, extreme origin, exact deadline) | 3.10 | W9a … W9d | FVG-INV-22 … -24 | T-S1 … T-S9 |
| Missing data, pure roll, basis, adjustment compatibility | 3.11 | W11, W12 | FVG-INV-20, -21 | T-D1 … T-D8 |
| Empty / no-zone outputs | 3.12.3 | — | FVG-INV-25 | T-E1 |

---

## 3. Design

### 3.1 Observations, ticks and continuity (unchanged from rev 1)

- **Observations.** 1m: canonical 1m bars. 5m, 15m, 1H, 4H, 1D: M3
  observations. Each timeframe is processed independently.
- **Ticks.** All comparisons are integer ticks (MNQ 0.25). Non-aligned
  prices fail closed.
- **Continuity.** C1, C2, C3 are three consecutive expected observations of
  one continuity segment (D-137): present, `is_complete`, one contract.
  - A triple may cross an expected session boundary or a weekend, because
    expected continuity does.
  - A missing or incomplete observation or a contract change ends the
    segment.
- **Mixed-contract buckets** raise in frozen M3 (D-119). A pure roll inside
  a bucket therefore fails closed for that timeframe until shared roll
  handling exists. On DEVELOPMENT every roll lies in a missing session.

### 3.2 Formation: C1/C3 wick gap with a C2 directional body

For consecutive complete observations C1, C2, C3 (ticks; `o`, `h`, `l`,
`c`):

| Direction | Wick gap (source-supported) | C2 directional body spans the gap (approved operational rule) | `lower` | `upper` |
|---|---|---|---|---|
| BULLISH | `l(C3) − h(C1) ≥ 1` | `c(C2) > o(C2)` **and** `o(C2) ≤ h(C1)` **and** `c(C2) ≥ l(C3)` | `h(C1)` | `l(C3)` |
| BEARISH | `l(C1) − h(C3) ≥ 1` | `c(C2) < o(C2)` **and** `o(C2) ≥ l(C1)` **and** `c(C2) ≤ h(C3)` | `h(C3)` | `l(C1)` |

- **Inclusions.**
  - C1 and C3 may be bullish, bearish or doji (W3 mixed colours).
  - Body boundaries may equal the gap boundaries (`o(C2) = h(C1)`,
    `c(C2) = l(C3)` is valid; W3).
  - C2's wick may become a confirmed swing extreme; that never excludes it
    (W9a).
- **Exclusions.**
  - **Equality** (`l(C3) = h(C1)` or `h(C3) = l(C1)`) is not an FVG
    (W3, both directions).
  - **A wick gap whose C2 fails the body rule** is rejected and recorded as
    audit with its reason: `C2_NOT_DIRECTIONAL` (including doji) or
    `C2_BODY_NOT_SPANNING`.
  - No size, displacement, body/range or wick-proportion threshold exists.
    The body predicate is a formation requirement, not a score.
- **Single direction per triple.** Both wick gaps would need
  `h(C3) < l(C1) ≤ h(C1) < l(C3) ≤ h(C3)`.
- **Lemmas used later** (bullish; bearish mirrors):
  - `l(C2) ≤ o(C2) ≤ h(C1) < l(C3)`, so C2's low is strictly below C3's
    low.
  - `h(C2) ≥ c(C2) ≥ l(C3) > h(C1)`.
- **Values.**
  - `width_ticks = upper − lower ≥ 1`;
    `width_points = width_ticks × tick`.
  - `midpoint_half_ticks = lower + upper` (exact). `midpoint` is an exact
    decimal and is never rounded. Odd widths give half-tick midpoints.
  - Midpoint comparisons use `2 × price_ticks` against
    `midpoint_half_ticks`.
- **Timing.** `source_at = e(C1)`, `source_end_at = e(C3)`, `available_at =
  e(C3)`. Source span = `[s(C1), e(C3))`.
- **Evidence.** The three observations' OHLC and `BAR_SPAN` refs. The
  triple ref is `BAR_SPAN:<instrument>|<contract>|<tf>|<e(C1)>|<e(C3)>`
  (frozen format, D-138).
- **Immutable.** Bounds, midpoint, widths, original direction, evidence,
  timing and the normalization record (§3.3) never change. Stage,
  mitigation, relationships and grades are separate versioned records.

### 3.3 Normalized gap strength

- **Baseline.** `baseline_atr_ticks` is the simple mean true range of the 14
  complete observations of the zone's own timeframe ending immediately
  before C1, all in C1's continuity segment. C1, C2 and C3 are excluded.
  - `TR = max(h − l, |h − c_prev|, |l − c_prev|)`, with `c_prev` the
    previous observation's close.
  - The first baseline bar therefore also needs the close of the
    observation before it. The baseline requires **15 consecutive
    observations** of the segment immediately before C1. This is a routine
    choice: one uniform TR definition, and no history across a segment
    boundary.
- `normalized_gap_strength = width_points / baseline_atr_points =
  width_ticks × 14 / Σ TR_ticks`. It is stored as an exact rational
  (`strength_num`, `strength_den`) plus a decimal rendering.
- **Status** (`normalization_status`):

  | Status | Condition | Strength |
  |---|---|---|
  | `OK` | 15 observations available and `Σ TR > 0` | exact rational |
  | `INSUFFICIENT_HISTORY` | fewer than 15 consecutive observations before C1 in the segment | null |
  | `ZERO_BASELINE` | `Σ TR = 0` (flat history) | null |

  No zero or infinite strength is fabricated, no history is imputed, and no
  FVG is discarded for its status.
- Known at C3 close (the inputs end before C1). It is part of the immutable
  formation record and preserved through mitigation and inversion.
- **Invariance (argument).** The ratio is unchanged by an additive price
  offset and by a positive scaling of all prices of the contract. This is
  relevant to §3.11.4.

### 3.4 Directional lifecycle: FVG → IFVG → RETIRED

M7A namespace `fvg.zone`; entity `zone_id`; initial `FVG`.

| From | To | Trigger | `reason_code` |
|---|---|---|---|
| FVG (bullish) | IFVG (bearish) | own-timeframe complete close `< lower` | `CONVERTED` |
| FVG (bearish) | IFVG (bullish) | own-timeframe complete close `> upper` | `CONVERTED` |
| IFVG (bullish) | RETIRED | own-timeframe complete close `< lower` | `RETIRED` |
| IFVG (bearish) | RETIRED | own-timeframe complete close `> upper` | `RETIRED` |
| FVG / IFVG | TERMINATED | 1m §G.2a gap onset | `DATA_GAP` |
| FVG / IFVG | PENDING_ADJUSTMENT | pure contract change (CB-2) | `CONTRACT_CHANGE` |

- Only bars with `bar_start ≥ stage_start` classify. `stage_start` =
  `available_at` (FVG stage) or the conversion close (IFVG stage).
- The IFVG inherits the bounds, midpoint, original width and normalization
  record, with the direction reversed.
- No IFVG → FVG edge. Equality and wicks never convert or retire.
- Terminal states: RETIRED, TERMINATED, PENDING_ADJUSTMENT. The last is
  terminal within a raw-basis run (§3.11).

### 3.5 Mitigation observation on canonical 1m

Per zone and stage: 1m bars `m` with `bar_start(m) ≥ stage_start` and an
eligible basis (§3.6.2). `R = [l, h]` is the bar's observed range; the zone
`Z = [L, U]` is closed. No intrabar path and no trade between consecutive
bars is inferred. Classes are statements about the observed range only.

**Observation classes** (bullish current direction = price expected above
the zone, retracement downward; bearish mirrors):

| Class | Bullish condition | Bearish condition | Meaning |
|---|---|---|---|
| `ZONE_TRADE` | `l < U` **and** `h ≥ L` (R meets `[L, U)`) | `h > L` **and** `l ≤ U` (R meets `(L, U]`) | Observed trading strictly past the near boundary, within the closed zone. **Initial mitigation** |
| ↳ `SPANNING` | `ZONE_TRADE` and `l ≤ L` and `h ≥ U` | mirrored | The bar's range covers the whole zone |
| ↳ `FAR_CONTACT` | `ZONE_TRADE` and `h = L` | `ZONE_TRADE` and `l = U` | The only in-zone trade is exactly at the far boundary, reached from beyond |
| `NEAR_CONTACT` | `l = U` | `h = L` | Exact touch of the near boundary only. **Not** mitigation |
| `BEYOND` | `h < L` | `l > U` | Wholly beyond the far boundary. **Never** mitigation |
| (no contact) | `l > U` | `h < L` | Nothing recorded |

**Milestones** (recorded once per stage, at the first qualifying bar's
`e(m)`; only `ZONE_TRADE` bars qualify):

| Milestone | Bullish | Bearish |
|---|---|---|
| First mitigation (penetration) | `ZONE_TRADE` | `ZONE_TRADE` |
| Midpoint reached (inclusive) | `ZONE_TRADE` and `2·l ≤ midpoint_half_ticks` | `ZONE_TRADE` and `2·h ≥ midpoint_half_ticks` |
| Full zone reached (inclusive) | `ZONE_TRADE` and `l ≤ L` | `ZONE_TRADE` and `h ≥ U` |

- **Depth** (on `ZONE_TRADE` bars):
  - `penetration_depth_ticks` = `U − l` (bullish) / `h − L` (bearish),
    uncapped (it may exceed the width);
  - `in_zone_depth_ticks` = `U − max(l, L)` / `min(h, U) − L`, capped at
    the width.

  A depth record is written each time the stage maximum grows.
- **Gap-through evidence.** A `BEYOND` bar observed while the stage has no
  `ZONE_TRADE` yet records `GAP_THROUGH` once per stage, with the bar ref.
  It says price passed the zone between observations without an observed
  trade inside it. It never sets a milestone. Close-based conversion
  (§3.4) remains independently applicable (W4a: the same 5m bar converts on
  its close).
- **Coherence (argument).**
  - Midpoint and full reach imply a `ZONE_TRADE` on the same bar, so
    `first_mitigation_at ≤ midpoint_at ≤ full_at` whenever present.
  - Depth records are nondecreasing.
  - A `FAR_CONTACT` bar sets all three milestones at once (W4b), because
    its in-zone trade is at the far boundary.
  - Half-tick midpoints can never be touched exactly; inclusive vs strict
    differs only for even widths.
- Mitigation never changes bounds, widths, normalization, stage or grade.

### 3.6 Causal batch, eligibility guards and exit precedence

#### 3.6.1 Batch at each instant `t`

All steps read the state left by the previous steps; nothing is
re-classified within the batch.

| Step | Content |
|---|---|
| **0. Resets and basis guards** | 1m `DATA_GAP` onset at `t`: every active zone, BPR, relationship episode and marker terminates (`DATA_GAP`) and a warning is written. Pure contract change at `t` (CB-2, the first new-contract bar's close): every object whose basis contract differs from the bar's contract becomes `PENDING_ADJUSTMENT` at `t` and is **excluded** from steps a–b for that bar |
| **a. 1m mitigation** | The 1m bar ending at `t` is tested against every active, basis-eligible zone and BPR, with the **stage at `s(m)`** |
| **b. Close classification** | Every complete timeframe bar ending at `t`: its timeframe's zones (conversion / retirement) and the BPRs it governs (retirement), basis-eligible only, `bar_start ≥ stage_start` / BPR `available_at` |
| **c. Admissions** | Zones whose C3 closes at `t`; swings confirmed at `t` (frozen detector) |
| **d. Relationship reassessment** | From the **final** state after steps 0–c: relationship episodes start or end (§3.7); BPR objects for new opposite-direction episodes |
| **e. Associations and markers** | §3.10 |
| **f. Formation groups and grade versions** | §3.9 |

- **Classify-before-admit.** Admissions at `t` were never classified by the
  bar closing at `t` (D-141 pattern). The first mitigation candidate is the
  1m bar starting at `e(C3)`.
- **Conversion-bar ordering.** Step a records FVG-stage mitigation by the
  bar ending at `t`; step b converts at `t`. The IFVG stage starts at `t`
  and its first test is the next 1m bar (W2, W7). The conversion bar never
  counts as an IFVG retest.
- **No same-close chaining.**
  - An IFVG created at `t` cannot retire at `t`.
  - A BPR created at `t` is tested only by governing bars with
    `bar_start ≥ t`.
  - An episode created at `t` is never ended at `t`: step d runs once, on
    the final state.
- **Visibility.** A bar starting at `t` sees facts with `available_at ≤ t`.
  The explicit `replay_cutoff` is required, and prefix equivalence holds
  for every cutoff.

#### 3.6.2 Basis-eligibility guard

- An object is evaluated against a bar only if the bar's price basis equals
  the object's evaluation basis.
- On the raw basis that means **the same contract**. The first new-contract
  1m bar never mitigates, converts or retires an old-contract object. W12:
  without the guard, the 18:31 bar would record full reach on the old zone;
  with it, nothing is recorded and the zone becomes `PENDING_ADJUSTMENT` at
  18:31.
- HTF bars that would mix contracts are already rejected by frozen M3.

#### 3.6.3 Single exit per entity and instant; precedence

Each lifecycle entity has at most one exit transition per instant (M7A: one
transition per entity and trigger; terminal states have no out-edges).
Coincident candidates are resolved by construction:

- A `DATA_GAP` onset is the expected completion of a **missing** 1m
  observation. No 1m bar ends then, and every timeframe bar ending then
  contains the missing minute and is incomplete. So no mitigation or
  classification coincides with it.
- `CONTRACT_CHANGE` excludes the old-contract objects from steps a–b at
  that instant.
- A zone's FVG → IFVG and IFVG → RETIRED need distinct closes, because the
  IFVG stage starts at the conversion close.
- A BPR has one governing timeframe. A marker ends only through its zone's
  conversion or reset.

If an implementation ever finds two exits for one entity at one instant,
the precedence is DATA_GAP > CONTRACT_CHANGE > RETIRED / CONVERTED, and the
run fails validation (FVG-INV-27). Only the final state at `t` is
materialized for each entity.

### 3.7 Relationship episodes: FVG_OVERLAP, BPR, MTF_BPR

#### 3.7.1 Stage identities and episodes

- A **stage identity** is `(zone_id, stage)`, stage ∈ {FVG, IFVG}.
- An **episode** is a pair of stage identities that, at instant `t`
  (step d, final state), are:
  - both active;
  - basis-comparable;
  - intersecting with positive width: `i_lower = max(lowers)`,
    `i_upper = min(uppers)`, `i_upper − i_lower ≥ 1`. Contact is never a
    relationship.
- **Creation.** An episode is created at `t` iff its stage-identity pair
  differs from the pair's previous episode (or the pair has none).
  - Pair keys change only through an **admission** or a **conversion** at
    `t`, so every creation has at least one *mover* (a parent admitted or
    converted at `t`).
- **End.** An episode ends at `t` (`fvg.overlap` exit) when:
  - a parent's stage changes: `PARENT_STAGE_CHANGED` (a successor episode
    may start at the same `t`);
  - a parent retires: `PARENT_RETIRED`;
  - a parent terminates: `PARENT_TERMINATED`;
  - a parent becomes pending: `PARENT_PENDING`.
- **Deduplication.** An unchanged parent-stage pair never yields a second
  episode or BPR. Stages only progress, so a pair has at most three
  episodes (FVG/FVG → one IFVG → IFVG/IFVG) over its life.

#### 3.7.2 Labels (fixed per episode)

| Current directions at creation | Same timeframe | Different timeframes |
|---|---|---|
| Same | `FVG_OVERLAP` | `FVG_OVERLAP` (`cross_timeframe = true`) |
| Opposite | `BPR` | `MTF_BPR` |

#### 3.7.3 The directional event (generalized "later parent")

- **At admission:** the mover is the newly admitted zone; its event time is
  its `available_at`.
- **At conversion:** the mover is the converting parent; its event time is
  the conversion close.
- **One mover:** the mover is the later parent. For an opposite-direction
  episode, the BPR direction is the mover's current direction and the
  governing timeframe is the mover's timeframe.
- **Two movers at the same `t`:** there is no unique later directional
  event, so the direction is `UNDEFINED` and there is no governing
  timeframe (§3.7.5). No arbitrary order is imposed.

#### 3.7.4 Reassessment after conversion (O-2 outcome)

- A conversion at `t` changes the converting parent's stage identity.
  Every active pair containing it is reassessed at step d of `t` from the
  final state:
  - a previously same-direction pair that is now opposite ends its
    `FVG_OVERLAP` episode (`PARENT_STAGE_CHANGED`) and starts a
    `BPR` / `MTF_BPR` episode (W7, 18:50);
  - a previously opposite pair that is now same-direction starts an
    `FVG_OVERLAP` episode (W6, 19:20).
- **Both parents convert at `t` and remain same-direction:** one successor
  episode is created from the final state. No transient opposite-direction
  episode or BPR is materialized (W8, 19:00).
- An existing BPR **object** keeps its bounds, direction and lifecycle
  (§3.8); only the episode that produced it ends.

#### 3.7.5 Undefined direction: reachability (argued and checked)

Two movers with opposite resulting directions and positive intersection at
one instant cannot occur, except through simultaneous admissions on
truncated buckets:

- **Admission + conversion at `t`.** The new zone's C3 and the converter's
  bar both close at `t` with the same close `c`.
  - New bullish N: `N.upper = l(C3) ≤ c`. A converter that became bearish
    satisfies `c < X.lower`, so `N.upper < X.lower`: disjoint.
  - New bearish N: `N.lower = h(C3) ≥ c > X.upper`: disjoint.
- **Conversion + conversion at `t`** ending opposite: `c < X.lower` and
  `c > Y.upper`, so `Y.upper < X.lower`: disjoint.
- **Admission + admission at `t`.**
  - Same timeframe: one triple per bar end, so impossible.
  - Different timeframes: the LTF zone lies inside
    `[l(HTF C3), h(HTF C3)]` and the HTF zone lies outside it whenever the
    HTF C3 bucket holds ≥ 3 LTF buckets.
  - On the DEVELOPMENT expected schedule the minimum is 3 (1H per 4H; all
    pairs in §5.14). So this is unreachable without calendar-truncated
    buckets.

The descriptive treatment (O-3) applies whenever `UNDEFINED` arises:
- recorded with both parents;
- not actionable;
- not ranked;
- no close-based retirement;
- ends only by `DATA_GAP` / `CONTRACT_CHANGE`.

### 3.8 BPR objects and their independent lifecycle

#### 3.8.1 Object

- Each `BPR` / `MTF_BPR` episode creates one BPR object (`bpr_id`). It
  holds:
  - intersection bounds, exact midpoint and width;
  - `available_at` = episode creation `t`;
  - direction and governing timeframe (§3.7.3);
  - the immutable parent stage identities.
- M7A namespace `fvg.bpr`:

| From | To | Trigger | `reason_code` |
|---|---|---|---|
| ACTIVE (bullish) | RETIRED | governing-timeframe complete close `< lower`, `bar_start ≥ available_at` | `RETIRED` |
| ACTIVE (bearish) | RETIRED | governing-timeframe complete close `> upper`, `bar_start ≥ available_at` | `RETIRED` |
| ACTIVE | TERMINATED | 1m gap onset | `DATA_GAP` |
| ACTIVE | PENDING_ADJUSTMENT | pure contract change | `CONTRACT_CHANGE` |

- No inversion. Mitigation is recorded descriptively with the BPR's
  direction (§3.5). An `UNDEFINED` BPR has no RETIRED edge.

#### 3.8.2 Independence from parents (corrected argument)

- **Parent events never trigger BPR exits.** A parent's conversion,
  retirement, grade change or episode end is not a BPR trigger. The BPR
  exits only by its own predicate or a reset.
- **When a parent's exit close also satisfies the BPR's own predicate.**
  Let:
  - the BPR have direction `d`, bounds `[bl, bu]` and governing timeframe
    `G`;
  - the parent P exit at its timeframe close `c` (bar ending at `t`),
    with current direction `dP` and bounds `[pl, pu]`.

  The BPR also retires at `t` **iff all** of the following hold:
  1. a complete `G` bar ends at `t`, with `bar_start ≥` BPR
     `available_at`. Then its close equals `c`: two bars ending at the
     same instant share the last 1m close.
  2. `c` is beyond the BPR's far bound for `d`: `c < bl` (`d` bullish) or
     `c > bu` (`d` bearish).

  Consequences:
  - **`dP = d`.** P's exit close is beyond P's far bound in direction `d`.
    The intersection's far bound is never beyond P's (`bl ≥ pl`,
    `bu ≤ pu`), so condition 2 holds. The BPR retires at `t` iff condition
    1 holds: P is on `G` or on a timeframe whose bar ends coincide with `G`
    bar ends at `t`.
  - **`dP ≠ d`.** P's exit close is beyond P's far bound in the opposite
    direction: for `d` bullish, `c > pu ≥ bu ≥ bl`. That never satisfies
    condition 2, so **the BPR survives, on any timeframe** (W1: a bearish
    IFVG parent retires on a same-timeframe close above its upper bound;
    the bullish BPR survives).
  - A lower-timeframe P close that is not a `G` close never retires the
    BPR (W6).

### 3.9 Priority, formation groups and BPR ranking

#### 3.9.1 Zone priority (actionable zones: stage FVG or IFVG)

Sort descending by:

1. `timeframe_rank` (1m = 1 … 1D = 6);
2. `overlap_contribution`: the number of qualifying formation groups
   (§3.9.2);
3. `normalized_gap_strength`. `OK` values rank above `INSUFFICIENT_HISTORY`
   / `ZERO_BASELINE` at equal keys 1–2; the null statuses tie with each
   other on this key;
4. `original_width_ticks`;
5. Final deterministic tiebreaks, which express no preference:
   `available_at` ascending, then `zone_id` ascending.

- All components are recorded per grade version. There is no opaque score,
  weight, proximity, direction bias or outcome input. Original width and
  strength never change through mitigation or inversion.

#### 3.9.2 Formation groups (O-1(b) outcome; objective and reproducible)

- **Qualifying partners** of zone S at instant `t`: zones in an active
  `FVG_OVERLAP` episode with S at `t`. These are same current direction,
  basis-comparable and positive price intersection; partner stages count by
  `zone_id`, never per stage.
- **Grouping eligibility and edges.** Two qualifying partners P, Q are
  linked iff their triple source spans `[s(C1), e(C3))` intersect with
  positive duration (half-open intervals, so end-to-start contact does not
  link). Spans are source-bar evidence only; price, direction and
  timeframe play no part.
- **Groups** are the connected components of that graph, so transitive
  chains merge. Partial overlaps link; a chain P–Q–R is one group even if P
  and R do not overlap. Chains are bounded in practice, because every
  member must also price-overlap S.
- **`overlap_contribution(S, t)`** = the number of groups. W5: three nested
  5m partners of the 15m zone form one group, so the contribution is 1.
  Each 5m zone has one partner group (the 15m zone), so its contribution
  is 1.
- **Representative** (evidence, deterministic): the member with the highest
  `timeframe_rank`, then the greatest width, then the earliest
  `available_at`, then `zone_id`. Members are recorded in full.
- **Prospective updates.** When a partner's episode ends (its conversion
  makes the pair opposite; it retires, terminates or becomes pending), the
  groups are recomputed from the remaining partners at `t`. A new grade
  version is written iff the contribution or the member set changes.
  Earlier versions are never rewritten.
- **Independence from S's own stage.** S's conversion ends S's same-direction
  episodes and may start new ones (§3.7.4). The contribution always follows
  the current episodes.

#### 3.9.3 BPR ranking (separate list; never compared with zones)

Active BPR objects with a defined direction are ranked descending by:

1. governing `timeframe_rank`;
2. `bpr_width_ticks` (intersection width; compared **only among BPRs**);
3. `available_at` ascending, then `bpr_id`.

`UNDEFINED` BPRs are listed descriptively and not ranked. No comparison
between a BPR width and a zone width is defined or used.

### 3.10 First FVG in a directional swing leg

**Inputs.** The zone's own-timeframe `swing_points` from the frozen detector
under the explicit 2/2 reference definition, restricted to the zone's
continuity segment. Bullish case shown; bearish mirrors (origin UPPER,
terminator LOWER, "highest").

1. **Anchor:** C2 (`e(C2)`).
2. **Last terminator:** `U` = the last UPPER swing in the segment with
   `source_end_at < e(C2)`.
3. **Origin candidates:** LOWER swings in the segment with
   `source_at ≤ e(C2)` and (`U` absent or `source_at > U.source_end_at`).
4. **Origin `O`:** the **lowest** candidate (ties: earliest `source_at`).
   No candidate means the zone is in no leg.
   - A higher low alone never changes `O`, so it does not restart the leg
     (W9b).
   - A **new lower** low becomes `O` for zones anchored at or after it,
     which starts a new leg (W9c). This is the deterministic rule, stated
     explicitly.
5. **First:** zone F is the first of leg `O` iff no other same-direction
   zone of that timeframe in leg `O` has an earlier `available_at` (ties:
   earlier `e(C2)`, then `zone_id`). Failed or converted earlier zones
   still count, so no later FVG is promoted.
6. **Association time:** `association_available_at = max(F.available_at,
   O.available_at, D)`.
   - `D` is the exact deadline: the first instant after which no
     unresolved swing candidate can change steps 2–5.
   - For 2/2:
     - C2's low is strictly below C3's (§3.2 lemma), so the only candidate
       that can still be unresolved at `e(C3)` is the equal-low run ending
       at C2.
     - Let `j` be that run's first observation. If both observations
       before `j` exist in the segment and neither has a strictly lower
       low (left-qualified), `D = e(C2 + 2)`. Otherwise `D =
       F.available_at`.
   - **Opposite terminators** with `source_end_at < e(C2)` have their
     plateau end at or before C1, so they are confirmed by `e(C3)`.
     (Bullish: C1 cannot be an UPPER swing, since `h(C3) > h(C1)`.)
   - General depths: `D` = the latest resolution instant of any candidate
     run that starts at or before the anchor and is unresolved at
     `F.available_at`.
   - **Cutoffs before `D`:** no association row exists, no marker is
     visible, and nothing provisional is shown (W9d at 18:25).

**Marker** (M7A `fvg.first_marker`; entity `association_id`; available at
`association_available_at`):

- active only while the zone is in the FVG stage;
- survives mitigation;
- ends `CONVERTED` at the conversion; the IFVG never inherits it;
- ends `DATA_GAP` / `CONTRACT_CHANGE` at resets;
- if the zone converted, terminated or became pending at or before
  `association_available_at`, the association row records
  `marker_never_active` with the reason. Step e runs after step b, so a
  conversion at `D` prevents activation.

Formation availability and association availability are separate columns.
No historical row is ever rewritten by a later swing confirmation.

### 3.11 Missing data, contract changes, price basis and future adjustment

#### 3.11.1 Missing or incomplete data (unchanged)

- At every 1m `DATA_GAP` onset, every active object of every timeframe
  terminates (step 0), and a `fvg_data_warnings` row is written. Mitigation
  is observed on 1m for all timeframes, so a 1m gap can hide events for any
  of them.
- Nothing is inferred inside the unobserved interval. Pre-gap ids never
  revive, and formation resumes only from post-gap segments (W11).
- Zone lifetime is bounded by the next 1m gap (33 1m episodes on
  DEVELOPMENT). This is the data rule, not an age limit.

#### 3.11.2 Rollover is not missing data

| Case | Detection (frozen adapter) | FVG effect |
|---|---|---|
| CB-1: gap, then a new contract | `DATA_GAP` at the gap onset; the change only in opening provenance | `TERMINATED` (`DATA_GAP`) |
| CB-2: pure change | `CONTRACT_CHANGE` at the first new-contract bar's close | Old-contract objects become `PENDING_ADJUSTMENT` at step 0; that bar never evaluates them (§3.6.2) |

#### 3.11.3 Price basis

- Every price-bearing value is stored raw, with `source_contract`.
  `basis_id` is `RAW:<contract>` today, and `ADJ:<process>:<version>` once
  the shared adjustment process exists.
- Formation, widths, midpoints and normalization are decided on the raw
  basis within one contract (a triple never spans a contract change).
  Adjusted values are propagated from them; formation is never re-decided
  on an adjusted series.
- **Comparable** = the objects, and the bars that test them, share one
  `basis_id`. Raw prices of different contracts are never compared, and no
  local adjustment is derived.

#### 3.11.4 Future shared adjustment: compatibility properties (A-1 outcome: method deferred)

FVG does not prescribe the adjustment method. It consumes an adjusted basis
only if the shared process declares, per `(contract, adjustment_version)`:

| # | Required property | Why |
|---|---|---|
| P1 | One transform per contract and version, applied identically to every bar and every POI value of that contract (bounds, midpoints, BPR and overlap intersections, Internal / External liquidity, …) | Consistent propagation; no object-specific adjustment |
| P2 | Strictly order-preserving within the contract | Strict penetration, strict closes, inclusive reach and equality keep their truth values |
| P3 | Exactly representable results, with a declared exact grid, or exact rationals | Strict / inclusive comparisons and exact midpoints are decided without rounding |
| P4 | Versioned and reproducible; prior versions retained | New runs, never rewrites; prior evidence preserved |
| P5 | Cross-contract continuity declared explicitly (which rolls the adjusted series bridges) | Decides whether a pure roll continues (adjusted) or suspends (raw) |

- Additive per-contract offsets satisfy P1–P3. A positive scaling satisfies
  P1–P2 but needs P3 to be declared, and it changes widths in points while
  normalized strength stays invariant (§3.3).
- **Unsupported transformations** (any of P1–P5 absent, e.g.
  non-monotone, time-varying within a contract, or results needing
  rounding) are flagged: comparisons on that basis become pending with
  reason `BASIS_UNSUPPORTED`. FVG never rounds transformed bounds silently.
- **Coexistence with the data rules.** Missing-data termination is
  basis-independent: a gap is unobserved on every basis. A pure roll
  suspends on the raw basis and continues on an adjusted basis only if P5
  declares it continuous. An adjusted run is a **new run** (`basis_id` and
  version in `run_id`); prior runs remain.
- No age limit and no same-contract-only eligibility rule exists. Basis
  comparability is the only cross-contract condition.

**Clarification (rev 2.1, 2026-10-07; no rule change).**

- **Order is not enough.** Strict order preservation (P2) alone does not
  preserve arithmetic midpoints or volatility-normalized width under an
  arbitrary nonlinear transformation: for a monotone `f`,
  `f((a + b) / 2) ≠ (f(a) + f(b)) / 2` and ratios of differences change in
  general. P2 guarantees only the truth values of comparisons.
- **Explicit declarations.** A future compatibility declaration must state,
  explicitly and separately, how it treats:
  - **midpoint geometry** (adjusted midpoint = midpoint of the adjusted
    bounds, or a transformed raw midpoint, and that the two agree);
  - **widths** (ticks and points) and the tick-count semantics of the
    formation threshold;
  - **normalized strength** (whether the baseline ATR and the width are
    transformed consistently so the ratio is preserved, or the raw ratio is
    carried as formation evidence);
  - **cross-contract intersection construction** (below).
- **Intersections.** Cross-contract intersections (FVG_OVERLAP, BPR,
  MTF_BPR) are computed from the compatible adjusted **parent bounds** on
  the shared basis (`max` of adjusted lowers, `min` of adjusted uppers). A
  raw intersection is never transformed as though it belonged to one
  parent contract.
- **Unsupported** declarations remain pending with `BASIS_UNSUPPORTED`; no
  value is rounded or approximated.
- **Current production scope** is raw-basis processing only, with explicit
  pending-comparison behavior at pure contract changes. The shared
  adjustment method remains deferred and is not selected or implemented
  locally; adjusted-basis support is an integration contract for the future
  shared process.

#### 3.11.5 Pending comparisons

`fvg_pending_comparisons(object_id, pending_object_id, reason ∈
{BASIS_MISMATCH, BASIS_UNSUPPORTED}, since_at)` is written when an object is
admitted or becomes pending while comparable-in-principle objects exist on
another basis. Views expose `pending_cross_contract_count`. No history is
discarded.

### 3.12 Output tables, M7A namespaces and strategy-facing views

All tables carry `instrument_id`, `contract_scope = SPECIFIC`, `contract`,
`basis_id`, `definition_version`, `run_id` and `fact_hash`. Times are UTC
tz-aware. Prices are exact decimals with integer tick (or half-tick) twins.

#### 3.12.1 Tables

| Table | Grain | Key columns |
|---|---|---|
| `fvg_zones` | one immutable row per zone | `zone_id`, `timeframe`, `original_direction`, `lower_ticks`, `upper_ticks`, `midpoint_half_ticks`, `lower`, `upper`, `midpoint`, `width_ticks`, `width_points`, `c1_ref`, `c2_ref`, `c3_ref`, `source_ref`, `source_at`, `source_end_at`, `span_start`, `available_at`, `segment_ref`, `baseline_atr_ticks`, `normalization_status`, `strength_num`, `strength_den`, `normalized_gap_strength` |
| `fvg_formation_rejections` | audit, one row per wick-gap triple failing the C2 rule | `timeframe`, `triple_ref`, `wick_gap_direction`, `reason`, `e_c3` |
| `fvg_zone_transitions` | M7A `fvg.zone` | M7A columns, plus `attr_current_direction`, `attr_close_ticks` |
| `fvg_mitigation_events` | per (zone, stage): milestones, depth records, `GAP_THROUGH` | `zone_id`, `stage`, `kind` (`PENETRATION` / `MIDPOINT` / `FULL` / `DEPTH` / `GAP_THROUGH`), `at`, `bar_ref`, `bar_ohlc`, `observation_class`, `penetration_depth_ticks`, `in_zone_depth_ticks` |
| `fvg_relationship_episodes` | one immutable row per episode | `relationship_id`, `label`, `zone_a`, `stage_a`, `zone_b`, `stage_b`, `cross_timeframe`, `movers`, `event_time`, `direction`, `governing_timeframe`, `i_lower`, `i_upper`, `i_midpoint_half_ticks`, `created_at` |
| `fvg_relationship_transitions` | M7A `fvg.overlap` (ACTIVE → ENDED) | reasons in §3.7.1 |
| `bpr_zones` | one immutable row per BPR object | `bpr_id`, `relationship_id`, `label`, `direction` (or `UNDEFINED`), `governing_timeframe`, bounds, midpoint, width, `available_at` |
| `bpr_transitions` | M7A `fvg.bpr` | §3.8.1 |
| `fvg_formation_groups` | one row per (subject, group, grade version) | `grade_version_id`, `group_index`, `representative_zone_id`, `member_zone_ids` |
| `fvg_grade_versions` | one row per component change | `grade_version_id`, `zone_id`, `available_at`, `timeframe_rank`, `overlap_contribution`, `normalization_status`, `normalized_gap_strength`, `original_width_ticks`, `actionable`, `supersedes` |
| `fvg_swing_associations` | one row per zone whose association became knowable | `association_id`, `zone_id`, `leg_origin_swing_id`, `last_terminator_swing_id`, `is_first`, `formation_available_at`, `association_available_at`, `marker_never_active`, `reason` |
| `fvg_first_marker_transitions` | M7A `fvg.first_marker` | `CONVERTED`, `DATA_GAP`, `CONTRACT_CHANGE` |
| `fvg_price_values` | per object and basis | `object_id`, `basis_id`, `adjustment_version`, `lower`, `upper`, `midpoint` |
| `fvg_pending_comparisons` | §3.11.5 | |
| `fvg_data_warnings` | one row per 1m gap onset in the replay range | `at`, `reason`, `reset_ref`, `terminated_count` |

#### 3.12.2 Strategy-facing causal views (bar-boundary rule `available_at ≤ t`)

- `active_fvg_zones(t)`: zones in stage FVG / IFVG. Columns:
  - current direction, bounds, exact midpoint, original width, strength
    and status;
  - stage and stage start;
  - the stage's mitigation summary as of `t` (first mitigation, max depth,
    midpoint / full reach, gap-through flag);
  - the first-FVG marker if active at `t`;
  - the latest grade components and the zone priority rank;
  - `pending_cross_contract_count`.

  No proximity or bias columns.
- `active_bprs(t)`: defined-direction BPRs with their BPR rank; `UNDEFINED`
  BPRs only in `descriptive_bprs(t)`.
- `active_overlaps(t)` (current episodes), `pending_comparisons(t)`.
- Retired, terminated and pending objects appear only in audit views.

#### 3.12.3 Empty and no-zone runs

- Every zone-dependent output (zones, rejections, transitions, mitigation,
  episodes, BPRs, groups, grades, associations, markers, price values,
  pending comparisons) is empty with its fixed schema when no zone forms.
- `fvg_data_warnings` may still contain rows: gaps occur without zones.
- The run manifest is always written, including:
  - `run_id`;
  - `replay_cutoff`;
  - `basis_id`;
  - definition versions;
  - the source fingerprint;
  - per-timeframe zone counts (possibly 0).

### 3.13 Identity, immutable versions and provenance

| Object | Id | Natural key (SHA-256) | Excludes |
|---|---|---|---|
| Zone | `fz_` | `definition_version`, `instrument_id`, `contract_scope`, `contract`, `timeframe`, `original_direction`, triple `source_ref` | prices, basis, times, stage, grade |
| Relationship episode | `fo_` | `definition_version`, `basis_id`, the two stage identities ordered by `zone_id` | label (derived), times |
| BPR | `fb_` | `relationship_id` | |
| Grade version | `fg_` | `zone_id`, canonical `available_at`, sorted group member ids, `actionable` | |
| Association | `fa_` | `zone_id`, `leg_origin_swing_id`, `leg_rule_version` | |
| Mitigation event | `fm_` | `zone_id`, `stage`, `kind`, canonical `at` | |
| M7A transitions | `st_` | frozen M7A key | |

- `run_id` = hash of the manifest:
  - definition versions;
  - the Swing reference definition;
  - `replay_cutoff`;
  - `basis_id` and adjustment version;
  - source fingerprint;
  - tick.
- `fact_hash` per row. Natural ids never contain `run_id`. Revisions create
  new runs.
- Every transition has exactly one trigger:
  - mitigation: the 1m `BAR_SPAN`;
  - conversion / retirement: the timeframe `BAR_SPAN`;
  - gap: `CONTINUITY_BREAK`;
  - CB-2: the first new-contract `BAR_SPAN`;
  - episode end: the triggering event's ref;
  - marker end: the conversion `BAR_SPAN`.

---

## 4. Consistency review

| Area | Check | Basis |
|---|---|---|
| Formation ↔ availability | Admission at step c of `e(C3)`. Steps a–b at `e(C3)` precede it, so formation bars and C3's close never test the zone | argument; W1, W2 executed |
| C2 rule ↔ geometry | Single direction per triple; `l(C2) < l(C3)`, `h(C2) > h(C1)` (bullish) | argument (§3.2) |
| C2 rule ↔ swings | C2 may be a confirmed swing extreme (W9a); not excluded | executed |
| Mitigation classes | `BEYOND` never mitigates; `FAR_CONTACT` / `SPANNING` set all milestones on one bar; milestones ordered; depth nondecreasing | argument; W4a/b/c/m executed |
| Mitigation ↔ conversion | Step a before b; IFVG tests start at the next bar | W2, W7 executed |
| Contract guard | No old-contract evaluation by the first new-contract bar; pending at that close | W12 executed (guarded vs unguarded) |
| Single exit | Gap instants have no bar; CB-2 excludes; conversion and retirement need distinct closes | argument (§3.6.3) |
| Episodes | Created only with a mover; deduplicated by stage identities; ≤ 3 per pair; final-state reassessment | W6, W7, W8 executed |
| Undefined direction | Reachable only through simultaneous admissions on truncated buckets | argument (§3.7.5); nesting minimums executed |
| BPR independence | Exact conditions (§3.8.2); opposite-current-direction parent never retires the BPR, any timeframe | W1 (same timeframe), W6 (lower timeframe) executed |
| Grouping | Objective (source spans); transitive; recomputed on partner changes | W5 executed |
| Normalization | Statuses; no imputation; invariant to additive and positive-scale transforms | W10 executed; invariance argued |
| Association | Exact deadline; no provisional marker; causal self-check on DEVELOPMENT | W9a–d executed; §5.14 |
| Missing data ↔ adjustment | Gap terminates on every basis; pure roll pending (raw) or continuous (adjusted, P5) | argument; W11, W12 executed |
| Empty outputs | Fixed schemas; warnings may exist; manifest always | specification |
| Contradictions | None found among the confirmed outcomes, the settled requirements and the frozen contracts | review |

---

## 5. Worked examples (executed)

Fixtures:
- 1m source bars built so that each 5m (or 1m) observation has exactly the
  shown O / H / L / C: the first minute carries it and the rest sit at the
  close (frozen-test fixture `ohlc_bars`).
- Prices = 20,000 + value. Times are ET on Sunday 2026-09-13, session
  opening 18:00.
- "Executed" means the scratch prototype printed the stated result using
  the frozen M3, continuity, §G.2a adapter and Swing detector.
- Zones with fewer than 15 prior observations show
  `normalization_status = INSUFFICIENT_HISTORY` (all short fixtures, except
  W10).

### 5.1 W1: bullish 5m zone; touch; penetration; midpoint; full; wick vs close; conversion; IFVG; same-timeframe BPR survival

| k | end | O | H | L | C | events |
|---|---|---|---|---|---|---|
| 0 | 18:05 | 100.00 | 101.00 | 99.00 | 100.75 | C1 |
| 1 | 18:10 | 100.75 | 104.00 | 100.50 | 103.75 | C2: bullish, `o = 100.75 ≤ 101.00`, `c = 103.75 ≥ 102.25` |
| 2 | 18:15 | 103.75 | 105.00 | 102.25 | 104.50 | C3 → zone **A [101.00, 102.25]**, width 5, midpoint **101.625**, available 18:15 |
| 3 | 18:20 | 104.50 | 104.75 | 102.25 | 103.00 | 1m low 102.25 = upper: `NEAR_CONTACT`, no mitigation |
| 4 | 18:25 | 103.00 | 103.25 | 102.00 | 102.50 | 18:21 first mitigation, depth 1 |
| 5 | 18:30 | 102.50 | 102.75 | 101.50 | 102.00 | 18:26 midpoint reached |
| 6 | 18:35 | 102.00 | 102.25 | 100.75 | 101.25 | 18:31 `SPANNING`, full reached (depth 6, in-zone 5); close inside: no conversion |
| 7 | 18:40 | 101.25 | 101.50 | 101.00 | 101.00 | 18:37–18:40 sit at exactly 101.00: `FAR_CONTACT` zone trades (no new milestone); close = lower: no conversion |
| 8 | 18:45 | 101.00 | 101.25 | 100.25 | 100.50 | close < lower: **converted** to bearish IFVG at 18:45 |
| 9 | 18:50 | 100.50 | 101.00 | 100.25 | 100.75 | 18:46 high = 101.00 = IFVG near boundary: `NEAR_CONTACT`, no IFVG mitigation |
| 10 | 18:55 | 100.75 | 101.75 | 100.50 | 101.50 | 18:51 IFVG mitigation and midpoint (depth 3) |
| 11 | 19:00 | 101.50 | 102.50 | 101.25 | 102.25 | 18:56 IFVG full; close = upper: no retirement. **Zone N [101.00, 101.25]** (C1 k9, C2 k10 bullish spanning, C3 k11) available 19:00 → **BPR** episode (A IFVG bearish, N FVG bullish), direction **bullish** (mover N), governing 5m, [101.00, 101.25] |
| 12 | 19:05 | 102.25 | 103.00 | 102.00 | 102.75 | close 102.75 > 102.25: **A (bearish IFVG) retires**; its episode ends. The bullish BPR needs a 5m close < 101.00: **survives** (§3.8.2, `dP ≠ d`). Zone [101.75, 102.00] also forms |

Rejected triples:
- k5–k7 is a bearish-side equality: `h(k7) = 101.50 = l(k5)`.
- k7–k9 is a bearish-side equality: `h(k9) = 101.00 = l(k7)`.

### 5.2 W2: conversion-bar ordering on a 1m zone

| k | end | O | H | L | C | events |
|---|---|---|---|---|---|---|
| 0–2 | 18:01–18:03 | rows of W1 k0–k2 | | | | 1m zone [101.00, 102.25], available 18:03 |
| 3 | 18:04 | 104.50 | 104.75 | 100.50 | 100.75 | (a) FVG-stage `SPANNING`: mitigation, midpoint, full (depth 7, in-zone 5); (b) conversion at 18:04 |
| 4 | 18:05 | 100.75 | 101.50 | 100.50 | 101.25 | first IFVG test: mitigation 18:05 (depth 2) |

### 5.3 W3: formation boundary cases (each a separate three-bar run; C3 at 18:15)

| Case | C1 | C2 | C3 | Result |
|---|---|---|---|---|
| Bearish one-tick | 105 / 106 / 104 / 104.25 | 104.25 / 104.50 / 101 / 101.25 (bearish, `o ≥ 104`, `c ≤ 103.75`) | 101.25 / 103.75 / 100.50 / 101 | zone [103.75, 104.00], width 1, midpoint 103.875 |
| Bullish equality | 100 / 101.00 / 99 / 100.75 | 100.75 / 104 / 100.50 / 103.75 | 103.75 / 105 / **101.00** / 104.50 | rejected `EQUALITY` (`l(C3) = h(C1)`) |
| Bearish equality | 105 / 106 / **104** / 104.25 | 104.25 / 104.50 / 101 / 101.25 | 101.25 / **104.00** / 100.50 / 101 | rejected `EQUALITY` (`h(C3) = l(C1)`) |
| C2 bearish | 100 / 101 / 99 / 100.25 | 103.75 / 104 / 100.50 / 100.75 | 104 / 105 / 102.25 / 104.50 | rejected `C2_NOT_DIRECTIONAL` |
| C2 body short of C3 low | 100 / 101 / 99 / 100.75 | 100.75 / 104 / 100.50 / **102.00** | 102.50 / 105 / 102.25 / 104.50 | rejected `C2_BODY_NOT_SPANNING` |
| C2 opens above C1 high | 100 / 101 / 99 / 100.75 | **101.25** / 104 / 100.50 / 103.75 | 103.75 / 105 / 102.25 / 104.50 | rejected `C2_BODY_NOT_SPANNING` |
| Doji C2 | 100 / 101 / 99 / 100.75 | 102 / 104 / 100.50 / 102 | 102.50 / 105 / 102.25 / 104.50 | rejected `C2_NOT_DIRECTIONAL` |
| Mixed colours | **101 / 101 / 99 / 99.50 (bearish)** | 99.50 / 104 / 99.25 / 103.75 | **104.50 / 105 / 102.25 / 103 (bearish)** | zone [101.00, 102.25] |
| Body on gap boundaries | 100 / 101 / 99 / 100.75 | **101.00** / 104 / 100.50 / **102.25** | 102.25 / 105 / 102.25 / 104.50 | zone [101.00, 102.25] (inclusive body bounds) |

(Columns are O / H / L / C.)

### 5.4 W4: mitigation classes (5m zone [101.00, 102.25] from W1 k0–k2, then k3 = 104.50 / 104.75 / 103.00 / 103.00)

| Case | k4 (first minute 18:21; rest at close) | Result |
|---|---|---|
| a. Wholly beyond | 100.00 / 100.75 / 99.50 / 100.25 | 18:21 `BEYOND` → `GAP_THROUGH` (no milestone). The 5m close 100.25 < 101.00 → **converted** at 18:25 (close rule independent) |
| b. Far contact from beyond | 100.50 / **101.00** / 100.00 / 101.00 | 18:21 `FAR_CONTACT`: mitigation, midpoint and full at once (depth 9, in-zone 5); close = lower: no conversion |
| c. Spanning | 103.00 / 103.25 / 100.75 / 101.50 | 18:21 `SPANNING`: all three milestones (depth 6, in-zone 5) |
| m. Mirrored (bearish zone [103.75, 104.00] from W3; k3 = 101 / 102 / 100.75 / 101.25) | 104.50 / 105.00 / 104.25 / 104.75 | 18:21 `BEYOND` above → `GAP_THROUGH`; 5m close 104.75 > 104.00 → converted at 18:25 |

### 5.5 W5: formation groups (5m and 15m)

| k | end | O | H | L | C |
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

- 5m zones:
  - [101.00, 102.50] (span 18:10–18:25);
  - [103.00, 104.50] (18:15–18:30);
  - [105.00, 106.00] (18:20–18:35).
- 15m zone [101.00, 106.00] (18:00–18:45, width 20), available 18:45.
- Three `FVG_OVERLAP` episodes at 18:45. The 15m zone's partners' spans
  overlap pairwise, so they form **one group: contribution 1** (not 3, and
  not 0). Each 5m zone has one partner group (the 15m zone):
  contribution 1.

### 5.6 W6: MTF_BPR with a lower-timeframe parent's inversion and retirement

5m rows k0–k2 as W1, then:

| k | end | O / H / L / C |
|---|---|---|
| 3 | 18:20 | 104.50 / 105.50 / 104.00 / 105.00 |
| 4 | 18:25 | 105.00 / 106.00 / 104.50 / 105.50 |
| 5 | 18:30 | 105.50 / 106.50 / 105.00 / 106.00 |
| 6 | 18:35 | 106.00 / 106.50 / 103.25 / 104.00 |
| 7 | 18:40 | 104.00 / 104.50 / 103.00 / 103.50 |
| 8 | 18:45 | 103.50 / 104.00 / 103.25 / 103.75 |
| 9 | 18:50 | 103.75 / 103.75 / 102.00 / 102.25 |
| 10 | 18:55 | 102.25 / 102.50 / 101.50 / 101.75 |
| 11 | 19:00 | 101.75 / 102.00 / 101.25 / 101.50 |
| 12 | 19:05 | 101.50 / 101.75 / 101.25 / 101.50 |
| 13 | 19:10 | 101.50 / 101.75 / 101.25 / 101.25 |
| 14 | 19:15 | 101.25 / 101.50 / 101.00 / 101.25 |
| 15 | 19:20 | 101.25 / 101.25 / 100.50 / 100.75 |
| 16 | 19:25 | 100.75 / 102.75 / 100.75 / 102.50 |
| 17 | 19:30 | 102.50 / 102.50 / 101.75 / 102.00 |
| 18 | 19:35 | 102.00 / 102.25 / 101.75 / 102.25 |
| 19 | 19:40 | 102.25 / 102.50 / 102.00 / 102.25 |
| 20 | 19:45 | 102.25 / 103.00 / 102.25 / 102.75 |

Executed:

- A = 5m bullish [101.00, 102.25].
- C = 15m bearish [101.75, 103.00]:
  - C1 = the 18:30–18:45 bucket (low 103.00);
  - C2 = 18:45–19:00 (bearish: open 103.75 ≥ 103.00, close 101.50 ≤
    101.75);
  - C3 = 19:00–19:15 (high 101.75);
  - available 19:15.
- 19:15: `MTF_BPR` episode (mover C) → BPR [101.75, 102.25], direction
  **bearish**, governing **15m**.
- 19:20: A converts (5m close 100.75). The pair becomes same-direction:
  the BPR episode ends and an `FVG_OVERLAP` episode (A IFVG / C FVG)
  starts. The BPR object is unaffected.
- 19:25: A (bearish IFVG) retires on 5m close 102.50 > 102.25.
  - `dP = d`, but P's timeframe (5m) close is not a 15m close (§3.8.2
    condition 1).
  - The 15m bar 19:15–19:30 then closes 102.00 ≤ 102.25, so the **BPR
    survives**.
- 19:45: the BPR retires on the 15m close 102.75 > 102.25. C never
  converts (102.75 ≤ 103.00).

### 5.7 W7: conversion-created BPR (W5 rows k0–k8, then:)

| k | end | O / H / L / C |
|---|---|---|
| 9 | 18:50 | 108.50 / 108.50 / 104.00 / 104.25 |
| 10 | 18:55 | 104.25 / 104.50 / 102.75 / 103.00 |
| 11 | 19:00 | 103.00 / 103.50 / 100.75 / 101.00 |
| 12 | 19:05 | 101.00 / 101.25 / 100.25 / 100.75 |

Executed:

- **18:50:** the 5m zone [105.00, 106.00] converts (close 104.25 <
  105.00) and its `FVG_OVERLAP` with the 15m [101.00, 106.00] ends.
  - A new **MTF_BPR** episode is created: mover = the converting 5m zone;
    direction **bearish** (its new direction); event time 18:50; governing
    **5m**; [105.00, 106.00].
  - It is tested only by 5m bars starting at or after 18:50.
- **19:00:** the 5m zone [103.00, 104.50] converts → MTF_BPR
  [103.00, 104.50] (bearish, 5m, 19:00). The 15m zone's close 101.00 =
  its lower: no conversion.
- **19:05:** the 5m zone [101.00, 102.50] converts → MTF_BPR
  [101.00, 102.50] (bearish, 5m, 19:05).
- Newly admitted bearish 5m zones produce their own admission-created
  episodes at 18:55, 19:00 and 19:05; each mover is the admitted zone.

### 5.8 W8: simultaneous conversion of both parents (W7 rows k0–k10, then k11 = 103.00 / 103.50 / 100.25 / 100.50)

- At 19:00:
  - the 5m [101.00, 102.50], the 5m [103.00, 104.50] and the 15m
    [101.00, 106.00] all convert on the same close 100.50;
  - every affected pair is reassessed once from the final state:
    (IFVG / IFVG), same direction → `FVG_OVERLAP` successor episodes.
- **No transient BPR is created** for the pairs whose parents both
  converted.
- The two BPRs created earlier (18:50, 18:55) keep their own lifecycle.

### 5.9 W9: first FVG in a swing leg (5m; frozen 2/2 swings)

| Case | Rows (O / H / L / C by k) | Executed result |
|---|---|---|
| **a** C2 = swing-low candle | 110/111/108/109; 109/109.50/105/105.50; 105.50/112.50/100/112; 112/115/110/114.50; 114.50/116/113/115.50; 115.50/119/115.25/118.50; 118.50/121/117/120.50 | Swing LOWER 100 (k2, available 18:25). First = [109.50, 110.00] (C2 = k2), formed 18:20, **associated 18:25** (C2 is a left-qualified candidate run → `D = e(C4)`). Later zones are not first and associate at formation |
| **b** higher low | 104/105/103/104; 104/104.50/102/102.50; 102.50/103/100/102.75; 102.75/104/101/103.75; 103.75/108/103.50/107.75; 107.75/110/105/109.50; 109.50/111/104.50/105; 105/112/104/111.50; 111.50/113/104.25/112.75; 112.75/114/104.50/113.50; 113.50/117/113.25/116.50; 116.50/118/115/117.50 | Swings LOWER 100 (k2) and LOWER 104 (k7); no UPPER. Origin stays 100 for every zone: first = [103.00, 103.50]; [113.00, 113.25] is **not** first (the higher low does not restart) |
| **c** new lower low | b with k6 = 109.50/111/101/102, k7 = 102/112/99/111, k8 = 111/113/99.50/112.50, k9 = 112.50/114/100/113.50 | Swings LOWER 100 (k2) and LOWER **99** (k7). Zones anchored at or after k7 have origin 99, a **new leg**: [113.00, 113.25] **is** first of it |
| **d** plateau C1 / C2 and cutoff | 106/107/105/105.50; 105.50/106/104/104.50; 104.50/105/100/100.50; 100.50/108/100/107.75; 107.75/109/105.50/108.50; 108.50/110/106/109.50; 109.50/111/107/110.50 | Zone [105.00, 105.50] formed 18:25; swing LOWER 100 with plateau k2–k3 (C1 = C2 low), available 18:30. Association 18:30. **Cutoff 18:25: zone present, no association row; cutoff 18:30: association present** (prefix-equivalent) |

### 5.10 W10: normalized gap strength (W1 k0–k2 pattern after a history)

| History before C1 | Result |
|---|---|
| 15 bars 100 / 100.50 / 99.50 / 100 (TR = 4 ticks each) | `OK`: baseline 4 ticks; strength = 5 / 4 = **1.25** |
| 15 flat bars 100 / 100 / 100 / 100 | `ZERO_BASELINE`, strength null; zone kept |
| 14 bars 100 / 100.50 / 99.50 / 100 | `INSUFFICIENT_HISTORY` (the 15th close is missing), strength null; zone kept |

### 5.11 W11: missing data (W1 rows with the 18:25–18:30 5m bar absent)

- Frozen adapter: `DATA_GAP` reset at **18:26** (the first missing
  minute's expected completion).
- Zone A records mitigation at 18:21 (depth 1), then **terminates at
  18:26** (step 0) with a warning.
- The later close below 101.00 (18:45) is never applied to A.
- Post-gap zones [101.00, 101.25] (19:00) and [101.75, 102.00] (19:05)
  form in segment 1 with new ids.

### 5.12 W12: pure contract change with the guard (W1 rows; k0–k5 `MNQ 09-26`, k6 onward `MNQ 12-26`)

- Frozen adapter: `CONTRACT_CHANGE` at **18:31**, the first new-contract
  bar's close.
- Guarded: A records mitigation 18:21 and midpoint 18:26, then becomes
  `PENDING_ADJUSTMENT` at 18:31 (step 0). The 18:31 bar (low 100.75,
  inside / beyond A) is **not** evaluated.
- Unguarded (the rev 1 defect): the same bar would record full reach and
  `SPANNING` at 18:31.
- New-contract zones [101.00, 101.25] and [101.75, 102.00] form normally.
  Their comparison with A is listed as pending (`BASIS_MISMATCH`), never
  computed on raw prices.
- The 15m build succeeds because the switch is on a 15m boundary.

### 5.13 W13: simultaneous events

- No fixture is constructible on the current schedule (§3.7.5).
- Executed parts:
  - W8 (simultaneous conversions, same direction afterwards);
  - the nesting minimums (§5.14).

### 5.14 DEVELOPMENT design evidence (scratch prototype; not validation)

DEVELOPMENT partition: 337,815 1m bars, 2024-06-21 … 2025-06-30.

**Formation under the rev 2 rule** (current):

| tf | wick-gap triples | FVG (bull / bear) | C2 rejected: not directional · body not spanning | equality-only triples | one-tick | half-tick midpoints | median width | normalization OK · INSUFFICIENT_HISTORY · ZERO_BASELINE | strength p10 / p50 / p90 |
|---|---|---|---|---|---|---|---|---|---|
| 1m | 66,328 | 59,661 (30,908 / 28,753) | 272 · 6,395 | 7,302 | 5,749 | 52.7 % | 8 t | 59,571 · 90 · 0 | 0.064 / 0.292 / 0.900 |
| 5m | 12,862 | 12,268 (6,549 / 5,719) | 46 · 548 | 601 | 545 | 51.3 % | 18 t | 12,188 · 80 · 0 | 0.051 / 0.275 / 0.897 |
| 15m | 4,404 | 4,223 (2,319 / 1,904) | 26 · 155 | 106 | 97 | 52.1 % | 33 t | 4,133 · 90 · 0 | 0.044 / 0.270 / 1.041 |
| 1H | 1,153 | 1,090 (603 / 487) | 10 · 53 | 12 | 10 | 48.1 % | 64 t | 1,005 · 85 · 0 | 0.033 / 0.238 / 1.196 |
| 4H | 319 | 285 (166 / 119) | 5 · 29 | 1 | 3 | 51.2 % | 170 t | 206 · 79 · 0 | 0.034 / 0.326 / 1.329 |
| 1D | 40 | 31 (17 / 14) | 1 · 8 | 0 | 0 | 29.0 % | 482 t | 6 · 25 · 0 | 0.250 / 0.626 / 0.729 |

- The C2 rule removes 4–23 % of wick gaps, depending on timeframe. Most
  rejections are `C2_BODY_NOT_SPANNING`.
- `INSUFFICIENT_HISTORY` concentrates at segment starts. It weighs most on
  4H and 1D, where segments are short relative to 15 observations.
- No `ZERO_BASELINE` occurs on DEVELOPMENT.

**Superseded (rev 1, no C2 rule; shown only for comparison):** 1m
66,328, 5m 12,862, 15m 4,404, 1H 1,153, 4H 319, 1D 40 zones. These equal
the "wick-gap triples" column above.

**Nesting minimums** (expected LTF buckets per HTF bucket, DEVELOPMENT
schedule):
- 1m / 5m: 5;
- 5m / 15m: 3;
- 15m / 1H: 4;
- 1H / 4H: 3;
- 4H / 1D: 6;
- all other pairs larger.

**First-FVG association** (exact segments, exact deadline, confirmed rule):

| tf | zones | in a leg | no leg | first markers | associated at formation | associated later | zones whose C2 is a pending candidate (deadline `e(C2+2)`) | causal self-check differences |
|---|---|---|---|---|---|---|---|---|
| 5m | 12,268 | 10,953 | 1,315 | 6,837 | 6,211 | 626 | 710 | 0 of 10,953 |
| 15m | 4,223 | 3,767 | 456 | 2,298 | 2,052 | 246 | 282 | 0 of 3,767 |
| 1H | 1,090 | 941 | 149 | 568 | 497 | 71 | 77 | 0 of 941 |
| 4H | 285 | 235 | 50 | 139 | 118 | 21 | 24 | 0 of 235 |
| 1D | 31 | 18 | 13 | 11 | 9 | 2 | 2 | 0 of 18 |

- **Causal self-check.** For every knowable association, the leg origin was
  recomputed using only the swings with `available_at ≤
  association_available_at`. It matched in every case: 0 differences.
- **No unknowable associations.** No zone's deadline fell beyond its
  segment end on DEVELOPMENT.
- **Not computed:** 1m (runtime). Same rule; covered by planned tests.

The rev 1 approximate figures (4-day proximity proxy, four rule
combinations) are superseded and removed.

---

## 6. Invariants (each must have 0 violations)

| Id | Invariant |
|---|---|
| FVG-INV-1 | C1–C3 are consecutive complete expected observations of one segment and one contract |
| FVG-INV-2 | Bounds equal the defining wicks; `width ≥ 1`; `midpoint_half_ticks = lower + upper`; nothing rounded |
| FVG-INV-3 | `available_at = e(C3)`; no event references a zone earlier; no formation bar tests its zone |
| FVG-INV-4 | Zone facts (incl. normalization) immutable; ids per §3.13; no duplicates |
| FVG-INV-5 | Independent recomputation: every zone satisfies the wick gap and the C2 body rule; every rejected wick gap fails exactly its recorded reason; equality never forms |
| FVG-INV-6 | Milestones only from `ZONE_TRADE` bars with `bar_start ≥ stage_start` and an eligible basis; `NEAR_CONTACT` / `BEYOND` never set milestones |
| FVG-INV-7 | Per stage: mitigation ≤ midpoint ≤ full in time; depth records nondecreasing; `GAP_THROUGH` only before the stage's first `ZONE_TRADE` |
| FVG-INV-8 | Mitigation never changes bounds, widths, normalization, stage or grade inputs |
| FVG-INV-9 | Conversions / retirements only on own-timeframe complete closes strictly beyond the far bound, `bar_start ≥ stage_start` |
| FVG-INV-10 | Stage sequence is a prefix of FVG → IFVG → RETIRED plus at most one TERMINATED / PENDING_ADJUSTMENT; never IFVG → FVG |
| FVG-INV-11 | No IFVG mitigation from bars with `bar_start <` the conversion close |
| FVG-INV-12 | No object is evaluated against a bar of another basis; CB-2 objects become pending at the first new-contract close and have no event from that bar |
| FVG-INV-13 | Every episode has positive intersection = max / min of the parents' bounds; contact never forms one |
| FVG-INV-14 | Episode labels match the parents' current directions and timeframes at creation; every episode has ≥ 1 mover |
| FVG-INV-15 | Directional event: one mover → its direction / timeframe / time; two movers → `UNDEFINED`, no governing timeframe |
| FVG-INV-16 | At most one episode per (stage identity, stage identity, basis); ≤ 3 per pair; final-state reassessment (no transient episodes) |
| FVG-INV-17 | BPR exits only by its own predicate or a reset; never relabelled; bounds / direction immutable |
| FVG-INV-18 | Grade components recomputed independently (groups, strength, width) equal the recorded ones; priority order follows §3.9.1; BPR order follows §3.9.3 and never mixes zones |
| FVG-INV-19 | Group contribution counts components of the span-overlap graph among current same-direction partners; a zone never counts twice |
| FVG-INV-20 | At every 1m gap onset all active objects terminate; no event inside the unobserved interval; no pre-gap id after it |
| FVG-INV-21 | Prefix equivalence for every tested cutoff (incl. inside gaps and before association deadlines) |
| FVG-INV-22 | Each leg has at most one first marker; origin and terminator selection reproduce §3.10 using only swings available at `association_available_at` |
| FVG-INV-23 | A marker is active only in the FVG stage at or after `association_available_at`; never on an IFVG |
| FVG-INV-24 | No later FVG gets a marker because an earlier one failed |
| FVG-INV-25 | No-zone runs: zone-dependent tables empty with fixed schemas; manifest present |
| FVG-INV-26 | M7A validity of every namespace |
| FVG-INV-27 | At most one exit transition per entity and instant |

---

## 7. Planned tests, prefix replays and visual-validation cases (none implemented)

**Formation (T-F).**
- T-F1: six timeframes, independently.
- T-F2: bullish wick gap.
- T-F3: bearish wick gap.
- T-F4: equality in both directions.
- T-F5: C2 not directional (incl. doji).
- T-F6: C2 body not spanning (open side, close side, both directions).
- T-F7: body exactly on the gap bounds.
- T-F8: mixed C1 / C3 colours.
- T-F9: availability at C3 close; no earlier visibility.
- T-F10: half-tick midpoint exact.
- T-F11: ids stable across cutoffs.
- T-F12: session-boundary / weekend triple valid; gap / incomplete triple
  invalid.

**Mitigation (T-M).**
- T-M1: near contact vs zone trade (both directions).
- T-M2: midpoint inclusive; even vs odd width.
- T-M3: full inclusive.
- T-M4: `FAR_CONTACT`.
- T-M5: `SPANNING`.
- T-M6: `BEYOND` / `GAP_THROUGH`, mirrored.
- T-M7: depth records and the in-zone cap.
- T-M8: stage separation.
- T-M9: mitigation leaves grades unchanged.

**Lifecycle (T-L).**
- T-L1: strict close conversion.
- T-L2: no classification by formation bars or the C3 close.
- T-L3: equality at the far bound.
- T-L4: wick beyond does not convert.
- T-L5: IFVG retirement; no re-inversion.
- T-L6: conversion-bar ordering (1m).
- T-L7: conversion-bar ordering (5m).

**Relationships (T-O).**
- T-O1: same-timeframe FVG_OVERLAP.
- T-O2: cross-timeframe FVG_OVERLAP.
- T-O3: BPR.
- T-O4: MTF_BPR.
- T-O5: mover by `available_at`.
- T-O6: conversion-created BPR (direction / time / timeframe /
  eligibility).
- T-O7: opposite → same after conversion.
- T-O8: both parents convert in one batch (no transient).
- T-O9: an earlier IFVG parent.
- T-O10: a retired parent creates nothing.
- T-O11: ≤ 3 episodes per pair; dedup.
- T-O12: truncated-bucket fixture for `UNDEFINED` (calendar override).

**BPR (T-B).**
- T-B1: retirement on governing closes only.
- T-B2: survives parent inversion.
- T-B3: same-timeframe opposite-direction parent retirement (W1).
- T-B4: lower-timeframe parent retirement (W6).
- T-B5: same-direction same-timeframe parent exit that also retires the
  BPR (both predicates at one close).

**Grading (T-G).**
- T-G1: lexicographic order.
- T-G2: formation groups (nested, partial, transitive, end-to-start
  contact not linked).
- T-G3: strength `OK`.
- T-G4: `INSUFFICIENT_HISTORY` (14 bars; gap before C1).
- T-G5: `ZERO_BASELINE`.
- T-G6: null-strength ranking policy.
- T-G7: prospective group updates on partner conversion / retirement /
  termination.
- T-G8: BPR ranking separate.

**Data and contracts (T-D).**
- T-D1: gap terminates every timeframe.
- T-D2: nothing inferred inside a gap.
- T-D3: post-gap re-establishment only.
- T-D4: trailing missing data.
- T-D5: CB-2 guard and pending (W12).
- T-D6: CB-1 → `DATA_GAP` only.
- T-D7: single exit per instant.
- T-D8: `BASIS_UNSUPPORTED` flagging with a mock adjusted basis.

**Swing association (T-S).**
- T-S1: C2 anchor (W9a).
- T-S2: higher low (W9b).
- T-S3: new lower low (W9c).
- T-S4: plateau deadline (W9d).
- T-S5: cutoff before the deadline.
- T-S6: conversion at `D` → `marker_never_active`.
- T-S7: marker ends at conversion.
- T-S8: IFVG never marked.
- T-S9: no promotion.

**Empty (T-E).**
- T-E1: no-zone run (schemas, warnings, manifest).

**Independent reference.** A per-bar replay with:
- naive formation (wick gap + C2);
- naive mitigation classes;
- per-bar lifecycle;
- naive pairwise episodes;
- naive groups;
- naive association.

It is reconciled against production (the Internal Liquidity pattern).

**Prefix replays** (DEVELOPMENT and synthetic). Cutoffs:
- at and one minute before an admission;
- at a `ZONE_TRADE`;
- at a `GAP_THROUGH`;
- at a conversion close;
- at a **conversion-created** BPR and one minute after;
- at an episode change caused by both parents converting;
- at a BPR retirement;
- inside a gap;
- at a CB-2 roll (synthetic);
- before and at an association deadline.

**Visual cases** (local HTML with prices; price-free manifest):
- W1–W12.
- From DEVELOPMENT, at least one per timeframe and one per class:
  - every mitigation class;
  - conversion;
  - IFVG retest;
  - retirement;
  - FVG_OVERLAP with a formation group;
  - BPR;
  - MTF_BPR;
  - conversion-created BPR;
  - first marker (immediate and delayed);
  - gap termination;
  - normalization statuses.
- Source spans, C2 bodies and `available_at` / association markers are
  drawn.
- Tables separate the pre-state at `s(m)`, the evidence, the post-state at
  `e(m)` and later lifecycle.

---

## 8. Integration and implementation milestones (not authorized)

| Step | Content |
|---|---|
| FVG-I0 | **DONE (2026-10-07):** implementation of rev 2 authorized; D-148 – D-152 registered; §3.11.4 clarified (rev 2.1) |
| FVG-I1 | Formation (wick gap + C2), rejection audit, normalization, zone facts, price basis, ids, empty schemas; tests |
| FVG-I2 | 1m mitigation classes, own-timeframe lifecycle, step-0 resets and basis guard, single-exit check, M7A logs; tests |
| FVG-I3 | Relationship episodes (admission- and conversion-created), BPR objects and lifecycle, formation groups, grade versions, rankings, views; tests |
| FVG-I4 | Swing-leg association with the exact deadline and markers; tests |
| FVG-I5 | Independent reference, invariants, DEVELOPMENT validation, prefix replays (incl. conversion-created relationships), visual package |

New module family `src/fvg/` (ICT family; not an extension of ORB or the
liquidity modules). Frozen M3, continuity, the §G.2a adapter, the Swing
detector and the M7A validators are reused read-only.

---

## 9. Decision outcomes and routine representation choices

### 9.1 Decision outcomes

All are closed (§1.3). No open user-facing semantic decision remains.

### 9.2 Routine representation choices (resolved here; no approval round needed)

| Choice | Resolution |
|---|---|
| ATR baseline window | 15 consecutive observations before C1 in the segment (14 TRs, each with its previous close); otherwise `INSUFFICIENT_HISTORY` |
| Strength storage | Exact rational (`strength_num`, `strength_den`) plus decimal |
| Null strength in ranking | Below `OK` values at equal keys 1–2; nulls tie on key 3; then raw width |
| Final tiebreaks | `available_at` ascending, `zone_id` ascending (BPR: `available_at`, `bpr_id`) |
| Mitigation class names | `ZONE_TRADE`, `SPANNING`, `FAR_CONTACT`, `NEAR_CONTACT`, `BEYOND`; event `GAP_THROUGH` |
| Depth | Uncapped penetration depth plus capped in-zone depth; records on growth only |
| Episode identity | Ordered stage-identity pair plus basis; ≤ 3 per pair |
| Group representative | Highest timeframe, then width, then earliest `available_at`, then `zone_id` |
| Span overlap for grouping | Half-open source spans; positive-duration intersection; transitive |
| Rejection audit | `fvg_formation_rejections` with the reason codes of §3.2 |
| Pending reasons | `BASIS_MISMATCH`, `BASIS_UNSUPPORTED` |
| Exit precedence (defensive) | `DATA_GAP` > `CONTRACT_CHANGE` > classification; any coincidence fails validation |
| Undefined-direction BPR | `direction = UNDEFINED`, no governing timeframe, descriptive view only |

---

## 10. Evidence classes

| Class | Content |
|---|---|
| Source-supported | C1/C3 wick-gap geometry; mixed candle directions (§1.1) |
| Approved operational rules | C2 directional body; ≥ 1 tick; strict penetration / closes; inclusive reach; strength; priority; groups; episodes; leg rule; data / basis rules (§1.2, §1.3) |
| Arguments (not tests) | Single direction per triple; C2 lemmas; mitigation coherence; single exit per instant; episode reachability (§3.7.5); BPR independence conditions (§3.8.2); deadline exactness (§3.10); normalization invariance (§3.3) |
| Executed scratch checks (2026-10-07; prototype not committed) | W1–W12 (§5); DEVELOPMENT formation, normalization, nesting and association evidence with a causal self-check (§5.14) |
| Not executed | No FVG code, tests or validation exist. The repository suite was not re-run (documentation-only change) |
| Planned | §6 invariants; §7 tests, independent reference, prefix replays, visual cases |
