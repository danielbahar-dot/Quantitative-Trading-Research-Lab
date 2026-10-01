# M7 — Generic State and Signal Contracts: Specification

**Status: M7 COMPLETE (2026-10-01).**

- **M7A (State)** is implemented and validated, and merged in PR #7
  (`4a0d674`; D-129–D-131).
- **M7B (Signal)** is implemented and validated in `src/signals/contract.py`
  (D-132). Its normative contract is "M7B FINAL CONTRACT" at the end of
  this document. Tests: `tests/test_signal_contract.py`, 28 tests / 88
  subtests.
- **Full suite:** 474 passed, 343 subtests.
- **Scope:** both are generic envelopes validated synthetically. No real
  State lifecycle or Signal family exists yet.

**M7A implementation (rev 3.1, D-130):**

- `src/state/contract.py`, with tests in `tests/test_state_contract.py`
  (46 tests / 40 subtests; rev 3.2, D-131).
- **The explicit causal-key truth table is the authoritative comparator
  test.** It covers equality, same-domain ordering, cross-domain and
  missing-sequence incomparability, and timestamp precedence.
- The randomized materializer-vs-brute-force test validates only the
  vectorization, because both paths use `compare_causal`.
- Validation is synthetic only. No real lifecycle exists yet, and none was
  invented for validation.

**Implementation notes:**

- `validate_transitions` returns timestamps normalized to UTC, in
  canonical order.
- The materializers return output in the observations' (bars') timezone.

**§0 (normative for M7A) supersedes any conflicting text** in §4–§24.
Those sections record the design reasoning and the Signal design (M7B),
which remains approved as written there, adjusted to §0's causal model,
SourceRef and identity rules.

## 0. Approved M7A contract (rev 3, normative)

> **Rev 3.1 amendments (2026-10-01, D-130). These override §0.2–§0.9 where
> they differ.**
>
> 1. **Sequence domain.** Causal keys are `(at, seq_domain, seq)`, with
>    `seq_domain` and `seq` co-null.
>    - `compare_causal(a, b)` returns `BEFORE`, `AFTER`, `EQUAL` or
>      `INCOMPARABLE`.
>    - At equal `at`, sequences order only when both are present in the
>      **same** domain. Both unsequenced, or the same domain and sequence,
>      is `EQUAL`. A missing sequence on one side, or different domains, is
>      `INCOMPARABLE`.
>    - Nullable domain/sequence pairs exist on transitions (`transition_*`,
>      `available_*`), on entities (`available_*`), on observations
>      (`observation_*`, `decision_*`) and on `state_as_of` queries.
>    - Current bar workflows use null / null.
>    - The domain participates in identity wherever its sequence does.
> 2. **`trigger_ref`** (a required `SourceRef`) identifies the single causal
>    source event.
>    - `source_refs` becomes **optional** supporting provenance, stored
>      canonically (sorted, unique). Input order never affects the id or the
>      output.
>    - A second transition for the same entity + namespace + `trigger_ref`
>      is rejected.
>    - Identity = full SHA-256 over namespace, version, entity, previous and
>      new state, the canonical UTC transition time, the sequence domain and
>      sequence, `trigger_ref`, and the canonical `source_refs`.
> 3. **Strict generic consumers.**
>    - `state_as_of` returns the state available **immediately before** the
>      query causal point: an entity or transition becoming available
>      exactly at the query key is not visible.
>    - `materialize_state_to_observations` is strict in the same way. There
>      is no configurable inclusive mode.
>    - **Only** `materialize_state_to_bars` applies the bar-boundary equality
>      convention.
>    - `validate_transitions` is causally strict and has no
>      `decision_offset` (removed in rev 3.2, D-131).
> 4. **No default timeframe.** `materialize_state_to_bars` requires a
>    `bar_start` column or an explicit `bar_interval`, and works for any
>    bar size. If both are supplied they must agree, otherwise it raises.
>    `valid_from` / `valid_until` remain timestamp-only static bounds, with
>    no sequence fields.
> 5. **Chain rules (unchanged in substance).**
>    - Consecutive transitions of one entity + namespace must be strictly
>      `BEFORE`-ordered, and the previous availability must be `BEFORE` the
>      next transition key. Simultaneous or incomparable keys therefore
>      cannot chain.
>    - Simultaneous transitions of *different* entities or namespaces are
>      allowed.
>    - An allowed edge whose `previous_state` disagrees with the replayed
>      history is rejected.

### 0.1 Layers and scope

- **Layers:** Validated Data → Feature → Interaction → **State** → Signal →
  Strategy → Execution.
- **State is a generic envelope.**
  - There is no global lifecycle vocabulary, reset policy or persistence
    rule.
  - Real namespaces (`liquidity.lifecycle`, `fvg.lifecycle`,
    `swing.lifecycle` …) belong to future modules and are not implemented
    here.
- **Canonical storage is the transition log.** Per-observation and per-bar
  views are derived materializations.
- **The core is observation / event based** and assumes no bar timeframe.
  M5 and M6 are unchanged.

### 0.2 Causal key

- A causal key is `K = (at, seq)`:
  - `at` is a tz-aware timestamp;
  - `seq` is an optional nullable integer, for stable ordering within one
    `at` in one sequence domain.
- **Strict precedence** `A ≺ B` iff:
  - `A.at < B.at`, or
  - `A.at == B.at` and both sequences are non-null and `A.seq < B.seq`.
- Any other same-`at` pair is **simultaneous** and is never ordered.
- **Not-later-than** `A ≼ B` is defined as `¬(B ≺ A)`.
- Current bar workflows use `seq = <NA>`.

### 0.3 `StateNamespaceSpec` (frozen dataclass)

| Field | Rule |
|---|---|
| `namespace` | Dotted lowercase, e.g. `test.lifecycle`. It determines the entity kind, so transitions carry no `entity_type` |
| `entity_kind` | Lowercase token |
| `initial_state` | **Required.** An entity is in it from the moment it becomes applicable until its first real transition. There is **no synthetic creation transition** |
| `allowed_states` | Uppercase tokens; contains `initial_state` |
| `allowed_transitions` | `(from, to)` pairs over `allowed_states`. **Self edges are rejected.** Skip edges must be declared explicitly |
| `terminal_states` | ⊆ `allowed_states`. A terminal state has no outgoing edge. Declaring one is a spec error: a namespace that wants a state to be re-enterable or exitable simply does not mark it terminal |
| `definition_version` | Non-empty |
| `attributes` | Optional tuple of `AttributeSpec(name, dtype, required)`, giving typed `attr_<name>` columns. `dtype` is one of `Int64`, `Float64`, `boolean`, `string`, `datetime` (tz-aware) |

### 0.4 Entity applicability frame

The entity frame is caller-provided; there is no persisted Entity
framework.

| Column | Req. | Rule |
|---|---|---|
| `entity_id` | yes | Unique, non-empty |
| `available_at` | yes | Causal knowledge time (tz-aware) |
| `available_seq` | optional | Nullable integer |
| `valid_from` | yes, nullable | Optional static start |
| `valid_until` | yes, nullable | Optional static end; `> valid_from` and `≥ available_at` when set |
| `instrument_id` | yes | — |
| `contract_scope` | yes | `SPECIFIC` / `AGNOSTIC` |
| `contract` | yes | Non-empty iff `SPECIFIC`; null iff `AGNOSTIC` |

**An entity is applicable at a causal point `D`** iff all three hold:

1. it is known: `(available_at, available_seq)` is visible at `D` (§0.8);
2. `valid_from ≤ D.at` (when set);
3. `D.at < valid_until` (when set).

The effective start is therefore `max(available_at, valid_from)`, as in
M5/M6. No State is ever returned or materialized outside applicability.

### 0.5 `StateTransition` record

One tidy DataFrame row per transition.

| Column | Req. | Notes |
|---|---|---|
| `transition_id` | yes | `"st_" + full 64-hex SHA-256` of the natural key (§0.6) |
| `namespace` | yes | Must equal the spec's namespace |
| `entity_id` | yes | Must exist in the entity frame |
| `previous_state` | yes | Non-null. For the entity's first transition it must equal `initial_state` |
| `new_state` | yes | `≠ previous_state` (no self transitions) |
| `transition_at`, `transition_seq` | yes / nullable | Causal key of the **source event that establishes** the change. Never back-dated to an inferred intrabar time; bars use `(bar_end, <NA>)` |
| `available_at`, `available_seq` | yes / nullable | When consumers may use it. Transition key `≼` availability key |
| `instrument_id`, `contract_scope`, `contract` | yes | Must equal the entity's. **No bridging across contracts** |
| `definition_version` | yes | Must equal the spec's |
| `source_refs` | yes | Non-empty canonical tuple of `KIND:key` strings (§0.7) |
| `reason_code` | optional | Module-owned |
| `attr_<name>` | optional | Declared in the spec, typed, required ones non-null |

**No lifecycle-specific generic fields** (`touch_count`, `consumed_at`, …)
and no source-granularity field: the SourceRef kind already captures the
source type.

### 0.6 Validation (`validate_transitions(transitions, spec, entities) -> DataFrame`)

> **Responsibility boundary (rev 3.2, D-131).** `validate_transitions`
> validates the integrity, causality, provenance and replay consistency of
> the State transition log. It does not independently re-evaluate whether
> the upstream trigger observation was eligible to interact with the
> entity. Exact trigger-observation eligibility is owned by the source
> feature / interaction module.
>
> - This is intentional architecture, not a validation omission.
> - M7 never infers tick vs bar, bar duration, `bar_start` or provider-event
>   geometry from transition metadata.
> - There is no source-duration parameter.

Invalid input raises `StateContractError`; there are no `INVALID_*`
statuses. The function returns the frame in canonical order (§0.9). It
checks:

- schema, tz-awareness and integer sequences;
- namespace and version equal the spec's;
- state membership, edge membership, and no self or terminal exits;
- the entity exists and its instrument, scope and contract match;
- transition key `≼` availability key;
- source-ref canonical form;
- recomputed SHA-256 id equality, and no duplicate ids;
- typed `attr_*` columns.

**Chain rule (per entity + namespace):**

- Ordered by transition key, the first `previous_state = initial_state` and
  each later `previous_state` equals the prior `new_state`.
- **One transition per entity + namespace + causal source event.**
  Transition keys must be strictly increasing under `≺`. Equal `at` with
  null or equal sequences is simultaneous, and therefore rejected.
- Each transition's source event must be able to consume the previous
  state: the previous transition's availability key `≺` this transition's
  key.
- So an order-dependent chain inside one simultaneous event is rejected,
  while reliably sequenced same-timestamp events may chain.
- Different namespaces are independent, and may transition on the same
  event.

**Entity applicability: retained checks.** These are universally valid
consistency checks, not trigger eligibility:

- the entity applicability record is well formed (`prepare_entities`):
  - tz-aware times, with co-null sequence pairs;
  - `valid_until > valid_from`;
  - `valid_until ≥ available_at`;
  - scope / contract rules;
- the entity exists, and the transition's instrument, scope and contract
  equal the entity's (no bridging);
- entity availability key `≺` transition key. The event that makes the
  entity known, or a simultaneous or incomparable one, cannot transition
  it;
- `transition_at ≥ valid_from`. An observation's decision instant never
  follows its event time, so this holds for ticks and for bars of any size.

**Delegated upstream (trigger-observation eligibility):**

- that the trigger observation's decision instant satisfied
  `valid_from ≤ decision < valid_until`;
- that the entity was causally available at that decision instant;
- source contract and continuity rules.

M6 owns bar / level eligibility; future tick modules own tick eligibility.

- **No upper bound on `transition_at` is checked.** `transition_at` may be
  the end of a bar whose start was still valid.
- **Exact windows are enforced by the consumers that hold a decision
  point:**
  - `state_as_of`;
  - `materialize_state_to_observations`, using each observation's decision
    key;
  - `materialize_state_to_bars`, using an explicit `bar_start` /
    `bar_interval` and the approved bar-boundary convention.

### 0.7 SourceRef and identity

- **`SourceRef(kind, key)`** is a frozen dataclass:
  - `kind` is an uppercase token, e.g. `M5_CONTEXT`, `M6_INTERACTION`,
    `TICK_INTERACTION`, `TRADE`, `QUOTE`, `BOOK_EVENT`,
    `STATE_TRANSITION`, `SIGNAL`. The set is open and only the format is
    validated;
  - `key` is a non-empty stable semantic key. Row numbers, paths and
    temporary indexes are never used.
- **`SourceRef.for_event(kind, subject, at, seq=None)`** builds keys of the
  form `subject@<canonical UTC time>[#seq]`. Examples:
  - an M6 interaction: subject = `level_id`, at = `bar_end`;
  - a tick: subject = instrument or stream, with `seq`;
  - a provider event id may be used directly as `key`.
- **Storage:** `source_refs` is a tuple of canonical strings `KIND:key`,
  sorted and unique (`canonical_source_refs`).
- **Canonical time:** UTC `YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ` (nanoseconds).
- **`transition_id`** = `"st_" + sha256(json([namespace,
  definition_version, entity_id, previous_state, new_state,
  canonical(transition_at), transition_seq|null, [source_refs…]]))`.
  - The full 256 bits are kept, with no truncation.
  - The natural-key fields stay as columns.
  - Re-runs are idempotent.

### 0.8 Visibility at a decision point

A key `K` (an entity or transition availability) is visible at decision key
`D` iff `K ≺ D`, with two exceptions:

- ~~`state_as_of` is inclusive~~. **Superseded by D-130:** `state_as_of` is
  strict, giving the state available immediately before the query point.
- **Bar-boundary convention:** only `materialize_state_to_bars` also accepts
  `K.at == D.at` when **both** keys are unsequenced. Under `BAR_END` labels a bar's decision instant (`bar_start`)
  follows the close stamped with the same label. This reproduces
  `bar_start ≥ available_at` (M5/M6) exactly.

**Consequence: the source observation that creates a transition can never
consume it.**

- Bars: the transition is available at the bar's `bar_end`, which is after
  its `bar_start`.
- Sequenced ticks: `(t, s)` is not `≺ (t, s)`.
- Unsequenced same-`at` events are simultaneous.

Only a causally later observation sees it: bar N+1, tick `(t, s+1)`, or a
later `at`.

### 0.9 Utilities

- `state_as_of(transitions, spec, entities, as_of_at, as_of_seq=None)`
  returns one row per entity:
  - `entity_id`, `namespace`, `applicable`, `state`, `transition_id`;
  - `state` is `<NA>` when the entity is not applicable;
  - it is `initial_state` before the first visible transition;
  - otherwise it is the latest transition whose availability key
    `≼ (as_of_at, as_of_seq)`.
- `materialize_state_to_observations(transitions, spec, entities,
  observations, *, boundary_inclusive=False)`:
  - observation columns: `observation_at`, `observation_seq` (optional),
    `decision_at`, `decision_seq` (optional);
  - it emits one row per (observation, applicable entity), with `state`
    and `transition_id`, using visibility at the decision key (§0.8);
  - this is the generic core.
- `materialize_state_to_bars(transitions, spec, entities, bars, *,
  bar_interval="1min")` is a convenience wrapper with
  `observation_at = bar_end` and `decision_at = bar_start`. Sequences are
  null and `boundary_inclusive=True`.
- **Ordering:** `available_at`, `available_seq`, `transition_at`,
  `transition_seq`, `namespace`, `entity_id`, `transition_id`, with null
  sequences first and a stable mergesort. Ties between simultaneous
  records are for determinism only, never chronology.
- **Nothing else:** no event bus, framework, stream processor, database or
  plugin system.

### 0.10 Ownership

**M7 owns:**

- schema, state, edge and terminal validation;
- causal validation;
- identity and ordering;
- replay and materialization.

**Modules own:**

- the vocabulary;
- transition conditions and skip-edge semantics;
- reset, expiry and terminal meaning;
- the consequences of continuity gaps (missing sessions, contract
  changes, unavailable sources), for which there is no universal
  SUSPENDED state;
- the mapping from M6 interactions to transitions. M7 never decides it.

---

**Rev 2 (2026-10-01): tick / event-granularity compatibility.** The
contracts no longer assume completed 1-minute bars. Changes:

- causal keys `(timestamp, optional sequence)` (§3a);
- one transition per causal source event (§9);
- generic observation alignment with a bar wrapper (§18);
- source refs that are not bar-specific (§16).

M5 and M6 are unchanged.

Related: [M6_LEVEL_INTERACTIONS_SPEC](M6_LEVEL_INTERACTIONS_SPEC.md) ·
[M5_MARKET_CONTEXT_SPEC](M5_MARKET_CONTEXT_SPEC.md) ·
[DECISION_LOG](DECISION_LOG.md) (D-110–D-128) ·
[QUALITY_CONTROL](QUALITY_CONTROL.md).

**Prerequisites verified (2026-10-01):**

- `main` = `0d0e917` (PR #6 merged): M5 Generic Market Context and M6
  Generic Level Interactions (M6A + M6B) are complete.
- Branch `m7-state-signal-contracts` from `origin/main`, clean tree.
- Baseline: 400 passed (see WORK_PROGRESS).

**Layering this spec assumes:**

```
Validated data → Feature catalog (M5 …) → Interaction catalog (M6)
  → State transitions (M7A envelope; module-owned rules)
  → Signals (M7B envelope; definition-owned semantics)
  → Strategy → Execution
```

M7 defines **envelopes and validation only**. It owns no lifecycle
vocabulary, no transition rules, and no signal semantics.

---

## 1. Existing state / signal-like patterns in the repository

Read-only inspection. Nothing was modified.

| # | Where | Pattern |
|---|---|---|
| P1 | `…london_interaction_event_characterization.first_interaction_timestamps` | First touch / first strict trade-through bar-end within the OR (left in ORB by M6B) |
| P2 | same script: `first_trade_through_state_knowledge = "RETROSPECTIVE_DESCRIPTIVE"`, `or_close_state_knowledge = "CAUSAL_STATE_KNOWN"`, `interaction_state_confirmation_timestamp`, `acceptance_confirmation_timestamp`, `eventual_state_known_at_first_trade_through = False` | Explicit separation of *when something happened* from *when the state became knowable* |
| P3 | same script: `derive_frozen_interaction_state`; `…key_level_interaction_characterization.derive_interaction_category` with `STATE_PRECEDENCE = (SWEEP, REJECTION, CLOSE_THROUGH, TOUCH_ONLY, NO_INTERACTION)` | One categorical label from several simultaneous primitives, by declared precedence |
| P4 | `research_viewer.find_orb_signals` | First-per-direction ORB breakout events (`signal_time`, `direction` LONG/SHORT, `ambiguity_status`). Two-sided PRINT bars are excluded as `AMBIGUOUS (LONG+SHORT)` instead of inventing order. It also hard-codes an eligibility window (`OR end + 1 min` … `ENTRY_CUTOFF 11:30`) |
| P5 | `backtesting.candidate_entries.build_candidate_entries` | Signal → candidate: `entry_price`, `initial_stop`, `initial_target`, `risk_points`, `candidate_validity` |
| P6 | `backtesting.completed_trades` | Exits; `AMBIGUOUS_STOP_TARGET` / `AMBIGUOUS_ENTRY_STOP` when OHLC cannot order events |
| P7 | `backtesting.session_trade_limit` | One trade per session: `EXECUTED` / `REJECTED` / `INVALID_CANDIDATE`, `session_trade_taken` |
| P8 | `backtesting.orb_v01.Breakout` dataclass | Mixes event (`direction`, `timestamp`) with execution (`entry`, `entry_at_open`) |
| P9 | `…combined_state_hypothesis.STATE_GROUPS` / `assign_combined_states` | Research "state" labels from width percentile × efficiency quintile |
| P10 | `…room_to_level_characterization` (`NO_LEVEL_AHEAD` / `KNOWN_LEVEL_AHEAD`), `stage3a.room_to_next_level` | Per-event descriptive categories |
| P11 | `…london…`: `interaction_direction`, `hypothesis_directional_context`, `orb_confirmation_group` | Hypothesis-specific direction and grouping |
| P12 | `session_context.align_market_context` statuses (`AVAILABLE`, `PENDING`, `UNAVAILABLE_CONTEXT`, `CONTRACT_MISMATCH`); M6 `PENDING_LEVEL` | Per-bar causal *visibility*; not lifecycle state |
| P13 | `mnq_orb_v02_features`: `*_feature_available`, `*_missing_reason`, `or_available_at` | Feature availability metadata |

## 2. Classification

Classes: **A** objective state · **B** objective event / signal ·
**C** strategy eligibility · **D** execution / order logic ·
**E** research / audit metadata.

| # | Class | Note |
|---|---|---|
| P1 | **A** (stateful "first …") + **E** | A genuine stateful concept ("has this level been touched yet?"). Today it is computed retrospectively inside one OR window, for audit. |
| P2 | **E**, and an important **design precedent** | It already distinguishes event time from knowledge time. This directly motivates `transition_at` ≠ `available_at` (§7). |
| P3 | **E** (analysis label) | Precedence-collapsing is acceptable for labelling, but not as generic state (§9). |
| P4 | **B** + **C** | The breakout is an objective event (B). "First per direction" and the 11:30 window are strategy eligibility (C). `LONG`/`SHORT` is action vocabulary; M7 uses BULLISH/BEARISH (§12). |
| P5, P6 | **D** | Out of M7 scope; the boundary is already clean (candidates consume signals). |
| P7 | **C** + **D** | Strategy / execution bookkeeping. |
| P8 | **B** + **D** mixed | An example of what the Signal contract must forbid (§15). |
| P9, P10 | **E** | Research classification. Not lifecycle; not migrated. |
| P11 | **C** + **E** | Hypothesis-specific. |
| P12 | Causal visibility (not A) | Per-bar *views*. M7's materialization (§18) produces the same kind of view for state. |
| P13 | **E** / feature metadata | Stays with features. |

**What this tells the design:**

- The repository has no generic state at all; "state" today means either
  per-event labels (E) or ORB bookkeeping (C/D).
- Three existing practices are worth keeping:
  - P2: event time vs knowledge time;
  - P4 and P6: refuse to invent intrabar order and mark ambiguity
    instead;
  - P5: signal and execution are already separated.
- None of these structures should be reproduced generically.

## 3. Architectural boundaries

| Layer | Owns | Must not contain |
|---|---|---|
| Feature (M5 …) | Entities and their static applicability (`valid_from` / `valid_until`) | History-dependent condition |
| Interaction (M6) | Per-bar objective facts versus a known feature | Memory across bars |
| **State (M7A envelope)** | How *any* history-dependent condition is recorded, validated, ordered and replayed | Any specific vocabulary or rule |
| State module (future, e.g. liquidity) | Allowed states, allowed transitions, conditions, reset / expiry | Strategy choices |
| **Signal (M7B envelope)** | How *any* immutable market event is recorded, validated and referenced | Trade instructions; specific semantics |
| Signal definition (future) | When the event occurs, its direction and attributes | Order fields |
| Strategy | Selection, combination, eligibility windows, "use for N bars" | — |
| Execution | Entry, stop, target, size, management | — |

## 3a. Causal event model (rev 2)

M7 is designed around **generic causal observations**, not bars.

- Today's inputs are completed OHLC bars (any timeframe).
- Future inputs may be ticks, trades, quotes, order-book events or other
  ordered market events.

**Causal key.** Every causal instant in M7 is a pair:

```text
K = (at, seq)
  at  : tz-aware timestamp (required)
  seq : optional stable integer ordering value for events sharing `at`;
        <NA> when no reliable sequence exists (all current bar workflows)
```

**Strict precedence** `A ≺ B` ("A is causally earlier than B") holds iff:

1. `A.at < B.at`; or
2. `A.at == B.at` **and** both `A.seq` and `B.seq` are non-null **and**
   `A.seq < B.seq`.

Every other same-timestamp pair is **simultaneous**: either sequence is
null, or the sequences are equal. Simultaneous events are unordered, and
M7 never orders them.

**Not-later-than** `A ≼ B` is defined as `¬(B ≺ A)`: A precedes B or is
simultaneous with it. It is used for "available no earlier than
confirmed" checks.

- **The same wall-clock timestamp is not automatically simultaneous.** A
  reliable sequence orders events.
- **Sequences compare only within one sequence domain**, e.g. one feed's
  trade sequence. M7 cannot verify the domain; the module that emits
  sequenced records must use one consistent domain per instrument stream.
  Whether to record the domain explicitly is question Q13.
- **Intrabar order is still never invented.** An OHLC bar is one causal
  event, with `seq = <NA>`.

Where the keys apply:

| Record | Keys |
|---|---|
| Source event / observation | `event_at`, `event_seq` |
| StateTransition | `transition_at`, `transition_seq`; `available_at`, `available_seq` |
| Signal | `event_at`, `event_seq`; `available_at`, `available_seq` |
| Observation, for alignment (§18) | `observation_at`, `observation_seq`; `decision_at`, `decision_seq` |

**Self-consumption rule.** An observation may never consume a transition it
created; only a causally later observation may consume it.

- This follows from the precedence rule. A transition created by event `E`
  has an available key no earlier than `E`'s key. An observation's decision
  key does not strictly follow its own event key, so the transition is
  never visible to `E` itself (§18).

**M5 and M6 are unchanged.** M5 stays the generic Market Context
implementation, and M6 stays the completed-OHLC-bar interaction engine.
Future tick-level interaction modules would emit the same kinds of causal
facts and feed the same State/Signal contracts.

## 4. Proposed State Transition schema

**Canonical representation: a transition log.** One row per state change.
Per-bar state is a **derived view** (§18).

Evaluation against the repository:

- **Auditability and causality.** Each change carries its own knowledge
  time and sources, extending the P2 practice.
- **Size.** Future lifecycles (levels, FVGs, swings) change rarely relative
  to bars. Snapshots would repeat identical rows: about 3.4M M6 pairs
  versus a few thousand transitions.
- **Replay and debugging.** Replay is deterministic, and "why is X SWEPT?"
  is answered by one row.
- **Strong reason against?** None found. Consumers that need per-bar state
  (backtests, viewers) get it from `materialize_state_to_bars`, exactly as
  M5 offers `align_market_context` beside its summary.

**`StateTransition` columns:**

| Column | Req. | Type | Meaning |
|---|---|---|---|
| `transition_id` | yes | str | Deterministic (§10) |
| `state_namespace` | yes | str | Module-owned vocabulary key, e.g. `liquidity.lifecycle`, `fvg.lifecycle`. Dotted lowercase; M7 validates the format only |
| `entity_id` | yes | str | Deterministic id of the entity (e.g. an M6 `level_id`), created by the owning module |
| `previous_state` | yes | str | **Rev 3:** non-null. The first transition starts from the namespace's `initial_state`; there is no creation transition (§0.3) |
| `new_state` | yes | str | Must be in the namespace's declared states |
| `transition_at` | yes | tz-aware ts | When the change is confirmed by evidence (§7): the confirming source event's `at` |
| `transition_seq` | optional | Int64 | The confirming source event's `seq`; `<NA>` for bar inputs (§3a) |
| `available_at` | yes | tz-aware ts | When consumers may know it |
| `available_seq` | optional | Int64 | Sequence of the availability instant; `<NA>` for bar inputs. The availability key must not precede the transition key: `(transition_at, transition_seq) ≼ (available_at, available_seq)` |
| `instrument_id` | yes | str | As in M6 |
| `contract_scope` | yes | `SPECIFIC` / `AGNOSTIC` | As in M6 (D-126 #8) |
| `contract` | iff SPECIFIC | str | As in M6 |
| `definition_version` | yes | str | Version of the module rules that produced it |
| `source_refs` | yes (≥ 1) | tuple[str] | Typed stable references (§16) |
| `reason_code` | optional | str | Module-owned short code, e.g. `M6_SWEEP`, `SOURCE_UNAVAILABLE` |
| `attr_*` | optional | typed | Module-declared typed attributes (§17) |

**Deliberately omitted:**

- **`entity_type`:** the namespace already identifies the module and entity
  kind, so a second label would be redundant. Its reintroduction is
  question Q9.
- **`source_type` / `source_event_id`:** folded into typed `source_refs`.
- **A free-form `metadata` dict:** replaced by declared `attr_*` columns.

## 5. State vocabulary ownership

- Each module declares a frozen spec. M7 defines the **shape** of the spec,
  never its contents:

  ```text
  StateNamespaceSpec (frozen dataclass)
    namespace: str                      # "liquidity.lifecycle"
    definition_version: str
    states: tuple[str, ...]             # module vocabulary
    initial_state: str                  # rev 3: single, required; no creation transition (§0.3)
    entity_kind: str                    # rev 3
    transitions: frozenset[tuple[str, str]]   # allowed (from, to), including skip edges
    terminal_states: tuple[str, ...]    # no transition may leave these
    attributes: tuple[AttributeSpec, ...]     # §17; may be empty
  ```

- There is **no global vocabulary**: `UNTOUCHED`, `SWEPT`, `FILLED` and
  `INVALIDATED` appear only in examples.
- Two namespaces may reuse a word (e.g. `INVALIDATED`) with different
  meanings. They never interact because the namespace is part of every key.
- **Primary lifecycle vs attributes (prompt §7).** Recommend the smallest
  disciplined model:
  - one **primary state value** per (`entity_id`, `state_namespace`);
  - a module that needs an independent second state variable declares a
    **second namespace** (e.g. `fvg.lifecycle` and `fvg.fill`) rather than
    a composite state;
  - auxiliary *quantities* (`touch_count`, `last_interaction_at`,
    `penetration_ticks`) are **not state**. They are either derived on
    demand from the M6 interaction log (counts, last-touch time), or carried
    as declared `attr_*` on the transition that records them.
  - Whether a pure attribute change with no state change may emit an
    `A → A` self-transition is question Q3.

## 6. Transition ownership

| M7 provides (generic) | Module provides (specific) |
|---|---|
| Schema / dtype validation | `StateNamespaceSpec` |
| Membership: `new_state ∈ states`; `(previous, new) ∈ transitions`; the first transition leaves `initial_state` (rev 3); nothing leaves `terminal_states`; no self transitions | The pure function that turns its inputs (features, M6 interactions, other transitions) into transition rows |
| **Chain continuity:** per (entity, namespace), each `previous_state` equals the prior row's `new_state` | Conditions, e.g. what SWEEP means for a level |
| Causal checks (§7); contract consistency per entity (§8) | Reset / expiry / end-of-applicability rules |
| Deterministic ids (§10) and ordering (§20) | `reason_code` vocabulary |
| `state_as_of`, `materialize_state_to_bars` (§18) | — |

**Interface:** plain functions and data, with no callbacks, registries or
base classes.

```text
module:  build_<x>_transitions(inputs…) -> DataFrame    # emits envelope rows
M7:      validate_transitions(frame, spec) -> DataFrame # raises on violation; returns canonical order
```

## 7. Causality semantics

- **Transition key** `(transition_at, transition_seq)` is the key of the
  causal source event that **confirms** the change.
  - For a bar-close-confirmed change it is `(bar_end, <NA>)`.
  - For a future tick it is that tick's `(at, seq)`.
  - It is never an intrabar estimate and never back-dated. A
    retrospectively knowable event time (P2, `RETROSPECTIVE_DESCRIPTIVE`)
    belongs in a feature or `attr_*`, not in the transition key.
- **Availability key** `(available_at, available_seq)` is when downstream
  consumers may know the change.
  - Transition key `≼` availability key.
  - They are equal for bar-close or tick confirmation, and later when a
    source became available later (e.g. an M5 context).
  - Both fields are required separately even when equal, because their
    meanings differ.
- **Consumption rule** (generic, §18): an observation may use the new
  state only if the availability key `≺` the observation's decision key.
  Consequences:
  - Bars use the declared bar-boundary convention (§18): a bar may use the
    new state iff `bar_start ≥ available_at`. This is the M5/M6 rule,
    unchanged.
  - The confirming bar or tick therefore never consumes its own
    transition.
  - A same-timestamp unsequenced event never consumes it.
  - A later-sequenced event at the same timestamp may consume it.
- **Validation (M7):**
  - transition key `≼` availability key;
  - per entity and namespace, transition keys are **strictly increasing**
    under `≺` (§9);
  - every **evidence** source (feature, interaction, market event)
    referenced by a transition is not later than its transition key
    (`source ≼ transition`);
  - every **consumed-state** source (another `transition`) is strictly
    earlier: its availability key `≺` the referencing transition's key.
    This forbids ordering-dependent chains within one simultaneous event;
  - the source checks run when the caller supplies the referenced records
    (§16). Otherwise they are the module's responsibility, and the docs say
    so.

## 8. Applicability / reset semantics

- **Static applicability belongs to the entity (the feature record), not to
  the transition.** M6 already models this with `valid_from` /
  `valid_until` on levels (D-127). Transitions carry no `valid_from` /
  `valid_until`.
- **Reset and expiry are module transitions.** M7 has no global "reset each
  session" or "persist forever". A module that ends an entity's life emits
  its own transition (e.g. `→ EXPIRED`) at its own causal time, with a
  `reason_code`.
- **Continuity / contract gaps (D1 deferred).** The boundary:
  - **M7 enforces** that one entity has one `contract_scope` / `contract`
    for its whole history (no silent bridging). It also requires that no
    transition be sourced from an M6 row with status ≠ `EVALUATED` /
    `AMBIGUOUS_APPROACH`, when the source records are supplied.
  - **The module decides** the lifecycle consequence of a missing expected
    session, a contract change, a contract mismatch or an unavailable
    source. It might end the entity, stop evaluating it, or ignore the gap
    if its definition allows. It records that decision with `reason_code`
    and `source_refs`.
  - **No universal `SUSPENDED` state.** Nothing found in the repository or
    in the planned families needs a shared one. A module that needs it
    declares it in its own namespace.

## 9. Multiple transitions per causal event (rev 2)

**Generic rule:** at most **one transition per (`entity_id`,
`state_namespace`, causal source event)**. Equivalently, per entity and
namespace, transition keys must be strictly increasing under `≺` (§3a).

| Inputs | Effect |
|---|---|
| Completed OHLC bars (`seq = <NA>`) | One transition per entity, namespace and bar, identical to the rev 1 bar rule. Two transitions at the same `transition_at` are simultaneous, so validation fails. |
| Future sequenced ticks | Two ticks with the same timestamp and distinct reliable `seq` are distinct ordered events, and may legitimately produce two ordered transitions. |
| Same timestamp, sequence missing on either side | Simultaneous, so validation fails. Ordering-dependent chains are forbidden. |

The bar case below is unchanged.

The case: a level is `UNTOUCHED` before a bar, and the bar trades through
and closes back. That bar is TOUCH and SWEEP at once.

| Option | Records | Assessment |
|---|---|---|
| **(1) One transition per bar: the final state only** | `UNTOUCHED → SWEPT` at `bar_end` | Invents no chronology. The intermediate fact (touch) stays visible through `source_refs` to the M6 row (touch = True, sweep = True). The module must declare the skip edge `(UNTOUCHED, SWEPT)`. **Recommended.** |
| (2) Implied chain at the same timestamp | `UNTOUCHED → TOUCHED`, `TOUCHED → SWEPT`, both at `bar_end`, with a step ordinal | The ordinal reads as chronology OHLC cannot prove (cf. P4 and P6, which refuse to order same-bar events). It doubles rows and complicates `state_as_of` at equal timestamps. |
| (3) Module-chosen policy | Either option per module | More flexible, but every consumer must then know which policy each namespace uses. Not needed by any planned family. |

**Recommendation: (1).** At most one transition per (`entity_id`,
`state_namespace`, causal source event), and M7 validates it via strictly
increasing keys. The module
computes the end-of-bar state from that bar's objective facts. It may use a
declared precedence internally, as P3 does for labels, but it records only
the result. Signals are separate: a module may still emit several signals
for the same bar (e.g. one for the touch and one for the sweep), because
signals are point events and do not imply order (§13).

## 10. Deterministic transition identity

- **Natural key:** (`state_namespace`, `definition_version`, `entity_id`,
  `transition_at`, `transition_seq`). This is unique by the
  one-per-causal-event rule (§9). The instrument and contract are already
  implied by `entity_id`, which the module builds deterministically, as
  M6's `level_id` is.
- **Superseded by §0.7 (rev 3).** The id is the **full** SHA-256 over
  namespace, version, entity, previous and new state, transition key and
  canonical source refs. The text below is the rev 2 reasoning.
- **`transition_id`** = `"st_" + sha256(canonical natural key)[:20]`:
  - the canonical key is a `|`-joined string, with `transition_at` in UTC
    ISO-8601 at nanosecond resolution and `transition_seq` as a decimal
    integer or the literal `NA`;
  - the natural-key columns stay in the record, so the id is inspectable
    and recomputable;
  - no random UUIDs.
- **Duplicate natural keys** in one frame raise an error. An identical
  re-run gives identical ids (idempotent). Changed rules require a new
  `definition_version` and therefore produce new ids.

## 11. Proposed Signal schema

A Signal is an **immutable point event**: *what happened*, never *what to
do*.

| Column | Req. | Type | Meaning |
|---|---|---|---|
| `signal_id` | yes | str | Deterministic (§15) |
| `signal_type` | yes | str | Definition-owned, dotted lowercase, e.g. `liquidity.sweep` |
| `definition_version` | yes | str | — |
| `subject_id` | yes | str | Primary entity the event is about (a level, FVG, swing …) |
| `event_at` | yes | tz-aware ts | Confirmation time of the event (same rule as `transition_at`) |
| `event_seq` | optional | Int64 | Confirming source event's sequence; `<NA>` for bar inputs (§3a) |
| `available_at` | yes | tz-aware ts | — |
| `available_seq` | optional | Int64 | Event key `≼` availability key |
| `instrument_id` | yes | str | — |
| `contract_scope` / `contract` | yes / iff SPECIFIC | — | As in M6 |
| `direction` | optional | `BULLISH` / `BEARISH` / `NEUTRAL` / `<NA>` | §12 |
| `source_refs` | yes (≥ 1) | tuple[str] | Features, M6 interactions, transitions, other signals (§16) |
| `attr_*` | optional | typed | Definition-declared (§17) |

The definition spec mirrors §5:

```text
SignalDefinitionSpec (frozen dataclass)
  signal_type, definition_version,
  directions: tuple[str, ...]     # allowed subset of {BULLISH, BEARISH, NEUTRAL}; empty = undirected
  attributes: tuple[AttributeSpec, ...]
```

- **Sources are open.** A signal may come from one feature, one M6 row, one
  transition, or several. It is **not required to originate from State**.
- **Forbidden columns (§15)** are rejected by validation.

## 12. Direction semantics

- Controlled vocabulary `BULLISH` / `BEARISH` / `NEUTRAL`, **optional**.
- The definition declares which values it may emit:
  - `<NA>` means the signal type is undirected;
  - `NEUTRAL` is reserved for directional definitions whose particular
    event carried no direction.
- **Direction describes the market event, not an action.** BULLISH ≠ buy and
  BEARISH ≠ sell. The legacy ORB `LONG` / `SHORT` (P4) is action vocabulary
  and is not adopted. The strategy maps direction to action.

## 13. Signal causality

- The event key `(event_at, event_seq)` is evidence confirmation: for a bar
  close, `(bar_end, <NA>)`. It is never an intrabar estimate. Event key
  `≼` availability key.
- A consumer may act on a signal only if its availability key `≺` the
  consumer's decision key, the same rule as State (§18). For bars this is
  `bar_start ≥ available_at`, the M5/M6/M7A rule.
- Several signals may share an event key. Simultaneous signals are
  unordered; any sort among them is for determinism only (§20).
- **A signal is a derivation, not a consumer of state.** It may therefore
  be derived from a transition at the **same** causal event: e.g. a
  "sweep" signal describing a SWEPT transition confirmed by the same bar.
- **Validation:** every referenced source must be available not later than
  the signal (source availability key `≼` signal availability key). This
  is checked when the source records are supplied (§16).

## 14. Signal lifetime semantics

- Signals have **no ACTIVE / EXPIRED state** and no `valid_from` /
  `valid_until`. "Use this signal for the next 5 bars" is strategy logic.
- A signal whose *subject* has a lifetime (e.g. an FVG that stays open)
  expresses that through the subject's state transitions (M7A), not through
  the signal.
- **Recommendation: defer validity intervals.** None of the planned families
  needs them once entity applicability (§8) and state (M7A) exist. Adding
  them later is backward compatible (new optional columns). This is Q4.

## 15. Deterministic signal identity

- **Natural key:** (`signal_type`, `definition_version`, `subject_id`,
  `event_at`, `event_seq`, `direction`).
  - `direction` is included because one definition may emit both
    directions for one subject and time.
  - `<NA>` (for direction or `event_seq`) is encoded as the literal `NA` in
    the key.
- **`signal_id`** = `"sg_" + sha256(canonical key)[:20]`. The key columns
  stay in the record. Duplicate keys raise an error, and re-runs are
  idempotent.
- **Signals are events, not orders.** Validation rejects these columns
  (exact names, and the same names behind the `attr_` prefix): `entry_price`,
  `stop_loss`, `stop`, `initial_stop`, `take_profit`, `target`,
  `initial_target`, `position_size`, `size`, `quantity`, `order_type`,
  `risk`, `risk_points`, `r_multiple`, `trade_id`.
- **Objective reference prices remain allowed.** If an event naturally has
  one, it is exposed as objective metadata, e.g. `attr_sweep_extreme_price`,
  never as an instruction.

## 16. Provenance / source-reference design

**Rev 3:** these kinds are realised as `SourceRef(kind, key)` with
uppercase kinds (`M5_CONTEXT`, `M6_INTERACTION`, `TICK_INTERACTION`,
`TRADE`, `QUOTE`, `BOOK_EVENT`, `STATE_TRANSITION`, `SIGNAL`). They are
stored canonically as `KIND:key` (§0.7). The lowercase kinds in the table
below are the rev 2 draft.

**Goal:** a researcher can answer "why does this record exist?" without
reverse-engineering a strategy.

- Each reference is a **typed string** `<kind>:<stable key>`. It never
  points to a DataFrame row number or a file path.
- **References are not bar-specific (rev 2).**
  - M7 validates only the format: a kind matching `[a-z][a-z0-9_.]*`, then
    `:`, then a non-empty key.
  - The kinds below are the documented initial set. A future module may
    introduce a new kind without changing M7 by documenting it.
  - Keys must be semantic and stable: an entity id, or a natural key of
    `(stream, at, seq)` form.

  | Kind | Key | Example |
  |---|---|---|
  | `context` | M5 context natural id `context_id:field:target_date` | `context:previous_day:low:2024-12-10` |
  | `level` | level / feature entity id (e.g. M6 `level_id`) | `level:previous_day:low:2024-12-10` |
  | `bar_interaction` | M6 natural key `level_id@bar_end_utc` | `bar_interaction:previous_day:low:2024-12-10@2024-12-10T14:31:00Z` |
  | `tick_interaction` *(future)* | `level_id@at_utc#seq` | `tick_interaction:…@2027-01-05T14:31:07.123456789Z#88123` |
  | `trade`, `quote`, `book` *(future)* | `stream@at_utc#seq` (feed / instrument stream) | `trade:MNQZ6.CME@…Z#88123` |
  | `bar` | `stream@bar_end_utc` (a whole-bar observation) | `bar:MNQ.1m@2024-12-10T14:31:00Z` |
  | `transition` | `transition_id` | `transition:st_1f…` |
  | `signal` | `signal_id` | `signal:sg_9a…` |

- `#seq` is omitted when the sequence is `<NA>`.
- **Evidence vs consumed state** is decided by kind. `transition` is
  consumed state for a StateTransition, so the strict `≺` rule of §7
  applies; every other kind is evidence (`≼`).
- **M5 and M6 need no change.** M6 rows are identified by the natural key
  (`level_id`, `bar_end`), which is unique by construction.
- **Storage:** `source_refs` is a tuple of strings per record (Parquet
  `list<string>`). A long "edges" table is rejected as unnecessary.
- **Optional causal check:** when the caller supplies the referenced frames,
  `validate_*` resolves each reference and checks
  `source.available_at ≤ record.available_at`. Unresolvable references
  raise an error only in that mode.

## 17. Extensible payload approach

This sits between a rigid wide schema and an untyped dict. The pattern is a
**generic envelope plus definition-declared typed `attr_*` columns**.

- `AttributeSpec(name, dtype, required, description)` is a frozen dataclass.
  Its dtype is one of `Int64`, `Float64`, `boolean`, `string`, or a
  tz-aware timestamp.
- **The envelope validator checks:**
  - every non-envelope column starts with `attr_`;
  - each `attr_*` column is declared by that namespace's or signal type's
    spec;
  - dtypes match;
  - required attributes are non-null.
- One frame holds records of one namespace or one signal type. Combining
  types is a plain `concat`, with sparse `<NA>` attribute columns.
- **Future data** (`penetration_ticks`, `sweep_price`, `gap_size`,
  `swing_strength`) is added by declaring an `AttributeSpec` in the new
  module, with no change to M7.
- **Rejected alternative:** a `dict` / JSON `attributes` column. It is
  untyped, hard to query in pandas, and easy to abuse. The choice is Q8.

## 18. Replay / materialization recommendation

**Rev 3:**

- The generic core is named `materialize_state_to_observations`. All
  utilities also take the namespace spec and the entity frame (§0.9).
- `state_as_of` is inclusive at the query point, and never returns a state
  outside entity applicability.

Small, pure functions. There is no event-sourcing framework. The core
alignment is **observation-generic** (rev 2), and bars are a thin wrapper.

| Function | Purpose | Two-family test |
|---|---|---|
| `validate_transitions(frame, spec, *, sources=None)` | Schema, membership, chain continuity, one-per-causal-event, causality, ids; returns canonical order | Every module |
| `state_as_of(transitions, as_of, as_of_seq=None)` | State per (entity, namespace) from transitions whose availability key `≼ (as_of, as_of_seq)`: "what is known at this instant" | Liquidity, FVG, swings |
| `align_state_to_observations(transitions, observations)` | **Generic core.** For each observation row, the state visible at its **decision key** `(decision_at, decision_seq)`: the last transition whose availability key `≺` the decision key | Bars today; ticks / quotes later |
| `materialize_state_to_bars(transitions, bars, *, bar_interval)` | **Bar wrapper.** Builds observations with `observation_at = bar_end` and `decision_at = bar_start`, then calls the core under the bar-boundary convention | Backtests, viewers |

**Observation frame** (input to the core):

| Column | Req. | Meaning |
|---|---|---|
| `observation_at` | yes | Time the observation is complete (bar: `bar_end`; tick: tick time) |
| `observation_seq` | optional | Sequence within `observation_at` |
| `decision_at` | yes | The instant at which a consumer acting on this observation decides (bar: `bar_start`; tick: tick time) |
| `decision_seq` | optional | Sequence within `decision_at` (tick: the tick's own `seq`) |

**Visibility rule:** a transition is visible to an observation iff its
availability key `≺` the observation's decision key (strict, §3a).

- **Ticks / sequenced events.** A tick at `(t, s)` creates a transition
  available at `(t, s)`. The same tick's decision key `(t, s)` is
  simultaneous with it, so the transition is not visible (no
  self-consumption). A later tick `(t, s+1)` sees it. An unsequenced tick at
  `t` does not see it, because they are simultaneous.
- **Bars (declared bar-boundary convention).** With `BAR_END` labels, a
  bar's `decision_at = bar_start` is the same timestamp label as the
  previous bar's close (`available_at = bar_end`). Under the strict generic
  rule, equal unsequenced timestamps are simultaneous, which would hide
  every bar-close transition from the next bar. Resolution:
  - The labelling convention already places a bar's decision **after** the
    close stamped with the same label; this is the M5/M6 rule
    `bar_start ≥ available_at`.
  - The bar wrapper therefore calls the core with
    `boundary_inclusive=True`, which makes an equal-timestamp,
    **unsequenced** availability visible at the decision.
  - This is the only exception, it is confined to the wrapper, and it
    reproduces the existing rule exactly. A bar's own transition (available
    at its `bar_end`, which is after its `bar_start`) is still never
    visible to that bar. Question Q12 asks you to ratify this.
- **Inclusive vs strict in one sentence:** generic observations are strict;
  bar decisions sit on a boundary that, by convention, follows the closes
  labelled at that instant.

- `validate_signals(frame, spec, *, sources=None)` is the M7B counterpart.
- **Not recommended:**
  - `apply_state_transitions`: modules build rows directly;
  - `current_state`: this is `state_as_of(…, as_of=max)`;
  - a separate tick-specific alignment: the generic core already covers it;
  - any generic state-machine runner.

## 19. M7A implementation plan (after approval)

New package `src/state/` (a new layer, not `src/features/`):

- `src/state/contract.py`:
  - `StateNamespaceSpec` and `AttributeSpec`;
  - schema constants;
  - `transition_id()`;
  - the causal-key helpers (`precedes`, `not_later_than`) implementing §3a;
  - `validate_transitions()`;
  - `state_as_of()`, `align_state_to_observations()` (generic core) and
    `materialize_state_to_bars()` (bar wrapper);
  - a `StateContractError(ValueError)`.
- Tests: `tests/test_state_contract.py`. These use synthetic namespaces
  defined **inside the test file only**; no real lifecycle is shipped.
- Docs: spec status update, DECISION_LOG entry, governance.

## 20. M7B implementation plan (after M7A)

- `src/signals/contract.py`:
  - `SignalDefinitionSpec`;
  - `signal_id()`;
  - `validate_signals()`;
  - the direction vocabulary;
  - the forbidden-field list;
  - `SignalContractError`.
- Shared helpers live in one small module (`src/state/contract.py`
  exports them, or `src/catalog_contract.py`), with no duplication:
  - typed references: one generic `source_ref(kind, key)` plus format
    validation; there are no per-kind helper functions until a second user
    exists;
  - the causal-key comparison (§3a);
  - the `attr_*` validator;
  - the scope / contract checks.
- Tests: `tests/test_signal_contract.py`, with synthetic definitions only.
- **Ordering (both contracts):** canonical sort by
  1. `available_at`, then `available_seq` (`<NA>` sorts first);
  2. `transition_at` / `event_at`, then `transition_seq` / `event_seq`
     (`<NA>` first);
  3. `state_namespace` / `signal_type`;
  4. `entity_id` / `subject_id`;
  5. id;

  using a stable mergesort.
  - Records at the same timestamp with reliable sequences are in true
    causal order.
  - Records whose keys are simultaneous (§3a) remain causally unordered;
    the tiebreak exists only for determinism and must never be read as
    chronology.
  - Within one entity and namespace no simultaneous pair can exist,
    because §9 forbids it.
- **M7C (migration): not required.** See §21.

## 21. Possible migration candidates (none migrated)

| Candidate | Likely future home | When |
|---|---|---|
| P1 first touch / first trade-through | A liquidity / level-lifecycle module, as transitions of a level namespace (`UNTOUCHED → TOUCHED` …) built from M6 rows | When that catalog feature is built. The London script stays frozen. |
| P4 ORB breakout event | A possible `orb.breakout` signal definition (BULLISH/BEARISH), with "first per direction" and the window kept in strategy | Only if ORB research resumes. ORB is parked. |
| P3 precedence category | Remains an analysis label. It could inspire a module's internal precedence (§9) | — |
| P5–P8 | Execution / strategy. Not M7 | — |
| P9–P11, P13 | Research / feature metadata. Not M7 | — |

No code moves for tidiness. Frozen ORB keeps its structures.

## 22. Unit-test plan

**State (M7A)**, using a synthetic `test.lifecycle` namespace defined in the
test file:

- **Deterministic ids:** reproducible, sensitive to every key component,
  inspectable from columns.
- **Valid ordering:** the canonical sort is order-independent of the input.
- **Duplicate handling:** a duplicate natural key raises an error; an
  identical rerun is idempotent.
- **Chain continuity:** a `previous_state` gap raises an error, as does a
  creation row without `<NA>` or a creation row outside `initial_states`.
- **Module-owned validation:** a disallowed edge, an unknown state, or a
  transition out of a terminal state raises an error. Skip edges are
  allowed only if declared.
- **One transition per causal event:**
  - two transitions at the same `transition_at` with `<NA>` seq raise an
    error (bar case; the "no invented intrabar chronology" guard);
  - same timestamp with distinct sequences validates and orders by
    sequence (tick case);
  - same timestamp with one null and one non-null sequence raises an error;
  - same timestamp with equal sequences raises an error.
- **Causal-key comparison (§3a):** a truth table for `≺` and `≼` over
  (different at), (equal at, both seq), (equal at, a null seq), (equal at,
  equal seq).
- **Chain dependency:** a transition citing a `transition` source available
  at a simultaneous key raises an error. A strictly earlier one is
  accepted. An evidence source at the same key is accepted.
- **Causality:**
  - `available_at < transition_at` raises an error;
  - a source available later than the record raises an error in sources
    mode;
  - the confirming bar does not see the new state in
    `materialize_state_to_bars`, and the next bar does. This is identical to
    `bar_start ≥ available_at`, including a mid-bar `available_at`;
  - generic alignment with sequenced observations: the creating tick
    `(t, s)` does not see the transition, the next tick `(t, s+1)` does,
    and an unsequenced tick at `t` does not;
  - `boundary_inclusive` changes visibility only for an equal-timestamp,
    unsequenced pair. It never makes a bar's own transition visible to that
    bar.
- **`state_as_of`:**
  - before, at and after `available_at`;
  - uses knowledge time, not `transition_at`, when they differ.
- **Independence:** two entities evolve independently; two namespaces on
  one entity are independent; the same state word in two namespaces is
  allowed.
- **Contract:** a contract change within one entity raises an error; a
  SPECIFIC row without a contract raises; an AGNOSTIC row with a contract
  raises.
- **Negative schema:**
  - missing columns;
  - naive timestamps;
  - a non-integer `*_seq`;
  - an undeclared `attr_*`;
  - a non-`attr_` extra column;
  - a wrong attribute dtype;
  - a missing required attribute;
  - empty `source_refs`;
  - malformed refs;
  - a bad namespace format.

**Signal (M7B)**, using synthetic definitions in the test file:

- deterministic ids and idempotent reruns; duplicate keys raise an error;
- directional and neutral signals; a direction outside the definition's set
  raises; an undirected definition requires `<NA>`;
- a signal sourced directly from an M6 interaction ref (no State involved);
- a signal from a transition ref, including one confirmed by the same causal
  event (a derivation is allowed at `≼`);
- `event_seq` participates in the id; sequenced same-timestamp signals for
  one subject are distinct;
- non-bar source refs (`trade:…#seq`, `tick_interaction:…`) pass format
  validation;
- a signal with multiple sources;
- causal availability: `available_at < event_at` raises; a source
  available later raises; same-bar consumption is blocked by the bar rule
  (documented helper check);
- same-timestamp signals ordered deterministically, with no implied
  chronology;
- **no execution fields:** each forbidden name raises an error, including
  behind the `attr_` prefix;
- negative schema tests as for State.

**Hypothetical walkthrough** (a test fixture only, no real module). M6
reports `sweep = True` for `previous_day:low:2024-12-10` on the bar ending
14:31. A synthetic "liquidity-like" module emits:

1. **Transition.** `test.lifecycle`, `UNTOUCHED → SWEPT`,
   `transition_at = available_at = 14:31`, both seqs `<NA>`,
   `source_refs = (bar_interaction:…@…14:31…)`, `reason_code = M6_SWEEP`.
2. **Signal.** `test.sweep`, `direction = BULLISH`,
   `source_refs = (transition:st_…)`, `attr_sweep_extreme_price` (an
   objective reference price).

`materialize_state_to_bars` shows `SWEPT` from the 14:32 bar onward. M7
never knows what a sweep strategy is.

A tick-stream variant of the same fixture is also included: a sweep
confirmed at `(t, 5)`. It shows the transition is invisible to `(t, 5)` and
to an unsequenced event at `t`, and visible to `(t, 6)`.

## 23. Anti-overengineering review

| Proposed | ≥ 2 plausible families? | Verdict |
|---|---|---|
| Transition envelope + validation | Liquidity, FVG, swings, Rejection Block | Keep |
| `StateNamespaceSpec` (states / edges / terminals) | All lifecycle families | Keep |
| One-transition-per-causal-event rule | All families, on bars and future ticks | Keep |
| Optional `*_seq` fields and the `≺` / `≼` key helpers | Bars (all seq `<NA>`, zero cost) and future ticks / quotes / book | Keep; they are nullable and cost nothing for bar workflows |
| `state_as_of`, `align_state_to_observations` with a `materialize_state_to_bars` wrapper | Strategy research and backtests on any family and granularity | Keep |
| Sequence-domain column | None today | Defer; Q13 |
| Tick ingestion, tick interaction engine | — | Out of scope; M6 stays bar-based |
| Signal envelope + `SignalDefinitionSpec` | Sweeps, MSS, FVG creation, breakouts | Keep |
| Typed `source_refs` | All | Keep |
| `attr_*` typed attributes | Liquidity (penetration), FVG (gap size), swings (strength) | Keep |
| `entity_type` column | — | Drop (namespace suffices); Q9 |
| Signal validity intervals | None identified | Defer; Q4 |
| Universal SUSPENDED / reset rules | None | Reject |
| Edges table, registry, plugin discovery, event bus, DSL, DB | None | Reject |
| `apply_state_transitions`, a state-machine runner | None | Reject |

## 24. Design-authority questions (resolved 2026-10-01, D-129)

**Resolutions:**

- **Q1:** the transition log is canonical.
- **Q2:** one transition per causal source event.
- **Q3:** one primary state per namespace; **no self transitions**.
- **Q4:** signal validity windows are deferred.
- **Q5:** **full** SHA-256 over the natural key, including previous and new
  state and the canonical source refs.
- **Q6:** typed SourceRef (§0.7); M5 and M6 are unchanged.
- **Q7:** module-owned.
- **Q8:** typed `attr_*` columns.
- **Q9:** no `entity_type`; `entity_kind` lives on the namespace spec.
- **Q10:** minimal utilities, with the generic core named
  `materialize_state_to_observations`.
- **Q11:** a new `src/state/` package.
- **Q12:** the bar-boundary convention is approved.
- **Q13:** the sequence domain is deferred.

New in rev 3: a required `initial_state` with no creation transition, and
a caller-provided entity applicability frame. The text below is the rev 2
analysis.

Only questions that change the architecture. Each has a recommendation.

**Q1. Canonical storage: transition log or per-bar snapshot.**

- *Consequence:* storage size, audit trail, and every consumer's API.
- **Recommend the transition log as canonical**, with per-bar views derived
  by `materialize_state_to_bars`.
- *Alternative:* snapshot-canonical. It is simpler for one-off backtests
  but repeats rows and loses the "why" per change.

**Q2. Multiple transitions per causal event.**

- *Consequence:* whether records ever imply order the data cannot prove.
- **Recommend one transition per (entity, namespace, causal source
  event)**, enforced as strictly increasing `(at, seq)` keys.
  - For OHLC bars this means one per bar, recording the end-of-bar state.
    Intermediate facts stay visible through M6 `source_refs`, and modules
    declare skip edges.
  - Reliably sequenced same-timestamp ticks may produce ordered
    transitions.
- *Alternative:* a same-timestamp chain with an ordinal. This is rejected
  because it implies chronology OHLC cannot prove.

**Q3. Primary lifecycle vs auxiliary attributes; self-transitions.**

- *Consequence:* whether counters live in State.
- **Recommend:**
  - one primary state per namespace;
  - a second namespace for an independent state variable;
  - counters and last-interaction times derived from the M6 log rather than
    stored as state;
  - `A → A` self-transitions **disallowed** in M7A.
- *Alternative:* allow declared self-transitions that carry updated
  `attr_*`. This is more flexible but invites counter bookkeeping in State.

**Q4. Signal validity intervals.**

- *Consequence:* schema size and whether signals carry lifetime.
- **Recommend deferring them.** Signals are point events, lifetime belongs
  to subject state, and holding periods belong to strategy.

**Q5. Deterministic id construction.**

- *Consequence:* id stability across reruns and versions.
- **Recommend a natural key plus a `sha256[:20]` prefixed id**, with the
  key columns retained:
  - transitions: (namespace, version, entity, `transition_at`,
    `transition_seq`);
  - signals: (type, version, subject, `event_at`, `event_seq`, direction).
- *Alternative:* human-readable composite ids. They are inspectable but
  long and fragile to escaping.

**Q6. Provenance model.**

- *Consequence:* auditability, and the need to change M5/M6.
- **Recommend typed string refs `<kind>:<natural key>`.** M6 rows are
  referenced by `level_id@bar_end`, so M6 is unchanged. The causal check
  runs only when sources are supplied.
- *Alternative:* add explicit id columns to M5/M6 outputs. That touches
  frozen, validated modules.

**Q7. Applicability / reset ownership.**

- *Consequence:* whether M7 encodes any domain persistence.
- **Recommend:** applicability stays on the entity (M6-style `valid_from` /
  `valid_until`), and reset / expiry are module transitions. M7 enforces
  only a single contract per entity, and no sourcing from non-evaluated M6
  rows when sources are supplied.

**Q8. Payload representation.**

- *Consequence:* typing and queryability of extension data.
- **Recommend declared typed `attr_*` columns validated against the spec.**
- *Alternative:* a JSON/dict `attributes` column. It is more flexible but
  untyped.

**Q9. `entity_type` field.**

- *Consequence:* minor schema redundancy.
- **Recommend omitting it**, because the namespace implies the entity kind.

**Q10. Are the replay utilities needed in M7A?**

- *Consequence:* M7A scope.
- **Recommend shipping** `validate_transitions`, `state_as_of`, and
  `align_state_to_observations` with its `materialize_state_to_bars`
  wrapper. These are the minimum a first consumer (liquidity) and any
  backtest need, and they keep the core tick-ready.
- *Alternative:* ship validation only and defer the views to the first
  module.

**Q11. Package placement.**

- *Consequence:* import layering.
- **Recommend new `src/state/` and `src/signals/` packages**, mirroring the
  layer separation.
- *Alternative:* `src/features/state_contract.py` etc. This blurs the
  FEATURE / STATE boundary.

**Q12. Bar-boundary convention in the generic alignment (rev 2).**

- *Consequence:* the generic rule is strict precedence, under which an
  equal-timestamp unsequenced pair is simultaneous. Applied literally to
  `BAR_END` bars, the next bar (`bar_start == previous bar_end`) could
  never see a bar-close transition, which contradicts the M5/M6 rule
  `bar_start ≥ available_at`.
- **Recommend:**
  - the generic core is strict;
  - the bar wrapper passes `boundary_inclusive=True`, under which an
    **unsequenced** availability at exactly the decision timestamp is
    visible. Under the `BAR_END` convention a bar's decision instant
    follows the close stamped with the same label;
  - this reproduces M5/M6 exactly and never lets a bar see its own
    transition.
- *Alternatives:*
  - encode the boundary with synthetic sequence numbers (e.g. close = 0,
    next decision = 1). This is rejected because it fabricates sequence
    values;
  - shift bar `decision_at` by an epsilon. This is rejected because it
    fabricates time.

**Q13. Sequence domain.**

- *Consequence:* sequences are comparable only within one ordered stream.
  If two feeds' sequences are mixed, `≺` would produce false order.
- **Recommend deferring a `seq_domain` column.** For now:
  - the rule is documented: one consistent domain per instrument stream,
    owned by the emitting module;
  - all current workflows are unsequenced;
  - the column is added when the first sequenced source exists. This is
    backward compatible as a nullable column.
- *Alternative:* add `transition_seq_domain` / `event_seq_domain` now, so
  that M7 can refuse cross-domain comparisons from day one.

---

## M7B FINAL CONTRACT — APPROVED / IMPLEMENTED (D-132)

**Status: APPROVED and IMPLEMENTED 2026-10-01 (D-132), with the amendments
in B.0, which override B.1–B.16 where they differ.**

- Implementation: `src/signals/contract.py`.
- Tests: `tests/test_signal_contract.py`, 28 tests / 88 subtests, synthetic
  definitions only. This section **supersedes §11–§15
for M7B**. §11–§16 are kept as historical reasoning from before D-130 /
D-131.

### B.0 Design-authority amendments (normative)

1. **Q1–Q10.** The questions are approved as recommended. `subject_kind` is
   required. `allowed_directions` works as simplified: empty means a null
   direction; non-empty means exactly one of the declared values; NEUTRAL
   has no special behaviour. Availability is not in the id. Source
   resolution is deferred, there are no materialization utilities, and
   there is no `reason_code`.
2. **`subject_id`** is a stable, non-empty, trimmed, single-line semantic
   identifier. It is **not** restricted to a token regex; separators, dates
   and compound ids are allowed. `subject_kind` lives only on the
   definition.
3. **Overlap.** `trigger_ref` must not also appear in `source_refs`;
   `source_refs` holds additional provenance only. An exact canonical
   overlap is rejected. This is not retrofitted into M7A State.
4. **Identity (supersedes B.6).** `signal_id = "sg_" + full SHA-256` of:
   - `signal_type`, `definition_version`;
   - `instrument_id`, `contract_scope`, `contract`;
   - `subject_id`;
   - canonical UTC `event_at`, `event_seq_domain`, `event_seq`;
   - `direction`;
   - `trigger_ref`;
   - canonical `source_refs`.

   It is instrument- and contract-safe without relying on `subject_id`
   being globally qualified. Excluded: `available_*` and `attr_*`.
5. **Semantic-event uniqueness (supersedes B.7 Rule 2).** At most one
   Signal per (`signal_type`, `definition_version`, `instrument_id`,
   `contract_scope`, `contract`, `subject_id`, `event_at`,
   `event_seq_domain`, `event_seq`, `direction`).
   - The key **excludes** `trigger_ref`, `source_refs`, `available_*` and
     attributes.
   - The same semantic event with different provenance is a duplicate.
   - The same trigger may yield different types or subjects. Opposite
     directions are distinct only when the definition allows them.
   - Duplicate `signal_id`s are also rejected.
6. **Ordering (supersedes B.11):**
   1. `available_at`;
   2. `available_seq_domain`, then `available_seq`;
   3. `event_at`;
   4. `event_seq_domain`, then `event_seq`;
   5. `signal_type`, `instrument_id`, `contract_scope`, `contract`,
      `subject_id`, `direction`, `signal_id`.

   Strings use deterministic sorted ranks, never encounter order, and nulls
   sort first. The order is for reproducibility only, never chronology.
7. **Errors.**
   - `SignalContractError(ValueError)`, which is not a
     `StateContractError`.
   - Reused M7A primitives' `StateContractError` is translated at the
     Signal API boundary with chaining.
   - Only public M7A primitives are imported. Signal-local private helpers
     do the DataFrame plumbing, and M7A is not refactored.
8. **Forbidden execution fields.** Exactly the B.9 list, checked directly
   and as `attr_<name>`, with no fuzzy matching. `side` stays allowed.

This section aligns Signals exactly with the implemented M7A causal,
provenance and identity model (D-129–D-131). M7A is not redesigned.

### B.1 Definition and scope

**A Signal is an immutable, reusable market event.** It describes *what
happened*, never *what trade to place*.

- **Origins.** It may originate from a Feature, an Interaction, a
  StateTransition, another objective event, or several of these. It is
  **not** required to originate from State.
- **Point events.** Signals carry no ACTIVE / EXPIRED state, no
  `valid_from` / `valid_until`, no holding period and no expiry bars.
- **Lifetime belongs elsewhere:** to the subject's State, or to Strategy
  eligibility. Validity windows stay deferred.
- **Infrastructure only.** M7B ships no real definitions (`liquidity.sweep`,
  `structure.mss`, `fvg.created`, `orb.breakout` …). Tests use synthetic
  definitions, and ORB is not migrated.

**Repository evidence reviewed (read-only):**

- `research_viewer.find_orb_signals`: a breakout event with `signal_time`,
  `direction` LONG/SHORT and `ambiguity_status`. "First per direction" and
  the 11:30 cut-off are strategy eligibility. LONG / SHORT is action
  vocabulary, which M7B does not adopt.
- `backtesting.candidate_entries`: signal → `entry_price`, `initial_stop`,
  `initial_target`, `risk_points`. This is execution, and confirms the
  forbidden-field list.
- `orb_v01.Breakout`: mixes the event (`direction`, `timestamp`) with
  execution (`entry`, `entry_at_open`), which is exactly what the contract
  must forbid.
- `completed_trades`: `AMBIGUOUS_*` when OHLC cannot order events, the same
  "never invent order" principle.
- None of this contradicts the recommendations below. Nothing is migrated.

### B.2 `SignalDefinitionSpec` (frozen dataclass)

| Field | Rule |
|---|---|
| `signal_type` | Dotted lowercase, e.g. `test.sweep`. It determines the event semantics |
| `subject_kind` | **Required**, a lowercase token (e.g. `liquidity_level`, `swing`, `fvg`). It mirrors `StateNamespaceSpec.entity_kind`, so there is no per-row subject type |
| `definition_version` | Non-empty |
| `allowed_directions` | A tuple drawn from {`BULLISH`, `BEARISH`, `NEUTRAL`}, unique. Empty means an undirected definition |
| `attributes` | A tuple of M7A `AttributeSpec`, giving typed `attr_<name>` columns. Each name is checked against the forbidden list (B.9) at construction |

### B.3 Signal row schema

| Column | Req. | Rule |
|---|---|---|
| `signal_id` | yes | `"sg_" + full 64-hex SHA-256` (B.6) |
| `signal_type`, `definition_version` | yes | Must equal the definition's |
| `subject_id` | yes | Non-empty stable id of the primary subject (an entity, level, swing …). It is not resolved against an entity frame; subject validity belongs upstream (B.10) |
| `event_at`, `event_seq_domain`, `event_seq` | yes / nullable / nullable | M7A causal key of the event confirmation; the domain and sequence are co-null |
| `available_at`, `available_seq_domain`, `available_seq` | yes / nullable / nullable | M7A causal key at which consumers may know the signal |
| `instrument_id` | yes | Non-empty |
| `contract_scope`, `contract` | yes | `SPECIFIC` requires a non-empty contract; `AGNOSTIC` requires null. No stitching or bridging |
| `direction` | yes, nullable | B.5 |
| `trigger_ref` | yes | Canonical M7A `SourceRef` (B.4) |
| `source_refs` | optional | Canonical tuple, possibly empty (B.4) |
| `attr_<name>` | optional | Declared and typed (B.8) |

No other columns are allowed. **There is no `reason_code`**: a signal's
meaning is its `signal_type`. If a concrete need appears, it can be added
later as an optional column.

### B.4 Causal model and provenance (reusing M7A, no second model)

**Keys.** Event and availability keys are M7A `CausalKey`s
`(at, seq_domain, seq)`, compared only with M7A `compare_causal`:

- `compare_causal(event, available)` must be `BEFORE` or `EQUAL`;
- `AFTER` is invalid, and `INCOMPARABLE` is invalid;
- completed-bar signals use `(bar_end, null, null)` for both keys;
- `event_at` is never back-dated to an inferred intrabar time.

**Derivation vs consumption.**

- A Signal may be **created** at the same causal event that creates a
  StateTransition, and may reference it:
  - M6 interaction at K → StateTransition at K → Signal at K is valid.
  - Derivation is another description of the same event, not downstream
    consumption.
- The causal observation that creates a Signal **cannot consume it**. A
  Strategy or Execution decision needs a causally later observation, under
  the M7A strict rule `available ≺ decision`.
- A future bar consumer adapter may apply the explicit `BAR_END` boundary
  convention, as `materialize_state_to_bars` does.
- **Signal validation has no inclusive mode.**

**Provenance.**

- **`trigger_ref`** is required. It is the single causal source event
  whose arrival caused the Signal. Examples:
  - `M6_INTERACTION:<level_id>@<bar_end UTC>`;
  - `STATE_TRANSITION:<transition_id>`;
  - `TRADE:<stream>@<t>#<domain>:<seq>`.
- **`source_refs`** is optional supporting provenance:
  - zero or more references;
  - canonicalized exactly as in M7A (`canonical_source_refs`: sorted,
    unique);
  - it need not repeat `trigger_ref`; overlap is allowed, as in M7A.
- **SourceRef keys are opaque.** M7B never parses them to infer timing,
  provider or source semantics.

### B.5 Direction semantics

- **Rule:**
  - `allowed_directions` empty ⇒ `direction` must be null;
  - `allowed_directions` non-empty ⇒ `direction` must be one of the listed
    values.
- `NEUTRAL` has no hidden rule. A definition that may emit it lists it
  explicitly.
- Direction describes the market event only: BULLISH ≠ BUY and
  BEARISH ≠ SELL. The Strategy maps direction to action.
- **Edge case (reported, not a rule change).** A directional definition
  cannot emit a null direction; it must list `NEUTRAL` if some events are
  directionless. No repository evidence needs anything else.

### B.6 Deterministic identity

- **`signal_id`** = `"sg_" + sha256(json([…]))`, over this natural key:
  - `signal_type`;
  - `definition_version`;
  - `subject_id`;
  - `canonical_time(event_at)`, `event_seq_domain|null`, `event_seq|null`;
  - `direction|null`;
  - `canonical_ref(trigger_ref)`;
  - `[canonical source_refs]`.
- It uses the **full SHA-256**, exactly the M7A standard. The natural-key
  fields stay as columns.
- **Excluded from identity:**
  - **`available_*`**, because availability is not event identity. A
    republication or delay of the same event keeps its id;
  - `instrument_id` / `contract`, which are implied by the deterministic
    `subject_id` (as M7A treats `entity_id`);
  - `attr_*`, which describe the event but do not define it.
- **Invariance:**
  - timezone-equivalent `event_at` values give the same id, through UTC
    canonical time;
  - the input order of `source_refs` does not affect the id.

### B.7 Uniqueness

M7A's "one per entity + namespace + trigger_ref" rule is **not** copied.
One trigger may legitimately produce several Signals (different types,
subjects or directions).

- **Rule 1.** Duplicate `signal_id`s are rejected; this is duplicate
  natural-key rejection.
- **Rule 2 (recommended in addition; see Q5).**
  - At most one Signal per **semantic event key**:
    (`signal_type`, `definition_version`, `subject_id`, event causal key,
    `direction`).
  - **Why:** the natural key includes `trigger_ref` and `source_refs`.
    Without Rule 2, the same market event recorded twice with different
    supporting references, or different simultaneous triggers, would yield
    two distinct "valid" Signals.
  - **Consequences:**
    - the same `trigger_ref` producing different types or subjects stays
      valid;
    - distinct directions stay distinct identities.

### B.8 Typed attributes

- They reuse the M7A `AttributeSpec` pattern.
- Validation rejects:
  - an undeclared `attr_*`;
  - a wrong dtype;
  - a missing required attribute;
  - any non-envelope, non-`attr_` column, so there is no dictionary
    payload.
- Objective event metadata is allowed, e.g. `attr_extreme_price`. It is
  never an entry instruction.

### B.9 Forbidden execution fields (finite controlled list; no heuristics)

`entry`, `entry_price`, `entry_time`, `stop`, `stop_loss`, `stop_price`,
`initial_stop`, `take_profit`, `target`, `target_price`,
`initial_target`, `limit_price`, `quantity`, `size`, `position_size`,
`order_type`, `order_side`, `risk`, `risk_points`, `r_multiple`,
`trade_id`.

- **Rejected forms:** the exact column name, and `attr_<name>`.
  - Comparison is exact on the lowercase name: no substring, regex or
    fuzzy text classification.
  - Attribute names are also checked when `SignalDefinitionSpec` is
    constructed, so a definition cannot declare one.
- **Not listed:** `side`, because the word is used for level sides in
  M6. Direction covers market direction, and execution side lives in the
  Strategy.

### B.10 Validation responsibility boundary (as D-131)

**`validate_signals(signals, definition)` validates:**

- schema and dtypes;
- definition membership (type, version, direction, attributes);
- causal consistency (event `≼` availability; co-null sequence pairs);
- provenance format and canonical form;
- scope / contract rules;
- deterministic identity and uniqueness;
- forbidden fields;
- canonical ordering.

**It does not:**

- reconstruct whether the upstream trigger observation was eligible to
  create the Signal;
- resolve subjects;
- resolve the timing of source refs.

Those belong to the source Feature / Interaction / State module. There is
no `decision_offset`, `trigger_decision_at`, bar duration or tick/bar
geometry in the schema.

**Cross-layer source causal revalidation is deferred.** The repository has
no reusable resolver for source records, and M7A deliberately keeps
SourceRef opaque. There is no registry, event database, graph resolver or
plugin.

### B.11 Canonical ordering

- **Stable sort, in order:**
  1. `available_at`;
  2. `available_seq_domain`, then `available_seq`, with nulls first;
  3. `event_at`;
  4. `event_seq_domain`, then `event_seq`;
  5. `signal_type`;
  6. `subject_id`;
  7. `signal_id`.
- String keys use deterministic sorted-unique codes, from a local helper
  equivalent to `factorize(sort=True)`. They never use encounter order.
- Order is for reproducibility only. It never implies causal order between
  simultaneous or `INCOMPARABLE` signals.

### B.12 Shared M7A primitives and import direction

- **`src/signals/contract.py` imports from `src/state/contract.py`.**
  - Reused public primitives: `CausalKey`, `compare_causal`, `BEFORE` /
    `AFTER` / `EQUAL` / `INCOMPARABLE`, `SourceRef`, `canonical_ref`,
    `canonical_source_refs`, `canonical_time`, `AttributeSpec`,
    `ATTRIBUTE_PREFIX`, `SPECIFIC` / `AGNOSTIC` / `CONTRACT_SCOPES`.
  - **No cycle:** `state.contract` imports only numpy and pandas.
  - **Layering is downward** (Signal → State primitives).
- **Responsibility split (design-authority clarification, 2026-10-01):**
  - **Reused (public M7A semantics only).** Causal comparison
    (`CausalKey` / `compare_causal`), SourceRef canonicalization and
    canonical timestamp identity are **never duplicated**.
  - **Never imported:** underscore-prefixed State helpers (`_frame_keys`,
    `_sequence_pair`, `_tz_column`, `_check_scope`, `_check_attribute`,
    `_codes`, …).
  - **Local Signal-specific helpers** in `src/signals/contract.py` handle:
    - required columns;
    - tz-aware timestamp normalization to UTC;
    - the `seq_domain` / `seq` co-null check;
    - contract-field checks (using the public scope constants);
    - typed `attr_*` validation against `AttributeSpec`;
    - deterministic row sorting with sorted-unique string codes.

    These are plumbing, not M7 semantics.
  - **Causal checks.** Event `≼` availability is evaluated per row with the
    public `compare_causal` on `CausalKey`s. Signal volumes are small, and
    the comparator mathematics is not re-implemented.
  - **No M7A refactor.** Helpers are not moved into a shared module, and
    `src/state` behaviour does not change unless an actual blocker is
    demonstrated. Nothing is re-exported through `src/state/__init__.py`.
- **Errors.**
  - M7B defines `SignalContractError(ValueError)`. It is **not** a
    subclass of `StateContractError`.
  - Every Signal-facing public API raises `SignalContractError`.
  - A `StateContractError` raised by a reused primitive (e.g. `CausalKey`,
    `SourceRef.parse`, `canonical_source_refs`, `AttributeSpec`) is caught
    at the Signal boundary and re-raised as `SignalContractError(...)`
    with `raise … from exc`.

### B.13 Proposed public API

```text
SignalDefinitionSpec(signal_type, subject_kind, definition_version,
                     allowed_directions=(), attributes=())
SignalContractError(ValueError)        # State errors re-raised with chaining
DIRECTIONS = ("BULLISH", "BEARISH", "NEUTRAL")
FORBIDDEN_EXECUTION_FIELDS = (... B.9 ...)
SIGNAL_COLUMNS / SIGNAL_ID_PREFIX = "sg_"

signal_id(*, signal_type, definition_version, subject_id, event_at,
          event_seq_domain=None, event_seq=None, direction=None,
          trigger_ref, source_refs=()) -> str
assign_signal_ids(signals: DataFrame) -> DataFrame
validate_signals(signals: DataFrame, definition: SignalDefinitionSpec) -> DataFrame
```

- `validate_signals` validates one definition per call, mirroring M7A's
  one namespace per call. It returns UTC-normalized rows in canonical
  order, with canonical refs.
- **Not in M7B:** `signal_as_of`, `materialize_signals_to_*`,
  `active_signals`, `expire_signals`. Signals are point events. The first
  Strategy consumer adds a causal alignment adapter when one is actually
  needed.

### B.14 Focused test plan (synthetic definitions only)

**Schema:**

- a valid directed and a valid undirected signal;
- an unknown direction;
- a direction on an undirected definition;
- a null direction on a directed definition;
- missing required fields;
- naive timestamps;
- the domain / sequence co-null rule;
- SPECIFIC / AGNOSTIC rules;
- unknown extra columns;
- a type or version mismatch with the definition.

**Causality:**

- event `BEFORE` availability: accepted;
- event `EQUAL` availability: accepted;
- `AFTER`: rejected;
- same timestamp, same domain: ordered sequences accepted, reversed
  rejected;
- same timestamp with different domains, or a missing sequence on one
  side: rejected (`INCOMPARABLE`).

**Provenance:**

- `trigger_ref` required (missing or null rejected);
- `source_refs` optional and empty allowed;
- canonical ordering;
- a future SourceRef kind accepted structurally;
- a malformed ref rejected.

**Identity:**

- full SHA-256 that is deterministic;
- timezone-equivalent events give the same id;
- `source_refs` input order gives the same id;
- the event sequence domain participates;
- each natural-key field changes the id;
- **an availability change alone does not change the id.**

**Uniqueness:**

- a duplicate id is rejected;
- a duplicate semantic event key (with different `source_refs`) is
  rejected;
- the same trigger may produce two different types;
- the same trigger may produce signals for different subjects;
- distinct directions are distinct ids.

**Error boundary:**

- Malformed refs, keys or attribute specs surface as `SignalContractError`
  (not `StateContractError`), with the original as `__cause__`.
- `SignalContractError` is not a `StateContractError`.

**Attributes and forbidden fields:**

- a typed attribute is accepted;
- an undeclared, wrong-dtype or missing required attribute is rejected;
- each forbidden name is rejected directly and through `attr_`;
- a definition declaring a forbidden attribute is rejected.

**Determinism:**

- shuffled input rows give identical canonical output;
- simultaneous `INCOMPARABLE` signals sort deterministically without
  implying chronology.

**State interop:**

- a Signal with `trigger_ref = STATE_TRANSITION:<id>` built with M7A
  `assign_transition_ids` on a synthetic namespace, at the same causal key
  as that transition, is valid.
- No real lifecycle is involved.

### B.15 Anti-overengineering

M7B does not include:

- a registry or discovery mechanism;
- an event bus;
- a graph or database;
- a source resolver;
- a strategy DSL;
- a lifetime engine or signal state machine;
- tick ingestion;
- execution integration.

M7B is only the reusable Signal envelope.

### B.16 Design-authority questions

- **Q1. Require `subject_kind`.** Recommend **yes**. There is no
  contrary repository evidence, and it mirrors `entity_kind`.
- **Q2. Simplified `allowed_directions`.** Recommend **yes**. The only
  edge is that a directed definition cannot emit a null direction and must
  list NEUTRAL instead.
- **Q3. Identity includes `trigger_ref` and canonical `source_refs`.**
  Recommend **yes**, matching M7A.
- **Q4. `available_*` in `signal_id`.** Recommend **no**.
- **Q5. Duplicate natural-key rejection only, or also a semantic-event
  key.** Recommend **duplicate ids plus the semantic-event uniqueness of
  B.7 Rule 2.**
  - Natural-key rejection alone is weaker than intended, because the key
    contains provenance.
  - *Alternative:* natural-key duplicates only, which allows the same
    event to be recorded twice with different supporting refs.
- **Q6. Cross-layer source causal resolution.** Recommend **deferring
  it**.
- **Q7. Import shared primitives from `src/state/contract.py` without
  refactoring.** Recommend **yes**.
- **Q8. Signal materialization / alignment utilities in M7B.** Recommend
  **no**.
- **Q9. Private M7A helpers: resolved (2026-10-01).**
  - Only public M7A semantics are reused; no underscore helpers are
    imported.
  - Small local Signal plumbing helpers are allowed.
  - There is no M7A refactor.
  - `SignalContractError(ValueError)`, with State errors re-raised through
    chaining (B.12).
- **Q10 (new). `reason_code`.** Recommend **omitting it** from Signal. It
  is available in State; for Signals the type carries the meaning.
