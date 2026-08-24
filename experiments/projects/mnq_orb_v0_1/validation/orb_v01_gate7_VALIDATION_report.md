# Gate 7 — MNQ ORB V0.1 confirmatory Validation

Validation: 2025-07-01 through 2025-12-31.
Frozen source: `1e34a38d2b0ee1e0b852bcbdb2632ad6bee0fe5f` / `mnq-orb-v0.1-dev-freeze`.

Validation evaluated exactly three frozen hypotheses; it did not optimize or select a winner.

## MNQ_ORB_V01_CAND_001 — 15m_PRINT_FIXED_50_TARGET75PT

- DEVELOPMENT: 241 trades, Avg R 0.182, PF 1.35, max DD 9.50R.
- VALIDATION: 122 trades, Avg R 0.039, PF 1.07, max DD 13.25R.
- Change: Avg R -0.142 (-78.3%), PF -0.28, ambiguity -3.0%.
- Chronology: ENTRY_FIRST Avg R 0.011, PF 1.02; range 0.029R.
- Temporal: UNSTABLE; 66.7% positive months; first half 12.38R, second half -7.57R.
- Assessment: edge **MIXED**; degradation **HIGH**; observability **STRONG**; overall **REVISE**.

## MNQ_ORB_V01_CAND_002 — 20m_PRINT_OR_MIDPOINT_TARGET75PT

- DEVELOPMENT: 246 trades, Avg R 0.233, PF 1.47, max DD 8.85R.
- VALIDATION: 119 trades, Avg R -0.025, PF 0.96, max DD 16.24R.
- Change: Avg R -0.257 (-110.7%), PF -0.51, ambiguity -2.1%.
- Chronology: ENTRY_FIRST Avg R -0.049, PF 0.92; range 0.058R.
- Temporal: UNSTABLE; 50.0% positive months; first half 8.92R, second half -11.88R.
- Assessment: edge **FAILED**; degradation **SIGN_REVERSAL**; observability **FAILED**; overall **REJECT**.

## MNQ_ORB_V01_CAND_003 — 30m_PRINT_FIXED_40_TARGET75PT

- DEVELOPMENT: 219 trades, Avg R 0.273, PF 1.50, max DD 12.38R.
- VALIDATION: 117 trades, Avg R -0.094, PF 0.86, max DD 13.84R.
- Change: Avg R -0.367 (-134.4%), PF -0.64, ambiguity -9.0%.
- Chronology: ENTRY_FIRST Avg R -0.117, PF 0.83; range 0.024R.
- Temporal: UNSTABLE; 33.3% positive months; first half -4.42R, second half -6.59R.
- Assessment: edge **FAILED**; degradation **SIGN_REVERSAL**; observability **FAILED**; overall **REJECT**.

## Research discipline

No target, stop, OR duration, ambiguity rule, cutoff, feature, filter, portfolio weight, or nearby parameter was changed or tested.
HYP_001/HYP_002 and OOS_BURNED were not accessed. Any future idea requires a new DEVELOPMENT version and human approval.
