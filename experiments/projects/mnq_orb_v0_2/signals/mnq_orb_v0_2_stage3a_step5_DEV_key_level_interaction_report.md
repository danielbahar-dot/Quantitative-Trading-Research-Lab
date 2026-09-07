# MNQ ORB V0.2 Stage 3A Step 5 key-level interaction

## Scope and deterministic category mapping

This DEVELOPMENT-only analysis uses 935 Step-1B PRINT breakout
events and only frozen Stage-2 key-level interaction primitives for previous-day,
NY pre-market, London, and Asia high/low families. Existing normalized
post-signal-bar MFE/MAE at 5m, 15m, 30m, 60m, and session end are the outcomes.
Signal-bar excursion is excluded because its chronology is unknown.

Each family aggregates its high/low primitive flags without changing them. One
analysis category is assigned by the fixed precedence `SWEEP`, `REJECTION`,
`CLOSE_THROUGH`, `TOUCH_ONLY`, then `NO_INTERACTION`. An unavailable family is
excluded and is never treated as no interaction. The CSVs retain primitive-flag
counts under every exclusive state.

The input contains 247 event-bearing dates. The first
123 (2024-06-21 through
2024-12-20) form `DEV_FIRST_HALF`; the final
124 (2024-12-23 through
2025-06-30) form `DEV_SECOND_HALF`.

| Family | Eligible N | Unavailable N | NO_INTERACTION | TOUCH_ONLY | CLOSE_THROUGH | REJECTION | SWEEP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Previous day | 830 | 105 | 588 | 0 | 142 | 0 | 100 |
| NY pre-market | 935 | 0 | 126 | 0 | 464 | 3 | 342 |
| London | 927 | 8 | 349 | 0 | 255 | 1 | 322 |
| Asia | 916 | 19 | 410 | 6 | 221 | 2 | 277 |

## Relationship assessment

Each family/duration assessment uses the state with the highest median MFE across
the five clean horizons, excludes states with fewer than 10 events from the
relationship inference, and requires a 30m state contrast of at least one quarter
of the median within-state IQR. `CONSISTENT_CANDIDATE_STATE` additionally requires
the same full/first-half/second-half pattern and at least 10 events in the top
state in each half. These are descriptive guardrails, not optimized thresholds.

| Level family | OR min | Full DEV | First half | Second half | Assessment |
| --- | --- | --- | --- | --- | --- |
| Previous day | 15 | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_SWEEP | WEAK_OR_UNSTABLE |
| Previous day | 20 | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_SWEEP | WEAK_OR_UNSTABLE |
| Previous day | 30 | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_SWEEP | WEAK_OR_UNSTABLE |
| NY pre-market | 15 | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_CLOSE_THROUGH | NO_CLEAR_RELATIONSHIP |
| NY pre-market | 20 | HIGHEST_MFE_SWEEP | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_SWEEP | WEAK_OR_UNSTABLE |
| NY pre-market | 30 | HIGHEST_MFE_SWEEP | HIGHEST_MFE_SWEEP | HIGHEST_MFE_CLOSE_THROUGH | NO_CLEAR_RELATIONSHIP |
| London | 15 | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_CLOSE_THROUGH | WEAK_OR_UNSTABLE |
| London | 20 | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_CLOSE_THROUGH | HIGHEST_MFE_CLOSE_THROUGH | NO_CLEAR_RELATIONSHIP |
| London | 30 | HIGHEST_MFE_CLOSE_THROUGH | HIGHEST_MFE_CLOSE_THROUGH | HIGHEST_MFE_CLOSE_THROUGH | CONSISTENT_CANDIDATE_STATE |
| Asia | 15 | HIGHEST_MFE_SWEEP | HIGHEST_MFE_SWEEP | HIGHEST_MFE_CLOSE_THROUGH | WEAK_OR_UNSTABLE |
| Asia | 20 | HIGHEST_MFE_NO_INTERACTION | HIGHEST_MFE_SWEEP | HIGHEST_MFE_CLOSE_THROUGH | WEAK_OR_UNSTABLE |
| Asia | 30 | HIGHEST_MFE_CLOSE_THROUGH | HIGHEST_MFE_CLOSE_THROUGH | HIGHEST_MFE_CLOSE_THROUGH | NO_CLEAR_RELATIONSHIP |

Potentially informative relationships: London / 30m.

Consistent across DEV halves: London / 30m.

Weak or no-clear relationships: Previous day / 15m, Previous day / 20m, Previous day / 30m, NY pre-market / 15m, NY pre-market / 20m, NY pre-market / 30m, London / 15m, London / 20m, Asia / 15m, Asia / 20m, Asia / 30m.

## Acceptance versus sweep and rejection

`CLOSE_THROUGH` is the acceptance state. `SWEEP` has precedence over rejection
because the frozen sweep primitive also carries rejection. Non-sweep
`REJECTION` is reported separately but is sparse in this dataset.

| Family | OR min | Close N | Sweep N | Reject N | Close−sweep median MFE | Close−sweep median MAE |
| --- | --- | --- | --- | --- | --- | --- |
| Previous day | 15 | 39 | 34 | 0 | -0.051% | 0.019% |
| Previous day | 20 | 52 | 32 | 0 | 0.037% | 0.014% |
| Previous day | 30 | 51 | 34 | 0 | 0.013% | 0.063% |
| NY pre-market | 15 | 163 | 115 | 2 | 0.002% | 0.047% |
| NY pre-market | 20 | 155 | 121 | 1 | -0.007% | 0.008% |
| NY pre-market | 30 | 146 | 106 | 0 | -0.017% | 0.037% |
| London | 15 | 91 | 106 | 1 | 0.048% | -0.041% |
| London | 20 | 87 | 108 | 0 | 0.026% | -0.019% |
| London | 30 | 77 | 108 | 0 | 0.095% | 0.014% |
| Asia | 15 | 61 | 104 | 0 | 0.027% | 0.014% |
| Asia | 20 | 87 | 86 | 1 | 0.019% | -0.002% |
| Asia | 30 | 73 | 87 | 1 | 0.012% | 0.000% |

Positive close−sweep MFE means acceptance produced more favorable excursion;
positive close−sweep MAE means acceptance also produced more adverse excursion.
The full five-horizon paths and half-sample comparisons remain in the CSVs.

## LONG/SHORT differences

| Family | Side | Largest 30m median-MFE state span | OR duration |
| --- | --- | --- | --- |
| Previous day | LONG | 0.074% | 15 |
| Previous day | SHORT | 0.110% | 30 |
| NY pre-market | LONG | 0.063% | 15 |
| NY pre-market | SHORT | 0.092% | 20 |
| London | LONG | 0.087% | 30 |
| London | SHORT | 0.133% | 30 |
| Asia | LONG | 0.068% | 30 |
| Asia | SHORT | 0.077% | 15 |

The spans show where direction-specific differences are largest. They do not
rank or define strategy rules.

## OR-duration and reference-family context

| OR min | Median 30m state contrast | Assessments |
| --- | --- | --- |
| 15 | 0.056% | WEAK_OR_UNSTABLE=3, NO_CLEAR_RELATIONSHIP=1 |
| 20 | 0.023% | WEAK_OR_UNSTABLE=3, NO_CLEAR_RELATIONSHIP=1 |
| 30 | 0.045% | NO_CLEAR_RELATIONSHIP=2, WEAK_OR_UNSTABLE=1, CONSISTENT_CANDIDATE_STATE=1 |

Family labels with small or unstable states are not treated as superior even if
a point estimate is large. Combined-duration output is secondary context only.

## Comparison with Step 4 room distance

Interaction states show more descriptive promise than Step 4 room distance because 1 family/duration relationships clear the informative guardrail, while Step 4 recorded none. This is not evidence of a trading rule.

No Step-4 state was recalculated or combined with an interaction state.

## Output guardrail

No OR-width, internal-structure, room-distance, pre-open, gap, combined-state,
strategy-performance, filter, optimization, or ML analysis was performed. Step 5
is complete; overall Stage 3A remains incomplete and reserved partitions remain
unexposed.
