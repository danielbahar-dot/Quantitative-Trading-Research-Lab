CREATE TABLE IF NOT EXISTS experiments (
    run_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    dataset TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    session TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    costs_slippage_json TEXT NOT NULL,
    results_summary_json TEXT NOT NULL,
    notes TEXT NOT NULL,
    code_version TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    artifact_paths_json TEXT NOT NULL,
    config_path TEXT NOT NULL,
    experiment_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    strategy_family TEXT NOT NULL DEFAULT '',
    asset_class TEXT NOT NULL DEFAULT '',
    instrument_id TEXT NOT NULL DEFAULT '',
    universe_id TEXT NOT NULL DEFAULT '',
    dataset_id TEXT NOT NULL DEFAULT '',
    dataset_hash TEXT NOT NULL DEFAULT '',
    partition_name TEXT NOT NULL DEFAULT '',
    execution_model_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'CREATED',
    conclusion TEXT NOT NULL DEFAULT '',
    dirty_worktree INTEGER NOT NULL DEFAULT 0,
    environment_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_experiments_strategy
ON experiments (strategy_name, strategy_version);

CREATE INDEX IF NOT EXISTS idx_experiments_timestamp
ON experiments (timestamp_utc);

