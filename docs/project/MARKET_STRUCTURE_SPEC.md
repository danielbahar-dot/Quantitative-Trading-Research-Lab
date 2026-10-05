# Generic Market Structure: Protected Swing, Structural Direction, Breaks, BOS, CHoCH — Design

**Status: DESIGN DRAFT rev 2.3 (2026-10-05).**

- **Within-contract semantic review: COMPLETE** (2026-10-05).
  - D1–D17, K-1 … K-14, N-1, N-3 and the rev 2.2 corrections apply.
  - Same-close target admission after a failed establishment (T-1) is
    **APPROVED (final, design authority, 2026-10-05)** (§E.6a, §K.2b).
- **The full specification remains a DESIGN DRAFT** pending:
  - contract-roll treatment (N-2 and the pure-roll reset onset, §G.0);
  - final approval and D-number registration (MS-I0).
- No implementation or freeze is authorized. Continuous or stitched
  structure is out of scope for this phase.

**Rev 2.2 corrections** (review findings 1–5; approved semantics preserved;
contract-roll treatment still deferred):

1. **Retained protection identity** (§C.4, §D.2, §E.7, §G.1, H.1).
   - PROTECTION keeps its `role_id`, `assigned_at` and promotion-event
     parent while it is retained.
   - Only the promotion of a different, strictly tighter swing creates a
     replacement assignment.
   - TARGET stays associated with the current expansion leg.
2. **H.8 replaced** with a realizable OHLC case. Under the frozen Swing
   contract, earliest eligibility and earliest source **never diverge**
   for same-orientation swings (§E.2a L0′). The N-1 rule is kept
   unchanged.
3. **H.5–H.6 rebuilt** from one OHLC sequence. The rev 2.1 anchor
   contradiction and H.5's confirmation-order slip are removed.
4. **Failed-establishment reselection** (§E.6a).
   - It is proved that no previously ignored target survives a failure.
     All of them are breached by the failing close.
   - The waiting rule needs no new boundary.
5. **Explicit OHLC sequences** (§H.0, H.1, H.5–H.6, H.8).
   - Swing spans come from the frozen detector core.
   - The derived outcomes were checked by a scratch-only script (§I.0).

**Rev 2.1 review outcomes:**

- **N-1 APPROVED:** eligibility-order ties (§E.1).
- **N-2 DEFERRED:** combined gap / contract-change provenance, pending the
  contract-roll review (§G.0, §G.2).
- **N-3 APPROVED:** parent-dependent candidate-target assignments (§C.4,
  §E.4).
- **N-4:** 3.MS draft numbering, sequenced before Internal Liquidity. This
  is administrative only.
- **N-5:** the trigger reference is the completed observation's `BAR_SPAN`,
  or the continuity onset (§C.7).
- §G.0 separates **closed within-contract semantics** from **deferred
  contract-roll treatment**.

- Not approved, not implemented and not frozen. No implementation is
  authorized.
- **Approved semantics:**
  - D1–D17 (handoff), unchanged except where refined by the approved
    K-decisions K-1 … K-14 (design review, 2026-10-05; mapping in §K.1);
  - K-12 makes BOS and CHoCH **Generic Market Structure** classifications,
    explicitly versioned.
- **Rev 2:**
  - applies K-1 … K-14;
  - corrects the freshness timestamp rule (§E.5);
  - specifies batch post-close processing for same-timestamp inputs (§F);
  - makes candidate reseeding a deterministic rescan (§E.2–§E.4);
  - separates gap and contract provenance (§G.2–§G.3);
  - separates natural identity from run identity (§C.8);
  - separates mathematical arguments, planned tests and executed tests
    (§I).
- **Executed for this design:** none. No code, tests or DEVELOPMENT runs
  exist for this feature family (§I.0).
- **In scope:**
  - Protected Swing, Structural Direction and the neutral Swing-referenced
    Structure Break;
  - BOS and CHoCH;
  - establishment, continuation, invalidation and reset.
- **Deferred:**
  - MSS (D17), including any displacement, FVG or liquidity dependency;
  - displacement, FVG and IFVG;
  - Internal Liquidity and the shared liquidity lifecycle;
  - the internal / external structural hierarchy;
  - strategies, orders and execution.

---

## A. Observed repository status and compatibility findings

### A.1 Repository state (observed 2026-10-05)

| Item | Observation |
|---|---|
| `main` | `0d7b7b18660b16d412a781a24bc7a417ebb5d437` (PR #13 merge) |
| Working branch | `market-structure-design`, from `main`; design files uncommitted |
| Agent instructions | No `AGENTS.md`. `CLAUDE.md` is the operating file, with continuity set `MEMORY.md`, `docs/project/WORK_PROGRESS.md` and `docs/project/DECISION_LOG.md` |
| **Swing Structure 3.2** | **APPROVED / FROZEN (2026-10-05), merged** (PR #13). Spec: `docs/project/SWING_STRUCTURE_SPEC.md`; D-135–D-138 |
| Swing code | `src/market_structure/swing.py` (contract), `src/market_structure/swing_detector.py` (`build_swing_points`, 1m / 5m / 15m / 1H / 4H / 1D), `src/market_structure/swing_audit.py` (audit only) |
| Swing baseline | 119,381 DEVELOPMENT swings (2/2 reference). Fingerprint `b6876266800d56b3421dbfb5e4a4aa50b83140acdd409390d28b5f75427c218f` |
| Continuity | `src/data/continuity.py` (`continuity_segments`, `BREAK_PRECEDENCE`, `ContinuityError`; D-137) |
| Timeframes | `src/data/timeframes.py` (`build_timeframe`, `expected_timeframe_schedule`, `validate_source_bars`) |
| Instruments | `src/data/instruments.py` (exact `Decimal` `tick_size`, `is_tick_aligned`) |
| M6 | `src/features/level_interactions.py`; spec `docs/project/M6_LEVEL_INTERACTIONS_SPEC.md` (D-126 / D-127); frozen |
| M7A / M7B | `src/state/contract.py` (D-129–D-131); `src/signals/contract.py` (D-132) |
| Governance | D-133 and ROADMAP row 4 recorded "MSS / BOS classification open". K-12 resolves this for BOS / CHoCH; the reconciliation is recorded in `DECISION_LOG.md` and `ROADMAP.md` (§K.3) |

### A.2 M6 incompatibilities (K-9), with concrete examples

The frozen M6 rules are in `src/features/level_interactions.py`, lines 8–35
and 154–253.

**1. Approach-relative `close_through` versus absolute D1.**

- M6 evaluates a level upward only when the bar **opens** at or below it.
  Take an UPPER level (target swing high) at 110.00, tick 0.25, so
  `f = c = 440` ticks.
- **Bar:** O = 110.50, H = 111.25, L = 110.25, C = 111.00.
- **M6:** O ≥ f+1, so `approach_side = ABOVE` and the bar is evaluated
  **downward**:
  - `close_through` = C ≤ c−1 = 109.75 → **False**;
  - `touch` = Lo ≤ f = 110.00 → **False**.

  M6 reports no interaction.
- **D1:** the completed bar closes strictly above 110.00 (C = 111.00), so
  it **is** a structural break.

**2. Fixed `bar_interval` versus actual bar geometry.**

- M6 derives `bar_start = bar_end − bar_interval` (lines 181–189) and
  pairs bars by `bar_end ≥ available_at`.
- **4H session-truncated bucket** (M3): `bar_start` 14:00, `bar_end` 17:00
  ET. Take a 4H swing confirmed by the 10:00–14:00 bar, so `available_at` =
  14:00.
  - **Actual:** `bar_start` 14:00 ≥ 14:00, so the truncated bar is
    **eligible** (D9).
  - **M6** with `bar_interval = 4h`: `bar_start` = 13:00 < 14:00 →
    `PENDING_LEVEL`, and the break would be lost.
- **1D on a verified early close** (13:00): M6 with a fixed 1-day
  interval puts `bar_start` at 13:00 the previous day, instead of the
  actual 18:00 session open. Eligibility comparisons are therefore made
  against the wrong instant.

**Decision (K-9).** A narrow native `swing_breaks` computation (§C.2) that:

- uses the actual observation geometry (`bar_start` / `bar_end` from the
  M3 or canonical 1m frame);
- uses exact integer ticks (M2);
- reuses shared continuity, canonical times and SourceRefs.

M6 stays unchanged. It remains optional wick / touch interaction evidence
on fixed-interval timeframes only (D8).

### A.3 M7A constraints adopted

- **No self edges.** BOS keeps direction, so BOS is a role transition plus
  an event, never a direction transition.
- **One transition per entity + namespace per causal event**, with
  strictly increasing keys. An entity's availability must be `≺` its first
  transition. Unsequenced bar events at one `bar_end` cannot chain on one
  entity.
- Bar consumers see records with `available_at ≤ bar_start`
  (`materialize_state_to_bars`).
- Entity frames have fixed columns (`entity_id`, `available_at`,
  `valid_from`, `valid_until`, `instrument_id`, `contract_scope`,
  `contract`). Episode and role metadata therefore live in module tables
  keyed by `entity_id`.

---

## B. Dependency diagram (one timeframe, one definition)

```text
canonical 1m bars ─► target-timeframe observations (1m direct | M3 5m–1D) ─► shared continuity segments + break rows
        │                                                                          │
        ▼                                                                          │
 swing_points (frozen)                                                             │
        │                                                                          │
        ├─► NEUTRAL BREAK EVIDENCE  swing_breaks  (first close strictly beyond each │
        │   swing, same segment, bar_start ≥ swing.available_at; actual geometry)   │
        ▼                                                                          ▼
 PRE-STATE S_N  = state with available_at ≤ s(N)           continuity onset / reset (§G.2)
        │
        ▼   at e(N): ONE post-close batch (§F)
   (a) CLASSIFY bar N against S_N → ESTABLISHMENT | BOS | CHOCH | (D16 anomaly) | none
   (b) BREACH UPDATE: swings closed beyond at N become permanently ineligible (K-6)
   (c) ADMIT all swings with available_at == e(N) (zero, one or several)
   (d) SELECT the final post-close roles F_N  (pure rescan, deterministic total order)
   (e) MATERIALIZE diff(S_N roles, F_N roles): exits of old roles + new role entities,
       one direction transition at most, events — all stamped e(N)
        ▼
 S_{N+1}

 Optional adapter: structure_events ─► M7B Signals (structure.established / .bos / .choch).
 Cross-timeframe readers: HTF.available_at ≤ LTF.bar_start; reference HTF ids, never copy.
```

---

## C. Objects, contracts, identities and provenance

Conventions:

- ids are a prefix + full SHA-256 of canonical JSON (`ensure_ascii=False`,
  `separators=(",",":")`);
- times use M7 `canonical_time` (UTC, nanoseconds);
- prices are compared as exact integer ticks (M2 `tick_size`); there is
  no buffer and no tolerance;
- `pos(o)` is an observation's index within its continuity segment.
  `bar_end` is strictly increasing in `pos`.

### C.1 `StructureDefinitionSpec` (frozen dataclass)

| Field | Rule |
|---|---|
| `definition_version` | e.g. `structure-v1`. It fixes D1–D17 and K-1 … K-14 semantics; there are no free parameters |
| `break_definition_version` | e.g. `swing-break-v1` (§C.2) |
| `swing_definition` | An explicit `SwingDefinitionSpec`. 2/2 is only the validation reference |

### C.2 `swing_breaks` — neutral break evidence (Interaction layer, K-9)

**One row per swing that is ever closed strictly beyond inside its own
continuity segment**: the **first** such observation only. Later closes
are irrelevant (K-6: breach is permanent).

| Column | Rule / provenance |
|---|---|
| `break_id` | **Natural id:** `sb_` + SHA-256(`break_definition_version`, `swing_id`, `observation_ref`) |
| `observation_ref` | The breaking observation, as SourceRef `BAR_SPAN:<instrument>\|<contract>\|<timeframe>\|<bar_end_utc>\|<bar_end_utc>` (single-observation span; the same format as Swing, D-138) |
| `swing_id`, `swing_ref` | The referenced swing and its `BAR_SPAN` source ref |
| `timeframe`, `orientation` | UPPER: close above the level; LOWER: close below |
| `bar_start`, `bar_end` | The observation's **actual** geometry |
| `event_at` = `available_at` | `bar_end`: a completed-bar event; the exact intrabar time is unknown |
| `level_ticks`, `close_ticks`, `tick_size` | Reconstruction inputs. The comparison is `close_ticks > level_ticks` (UPPER) or `<` (LOWER) |
| `close_excess_ticks` | `\|close_ticks − level_ticks\|` > 0 |
| `instrument_id`, `contract_scope` (SPECIFIC), `contract` | The swing's, equal to the observation's |
| `break_definition_version` | — |

**Rule (D1 / K-9).** A break requires all of:

- the observation lies in the swing's segment;
- `bar_start ≥ swing.available_at`;
- a strictly-beyond close.

Equality is not a break, and a wick never is. Optional audit: M6 rows
(`M6_INTERACTION:<level_id>@<bar_end>`), on fixed-interval timeframes
only.

### C.3 `structure_episodes` (State subject; M7A entity in `structure.direction`)

One episode per (timeframe, definition, continuity segment).

| Column | Rule |
|---|---|
| `episode_id` | `se_` + SHA-256(`definition_version`, swing-definition triple, `instrument_id`, `contract_scope`, `contract`, `timeframe`, `canonical(first_bar_end)`) |
| `first_bar_end` | First valid observation of the segment; it is the entity `available_at` |
| `opening_cause` | `DATA_START` \| `DATA_GAP_REESTABLISHMENT` \| `CONTRACT_CHANGE_REESTABLISHMENT` (§G.3). Which cause applies at a combined gap + roll boundary is **DEFERRED (N-2, §G.0)** |
| `opening_ref` | Null for `DATA_START`; otherwise the preceding `CONTINUITY_BREAK:<timeframe>\|<prev_contract>\|<canonical(onset)>` |
| `opening_contract_changed` | Boolean from shared continuity. Whether it is the provenance carrier at combined boundaries is **DEFERRED (N-2)** |
| `contract`, `instrument_id`, `contract_scope` (SPECIFIC) | The segment's |

There is no `valid_until` (no hindsight bound). An episode ends only
through a terminal `RESET` transition (§D.1).

### C.4 `structure_roles` — versioned swing-role assignments (K-10)

Each role assignment is a separate State entity that references a
canonical swing. Protected Swing is the `PROTECTION` role, not a swing row.

| Column | Rule |
|---|---|
| `role_id` | `sr_` + SHA-256(`episode_id`, `role_kind`, `swing_id`, `parent_key`, `canonical(assigned_at)`) |
| `role_kind` | `BULL_ANCHOR`, `BEAR_ANCHOR`, `BULL_CANDIDATE_TARGET`, `BEAR_CANDIDATE_TARGET`, `PROTECTION`, `TARGET` |
| `parent_key` (in identity) | Anchors: `scope_key` (§E.3). **Candidate targets: their parent anchor assignment's `role_id` (N-3 approved).** **`PROTECTION`: the `event_id` of the event that promoted this swing to protection** (the ESTABLISHMENT, or the BOS that replaced the previous protection). It is fixed for the life of the assignment and is **not** updated by later BOS events (rev 2.2). `TARGET`: the `event_id` of the expansion (ESTABLISHMENT / BOS) that opened the current leg |
| `parent_role_id` (provenance) | Candidate targets: the parent anchor `role_id`, the same value as `parent_key`, kept as an explicit column. Null for other kinds |
| `direction_context` | `BULLISH` / `BEARISH` |
| `assigned_at` | The batch instant `e(N)` (entity `available_at`) |
| `assigned_by_refs` | The batch trigger (§C.7, N-5) plus supporting refs, e.g. `STRUCTURE_BREAK:<break_id>`, `SWING:<swing_id>`, `STRUCTURE_EVENT:<event_id>` |
| Pinned swing facts (K-13) | `swing_price_ticks`, `swing_available_at`, `swing_source_at`, `swing_source_end_at` |
| `episode_opening_cause` | Copied from the episode (D12 / K-5 provenance) |

**Persistence rule.** A role persists (keeps its `role_id`) across a batch
iff the final selection contains the same (`role_kind`, `swing_id`,
`parent_key`). Otherwise the old role exits and a new entity is created
(§F.2).

**Retained protection (rev 2.2; D3 / D7 / D15).**

- PROTECTION is a **history marker**, not a rescan result (§E.2). `F_N`
  carries the active protection forward **with its existing `swing_id` and
  promotion parent**, so it persists with the same `role_id` and
  `assigned_at`.
- Only three things end it:
  - **REPLACED:** a BOS whose `P*` is a **different** swing, strictly
    tighter than the current protection, is promoted. The new assignment's
    parent is that BOS's `event_id`.
  - **BROKEN:** a CHoCH.
  - **ENDED:** a RESET.
- **A BOS without replacement** (no `P*`, or `P*` not strictly tighter)
  writes **no** protection transition and creates no new protection
  entity.
  - The BOS event's `role_refs` lists the retained protection `role_id`
    as read.
- **`P*` at a BOS can never be the current protection's own swing.**
  - The current protection was eligible at `s(E)`, so its
    `source_end_at < s(E)`.
  - The consumed target has `source_end_at ≥ e(E)` (K-1).
  - So the current protection is never after the consumed target, while
    `P*` must be.
  - "Re-promoting" the same swing therefore cannot occur.
- **TARGET**, by contrast, belongs to one expansion leg.
  - At a BOS it is CONSUMED.
  - The next leg's target is a new entity whose parent is that BOS.

**Parent dependency (N-3 approved).**

- A candidate-target assignment depends on its parent anchor assignment.
- When the anchor assignment ends (SUPERSEDED, BROKEN or ENDED), the
  dependent candidate-target assignment ends (ENDED) in the same batch.
- If the same canonical swing remains selected as the candidate target,
  a **new** candidate-target assignment is created, referencing the new
  anchor role (`parent_key` / `parent_role_id`).
- Only the final assignments of each same-close batch are materialized
  (§F.2).

**Uniqueness (K-10).** In any post-batch state, per episode, there is at
most one active role per `role_kind`:

- while UNDEFINED: anchors and candidate targets, at most one each per
  side;
- while established: at most one `PROTECTION` (exactly one) and at most
  one `TARGET`.

### C.5 `structure_events` — classified point events (module-owned; K-12, K-14)

| Column | Rule |
|---|---|
| `event_id` | **Natural id:** `sx_` + SHA-256(`definition_version`, `episode_id`, `kind`, `direction`, `break_id` \| `reset_ref`) |
| `kind` | `ESTABLISHMENT`, `BOS`, `CHOCH`, `RESET` |
| `direction` | **The break direction** (K-14): close above → `BULLISH`, close below → `BEARISH`. RESET → null |
| `pre_direction` / `post_direction` | e.g. CHoCH of bullish protection: `pre = BULLISH`, `direction = BEARISH`, `post = UNDEFINED` |
| `event_at` = `available_at` | `bar_end` of the classified observation (RESET: the onset, §G.2) |
| `break_id`, `swing_id` | The broken reference: candidate target, target or protection |
| `reset_reason` | `DATA_GAP` \| `CONTRACT_CHANGE` (RESET only) |
| `role_refs`, `transition_refs` | Canonical tuples of the roles read / created / exited and the M7A `transition_id`s produced |
| `classification_version` | = `definition_version` (explicit versioning, K-12) |
| `episode_opening_cause` | Provenance |

**M7B adapter (optional, later).** `structure.established`,
`structure.bos` and `structure.choch` signals, with:

- `subject_kind = structure_episode`, `subject_id = episode_id`;
- `trigger_ref = STRUCTURE_BREAK:<break_id>`;
- `source_refs = transition_refs`;
- `direction` = the event's break direction.

The adapter publishes; it never defines. Future MSS may reference
`event_id` / `break_id` (D17).

### C.6 `structure_anomalies` — invariant-violation evidence (K-11)

One row per detected invariant violation, e.g. `DUAL_ESTABLISHMENT`
(D16), with:

- `episode_id`, `bar_end`, `anomaly_kind`;
- both evidence sets: anchors, targets, pullbacks and `break_id`s,
  canonical tuples.

**Any row fails machine validation and blocks approval or freeze.** It is
not a runtime exception (§E.8).

### C.7 M7A namespaces

**`structure.direction`** (entity = episode)

- States `UNDEFINED` (initial), `BULLISH`, `BEARISH`, `RESET` (terminal).
- Edges:
  - `UNDEFINED→BULLISH`, `UNDEFINED→BEARISH`;
  - `BULLISH→UNDEFINED`, `BEARISH→UNDEFINED`;
  - `{UNDEFINED, BULLISH, BEARISH}→RESET`.
- There is no `BULLISH↔BEARISH` edge (D5).
- `reason_code`: `ESTABLISHED`, `PROTECTION_BROKEN`, `DATA_GAP`,
  `CONTRACT_CHANGE`.

**`structure.role`** (entity = role assignment)

- `ACTIVE` (initial). Terminal states: `CONSUMED`, `SUPERSEDED`,
  `REPLACED`, `BROKEN`, `RETIRED`, `ENDED`.
- Each role has at most **one** exit transition.

**Transitions and trigger reference (N-5).**

The rule is deliberately the simplest one compatible with M7A, with no new
provenance framework. Every transition has exactly one `trigger_ref`,
chosen by the **causal source event** of its batch.

- **Observation batch** (classification, breaches, admissions and
  rescans at `e(N)`):
  - `trigger_ref = BAR_SPAN:<instrument_id>|<contract>|<timeframe>|<canonical e(N)>|<canonical e(N)>`.
    This is the completed observation N, as a single-observation span in
    the existing Swing `BAR_SPAN` format (D-138), identical to
    `swing_breaks.observation_ref`.
  - Everything in the batch happens because observation N completed:
    - its close is classified;
    - its close breaches swings;
    - the swings admitted at `e(N)` are confirmed **by** observation N
      (L0).

    A single deterministic trigger per batch is therefore exact.
- **Reset** (§G.2):
  - `trigger_ref = CONTINUITY_BREAK:<timeframe>|<contract>|<canonical t_r>`.
  - A missing expected observation has no `BAR_SPAN` of its own, so the
    shared-continuity break at its onset is the source event.
  - This is the same ref as the episode's `opening_ref` and the RESET
    event's `reset_ref`.
- **Causal timestamp:** `transition_at = available_at = e(N)`, or `t_r`
  for a reset, which equals the trigger's own timestamp. Sequences are
  null.
- **Supporting `source_refs`** (canonical, sorted, unique, never repeating
  the trigger):
  - `STRUCTURE_BREAK:<break_id>` for the classified break, if any;
  - `SWING:<swing_id>` for the swing of the transitioning role, and for
    the admitted swings that caused the selection change;
  - `STRUCTURE_EVENT:<event_id>` for the classification event, if any.
- **M7A compatibility:**
  - "one transition per entity + namespace + trigger" holds, because each
    entity has at most one transition per batch (§F.2);
  - different entities share the batch trigger, which M7A allows.
- **M7B adapter:**
  - `trigger_ref = STRUCTURE_BREAK:<break_id>`, the most specific cause
    of the classified event;
  - `source_refs` = the `transition_refs`.

  B.0 forbids repeating the trigger in `source_refs`, and this is
  respected.

### C.8 Natural identity versus run identity (K-13)

**Natural ids** (`sb_`, `se_`, `sr_`, `sx_`) are deterministic functions
of the semantic source identity. They contain no run, wall-clock or
data-version fields.

**Run identity.** Every output table carries `run_id` and is stored per
run. The run manifest records:

- the bar input fingerprint (canonical 1m slice and the derived frame per
  timeframe);
- the swing input fingerprint (per timeframe);
- `StructureDefinitionSpec` and the Swing definition versions;
- the session spec and calendar overrides (schedule) and the instrument
  metadata;
- the code version.

**Revisions.**

- A revised input yields a **new `run_id`**. The same natural id may then
  carry different pinned facts: for example, the same `swing_id` with a
  revised price (the Swing id excludes price), or the same `break_id` with
  a different `close_excess_ticks`.
- Each row also carries `fact_hash` = SHA-256 of its pinned, price-bearing
  facts, so diffs between runs are explicit.
- **Prior runs are preserved; nothing is patched in place.** Natural ids
  are unique within a run, not across runs.
- Only affected (timeframe, definition) structures are recomputed.

---

## D. State-transition tables

### D.1 `structure.direction`

| From | Batch at e(N) (pre-state `S_N`) | To | reason | Event (direction / pre / post) |
|---|---|---|---|---|
| UNDEFINED | Exactly the bull candidate qualifies (§E.6) | BULLISH | ESTABLISHED | ESTABLISHMENT (BULLISH / UNDEFINED / BULLISH) |
| UNDEFINED | Exactly the bear candidate qualifies | BEARISH | ESTABLISHED | ESTABLISHMENT (BEARISH / UNDEFINED / BEARISH) |
| UNDEFINED | Both qualify (K-11 fallback) | — (stays UNDEFINED) | — | No event; a `DUAL_ESTABLISHMENT` anomaly row |
| BULLISH | Close < active PROTECTION | UNDEFINED | PROTECTION_BROKEN | CHOCH (BEARISH / BULLISH / UNDEFINED) |
| BEARISH | Close > active PROTECTION | UNDEFINED | PROTECTION_BROKEN | CHOCH (BULLISH / BEARISH / UNDEFINED) |
| BULLISH / BEARISH | Close beyond active TARGET | — (no direction transition) | — | BOS (same / same / same) |
| any non-RESET | Continuity onset (§G.2) | RESET | DATA_GAP \| CONTRACT_CHANGE | RESET (null) |

### D.2 `structure.role` exits

When several causes apply in one batch, the first in this order is
recorded: `CONSUMED > BROKEN > REPLACED > RETIRED > SUPERSEDED > ENDED`.

| Role | Exit | Cause |
|---|---|---|
| `*_ANCHOR` | BROKEN | Close beyond the anchor (D14 invalidation) |
| | SUPERSEDED | A strictly more extreme eligible in-scope swing is admitted (D14) |
| | ENDED | Establishment (either side), CHoCH-rescope, or RESET |
| `*_CANDIDATE_TARGET` | CONSUMED | It is the broken target of an ESTABLISHMENT (it becomes the consumed baseline, D10) |
| | RETIRED | Closed beyond without qualifying establishment (K-4 / K-8), or in a D16 anomaly |
| | SUPERSEDED | A strictly more extreme target is selected under the **same** anchor (K-7) |
| | ENDED | Its anchor exits, the other side establishes, or RESET |
| `PROTECTION` | BROKEN | CHoCH (D5) |
| | REPLACED | A BOS whose deepest pullback `P*` is a different, strictly tighter swing, promoted as the new protection (D3 / D7 / D15) |
| | ENDED | RESET |
| | *(no exit)* | A BOS without replacement. The role keeps its `role_id`, `assigned_at` and promotion parent (§C.4, rev 2.2) |
| `TARGET` | CONSUMED | BOS (D7) |
| | SUPERSEDED | A strictly more extreme since-expansion target (D4 / K-7) |
| | ENDED | CHoCH or RESET |

The consumed-target baseline (D10) is the swing of the most recent
`CONSUMED` candidate-target or target role in the current established leg.
It is derived from the role history.

---

## E. Selection algorithms (pure functions of facts + history markers)

### E.1 Eligibility, ordering and ties

A swing `X` is **eligible at instant t** (for post-batch selection,
`t = e(N)`; for classification of N, `t = s(N)`) iff:

- (a) `X` is in the episode's segment;
- (b) `X.available_at ≤ t`;
- (c) `X` is **unbreached at t**: its `swing_breaks` row, if any, has
  `bar_end > t` (K-6). A breached swing never regains eligibility.

**Span order** (all equivalent, because `bar_end` strictly increases in
`pos`):

- "A after B" ⇔ `A.source_at > B.source_end_at` ⇔
  `pos(first(A)) > pos(last(B))`;
- "A reaches E" ⇔ `A.source_end_at ≥ e(E)` ⇔ `pos(last(A)) ≥ pos(E)`.

**Deterministic total orders** (never input row order):

- **Persistent anchors and targets** (D11 / D14; **N-1 approved**): the
  most extreme price wins.
  - At equal price, the **first eligible** reference is retained.
    Eligibility order is causal availability (`available_at`), never row
    order.
  - For simultaneous eligibility (equal `available_at`), the tie-break is
    the earliest source span (`source_at`, then `source_end_at`), then
    `swing_id` as the final determinism key.
  - An equal-price swing that becomes eligible later never displaces the
    incumbent, which reproduces D14's "replace only with strictly lower".
- **Pullbacks / protection candidates** (D11, unchanged): the deepest
  price wins, then the earliest source span (`source_at`, then
  `source_end_at`), then `swing_id`.
- **Rescans reproduce these rules without touching the past.**
  - A historical rescan (§E.2, §E.3) applies the same orders to the
    eligible facts at the batch instant, so it selects exactly what the
    incremental "first eligible, replace only if strictly more extreme"
    rule would.
  - It only determines the **post-batch** state.
  - Previously materialized assignments keep their `role_id`s, exits and
    timestamps (§F.2). Earlier classifications are never revised.

### E.2a Confirmation order versus source order (lemma L0)

**Setting:** one timeframe, one segment, one Swing definition, so R is the
same for every swing.

- `available_at = bar_end(pos(last plateau observation) + R)`.
- **L0:** if `Y` is after `X` (non-overlapping), then
  `X.available_at < Y.available_at`, because
  `pos(last X) < pos(first Y) ≤ pos(last Y)`.
- **Consequences:**
  - (i) Confirmation order can differ from source order **only for
    overlapping spans**, and overlapping spans are never in an "after"
    relation. Every reference that must be after another (target after
    anchor, pullback after target) therefore always confirms after it.
  - (ii) Swings admitted in the **same** batch must share their last
    plateau observation (e.g. an outside bar, or a long plateau ending on
    the bar where an opposite swing sits), so they overlap.
  - (iii) A **delayed plateau** (a long plateau whose first observation
    is early) confirms by its *last* observation. Freshness uses its
    *first* observation (§E.5), and "after" relations use both ends.
- **L0′ (same orientation; rev 2.2).**
  - Two distinct UPPER swings never overlap (L4: distinct maximal equal-high
    runs are disjoint), so one is strictly after the other. By L0 the
    earlier span then has strictly earlier `available_at`.
  - Equal `available_at` would require the same last plateau observation,
    hence the same maximal run, hence the same swing. LOWER swings behave
    identically.
  - **Consequence for N-1:**
    - for anchors and targets (always one orientation per role kind),
      "first eligible" and "earliest source span" select the **same**
      swing under the frozen contract;
    - simultaneous eligibility of two distinct same-orientation swings
      cannot occur.
  - The approved N-1 order is kept unchanged as the deterministic rule.
    No case exists in which it differs from source order, and none is
    invented here (H.8).
- L0 removes ordering ambiguity but is **not relied upon** for
  correctness. Selections still rescan every eligible fact (§E.2), so the
  design stays correct if R ever differed (e.g. a future definition).

### E.2 Why selection is a rescan

- All selections below are **recomputed from the full eligible fact set**
  at the batch instant, plus history markers:
  - direction;
  - the active protection;
  - the consumed baseline;
  - the last expansion `E`;
  - `scope_key` and the last CHoCH bar `X`.
- **Consequences:**
  - (1) Facts are never lost because confirmation order differs from
    source order. A delayed plateau confirmation is found by source order.
  - (2) The result is independent of iteration order.
  - (3) Rescans only shape the post-batch state, so classifications at or
    before N are never changed (D9).
- **Equivalence to the incremental D13 / D14 wording.**
  - The minimum, with "earliest eligible" ties, over unbreached in-scope
    lows equals "start from the first eligible low, replace only with a
    strictly lower one".
  - Breached lows are excluded in both.
  - After invalidation the rescan set is empty (§E.4), which is K-2.

### E.3 Candidate scope (D14, K-3)

- `scope_key` is `episode_id` while no CHoCH has occurred in the episode.
  Otherwise it is the `event_id` of the latest CHoCH.
- **In-scope anchors:**
  - before any CHoCH: every eligible swing of the episode's segment;
  - after a CHoCH that broke protection `P_b`: eligible swings with
    `source_at ≥ P_b.source_at` (K-3), including swings admitted later.
- Candidate targets and pullbacks are "after the anchor", so they are
  automatically in scope.

### E.4 Candidate selection while UNDEFINED (bull shown; bear is the exact mirror)

```text
anchor_bull(t)  = argmin_price { LOWER X eligible at t, in scope }              (anchor order)
ctarget_bull(t) = argmax_price { UPPER X eligible at t, X after anchor_bull(t) } (target order)
```

- **Anchor replacement restarts the sequence:** `ctarget` is recomputed
  after the new anchor's span. The old candidate-target role exits
  `ENDED`; its parent changed.
- **Anchor invalidation (D14):** `c(N) < anchor.price` → the anchor is
  BROKEN.
  - Every in-scope low eligible at `s(N)` is ≥ the anchor > `c(N)`, so
    every one is breached by bar N.
  - Lows admitted in the same batch (`available_at = e(N)`) are **not**
    breached by N, because `bar_start(N) < available_at`. They are the
    "next eligible admitted confirmations" and may seed in this very
    batch.
  - Otherwise the rescan set is empty until a later admission (**K-2**).
  - **Consistency with K-3:** after a CHoCH, the reseed uses the same
    rescan restricted to scope.
  - Swings admitted later are in scope (their `source_at` is later), so
    both paths are "restart from empty, then seed from the next eligible
    fact".
- **Target replacement (K-7):** a strictly more extreme `ctarget` under
  the same anchor → the old role is SUPERSEDED. The pullback interval
  becomes "after the new target's span". An equal price keeps the
  incumbent and does not restart the interval.

### E.5 Pullback selection — deepest first, then qualify (D15, K-4) and freshness (D6, corrected)

For a reference target `R` (a candidate target for establishment, or the
consumed target for BOS) and break observation N:

```text
P* = argmin_price { LOWER Y eligible at s(N), Y after R }   (pullback order; earliest source span on ties)
```

- `available_at ≤ s(N)` implies `Y.source_end_at < s(N)`, so D3's "before
  the break bar starts" holds automatically.
- **No filtering by freshness or qualification happens before the
  argmin** (D15 / K-4).

**Freshness (D6, applies only to establishment after a CHoCH at
observation X).**

- `P*` is fresh ⇔ `pos(first(P*)) > pos(X)` ⇔ `P*.source_at > e(X)`.
- `source_at` is the **completion** of the first plateau observation
  (frozen Swing contract), and `bar_end` strictly increases in `pos`.
- The immediately following observation X+1 has `bar_end > e(X)` (its
  `bar_start ≥ e(X)`, equal when contiguous), so a pullback starting at
  X+1 **is fresh**.
  - (The rev 1 prose "starts after the CHoCH bar ends" would wrongly
    exclude X+1, because `bar_start(X+1) = e(X)`. It is corrected here.)
- Confirmation before the expansion bar starts is
  `P*.available_at ≤ s(N)`, already required.
- **A stale `P*` blocks establishment** (K-4). No shallower fresh swing is
  substituted.

### E.6 Classification of observation N while UNDEFINED

For each side, against `S_N`:

1. **Invalidation:** `c(N)` beyond the anchor (bull: `<`) → the anchor is
   BROKEN, and nothing else happens for that side at N.
2. **Otherwise,** if an active `ctarget` exists and `c(N)` is strictly
   beyond it, the side **qualifies** iff `P*` exists (§E.5) and all of the
   following hold:
   - `P*` is strictly beyond the anchor (bull: `P*.price > anchor.price`;
     D2 / D15);
   - if a CHoCH has occurred in this episode, `P*` is fresh (§E.5).

   **Failure** → the `ctarget` is RETIRED (breached; K-4 / K-8), the
   unbroken anchor persists, and the side waits for a new eligible target.
   There is no retrospective establishment.
3. **Outcome:**
   - exactly one side qualifies → ESTABLISHMENT in its direction (§F);
   - both qualify → the **K-11 fallback**: stay UNDEFINED; both
     candidate targets are RETIRED (both were closed beyond); the
     unbroken anchors persist; a `DUAL_ESTABLISHMENT` anomaly row records
     both evidence sets; no directional event is emitted.

### E.6a Failed establishment, rescans and reseeding (rev 2.2; K-2, K-3, K-6, K-8)

**Question.** Rescans are unrestricted: they recompute from every eligible
fact (§E.2). K-8 retires the breached target, keeps the anchor and waits.
Can a candidate that the rescan previously ignored (eligible, unbreached,
not selected) be selected after a failure, so that the "wait" would in
effect be a reselection?

**Answer: no.** Under the frozen Swing rules and close-beyond semantics,
no such candidate survives the failing close. The argument follows; it is
not machine-checked. A worked case is H.6.

**Setting.**

- Failure at observation N on the bull side (bear mirrors): anchor `A`
  and candidate target `H` are active in `S_N`, `c(N) > H.price`, and the
  side does not qualify (no `P*`, `P*` not beyond `A`, or `P*` stale).
- Same segment and Swing definition throughout. Let `𝒰` be the UPPER
  swings eligible and unbreached at `s(N)`.

**Lemma L5 (opposite extremes; uses L1 / L1′).** If `U ∈ 𝒰` and `Lo` is a
LOWER swing eligible and unbreached at `s(N)`, then `U.price ≥ Lo.price`.

- **`Lo` after `U`:** every observation after `U`'s plateau and before N
  closes ≤ `U.price` (L1), and `Lo.price ≤` its own close.
- **`U` after `Lo`:** the mirror argument (L1′).
- **Overlap:** the shared observation has high ≥ low.

**R1 (the failed side's ignored candidates are destroyed).**

- Every `U ∈ 𝒰` after `A` has `U.price ≤ H.price < c(N)`, because `H` is
  the maximum.
- `U.available_at ≤ s(N) = bar_start(N)`, so N qualifies as `U`'s
  breaking observation (§C.2), and `U` is breached at N.
- By K-6 it never regains eligibility for **any** role. The set
  "previously ignored, unbreached candidates of the failed target" is
  therefore **empty at `e(N)`**.

**R2 (later admissions are new facts).** Take an UPPER swing `Z` admitted
at `e(N)` or later.

- **If `Z`'s plateau ends before N:** N lies in its right window
  (`Z.available_at ≥ e(N)`), so `Z.price ≥ high(N) ≥ c(N) > H.price`.
- **If `Z`'s plateau contains N:** its price is `high(N)`.
- **Otherwise** `Z` is after N.
- In every case `Z` was not eligible at `s(N)`, so `Z` is a **new
  eligible target** in the sense of K-8, never a resurrected one.
- **Same batch (T-1, APPROVED final, rev 2.3; §K.2b).** The timing follows the
  general classification-before-admission rule (§F.1, §F.3), not K-2
  alone. After a failed establishment at N:
  1. the breached candidate target is RETIRED at `e(N)`;
  2. swings confirmed at `e(N)` are admitted during the normal post-close
     batch;
  3. a newly confirmed target that is otherwise valid (eligible, after the
     anchor, and the rescan maximum) **may receive an assignment at
     `e(N)`**;
  4. it **cannot participate in the classification of N**, because N was
     classified against `S_N` before admission;
  5. it is usable only by an observation whose `bar_start` is ≥ both its
     `assigned_at` and the swing's `available_at`. That is the next
     observation N+1 at the earliest, since `s(N+1) ≥ e(N)`;
  6. the failed establishment is **never retrospectively revised**. No
     event, role exit or direction transition at or before `e(N)` changes.

**R3 (anchor or scope changes cannot reach older swings while
UNDEFINED).**

- Within an unchanged scope, every later bull anchor is either `A` itself
  or a LOWER swing admitted after `s(N)`.
  - `A` is the minimum of the in-scope eligible lows at `s(N)`. An older
    low can become the minimum only after `A` (or a lower successor) is
    closed beyond.
  - That close is beyond every older, higher in-scope low as well.
- By L0, a swing admitted after `s(N)` is never strictly before a swing
  eligible at `s(N)`. So an older UPPER swing is never "after" a later
  anchor and cannot be its candidate target.
- **A scope change needs a CHoCH, which needs an establishment after N.**
  - By L5, the opposite side cannot establish **at** N: a close above `H`
    is not below any unbreached LOWER swing.
  - After a later establishment and CHoCH, K-3's approved historical scope
    applies. It can only reach unbreached swings, so R1's breached
    candidates stay excluded (K-6).

**Consequences.**

- K-8's "wait for a new eligible target" needs **no** additional
  target-reselection boundary, and none is added.
- The unrestricted rescan and K-8 agree.
- Approved semantics are unchanged.
- **Side note:** L5 also shows directly that no close can be beyond both
  candidate targets at once. That is an alternative argument for D16
  (§E.8, A-1′).

### E.7 Continuation while established BULLISH (BEARISH mirrors)

Let `E` be the last expansion observation (establishment or BOS) and `B`
the consumed-target baseline swing.

```text
target(t) = argmax_price { UPPER X eligible at t :
                           X.source_end_at ≥ e(E)            (K-1, straddlers included)
                           and X after B                     (strict order after consumed span)
                           and X.price > B.price }           (D10 progression; equality fails)
```

Ties use the target order. A strictly more extreme admission is
SUPERSEDED (K-7). Nested swings are ignored (D4).

**Classification of N against `S_N`:**

1. `c(N) < PROTECTION.price` → **CHOCH**:
   - direction BEARISH; pre BULLISH; post UNDEFINED;
   - the protection is BROKEN and the target ENDED;
   - `scope_key :=` this CHoCH, and the candidates reseed in the same
     batch (§F, example H.5);
   - there is no opposite establishment on this observation (D5 / D6).
2. Else, if a `TARGET` is active and `c(N) > TARGET.price` → **BOS
   BULLISH**:
   - the target is CONSUMED (so `B :=` it) and `E := N`;
   - compute `P*` after the consumed target (§E.5, without freshness);
   - if `P*.price > PROTECTION.price` strictly → the protection is
     REPLACED by `P*` (a new PROTECTION entity, parent = this BOS);
   - else it is retained (D7 / D15): the **same entity**, with no
     transition, keeping its original `assigned_at` and promotion parent
     (§C.4).
3. **Exclusivity:** cases 1 and 2 cannot both hold at one close. That
   needs `PROTECTION < TARGET`, whose argument is in §I.1 (A-2).

### E.8 D16: argument for unreachability under the finalized rules, plus the fallback (K-11)

> **Claim.** Under §E.1–§E.6 (K-1 … K-8 included), no close qualifies
> both sides at once.

This is a mathematical argument, **not yet tested** (§I.0).

**Lemmas** (assumptions: same-timeframe, complete, in-segment
observations; frozen Swing confirmation rule; D14 anchor invalidation;
K-6 breach permanence):

- **L1 (UPPER).** If an UPPER swing `U` is unbreached at `s(N)`, every
  observation after `U`'s plateau and before N closes ≤ `U.price`.
  - Right-window and plateau observations have high ≤ `U.price`, so close
    ≤ high ≤ `U.price`.
  - Later observations before N would otherwise have produced a breach
    row.
- **L1′ (LOWER).** The mirror holds for LOWER swings.
- **L2.** While the bear anchor `A_s` is valid, every observation after
  `A_s` and before N closes ≤ `A_s.price`. This follows from D14 and L1.
  The bull anchor `A_b` mirrors this (closes ≥ `A_b.price`).
- **L3.** A LOWER swing `Y` whose source is after an unbreached UPPER `U`
  has `Y.price ≤ U.price`. Its low ≤ its own close, which is ≤ `U.price`
  by L1; or ≤ `A_s.price` by L2 when `U = A_s`.
- **L4.** Two UPPER swings never have overlapping spans. Equal adjacent
  highs form one maximal plateau. Two LOWER swings likewise never overlap.

**Argument.**

- Suppose bull qualifies with anchor `A_b`, target `H` and pullback `P_b`
  (with `A_b` < `H` < `P_b` in span order and `c(N) > H.price`), and bear
  qualifies with anchor `A_s` and target `L` (`c(N) < L.price`).
- All five swings are eligible at `s(N)`. By K-3 they are in the same
  scope, because each candidate's swings are at or after its anchor, and
  both anchors are in scope.
- **Case 1, `A_s` strictly before `P_b`.**
  - `P_b` is an eligible low after `A_s`, so `L ≤ P_b` (L is the minimum).
  - `P_b ≤ H` by L3.
  - Hence `c(N) > H ≥ P_b ≥ L`. This contradicts `c(N) < L`.
- **Otherwise, `A_s` is not strictly before `P_b`.**
  - Then `A_s` is strictly after `A_b`: by L4 its span cannot reach back
    across `H` unless `A_s = H`, and `A_s = H` is itself after `A_b`.
  - `A_s` is an eligible UPPER swing after `A_b`, so `H ≥ A_s` (H is the
    maximum).
  - `L` is after `A_s`, so `L ≤ A_s` by L3 / L2.
  - Hence `c(N) > H ≥ A_s ≥ L`. Contradiction.
- **Freshness** (§E.5) only removes qualifications, so it cannot create a
  dual one. The bear mirror is symmetric.

**Alternative argument A-1′ (rev 2.2; not machine-checked).**

- Dual qualification needs `c(N) > H.price` and `c(N) < L.price` for the
  two active candidate targets, which are both eligible and unbreached at
  `s(N)`.
- Lemma L5 (§E.6a) gives `H.price ≥ L.price`, so both inequalities
  cannot hold together.
- This argument uses neither anchors nor pullbacks.

**Fallback (K-11, retained even though it is argued unreachable).**

- Stay UNDEFINED, keep both evidence sets in `structure_anomalies`, and
  flag the invariant violation.
- No directional establishment, and no hard runtime error.
- Any anomaly fails machine validation (§I.3), blocking approval and
  freeze.

### E.9 Breach semantics (K-6)

- A breach belongs to the **`swing_id`**: the first strictly-beyond close
  at an observation with `bar_start ≥ available_at` in the swing's segment
  (§C.2).
- A breached swing is permanently ineligible for every role.
- A **later, distinct** swing at the same price is independently eligible,
  subject to all role rules. For example, it cannot be a target at a price
  equal to the consumed baseline (D10).

---

## F. Causal timing and post-close batch processing

### F.1 Order within a segment

Within a segment, observations are processed in `pos` order. For
observation N (`s(N)`, `e(N)`, `c(N)`):

```text
S_N := state with available_at ≤ s(N)                              (D9)
BATCH at e(N):
  (a) classify N against S_N            (§E.6 / §E.7; uses only facts eligible at s(N))
  (b) breaches at N (swing_breaks with bar_end == e(N)) join the breached set
  (c) admissions: all swings with available_at == e(N)
  (d) update history markers from (a): direction, protection, baseline, E, scope_key, X
  (e) F_N := final roles by rescan (§E.3–§E.7) at t = e(N) over eligible facts and markers
  (f) materialize diff(S_N, F_N)
```

### F.2 Materialization rules (K-10)

- **Exits:**
  - every role active in `S_N` and absent from `F_N` (by persistence key,
    §C.4) gets exactly **one** exit transition at `e(N)`;
  - the reason is taken from (a)–(e) using the §D.2 precedence;
  - the trigger is the batch's observation `BAR_SPAN` ref, with the
    specific causes in `source_refs` (§C.7, N-5).
- **New roles:** every role in `F_N` but absent from `S_N` becomes a
  **new entity** with `available_at = e(N)`. It has no transition at
  `e(N)`.
- **Persisting roles** get nothing.
- **Direction:** at most one transition at `e(N)`, from (a) only.
  Admissions and rescans never change direction.
- **Hence:** no entity is created and exited at the same timestamp,
  intermediate selections are never materialized, and each entity gets at
  most one transition per instant. Both are M7A-compatible.
- **Iteration-order independence:** `F_N` is a pure function of sets
  under total orders (§E.1). The diff is set-based.

### F.3 Causal guarantees

- **Same-observation exclusion:** swings confirmed by N (`available_at =
  e(N)`) are admitted after N is classified, so they are first usable by
  N+1.
- **No revision of the past:** rescans and admissions only affect `F_N`
  onward.
- **Availability:** every output of the batch has `available_at = e(N)`,
  which is ≥ every input it uses (references with `available_at ≤ s(N)`,
  plus N itself).
- **Cross-timeframe:** an LTF bar reads HTF records only with
  `HTF.available_at ≤ LTF.bar_start`. It references HTF ids, never copies
  them, and never feeds back.

---

## G. Lifecycle, gaps, contracts, timeframes and revisions

### G.0 Closed within-contract semantics versus deferred contract-roll treatment

**CLOSED** (approved for design; it applies inside one continuity segment
of one contract). **Within-contract semantic review is complete (rev 2.3,
§K.2b).**

- D1–D17 and K-1 … K-14 as applied in §C–§F;
- N-1 and N-3;
- data-gap resets inside one contract (missing bucket / session,
  incomplete observation): their scheduled-replay onset, the `DATA_GAP`
  reason and the `DATA_GAP_REESTABLISHMENT` opening (K-5, §G.2);
- contract isolation (K-5): episodes, roles and events are `SPECIFIC`, so
  a new contract never inherits old-contract state, and no observation is
  ever classified against another contract's state;
- the requirement that a contract change carries its **own** reset reason
  and provenance (`CONTRACT_CHANGE` / `CONTRACT_CHANGE_REESTABLISHMENT`),
  never mislabelled `DATA_GAP` (K-5).

**DEFERRED** (dependent on the contract-roll review; not finalized):

- **N-2:** provenance when a data gap and a contract change occur at the
  same boundary.
  - The user's provisional preference is primary `DATA_GAP` plus an
    explicit `contract_changed = True` flag. This is **not** an approved
    rule.
  - On DEVELOPMENT **every** roll coincides with missing roll-week
    sessions. Every DEVELOPMENT roll boundary therefore depends on N-2.
- **The exact reset onset for a pure contract change** (no missing or
  invalid observation).
  - Proposed: the `bar_end` of the first new-contract observation (§G.3).
  - It remains a proposal until roll treatment is reviewed.
- **Any broader roll treatment.** Continuous or stitched structure across
  rolls stays out of scope (D1 data-quality gate deferred, D-123).

Implementation must not hard-code the deferred items before review
(§J, MS-I0).

### G.1 Lifecycle

- An episode opens `UNDEFINED`, with both candidates seeding by rescan.
- **ESTABLISHMENT** (not BOS):
  - the broken candidate target is CONSUMED and becomes the baseline;
  - `P*` becomes PROTECTION;
  - `E := N`;
  - the anchors and the other side's roles are ENDED.
- **BOS** consumes the target and moves `E`.
  - It may promote a strictly tighter protection (REPLACED).
  - Otherwise the protection entity is untouched (§C.4).
- **CHoCH** returns the direction to UNDEFINED and rescopes. Candidates
  reseed in the same batch, and either direction may re-establish later.
- **RESET** ends the episode.

### G.2 Resets for historical replay (K-5)

**Breaks come from shared continuity only** (`src/data/continuity.py`).
Scheduled closures, maintenance intervals, weekends and verified
shortened sessions follow the M1 / M3 expected schedule and are **not**
breaks.

**Onset**, computed only from the declared expected schedule and the
observations:

| Break | Onset `t_r` | Reset reason |
|---|---|---|
| Missing expected bucket / session | Expected `bar_end` of the first missing expected observation after the last valid one (from `expected_timeframe_schedule`) | `DATA_GAP` |
| Incomplete (invalid) observation | That observation's `bar_end` (its expected completion) | `DATA_GAP` |
| Contract change, no missing or invalid observation | **Proposed, pending the roll review (§G.0):** `bar_end` of the first observation on the new contract (§G.3) | `CONTRACT_CHANGE` (distinct reason: K-5, closed) |
| Gap **and** contract change at one boundary | **DEFERRED (N-2)**; the gap onset is the provisional preference | **DEFERRED (N-2)**; provisional preference `DATA_GAP` + `contract_changed = True`, **not approved** |

**At `t_r`:**

- the direction goes to `RESET` (reason as above);
- every active role is ENDED;
- a RESET event is written (`reset_reason`, `CONTINUITY_BREAK` ref).

There is no BOS / CHoCH inference across or inside the gap (D12).

**Live operation:** feed lateness and timeout detection are **deferred**.
The onset above is a property of scheduled historical replay. No claim is
made that a live system could detect it at `t_r`.

### G.3 Opening causes and contract isolation

| New episode follows | `opening_cause` |
|---|---|
| Start of the input (the first segment) | `DATA_START` |
| A break whose shared-continuity reason is MISSING_EXPECTED_SESSION / MISSING_EXPECTED_BUCKET / INCOMPLETE_BAR, **without** a contract change | `DATA_GAP_REESTABLISHMENT` (closed) |
| A break whose reason is CONTRACT_CHANGE only | `CONTRACT_CHANGE_REESTABLISHMENT` (the distinct cause is closed; the onset is pending the roll review) |
| A gap break **with** `contract_changed = True` | **DEFERRED (N-2).** Provisionally `DATA_GAP_REESTABLISHMENT` with `opening_contract_changed = True`; not approved |

Not every later segment is a data-gap re-establishment. The cause comes
from the shared break row.

**Contract changes** (the onset is proposed, pending the roll review;
isolation is closed).

- The new contract is known only from the first new-contract observation:
  its data, available at its `bar_end`. Nothing earlier is assumed.
- **Proposed:** the old episode resets, and the new episode opens, at the
  same instant: `e(first new-contract observation)`. These are different
  entities, so M7A is satisfied.
- That observation is the new episode's first observation and is **never
  classified against the old episode**.
- **Contract isolation:**
  - episodes, roles and events are `SPECIFIC` to one contract;
  - M7A forbids bridging, so a new-contract consumer cannot read
    old-contract state;
  - between `s(first new obs)` and its `e`, no new-contract structure
    exists yet.
- New-episode roles and events copy `episode_opening_cause` (D12
  provenance). Canonical swings are untouched, with no special swing type.

### G.4 Timeframes

- The same engine runs independently on 1m (canonical bars directly) and
  on 5m / 15m / 1H / 4H / 1D (M3), each with its own swings, breaks and
  continuity.
- There is no top-down mutation.

### G.5 Prefix replay

- Observations `1..k` must reproduce exactly every row with `available_at
  ≤ e(k)`, and every M7A state at decision points `≤ e(k)`, of the full
  run.
- No hindsight fields are used: no `valid_until`, and a RESET only at a
  known onset.
- **The one boundary case:**
  - a gap onset is placed at the schedule instant of the first missing
    observation;
  - a prefix ending exactly at the last valid observation therefore lacks
    that RESET, which is identical to the full run restricted to
    `≤ e(k)`.

### G.6 Revisions

Covered in §C.8.

---

## H. Worked examples

Notation: 5m bars unless stated. `S[kind price; span p..q; avail at
e(r)]` names a swing whose plateau occupies observations `p..q` and which
is confirmed by observation `r`. `c@n` is observation n's close.

### H.0 Verified OHLC examples: the one Swing definition and what was checked

**Swing definition for every OHLC example:**

- `swing-pivot-v1` with `left_depth = right_depth = 2`;
- tick 0.25;
- contiguous 5m observations in one continuity segment of one contract;
- observation `i` has `bar_end = e(i)` and `bar_start = s(i) = e(i−1)`;
- `source_at = e(a)`, `source_end_at = e(b)` and `available_at = e(b+2)`
  for plateau `a..b`;
- a swing is eligible at `s(N)` iff `b + 2 ≤ N − 1`;
- a break at observation `j` requires `j ≥ b + 3`
  (`bar_start ≥ available_at`) and a strictly-beyond close.

**Checked by a scratch-only script** (not feature code, not a test, no
DEVELOPMENT data):

- valid OHLC (`L ≤ min(O, C)`, `H ≥ max(O, C)`) and tick alignment;
- **every** confirmed swing in each sequence, derived with the **frozen**
  detector core (`swing_detector._confirmed_plateaus`): maximal plateaus,
  strict-exceed left / right windows, equality in windows allowed. The
  swing lists below are complete; no other swing exists in these bars;
- each swing's first breaking observation;
- the §E selection formulas at the stated instants:
  - anchors (min / max, first eligible);
  - candidate targets (after the anchor);
  - `P*` (deepest, earliest source);
  - K-3 scope, freshness, and E.7 target eligibility (K-1, D10);
- the stated close comparisons (first close beyond each level).

**Not checked by script:**

- role-entity ids and transition rows. These follow §C.4 / §F.2 by hand.
- H.2–H.4, H.7 and H.9–H.15, which are unchanged from rev 2.1.

**EX-A bars** (used by H.1; observations 0–10 are reused by EX-C):

| i | O | H | L | C | swing (span; avail) | note |
|---|---|---|---|---|---|---|
| 0 | 106 | 107 | 105 | 106 | | |
| 1 | 106 | 106 | 102 | 103 | | |
| 2 | 103 | 104 | 100 | 103 | `A0` LOW 100 (2..2; e(4)) | |
| 3 | 103 | 106 | 102 | 105 | | |
| 4 | 105 | 108 | 104 | 107 | | |
| 5 | 107 | 110 | 106 | 108 | `C0` HIGH 110 (5..5; e(7)) | |
| 6 | 108 | 109 | 105 | 106 | | |
| 7 | 106 | 107 | 104 | 105 | `P` LOW 104 (7..7; e(9)) | |
| 8 | 105 | 108 | 105 | 107 | | |
| 9 | 107 | 109 | 106 | 108 | | |
| 10 | 108 | 112 | 107 | 111 | | **E1:** first close > 110 |
| 11 | 111 | 115 | 110 | 114 | | |
| 12 | 114 | 118 | 113 | 116 | `T1` HIGH 118 (12..12; e(14)) | |
| 13 | 116 | 117 | 109 | 110 | | |
| 14 | 110 | 111 | 104 | 106 | `Q1` LOW 104 (14..14; e(16)) | equal to `P` |
| 15 | 106 | 109 | 105 | 108 | | |
| 16 | 108 | 112 | 107 | 111 | | |
| 17 | 111 | 116 | 110 | 115 | | |
| 18 | 115 | 120 | 114 | 119 | | **BOS1:** first close > 118 |
| 19 | 119 | 124 | 118 | 123 | | |
| 20 | 123 | 126 | 121 | 122 | `T2` HIGH 126 (20..20; e(22)) | |
| 21 | 122 | 124 | 116 | 117 | | |
| 22 | 117 | 118 | 112 | 114 | `Q2` LOW 112 (22..22; e(24)) | |
| 23 | 114 | 119 | 113 | 118 | | |
| 24 | 118 | 122 | 117 | 121 | | |
| 25 | 121 | 125 | 120 | 124 | | |
| 26 | 124 | 129 | 123 | 128 | | **BOS2:** first close > 126 |

The complete swing set is `A0, C0, P, T1, Q1, T2, Q2`. Breaches: `C0` at
10, `T1` at 18, `T2` at 26; no LOWER swing is ever closed below.

**H.1 Establishment (D2), BOS without replacement, then BOS with
replacement (D7 / D15; rev 2.2 protection identity).** Bars: EX-A.

- **`S_10`:** `BULL_ANCHOR(A0 = 100)`, `BULL_CANDIDATE_TARGET(C0 = 110)`.
  `P` (avail e(9) = s(10)) is eligible.
- **Establishment at 10:** `c@10 = 111 > 110`.
  - `P*` = deepest low after `C0` = `P` (104), and 104 > 100, so bull
    qualifies.
  - **Batch e(10):**
    - direction `UNDEFINED→BULLISH`;
    - `A0` ENDED;
    - `C0` CONSUMED (baseline);
    - bear anchor `C0` BROKEN, and the dependent
      `BEAR_CANDIDATE_TARGET(P)` (assigned e(9)) ENDED;
    - new `PROTECTION(P)` with `assigned_at = e(10)` and parent =
      ESTABLISHMENT `event_id`;
    - event `ESTABLISHMENT(BULLISH)`.
- **e(14):** new `TARGET(T1 = 118)`, parent = ESTABLISHMENT. Its
  `source_end_at = e(12) ≥ e(10)`, it is after `C0`, and 118 > 110.
- **BOS1 at 18:** `c@18 = 119 > 118`.
  - `T1` CONSUMED; `E := 18`; `B := T1`.
  - `P*` = deepest low after `T1` eligible at s(18) = `Q1` (104).
  - 104 is **not** > 104, so there is no replacement.
  - **PROTECTION(P) persists:**
    - the same `role_id`, `assigned_at = e(10)` and ESTABLISHMENT parent;
    - **no transition** and no new entity at e(18);
    - the BOS event lists it in `role_refs` as read.
- **e(22):** new `TARGET(T2 = 126)`, with parent = the BOS1 `event_id`
  (the current leg).
- **BOS2 at 26:** `c@26 = 128 > 126`.
  - `T2` CONSUMED.
  - `P*` = `Q2` (112), and 112 > 104, so the protection is replaced:
    - `PROTECTION(P)` exits **REPLACED** at e(26);
    - new `PROTECTION(Q2)` with `assigned_at = e(26)` and parent = the
      BOS2 `event_id`.

**H.2 Freshness on the immediately following observation (correction 1).**

- A CHoCH at X = 10:15–10:20 (`e(X) = 10:20`).
- Swing `F[LOW; first observation X+1 = 10:20–10:25]` has `source_at =
  10:25 > 10:20` → **fresh**.
- Across maintenance: X = 16:55–17:00 and X+1 = 18:00–18:05 →
  `source_at = 18:05 > 17:00` → fresh.
- A swing whose plateau **starts at X** (`source_at = 10:20 = e(X)`) is
  stale, even if confirmed later.

**H.3 Several swings confirming together (correction 2).** By L0 they must
share their last plateau observation.

- **Pre-state `S_N`:** UNDEFINED.
  - Bull: `BULL_ANCHOR(A1 = LOW 101; 2..2)` and
    `BULL_CANDIDATE_TARGET(H1 = HIGH 110; 4..4, parent A1)`.
  - Bear: `BEAR_ANCHOR(Hb = HIGH 111; 1..1)` and
    `BEAR_CANDIDATE_TARGET(A1, parent Hb)`.
- **Closes.** All closes of observations 2–9 lie in 101.25…109.75, so no
  anchor or target is breached and no classification occurs.
- **Outside bar.** Observation 7 is an outside bar, the only extreme in
  both windows. With R=2 it is confirmed at `e(9)` = `e(N)`, N = 9,
  `c@9 = 105` (no event), as **both** `H7[HIGH 112; 7..7]` and
  `L7[LOW 100; 7..7]`.
- **Rescan at e(9)** (one batch; order of admission irrelevant):
  - **bull:** anchor = L7 (100 < 101, so the anchor is replaced, D14);
    ctarget = max high **after** L7's span (after 7): none, because H7
    overlaps L7 and is not after it;
  - **bear:** anchor = H7 (112 > 111, replaced); ctarget = min low after
    H7's span: none.
- **Diff at e(9):**
  - exits: `A1` (bull anchor) SUPERSEDED; `H1(parent A1)` ENDED;
    `Hb` SUPERSEDED; `A1(parent Hb)` ENDED;
  - new: `BULL_ANCHOR(L7)`, `BEAR_ANCHOR(H7)`.
  - Each old entity has exactly one exit, and no new entity exits at
    e(9).
  - Swing `A1` had two role entities (anchor, bear candidate target).
    Both exit, each with a single transition.
- **Order independence:** admitting `H7` before `L7`, or the reverse,
  yields the same `F_9` (set-based rescan) and the same diff.

**H.3b Delayed plateau and anchor replacement (correction 3).**

- **Facts:**
  - `L5[LOW 100; 3..6]` is a long equal-low plateau, confirmed at `e(8)`;
  - `H5[HIGH 110; 5..5]` is a swing high inside it (bar 5 also carries the
    equal low), confirmed at `e(7)`;
  - the anchor before `e(8)` is `A0[LOW 102; 1..1]`.
- **Batch at e(7)** admits H5: ctarget = H5 (after A0).
- **Batch at e(8)** admits L5:
  - L5 is strictly lower, so the anchor is replaced. ctarget is then
    recomputed after L5's span (after 6), and H5 (at 5) **no longer
    qualifies**: it overlaps.
  - **Diff:** A0 SUPERSEDED, `H5(parent A0)` ENDED, new
    `BULL_ANCHOR(L5)`.
  - **No classification at or before e(8) changes** (D9). If a close
    above 110 occurred at observation 8, it was classified against
    `S_8`, where the anchor was A0 and the target H5.

**H.4 Admission at the same close as classification.**

- A BOS at N consumes T. `Lc[LOW; source between T and N; avail e(N)]` is
  admitted at `e(N)`.
- Lc is not eligible at `s(N)`, so it is not `P*` for this BOS (D9).
- After the BOS, `E = N`. Future protection candidates must be after the
  **next** consumed target, so Lc is never used.
- Past classifications are not revised.

**EX-C bars** (used by H.5 and H.6). Observations 0–10 are EX-A 0–10
(`A0`, `C0`, `P`; establishment E1 at 10). They continue:

| i | O | H | L | C | swing (span; avail) | note |
|---|---|---|---|---|---|---|
| 11 | 111 | 118 | 110 | 117 | | |
| 12 | 117 | 125 | 116 | 124 | | |
| 13 | 124 | 130 | 123 | 127 | `T` HIGH 130 (13..13; e(15)) | |
| 14 | 127 | 128 | 120 | 121 | | |
| 15 | 121 | 122 | 116 | 117 | | |
| 16 | 117 | 118 | 108 | 110 | | |
| 17 | 110 | 111 | 102 | 105 | `A` LOW 102 (**17..18**; e(20)) | wick below `P`; close ≥ 104 |
| 18 | 105 | 107 | 102 | 106 | (plateau, equal low) | maximal: 16 and 19 lows differ |
| 19 | 106 | 112 | 105 | 111 | | |
| 20 | 111 | 116 | 110 | 115 | | |
| 21 | 115 | 120 | 114 | 118 | `H` HIGH 120 (21..21; e(23)) | |
| 22 | 118 | 119 | 112 | 113 | | |
| 23 | 113 | 114 | 107 | 108 | `Ld` LOW 107 (23..23; e(25)) | |
| 24 | 108 | 113 | 108 | 112 | | |
| 25 | 112 | 116 | 111 | 115 | `H2` HIGH 116 (25..25; e(27)) | |
| 26 | 115 | 115 | 110 | 111 | | |
| 27 | 111 | 112 | 103 | 106 | `Ps` LOW 103 (27..27; e(29)) | wick below `P`; close ≥ 104. Breaks `Ld` (106 < 107) |
| 28 | 106 | 109 | 105 | 108 | | |
| 29 | 108 | 110 | 106 | 109 | | |
| 30 | 109 | 109.5 | 103.5 | 103.5 | `Lx` LOW 103.5 (30..30; e(32)) | **X:** first close < 104 since E1 (CHoCH) |
| 31 | 104 | 107 | 104 | 106 | | |
| 32 | 106 | 109 | 105 | 108 | | |
| 33 | 108 | 110 | 106 | 107 | | |
| 34 | 107 | 108 | 105 | 107 | `Lf` LOW 105 (34..34; e(36)) | equal low at 32 is non-adjacent (allowed) |
| 35 | 107 | 112 | 106 | 111 | | |
| 36 | 111 | 116 | 110 | 115 | | |
| 37 | 115 | 116 | 114 | 116 | | close = `H2` (equality is no break) |
| 38 | 116 | 123 | 115 | 122 | `Hn` HIGH 123 (38..38; e(40)) | **N:** first close > 120 |
| 39 | 122 | 122 | 118 | 119 | | |
| 40 | 119 | 120 | 116 | 117 | | |

- **Complete swing set:** `A0, C0, P, T, A, H, Ld, H2, Ps, Lx, Lf, Hn`.
- **Breaches:** `C0` at 10, `Ld` at 27, `P` at 30, `H` and `H2` at 38.
  `A0`, `T`, `A`, `Ps`, `Lx`, `Lf` and `Hn` are never breached in these
  bars.

**H.5 Historical reseeding during a CHoCH (K-3; rebuilt in rev 2.2).**
Bars: EX-C.

- **Pre-state while BULLISH (e(15) … s(30)):**
  - `PROTECTION(P = 104; 7..7)` from e(10);
  - `TARGET(T = 130; 13..13)` from e(15), with `source_end_at = e(13) ≥
    e(10)`, after `C0`, and 130 > 110.
  - `H` (120) and `H2` (116) are lower since-expansion highs, so they are
    ignored (nested, D4).
  - `A` and `Ps` wick below 104 but every close from 10 to 29 is ≥ 104,
    so there is no CHoCH. Protection changes only at an expansion, so
    neither became a role.
  - No close reaches 130, so there is no BOS.
- **Confirmation order follows span order** (L0):
  `T` e(15) < `A` e(20) < `H` e(23) < `H2` e(27) < `Ps` e(29).
  - The rev 2.1 claim that a target confirmed before an earlier-span low
    is not used. The rescan below does not depend on order in any case.
- **CHoCH at X = 30:** `c@30 = 103.5 < 104` →
  `CHOCH(BEARISH, pre BULLISH, post UNDEFINED)`.
- **Breaches at 30:** `P`. (`Ld` was already breached at 27.) `A` (102)
  and `Ps` (103) are ≤ 103.5, so they survive.
- **Rescan at e(30):** the scope is `source_at ≥ P.source_at = e(7)` (K-3),
  so `A0` (100, at 2) is out of scope.
  - **bull anchor** = min in-scope unbreached low = `A` (102; the
    17..18 plateau);
  - **bull candidate target** = max high after `A` (after 18) = `H` (120).
    `H2` (116) is lower and ignored;
  - **bear anchor** = max in-scope high = `T` (130);
  - **bear candidate target** = min low after `T` (after 13) = `A` (102).
- **Diff at e(30):**
  - `PROTECTION(P)` BROKEN; `TARGET(T)` ENDED; direction
    `BULLISH→UNDEFINED`;
  - new `BULL_ANCHOR(A)`;
  - new `BULL_CANDIDATE_TARGET(H, parent = BULL_ANCHOR(A) role)`;
  - new `BEAR_ANCHOR(T)`;
  - new `BEAR_CANDIDATE_TARGET(A, parent = BEAR_ANCHOR(T) role)`.
  - `T` has one exiting and one new entity, and `A` has two new entities.
    All are M7A-valid.
- **Later admissions, no role change:**
  - e(32): `Lx` (103.5 > 102);
  - e(36): `Lf` (105).

**H.6 Stale deepest blocks establishment (K-4), then waiting without
reselection (K-8, §E.6a).** Continues H.5 (EX-C).

- **Classification of N = 38 against `S_38`:** `c@38 = 122 > H` (120).
  Every close from 24 to 37 is ≤ 120, so 38 is the first break.
  - **Bull, not invalidated:** 122 ≥ 102.
  - `P*` = deepest eligible low after `H` (after 21) at s(38). Candidates:
    - `Ps` 103;
    - `Lx` 103.5;
    - `Lf` 105;
    - (`Ld` is breached).

    So `P*` = `Ps` (103) > anchor 102, and it is strictly beyond the
    anchor.
  - **Freshness:** `Ps.source_at = e(27) ≤ e(30)` → **stale** →
    the side does not qualify (K-4).
  - `Lf` is fresh (`source_at = e(34) > e(30)`) but shallower, so it is
    **not substituted**.
  - `Lx` (plateau starting at X) would be stale too (H.2).
  - **Bear:** 122 < 130 (no invalidation) and 122 ≥ 102 (no break), so
    nothing happens.
- **Batch e(38):**
  - `BULL_CANDIDATE_TARGET(H)` RETIRED;
  - `BULL_ANCHOR(A)` persists;
  - no event, no direction change.
- **Breaches at 38:** `H`, **and `H2`** (122 > 116). `H2` was the
  previously ignored, unbreached candidate after `A` (§E.6a R1).
- **Rescan at e(38):** no unbreached eligible high after `A`, so there is
  no bull candidate target. The side waits (K-8).
- **e(40):** `Hn` (123; 38..38) is admitted.
  - New `BULL_CANDIDATE_TARGET(Hn, parent = BULL_ANCHOR(A) role)`.
  - `Hn` is a new fact, priced ≥ high(38) ≥ c(38) (§E.6a R2). `H2` is
    never reselected.
- **The anchor `A` persists through e(40).**
- **Contrast with rev 2.1.** Rev 2.1 placed an eligible, unbreached,
  in-scope low (101) below the selected anchor (102). D14 would have made
  that low the anchor. Here every in-scope unbreached low is ≥ `A`, and
  the stale `P*` lies strictly between the anchor and the fresh low.

**H.7 Deepest pullback failing strict qualification (D15).**

- `A[LOW 100]`, `H0[HIGH 110]`, `P1[LOW 100]` (equal to A, so it does not
  replace the anchor), `P2[LOW 105]`.
- `c > 110` → `P* = P1` (100, not > 100) → no establishment. H0 is
  RETIRED, A persists, and P2 is not substituted.

**H.8 Equal targets (K-7, N-1) and equal pullbacks (D11); replaced in
rev 2.2.**

The rev 2.1 case (source 5 / confirmation 7 against source 3 /
confirmation 9) was **not realizable**. Two single-observation swings
under one `right_depth` confirm in source order (L0). Under the frozen
contract, earliest eligibility and earliest source **never diverge** for
same-orientation swings (§E.2a L0′), so no divergent case is shown.

**EX-B bars:**

| i | O | H | L | C | swing (span; avail) | note |
|---|---|---|---|---|---|---|
| 0 | 106 | 107 | 105 | 106 | | |
| 1 | 106 | 106 | 102 | 103 | | |
| 2 | 103 | 104 | 100 | 103 | `A` LOW 100 (2..2; e(4)) | |
| 3 | 103 | 106 | 102 | 105 | | |
| 4 | 105 | 108 | 104 | 107 | | |
| 5 | 107 | 110 | 106 | 108 | `Ha` HIGH 110 (5..5; e(7)) | |
| 6 | 108 | 109 | 105 | 106 | | |
| 7 | 106 | 107 | 104 | 105 | `Pa` LOW 104 (7..7; e(9)) | |
| 8 | 105 | 108 | 105 | 107 | | |
| 9 | 107 | 110 | 106 | 109 | `Hb` HIGH 110 (9..9; e(11)) | separated equal high (not a plateau with 5) |
| 10 | 109 | 109 | 106 | 107 | | |
| 11 | 107 | 108 | 104 | 105 | `Pb` LOW 104 (11..11; e(13)) | separated equal low |
| 12 | 105 | 107 | 105 | 106 | | |
| 13 | 106 | 109 | 105 | 108 | | |
| 14 | 108 | 112 | 107 | 111 | | **N:** first close > 110 |

- **Complete swing set:** `A, Ha, Pa, Hb, Pb`.
- **Breaches:** `Ha` and `Hb` at 14; the lows are never breached.
- **Timeline:**
  - **e(7):** `BULL_CANDIDATE_TARGET(Ha)` under `BULL_ANCHOR(A)`.
  - **e(11):** `Hb` is admitted at an equal price. The incumbent `Ha` is
    retained: it is the first eligible, which is also the earliest
    source. There is no transition, and the pullback interval stays
    "after `Ha`" (K-7).
  - **N = 14:** `c@14 = 111 > 110`.
    - `P*` = deepest low after `Ha` among `Pa` and `Pb`. They tie at 104,
      so the earliest source wins: `P*` = **`Pa`** (D11).
    - 104 > 100, so the result is ESTABLISHMENT BULLISH: `Ha` CONSUMED and
      new `PROTECTION(Pa)`.
    - `Hb` is breached at 14 and holds no role.

**H.9 Nested consolidation and the K-1 straddle.**

- BOS at E with an E high of 115; `X[HIGH 115; E−1..E]` straddles E →
  `source_end_at = e(E)` → target-eligible (K-1), if after the consumed
  span and > baseline.
- `X2[HIGH 113]`, nested and later: a close at 114 breaches X2 only (no
  event); a close at 116 is a BOS on X.

**H.10 Wick versus close (D1).**

- Target 110: H = 111, C = 110 → no break (equality).
- C = 110.25 → break (`close_excess_ticks = 1`).
- Gap-open O = 110.50, C = 111 → break (D1), although M6 reports no
  close_through (§A.2).

**H.11 Gap versus contract provenance (correction 4).**

- **4H, contract A:** the last valid bucket ends 10:00; the 10:00–14:00
  bucket is missing.
  - RESET(`DATA_GAP`) at its expected `bar_end` 14:00.
  - The next segment opens at the next valid bucket's `bar_end`, as
    `DATA_GAP_REESTABLISHMENT`.
- **Closed:** the A episode is not continued on B, and no B observation
  is ever classified against A state (K-5).
- **Roll with no gap: onset proposed, pending the roll review (§G.0).**
  - The last A bar ends 14:00; the next expected bucket (14:00–17:00) is
    on contract B.
  - RESET(`CONTRACT_CHANGE`) of the A episode, and a new B episode
    (`CONTRACT_CHANGE_REESTABLISHMENT`), both at 17:00.
  - The 14:00–17:00 bar is the B episode's first observation.
- **Roll during missing roll-week sessions** (the DEVELOPMENT pattern):
  **DEFERRED (N-2).**
  - Provisional, not approved: RESET(`DATA_GAP`, `contract_changed =
    True`) at the first missing observation's expected end, with
    `opening_cause = DATA_GAP_REESTABLISHMENT`.
  - Until N-2 is decided, the only settled facts are these:
    - the A episode ends no later than this boundary;
    - B starts a new episode with no inherited state.

**H.12 Revision (K-13 / correction 5).**

- **Run R1:** `swing_id S` (price 110.00) breaks at observation 40 →
  `break_id B40`, `fact_hash h1`.
- **Revised bars give run R2:** the same S span, but a revised high of
  110.25, which breaks at 41 → `break_id B41`. In R2, S has no `B40`
  row.
- R1 rows remain stored. R2 is new. Neither patches the other, and the
  pinned facts show the difference.

**H.13 Outside bar / overlap.** Observation 5 is both `HIGH 110` and
`LOW 98`. It can never serve as consecutive anchor → target, because
anchor-to-target requires strictly after.

**H.14 Cross-timeframe.** A 4H BOS with `available_at` 14:00 is first
readable by the 5m bar with `bar_start` 14:00. The 5m reader references
the 4H `event_id`, and 5m structure is unchanged.

**H.15 D16 fallback contract.** If an anomaly were ever produced:
direction stays UNDEFINED; both targets are RETIRED; one
`DUAL_ESTABLISHMENT` row is written; no event is emitted; validation
fails.

---

## I. Validation: arguments, planned tests, executed tests

### I.0 Status

| Category | Content | Status |
|---|---|---|
| Mathematical arguments | A-1 … A-7 below (A-1′, A-6 and A-7 new in rev 2.2) | Written; **not machine-checked** |
| Example consistency check (rev 2.2) | EX-A, EX-B, EX-C (§H.0) | **Scratch-only script, run 2026-10-05: all assertions pass.** Swing spans come from the frozen `_confirmed_plateaus`; breaches and §E formulas were evaluated at the stated instants. This is not a feature test, not a DEVELOPMENT run and not repository code. Role-entity / transition rows were not machine-checked |
| Planned tests | MS-T1 … MS-T20, invariants INV-1 … INV-15 | **Not implemented, not run** |
| Executed tests | — | **None** for this feature family |

### I.1 Mathematical arguments (with assumptions)

- **A-1 (D16 unreachable):** §E.8.
- **A-2 (protection < target while bullish).**
  - At promotion, `P* ≤ consumed target` by L3, because `P*` is after
    it.
  - Every later target is strictly above the consumed baseline (D10).
  - Replacement only raises protection to another `P* ≤` the
    newly consumed target.
  - Hence `PROTECTION.price < TARGET.price`.
  - Assumptions are those of the L-lemmas; BEARISH mirrors.
- **A-3 (INV-8: no break row before eligibility is even possible).**
  - Under the frozen Swing rule, the plateau and its R right-window
    observations have extremes not beyond the swing price. So their
    closes are not strictly beyond.
  - **Assumptions:**
    - breaks are evaluated on the **same timeframe's** prepared frame that
      produced the swing (canonical 1m or the same M3 frame);
    - the observations are complete and inside one continuity segment;
    - prices are on the tick grid;
    - the swing input is unrevised (§C.8).
  - Under other inputs (e.g. a different timeframe's bars, or revised
    data) the claim does not hold, and INV-8 is checked rather than
    assumed.
- **A-4 (rescan ≡ incremental D13 / D14):** §E.2.
- **A-5 (L0: confirmation order follows span order for non-overlapping
  swings under one definition):** §E.2a.

- **A-1′ (D16 via opposite-extreme ordering, L5):** §E.8.
- **A-6 (L0′: no eligibility / source divergence for same-orientation
  swings under one definition):** §E.2a.
- **A-7 (no target resurrection after failed establishment; R1–R3):**
  §E.6a.

### I.2 Planned synthetic tests (not yet implemented)

| Id | Scenario |
|---|---|
| MS-T1 | Initial bullish / bearish establishment; establishment is not BOS (H.1) |
| MS-T2 | Deepest pullback failing strict qualification (H.7) |
| MS-T3 | Equal separated targets (incumbent retained) and equal pullbacks (earliest source) (H.8, EX-B) |
| MS-T4 | Nested consolidation; K-1 straddle (H.9) |
| MS-T5 | BOS without replacement (equal `P*`: protection keeps `role_id` / `assigned_at` / parent, with no transition); BOS with replacement (REPLACED, new parent) (H.1, EX-A) |
| MS-T6 | CHoCH → bearish and → bullish re-establishment; K-3 scope; freshness including X+1 and maintenance (H.2, H.5) |
| MS-T7 | Stale deepest blocks; fresh shallower not substituted (H.6, EX-C) |
| MS-T8 | Same-observation confirmation excluded; admission at the classification close (H.4) |
| MS-T9 | Several simultaneous confirmations (outside bar); anchor replacement in one batch; delayed plateau (H.3, H.3b); CHoCH reseed with historical anchor and target in one batch (H.5) |
| MS-T10 | Wick versus close, equality, one tick, gap-open break; the M6 contrast (H.10) |
| MS-T11 | Gap reset (missing bucket / session / incomplete); contract isolation. Contract-only onset and the combined case (H.11) are tested only after the roll review (N-2) |
| MS-T12 | Prefix replay equivalence (G.5) |
| MS-T13 | Iteration-order independence: shuffled swings / bars / breaks / admissions give byte-identical outputs |
| MS-T14 | Cross-timeframe isolation (H.14) |
| MS-T15 | Non-alternating and overlapping swings (H.13) |
| MS-T16 | M7A integration: `validate_transitions` for both namespaces; `materialize_state_to_bars` reproduces per-bar direction |
| MS-T17 | Revision runs: new `run_id`, prior run preserved, `fact_hash` diffs (H.12) |
| MS-T18 | Randomized small-configuration search for dual establishment (**supporting evidence only**, not proof) |
| MS-T19 | Failed establishment: every ignored candidate is breached by the failing close; the anchor persists; the next target is a new admission; no reselection (§E.6a, H.6, EX-C) |
| MS-T20 | T-1 timing (synthetic): a target confirmed at `e(N)` by the failing observation N is assigned at `e(N)`; it is absent from N's classification inputs; it is first readable at `s(N+1)` (including across a scheduled closure, where `s(N+1) > e(N)`); the failure batch's RETIRED exit and the absence of an event are unchanged by the admission; prefix replay to `e(N)` is identical |

### I.3 Planned machine-validation invariants (each must have 0 violations; DEVELOPMENT validates definitions, never optimizes)

- **INV-1:** no `structure_anomalies` rows (D16 / K-11). Any row fails
  validation and blocks approval or freeze.
- **INV-2:** every reference used to classify N is eligible at `s(N)`.
- **INV-3:** sequence spans are strictly ordered and non-overlapping.
- **INV-4:** protection is strictly tightened on replacement.
- **INV-5:** protection < target (bullish) / > target (bearish) when both
  are active (A-2).
- **INV-6:** targets are strictly progressive versus the baseline.
- **INV-7:** active-role uniqueness (§C.4).
- **INV-8:** no `swing_breaks` row with `bar_start < swing.available_at`
  (A-3 assumptions).
- **INV-9:** every output's `available_at` ≥ all of its inputs'.
- **INV-10:** no output crosses a segment or contract.
- **INV-11:** M7A validity; no entity is created and exited at the same
  timestamp.
- **INV-12:** pinned facts equal the run's input facts.
- **INV-13:** every RESET onset follows the schedule rules in §G.2.
- **INV-14:** a PROTECTION entity exits only as REPLACED (by a different,
  strictly tighter swing), BROKEN or ENDED. No protection transition
  occurs at a BOS without replacement (§C.4).
- **INV-15:** no role is assigned to a swing breached at or before its
  `assigned_at` (K-6; covers §E.6a R1).

### I.4 Visual validation (local, price-bearing, Git-ignored; tracked price-free manifest)

Each case shows the **causal sequence**, not retrospective labels:

1. **Pre-state at `s(N)`:**
   - eligible swings drawn solid;
   - swings confirmed later drawn hollow, with their `available_at`
     marker;
   - breached swings struck through from their break observation;
   - active roles (anchor, candidate target, target, protection) labelled
     with their `assigned_at`.
2. **Break evidence:** observation N's close against the referenced
   level, with tick excess, and the wick shown separately.
3. **Post-state after `e(N)`:** role exits (with reason) and new roles,
   direction change, and event label.
4. **For CHoCH / reseed cases:** the K-3 scope boundary
   (`broken_protection.source_at`) and the freshness boundary `e(X)`.

**Cases:**

- REAL DEVELOPMENT for every MS-T scenario where one exists;
- SYNTHETIC for H.1–H.15 otherwise;
- HTF→LTF panels showing `available_at` against LTF `bar_start`.

**Human visual approval is mandatory before any freeze.**

---

## J. Proposed bounded implementation sequence (requires separate authorization)

| Step | Content | Files (new unless noted) |
|---|---|---|
| MS-I0 | Approve this spec; register its D-numbers per the convention (§K.3) | docs |
| MS-I1 | `swing_breaks` and tests | `src/market_structure/swing_breaks.py`, `tests/test_swing_breaks.py` |
| MS-I2 | Engine: definition, episodes, roles, events, anomalies, batch rescan and diff, M7A transitions, per-timeframe runner, run manifest | `src/market_structure/structure.py`, `tests/test_structure.py` |
| MS-I3 | Audit, invariants, DEVELOPMENT runner, visual | `src/market_structure/structure_audit.py`, `src/experiments/market_structure_dev_validation.py`, `tests/test_structure_audit.py`, `reports/validation/market_structure_*` |
| MS-I4 (optional) | M7B adapter | `src/market_structure/structure_signals.py` |

No change to the frozen Swing, continuity, M3, M6 or M7 modules.

---

## K. Decision record

### K.1 Approved K-decisions → sections

**Rev 2.1 and rev 2.2 leave K-1 … K-14 intact.** Rev 2.2 corrects only
text, identity wording and examples (§K.2a).

- N-1 refines the meaning of "earliest" within K-7 / D11 / D14. It does
  not change them.
- N-3 refines K-10's entity-per-assignment rule with parent identity.
- N-2 keeps K-5's approved rules. It defers only the combined-boundary
  provenance.

| K | Decision | Applied in |
|---|---|---|
| K-1 | Since-expansion: `source_end_at ≥ e(E)`; straddlers included; ordering after the consumed span and progression retained | §E.1, §E.7, H.9 |
| K-2 | After invalidation, restart from empty and seed from the next eligible admission (including same-batch admissions); consistent with CHoCH reseeding | §E.2, §E.2a, §E.4, H.3 |
| K-3 | Historical reuse only for `source_at ≥ broken_protection.source_at`; freshness still applies | §E.3, §E.5, H.5 |
| K-4 | Deepest first, then freshness; a stale deepest blocks; target retired on a failed break | §E.5, §E.6, H.6 |
| K-5 | Scheduled-replay onset; closures don't reset; live lateness deferred; distinct CONTRACT_CHANGE reason and provenance; no inheritance across contracts | §G.2, §G.3, H.11 |
| K-6 | Breach per `swing_id`, permanent; later equal-price swings are independent | §C.2, §E.1, §E.9 |
| K-7 | A strictly more extreme target moves the interval; equal keeps the earliest without restart | §E.1, §E.4, §E.7, H.8 |
| K-8 | Failed establishment: retire the target, keep the anchor, wait; no retrospective establishment | §E.6, H.6, H.7 |
| K-9 | Native `swing_breaks`; M6 unchanged; concrete incompatibilities documented | §A.2, §C.2, H.10 |
| K-10 | A separate entity per assignment; final batch selection before materialization; no create-and-exit at one timestamp; uniqueness | §C.4, §E.2a, §F.2, H.3, H.3b, H.5 |
| K-11 | Dual-qualification fallback: stay UNDEFINED, keep evidence, flag, no establishment, fail validation (no runtime error); argument plus supporting search | §C.6, §E.6, §E.8, INV-1, MS-T18 |
| K-12 | BOS / CHoCH are versioned Generic Market Structure classifications; MSS deferred; governance reconciled | §C.5, §K.3 |
| K-13 | Pin facts; fingerprint bars, swings, definitions, schedule and instrument; new `run_id`; preserve prior runs | §C.4, §C.8, H.12 |
| K-14 | Event direction = break direction; pre / post recorded; no implied opposite establishment | §C.5, §D.1, §E.7 |

### K.2 Rev-2 review outcomes (N-1 … N-5)

**N-1. "Earliest" for anchors and targets: APPROVED (eligibility order).**

- **Anchors and targets** (persistent roles): retain the **first eligible**
  equal-price reference.
  - Eligibility order is causal availability (`available_at`), never input
    row order.
  - Simultaneous eligibility is tie-broken by the earliest source span:
    `source_at`, then `source_end_at`, then `swing_id`.
- **Pullback / protection selection** stays: deepest price, then earliest
  source span.
- Deterministic historical rescans reproduce this rule. They never change
  previously materialized assignments or classifications.
- **Applied in:** §E.1; H.8.

**N-2. Gap and contract change at the same boundary: DEFERRED.**

- This stays open until the contract-roll treatment is reviewed.
- The user's provisional preference is primary `DATA_GAP` plus an explicit
  contract-change flag. It is **not** an approved rule.
- The exact onset of a pure contract-change reset is also only proposed,
  pending the same review.
- **Applied in:** §G.0, §G.2, §G.3, §C.3 opening causes, H.11.
- **Implementation dependency:** MS-I0 must not hard-code combined-boundary
  semantics before this is resolved.
- **Closed within one contract:** all within-contract semantics, contract
  isolation and the distinct CONTRACT_CHANGE reason (§G.0).

**N-3. Parent-dependent target assignments: APPROVED.**

- A candidate-target assignment depends on its parent anchor assignment.
  Anchor replacement ends the dependent target assignment.
- If the same swing remains selected, a new target-role assignment is
  created that references the new anchor role.
- The parent context is in both identity (`parent_key` = parent anchor
  `role_id`) and provenance (`parent_role_id`).
- Only each same-close batch's final assignments are materialized (K-10).
- **Applied in:** §C.4; H.3.

**N-4. Numbering and sequencing: ADMINISTRATIVE.**

- 3.MS is retained as draft numbering. Market Structure work is sequenced
  before 3.3 Internal Liquidity.
- This is **not** feature approval.
- **Applied in:** `ROADMAP.md`; §K.3.

**N-5. Trigger reference: ADOPTED (simplest deterministic, existing
contracts only).**

- **Observation batches** use the batch observation's existing
  `BAR_SPAN:<instrument_id>|<contract>|<timeframe>|<e(N)>|<e(N)>`.
  - `transition_at = e(N)`.
  - Supporting `source_refs` list the specific causes:
    - `STRUCTURE_BREAK` for the batch's breaches;
    - `SWING` for admissions and selected swings;
    - `STRUCTURE_EVENT` for classifications.
- **Resets** use the existing `CONTINUITY_BREAK:<timeframe>|<contract>|<t_r>`
  ref, with `transition_at = t_r`.
- This adds no new provenance framework.
- **Applied in:** §C.7, §F.2.

**No contradictions with D1–D17 were found.** K-3's scope bound and D6's
freshness are independent filters, and §E.8 covers the finalized rules.

### K.2a Rev 2.2 review corrections (findings 1–5)

These correct the spec's text and examples. **No approved semantic rule is
changed.**

| Finding | Correction | Basis |
|---|---|---|
| 1. Retained protection identity | PROTECTION `parent_key` = its promotion event, fixed. A BOS without replacement leaves the entity untouched; only promotion of a different, strictly tighter swing is REPLACED. TARGET stays leg-scoped (§C.4, §D.2, §E.7, §G.1, H.1, INV-14) | D3 / D7 / D15 ("retained"); K-10 |
| 2. Impossible H.8 | Replaced by realizable EX-B. L0′ shows eligibility and source order cannot diverge for same-orientation swings, so no divergent case exists | N-1 kept as written |
| 3. H.5–H.6 anchor contradiction | Rebuilt on EX-C. Every in-scope unbreached low is ≥ the anchor; the stale `P*` lies strictly between the anchor and the fresh low. H.5's confirmation-order slip is removed | D14, K-3, K-4, K-6, D6 |
| 4. Reselection after failure | §E.6a R1–R3 prove that no previously ignored candidate survives the failing close. No reselection boundary is added | K-2, K-6, K-8 |
| 5. Example validity | §H.0 gives the Swing definition, explicit OHLC and what the scratch check covered (§I.0) | — |

**Genuinely unresolved semantic choices after rev 2.2:**

- **None within one contract.**
- **Deferred (unchanged):** N-2 and the pure-roll onset (§G.0).
- **Same-batch target after a failed establishment:** T-1, APPROVED
  (final) in rev 2.3 (§K.2b). No longer open.

### K.2b Rev 2.3 timing confirmation: T-1 APPROVED (final, design authority, 2026-10-05)

T-1 is final. It is registered with a D-number together with the rest of
the spec at MS-I0. The approval covers this semantic only:

- it does not approve or freeze the full specification;
- it authorizes no implementation;
- contract-roll treatment remains **DEFERRED** (§G.0: N-2 and the
  pure-roll reset onset).


| Id | Confirmation | Basis | Applied in |
|---|---|---|---|
| T-1 | After a failed establishment at N: the breached target is RETIRED; swings confirmed at `e(N)` are admitted in normal post-close processing; a newly confirmed, otherwise-valid target may be assigned at `e(N)`; it never participates in classifying N; it is usable only where `assigned_at` and `Swing.available_at` are ≤ the subsequent bar's start; the failed establishment is not retrospectively revised | The general classification-before-admission rule (D9; §F.1 (a) before (c); §F.3), not K-2 alone; consistent with K-8 | §E.6a R2, MS-T20 |

**Within-contract semantic review: COMPLETE.**

- K-1 … K-14, N-1, N-3 and T-1 are intact.
- No approved decision is changed.
- **Remaining open items:**
  - the contract-roll treatment (§G.0);
  - final approval and D-number registration.

### K.3 Governance reconciliation (K-12)

**Decision-recording convention.** Approved semantics receive D-numbers
when the design is approved, as happened for Swing (P-SW → D-135–D-138).
Until then:

- **`DECISION_LOG.md`:** a dated clarification is appended to D-133.
  - BOS / CHoCH are Generic Market Structure classifications, explicitly
    versioned (K-12). MSS stays deferred.
  - The full design (D1–D17, K-1 … K-14) is pending design approval and
    D-number registration.
- **`ROADMAP.md`:**
  - row 4 no longer lists "MSS / BOS open"; MSS is deferred and BOS /
    CHoCH are generic;
  - a "3.MS Generic Market Structure — DESIGN DRAFT" row is added.
    Its draft numbering and its sequencing before 3.3 are administrative
    (N-4).
- **Status:** not approved, implemented or frozen.
