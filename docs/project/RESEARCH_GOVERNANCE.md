# Research Governance

Research methodology and safeguards. This complements, and does not replace,
`docs/RESEARCH_LIFECYCLE_V1.md` (canonical 12-stage lifecycle) and the
partition methodology in the root [README](../../README.md). Related:
[QUALITY_CONTROL](QUALITY_CONTROL.md) · [DECISION_LOG](DECISION_LOG.md).

## 1. Partition separation (DEVELOPMENT / VALIDATION / OOS)

- Define partitions **before** inspecting results; assign by `session_date`.
- DEVELOPMENT is the only partition for exploration, debugging, and tuning.
- VALIDATION is confirmatory only, opened after candidate + criteria freeze;
  outcomes are `PASS`, `REVISE`, or `REJECT`. It is never a second
  optimization set.
- OOS is a single final frozen evaluation. Any period that influenced design is
  relabeled burned (e.g. `OOS_BURNED`) and is never called untouched evidence.
- Current MNQ state: VALIDATION was exposed during ORB V0.1 Gate 7/8A;
  OOS is `OOS_BURNED`. Partition treatment for ICT research is an **open
  decision** (see [WORK_PROGRESS](WORK_PROGRESS.md)).

## 2. Candidate freeze discipline

Before VALIDATION: freeze candidate configuration, code SHA, data boundary,
acceptance criteria, and protocol. A failed or revised candidate becomes a new
version and research cycle; frozen candidates are never edited.

## 3. Leakage controls

- **Parameter leakage:** no parameter, threshold, or lookback chosen using
  VALIDATION/OOS data or post-hoc best-cell selection. Predeclared alternatives
  (e.g. several lookbacks) may not be narrowed after seeing results.
- **Future leakage:** every derived value has an availability timestamp;
  outcome/forward columns are kept in separate, clearly prefixed tables.

## 4. Exploratory vs confirmatory research

| | Exploratory | Confirmatory |
|---|---|---|
| Partition | DEVELOPMENT | VALIDATION / OOS |
| Hypotheses | May be generated | Must be predeclared |
| Iteration | Allowed, recorded | Not allowed |
| Output label | Descriptive / diagnostic | Decision (`PASS`/`REVISE`/`REJECT`) |

Post-validation diagnosis is retrospective and never rewrites a decision.

## 5. Hypothesis tracking

Each hypothesis has an ID, statement, mechanism, scope, falsification
criteria, status, and evidence links. Existing conventions: experiment records
(`experiments/projects/<project>/records/`), `research_ideas.json`, and IDs such
as `HYP-ORB-STATE-01`. Observations from visual review are logged as
hypothesis candidates, not rules.

## 6. When performance may be examined

- Not before the feature and signal are `FROZEN` (signal validation precedes
  performance testing).
- Only on DEVELOPMENT during exploration.
- Descriptive excursion/outcome statistics during characterization are allowed
  only when labeled descriptive and kept out of definition decisions.

## 7. When a feature can enter a strategy

Only after the feature (and any derived state/signal) has passed the full
[QUALITY_CONTROL](QUALITY_CONTROL.md) process and is `FROZEN`. For ICT: Phase 2
does not begin until the required Phase 1 primitives are frozen (D-103).

## 8. When a strategy may be optimized

After signal and execution validation and a DEVELOPMENT baseline, within a
predeclared parameter space, on DEVELOPMENT only. Prefer stable regions,
temporal robustness, chronology/observability robustness, and economic
rationale over maxima. Optimization capacity is limited by sample size.

## 9. Parking and rejecting research

- **REJECT:** confirmatory evidence contradicts the hypothesis, or expectancy
  reverses under reasonable chronology/observability scenarios.
- **REVISE / NEW VERSION:** partial evidence; requires a new version and cycle.
- **PARK:** potentially informative but not sufficiently stable to justify a
  new version; evidence preserved, no active work, reopening needs explicit
  authorization (e.g. ORB V0.2, D-101).

## 10. Provenance and reproducibility

Every material run records dataset ID/hash, partition, config path and
parameters, execution/cost model, Git SHA, environment, artifacts, status, and
conclusion, via `src/experiments/experiment_registration.py`. Reruns create a
new `run_id`. Raw data is immutable; derived data must be rebuildable from a
versioned transform.
