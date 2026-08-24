# Gate 7 — predeclared MNQ ORB V0.1 Validation protocol

**Status:** `PREDECLARED_LOCKED`  
**Declared:** 2026-08-24T12:23:11.772990Z  
**Partition:** VALIDATION, 2025-07-01 through 2025-12-31 inclusive

This protocol was written before loading or calculating Validation performance.
Validation is confirmatory rather than exploratory.

## Frozen candidates

- `MNQ_ORB_V01_CAND_001`: 15m PRINT, fixed 50-point stop, fixed 75-point target.
- `MNQ_ORB_V01_CAND_002`: 20m PRINT, OR-midpoint stop, fixed 75-point target.
- `MNQ_ORB_V01_CAND_003`: 30m PRINT, fixed 40-point stop, fixed 75-point target.

`MNQ_ORB_V01_HYP_001` and `MNQ_ORB_V01_HYP_002` are excluded from Validation.

## Confirmatory question

> Does the positive edge and execution robustness observed during DEVELOPMENT
> survive on the reserved VALIDATION period without changing the strategy?

The primary metrics, degradation formulas, chronology scenarios, borderline
margins, temporal-concentration rule, observability thresholds, and
PASS/REVISE/REJECT logic are fixed in the adjacent JSON protocol. No composite
score is used.

Temporal breadth is `BROAD` only when Total R is positive, at least half of the
observed months are positive, the best positive month contributes no more than
60% of positive monthly R, and the second half does not give back at least half
of a positive first-half result. Positive results failing breadth without the
giveback condition are `CONCENTRATED`; non-positive or material giveback paths
are `UNSTABLE`.

No parameter alternative, research-hypothesis candidate, filter, indicator,
combined portfolio, Validation retuning, or OOS_BURNED access is authorized.
