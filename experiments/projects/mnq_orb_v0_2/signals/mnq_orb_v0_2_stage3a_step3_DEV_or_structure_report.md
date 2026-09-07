# MNQ ORB V0.2 Stage 3A Step 3 OR internal structure

## Scope

This DEVELOPMENT-only analysis uses 935 Step-1B PRINT breakout events and only
four internal OR fields: OR efficiency, directional CLV, OR/breakout alignment,
and directional OR net-move percentage. Existing normalized post-signal-bar
MFE/MAE at 5m, 15m, 30m, 60m, and session end are the outcomes. Signal-bar
excursion is excluded because its chronology is unknown. No OR-width state,
other state family, strategy performance, filter, optimization, or ML is used.

## State definitions

Each continuous feature uses ordinary full-DEVELOPMENT value quintiles
calculated separately for the 15m, 20m, and 30m OR. Combined results use their
own full-DEVELOPMENT boundaries and are secondary context. Boundaries are
left-inclusive and right-exclusive, except the final interval includes its
upper bound. The full-DEVELOPMENT boundaries are recorded in every CSV and
reused unchanged for DEV halves and LONG/SHORT splits. Duplicate edges collapse
deterministically. Alignment uses `ALIGNED`, `OPPOSED`, and `FLAT` exactly as
stored. Only 3 FLAT events exist, all at 15m, so
FLAT remains reported but is excluded from relationship classification.

The input contains 247 event-bearing dates. The first
123 (2024-06-21 through
2024-12-20) form `DEV_FIRST_HALF`; the final
124 (2024-12-23 through
2025-06-30) form `DEV_SECOND_HALF`.

## Relationship assessment

Patterns must recur in at least three of five clean horizons. Continuous-state
monotonic patterns require absolute Spearman ordering of at least 0.70. A
relationship also needs a 30m median-MFE contrast of at least one quarter of the
median within-state IQR before it can be informative. Consistent candidate-state
labels additionally require the same pattern in full DEV and both halves with at
least 10 events in every inferential half-state. These fixed descriptive rules
are classification guardrails, not trading thresholds.

| Feature | OR min | Full DEV | First half | Second half | Assessment |
| --- | --- | --- | --- | --- | --- |
| OR efficiency | 15 | MIDDLE_RANGE_PREFERENCE | HIGH_STATE_DETERIORATION | HIGH_STATE_DETERIORATION | WEAK_OR_UNSTABLE |
| OR efficiency | 20 | HIGH_STATE_DETERIORATION | HIGH_STATE_DETERIORATION | HIGH_STATE_DETERIORATION | CONSISTENT_CANDIDATE_STATE |
| OR efficiency | 30 | MIDDLE_RANGE_PREFERENCE | HIGH_STATE_DETERIORATION | MONOTONIC_HIGHER_STATE_MORE_MFE | WEAK_OR_UNSTABLE |
| Directional CLV | 15 | MONOTONIC_HIGHER_STATE_MORE_MFE | HIGH_STATE_DETERIORATION | MIDDLE_RANGE_PREFERENCE | WEAK_OR_UNSTABLE |
| Directional CLV | 20 | MIDDLE_RANGE_PREFERENCE | MIDDLE_RANGE_PREFERENCE | MIDDLE_RANGE_PREFERENCE | NO_CLEAR_RELATIONSHIP |
| Directional CLV | 30 | MIDDLE_RANGE_PREFERENCE | HIGH_STATE_DETERIORATION | NO_CLEAR_PATTERN | WEAK_OR_UNSTABLE |
| Directional OR net move | 15 | MIDDLE_RANGE_PREFERENCE | HIGH_STATE_DETERIORATION | MIDDLE_RANGE_PREFERENCE | POTENTIALLY_INFORMATIVE |
| Directional OR net move | 20 | NO_CLEAR_PATTERN | MIDDLE_RANGE_PREFERENCE | NO_CLEAR_PATTERN | NO_CLEAR_RELATIONSHIP |
| Directional OR net move | 30 | MONOTONIC_HIGHER_STATE_MORE_MFE | MONOTONIC_HIGHER_STATE_MORE_MFE | NO_CLEAR_PATTERN | WEAK_OR_UNSTABLE |
| OR/breakout alignment | 15 | ALIGNED_MORE_MFE | ALIGNED_MORE_MFE | OPPOSED_MORE_MFE | WEAK_OR_UNSTABLE |
| OR/breakout alignment | 20 | OPPOSED_MORE_MFE | OPPOSED_MORE_MFE | OPPOSED_MORE_MFE | NO_CLEAR_RELATIONSHIP |
| OR/breakout alignment | 30 | ALIGNED_MORE_MFE | ALIGNED_MORE_MFE | OPPOSED_MORE_MFE | WEAK_OR_UNSTABLE |

The strongest result is 20m OR efficiency: the highest-efficiency quintile has
lower MFE and higher MAE than the middle of the distribution, and that
high-state deterioration pattern persists across both DEV halves. The only
other relationship above the materiality guardrail is 15m directional OR net
move, where a middle-range preference is potentially informative but not fully
stable.

Consistent across DEV halves: OR efficiency / 20m

Weak or no-clear relationships: OR efficiency / 15m, OR efficiency / 30m, Directional CLV / 15m, Directional CLV / 20m, Directional CLV / 30m, Directional OR net move / 20m, Directional OR net move / 30m, OR/breakout alignment / 15m, OR/breakout alignment / 20m, OR/breakout alignment / 30m

## LONG and SHORT context

The largest 30m median-MFE state spans by side are shown only to describe where
directional differences are most visible. They do not rank trading rules.

| Feature | Side | Largest 30m median-MFE state span | OR duration |
| --- | --- | --- | --- |
| OR efficiency | LONG | 0.182% | 15 |
| OR efficiency | SHORT | 0.261% | 30 |
| Directional CLV | LONG | 0.087% | 30 |
| Directional CLV | SHORT | 0.142% | 30 |
| Directional OR net move | LONG | 0.148% | 30 |
| Directional OR net move | SHORT | 0.242% | 30 |
| OR/breakout alignment | LONG | 0.043% | 30 |
| OR/breakout alignment | SHORT | 0.086% | 15 |

## OR-duration context

| OR min | Median 30m MFE contrast across features | Assessments |
| --- | --- | --- |
| 15 | 0.091% | WEAK_OR_UNSTABLE=3, POTENTIALLY_INFORMATIVE=1 |
| 20 | 0.067% | NO_CLEAR_RELATIONSHIP=3, CONSISTENT_CANDIDATE_STATE=1 |
| 30 | 0.080% | WEAK_OR_UNSTABLE=4 |

## Relation to Step 2 OR-width findings

Internal OR structure does not provide a simple descriptive explanation for the
Step-2 causal OR-width result. Step 2 mainly showed higher MFE at higher width
percentiles. Here, the only consistent result is 20m high-efficiency
deterioration, while directional CLV and alignment are weak or no-clear and
directional net move is unstable outside the potentially informative 15m
middle-range pattern. This does not rule out overlap, but establishing mediation
or incremental explanation would require combining state families, which is
outside this run and was not performed.

## Output guardrail

The master CSV contains separate 15m/20m/30m results and combined secondary
context. The stability CSV contains full, first-half, and second-half results for
ALL, LONG, and SHORT. The direction CSV contains full-DEVELOPMENT LONG/SHORT
results. All percentages retain the frozen fractional convention. Step 3 is
complete, but the overall Stage 3A experiment remains incomplete.
