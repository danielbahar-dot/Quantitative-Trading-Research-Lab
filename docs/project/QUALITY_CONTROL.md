# Quality Control

Internal engineering and research review process. Related:
[RESEARCH_GOVERNANCE](RESEARCH_GOVERNANCE.md) ·
[REVIEW_CHECKLIST](REVIEW_CHECKLIST.md) (short daily-use version) ·
`docs/RESEARCH_LIFECYCLE_V1.md` (canonical lifecycle stages).

## Review status vocabulary

| Status | Meaning |
|---|---|
| `DRAFT` | Written specification exists; not implemented or still changing |
| `IMPLEMENTED` | Code matches the spec; tests may be incomplete |
| `TESTED` | Unit, invariant, edge-case, and negative-case tests pass |
| `VISUALLY_VALIDATED` | Chart review of representative and negative cases completed and recorded |
| `APPROVED` | Human (design authority) approved the definition and evidence |
| `FROZEN` | Versioned; definition and artifacts are read-only. Changes require a new version |
| `DEPRECATED` | Superseded; retained for lineage, not for new use |

Statuses advance in order. A downstream layer may only consume `FROZEN`
components (exploratory use must be labeled as such). Existing registry values
in `config/components/research_components.json` (`reference`, `validated`)
predate this vocabulary and are left unchanged.

## Standard process for a new deterministic feature

1. Written formal specification → 2. Causal availability definition →
3. Unit tests → 4. Invariant tests → 5. Edge-case tests → 6. Negative-case
sampling → 7. Audit/export output → 8. Visual chart validation →
9. Human approval → 10. Freeze/version → 11. Downstream use allowed.

## Common temporal checks (apply wherever relevant)

- Timestamp semantics (bar-end labels, `timestamp_et`) and timezone.
- Session boundaries, `session_date` ownership, shortened sessions, holidays.
- Warm-up periods and null behavior before sufficient history.
- No look-ahead; same-bar vs next-bar availability stated explicitly.
- Missing data, session gaps, duplicate timestamps.
- Contract/roll boundaries; tick-size assumptions and rounding.
- Deterministic IDs; lifecycle transitions (e.g. ACTIVE → TAKEN).
- Feature/state/signal parity; regression against validated artifacts.

---

## 1. Feature implementation review

- [ ] Formal spec exists and implementation matches it line by line.
- [ ] Availability timestamp defined for every output; no future data used.
- [ ] Deterministic: identical inputs → identical outputs and IDs.
- [ ] Warm-up/null behavior explicit; no backfill.
- [ ] Timestamp/session/timezone semantics unchanged or explicitly approved.
- [ ] Unit, invariant, edge-case, and negative-case tests added and passing.
- [ ] Audit/export table produced with enough columns to verify by hand.
- [ ] Visual validation performed or explicitly pending.
- [ ] No parameter chosen by looking at performance.

## 2. State / signal review

- [ ] Consumes only `FROZEN` (or explicitly exploratory) features.
- [ ] State is causal at its decision timestamp; signal event time and first
      executable time are distinct and stated.
- [ ] Signals are recorded even when no trade follows.
- [ ] Edge cases: same-bar multiple events, session boundaries, missing bars.
- [ ] Negative cases sampled (conditions that should *not* fire).
- [ ] Parity check between feature table and state/signal table.
- [ ] Visual validation of representative and negative cases.

## 3. Strategy review

- [ ] Strategy spec separate from feature/signal definitions.
- [ ] Eligibility, entry, exit, sizing, ambiguity policy fully defined.
- [ ] Instrument facts come from instrument config, not strategy code.
- [ ] Parameter domains declared before running; partition stated.
- [ ] No rule added or changed without a recorded hypothesis and decision.

## 4. Execution / backtest review

- [ ] Fill timing (same-bar / next-bar) matches spec.
- [ ] Stop/target formulas tested independently for long and short.
- [ ] Tick rounding, session exits, shortened sessions tested.
- [ ] Intrabar ambiguity flagged and audited, never silently resolved.
- [ ] Trade limits and rejected candidates audited.
- [ ] Frozen controls reproduce previously validated results exactly.
- [ ] VectorBT used only where its assumptions are faithful.

## 5. Data change review

- [ ] Raw data untouched; transform versioned and reproducible.
- [ ] Hashes and row counts recorded before/after.
- [ ] Timestamp semantics, timezone, session ownership verified.
- [ ] Duplicates, gaps, missing bars, roll boundaries reported.
- [ ] Partition membership unchanged or change explicitly approved.
- [ ] Downstream artifacts affected are identified.

## 6. Experiment / research review

- [ ] Hypothesis and falsification criteria declared before running.
- [ ] Canonical lifecycle stage and partition declared; reserved data not
      exposed unless authorized.
- [ ] Config saved; experiment registered via the registration API.
- [ ] Dataset ID/hash, Git SHA, environment captured.
- [ ] Results interpreted with sample size, stability, and observability — not
      a single best cell.
- [ ] No performance-driven rule changes without a new hypothesis/version.

## 6a. Generalization / parity review (moving logic out of ORB)

- [ ] The generic implementation is added alongside ORB; ORB code is unchanged
      until parity is proven and migration is separately approved.
- [ ] Parity tests compare generic outputs with frozen ORB outputs, value for
      value, including availability timestamps and missing reasons.
- [ ] Every intended semantic difference is listed and approved (e.g. D-113
      expected-session vs ORB dataset-previous session).
- [ ] Generic code takes session, timezone, and tick facts from their
      authoritative sources (`src/data/sessions.py`, instrument config), with
      no new hard-coded constants.
- [ ] Derived timeframes: no HTF value is visible before its `available_at`,
      and no bars are synthesized.

## 7. Release / freeze review

- [ ] All status steps through `APPROVED` completed and recorded.
- [ ] Version identifier assigned; spec, config, code SHA, data boundary frozen.
- [ ] Regression tests pin the frozen behavior.
- [ ] Artifacts stored under the project directory; nothing overwritten.
- [ ] DECISION_LOG, CHANGELOG, WORK_PROGRESS updated; MEMORY if durable.
