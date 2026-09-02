# MNQ ORB V0.2 Stage 2 Feature Validation

This artifact is descriptive feature validation only. It contains no strategy
profitability, threshold selection, ranking, or V0.2 trading rule.

## Scope

- Partition: DEVELOPMENT only, 2024-06-21 through 2025-06-30.
- Sessions: 248
- Feature rows: 744 (session x 15/20/30-minute OR)
- PRINT outcome events: 935
- Ambiguous PRINT bars retained in a separate audit: 2
- Validation/OOS loaded: no

## Window definitions

- Asia Kill Zone: 20:00-00:00 ET; **proposed, human approval required**.
- London Kill Zone: 02:00-05:00 ET; **proposed, human approval required**.
- New York pre-market (legacy label NY PM): 07:00-09:00 ET; user specified.
- Globex overnight: 18:00-09:30 ET.
- Combined pre-open: 20:00-09:00 ET; inherits Asia-start approval dependency.

Under NT8 bar-end semantics, each conceptual window uses labels one minute
after its start through its end. NY pre-market therefore uses 07:01-09:00.

## Incomplete source windows by session

{
  "asia": 5,
  "london": 3,
  "ny_premarket": 0,
  "overnight": 12,
  "combined_preopen": 10,
  "previous_rth": 16
}

Incomplete windows remain null/unavailable; no values are fabricated.

## Descriptive redundancy candidates for human review

- 30m: `or_width_hist_40_percentile` vs `or_width_hist_60_percentile` = 0.996
- 30m: `or_width_hist_60_percentile` vs `or_width_hist_40_percentile` = 0.996
- 20m: `or_width_hist_60_percentile` vs `or_width_hist_40_percentile` = 0.980
- 20m: `or_width_hist_40_percentile` vs `or_width_hist_60_percentile` = 0.980
- 15m: `or_width_hist_60_percentile` vs `or_width_hist_40_percentile` = 0.979
- 15m: `or_width_hist_40_percentile` vs `or_width_hist_60_percentile` = 0.979
- 30m: `or_width_hist_20_percentile` vs `or_width_hist_60_percentile` = 0.973
- 30m: `or_width_hist_60_percentile` vs `or_width_hist_20_percentile` = 0.973

These correlations describe feature redundancy only. They are not related to
profitability and are not a feature ranking.

## Outcome separation

All future-looking fields live only in the breakout-outcome table and use the
`outcome_` prefix. The first measured bar is the first complete bar after the
PRINT signal bar, avoiding an unobservable within-bar chronology assumption.
