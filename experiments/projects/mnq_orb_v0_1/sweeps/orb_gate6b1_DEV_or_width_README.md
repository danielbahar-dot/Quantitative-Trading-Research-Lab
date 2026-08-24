# Gate 6B.1 — OR-width relationship analysis

This is a DEVELOPMENT-only, artifact-only diagnostic of Gate 6B. It does not
rerun strategy execution, modify Gate 6B outputs, apply an OR-width filter, or
select a preferred configuration.

## Scope and definitions

- Dates: 2024-06-21 through 2025-06-30 only.
- OR durations: 15, 20, and 30 minutes.
- OR width: `or_high - or_low`.
- Market-state unit: one unique `session_date × or_minutes` observation.
- Performance unit: the actual Gate 6B candidate or executed-trade row within
  one configuration.

The analysis first reconciles every repeated candidate/trade OR width against
the unique market-state observation. This prevents the 25 target/stop
configurations per duration from inflating the reported OR-width distribution.

## Width bins and ties

Quintiles are assigned independently for each OR duration. Unique session
observations are sorted by OR width and then session date, given stable ordinal
ranks, and divided into five approximately equal-count bins. This makes the
assignment deterministic and preserves similar bin sizes. When several sessions
have exactly the same width, that tied width may occur at both sides of an
adjacent-bin boundary.

The same quintiles are used for the expectancy curves. Deciles were not used
because their per-configuration sample sizes would generally fall below the
30-trade diagnostic threshold.

## Sample-size warning

Conditional cells with fewer than 30 executed trades are not removed. They are
marked `LOW_SAMPLE` in the CSV and highlighted in hover information. Results in
those cells are descriptive and should not drive a research decision.

## Interpretation guardrail

For a fixed-point target or stop, its ratio to OR width is mechanically an
inverse transformation of OR width within a configuration. It is therefore not
independent evidence. Cross-configuration pooling would also repeat the same
market sessions, so this analysis reports configuration-level relationships
without treating duplicated rows as independent observations.

## Outputs

The canonical tables are:

- `orb_gate6b1_DEV_or_width_distribution.csv`
- `orb_gate6b1_DEV_or_width_quintiles.csv`
- `orb_gate6b1_DEV_or_width_conditional_performance.csv`
- `orb_gate6b1_DEV_or_width_expectancy_bins.csv`
- `orb_gate6b1_DEV_or_width_correlations.csv`
- `orb_gate6b1_DEV_ratio_analysis.csv`
- `orb_gate6b1_DEV_ambiguity_by_or_width.csv`
- `orb_gate6b1_DEV_metadata.json`

The companion interactive HTML files cover the width distribution, average R,
profit factor, target-hit rate, ambiguity exclusions, expectancy curves, and
the target/stop/reward-risk ratio relationships. Every chart is labeled
`DEVELOPMENT ONLY`.
