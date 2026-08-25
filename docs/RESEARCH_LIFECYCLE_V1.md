# Research Lifecycle V1.0

Research Lifecycle V1.0 is the platform-wide evidence process. It is independent of strategy family, signal type, instrument, universe, timeframe, and asset class. Project gates remain useful local identifiers, but every experiment also maps to one canonical lifecycle stage.

| Stage | Canonical ID | Purpose |
|---:|---|---|
| 0 | `STAGE_0_IDEA` | Declare the hypothesis, mechanism, scope, data needs, biases, and falsification criteria. |
| 1 | `STAGE_1_DATA` | Qualify provenance, mappings, timestamps, sessions, adjustments, quality, and partitions. |
| 2 | `STAGE_2_FEATURES` | Validate causal feature definitions, timing, invariants, and representative observations. |
| 3 | `STAGE_3_SIGNALS` | Validate the exact market event before performance testing. |
| 4 | `STAGE_4_EXECUTION` | Validate entries, risk, exits, limits, rounding, costs, and ambiguity separately from signals. |
| 5 | `STAGE_5_BASELINE` | Establish the simplest meaningful DEVELOPMENT baseline. |
| 6 | `STAGE_6_EXPLORATION` | Map DEVELOPMENT response surfaces and interactions without selecting a maximum cell. |
| 7 | `STAGE_7_ROBUSTNESS` | Test sensitivity, perturbations, chronology, temporal stability, and observability. |
| 8 | `STAGE_8_FREEZE` | Reduce and freeze candidates, code, configuration, data boundary, and protocol. |
| 9 | `STAGE_9_VALIDATION` | Evaluate frozen candidates on VALIDATION without tuning. |
| 10 | `STAGE_10_DIAGNOSIS` | Diagnose Validation retrospectively without rewriting its result. |
| 11 | `STAGE_11_DECISION` | Record rejection, revision/new version, or approval for the next controlled phase. |

The machine-readable definition and evidence expectations are in `experiments/schema/research_lifecycle_v1.json`.

## Evidence boundaries

- Signal validation precedes performance research.
- Feature, signal, strategy eligibility, and execution semantics are separate contracts.
- DEVELOPMENT is the only partition used for exploration and tuning.
- Candidates and acceptance criteria are frozen before VALIDATION is opened.
- VALIDATION is confirmatory. A revision starts a new strategy version and research cycle.
- Post-validation diagnosis is explicitly retrospective and cannot change the original Validation decision.
- Reserved/OOS metadata may be visible without exposing performance. If reserved data influences research, its evidence status must be relabeled.

## Research package and hierarchy

```text
Research Platform
  Project
    Strategy
      Strategy Version
        Experiment
          Run / configuration
            Artifacts
```

Reusable features, signals, and state variables live outside any single experiment. Strategies reference those components and add eligibility, execution, and risk rules. The filesystem and structured metadata remain the source of truth; a database is not required for the reviewed research catalog.

## Future strategy lifecycle — reserved, not implemented

Research approval authorizes movement to a later controlled phase; it does not authorize deployment and is not a terminal state. A future strategy lifecycle is reserved for implementation verification, simulation/paper trading, deployment approval, live deployment, monitoring, periodic review, revalidation, version migration, suspension, and retirement. Detailed monitoring thresholds and broker/live infrastructure are intentionally outside V1.0.
