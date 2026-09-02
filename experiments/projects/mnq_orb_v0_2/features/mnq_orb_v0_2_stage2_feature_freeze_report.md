# MNQ ORB V0.2 Stage 2 Feature Validation — Final Freeze

## Decision

- Lifecycle state: **FEATURES_VALIDATED_AND_FROZEN**
- Experiment decision: **freeze**
- Human review completion date: **2026-09-02**
- Representative reviews: **14/14 PASS**
- Next authorized stage: **STAGE_3_SIGNALS** (not started by this gate)

This approval freezes the Stage-2 feature definitions and evidence. It does not
approve a V0.2 strategy, signal, execution model, performance claim, or live use.

## Corrected representative-review contract

Every populated representative case stores a machine-stable `trigger_id`, not
only human-readable text. Key-level examples are:

- `PREVIOUS_DAY_LEVEL_TOUCH` -> `previous_day_high`
- `CLEAN_TRADE_THROUGH` -> `previous_day_high`
- `SWEEP` -> `previous_day_high`
- `CLOSE_THROUGH` -> `previous_day_high`
- `ASIA_INTERACTION` -> `asia_low`
- `LONDON_INTERACTION` -> `london_low`
- `NY_PREMARKET_INTERACTION` -> `ny_premarket_low`

`CLEAN_TRADE_THROUGH` is selected only when `TRADE_THROUGH=true`,
`CLOSE_THROUGH=true`, and `REJECT=false` all belong to the same exact
`trigger_id`. Queue enrichment independently resolves that level and fails if
the predicates cannot be reconciled on one reference level.

The liquidity-path case stores the exact comparison key (`london_took_asia`)
and explicit HIGH_ONLY/LOW_ONLY/BOTH/NEITHER evidence. Gap and availability
cases likewise store stable feature identifiers.

## Human review completion

All 14 representative cases passed, including narrow/wide OR, previous-day
touch/trade-through/sweep/close-through, Asia/London/NY pre-market interaction,
liquidity path, Globex gap FILLED/PARTIAL/OPEN, and incomplete source-window
handling.

## Data isolation

- Partition loaded: DEVELOPMENT only.
- Session range: 2024-06-21 through 2025-06-30.
- Validation accessed: no.
- OOS_BURNED accessed: no.
- Strategy performance calculated: no.

## Frozen limitations

- Incomplete source windows remain unavailable rather than being fabricated.
- Liquidity-path comparisons do not reconstruct intrawindow chronology.
- Signal-bar excursion remains unordered OHLC evidence and is not an execution input.
