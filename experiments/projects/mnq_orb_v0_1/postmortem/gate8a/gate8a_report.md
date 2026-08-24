# Gate 8A — MNQ ORB V0.1 Post-Validation Diagnostic

> POST-VALIDATION DIAGNOSTIC — NOT CONFIRMATORY

This is a retrospective failure diagnostic. It does not select a strategy, create a V0.2 candidate, or provide new confirmatory evidence.

## Scope and safeguards

- DEVELOPMENT: 2024-06-21 through 2025-06-30
- VALIDATION: 2025-07-01 through 2025-12-31
- OOS_BURNED: not opened and not used.
- Exact frozen Gate 6B grid: 75 configurations, no new values.
- Historical Gate 6B/6B.1/6B.2/6C/7 hashes were unchanged.

## Surface persistence

- Avg-R Spearman: 0.1325
- PF Spearman: -0.0305
- Median Avg-R delta: -0.2592R
- Sign cells: POSITIVE_DEV_NEGATIVE_VAL=48, POSITIVE_DEV_POSITIVE_VAL=27
- Strong DEVELOPMENT-neighborhood cells still positive in VALIDATION: 21/57
- VALIDATION Avg R range: -0.2056 to 0.5864
- VALIDATION PF range: 0.6622 to 1.8593

## Parameter migration

- Target-region descriptors: {'SHIFTED_TOWARD_SMALLER_TARGETS': 9, 'STABLE_REGION': 6}
- Stop-family descriptors: {'SHIFTED_FIXED_30_TO_FIXED_40': 5, 'STABLE_REGION': 4, 'SHIFTED_FIXED_30_TO_OR_MIDPOINT': 3, 'SHIFTED_FIXED_30_TO_OR_25_RETRACEMENT': 2, 'SHIFTED_FIXED_30_TO_FIXED_50': 1}
- These are retrospective descriptive peaks, not candidate recommendations.

## Frozen-candidate neighborhoods

- MNQ_ORB_V01_CAND_001: LOCAL_FAILURE; candidate VAL Avg R 0.0394, neighborhood mean 0.0326, VAL-positive neighbors 75.0%.
- MNQ_ORB_V01_CAND_002: BROAD_SURFACE_DETERIORATION; candidate VAL Avg R -0.0249, neighborhood mean -0.0140, VAL-positive neighbors 50.0%.
- MNQ_ORB_V01_CAND_003: BROAD_SURFACE_DETERIORATION; candidate VAL Avg R -0.0941, neighborhood mean -0.1192, VAL-positive neighbors 0.0%.

## Time decomposition

- MNQ_ORB_V01_CAND_001: ABRUPT; first-half 12.380R, second-half -7.570R.
- MNQ_ORB_V01_CAND_002: ABRUPT; first-half 8.922R, second-half -11.880R.
- MNQ_ORB_V01_CAND_003: PERSISTENT_WEAKNESS; first-half -4.419R, second-half -6.588R.
- REGION_15M_FIXED50: ABRUPT; first-half 8.335R, second-half -5.933R.
- REGION_20M_MIDPOINT: ABRUPT; first-half 8.373R, second-half -13.768R.
- REGION_30M_FIXED40: PERSISTENT_WEAKNESS; first-half -5.971R, second-half -9.542R.

Rolling 30/50 series are calculated separately inside each partition. No window crosses the boundary.

## OR-width state

- 15m: median width 91.25 -> 87.00 points; p10–p90 51.40–169.90 -> 48.70–161.35.
- 20m: median width 102.00 -> 99.75 points; p10–p90 58.90–185.60 -> 53.18–185.30.
- 30m: median width 119.75 -> 114.25 points; p10–p90 66.75–210.00 -> 64.00–218.75.

Within-period quintiles changed sign in 58.9% of matched surface cells. The relationship was nonlinear: 15m remained positive across relative-width quintiles, while 20m weakness concentrated in quintiles 1–3 and 30m was negative in quintiles 2–5. This is descriptive and does not define an OR-width filter.

## Price-level drift

- 15m: median OR-mid 20467.62 -> 24739.38 (+20.9%); 75 points changed from 0.366% to 0.303% of price.
- 20m: median OR-mid 20461.50 -> 24745.00 (+20.9%); 75 points changed from 0.367% to 0.303% of price.
- 30m: median OR-mid 20479.38 -> 24742.00 (+20.8%); 75 points changed from 0.366% to 0.303% of price.

These percentage equivalents are descriptive only; the strategy was not rerun with percentage distances.

## Observability

- FIXED_30: entry/stop ambiguity 19.08% -> 10.62%; total exclusions 19.89% -> 10.84%.
- FIXED_40: entry/stop ambiguity 9.80% -> 2.88%; total exclusions 10.16% -> 3.10%.
- FIXED_50: entry/stop ambiguity 5.95% -> 1.77%; total exclusions 6.31% -> 1.99%.
- OR_25_RETRACEMENT: entry/stop ambiguity 28.62% -> 20.80%; total exclusions 29.41% -> 21.02%.
- OR_MIDPOINT: entry/stop ambiguity 5.26% -> 2.88%; total exclusions 5.67% -> 3.10%.

Ambiguity and total-exclusion rates fell in every stop family, so reduced OHLC observability cannot explain the broad expectancy loss.

## Post-mortem classifications

- BROAD_EDGE_DETERIORATION: **SUPPORTS** — DEV-positive flip rate=0.640; median Avg-R delta=-0.2592.
- PARAMETER_INSTABILITY_MIGRATION: **SUPPORTS** — Avg-R Spearman=0.132; grouped descriptive-peak shift rate=0.667.
- MARKET_STATE_DEPENDENCE: **SUPPORTS** — Within-period width-cell sign-change rate=0.589; durations with median absolute change >=0.15R=3.
- SELECTION_ERROR_OVERFITTING: **DOES_NOT_SUPPORT** — Frozen candidates satisfying the predeclared selection-error pattern=0/3.

## Parked future hypotheses

OR expansion may be more meaningfully normalized against a separately validated pre-market expansion feature than generic ATR. Gate 8A does not define or calculate that feature. Percentage-normalized distances, OR-width state, and causal OR-width percentiles also remain parked for a future V0.2 definition gate.

## Methodological conclusion

VALIDATION has been observed and is burned for future V0.2 hypothesis generation. It may remain available for retrospective diagnosis only. OOS_BURNED remains unopened in the formal lifecycle and requires explicit human approval.
