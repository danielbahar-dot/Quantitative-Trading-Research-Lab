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
    config_path TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_experiments_strategy
ON experiments (strategy_name, strategy_version);

CREATE INDEX IF NOT EXISTS idx_experiments_timestamp
ON experiments (timestamp_utc);

