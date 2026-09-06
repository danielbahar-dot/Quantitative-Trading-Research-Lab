# MNQ ORB V0.2 — Stage 3A Step 2 causal OR-width characterization

## Scope and chronology

This is a DEVELOPMENT-only characterization of the four frozen causal OR-width
percentiles in the 935-row Step-1B PRINT breakout-event dataset. It uses only
existing normalized post-signal-bar MFE/MAE outcomes. Signal-bar excursion is
excluded from every clean result because its within-bar chronology is unknown.
No strategy performance, threshold search, filter, preferred lookback, or other
state family is evaluated.

Fixed band boundaries are left-inclusive and right-exclusive:
`[0.00, 0.20)`, `[0.20, 0.40)`, `[0.40, 0.60)`, `[0.60, 0.80)`, with
`[0.80, 1.00]` including 1.00. A row is eligible only when its frozen
availability flag is true and its percentile is present in `[0, 1]`; warm-up
rows remain unavailable and are never backfilled.

## Eligibility

| Lookback | Eligible N | Unavailable N |
| --- | --- | --- |
| 5 sessions | 880 | 55 |
| 10 sessions | 837 | 98 |
| 15 sessions | 779 | 156 |
| 20 sessions | 731 | 204 |

## DEVELOPMENT stability split

The input contains 247 event-bearing session dates.
Dates are sorted chronologically and kept intact: the first
123 dates (2024-06-21 through
2024-12-20) form `DEV_FIRST_HALF`; the final
124 dates (2024-12-23 through
2025-06-30) form `DEV_SECOND_HALF`. This replaces the planning
assumption of 248 frozen calendar sessions with the 247 dates actually present
in the authorized breakout-event input.

## Descriptive relationship assessment

The assessment spans all five clean horizons. Within each horizon, extreme
deterioration requires the widest band to have lower median MFE and higher
median MAE than the median of bands 1–4; a monotonic label requires absolute
Spearman ordering of at least 0.70; middle preference requires the largest
median MFE in bands 2–4 and above both extremes. A segment-level pattern must
recur in at least three of five horizons. A state is called consistent only
when the same qualifying pattern appears in full DEV and both halves and every
30m half-band has at least 10 events. These labels are not trading filters.

| Lookback | OR min | Full DEV | First half | Second half | Assessment |
| --- | --- | --- | --- | --- | --- |
| 5 | 15 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MIDDLE_RANGE_PREFERENCE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | POTENTIALLY_INFORMATIVE |
| 5 | 20 | MIDDLE_RANGE_PREFERENCE | MIDDLE_RANGE_PREFERENCE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | WEAK_OR_UNSTABLE |
| 5 | 30 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MIDDLE_RANGE_PREFERENCE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | WEAK_OR_UNSTABLE |
| 10 | 15 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | CONSISTENT_CANDIDATE_STATE |
| 10 | 20 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | NO_CLEAR_PATTERN | MIDDLE_RANGE_PREFERENCE | WEAK_OR_UNSTABLE |
| 10 | 30 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | CONSISTENT_CANDIDATE_STATE |
| 15 | 15 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | CONSISTENT_CANDIDATE_STATE |
| 15 | 20 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | CONSISTENT_CANDIDATE_STATE |
| 15 | 30 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MIDDLE_RANGE_PREFERENCE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | WEAK_OR_UNSTABLE |
| 20 | 15 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MIDDLE_RANGE_PREFERENCE | WEAK_OR_UNSTABLE |
| 20 | 20 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | MONOTONIC_HIGHER_WIDTH_MORE_MFE | CONSISTENT_CANDIDATE_STATE |
| 20 | 30 | MONOTONIC_HIGHER_WIDTH_MORE_MFE | NO_CLEAR_PATTERN | MONOTONIC_HIGHER_WIDTH_MORE_MFE | POTENTIALLY_INFORMATIVE |

Stable across both DEV halves: 10-session / 15m, 10-session / 30m, 15-session / 15m, 15-session / 20m, 20-session / 20m

## LONG / SHORT context

The table below reports, without selecting a winner, the largest clean 30m
median-MFE band span observed across the four fixed lookbacks for each duration
and side. Full horizon-by-band statistics are in the direction-breakdown CSV.

| OR min | Side | Largest 30m median-MFE band span | Lookback at that span |
| --- | --- | --- | --- |
| 15 | LONG | 0.201% | 5 |
| 15 | SHORT | 0.233% | 20 |
| 20 | LONG | 0.133% | 15 |
| 20 | SHORT | 0.223% | 20 |
| 30 | LONG | 0.174% | 10 |
| 30 | SHORT | 0.203% | 5 |

## OR-duration context

| OR min | Median MFE span across lookbacks | Assessments |
| --- | --- | --- |
| 15 | 0.163% | CONSISTENT_CANDIDATE_STATE=2, POTENTIALLY_INFORMATIVE=1, WEAK_OR_UNSTABLE=1 |
| 20 | 0.132% | WEAK_OR_UNSTABLE=2, CONSISTENT_CANDIDATE_STATE=2 |
| 30 | 0.129% | WEAK_OR_UNSTABLE=2, CONSISTENT_CANDIDATE_STATE=1, POTENTIALLY_INFORMATIVE=1 |

## Relation to noncausal Gate 6B.1

Gate 6B.1 used same-sample actual-width ranked quintiles and strategy R metrics,
not lagged causal percentiles and raw post-breakout excursion. It showed a
middle-quintile preference for 15m, mixed 20m behavior, and strongest
widest-quintile strategy metrics for 30m. Step 2 mostly contradicts the earlier
15m middle preference: the stable 10- and 15-session 15m views show higher MFE
with higher causal width percentile. The 20m result partly resembles the earlier
mixed picture because the shorter lookbacks are unstable, although the 15- and
20-session views are consistent. The 30m result partially resembles the earlier
widest-width strength at the 10-session lookback, but the other lookbacks are
mixed or less stable. This is a causal robustness comparison, not a direct
replication, and higher MFE must not be read as strategy expectancy.

## Artifacts and guardrail

The master CSV contains 15m/20m/30m results plus combined secondary context.
The stability CSV contains full/first-half/second-half results for ALL, LONG,
and SHORT. The direction CSV contains full-DEVELOPMENT LONG/SHORT results plus
combined secondary context. All outcome values retain the frozen fractional
percentage convention. No overall Stage 3A completion is claimed.
