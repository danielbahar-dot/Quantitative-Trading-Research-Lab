# M6 — Generic Level Interaction Catalog: Specification

**Status: rev 4. M6 COMPLETE (2026-10-01).** M6A (generic engine) is
implemented and validated. M6B (ORB migration) achieved exact frozen
parity; see §21. It incorporates the design-authority decisions of
2026-09-30 (**D-126**), the applicability-bound decision of 2026-10-01
(**D-127**), and the ORB migration decision (**D-128**).

- **Implementation:** `src/features/level_interactions.py` (generic
  authority) and `src/experiments/orb_level_interaction_compat.py` (ORB
  consumer / compatibility adapter).
- **Tests:** `tests/test_level_interactions.py`,
  `tests/test_orb_level_interaction_compat.py`.
- **Validation evidence:** §17, §20, §21.

Related: [M5_MARKET_CONTEXT_SPEC](M5_MARKET_CONTEXT_SPEC.md) ·
[DECISION_LOG](DECISION_LOG.md) (D-115, D-118, D-123–D-126) ·
[QUALITY_CONTROL](QUALITY_CONTROL.md).

**Layer boundary.** M6 answers one question: *"What did this completed bar
objectively do relative to this already-available level?"* It is stateless
and per bar.

- **Not M6:** first-touch, active/consumed/invalidated, counts, setup
  validity. Those belong to State, Signal and Strategy.
- **Primitives:** `TOUCH`, `TRADE_THROUGH`, `CLOSE_THROUGH`, `REJECT`,
  `SWEEP`. These are independent booleans, never one categorical label.

---

## 1. Existing ORB interaction logic

This section describes the pre-M6B state. Since M6B, `level_interaction`
has been removed from `market_context.py`, and ORB evaluates through M6A via
`orb_level_interaction_compat.py` (§21).

| Where | What | Unit | Orientation | Tick | State |
|---|---|---|---|---|---|
| `src/features/market_context.py::level_interaction` | `touched`, `traded_through`, `closed_through`, `rejected`, `swept`, `start_side`, OR distances | **One aggregated OR window** (15/20/30m) | `start_side` from the OR open vs the level: `BELOW`/`ABOVE`/`AT` | none; strict `>`/`<` | none |
| `mnq_orb_v02_features.build_feature_audit` | Applies it to 18 ORB key levels per session × OR duration | OR aggregate | as above | — | none |
| `…london_interaction_event_characterization.first_interaction_timestamps` | First touch / first strict trade-through **per bar** in the OR | per bar | frozen `start_side` | — | **stateful ("first")** |
| `derive_frozen_interaction_state`, `derive_interaction_category` | One categorical label by precedence | derived | — | — | analysis labelling |
| `feature_validation_viewer` | Displays the frozen flags | — | — | — | — |

**Frozen formulas** (level `L`, OR aggregate `o/h/l/c`):

- `touched = l ≤ L ≤ h`.
- **`BELOW`** (`o < L`):
  - `traded_through = h > L`
  - `closed_through = c > L`
  - `swept = traded_through ∧ c ≤ L`
  - `rejected = touched ∧ c ≤ L`
- **`ABOVE`:** the mirror image.
- **`AT`:** touched only; every directional flag is False.

**M6B oracle:** the 234 `level_*` columns of
`mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv` (18 levels × 13 fields;
SHA-256 in M5 spec §11).

**Why far-side support matters** (frozen audit; session × OR rows):

| Level | Semantic orientation | Opens on original side | Opens beyond (far side) | Far side and ORB `touched` |
|---|---|---|---|---|
| previous_day_high / low | UPPER / LOWER | 500 / 578 | 153 / 75 | 70 / 20 |
| asia_high / low | UPPER / LOWER | 430 / 504 | 291 (+3 `AT`) / 220 | 116 / 98 |
| london_high / low | UPPER / LOWER | 481 / 545 | 249 / 185 | 127 / 87 |
| ny_premarket_high / low | UPPER / LOWER | 652 / 631 | 87 / 108 | 64 / 93 |

M6 evaluates these far-side approaches explicitly through `approach_side`
(D-126 #1).

## 2. Generic vs ORB classification

| ORB concept | Class | Notes |
|---|---|---|
| Flag formulas for a `BELOW` or `ABOVE` start | **A**: identical generic primitive | ORB `start_side` **is** the generic `approach_side` of the evaluated OHLC. On the tick grid `h > L` ≡ `H ≥ f+1` |
| `AT` start (directional flags False) | **B**: legacy semantics | Generic UPPER/LOWER treat `open == L` as the original side (D-126 #7). NEUTRAL gives `AMBIGUOUS_APPROACH`. The ORB rule is reproduced only in the M6B adapter |
| OR-aggregate evaluation | **B** | Generic per-bar engine applied to an aggregated OHLC (M6B) |
| Non-directional levels (`*_close`, gaps, `ny_open_reference`) | **A with NEUTRAL** | Semantic orientation `NEUTRAL` (D-126 #3) |
| Distances to OR high / low / mid | **C**: strategy-specific | Stays in ORB |
| Categorical precedence labels | **C** | Analysis / Signal |
| `first_interaction_timestamps` | **D**: stateful | State layer |

## 3. Level input schema

| Field | Required | Type | Meaning |
|---|---|---|---|
| `level_id` | yes | str | Deterministic and unique |
| `level_value` | yes | float | **May be off the tick grid** (derived levels such as midpoints). Converted exactly via its shortest decimal representation |
| `orientation` | yes | `UPPER` / `LOWER` / `NEUTRAL` | **Semantic, immutable**; never inferred from price |
| `available_at` | yes | tz-aware ts | **Causal knowledge time.** Evaluated only on bars with `bar_start ≥ max(available_at, valid_from)` |
| `instrument_id` | yes | str | `tick_size` through M2 `load_instrument` |
| `contract_scope` | yes | `SPECIFIC` / `AGNOSTIC` | Explicit (D-126 #8) |
| `contract` | iff `SPECIFIC` | str | Must be non-empty for `SPECIFIC` and null for `AGNOSTIC`; otherwise input validation raises |
| `valid_from` | optional | tz-aware ts | **Immutable lower applicability bound** (D-127): only bars with `bar_start ≥ valid_from` apply (e.g. the target session open). Not lifecycle state |
| `valid_until` | optional | tz-aware ts | **Immutable upper applicability bound** (D-126 #4, D-127): only bars with `bar_start < valid_until` apply (e.g. the target session close). Not lifecycle state. Must be `≥ available_at` and `> valid_from`, else input validation raises |
| `level_type`, `source_feature`, `source_trading_date`, `definition_version` | optional | — | Provenance, passed through |

There are no lifecycle fields.

**Derived per level** (exact, `Decimal`), with `t` the tick:

- `f = floor(L / t)` and `c = ceil(L / t)`. For an on-grid `L`, `f = c = L/t`.
- **`first_tradable_above = (f + 1)·t`**: the first tradable price strictly
  above `L`.
- **`first_tradable_below = (c − 1)·t`**: the first tradable price strictly
  below `L`.

## 4. Bar input schema

- Canonical bars with a tz-aware `DatetimeIndex` of **bar-end labels**, plus
  `open`, `high`, `low`, `close`, `contract`.
- `bar_start = bar_end − bar_interval` (default 1 minute), as in M3/M5.
  Volume is not needed.
- **Bar prices must lie on the instrument tick grid.** They are converted
  once to integer ticks `O, H, Lo, C`.
- An optional `session_date` column is checked against the session model.

**Input errors raise** (D-126 #5):

- schema: missing columns, naive or duplicate timestamps, NaN;
- inconsistent OHLC;
- off-grid **bar** prices;
- an invalid `orientation` or `contract_scope`;
- `SPECIFIC` without a contract, or `AGNOSTIC` with one;
- a non-finite `level_value`;
- an unknown instrument.

## 5. Approach side (per bar, per level)

The approach is taken from the bar's open. Integer comparisons are exact:

| `approach_side` | Condition | Meaning |
|---|---|---|
| `BELOW` | `O ≤ c − 1` (open strictly below `L`) | approaching the level upward |
| `ABOVE` | `O ≥ f + 1` (open strictly above `L`) | approaching the level downward |
| `AT` | `O·t == L` (only possible when `L` is on the grid) | open exactly at the level |

**Evaluation direction.** `AT` resolves by orientation (D-126 #7):

- UPPER → evaluated as `BELOW` (the original side);
- LOWER → evaluated as `ABOVE` (the original side);
- NEUTRAL → **no direction is invented**; the row gets `AMBIGUOUS_APPROACH`
  (§7).

**`approach_relation`** (directional levels only):

| orientation | approach_side BELOW | ABOVE | AT |
|---|---|---|---|
| UPPER | `ORIGINAL_SIDE` | `FAR_SIDE` | `ORIGINAL_SIDE` |
| LOWER | `FAR_SIDE` | `ORIGINAL_SIDE` | `ORIGINAL_SIDE` |
| NEUTRAL | `<NA>` | `<NA>` | `<NA>` |

**Gap opens** (D-126 #2). A bar that opens beyond the level is **not** itself
a TOUCH or TRADE_THROUGH. It is simply a `FAR_SIDE` approach, and its
primitives describe whether it came back to the level from there.
`GAP_THROUGH` needs the previous bar's state and is **deferred**.

## 6. Primitive definitions

Integer ticks throughout: `O, H, Lo, C` for the bar, and `f, c` for the
level. The price form is shown for an on-grid `L`, with `t` the tick.

**Approach `BELOW`** (upward):

| Primitive | Exact rule | Price form (on-grid `L`) |
|---|---|---|
| TOUCH | `H ≥ c` | `high ≥ L` |
| TRADE_THROUGH | `H ≥ f + 1` | `high ≥ L + t` (`high ≥ first_tradable_above`) |
| CLOSE_THROUGH | `C ≥ f + 1` | `close > L` |
| REJECT | `H ≥ c ∧ C ≤ f` | `high ≥ L ∧ close ≤ L` |
| SWEEP | `H ≥ f + 1 ∧ C ≤ f` | `high ≥ L + t ∧ close ≤ L` |

**Approach `ABOVE`** (downward; mirror):

| Primitive | Exact rule | Price form (on-grid `L`) |
|---|---|---|
| TOUCH | `Lo ≤ f` | `low ≤ L` |
| TRADE_THROUGH | `Lo ≤ c − 1` | `low ≤ L − t` (`low ≤ first_tradable_below`) |
| CLOSE_THROUGH | `C ≤ c − 1` | `close < L` |
| REJECT | `Lo ≤ f ∧ C ≥ c` | `low ≤ L ∧ close ≥ L` |
| SWEEP | `Lo ≤ c − 1 ∧ C ≥ c` | `low ≤ L − t ∧ close ≥ L` |

**Reading far-side rows.** The meaning is always relative to the approach.
For example, for an UPPER level approached from `ABOVE`:

- TOUCH = came back down to the level;
- CLOSE_THROUGH = closed back below it;
- REJECT / SWEEP = touched or pierced it and closed back above.

Interpreting these (retest, polarity flip) is a State/Signal concern;
consumers filter with `approach_relation`.

**CLOSE_THROUGH rule.** It means a close strictly beyond `L`, which equals
"at or beyond the first tradable price". For on-grid levels that is at least
one full tick.

**Off-grid levels (`f < c`).** Exact contact is impossible, so:

- TOUCH ⇔ TRADE_THROUGH;
- REJECT ⇔ SWEEP;
- `AT` cannot occur.

This follows from the exact rule and is not a special case.

## 7. Evaluator status and representation

| Status | When | Primitives |
|---|---|---|
| `EVALUATED` | Visible, applicable, contract-compatible, and the approach has a direction | nullable `boolean`, all True/False |
| `AMBIGUOUS_APPROACH` | NEUTRAL level with `open == L` | `touch = True` (the open is at the level); the other four are `<NA>` |
| `PENDING_LEVEL` | The confirming bar only (`bar_start < available_at ≤ bar_end`), and only when that bar lies inside the static window (`valid_from ≤ bar_start < valid_until`) | all `<NA>` |
| `CONTRACT_MISMATCH` | `contract_scope == SPECIFIC` and the level contract ≠ the bar contract | all `<NA>` |

- `<NA>` ("not evaluated / not defined") is always distinct from `False`
  ("evaluated, did not happen").
- Bars outside `[valid_from, valid_until)` (by `bar_start`) are not
  applicable and are not emitted.
- Invalid input raises (§4) and is never a status.

## 8. Logical invariants (every `EVALUATED` row, either approach)

- `TRADE_THROUGH ⇒ TOUCH`; `CLOSE_THROUGH ⇒ TOUCH`;
  `CLOSE_THROUGH ⇒ TRADE_THROUGH`; `REJECT ⇒ TOUCH`.
- `SWEEP ⇔ TRADE_THROUGH ∧ REJECT`; therefore
  `SWEEP ⇒ TOUCH, TRADE_THROUGH, REJECT` and `SWEEP ⇒ ¬CLOSE_THROUGH`.
- `TOUCH ⇔ (CLOSE_THROUGH xor REJECT)`.
- On-grid, exact contact only (extreme exactly at `L`): `¬TRADE_THROUGH` and
  `¬SWEEP`. `REJECT ⇏ SWEEP` (on-grid).
- Off-grid: `TOUCH ⇔ TRADE_THROUGH` and `REJECT ⇔ SWEEP`.
- A bar entirely on the far side that never reaches `L` (e.g. UPPER, open and
  low above `L`): TOUCH False, so all five are False.
- Non-`EVALUATED` rows follow §7 exactly.

## 9. Causal availability

**Timing contract (D-127):**

- `available_at` = causal knowledge time; `valid_from` / `valid_until` =
  optional immutable static applicability bounds (not lifecycle).
- `effective_start = max(available_at, valid_from)` (just `available_at`
  when `valid_from` is null).
- A bar is **evaluated** when `bar_start ≥ effective_start` and, if
  `valid_until` is set, `bar_start < valid_until`. With no `valid_until`
  there is no static upper cutoff.
- The end rule is `bar_start < valid_until`, **not** `bar_end ≤ valid_until`.
  They coincide for aligned 1m bars and an on-boundary `valid_until`; for
  unaligned instants, a bar that starts before `valid_until` is included.
- The confirming bar (`bar_start < available_at ≤ bar_end`) is
  `PENDING_LEVEL`, and only when it itself lies inside the static window.
  A level never interacts with the bar that confirms it, and no
  retrospective rows exist for bars before the level was known. This matters
  for future swings, EQ/REQ, FVG and MSS levels.
- The bounds are enforced in the generic engine, not only by helpers. The M5
  helper sets `valid_from` / `valid_until` to the target session open /
  close, which gives target-session scope.

## 10. Contract behavior

- **`SPECIFIC`:** evaluated only when `bar.contract == level.contract`;
  otherwise `CONTRACT_MISMATCH` with `<NA>` primitives. There is no stitching
  (D-123), and it matches M5's `CONTRACT_MISMATCH` alignment status.
- **`AGNOSTIC`:** explicitly declared as contract-independent, e.g. a
  user-supplied research level. It is never `CONTRACT_MISMATCH`.
- A null contract is never silently treated as agnostic (D-126 #8).

## 11. Tick-size handling

- `tick_size` comes only from M2 (`InstrumentSpec.tick_size`, a `Decimal`),
  never hard-coded.
- **Bars:** `P = rint(price / t)`. Each must be within `1e-9` of an integer,
  or input validation raises. MNQ's 0.25 grid is exact in binary; a 0.1 tick
  is exercised synthetically.
- **Levels:** `L` is converted to `Decimal` from its shortest representation,
  then `f` and `c` are computed exactly with `Decimal` floor/ceil. This is
  once per level, so it's cheap.
- **All comparisons** are integer comparisons between bar ticks and `f`/`c`,
  vectorized over pairs.

## 12. Output schema (long / tidy)

`evaluate_level_interactions(bars, levels, *, bar_interval="1min",
session_spec=None, interactions_only=False, instrument_config_dir=None)`
emits one row per (bar, level) for bars with `bar_end ≥ available_at` (so
the confirming bar, if present, is `PENDING_LEVEL`) and
`valid_from ≤ bar_start < valid_until` (each bound only if set). Rows are
sorted by (`bar_end`, `level_id`); `interactions_only=True` keeps rows with
`touch` True.

| Column | Type |
|---|---|
| `bar_end`, `bar_start`, `bar_contract` | from the bar |
| `level_id`, `level_value`, `orientation`, `instrument_id`, `contract_scope`, `level_contract` | from the level |
| `available_at`, `valid_from`, `valid_until` | tz-aware ts (bar tz) |
| `first_tradable_above`, `first_tradable_below` | float (exact tick-grid prices) |
| `status` | §7 |
| `approach_side` | `BELOW` / `ABOVE` / `AT` (null unless `EVALUATED` / `AMBIGUOUS_APPROACH`) |
| `approach_relation` | `ORIGINAL_SIDE` / `FAR_SIDE` / `<NA>` |
| `touch`, `trade_through`, `close_through`, `reject`, `sweep` | nullable `boolean` |
| `open_offset_ticks`, `high_offset_ticks`, `low_offset_ticks`, `close_offset_ticks` | nullable `Float64` |
| provenance passthrough | as supplied |

**Offsets** (D-126 #9):

- Raw and signed: `(price − L) / t`, in plain price direction, **not
  clipped**, and not orientation-normalized.
- Integer for on-grid levels, fractional for off-grid ones.
- They are transparent diagnostics. The primitives are computed from the
  exact integer rules in §6, not from the float offsets.
- `<NA>` when the row is `PENDING_LEVEL` or `CONTRACT_MISMATCH`.

**M5 helper** (`evaluate_market_context_interactions(bars, context, …)`)
builds levels from the M5 **valid** tier:

- `<ctx>:high` → UPPER; `<ctx>:low` → LOWER; `previous_day:close` and
  `previous_rth:close` → **NEUTRAL**;
- `contract_scope = SPECIFIC` with the context contract;
- `available_at` from M5;
- `valid_from` = the target session open, `valid_until` = the target
  session close;
- `level_id = <ctx>:<field>:<target_trading_date>`; unavailable M5 contexts
  never become levels.

## 13. Measurement fields

The four raw offsets are included in M6A (D-126 #9). No scores, categories or
clipped variants are added; a derived clipped penetration is trivially
`max(0, …)` of the orientation-appropriate offset.

## 14. M6A plan (generic only; ORB untouched)

1. **Module and core.** New module `src/features/level_interactions.py`:
   - level and bar validation (raise);
   - per-level exact `f`, `c` and first-tradable prices;
   - a vectorized pair core (approach, then the §6 rules, then status);
   - the long-output builder.
2. **M5 helper** as in §12.
3. **Synthetic unit tests** (§16), then the full suite.
4. **Read-only DEVELOPMENT validation and visual review** (§17), then approval
   and freeze.
5. **Docs:** M6 spec status, decision entry, ARCHITECTURE_MAP, WORK_PROGRESS,
   CHANGELOG, MEMORY.

## 15. M6B plan (ORB migration; after M6A is frozen)

1. **Same engine on an aggregate.** Aggregate the OR window's bars to one
   OHLC and run the **same generic core** on it. The generic `approach_side`
   reproduces ORB `start_side` for `BELOW`/`ABOVE`.
2. **Adapter.** The ORB compatibility adapter holds **only** the legacy
   `AT` rule (touched only, directional flags False), plus schema mapping to
   the `level_*` columns. `start_side` = `approach_side`; the OR distances
   (class C) stay ORB.
3. **Parity.** Exact parity against all 234 frozen `level_*` columns; 0
   mismatches required.
4. **Negative test.** The generic `AT` rule *would* differ on the 3 frozen
   `asia_high` `AT` rows. This protects the adapter from removal. In the
   implementation, removal breaks 718 frozen AT rows; see §21.
5. **Scope.** Class C and D logic stays in ORB.

## 16. Required M6A unit tests (synthetic)

**Cases** (UPPER, with LOWER mirrored):

- **Original side:** below with no interaction; exact touch; one-tick and
  multi-tick trade-through; close-through; exact-touch reject; penetration
  reject; sweep.
- **At the level:** open exactly at `L` (original side); close exactly at
  `L`; extreme exactly one tick beyond.
- **Far side:** fully beyond (all False); gap-open beyond then returning
  (far-side TOUCH / REJECT / SWEEP / CLOSE_THROUGH); `approach_relation` is
  `FAR_SIDE`.

**NEUTRAL levels:**

- a `BELOW` and an `ABOVE` approach;
- `open == L` gives `AMBIGUOUS_APPROACH`, with `touch = True` and the other
  four `<NA>`.

**Off-grid level** (e.g. `L = 100.125`, `t = 0.25`):

- `first_tradable_above` 100.25 and `first_tradable_below` 100.00;
- TOUCH ⇔ TRADE_THROUGH and REJECT ⇔ SWEEP;
- `AT` impossible;
- fractional offsets.

**Other groups:**

- **Invariants (§8):** on every explicit case and on randomized tick-grid bars
  × on-grid and off-grid levels.
- **Causality:**
  - the confirming bar is `PENDING_LEVEL`;
  - the first bar with `bar_start ≥ available_at` is evaluated;
  - no rows after `valid_until`;
  - the M5 helper stays within the target session.
- **Contracts:**
  - `SPECIFIC` with the same contract is evaluated;
  - a mismatch gives `CONTRACT_MISMATCH` with `<NA>`;
  - `AGNOSTIC` is evaluated across contracts;
  - `SPECIFIC` without a contract, or `AGNOSTIC` with one, raises.
- **Tick:** MNQ from metadata; a synthetic 0.1-tick instrument (temp config);
  near-boundary floats (e.g. `0.1 + 0.2` as a bar price on a 0.1 tick is
  accepted within tolerance; a genuinely off-grid bar price raises).
- **Validation:** raises for an invalid orientation or scope, NaN, naive
  timestamps, or inconsistent OHLC.
- **Representation:** nullable dtypes; `False` is distinct from `<NA>`;
  outputs are deterministic and independent of input order.

## 17. Real-data / visual validation plan (after M6A)

- **Source:** DEVELOPMENT, read-only. M5A valid levels give 12 directional
  levels plus 2 NEUTRAL closes per session.
- **Counts** by source × orientation × `approach_relation` × primitive ×
  time-of-day bucket. Frequency is not correctness.
- **Audit:** invariants (§8), causality, contracts, and the NEUTRAL `AT` rows.
- **Visual review:**
  - local HTML, raw prices not tracked; a price-free cases CSV is tracked;
  - exact touches, one-tick penetrations, sweeps, close-throughs;
  - far-side retests and gap-open-then-return bars;
  - NEUTRAL ambiguous rows;
  - confirming bars that stay `PENDING_LEVEL`.
- **ORB cross-check** (informational until M6B): generic per-bar results vs
  the frozen OR-aggregate flags.

## 18. Performance

- **Cost** is O(P), where P = emitted (bar, level) pairs. The pair core is
  vectorized; per-level `Decimal` work is O(levels).
- **DEVELOPMENT via M5:** about 14 levels × 337,815 bars ≈ 4.7M pairs.
  Compute is fast, but a long frame is roughly 0.5–0.7 GB.
- **Mitigations:** per-trading-date processing, an `interactions_only`
  filter, and `valid_until` scoping.
- **Scalability risk:** future many-level sets (swings, EQ/REQ, FVG) multiply
  P and will need caller scoping or price-band pre-filters. That is deferred;
  no event engine is built now.

## 19. Decisions incorporated (D-126) and remaining questions

**Incorporated (2026-09-30):**

1. far-side support through `approach_side`, with orientation kept semantic
   and immutable;
2. a gap open beyond is not itself a TOUCH/TRADE_THROUGH, a later return is a
   far-side interaction, and `GAP_THROUGH` is deferred;
3. `NEUTRAL` orientation, with `open == L` giving `AMBIGUOUS_APPROACH`;
4. `valid_until` as immutable applicability metadata;
5. invalid input raises;
6. off-grid levels are allowed, using exact first-tradable-price arithmetic;
7. directional `open == L` counts as the original side, and ORB's `AT` rule
   is kept only in the M6B adapter;
8. an explicit `SPECIFIC` / `AGNOSTIC` contract scope;
9. raw signed, unclipped `open/high/low/close_offset_ticks`.

**Final answers (2026-09-30, approved for M6A):**

- **a.** NEUTRAL with `open == L` gives `AMBIGUOUS_APPROACH`, `touch = True`,
  and the four directional primitives `<NA>`. Touch is objectively known;
  directional interpretation is not.
- **b.** `PENDING_LEVEL` is emitted **only for the confirming bar** when it
  exists. Earlier bars are never emitted: the level was not yet causally
  known.
- **c.** M5-derived levels set `valid_until` = the **target CME trading
  session close**. This is static applicability metadata consistent with M5
  target-session scope, not lifecycle invalidation. Other level types may
  leave `valid_until` null.

**Applicability bounds (2026-10-01, D-127):** `valid_from` added as optional
immutable applicability metadata, symmetric with `valid_until`. Eligibility
is `bar_start ≥ max(available_at, valid_from)` and `bar_start < valid_until`;
`PENDING_LEVEL` only for a confirming bar inside the static window, enforced
in the generic engine. M5-derived levels: `valid_from` / `valid_until` = the
target session open / close. Trigger: M6A DEV validation found
`previous_rth` levels (available 16:00 on D−1) being evaluated on D−1
16:01–17:00 bars, outside the target session.

## 20. M6A validation results (2026-10-01)

**Unit tests:** `tests/test_level_interactions.py`, 29 tests / 35 subtests,
all passing. They cover the 12 UPPER cases mirrored to LOWER, offsets,
NEUTRAL and ambiguous, off-grid collapse, randomized invariants (2000 bars ×
9 levels), causality, the 8 applicability-boundary cases, unaligned bounds,
contracts, alternate tick, validation errors, representation, and the M5
helper. Full suite: 381 passed, 215 subtests. That is the M5B baseline of
352 (180 subtests) plus the 29 M6A tests (35 subtests).

**DEVELOPMENT (read-only, canonical 1m, generic M5 levels):**

- 337,815 bars; 1,869 M5 contexts, of which 208 are unavailable (none
  became levels); 3,773 levels (UPPER 1,661 / LOWER 1,661 / NEUTRAL 451).
- 3,379,242 pairs: `EVALUATED` 3,376,018; `PENDING_LEVEL` 2,420;
  `AMBIGUOUS_APPROACH` 804; `CONTRACT_MISMATCH` 0.
- Zero failures for: all §8 invariants; no row before `effective_start`;
  pending rows are confirming bars inside the window, one per level; no row
  with `bar_start ≥ valid_until`; no cross-target-session row; evaluated
  rows have matching contracts; NA shapes for pending / mismatch /
  ambiguous; no unavailable context produced a level.
- `CONTRACT_MISMATCH` never occurs in DEVELOPMENT: target-session-scoped M5
  levels never meet a bar of another contract. The rule is exercised by unit
  tests only.
- Off-grid levels never occur in DEVELOPMENT (M5 levels are observed bar
  prices). The visual review uses one clearly labelled synthetic off-grid
  level.
- Price-free counts: `reports/validation/m6a_level_interactions_dev_summary.csv`
  (source × field × orientation × status × approach side/relation ×
  primitives). Frequencies are not performance.

**Visual validation:**
`reports/validation/m6a_level_interactions_visual_validation.html` is local
and Git-ignored (it embeds prices). The price-free case list is
`m6a_level_interactions_visual_validation_cases.csv`. Twelve cases were
reviewed: exact touch, one-tick trade-through, close-through, sweep,
original-side rejection, far-side rejection, NEUTRAL touch, NEUTRAL
ambiguous, pending confirming bar, level known before `valid_from`, final
eligible bar ending at `valid_until`, and synthetic off-grid. All agree with
§6–§9.

## 21. M6B ORB migration results (2026-10-01, D-128)

**Path migrated.** The frozen ORB `level_interaction` in
`src/features/market_context.py` (18 key levels × 13 fields, per session ×
OR duration in `mnq_orb_v02_features.build_feature_audit`) was removed. ORB
now goes through `src/experiments/orb_level_interaction_compat.py`, which
calls `evaluate_level_interactions` (M6A) and does not reimplement any
primitive formula.

**Classification:**

| Class | Behavior | Where |
|---|---|---|
| A (generic, reused) | TOUCH, TRADE_THROUGH, CLOSE_THROUGH, REJECT, SWEEP; geometric `approach_side` (= ORB `start_side`) | M6A |
| B (compatibility) | open-at-level rule; aggregated OR-window evaluation; historical 13-field schema and column order; `available` flag | adapter |
| C (strategy-specific) | OR distance fields (points and `% of or_mid`); ORB categorical labels (`derive_frozen_interaction_state` / `derive_interaction_category`) | adapter / London script |
| D (stateful) | `first_interaction_timestamps` (first touch / first trade-through per bar) | London characterization script (unchanged) |

**Adapter (consumer pattern, not the generic definition):**

- **Aggregated window.** Each OR is one explicit aggregated OHLC bar over
  [09:30, 09:30 + duration), evaluated with `bar_interval = duration`.
- **Bounds.** Each level gets `valid_from = window_start` and
  `valid_until = window_end`, so it pairs only with its own window.
- **Availability.** `available_at = window_start`. This is ORB's historical
  contract that key levels are known before OR completion; the adapter
  declares it and does not re-verify it.
- **Contract scope.** `AGNOSTIC`, because ORB never compared contracts.
- **Orientation** is semantic: `_high` UPPER, `_low` LOWER, closes and
  reference prices NEUTRAL. It is proven not to affect ORB output.
- **The only compatibility rule** applies when the window opens exactly at
  the level (`approach_side == AT`). The adapter keeps generic
  `touched = True` and forces `traded_through`, `closed_through`,
  `rejected` and `swept` to `False`. Generic M6A behavior is unchanged:
  directional AT is original side, and NEUTRAL AT is `AMBIGUOUS_APPROACH`.
- **Equivalence for BELOW / ABOVE.** M6A matches the frozen strict-`>` /
  `<` formulas for all on-grid bars and for any level. It is proven by
  randomized tests against a verbatim frozen reference kept in the test
  file.

**Parity** against
`experiments/projects/mnq_orb_v0_2/features/mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv`
(committed `0120af8`, SHA-256
`7543579877a74a76bbba916a453ca341e08f09d60af9a619bfe64b1cc1017f3b`,
unmodified):

- 744 × 474, column order identical.
- All 234 `level_*` columns (18 × 13) show **0 mismatches** for every field
  and level, and all 474 columns show 0 mismatches.
- Frozen `start_side`: ABOVE 6,422; BELOW 5,442; AT 718.
- AT rows by level: `ny_open_reference` 706 (it *is* the OR open), and 3
  each for `asia_high`, `globex_reopen`, `globex_reopen_prior_1700_close`
  and `previous_day_close`.
- **Negative test.** Without the AT rule, 718 frozen rows break on
  `traded_through` / `closed_through` / `swept` / `rejected` only.

**Generic regression guard:**

- `level_interactions.py` and its tests are unchanged.
- The regenerated M6A DEVELOPMENT summary and case CSVs are
  content-identical to the committed M6A baseline.

**Fixture note (design-authority choice).** Synthetic test fixtures were
off the 0.25 tick grid, and M6A rejects off-grid bars. Both were snapped to
the grid, with assertions unchanged:

- `test_mnq_orb_v02_features.make_owned_session`: the +0.01/min drift is
  floored to 0.25 steps; this affected 5 tests.
- The London characterization `_synthetic_inputs`: 101.2 → 101.25,
  98.8 → 98.75, and the stated OR widths are 2.5 / 2.25; this affected 3
  tests.

**Tests:** `tests/test_orb_level_interaction_compat.py` adds 19 tests. Full
suite: **400 passed**, 215 subtests. That is the post-M6A baseline of 381
plus 19.
