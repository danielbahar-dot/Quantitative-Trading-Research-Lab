# MNQ ORB V0.2 Stage 3C combined-state hypothesis test

## Scope

This final ORB round tests `HYP-ORB-STATE-01` on DEVELOPMENT only. It uses only
20-minute validated PRINT events, four frozen causal OR-width percentiles, the
unchanged Step-3 20-minute OR-efficiency quintiles, and existing clean
post-signal-bar percentage MFE/MAE. Signal-bar excursion is excluded. No
threshold search, feature search, strategy execution, P&L, Validation, or
OOS_BURNED data is used.

Width bands use `[0.00, 0.20)`, `[0.20, 0.40)`, `[0.40, 0.60)`,
`[0.60, 0.80)`, and `[0.80, 1.00]`. The primary state is width Q4/Q5 with
efficiency Q1-Q4. The max-efficiency comparison is width Q4/Q5 with efficiency
Q5. The not-elevated comparison is width Q1-Q3. Missing warm-up percentiles are
not backfilled.

## Eligibility and group counts

| Lookback | Eligible N | Primary N | Elevated + max-eff N | Not elevated N |
| --- | --- | --- | --- | --- |
| 5 sessions | 303 | 100 | 38 | 165 |
| 10 sessions | 293 | 93 | 29 | 171 |
| 15 sessions | 278 | 88 | 32 | 158 |
| 20 sessions | 266 | 81 | 32 | 153 |

## Full-DEVELOPMENT primary contrasts

Differences are primary state minus `WIDTH_NOT_ELEVATED`. Positive MFE favors
the hypothesis. Positive MAE means more adverse excursion.

| Lookback | 30m MFE delta | 30m MAE delta | 60m MFE delta | 60m MAE delta | Max-eff underperforms |
| --- | --- | --- | --- | --- | --- |
| 5d | 0.078% | -0.027% | 0.150% | -0.048% | True |
| 10d | 0.090% | 0.027% | 0.135% | 0.040% | False |
| 15d | 0.071% | 0.062% | 0.116% | 0.069% | True |
| 20d | 0.072% | 0.108% | 0.096% | 0.108% | True |

## DEVELOPMENT-half stability

The same event-date split as Stage 3A is reused: 2024-06-21
through 2024-12-20 and 2024-12-23 through
2025-06-30. Average deltas below average the predeclared 30m and
60m horizons only.

| Lookback | Segment | Avg 30m/60m MFE delta | Avg quality delta |
| --- | --- | --- | --- |
| 5d | DEV_FIRST_HALF | 0.111% | 0.175% |
| 5d | DEV_SECOND_HALF | 0.132% | 0.112% |
| 10d | DEV_FIRST_HALF | 0.111% | 0.121% |
| 10d | DEV_SECOND_HALF | 0.100% | -0.024% |
| 15d | DEV_FIRST_HALF | 0.105% | 0.102% |
| 15d | DEV_SECOND_HALF | 0.094% | -0.071% |
| 20d | DEV_FIRST_HALF | 0.097% | 0.081% |
| 20d | DEV_SECOND_HALF | 0.073% | -0.121% |

## LONG and SHORT context

| Lookback | Direction | Avg 30m/60m MFE delta | Avg quality delta |
| --- | --- | --- | --- |
| 5d | LONG | 0.091% | 0.108% |
| 5d | SHORT | 0.159% | 0.201% |
| 10d | LONG | 0.091% | 0.063% |
| 10d | SHORT | 0.137% | 0.099% |
| 15d | LONG | 0.086% | 0.079% |
| 15d | SHORT | 0.132% | 0.009% |
| 20d | LONG | 0.071% | 0.020% |
| 20d | SHORT | 0.115% | -0.023% |

## Guardrail assessment

| Lookback | Sample adequate | Full-DEV support | Max-eff underperforms | Both halves support | LONG/SHORT consistent | Improves width-only interpretation | Promotion ready |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | True | True | True | True | True | True | True |
| 10 | True | True | False | False | True | False | False |
| 15 | True | True | True | False | True | True | False |
| 20 | True | False | True | False | False | True | False |

Final evidence classification: `POTENTIALLY_INFORMATIVE`.

ORB research disposition: `PARKED_AS_RESEARCH_CANDIDATE`.

The combined state is judged more interpretable than width alone for
3 of four causal lookbacks. This
is a descriptive hypothesis result, not a trading filter or validation result.

## Optional frozen-strategy diagnostic

Skipped. The exact 20m PRINT / midpoint / target75 freeze is available only in
aggregate candidate evidence, not as a reusable event-level trade artifact.
Producing conditional Avg R, PF, and win rate would require rebuilding execution,
which is outside this run.

## Output guardrail

The master CSV contains full-DEVELOPMENT results. The stability CSV contains
full, first-half, and second-half results for ALL, LONG, and SHORT. The direction
CSV contains full-DEVELOPMENT LONG/SHORT results. All percentages retain the
frozen fractional convention. The hypothesis is not validated or approved.
