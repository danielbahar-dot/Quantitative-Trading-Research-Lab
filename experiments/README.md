# Experiments

This directory stores experiment infrastructure and reviewed artifacts.

- `projects/<project_id>/`: compact, reviewed, version-controlled outputs.
- `runs/<run_id>/`: local config snapshots and large artifacts.
- `schema/`: versioned SQLite ledger schema.
- `templates/`: reusable run-config templates.
- `experiment_ledger.sqlite`: local operational ledger (ignored by Git).
- `ledger.csv`: generated readable mirror (ignored by Git).

Create a new run instead of overwriting a completed run. Record strategy,
instrument/universe, dataset ID/hash, partition, parameters, execution/cost
model, code/environment version, artifacts, status, and conclusion. See the
root README for the canonical experiment object and artifact rules.

## Automatic registration for new experiments

Future runners should use `src.experiments.create_experiment` (or
`ExperimentRun`) rather than editing `experiment_index.json` directly. The API
creates a canonical per-experiment record under
`projects/<project_id>/records/`, registers canonical artifact paths, protects
identity/provenance fields, records failure state, and deterministically
upserts the existing project index. Historical records already mapped directly
in an index remain supported.

The dashboard only reads the resulting index. It never runs or mutates an
experiment. See `docs/AUTOMATIC_EXPERIMENT_REGISTRATION.md` for the prospective
runner pattern.
