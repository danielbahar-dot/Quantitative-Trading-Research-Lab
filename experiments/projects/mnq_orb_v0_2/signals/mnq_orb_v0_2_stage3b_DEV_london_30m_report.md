# MNQ ORB V0.2 Stage 3B London interaction event characterization

## Scope and chronology

This DEVELOPMENT-only event study contains 187 frozen London High/Low
30-minute OR interaction events: 95
`CLOSE_THROUGH` and 92 `SWEEP`. The primary
directional hypothesis population contains 113 events whose frozen OR
start side matches the declared London High UP / London Low DOWN acceptance
direction. Reverse-start events remain in the event and audit files but do not
enter the primary hypothesis classification.

Timestamps are one-minute bar-end labels. `first_trade_through_timestamp` is the
first strict crossing relative to the frozen OR start side. Eventual
`CLOSE_THROUGH`/`SWEEP` status is retrospective at that timestamp. The state is
causally known only at the 10:00 ET 30m OR close. Excursion windows begin with
the first complete bar after each anchor.

## First trade-through timing

- N: 113
- Minimum: 1 minute(s) after 09:30
- 25th percentile: 2 minutes
- Median: 5 minutes
- 75th percentile: 14 minutes
- Maximum: 30 minutes

## Primary OR-close comparison

| Horizon | Close N | Sweep N | Close median MFE | Sweep median MFE | Close−sweep MFE | Close median MAE | Sweep median MAE | Close−sweep MAE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5m | 61 | 52 | 0.146% | 0.128% | 0.019% | 0.061% | 0.090% | -0.029% |
| 15m | 61 | 52 | 0.223% | 0.197% | 0.027% | 0.173% | 0.124% | 0.049% |
| 30m | 61 | 52 | 0.246% | 0.238% | 0.008% | 0.233% | 0.150% | 0.083% |
| 60m | 61 | 52 | 0.329% | 0.267% | 0.062% | 0.254% | 0.236% | 0.018% |
| session_end | 61 | 52 | 0.617% | 0.509% | 0.108% | 0.623% | 0.549% | 0.074% |

## ORB confirmation groups

The group uses the first later validated 30m PRINT by timestamp. Presence fields
in the event dataset also expose whether either direction occurs later that day.

| State | NO_ORB | OPPOSITE_DIRECTION_ORB | SAME_DIRECTION_ORB |
| --- | --- | --- | --- |
| CLOSE_THROUGH | 2 | 11 | 48 |
| SWEEP | 1 | 19 | 32 |

For CLOSE_THROUGH plus same-direction ORB events (N=48), the median
OR-close-to-ORB delay is 1.00 minutes. Median directional
displacement is 44.12 points from the London level to
OR close, 14.88 additional points from OR close to
the ORB reference, and 64.62 points in total. Median 30m
MFE is 0.317% from the causal OR-close anchor versus
0.241% in the unchanged post-ORB outcome. These windows have
different start times and are descriptive; no P&L or hypothetical fill is used.

## Interaction without a later ORB

| State | N | Median 30m MFE | Median 30m MAE |
| --- | --- | --- | --- |
| CLOSE_THROUGH | 2 | 0.051% | 0.186% |
| SWEEP | 1 | 0.161% | 0.150% |

These rows test whether interaction-state continuation exists without a later
qualifying PRINT. Sparse groups remain `INSUFFICIENT_SAMPLE` in the CSV outputs.

## DEVELOPMENT-half stability

| DEV segment | Close N | Sweep N | Close−sweep MFE | Close−sweep MAE | Sample status |
| --- | --- | --- | --- | --- | --- |
| FULL_DEVELOPMENT | 61 | 52 | 0.008% | 0.083% | SUFFICIENT |
| DEV_FIRST_HALF | 32 | 22 | -0.070% | 0.050% | SUFFICIENT |
| DEV_SECOND_HALF | 29 | 30 | 0.067% | 0.142% | SUFFICIENT |

Positive MFE differences favor acceptance; positive MAE differences mean
acceptance also experienced more adverse excursion. The fixed classification is
`WEAK_OR_UNSTABLE`. The hypothesis remains registered as a DEVELOPMENT-only research candidate, but its event-anchored evidence is weak or unstable and does not satisfy the candidate-promotion guardrail.

## Human review and guardrails

12 representative sessions are queued with status
`PENDING_HUMAN_REVIEW`. Human review is not marked complete. The analysis did not
access Validation/OOS_BURNED, redefine features or PRINT signals, simulate a new
entry, calculate P&L, optimize a threshold, or create a strategy rule.
