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
