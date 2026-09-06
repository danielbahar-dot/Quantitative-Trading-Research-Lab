# MNQ ORB V0.2 Stage 3A Step 1A audit

DEVELOPMENT-only construction audit. This artifact does not characterize
performance, create filters, alter the frozen PRINT signal, or register a
Stage-3 experiment.

## Construction

- Join key: `session_date`, `contract`, `or_minutes`
- Input PRINT outcome rows: 935
- Output event rows: 935
- Unmatched joins: 0
- `no_level_ahead` rows: 164
- `room_to_next_level_pct`: point distance divided by frozen `or_mid`, matching
  the Stage-2 key-level distance-percent normalization.
- Equal-price tie order: `previous_day_high` -> `previous_day_low` -> `overnight_high` -> `overnight_low` -> `asia_high` -> `asia_low` -> `london_high` -> `london_low` -> `ny_premarket_high` -> `ny_premarket_low`

## Missing candidate-level counts

Counts are event-row counts for unavailable or non-numeric frozen candidates.

- `previous_day_high`: 105
- `previous_day_low`: 105
- `overnight_high`: 43
- `overnight_low`: 43
- `asia_high`: 19
- `asia_low`: 19
- `london_high`: 8
- `london_low`: 8
- `ny_premarket_high`: 0
- `ny_premarket_low`: 0

## LONG examples

| session_date | contract | or_minutes | breakout_timestamp | breakout_direction | or_high | or_low | next_level_type | next_level_price | room_to_next_level_points | room_to_next_level_pct | room_to_next_level_or_widths | no_level_ahead |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-06-21 | MNQ 09-24 | 15 | 2024-06-21 11:20:00-04:00 | LONG | 20027.75 | 19973.5 | ny_premarket_high | 20043 | 15.25 | 0.00076247617 | 0.28110599 | False |
| 2024-06-21 | MNQ 09-24 | 20 | 2024-06-21 11:20:00-04:00 | LONG | 20027.75 | 19955.5 | ny_premarket_high | 20043 | 15.25 | 0.00076281943 | 0.21107266 | False |
| 2024-06-21 | MNQ 09-24 | 30 | 2024-06-21 11:20:00-04:00 | LONG | 20027.75 | 19914 | ny_premarket_high | 20043 | 15.25 | 0.00076361201 | 0.13406593 | False |
| 2024-06-24 | MNQ 09-24 | 15 | 2024-06-24 10:02:00-04:00 | LONG | 19965.25 | 19886.75 | london_low | 19982 | 16.75 | 0.00084061026 | 0.2133758 | False |
| 2024-06-24 | MNQ 09-24 | 20 | 2024-06-24 10:02:00-04:00 | LONG | 19965.25 | 19866.75 | london_low | 19982 | 16.75 | 0.00084103234 | 0.17005076 | False |

## SHORT examples

| session_date | contract | or_minutes | breakout_timestamp | breakout_direction | or_high | or_low | next_level_type | next_level_price | room_to_next_level_points | room_to_next_level_pct | room_to_next_level_or_widths | no_level_ahead |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-06-21 | MNQ 09-24 | 15 | 2024-06-21 09:46:00-04:00 | SHORT | 20027.75 | 19973.5 | london_low | 19947.5 | 26 | 0.0012999594 | 0.47926267 | False |
| 2024-06-21 | MNQ 09-24 | 20 | 2024-06-21 09:51:00-04:00 | SHORT | 20027.75 | 19955.5 | london_low | 19947.5 | 8 | 0.00040016757 | 0.11072664 | False |
| 2024-06-24 | MNQ 09-24 | 15 | 2024-06-24 09:49:00-04:00 | SHORT | 19965.25 | 19886.75 |  |  |  |  |  | True |
| 2024-06-24 | MNQ 09-24 | 20 | 2024-06-24 10:44:00-04:00 | SHORT | 19965.25 | 19866.75 |  |  |  |  |  | True |
| 2024-06-24 | MNQ 09-24 | 30 | 2024-06-24 10:44:00-04:00 | SHORT | 19965.25 | 19866.75 |  |  |  |  |  | True |
