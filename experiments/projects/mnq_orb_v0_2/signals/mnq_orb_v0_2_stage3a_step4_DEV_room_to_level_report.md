# MNQ ORB V0.2 Stage 3A Step 4 room to next key level

## Scope

This DEVELOPMENT-only analysis uses 935 Step-1B PRINT breakout
events and only the frozen room-to-next-level fields. Existing normalized
post-signal-bar MFE/MAE at 5m, 15m, 30m, 60m, and session end are the outcomes.
Signal-bar excursion is excluded because its chronology is unknown. No OR-width,
internal-structure, key-level-interaction, pre-open, gap, combined-state,
strategy-performance, filter, optimization, or ML analysis is included.

## State definitions

`room_to_next_level_pct` and `room_to_next_level_or_widths` are the two primary
continuous representations. `room_to_next_level_points` is secondary context;
no preferred representation is selected. Each continuous measure uses ordinary
full-DEVELOPMENT value quintiles calculated separately for each OR duration.
Combined results use their own boundaries and are secondary. Boundaries are
left-inclusive and right-exclusive, except the final interval includes its
upper bound. The full-DEVELOPMENT edges recorded in the CSVs are reused for all
DEV-half and LONG/SHORT comparisons.

The 164 `NO_LEVEL_AHEAD` events remain a separate state
and are never put into a high-distance quintile. The other
771 events form the distance quintiles.

The input has 247 event-bearing dates. The first
123 (2024-06-21 through
2024-12-20) form `DEV_FIRST_HALF`; the final
124 (2024-12-23 through
2025-06-30) form `DEV_SECOND_HALF`.

## Relationship assessment

Patterns must recur in at least three of five clean horizons. Continuous
monotonic patterns require absolute Spearman ordering of at least 0.70. A
relationship also needs a 30m median-MFE contrast of at least one quarter of the
median within-state IQR. `CONSISTENT_CANDIDATE_STATE` additionally requires the
same pattern in full DEV and both halves with at least 10 events in every
inferential half-state. These fixed rules are descriptive guardrails, not
trading thresholds or filters.

| Representation | OR min | Full DEV | First half | Second half | Assessment |
| --- | --- | --- | --- | --- | --- |
| Room / OR-mid price | 15 | MONOTONIC_MORE_ROOM_MORE_MFE | NO_CLEAR_PATTERN | MIDDLE_RANGE_PREFERENCE | WEAK_OR_UNSTABLE |
| Room / OR-mid price | 20 | MONOTONIC_MORE_ROOM_MORE_MFE | MIDDLE_RANGE_PREFERENCE | MONOTONIC_MORE_ROOM_MORE_MFE | WEAK_OR_UNSTABLE |
| Room / OR-mid price | 30 | MONOTONIC_MORE_ROOM_MORE_MFE | MIDDLE_RANGE_PREFERENCE | MONOTONIC_MORE_ROOM_MORE_MFE | WEAK_OR_UNSTABLE |
| Room / OR width | 15 | HIGH_ROOM_DETERIORATION | NO_CLEAR_PATTERN | HIGH_ROOM_DETERIORATION | NO_CLEAR_RELATIONSHIP |
| Room / OR width | 20 | MIDDLE_RANGE_PREFERENCE | MIDDLE_RANGE_PREFERENCE | MIDDLE_RANGE_PREFERENCE | NO_CLEAR_RELATIONSHIP |
| Room / OR width | 30 | NO_CLEAR_PATTERN | NO_CLEAR_PATTERN | HIGH_ROOM_DETERIORATION | NO_CLEAR_RELATIONSHIP |
| Known level ahead | 15 | KNOWN_LEVEL_AHEAD_MORE_MFE | KNOWN_LEVEL_AHEAD_MORE_MFE | KNOWN_LEVEL_AHEAD_MORE_MFE | NO_CLEAR_RELATIONSHIP |
| Known level ahead | 20 | KNOWN_LEVEL_AHEAD_MORE_MFE | KNOWN_LEVEL_AHEAD_MORE_MFE | KNOWN_LEVEL_AHEAD_MORE_MFE | NO_CLEAR_RELATIONSHIP |
| Known level ahead | 30 | KNOWN_LEVEL_AHEAD_MORE_MFE | KNOWN_LEVEL_AHEAD_MORE_MFE | NO_LEVEL_AHEAD_MORE_MFE | WEAK_OR_UNSTABLE |

Consistent across DEV halves: none.

Weak or no-clear: Room / OR-mid price / 15m, Room / OR-mid price / 20m, Room / OR-mid price / 30m, Room / OR width / 15m, Room / OR width / 20m, Room / OR width / 30m, Known level ahead / 15m, Known level ahead / 20m, Known level ahead / 30m.

No primary representation reaches `POTENTIALLY_INFORMATIVE` or
`CONSISTENT_CANDIDATE_STATE`. Price-normalized room has the largest full-DEV
contrast: more room generally corresponds to more MFE for 15m and 20m ORs, but
the 30m endpoint is nearly flat and the first half is middle-shaped or unclear.
OR-width-normalized room does not confirm that relationship: its Q5 median MFE
is below Q1 for every OR duration, with middle-range or high-room-deterioration
patterns depending on duration and half.

## Distance, MFE, MAE, and total excursion

The table compares the outer quintiles at the clean 30m horizon. Positive MAE
deltas mean more adverse excursion, not improvement. “Total excursion” is the
sum of the median favorable and adverse magnitudes and is descriptive only.

| Representation | OR min | Q5-Q1 median MFE | Q5-Q1 median MAE | Q5-Q1 total excursion |
| --- | --- | --- | --- | --- |
| Room / OR-mid price | 15 | 0.102% | 0.080% | 0.182% |
| Room / OR-mid price | 20 | 0.061% | 0.048% | 0.109% |
| Room / OR-mid price | 30 | -0.010% | 0.056% | 0.046% |
| Room / OR width | 15 | -0.022% | 0.059% | 0.037% |
| Room / OR width | 20 | -0.040% | 0.022% | -0.018% |
| Room / OR width | 30 | -0.045% | 0.010% | -0.034% |

This shows whether any wider-room pattern is primarily a favorable-excursion
shift, an adverse-excursion reduction, or a larger overall excursion. The full
quintile paths for all five horizons are retained in the master CSV; nonlinear
and half-unstable patterns are not promoted to filters.

At 15m and 20m, the price-normalized Q5/Q1 difference is mainly a larger total
excursion: both MFE and MAE rise, so greater room does not reduce adverse
excursion. At 30m, MFE is effectively unchanged while MAE rises. In OR-width
units, Q5 has lower MFE and higher MAE at all three durations. These conflicting
normalizations are a principal reason not to select a preferred representation.

## No known level ahead

`NO_LEVEL_AHEAD` is compared directly with `KNOWN_LEVEL_AHEAD`, independently
of the distance quintiles.

| OR min | State | N | Median MFE | Median MAE |
| --- | --- | --- | --- | --- |
| 15 | KNOWN_LEVEL_AHEAD | 285 | 0.248% | 0.201% |
| 15 | NO_LEVEL_AHEAD | 48 | 0.207% | 0.228% |
| 20 | KNOWN_LEVEL_AHEAD | 261 | 0.229% | 0.199% |
| 20 | NO_LEVEL_AHEAD | 56 | 0.215% | 0.167% |
| 30 | KNOWN_LEVEL_AHEAD | 225 | 0.223% | 0.184% |
| 30 | NO_LEVEL_AHEAD | 60 | 0.163% | 0.150% |

Full DEV shows lower 30m median MFE for `NO_LEVEL_AHEAD` at every OR duration.
Its MAE is higher at 15m but lower at 20m and 30m. The contrasts are small
relative to within-state dispersion, and the 30m OR MFE ordering reverses in the
second DEV half, so the categorical difference is weak rather than stable.

## LONG/SHORT and OR-duration context

The largest 30m median-MFE state spans by side identify where differences are
most visible; they do not rank rules.

| Representation | Side | Largest 30m median-MFE state span | OR duration |
| --- | --- | --- | --- |
| Room / OR-mid price | LONG | 0.087% | 15 |
| Room / OR-mid price | SHORT | 0.169% | 30 |
| Room / OR width | LONG | 0.095% | 20 |
| Room / OR width | SHORT | 0.120% | 20 |
| Known level ahead | LONG | 0.077% | 30 |
| Known level ahead | SHORT | 0.110% | 30 |

## Equal-price ties and next-level type

Exactly 71 events have multiple reference labels at
the same exact nearest price. The frozen Step-1A type remains unchanged and the
analysis-only `next_level_type_tied` flag does not alter distance values or
selection semantics. Distance analyses include these rows. Type results include
both all frozen labels and an untied-only sensitivity view. The largest absolute
30m median-MFE change after removing tied rows is 0.204% (20m overnight_low); therefore type
labels remain descriptive and are not used for superiority claims.

| Frozen type | N | LONG N | SHORT N | Tied N | Median MFE | Median MAE |
| --- | --- | --- | --- | --- | --- | --- |
| NO_LEVEL_AHEAD | 164 | 100 | 64 | 0 | 0.188% | 0.184% |
| previous_day_high | 105 | 93 | 12 | 0 | 0.220% | 0.201% |
| london_low | 97 | 34 | 63 | 0 | 0.200% | 0.199% |
| london_high | 90 | 57 | 33 | 0 | 0.197% | 0.226% |
| previous_day_low | 85 | 16 | 69 | 0 | 0.299% | 0.174% |
| ny_premarket_low | 81 | 6 | 75 | 0 | 0.167% | 0.184% |
| ny_premarket_high | 71 | 57 | 14 | 0 | 0.276% | 0.193% |
| asia_low | 68 | 27 | 41 | 0 | 0.276% | 0.190% |
| asia_high | 62 | 30 | 32 | 0 | 0.253% | 0.259% |
| overnight_low | 60 | 0 | 60 | 35 | 0.355% | 0.164% |
| overnight_high | 52 | 52 | 0 | 36 | 0.233% | 0.131% |

The displayed type table is combined secondary context. The complete type CSV
also separates 15m, 20m, and 30m ORs and records tied counts, LONG/SHORT counts,
eligible shares, and clean outcome distributions. Any type pattern is only a
candidate for a later predeclared hypothesis.

The type table has visible outcome dispersion, but it is also strongly
side-imbalanced, and the two overnight labels contain all 71 ties. Their
untied-only samples shrink materially and can move the median MFE substantially.
That makes a label-specific hypothesis premature; a later investigation would
need a predeclared treatment of ties and direction, neither of which is added
here.

## Output guardrail

The master CSV contains separate 15m/20m/30m results and combined secondary
context. The stability CSV contains full, first-half, and second-half results
for ALL, LONG, and SHORT. The direction CSV contains full-DEVELOPMENT LONG/SHORT
results. Percentages retain the frozen fractional convention. Step 4 is
complete; overall Stage 3A remains incomplete and reserved partitions remain
unexposed.
