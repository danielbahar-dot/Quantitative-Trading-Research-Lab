# MNQ ORB V0.2 Stage 3A Step 1B audit

DEVELOPMENT-only dataset preparation audit. No outcome characterization,
state bucketing, strategy performance, filters, or optimization were run.

## Counts

- Input Step-1A rows: 935
- Output Step-1B rows: 935
- ALIGNED: 598
- OPPOSED: 334
- FLAT: 3
- Missing alignment: 0
- Step-1A equal-price nearest-level ties: 71

The tie count is the number of event rows with two or more eligible candidate
levels at the exact nearest price. Step-1A selection order and values are
unchanged.

## Directional-state ranges

| field | min | median | max |
| --- | ---: | ---: | ---: |
| directional_clv | 0 | 0.7027027027 | 1 |
| directional_or_net_move_points | -186 | 20.75 | 358.75 |
| directional_or_net_move_pct | -0.01023452268 | 0.001013159692 | 0.02045427694 |

`directional_or_net_move_pct` carries forward the frozen Stage-2 OR-open
normalization: LONG uses `or_net_move_pct`, while SHORT uses its sign inverse.
Existing `or_efficiency` values are carried forward unchanged.

## LONG examples

| session_date | contract | or_minutes | breakout_timestamp | breakout_direction | or_direction | or_open | or_close | or_breakout_alignment | directional_or_net_move_points | directional_or_net_move_pct | directional_clv | or_efficiency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-06-21 | MNQ 09-24 | 15 | 2024-06-21 11:20:00-04:00 | LONG | DOWN | 20017 | 19988.75 | OPPOSED | -28.25 | -0.0014113004 | 0.28110599 | 0.52073733 |
| 2024-06-21 | MNQ 09-24 | 20 | 2024-06-21 11:20:00-04:00 | LONG | DOWN | 20017 | 19957.5 | OPPOSED | -59.5 | -0.0029724734 | 0.027681661 | 0.82352941 |
| 2024-06-21 | MNQ 09-24 | 30 | 2024-06-21 11:20:00-04:00 | LONG | DOWN | 20017 | 19952.75 | OPPOSED | -64.25 | -0.0032097717 | 0.34065934 | 0.56483516 |
| 2024-06-24 | MNQ 09-24 | 15 | 2024-06-24 10:02:00-04:00 | LONG | DOWN | 19922 | 19904 | OPPOSED | -18 | -0.00090352374 | 0.21974522 | 0.22929936 |
| 2024-06-24 | MNQ 09-24 | 20 | 2024-06-24 10:02:00-04:00 | LONG | DOWN | 19922 | 19870.25 | OPPOSED | -51.75 | -0.0025976308 | 0.035532995 | 0.52538071 |

## SHORT examples

| session_date | contract | or_minutes | breakout_timestamp | breakout_direction | or_direction | or_open | or_close | or_breakout_alignment | directional_or_net_move_points | directional_or_net_move_pct | directional_clv | or_efficiency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-06-21 | MNQ 09-24 | 15 | 2024-06-21 09:46:00-04:00 | SHORT | DOWN | 20017 | 19988.75 | ALIGNED | 28.25 | 0.0014113004 | 0.71889401 | 0.52073733 |
| 2024-06-21 | MNQ 09-24 | 20 | 2024-06-21 09:51:00-04:00 | SHORT | DOWN | 20017 | 19957.5 | ALIGNED | 59.5 | 0.0029724734 | 0.97231834 | 0.82352941 |
| 2024-06-24 | MNQ 09-24 | 15 | 2024-06-24 09:49:00-04:00 | SHORT | DOWN | 19922 | 19904 | ALIGNED | 18 | 0.00090352374 | 0.78025478 | 0.22929936 |
| 2024-06-24 | MNQ 09-24 | 20 | 2024-06-24 10:44:00-04:00 | SHORT | DOWN | 19922 | 19870.25 | ALIGNED | 51.75 | 0.0025976308 | 0.96446701 | 0.52538071 |
| 2024-06-24 | MNQ 09-24 | 30 | 2024-06-24 10:44:00-04:00 | SHORT | UP | 19922 | 19946.25 | OPPOSED | -24.25 | -0.0012172473 | 0.1928934 | 0.24619289 |
