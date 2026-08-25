# Automatic Experiment Registration

Research Infrastructure V1.0 uses one prospective registration workflow for
future strategy families and instruments. It records research metadata; it
does not decide partition permission or access a dataset.

## Runner pattern

```python
from pathlib import Path

from src.experiments import create_experiment


with create_experiment(
    experiment_id="example_strategy_v02_gate5_dev_baseline",
    project_id="example_strategy_v02",
    strategy_id="example_strategy",
    strategy_version="V0.2",
    research_stage="STAGE_5_BASELINE",
    gate="5",
    title="Example DEVELOPMENT baseline",
    experiment_type="DEVELOPMENT_BASELINE",
    hypothesis="The frozen baseline has positive DEVELOPMENT expectancy.",
    description="Descriptive baseline; no parameter selection.",
    partition="DEVELOPMENT",
    confirmatory=False,
    reserved_data_exposed=False,
    parent_experiment_ids=["example_strategy_v02_execution_validation"],
    source_gates=["4"],
    configuration_path="config/experiments/example_v02_baseline.json",
    dataset_id="example_dataset_v1",
) as experiment:
    # The research runner writes each output to its canonical project path.
    summary_path = Path("experiments/projects/example_strategy_v02/baselines/summary.csv")
    run_research_and_write_summary(summary_path)

    experiment.register_artifact(
        artifact_id="development_summary",
        artifact_type="summary",
        title="DEVELOPMENT baseline summary",
        path=summary_path,
        category="data",
    )
    experiment.update(summary_metrics={"trades": 250, "average_r": 0.12})
```

Successful context exit validates required artifacts, records completion, and
refreshes the existing project `experiment_index.json`. The dashboard notices
the index modification and displays the run. A runner can instead call
`finalize_experiment()` explicitly.

## Mutable and immutable fields

After creation, only run-state fields are mutable: status (before completion),
notes, summary metrics, decision, runtime metadata, limitations, warnings, and
future-hypothesis notes. Experiment/project/strategy identity, lifecycle stage,
partition exposure, lineage, configuration reference, dataset provenance, Git
SHA, and start time are immutable. A correction to those fields requires a new
experiment ID rather than silent history rewriting.

Artifacts are registered by repository-relative canonical path and are never
copied for the dashboard. Artifact types are extensible. Registering the same
artifact ID and path is idempotent; rebinding an existing artifact ID to a
different path fails. Artifacts are required by default, while an explicitly
optional artifact may remain unavailable without imposing one artifact set on
every experiment type.

## Failure behavior

If an `ExperimentRun` context raises an exception, the record becomes
`failed`, retains its identity, start time, provenance, and already registered
artifacts, and stores the exception type and message. The exception is then
re-raised. Failed records remain in the same index and are visible in the
read-only dashboard.

## Index and project requirements

- A project manifest must exist before registration.
- Prospective source records live under
  `experiments/projects/<project_id>/records/`.
- `experiment_index.json` remains the single dashboard index.
- Index refresh is deterministic, idempotent, and rejects duplicate IDs,
  invalid records, and unknown lineage parents.
- Existing historical V1.0 index records remain intact and compatible.
- Registration records partition and reserved-data exposure but never loads
  data or grants permission to use it.
