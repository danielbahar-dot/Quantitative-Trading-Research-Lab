# MNQ ORB V0.2 Stage 2 Feature Validation Completion

This is DEVELOPMENT-only feature validation. No strategy performance, feature
optimization, entry filter, or V0.2 trading rule was calculated.

## Approved definitions

- Asia KZ: 20:00-00:00 ET.
- London KZ: 02:00-05:00 ET.
- New York pre-market: 07:00-09:00 ET.
- `combined_preopen` migrated to `OVERNIGHT_CONTEXT_2000_0900`, a continuous
  20:00-09:00 contextual range rather than a union of named windows.

All use NT8 bar-end labels: a conceptual start is represented by the first bar
stamped one minute later.

## Previous-day and gap families

Previous-day H/L/C use the complete prior futures trading day owned by
`session_date`: prior-calendar-day 18:01 through trading-date 17:00 bar ends.
Previous RTH H/L/C remain optional reusable features.

`GLOBEX_REOPEN_GAP` remains the prior 17:00 close to 18:01 reopen concept.
`NY_OPEN_GAP` is separate: prior trading day's 16:14 bar close versus the
current 09:31 bar open (the 09:30 market open). The 16:14 reference exists in
238 of 248 source
sessions; missing bars are not substituted.

## Causal OR-width history

- 5 sessions: 699 populated rows
- 10 sessions: 659 populated rows
- 15 sessions: 619 populated rows
- 20 sessions: 579 populated rows

Every populated value uses only the exact prior completed sessions of the same
OR duration. Current-session data never enters its own reference distribution.

## Outcome separation

Signal-bar favorable/adverse excursion is retained as unordered OHLC evidence
and always labelled `signal_bar_chronology_unknown = true`. Clean MFE/MAE fields
use the `post_signal_bar_` prefix and begin with the first complete bar after
the PRINT signal bar. Neither family changes execution logic.

## Overnight missing-data diagnosis

- overnight / CONTRACT_ROLL_DATA_GAP: 4 sessions
- overnight / DATASET_BOUNDARY: 1 sessions
- overnight / MISSING_SOURCE_BARS: 7 sessions
- overnight_context_2000_0900 / CONTRACT_ROLL_DATA_GAP: 4 sessions
- overnight_context_2000_0900 / DATASET_BOUNDARY: 1 sessions
- overnight_context_2000_0900 / MISSING_SOURCE_BARS: 5 sessions

Completeness rules were not weakened. The detailed audit records expected and
observed bars, actual first/last timestamps, and reason for every unavailable
overnight/context observation.

## Human review status

The viewer includes validation presets, prior-session context, selectable end
times through 16:00, independent X/Y navigation, an interactive legend, and a
neutral TOUCH / TRADE_THROUGH / CLOSE_THROUGH / REJECT / SWEEP panel.
14 representative review cases are queued.
Final Stage-2 freeze still requires human visual/data approval.

## Isolation

- Feature audit: 744 session x OR-duration rows and 474 columns.
- Maximum session date: 2025-06-30.
- Validation/OOS loaded: no.
- Strategy performance calculated: no.
