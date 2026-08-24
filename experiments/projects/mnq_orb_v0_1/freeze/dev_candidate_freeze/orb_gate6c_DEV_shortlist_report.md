# Gate 6C — DEVELOPMENT candidate shortlist

**Freeze status: PENDING_HUMAN_APPROVAL**

This report proposes a small, diverse candidate set from the frozen 75-cell Gate 6B universe.
It does not authorize Validation access and does not identify a ‘best’ configuration.

DEVELOPMENT evidence: 2024-06-21 through 2025-06-30.

## Transparent reduction rules

Hard-flag definitions and thresholds are recorded in the experiment config and freeze metadata.
Neighbor support requires chronology robustness, PF above 1 in all scenarios, and an adjacent
target or economically meaningful stop peer within 0.15R of ENTRY_FIRST average R. STRONG
requires support on both dimensions; MODERATE requires either; otherwise support is WEAK.
No composite optimization score is used.

## Core shortlist

### MNQ_ORB_V01_CAND_001 — 15m_PRINT_FIXED_50_TARGET75PT

- Role: Representative candidate; lower-ambiguity 15m fixed-stop representative.
- DEVELOPMENT: 241 trades, Avg R 0.182, PF 1.35, max DD 9.50R.
- Observability: entry-stop ambiguity 5.4%; ENTRY_FIRST Avg R 0.143; chronology range 0.039R.
- Stability: neighbor support STRONG; all-scenario PF > 1 = True.
- Cautions: OR-width dependence: HUMP_SHAPED.
- Validation must confirm: Does the 15m fixed-50/75-point hypothesis retain positive expectancy without the DEVELOPMENT widest-OR weakness becoming dominant?

### MNQ_ORB_V01_CAND_002 — 20m_PRINT_OR_MIDPOINT_TARGET75PT

- Role: Representative candidate; structurally adaptive midpoint representative.
- DEVELOPMENT: 246 trades, Avg R 0.233, PF 1.47, max DD 8.85R.
- Observability: entry-stop ambiguity 4.7%; ENTRY_FIRST Avg R 0.192; chronology range 0.041R.
- Stability: neighbor support STRONG; all-scenario PF > 1 = True.
- Cautions: OR-width behavior: RELATIVELY_STABLE.
- Validation must confirm: Does the 20m midpoint/75-point hypothesis preserve its low-ambiguity, low-chronology-sensitivity profile?

### MNQ_ORB_V01_CAND_003 — 30m_PRINT_FIXED_40_TARGET75PT

- Role: Representative candidate; distinct 30m moderate fixed-stop representative.
- DEVELOPMENT: 219 trades, Avg R 0.273, PF 1.50, max DD 12.38R.
- Observability: entry-stop ambiguity 12.3%; ENTRY_FIRST Avg R 0.126; chronology range 0.147R.
- Stability: neighbor support STRONG; all-scenario PF > 1 = True.
- Cautions: OR-width dependence: U_SHAPED_CONCENTRATED.
- Validation must confirm: Does the 30m fixed-40/75-point hypothesis persist despite its U-shaped DEVELOPMENT OR-width behavior?

## Research hypotheses

### MNQ_ORB_V01_HYP_001 — 20m_PRINT_OR_25_RETRACEMENT_TARGET75PT

- Role: Higher-risk research candidate; ambiguity-sensitive 25%-stop robust exception.
- DEVELOPMENT: 202 trades, Avg R 0.297, PF 1.46, max DD 10.40R.
- Observability: entry-stop ambiguity 26.5%; ENTRY_FIRST Avg R 0.009; chronology range 0.288R.
- Stability: neighbor support MODERATE; all-scenario PF > 1 = True.
- Cautions: high entry-bar ambiguity; high chronology sensitivity; OR-width dependence: HUMP_SHAPED.
- Validation must confirm: Is the marginal ENTRY_FIRST edge and Q2 concentration reproducible outside DEVELOPMENT?

### MNQ_ORB_V01_HYP_002 — 20m_PRINT_OR_25_RETRACEMENT_TARGET100PT

- Role: Higher-risk research candidate; higher-target 25%-stop robust exception.
- DEVELOPMENT: 202 trades, Avg R 0.454, PF 1.67, max DD 13.00R.
- Observability: entry-stop ambiguity 26.8%; ENTRY_FIRST Avg R 0.118; chronology range 0.336R.
- Stability: neighbor support MODERATE; all-scenario PF > 1 = True.
- Cautions: high entry-bar ambiguity; high chronology sensitivity; OR-width dependence: HUMP_SHAPED_CONCENTRATED; BOUNDARY_TARGET; no interior optimum demonstrated.
- Validation must confirm: Does the boundary-target and narrow-OR weakness persist outside DEVELOPMENT?

## Why other robust cells were not shortlisted

Many cells remain chronology-robust. They are retained in the 75-row evidence table but omitted
to avoid carrying near-duplicate target/stop hypotheses into Validation. The core set intentionally
represents 15m/20m/30m, midpoint/fixed-40/fixed-50 stops, and an interior 75-point target with
supporting target and stop-family neighbors. Fixed-30 remains documented but adds materially more
entry-bar ambiguity. Most 25%-retracement cells fail conservative chronology; its two surviving
20m exceptions remain separate research hypotheses.

## Approval boundary

Human approval must confirm the shortlist and predeclare Validation acceptance criteria before
the package can become FINAL. No Validation or OOS_BURNED data was loaded for this report.
