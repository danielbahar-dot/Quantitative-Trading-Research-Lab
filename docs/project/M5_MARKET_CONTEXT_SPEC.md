# M5 — Generic Market Context: Specification

Related: [DECISION_LOG](DECISION_LOG.md) (D-110, D-113, D-114, D-121, D-123,
**D-124**) · [ARCHITECTURE_MAP](ARCHITECTURE_MAP.md) ·
[QUALITY_CONTROL](QUALITY_CONTROL.md).

**Status:**

- **M5A: APPROVED / FROZEN** (2026-09-30).
  - Tested (33 focused tests; full suite 341 passed).
  - Visual validation and the semantic audit are complete.
  - The `MISSING_EXPECTED_SESSION` vs `NO_OBSERVATIONS` distinction is
    confirmed.
  - All causal, contract and session invariants pass (§10). Design authority
    approved.
  - Frozen means changes to these semantics require a new
    `definition_version` and a decision entry.
- **M5B (ORB compatibility / migration): NOT STARTED, optional.**
  - It is not required before continuing the generic context / feature
    catalog.

**Code:**

- `src/features/session_context.py`
- Registry: `config/features/market_context_windows.json`
- Tests: `tests/test_session_context.py`

## 1. Generic vs compatibility

A concept is **generic** when it is strategy-independent. It is not
ORB-specific merely because ORB uses it.

- **Generic contexts:**
  - `previous_day`
  - `previous_rth`
  - `asia_2000_0000`
  - `london_0200_0500`
  - `overnight_1800_0700`
  - `overnight_context_2000_0900`
  - `ny_premarket_0700_0900`
- **ORB-specific compatibility definitions** exist **only** where frozen ORB
  semantics genuinely differ. They are deferred to M5B:
  - ORB `overnight` (18:00–09:30) → possible `orb_overnight_1800_0930`;
  - ORB previous-day/RTH *session selection* (previous **available**
    session) → an isolated legacy adapter.
- No ORB duplicate is created where the generic definition is identical. For
  example, `overnight_context_2000_0900` is the same definition ORB uses;
  parity was confirmed.

## 2. Registry (`config/features/market_context_windows.json`)

- **Clock windows** are defined relative to a trading date, with explicit day
  offsets for **both** ends.
- **Contexts** pair a window with a source session: `TARGET` or
  `PREVIOUS_EXPECTED`.
- **Previous Day** is defined in code: the full previous expected session. It
  is never a clock window.

| context_id | window | source | window (ET) | expected 1m bars | available_at |
|---|---|---|---|---|---|
| `asia_2000_0000` | asia_2000_0000 | TARGET | D-1 20:00 → D 00:00 | 240 | 00:00 |
| `london_0200_0500` | london_0200_0500 | TARGET | D 02:00 → 05:00 | 180 | 05:00 |
| `overnight_1800_0700` | overnight_1800_0700 | TARGET | D-1 18:00 → D 07:00 | 780 | 07:00 |
| `overnight_context_2000_0900` | overnight_context_2000_0900 | TARGET | D-1 20:00 → D 09:00 | 780 | 09:00 |
| `ny_premarket_0700_0900` | ny_premarket_0700_0900 | TARGET | D 07:00 → 09:00 | 120 | 09:00 |
| `previous_rth` | rth_0930_1600 | PREVIOUS_EXPECTED | S 09:30 → S 16:00 | 390 | S 16:00 |
| `previous_day` | full_session | PREVIOUS_EXPECTED | S-1 18:00 → S 17:00 | 1380 | S 17:00 |

`D` is the target trading date. `S` is the previous expected open session.
09:00–09:30 belongs to no window.

**Loader validation:**

- identifiers are lowercase snake case and unique;
- `previous_day` and `full_session` are reserved;
- every window lies inside the regular session with start < end;
- `session_id`, timezone, and `bar_end` semantics must match the session spec.

## 3. Previous RTH: the confirmed existing definition

Evidence, all consistent:

- `mnq_orb_v02_features.rth_window = WindowDefinition("rth", 09:30, 16:00)`;
- the frozen timing contract says "prior trading session 09:30-16:00 market
  time; earliest availability prior session 16:00 ET; null/unavailable without
  complete prior RTH";
- `mnq.json` `regular_session` is 09:30 → 16:00 bar-end;
- `completed_trades.py` treats the 16:00 bar as the "final normal RTH minute".

The resulting definition:

- **Window:** 09:30 → 16:00 America/New_York, on the same calendar date as
  its trading date (no midnight crossing).
- **Bars:** bar-end labels 09:31 … 16:00, 390 bars.
- **Close:** the close of the 16:00 bar.
- **Availability:** 16:00 on the source session.
- **Completeness:** strict.

The 16:14 reference in the repository belongs to the separate
`NY_OPEN_GAP` feature; it is not an RTH definition.

## 4. Summary schema (audit tier, `build_market_context`)

There is one row per *(expected open target trading date, context)*. Dates
with no data are included, which is what keeps missing sessions visible.

| Group | Columns |
|---|---|
| Identity | `context_id`, `context_type` (`TARGET_SESSION_WINDOW` / `PREVIOUS_SESSION_WINDOW` / `PREVIOUS_SESSION`), `window_id`, `definition_version`, `instrument_id` |
| Dates and window | `target_trading_date`, `source_trading_date`, `window_start`, `window_end`, `available_at` (= `window_end`) |
| Contract | `contract` (the single observed contract, else null), `contract_count` |
| Observed values | `observed_open`, `observed_high`, `observed_low`, `observed_close`, `high_at`, `low_at` (first occurrence); **diagnostic only** |
| Counts | `expected_count`, `observed_count`, `missing_count` |
| Status | `is_complete`, `is_schedule_clipped`, `is_available`, `unavailable_reason` (null ⇔ available), `calendar_verified` (metadata only) |

The summary deliberately has no plain `high`/`low` columns, so observed values
cannot be mistaken for valid context.

## 5. Completeness and schedule

For each context:

- The nominal window is intersected with the actual source session from the
  session model, with verified overrides applied.
- **Expected** = the 1m bar-end grid over `(start, end]` of that intersection.
- **Available** requires *every* expected bar, a single contract, and full
  source coverage.
- There is no fill, interpolation, substitution, or silent shortening.

Verified overrides:

- **Partial clipping:** the context can still be available, with
  `is_schedule_clipped = True`.
- **Zero scheduled minutes:** `NOT_SCHEDULED`.
- **Unverified early data end:** stays `INCOMPLETE_WINDOW`.

## 6. Unavailable reasons (summary; first match wins)

1. `INSUFFICIENT_HISTORY`: window starts before the source coverage start.
2. `INSUFFICIENT_FUTURE_COVERAGE`: window ends after the source coverage end.
3. `MISSING_EXPECTED_SESSION`: the source session has zero bars.
4. `NOT_SCHEDULED`: a verified schedule leaves zero minutes.
5. `NO_OBSERVATIONS`: the session has bars, but none in the window.
6. `MIXED_CONTRACT`: more than one contract in the window.
7. `INCOMPLETE_WINDOW`: some expected minutes are missing.

Coverage defaults to the first bar-start through the last bar-end. An explicit
coverage may be supplied, but it must contain every bar. `calendar_verified` is
never a reason.

## 7. Previous Day / Previous RTH (session selection)

- **Source session:** `previous_expected_session(D)` from the M1 session
  model. Weekends and verified CLOSED dates are skipped; `calendar_verified`
  is ANDed over the dates examined.
- **No fallback.** A missing expected source session gives
  `MISSING_EXPECTED_SESSION`. Older available data is never used.
- **Frozen ORB differs (D-121).** On DEVELOPMENT, frozen ORB used an older
  available session on exactly six dates: the four roll Fridays (2024-09-20,
  2024-12-20, 2025-03-21, 2025-06-20), 2025-01-02, and 2025-04-21. Generic
  output is unavailable on those dates. This difference is intentional.

## 8. Tiers and causal alignment

1. **Audit summary** (`build_market_context`): every attempt, observed
   diagnostics included.
2. **Valid levels** (`valid_context_levels`): `is_available` rows only, with
   `open/high/low/close/high_at/low_at`.
3. **Bar alignment** (`align_market_context`): per 1m bar,
   `<context_id>_<field>` plus `<context_id>_status`.

Alignment statuses (never used as summary reasons):

| Status | Meaning |
|---|---|
| `AVAILABLE` | Valid, visible (`bar_start ≥ available_at`, i.e. `bar_end > available_at` for 1m), and the bar's contract equals the context contract |
| `PENDING` | Valid but not yet visible; the completing bar itself is `PENDING` |
| `UNAVAILABLE_CONTEXT` | No valid summary for this bar's trading date |
| `CONTRACT_MISMATCH` | Valid context from a different contract than the bar; the summary stays valid |

**Target-session scope:** context for trading date D is aligned **only** to
bars of trading date D and never carries into another session. Multi-session
lifecycles belong to later layers.

## 9. DEVELOPMENT validation (2026-09-29, read-only)

337,815 bars; 267 expected open target dates (248 with data plus 19 absent
weekdays); all `calendar_verified = False` (empty calendar); 0 clipped; 0
mixed.

| context | available | unavailable reasons |
|---|---|---|
| asia_2000_0000 | 243 | MISSING_EXPECTED_SESSION 19, NO_OBSERVATIONS 4 (roll Fridays), INSUFFICIENT_HISTORY 1 |
| london_0200_0500 | 245 | MISSING_EXPECTED_SESSION 19, INCOMPLETE_WINDOW 3 |
| overnight_1800_0700 | 236 | MISSING_EXPECTED_SESSION 19, INCOMPLETE_WINDOW 11, INSUFFICIENT_HISTORY 1 |
| overnight_context_2000_0900 | 238 | MISSING_EXPECTED_SESSION 19, INCOMPLETE_WINDOW 9, INSUFFICIENT_HISTORY 1 |
| ny_premarket_0700_0900 | 248 | MISSING_EXPECTED_SESSION 19 |
| previous_rth | 232 | MISSING_EXPECTED_SESSION 19, INCOMPLETE_WINDOW 14, INSUFFICIENT_HISTORY 1, NO_OBSERVATIONS 1 |
| previous_day | 219 | INCOMPLETE_WINDOW 27, MISSING_EXPECTED_SESSION 19, INSUFFICIENT_HISTORY 2 |

- No `CONTRACT_MISMATCH` alignments occur on DEVELOPMENT. Each roll Friday's
  previous expected session (the Thursday) is absent, so it is already
  unavailable.

**Frozen ORB parity observations** (reference: the Git-tracked
`experiments/projects/mnq_orb_v0_2/features/mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv`,
248 sessions):

- **Exact parity** for Asia, London, NY Pre-market and Overnight Context:
  availability, OHLC, high/low timestamps, and expected counts.
- **Previous RTH and Previous Day:** 0 value mismatches where both are
  available. There are exactly 6 availability differences, all of them the
  intentional D-121 cases listed in §7.
- **ORB `overnight` (930 bars) ≠ generic `overnight_1800_0700` (780 bars).**
  This is intentional (D-114).

## 10. Final M5A validation (2026-09-30, DEVELOPMENT, read-only)

**Visual review.** Artifacts are in `reports/validation/`:

- `m5a_market_context_visual_validation.html`: candles, with levels drawn
  **only** from `align_market_context` (status `AVAILABLE`). It is local
  only and Git-ignored, because it embeds raw prices.
- `m5a_market_context_visual_validation_cases.csv`: price-free causality
  facts per session × context. This is the tracked audit artifact.

| Session | Case | Confirmed |
|---|---|---|
| 2024-10-01, 2025-05-01 | Normal | All 7 contexts are drawn. Each level starts exactly one bar after its dotted `available_at`, and the completing bar is `PENDING`. Previous Day / RTH are visible from the first session bar |
| 2024-12-20 | Roll Friday | Session starts 00:01. Only London and NY pre-market are drawn. Asia is `NO_OBSERVATIONS`; both overnights are `INCOMPLETE_WINDOW`; Previous Day / RTH are `MISSING_EXPECTED_SESSION`. None of these is drawn |
| 2025-01-02 | After a missing session | Previous Day / RTH are `MISSING_EXPECTED_SESSION` (2025-01-01 absent, unverified). No older session is substituted (frozen ORB would use 2024-12-31) |
| 2025-01-23 | Incomplete window | London and both overnights are `INCOMPLETE_WINDOW` and not drawn. The gap is visible in the candles |
| 2024-11-04, 2025-03-10 | DST-adjacent | Windows sit on wall-clock boundaries. The weekend exposure delay for Previous Day / RTH reflects the true elapsed time (±60 min) |

**Reason semantics** (verified for every row):

- **`MISSING_EXPECTED_SESSION`:** the source *session itself* has zero bars
  although the session model expects it to be open.
  - This covers the 19 absent DEVELOPMENT weekdays: 16 in roll weeks, plus
    2024-12-25, 2025-01-01 and 2025-04-18, which stay unverified because the
    calendar is empty.
  - All five same-session contexts on those dates, and Previous Day / RTH
    sourced from them, carry this reason.
- **`NO_OBSERVATIONS`:** the source session *has* bars, but none fall in this
  window.
  - The 4 roll-Friday Asia cases: those sessions have 1,020 bars starting at
    00:01, while the Asia window ends at 00:00.
  - Previous RTH on 2025-01-10: the source session 2025-01-09 ends at 09:30.

**Invariants** (all 337,815 bars, every context): all checks pass.

- No value is exposed unless `AVAILABLE`, and never when the summary is
  unavailable.
- Nothing is exposed before `available_at`; completing bars are never
  exposed.
- The exposed level always belongs to the bar's own target trading date.
- Nothing is exposed across contracts. An adversarial in-memory contract
  relabel gives `CONTRACT_MISMATCH`, and the summary is unchanged.
- The Previous Day / RTH source always equals `previous_expected_session`,
  with no observations taken from any other session.

## 11. M5B (not started; optional)

M5B is optional compatibility / migration work. It is **not** a
prerequisite for continuing the generic catalog (e.g. M6). It needs separate
approval, and would include:

- a formal read-only parity harness;
- a legacy compatibility config/adapter for ORB `overnight` 18:00–09:30 and
  previous-*available*-session selection;
- optionally, routing ORB through the generic engine behind golden tests.

Frozen artifacts are never rewritten.
