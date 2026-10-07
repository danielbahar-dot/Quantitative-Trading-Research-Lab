# Internal Liquidity (ROADMAP 3.3): Consolidated Design (rev 4)

**Status: APPROVED / FROZEN (2026-10-07).** Human visual approval passed on the corrected package at
checkpoint `9dd62ca`; merged to `main` via PR #16. Frozen DEVELOPMENT baseline: DECISION_LOG D-143
freeze note. Future semantic changes require a new decision.

- IL-I1 – IL-I4 implemented (`683da5a`, `e6cfbec`, `617e983`, `52291d1`, review fixes `9dd62ca`).
  All 11 DEVELOPMENT machine gates PASS (`reports/validation/internal_liquidity_dev_summary.csv`).

- The design authority approved rev 4 as the implementation specification on
  2026-10-06. That covers IL-D0 – IL-D14, OI-1 – OI-6 and A-19 (pinned
  boundary assignments).
- The approved decisions are registered as **D-143 – D-147**:

  | Decision | Covers |
  |---|---|
  | D-143 | The shared consumption contract |
  | D-144 | Internal formation atoms |
  | D-145 | Levels, price records and grading |
  | D-146 | External ranges and pinned boundary assignments |
  | D-147 | Lifecycle, gaps, causality and outputs |

- Implementation steps IL-I1 – IL-I4 are authorized. Freeze and merge are
  not.

- Rev 4 incorporates every design-authority outcome: IL-D0 … IL-D14,
  OI-1 … OI-6, and the boundary-assignment correction A-19 (§1.2).
- Rev 4 separates **pinned boundary assignments** from **current External
  cluster objects** (§3.6.2, §4.5).
- It records the routine representation choices that realize them (§3) and a
  final consistency check (§4).
- **No genuine semantic conflict remains** (§5).
- Frozen modules (External, Swing, Market Structure, continuity, M3, M7) are
  never changed. Implementation adds separate modules.

- **Branch:** `internal-liquidity-design`, from local `main` `25f95d9`
  (PR #14 merge `434d919` plus the Market Structure freeze record).
- **Builds on (frozen, read-only):**
  - External Liquidity 3.1 (D-134; `EXTERNAL_LIQUIDITY_SPEC.md`;
    `src/liquidity/contract.py`, `src/features/external_liquidity.py`);
  - Swing Structure 3.2 (D-135 – D-138);
  - Generic Market Structure 3.MS (D-139 – D-142);
  - continuity / M3 (D-137) and M7A (D-129 – D-131).
- **Out of scope:** FVG / imbalance, MSS, entry signals, profitability or
  performance testing, optimization, VALIDATION / OOS data, stitching or roll
  calendars (D1), and the broader 3.4 lifecycle beyond the narrow consumption
  contract (§3.1).

| Marker | Meaning |
|---|---|
| **R-n** | Approved requirement (original brief) |
| **A-n** | Approved decision outcome (design authority, 2026-10-06) |
| **RC** | Representation choice made within the approved outcomes |

---

## 1. Approved inputs

### 1.1 Requirements (R)

| Id | Requirement |
|---|---|
| R-1 | Internal liquidity exists only within an **explicitly identified external-liquidity range**. |
| R-2 | Outputs provide **definitive, tick-aligned price levels** that future strategy definitions can reference. |
| R-3 | **EQ** = equal highs / lows. **REQ** = relatively equal highs / lows. |
| R-4 | Candidate families include 1H highs / lows, confirmed swings across timeframes, and REQ / EQ across timeframes. |
| R-5 | Within one timeframe, **ordinary H/L < REQ < EQ**. Ordinary swing priority **increases with timeframe**. |
| R-6 | Multiple levels are preserved with explainable grades. Grades are rule-based evidence, **not** trading probabilities. |
| R-7 | Formation, grading and lifecycle are separate. A touch or penetration never redefines the original level. |
| R-8 | A consumed level is no longer eligible. Its identity, evidence and consumption timestamp are retained. |
| R-9 | FVG / imbalance, MSS, entry signals and profitability testing are out of scope. |

### 1.2 Approved decision outcomes (A), 2026-10-06

| Id | Outcome |
|---|---|
| A-0 (IL-D0) | A **narrow shared consumption contract** now; broader 3.4 lifecycle stays deferred. Frozen formation facts are preserved. |
| A-1 (IL-D1/2) | Consumption is observed on **canonical 1m bars**. A **high** is consumed strictly above its current outermost confirmed price + tolerance; a **low** strictly below price − tolerance. **Equality does not consume.** |
| A-2 (IL-D1/2) | Each bar evaluates the **version available at its start**. Consumption is **recorded at bar close**. A within-tolerance excursion contributes only **after qualifying confirmation**. **Later confirmation cannot undo consumption.** |
| A-3 (IL-D3/4) | Boundaries come from **Daily H/L and 4H EQ/REQ**. The closest eligible boundaries are selected initially. On consumption, seek the next unconsumed boundary **farther out on that side**. Newly formed boundaries may be introduced **on the opposite side**. Newly confirmed closer levels **do not automatically replace** active boundaries. The External detector keeps recording formations. |
| A-4 (IL-D3/4) | The **upper side may be unbounded**. The lower side is expected to be bounded. With no qualifying lower boundary in history, flag **insufficient boundary data**; never invent one. |
| A-5 (IL-D5) | Historical, known, unconsumed levels qualify **strictly inside** the available boundaries. **Boundary equality is excluded.** |
| A-6 (IL-D6/7/8) | Candidates: **completed 1H candle H/L**; **confirmed swings / EQ / REQ on 5m, 15m, 1H**; **explicit frozen 2/2 swings**. EQ/REQ clusters use confirmed swings grouped by **side and timeframe**. |
| A-7 (IL-D9) | REQ's definitive price is its **outermost constituent**; EQ uses the **common exact price**. Extensions create **prospective immutable versions**. |
| A-8 (IL-D10) | **Consolidate coincident side / price candidates** into one actionable level with multiple evidence references. **No double counting** of shared formations. Consumed identities stay **terminal**; genuinely new formations may create a **new identity at the same price**. |
| A-9 (IL-D11) | Attribute profile with ordered tiers: **timeframe first, then family**. Within a timeframe, **ordinary H/L < REQ < EQ**. Proximity and strategy direction stay separate from quality. |
| A-10 (IL-D12) | The **tolerance-based** consumption rule applies to clusters, replacing the one-tick proposal. |
| A-11 (IL-D13) | Data gaps **terminate** affected levels and ranges as **data uncertainty**, not consumption. Re-establish **without silently reviving pre-gap identities**. Contract state stays isolated. |
| A-12 (IL-D14) | Reuse the formation tables. Add separate **level, range and lifecycle** outputs, plus a **causal active-level view** for strategies. |
| A-13 (OI-1) | **Internal:** REQ **linking and consumption tolerance = 4 ticks**. **External Daily / 4H: 6 ticks**, including consumption of standalone H/L, EQ and REQ. **EQ formation stays exact equality.** Consumption requires **strictly exceeding** the tolerance. |
| A-14 (OI-2) | Coincident internal / external evidence **shares one actionable price record**, with **separate classification lifecycles and thresholds**. Valid internal membership is **not suppressed**, and confluence is **not double-counted**. |
| A-15 (OI-3) | Re-establish using **post-gap formations only**. No uncertain pre-gap boundary reuse, no silent reactivation. |
| A-16 (OI-4) | At a boundary consumption, **advance the consumed side outward** and **reselect the closest eligible opposite boundary**. **Retain** the existing opposite boundary if no qualifying replacement exists. **No reselection between consumption events.** |
| A-17 (OI-5) | With no qualifying lower boundary, **no active range**: report `INSUFFICIENT_BOUNDARY_DATA`. An **unbounded upper** side stays supported. |
| A-18 (OI-6) | Within 1H: **candle H/L < confirmed swing < REQ < EQ**. Timeframe-first grading is preserved. |
| A-19 (boundary assignments) | A **boundary assignment** is **pinned** to its selected formation version, price and tolerance. Its consumption is evaluated **independently** of the current cluster's consumption. **Later cluster extensions never change an existing assignment.** A consumed assignment stays **terminal** even if the extended cluster remains active. At boundary consumption, the approved outward-advancement and opposite-reselection rules apply. "Consumed clusters cannot extend" is limited to consumption of the **current cluster object**, not of a pinned assignment. |

---

## 2. Decision → section mapping

| Decision | Outcomes | Realized in |
|---|---|---|
| IL-D0 | A-0 | §3.1, §9 |
| IL-D1 / IL-D2 | A-1, A-2, A-13 | §3.1, §3.8; E1–E4, E19; IL-INV-4…6 |
| IL-D3 / IL-D4 | A-3, A-4, A-16, A-17 | §3.6; §4.3; E9–E12, E20, E21; IL-INV-9, IL-INV-17 |
| IL-D5 | A-5, A-14 | §3.6.5, §3.4; E13, E19 |
| IL-D6 / IL-D7 / IL-D8 | A-6, A-13 | §3.2, §4.4 |
| IL-D9 | A-7 | §3.3.1; E5–E7 |
| IL-D10 | A-8, A-14 | §3.3.2 – §3.4; §4.1 |
| IL-D11 | A-9, A-18 | §3.5; E15 |
| IL-D12 | A-10, A-13 | §3.1.3; E6 |
| IL-D13 | A-11, A-15 | §3.7; §4.2; E14, E22 |
| IL-D14 | A-12, A-14 | §3.9 |
| OI-1 … OI-6 | A-13 … A-18 | As listed above |
| Boundary assignments | A-19 | §3.6.1 – §3.6.4, §3.7, §3.8, §3.9; §4.4 (P-1 scope), §4.5; E23 – E25; IL-INV-19, IL-INV-20 |

---

## 3. Design (draft for final approval)

Prices are MNQ (tick 0.25). **Internal tolerance 4 ticks = 1.00 point.
External tolerance 6 ticks = 1.50 points.** `o / h / l / c` are the open /
high / low / close of a canonical 1m bar `m`; `s(m)` / `e(m)` are its start /
close.

### 3.1 Narrow shared consumption contract (A-0, A-1, A-2, A-10, A-13)

**Scope.** One deterministic predicate plus the evidence it records, used by
Internal levels and by a derived consumption view over External objects. 3.4
adopts it. It defines no broader lifecycle vocabulary. Frozen formation
tables are never modified.

**Consumable object.**

- `class`: INTERNAL / EXTERNAL;
- `side`: UPPER / LOWER;
- immutable versions, each with a definitive price `p` (tick-aligned),
  `tolerance_ticks` `t`, and `available_at`;
- `contract`.

There are three kinds (RC), all evaluated by the same predicate and each
with its own lifecycle:

| Kind | Versions | Price over time |
|---|---|---|
| Internal level (§3.3) | Evidence versions | Fixed: the level's anchor price |
| External object (§3.6.1): a Daily member, or an External cluster lineage | Daily member: one. Cluster: one per D-134 structure version | Daily: fixed. Cluster: the **current** version's definitive price (A-1) |
| **Boundary assignment** (§3.6.2) | **Exactly one, pinned at selection** (A-19) | Fixed: the pinned price and tolerance |

**Threshold:**

- UPPER: `θ = p + t·tick`;
- LOWER: `θ = p − t·tick`.

**Predicate.** 1m bar `m` consumes the object iff:

- it is active at `s(m)`;
- the version available at `s(m)` is used;
- and UPPER `h(m) > θ`, LOWER `l(m) < θ`.

Equality with `θ` does not consume (A-1, A-13).

**Tolerances (A-13).**

| Object | `t` | Formation tolerance (unchanged) |
|---|---|---|
| External Daily high / low member | 6 | — (standalone) |
| External 4H / Daily EQ cluster | 6 | 0 (exact) |
| External 4H / Daily REQ cluster | 6 | 6 (D-134) |
| Internal 1H candle level | 4 | — |
| Internal 5m / 15m / 1H swing level | 4 | — |
| Internal 5m / 15m / 1H EQ cluster | 4 | 0 (exact) |
| Internal 5m / 15m / 1H REQ cluster | 4 | **4** (linking) |

**Recording.**

- **When:** at `e(m)`. Every object consumed by bar `m` gets the same
  timestamp; no intrabar order is inferred.
- **Evidence:** the bar's `BAR_SPAN` ref, `o / h / l / c`, the version id
  evaluated, `p`, `t`, `θ`, `excess_ticks` (beyond `θ`), and `gap_through`
  (UPPER `o > θ`, LOWER `o < θ`).
- **Terminal.** Consumption is never undone (A-2).

**Within-tolerance excursions.** A bar beyond `p` but not beyond `θ` does
not consume. It is recorded as audit (`max_penetration_ticks`, nonnegative;
the signed form is `max_signed_excursion_ticks`). It changes the
object only through a later qualifying confirmation, which creates a
prospective version available at that confirmation (A-2).

**Continuity.**

- The contract runs on the fail-closed 1m expected schedule, using the
  approved Market Structure §G.2a adapter pattern with an explicit, required
  `replay_cutoff`.
- Missing / incomplete expected observations and contract changes terminate
  objects (§3.7), never as `CONSUMED`.

#### 3.1.3 Clusters (A-10)

A cluster object is consumed when its **current** version's definitive price
(the common EQ price or the REQ outermost) is exceeded by more than `t`.
Inner constituents are not cluster consumption: they are standalone levels
with their own thresholds (§3.3).

### 3.2 Formation atoms (A-6, A-13)

**Frozen envelope.** `liquidity_class = INTERNAL` (RC):

| Atom | Table | Kind | `reference_family` | `source_ref` | `available_at` |
|---|---|---|---|---|---|
| 1H candle high / low | `liquidity_members` | `INTERNAL_CANDLE_HIGH` / `_LOW` | `1H` | `HTF_BAR:<instrument>\|<contract>\|1H\|<bar_end>` | 1H `bar_end` |
| Confirmed swing high / low | `liquidity_members` | `INTERNAL_SWING_HIGH` / `_LOW` | `5m` / `15m` / `1H` | The swing's `BAR_SPAN` | The swing's `available_at` |
| EQ / REQ version | `liquidity_structures` | `EQ` / `REQ` | `5m` / `15m` / `1H` | Member ids | The confirming swing's `available_at` |

- Only complete 1H bars yield candle atoms.
- Swings come from the frozen detector with the explicit
  `SwingDefinitionSpec("swing-pivot-v1", 2, 2)` on each timeframe.

**EQ / REQ grammar** (D-134 rules at the internal grain; A-13): clusters of
**confirmed swings of one side and one timeframe**, inside one continuity
segment and contract.

- EQ = exact equality.
- REQ link ≤ **4 ticks**, with chain connectivity and ≥ 2 distinct prices; a
  pure-equal component is EQ only.
- The **pair-outer barrier** applies on that timeframe's bars strictly
  between the two swings.
- Immutable FORMED / EXTENDED / MERGED versions with `supersedes`.
- No averaged level, no member cap, never back-dated.
- Distinct swings are distinct formations, separated by at least one
  observation with a strictly lower high (higher low). No extra gap rule
  applies (RC).

### 3.3 Internal levels (A-7, A-8)

#### 3.3.1 Definitive price (A-7)

| Evidence | Price |
|---|---|
| 1H candle, swing | Its source price |
| EQ version | The common exact price |
| REQ version | The outermost constituent: max for UPPER, min for LOWER |

Constituent prices and ids are evidence on every version; a zone is never
the output.

#### 3.3.2 Consolidation and identity (A-8)

- **One active internal level per (contract, side, price).** Every internal
  candidate with that definitive price attaches to it.
- **Identity.**
  `level_id = il_ + sha256(definition_version, instrument_id, contract_scope, contract, side, price_ticks, first_evidence_source_ref)`.
  The first evidence is the earliest available candidate that created the
  level while no active internal level existed at that (side, price).
- **Terminal.** After `CONSUMED`, `DATA_GAP` or `CONTRACT_CHANGE`, a
  `level_id` never reactivates. A **genuinely new formation** at the same
  price (a source not already evidence of the terminated level) creates a new
  `level_id`.

#### 3.3.3 Versions (A-7)

- `level_version_id = iv_ + sha256(level_id, sorted evidence ids, sorted superseded evidence ids)`.
- `change_kind` is CREATED, EVIDENCE_ADDED or EVIDENCE_SUPERSEDED, with
  `supersedes`.
- `available_at` is the evidence change's availability (never back-dated).
  `level_available_at` never changes.
- A level's price and tolerance never change; versions change only evidence
  and therefore grade.
- **Moving REQ outermost.** The new REQ version attaches to the level at the
  new outermost price. The old outermost's level gets EVIDENCE_SUPERSEDED and
  remains active on its own swing evidence. "Current outermost confirmed
  price" (A-1) is always the price of the level carrying the cluster's latest
  version.

### 3.4 Actionable price records: internal / external coincidence (A-14, RC)

**Price record.** Every (contract, side, price) at which any
consumable object exists has one **actionable price record**:
`price_record_id = lp_ + sha256(instrument_id, contract_scope, contract, side, price_ticks)`.

- It is a grouping key, **not** a lifecycle entity. It never terminates or
  reactivates. Over time it groups successive objects at that price.
- It references:
  - **Internal:** the internal level at that price (at most one active),
    lifecycle namespace `liquidity.consumption`, threshold `p ± 4`.
  - **External:** every External object whose **current** definitive price
    equals it (a Daily member, or an External cluster lineage at its current
    version's definitive price), each with its own lifecycle in the same
    namespace and threshold `p ± 6`. A cluster's link follows its current
    version, as a new price-record version.
  - **Boundary assignments** (§3.6.2) at their **pinned** price, each with its
    own lifecycle and pinned threshold. A cluster extension never moves an
    assignment's link.
- **Separate lifecycles and thresholds (A-14).** Each class object keeps
  its own status, threshold and consumption evidence; they are never merged
  into one status (§4.1).
- **Membership is not suppressed (A-14).** An internal level coincident with
  a **non-boundary** External object is a normal member when strictly inside
  the range.
  - Boundary equality remains excluded (A-5): an internal level at the price
    of an **active range boundary** is not a member while that boundary is
    active.
- **Confluence is not double-counted (A-8, A-14).** The price record's
  evidence is the union of the internal and external objects' evidence.
  `confluence` counts **distinct physical extremes** in that union:
  - same contract, side and price, with overlapping source spans in time,
    count once;
  - example: a Daily high and the 5m swing that printed it are one extreme.

### 3.5 Grading (A-9, A-18)

Per internal level version:

- `grade_tier`, `grade_rank`;
- `grade_profile`:
  - primary family and timeframe;
  - `confluence` (§3.4);
  - distinct timeframes;
  - constituent count;
  - distinct constituent prices;
  - `external_coincidence`: External object ids on the price record that
    are active at the version's availability;
- `grade_explanation`.

Sort by `grade_rank`, then `confluence`, then distinct timeframes, then
`level_id`. External evidence never changes the **tier**; it affects only
`confluence` and the profile. Grades never use proximity, direction, time or
outcomes.

| Rank | Tier | Basis |
|---|---|---|
| 1 | 5m swing | A-9 |
| 2 | 5m REQ | A-9 |
| 3 | 5m EQ | A-9 |
| 4 | 15m swing | A-9 |
| 5 | 15m REQ | A-9 |
| 6 | 15m EQ | A-9 |
| 7 | 1H candle H/L | A-18 |
| 8 | 1H swing | A-18 |
| 9 | 1H REQ | A-18 |
| 10 | 1H EQ | A-18 |

A 1H candle and the 1H swing on the same bar are one physical extreme
(confluence 1), graded at the swing tier.

### 3.6 External ranges (A-3, A-4, A-5, A-15, A-16, A-17)

#### 3.6.1 External objects and boundary candidates (RC)

**External objects** (a derived consumption view; External itself is
unchanged):

- **Daily member object.** One per External Daily high / low member: fixed
  price, `t = 6`. Identity = its `member_id`.
- **External cluster object.** One per External 4H (and Daily) EQ / REQ
  **lineage**, `t = 6`.
  - Lineage id: `xc_ + sha256(structure_id of the FORMED version)`.
  - An EXTENDED version continues the lineage.
  - A MERGED version starts a **new** lineage that references the absorbed
    lineages. Absorbed active lineages end with `MERGED`, a non-consumption
    terminal exit. There is no survivor, consistent with D-134.
  - Its versions are the D-134 structure versions. Its price is the
    **current** version's definitive price (common EQ / outermost REQ).
  - Consumption uses the version available at `s(m)` (A-1).

**Boundary candidates** at an instant: the UPPER (LOWER) Daily member
objects and External cluster objects of the boundary families (A-3), at
their current price. Inner 4H REQ members are not separate candidates. A
candidate is **eligible** iff:

- same contract as the range;
- `available_at` reached;
- the object is not consumed, terminated or merged;
- **after a data gap, a post-gap formation (A-15)**: every source of the
  candidate's current version has `source_at` later than the gap's §G.2a
  onset.

Selecting a candidate as a boundary creates a **boundary assignment**
(§3.6.2). Range versions reference assignments, never live objects.

#### 3.6.2 Boundary assignments (A-19)

A boundary assignment is an immutable record of "this formation version, at
this price and tolerance, is this range's boundary on this side from this
instant".

| Field | Meaning |
|---|---|
| `boundary_assignment_id` | `ba_ + sha256(range_id, side, external_object_id, pinned_formation_ref, pinned_price_ticks, pinned_tolerance_ticks, canonical(assigned_at))` |
| `range_id`, `side` | The range and side (UPPER / LOWER) |
| `external_object_id` | The Daily `member_id` or the External cluster lineage id (`xc_...`) |
| `pinned_formation_ref` | The exact formation selected: the Daily `member_id`, or the **structure version id** (`ls_...`) current at selection |
| `pinned_member_ids` | That version's member ids (evidence) |
| `pinned_price`, `pinned_price_ticks`, `pinned_tolerance_ticks`, `pinned_threshold` | `p`, `t = 6`, `θ = p ± 6` at selection. **Never change** |
| `assigned_at` | The selection instant `e(m)` (the assignment's `available_at`) |
| `selection_kind` | `ESTABLISHED`, `ADVANCED_OUTWARD`, `OPPOSITE_RESELECTED` |
| `selection_close` | `c(m)` at selection |
| `replaces_assignment_id` | The consumed or released assignment it replaces (null at establishment) |
| Contract fields, `run_id` | - |

**Rules (A-19).**

- **Independent consumption.** The assignment is a consumable object with
  exactly one version (its pinned values), evaluated by the shared
  predicate (§3.1).
  - Its consumption is independent of the External object's consumption
    under the object's current version.
- **No propagation.** Later extensions or merges of the underlying cluster
  never change an active assignment. They change only the live object
  (and therefore future selections).
- **Terminal outcomes:**
  - **`CONSUMED`:** pinned threshold exceeded. Terminal, even if the
    underlying extended cluster object stays active.
  - **`RELEASED`:** replaced by opposite-side reselection (non-consumption).
  - **`RANGE_TERMINATED`:** the range ended (`DATA_GAP`, `CONTRACT_CHANGE`,
    `INSUFFICIENT_BOUNDARY_DATA`).
- **Monotonicity** (no conflict).
  - An UPPER cluster's outermost never decreases across EXTENDED / MERGED
    versions; LOWER mirrors this.
  - Consumption of the live cluster object (`h > p_current + 6`) therefore
    implies consumption of every active assignment pinned to an earlier
    version of it (`p_pinned ≤ p_current`) by the same or an earlier bar.
  - The converse does not hold: an assignment may be consumed while its
    cluster stays active (E23).

#### 3.6.3 Range lineage and versions (RC)

A **range** has a stable `range_id` from establishment until termination
(`DATA_GAP`, `CONTRACT_CHANGE`, `INSUFFICIENT_BOUNDARY_DATA`). A later range
always has a new `range_id`.

Every boundary change creates an immutable, prospective **range version**:

- `upper_assignment_id` (or `UNBOUNDED`) and `lower_assignment_id`, plus
  their pinned prices and thresholds, copied from the assignments;
- `available_at`;
- `change_kind`: ESTABLISHED, UPPER_ADVANCED, LOWER_ADVANCED,
  BOTH_ADVANCED, OPPOSITE_RESELECTED, or an advance combined with an
  opposite reselection.

Each bar uses the range version available at its start. A range version
changes only at a boundary-assignment consumption event, never because a
cluster extended (A-3, A-19).

#### 3.6.4 Selection and boundary changes

- **Establishment** at `e(m)`, when no range is active:
  - **upper** = the closest eligible UPPER candidate with current price
    `≥ c(m)`, else `UNBOUNDED`;
  - **lower** = the closest eligible LOWER candidate with current price
    `≤ c(m)`;
  - **ties** (confirmed by the design authority, 2026-10-07): first ascending `available_at` of the candidate's current formation version; then ascending `source_at` (a Daily member's own `source_at`; for a cluster version, the earliest constituent member `source_at`); then ascending stable candidate id;
  - **no lower:** no range; report `INSUFFICIENT_BOUNDARY_DATA` (A-17).

  Each selected side gets a new assignment pinned to the candidate's current
  formation version.
- **Boundary consumption event:** an active **boundary assignment** is
  consumed at `e(m)` (pinned threshold, A-19). The update runs after every
  consumption and admission of bar `m` (A-16):
  1. **Consumed side advances outward** to the closest eligible candidate
     whose **current** price is farther out than the consumed assignment's
     **pinned** price:
     - UPPER: `p > pinned price`, else `UNBOUNDED`;
     - LOWER: `p < pinned price`; if none exists, the range **terminates**
       with `INSUFFICIENT_BOUNDARY_DATA` (A-17).

     A new assignment is pinned to that candidate's current formation
     version. The **surviving extended cluster** of the consumed assignment
     is an ordinary candidate here: it qualifies iff its current version is
     unconsumed, eligible and farther out (§4.5, E23).
  2. **Opposite side is reselected:** the closest eligible candidate on that
     side relative to `c(m)` (LOWER `≤ c(m)`, UPPER `≥ c(m)`).
     - It replaces the active opposite assignment only if its current price
       is strictly closer to `c(m)` than that assignment's **pinned** price.
       The old assignment is then `RELEASED`.
     - Otherwise the existing assignment is **retained** unchanged (A-16).
     - An UNBOUNDED upper is replaced only by an eligible candidate
       `≥ c(m)`.
  3. **Both assignments consumed** by bar `m`: both sides advance outward
     (BOTH_ADVANCED). There is no opposite side to reselect (§4.3).
- **No reselection between consumption events** (A-3, A-16). Cluster
  extensions, newly confirmed closer candidates, and consumption of a live
  cluster object whose assignment was already consumed earlier all wait for
  the next assignment consumption event, or for a new establishment.

#### 3.6.5 Membership (A-5, A-14)

- An internal level is a member of a range version iff the level is active
  and `lower < p < upper` (`lower < p` when the upper is UNBOUNDED).
- Equality with an active boundary assignment's **pinned price** excludes it
  (audit `COINCIDES_WITH_BOUNDARY`).
- Coincidence with non-boundary External objects does not exclude it (A-14).
- Historical, known, unconsumed internal levels qualify as soon as a
  containing range version is available.
  - **After a gap**, only post-gap levels exist (§3.7).

### 3.7 Lifecycle and exits (A-2, A-11, A-15)

| Object | Terminal exits | Re-eligible? |
|---|---|---|
| Internal level | `CONSUMED`, `DATA_GAP`, `CONTRACT_CHANGE` | Never. A genuinely new formation creates a new id |
| External Daily member object (derived view) | `CONSUMED`, `DATA_GAP`, `CONTRACT_CHANGE` | Never. Frozen External facts remain, but a terminated object is never a candidate again |
| External cluster lineage (derived view) | `CONSUMED` (current version), `MERGED` (absorbed; non-consumption), `DATA_GAP`, `CONTRACT_CHANGE` | Never. A MERGED lineage continues only as the new merged lineage |
| Boundary assignment (§3.6.2) | `CONSUMED` (pinned threshold), `RELEASED` (opposite reselection), `RANGE_TERMINATED` | Never. Re-selecting the same External object later creates a **new** assignment pinned to its then-current version |
| Range | `DATA_GAP`, `CONTRACT_CHANGE`, `INSUFFICIENT_BOUNDARY_DATA` | Never. A later range is a new `range_id` |
| Membership (derived) | `RANGE_VERSION_EXCLUDES`, `RANGE_TERMINATED`, `LEVEL_CONSUMED`, `LEVEL_TERMINATED` | An unconsumed level may join a later version or range |

**Data gaps (A-11, A-15).**

- **At the onset:** at the §G.2a onset of a missing or incomplete expected
  1m observation, every active internal level, every active External object
  in the derived view, every active boundary assignment, and the range
  terminate with `DATA_GAP` (data uncertainty, not consumption).
- **After the gap**, only formations whose every source is later than the
  onset may create internal levels or serve as boundary candidates.
  - Pre-gap frozen formations are never re-admitted under new identities.
  - No pre-gap identity revives.
- **Consistency with frozen External rules.** Daily and 4H bars that contain
  the gap are incomplete, so they produce no External members (D-134). The
  first post-gap Daily / 4H candidates are therefore exactly the post-gap
  formations.
- **Re-establishment** follows §3.6.4 once both a post-gap upper (or
  UNBOUNDED) and a post-gap lower exist. Until then the state is
  `INSUFFICIENT_BOUNDARY_DATA`.

**Contract change (A-11).** Everything is contract-specific. A new contract
starts with no levels and no range until its own candidates exist.

### 3.8 Causal batch per canonical 1m bar (A-2)

```text
S_m := objects / versions with available_at ≤ s(m)
at e(m):
  (a) shared contract: test every active internal level, every eligible External object (its current
      S_m version) and every active boundary assignment (its pinned version) against bar m
      (θ = p ± t); record all hits at e(m), each object independently
  (b) admissions at e(m): new atoms and cluster versions (internal and External) → levels / versions,
      price-record links (never tested against bar m)
  (c) range update with the eligible candidate set at e(m) (after (a) and (b)):
      - if a boundary assignment was consumed in (a): advance the consumed side(s) outward to new
        pinned assignments, reselect the opposite side (A-16), or terminate INSUFFICIENT_BOUNDARY_DATA
        (A-17); cluster extensions in (b) never alter an existing assignment (A-19);
      - if no range is active: establish (closest eligible; post-gap only after a gap)
  (d) memberships recomputed against the range version (strict containment; active-boundary equality excluded)
continuity: DATA_GAP / CONTRACT_CHANGE terminations at §G.2a onsets; explicit replay_cutoff
```

**Ordering (RC).**

- Candidates admitted at `e(m)` take part in the range update at `e(m)`.
  This is how "newly formed boundaries may be introduced" (A-3) applies to a
  boundary completed by the same bar, e.g. a Daily member completing at
  17:00.
- They are never tested for consumption against bar `m`.
- The new range version is first usable by bar `m+1`.

**Guarantees.**

- Same-close formation is never consumed by its own bar.
- A swing's plateau and right-window bars, and any 1m bar inside them, cannot
  consume its level.
- No intrabar ordering is inferred.
- Prefix equivalence holds for every explicit cutoff.

### 3.9 Output contract (A-12, A-14)

**Formation (frozen tables, reused).** `liquidity_members` and
`liquidity_structures` with `liquidity_class = INTERNAL`.

**`internal_liquidity_levels`** (one row per immutable level version):

- `level_id`, `level_version_id`, `change_kind`, `supersedes`;
- `price_record_id`;
- `side` (UPPER buy-side above highs / LOWER sell-side below lows);
- `price`, `price_ticks`, `tolerance_ticks` (4), `consumption_threshold`;
- `evidence_member_ids`, `evidence_structure_ids`, `superseded_evidence_ids`;
- `constituent_prices`;
- `primary_family`, `primary_timeframe`, `timeframes`;
- `level_available_at`, `available_at`;
- `grade_tier`, `grade_rank`, `grade_profile`, `grade_explanation`;
- `instrument_id`, `contract_scope` (`SPECIFIC`), `contract`,
  `definition_version`, `run_id`, `fact_hash`.

**`liquidity_price_records`** (derived and versioned, one row per change):

- `price_record_id`, side, price, contract fields;
- `internal_level_id` (or null);
- `external_object_refs`;
- per-object status and threshold at the version's `available_at`;
- `confluence`.

**`internal_liquidity_ranges`** (one row per range version):

- `range_id`, `range_version_id`, `change_kind`, `supersedes`;
- `upper_assignment_id` (or `UNBOUNDED`), `upper_pinned_price`,
  `upper_pinned_threshold`;
- `lower_assignment_id`, `lower_pinned_price`, `lower_pinned_threshold`;
- `available_at`, `selection_close`, `post_gap_restricted` (boolean),
  contract fields, `run_id`.

**`range_boundary_assignments`** (one immutable row per assignment; fields
in §3.6.2):

- `boundary_assignment_id`, `range_id`, `side`, `external_object_id`;
- `pinned_formation_ref`, `pinned_member_ids`;
- `pinned_price`, `pinned_price_ticks`, `pinned_tolerance_ticks`,
  `pinned_threshold`;
- `assigned_at`, `selection_kind`, `selection_close`,
  `replaces_assignment_id`;
- `price_record_id`, contract fields, `run_id`.

The assignment's status is replayed from `liquidity.consumption`; it is never
stored as a mutable column.

**`external_cluster_objects`** (derived view, one row per lineage version):

- `external_object_id` (`xc_...`), `structure_id`, `change_kind`;
- `merged_from_object_ids`;
- the current definitive price and threshold;
- `available_at`.

**Range status view.** At each instant: `ACTIVE` (with `range_version_id`),
`INSUFFICIENT_BOUNDARY_DATA`, or `NO_DATA` (inside a gap).

**Lifecycle: M7A namespaces.**

| Namespace | Entity | States | `reason_code` / attributes |
|---|---|---|---|
| `liquidity.consumption` | Internal level, External Daily object, External cluster lineage, or boundary assignment | ACTIVE → CONSUMED / TERMINATED | `CONSUMED`; TERMINATED with `DATA_GAP`, `CONTRACT_CHANGE`, `MERGED` (cluster lineage), `RELEASED` or `RANGE_TERMINATED` (assignment). Attributes: `attr_object_kind`, `attr_class`, `attr_threshold_ticks`, `attr_excess_ticks`, `attr_gap_through`, `attr_version_evaluated` (the pinned formation for assignments). Trigger: the 1m `BAR_SPAN`, `CONTINUITY_BREAK`, or the range event |
| `liquidity.internal_range` | `range_id` | ACTIVE → TERMINATED | `DATA_GAP`, `CONTRACT_CHANGE`, `INSUFFICIENT_BOUNDARY_DATA` |

**Other outputs.**

- **Consumption evidence** (local, price-bearing): object id, class, the
  consuming bar ref with o / h / l / c, `p`, `t`, `θ`, `excess_ticks`,
  `gap_through`, the version evaluated, `max_penetration_ticks` and
  `max_signed_excursion_ticks`.
- **Membership view** (derived): `range_id`, `range_version_id`,
  `level_id`, `from_at`, `until_at`, `end_reason`.
- **Causal active-level view for strategies** (A-12). For instant `t`
  (bar-boundary rule `available_at ≤ bar_start`), one row per member
  internal level with:
  - `level_id`, `level_version_id`, `price_record_id`;
  - side, price, internal `θ`;
  - grade tier / rank / explanation, `confluence`, `external_coincidence`;
  - `range_id`, `range_version_id`, `upper_assignment_id`,
    `lower_assignment_id`, and their pinned prices.

  It has no proximity or direction columns.

---

## 4. Final consistency check

### 4.1 Separate consumption statuses at one price (A-14)

- For one price `p`, the internal threshold is `p ± 4` and the External one
  `p ± 6`.
- For UPPER, `h > p + 6` implies `h > p + 4`; LOWER mirrors.
- So **within one epoch** (both objects active over the same bars), an
  External object can never be consumed while the coincident internal level
  stays active.

The reachable joint states are:

| Internal | External | How |
|---|---|---|
| ACTIVE | ACTIVE | No bar beyond `p ± 4` since both became available |
| CONSUMED | ACTIVE | A bar in `(p + 4, p + 6]` (UPPER) |
| CONSUMED | CONSUMED | One bar beyond `p + 6`, or two bars |
| ACTIVE | CONSUMED | Only across epochs: the External object was consumed **before** a genuinely new internal formation at `p` became available. The new level is unaffected (separate lifecycles) |

- Each status is recorded once, in its own `liquidity.consumption` entity,
  with its own threshold. The price record shows both.
- A consumed or terminated object never reactivates.

### 4.2 Post-gap source eligibility (A-11, A-15)

- **Never eligible after a gap at onset `t_r`:**
  - every pre-gap object, internal or External, active or not;
  - every formation with any source `≤ t_r`.
- **Incomplete bars** containing the gap yield no candles (internal 1H) and
  no External members (D-134). Swing and EQ/REQ continuity segments break at
  the gap (frozen continuity), so no cluster links across it.
- **No implicit carry** therefore exists at any layer, consistent with D-123
  and A-15.
- Re-establishment is driven only by post-gap Daily / 4H candidates, and an
  unbounded upper is allowed.
- **Example.** A missing minute at 10:31 Tuesday makes Tuesday's Daily
  incomplete. With no post-gap 4H EQ/REQ yet, the first possible lower is
  Wednesday's complete Daily low, so `INSUFFICIENT_BOUNDARY_DATA` holds until
  Wednesday 17:00.

### 4.3 Bars consuming both boundaries (A-16)

- If bar `m` trades above the upper assignment's pinned threshold
  (`upper + 6`) and below the lower one's (`lower − 6`), both assignments are
  consumed, and so is every internal level strictly inside.
  - Proof: `p < upper` gives `h > upper + 6 > p + 4`; LOWER mirrors.
  - Coincident internal levels at a boundary price (excluded from membership)
    are consumed as well.
- Both sides advance outward at `e(m)` (BOTH_ADVANCED). Each takes the
  closest eligible candidate farther out, after all of bar `m`'s
  consumptions.
- There is no opposite side to reselect. Upper → UNBOUNDED if none exists.
  Lower with none → `INSUFFICIENT_BOUNDARY_DATA`, range terminated.
- No order between the two crossings is inferred or recorded.

### 4.4 Formation grammar vs. tolerance consumption (D-134)

**Proposition P-1 (a consumed current cluster object is never extended or
merged).** It holds whenever the link tolerance `t_f` is ≤ the consumption
tolerance `t_c`, with the pair-outer barrier on bars that contain the 1m
bars.

**Scope (A-19).** P-1 concerns consumption of the **current cluster
object**, i.e. a bar beyond the threshold of its version available at that
bar's start. It says nothing about a **pinned boundary assignment**.

- An assignment may be consumed (beyond its pinned `θ`) while the live
  cluster, already extended to a farther outermost, stays unconsumed.
- That cluster may keep extending (E23).

- The sweeping 1m bar lies in a formation-timeframe bar with high `≥ H`,
  where `H > p_out + t_c`.
- **That bar is between members `i` and `j`:** then `p_j ≥ H`. So
  `p_j − p_i > t_c ≥ t_f`: no link.
- **It is in `j`'s plateau or right window:** then `p_j ≥ H`. Same
  conclusion.

**Status under A-13:**

- Internal: `t_f = t_c = 4` ✓.
- External REQ: `t_f = t_c = 6` ✓.
- EQ: `t_f = 0 ≤ t_c` ✓.

"Later confirmation cannot undo consumption" (A-2) therefore holds
structurally.

### 4.5 Boundary assignments vs. current cluster objects (A-19)

- **Independent evaluation.** In one batch, the live cluster object is tested
  with its current version's `θ`, and every assignment with its pinned `θ`.
  The outcomes are independent records.
- **One direction only.** Because an UPPER outermost never decreases across
  versions (LOWER mirrors this), the live object's consumption implies the
  consumption of every active assignment pinned to it. The reverse does not
  hold.
- **Extensions never touch assignments.** A cluster EXTENDED or MERGED after
  an assignment was pinned changes only the live object, its price record
  and future selections. The active range version keeps the pinned price,
  threshold and formation ref (IL-INV-19).
- **The surviving extended cluster may be the next outward boundary.** It
  qualifies under the approved rules (A-3, A-16) iff:
  - its **current** price is farther out than the consumed assignment's
    pinned price;
  - its current version is **unconsumed** (it was not beyond its own `θ`,
    including on the consuming bar);
  - it is otherwise eligible (contract, post-gap rule, not MERGED / terminated);
  - it is the closest such candidate.

  It then receives a **new** assignment pinned to its current version (E23).
  If the consuming bar also exceeded its current `θ`, it is consumed and the
  advance skips it (E24). If the extension arrives only after the
  assignment's consumption bar, the live object was consumed by that same bar
  under its then-current version, and P-1 forbids the later extension (E25).
- **Upper boundary below the close is allowed.** An advance may select a
  candidate below `c(m)`: in E23 the new boundary 20,101.00 can be below a
  close of 20,101.25. That is the same situation as any active boundary
  probed within its tolerance band. It is not consumed, and internal
  membership stays strictly below the pinned price. No conflict with A-3 /
  A-16, which do not constrain advances relative to the close.

### 4.6 Other checks (no conflict found)

| Check | Result |
|---|---|
| Moving REQ outermost (A-7, A-8) | Evidence moves to the level at the new price; two active internal levels never collide; no survivor rule needed (consistent with D-134) |
| Opposite reselection (A-16) vs. no replacement (A-3) | Reselection only at assignment consumption events. Between them the pinned assignments are fixed, even if their clusters extend (A-19) |
| Unbounded upper (A-4, A-17) | Range valid with `lower < p`; a later consumption event may reselect it to a newly eligible upper `≥ c(m)` |
| A-5 vs. A-14 | Boundary equality still excludes; only non-boundary External coincidence keeps membership |
| Frozen modules | Read-only; `lm_` / `ls_` ids unchanged; new ids are `il_`, `iv_`, `lp_`, range ids |
| Close-beyond (D-139) | Not used for consumption |
| Grades | Pure functions of version evidence. External coincidence affects only profile / confluence, never tier |

---

## 5. Remaining semantic conflicts

**None found.** Everything in §3 not stated by A-0 … A-19 is a
representation choice (RC) inside them:

- External cluster lineage ids (`xc_`), with MERGED starting a new lineage;
- boundary-assignment ids (`ba_`) and fields;
- an opposite replacement only when strictly closer than the pinned price;

- the price-record grouping key;
- range lineage with immutable versions;
- 4H cluster boundaries at the outermost price;
- one shared lifecycle namespace;
- derived membership and active views;
- the batch ordering note.

---

## 6. Worked examples

| # | Case | Expected |
|---|---|---|
| E1 | Internal UPPER `p = 20,050.00`, `θ = 20,051.00`; bars with `h` = 20,050.75 / 20,051.00 / 20,051.25 | Within-tolerance (audit); equality (no); **consumed** at `e(m)`, excess 1 tick |
| E2 | Internal LOWER `p = 19,950.00`, `θ = 19,949.00`; `l` = 19,949.00 / 19,948.75; a bar opening at 19,948.00 | No; consumed; consumed with `gap_through` |
| E3 | External Daily high 20,100.00, `θ = 20,101.50`; External 4H EQL 19,960.00, `θ = 19,958.50` | `h = 20,101.50` no, `h = 20,101.75` consumed; `l = 19,958.50` no, `l = 19,958.25` consumed |
| E4 | Level created at `e(m)`; bar `m` has `h = θ + 2` | Not consumed by `m`; first tested on `m+1` |
| E5 | 5m S1 20,050.00 (10:20); S2 20,050.75 (10:55; 3 ticks; barrier ok) | REQ v1 {S1, S2}. Level 20,050.75 {S2, REQ v1}, `θ = 20,051.75`. Level 20,050.00 {S1}, `θ = 20,051.00` |
| E6 | 1m bar at 11:05 with `h = 20,051.50` | Consumes level 20,050.00. Level 20,050.75 stays active (within tolerance) |
| E7 | The 11:05 excursion confirms as 5m S3 20,051.50 at 11:20 (barrier ok, 3 ticks) | REQ v2 EXTENDED. New level 20,051.50 {S3, REQ v2}, `θ = 20,052.50`. Level 20,050.75 gets EVIDENCE_SUPERSEDED (keeps S2). Bars before 11:20 used v1 |
| E8 | Variant: 11:12 bar with `h = 20,052.00` (> 20,051.75) | Level 20,050.75 consumed at 11:13. A later swing at 20,052.00 (5 ticks away) cannot link (P-1); it is a new standalone level |
| E9 | `c = 20,010`; closest eligible Daily low 19,900, Daily high 20,100 | Range v1 ESTABLISHED [19,900, 20,100] |
| E10 | The upper is consumed (`h = 20,101.75`, `c = 20,098`). Farther out: 4H EQH 20,180. Opposite: a 4H EQL at 19,960 formed since v1 (eligible, `≤ c`) | v2 UPPER_ADVANCED + OPPOSITE_RESELECTED: [19,960, 20,180]. Internal levels in (19,900, 19,960] leave (`RANGE_VERSION_EXCLUDES`); unconsumed levels in (20,100, 20,180) join |
| E11 | Same, but no newer lower and no farther upper | v2 UPPER_ADVANCED: [19,900, UNBOUNDED] (opposite retained) |
| E12 | One bar with `l = 19,898.25`, `h = 20,102.00` against [19,900, 20,100] | Both boundaries and every inside internal level are consumed at `e(m)`. With a farther lower 19,820 and upper 20,180 → v2 BOTH_ADVANCED [19,820, 20,180]. With no farther lower → range terminated, `INSUFFICIENT_BOUNDARY_DATA` |
| E13 | Internal level 20,100.00 equal to the active upper boundary; historical 15m swing low 19,950 (unconsumed) | The first is excluded (`COINCIDES_WITH_BOUNDARY`); the second is a member |
| E14 | Missing 1m minute at Tuesday 10:31 | All internal levels, all External objects in the view, and the range terminate `DATA_GAP` at 10:31. Tuesday's Daily is incomplete (no member). The status is `INSUFFICIENT_BOUNDARY_DATA` until post-gap candidates exist on the lower side. Pre-gap formations never re-admit |
| E15 | 5m EQH vs. 1H swing high; 1H candle H/L vs. 1H swing; 1H candle + 1H swing on one bar | 1H swing (8) > 5m EQ (3). Candle (7) < swing (8). The coincident pair is one extreme, tier 8, confluence 1 |
| E16 | Consumed level 20,050.00; a later new 5m swing at 20,050.00 | A new `level_id`; the old one stays CONSUMED; the same `price_record_id` |
| E17 | Contract roll | Nothing crosses. The new contract has no range until its own candidates exist |
| E18 | Prefix replays: at a consumption bar, inside a gap, and between an excursion and its confirmation | Restricted equality |
| E19 | Internal 5m swing level 20,075.00 (`θ = 20,076.00`) coincident with a non-boundary External Daily high 20,075.00 (`θ = 20,076.50`), inside range [19,900, 20,180]. A bar with `h = 20,076.25`, then later `h = 20,076.75` | One price record. The internal level is a **member** while active. The first bar consumes **internal only**; the External object stays ACTIVE. The second bar consumes the External object. Confluence 1 if the swing printed the Daily high (one extreme), else 2 |
| E20 | The lower boundary 19,900 is consumed; no farther lower exists in the contract's history | Range terminated `INSUFFICIENT_BOUNDARY_DATA`; no memberships until a qualifying lower exists |
| E21 | Unbounded upper [19,900, UNBOUNDED]; a newly formed Daily high 20,300 appears; then the lower 19,900 is consumed (`c = 19,895`), with farther lower 19,820 | 20,300 does not bound until a consumption event. At the lower consumption: LOWER_ADVANCED to 19,820; the opposite is reselected to the closest eligible upper `≥ 19,895`, i.e. 20,300 (or a closer eligible one) |
| E22 | After E14, Wednesday's Daily completes (high 20,140, low 19,980, `c = 20,010`) | New `range_id`, ESTABLISHED [19,980, 20,140], `post_gap_restricted = true`. Only post-gap internal levels can be members |
| E23 | **Extension 20,100.00 → 20,101.00.** Monday: the upper is External 4H REQH lineage `xc_X` v1 {20,099.00, 20,100.00}, outermost 20,100.00 → assignment `BA1` pinned (v1, 20,100.00, `t = 6`, `θ = 20,101.50`). Tuesday: the 4H bar 06:00–10:00 (high 20,101.00, 4 ticks, barrier ok) extends `xc_X` → v2 EXTENDED, outermost 20,101.00, `θ = 20,102.50`, available 10:00. At 13:42 a 1m bar has `h = 20,101.75`; the next Daily high above is 20,180.00 | **10:00:** `BA1` unchanged (still 20,100.00 / 20,101.50); range version unchanged; `xc_X` moves to price record 20,101.00. **13:43:** `BA1` CONSUMED (20,101.75 > 20,101.50); `xc_X` stays ACTIVE (20,101.75 ≤ 20,102.50). **Advance:** candidates beyond 20,100.00 are `xc_X` @20,101.00 and Daily 20,180.00. `xc_X` is eligible and closest, so new `BA2` pinned (v2, 20,101.00, `θ = 20,102.50`), ADVANCED_OUTWARD, replaces `BA1`. The opposite side is reselected per A-16. `BA1` stays CONSUMED |
| E24 | E23 variant: the 13:42 bar has `h = 20,102.75` | `BA1` CONSUMED and `xc_X` CONSUMED (beyond 20,102.50) in the same batch. The advance skips `xc_X` → `BA2` pinned to Daily 20,180.00 |
| E25 | E23 variant: no extension before 13:42; `h = 20,101.75` | At 13:43, `BA1` CONSUMED and `xc_X` (current v1, `θ = 20,101.50`) CONSUMED. A later 4H high 20,101.00 cannot link: any later candidate must be ≥ 20,101.75, which is more than 6 ticks from 20,100.00 (P-1). The advance goes to the next eligible candidate |

---

## 7. Invariants (each must have 0 violations)

| Id | Invariant |
|---|---|
| IL-INV-1 | Level prices are tick-aligned and equal their definitive price (source / common EQ / REQ outermost) |
| IL-INV-2 | At most one active internal level per (contract, side, price) |
| IL-INV-3 | Terminal ids never reappear in later versions, memberships or active views |
| IL-INV-4 | Each consumption uses the version available at `s(m)`, exceeds `θ` strictly on bar `m`, and is the first such bar since eligibility (first-hit; each bar against its own start version) |
| IL-INV-5 | No consumption at excess 0. No consumption by a bar ending at or before the object's `available_at` |
| IL-INV-6 | Tolerances: internal objects 4; External Daily / 4H objects 6; EQ formation 0; internal REQ link 4 (A-13) |
| IL-INV-7 | P-1: no cluster version available after a consumption extends or merges the consumed cluster |
| IL-INV-8 | Membership: strict containment (UNBOUNDED upper allowed); active-boundary equality excluded; both objects active over the interval; none while `INSUFFICIENT_BOUNDARY_DATA` |
| IL-INV-9 | Boundaries: assignments are created only for eligible candidates of the boundary families; closest at establishment; an advance goes to the closest eligible candidate whose current price is beyond the consumed assignment's pinned price; the opposite side changes only at assignment consumption events, and only to a strictly closer eligible candidate, else retained (A-16) |
| IL-INV-10 | Versions immutable and prospective; `level_available_at` constant |
| IL-INV-11 | Confluence counts distinct physical extremes across the price record's internal + external evidence |
| IL-INV-12 | Contract isolation. `DATA_GAP` / `CONTRACT_CHANGE` at §G.2a onsets |
| IL-INV-13 | Grades are pure and follow §3.5 ordering; external coincidence never changes the tier |
| IL-INV-14 | M7A validity of both namespaces; at most one terminal transition per entity |
| IL-INV-15 | Prefix equivalence for every tested cutoff |
| IL-INV-16 | Internal EQ/REQ versions satisfy D-134 grammar with a 4-tick link (independent recomputation) |
| IL-INV-17 | **Post-gap:** after a gap with onset `t_r`, no object or formation with any source `≤ t_r` is active, a member, or a boundary candidate |
| IL-INV-18 | **Price records:** each class object keeps its own status and threshold. Within an epoch, no External consumption precedes the coincident internal consumption |
| IL-INV-19 | **Boundary immutability (A-19).** Once written, an assignment's `pinned_formation_ref`, `pinned_member_ids`, `pinned_price`, `pinned_tolerance_ticks`, `pinned_threshold`, `assigned_at` and `external_object_id` never change. Its consumption is evaluated only against `pinned_threshold` (first-hit). It has at most one terminal exit (CONSUMED / RELEASED / RANGE_TERMINATED). Every range version's boundary prices equal its assignments' pinned prices. A range version changes only at an assignment consumption event or a termination, never at a cluster extension / merge. A terminal assignment is never referenced by a later range version |
| IL-INV-20 | **Assignment vs. live cluster.** At `assigned_at`, the `pinned_formation_ref` was the current version of `external_object_id`, and that object was eligible. Consumption of a live cluster object at bar `m` implies that every active assignment pinned to that lineage is consumed at or before `m`. An assignment's consumption never terminates or alters its live cluster object |

---

## 8. Visual review requirements

Every case shows:

- source formations (spans with `available_at` markers);
- the definitive price **and** every class threshold on its price record
  (internal `θ` and External `θ`, dashed and distinct);
- REQ / EQ constituent prices;
- range versions (`UNBOUNDED`, `INSUFFICIENT_BOUNDARY_DATA` and
  `post_gap_restricted` markers);
- each **boundary assignment** as its own pinned line (formation ref, pinned
  price and threshold), drawn separately from the live cluster object's
  current price and threshold;
- membership intervals;
- grade tier and explanation;
- the consuming 1m bar highlighted, with class, `excess_ticks`,
  `gap_through` and the evaluated version.

| Area | Required cases |
|---|---|
| Consumption | E1 / E2 / E3, bullish and bearish: within tolerance, equality, consumption, gap-through; internal 4 vs. External 6 ticks |
| Price records | E19: one price, internal consumed first, External later; confluence with and without a shared extreme |
| Delayed confirmation | E5 → E8 |
| Clusters | E6 (inner constituent consumed, cluster active); EQ inside a REQ; E7 (outermost move) |
| Ranges | E9; E10 (advance + opposite reselection); E11 (retained, UNBOUNDED); E12 (both sides in one bar); E20 (insufficient lower); E21 (unbounded upper reselected at an event) |
| Boundary assignments | E23 (extension leaves `BA1` pinned; `BA1` consumed while `xc_X` survives; `xc_X` becomes `BA2`); E24 (both consumed; advance skips); E25 (no extension; P-1) |
| Membership | E13 (boundary equality; historical level); levels leaving after an opposite reselection (E10) |
| Grades | E15 and a confluence case |
| Gaps and contracts | E14 → E22 (post-gap only re-establishment); E17 (roll); E16 (terminal id vs. new id, same price record) |
| Causality | E4; prefix replay (E18) |

**Validation pattern:** DEVELOPMENT only, without optimization or
VALIDATION / OOS data. It follows Market Structure MS-I3:

- the engine run;
- an independent reference replay;
- invariants;
- prefix replays;
- a local price-bearing HTML with a tracked price-free manifest.

---

## 9. Dependencies and proposed implementation sequence (not authorized)

| Frozen component | Use | Not changed |
|---|---|---|
| External 3.1 (D-134) | Boundary candidates and price-record External objects (derived consumption view); EQ/REQ grammar; member / structure envelope | Rules, tables, ids |
| Swing 3.2 (D-135 – D-138) | Swing atoms (explicit 2/2) | Detector, ids, availability |
| Market Structure 3.MS (D-139 – D-142) | §G.2a adapter and batch conventions (not close-beyond) | Engine, outputs |
| Continuity / M3 / M7A | Schedule, segments, transition logs | Unchanged |

| Step | Content |
|---|---|
| IL-I0 | **DONE (2026-10-06):** design approved; D-143 – D-147 registered |
| IL-I1 | **DONE (`683da5a`):** shared consumption contract (§3.1) and External derived view, with tests |
| IL-I2 | **DONE (`e6cfbec`):** internal formation atoms and EQ/REQ (§3.2), with tests |
| IL-I3 | **DONE (`617e983`):** levels, price records, grades, ranges, memberships, lifecycles, active view (§3.3 – §3.9), with tests (E1–E25) |
| IL-I4 | **DONE — APPROVED / FROZEN (`52291d1`, review fixes `9dd62ca`; human visual approval 2026-10-07):** independent reference, IL-INV-1 – IL-INV-20, DEVELOPMENT validation, prefix replays, visual package |
