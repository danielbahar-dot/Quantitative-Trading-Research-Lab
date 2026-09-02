"""Run MNQ ORB V0.2 Stage 2 DEVELOPMENT-only feature validation.

This is feature construction and descriptive characterization, not a strategy
backtest, parameter sweep, or profitability study.  The runner is the first
prospective consumer of Research Infrastructure V1.0 registration.
"""

from __future__ import annotations

from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments import create_experiment  # noqa: E402
from src.experiments.mnq_orb_v02_features import (  # noqa: E402
    build_breakout_outcomes,
    build_feature_audit,
    build_feature_contract,
    characterize_features,
    feature_summary,
    load_development_prices,
    read_json,
    write_characterization_charts,
)


CONFIG_PATH = PROJECT_ROOT / "config" / "experiments" / "mnq_orb_v0_2_stage2_feature_validation.json"
WINDOW_CONFIG_PATH = PROJECT_ROOT / "config" / "features" / "mnq_orb_v0_2_preopen_windows.json"
OUTPUT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "features"


def main() -> None:
    config = read_json(CONFIG_PATH)
    window_config = read_json(WINDOW_CONFIG_PATH)
    data_path = PROJECT_ROOT / config["dataset_path"]

    run = create_experiment(
        experiment_id=config["experiment_id"],
        project_id=config["project_id"],
        strategy_id=config["strategy_id"],
        strategy_version=config["strategy_version"],
        research_stage=config["research_stage"],
        gate="V0.2-S2",
        title="Pre-open and opening-auction feature validation",
        experiment_type="FEATURE_VALIDATION",
        hypothesis="Causal pre-open and opening-auction features can be defined, timed, and audited without using future information or strategy performance.",
        description="DEVELOPMENT-only construction, validation, and descriptive characterization of reusable MNQ context features plus a separately labelled PRINT breakout outcome layer.",
        partition="DEVELOPMENT",
        confirmatory=False,
        reserved_data_exposed=False,
        parent_experiment_ids=["mnq_orb_v0_1_research_decision"],
        source_gates=["V0.1 decision", "V0.2 Stage 2"],
        configuration_path=CONFIG_PATH,
        configuration_parameters={
            "or_durations": config["or_durations"],
            "historical_width_lookbacks": config["historical_width_lookbacks"],
            "outcome_horizons_minutes": config["outcome_horizons_minutes"],
            "window_config_path": config["window_config_path"],
        },
        dataset_id=config["dataset_id"],
        dataset_version="qualified_actual_contract_v1",
        data_hash=config["dataset_sha256"],
        instrument_id="MNQ",
        asset_class="futures",
        timeframe="1 minute",
        project_root=PROJECT_ROOT,
    )

    with run:
        prices = load_development_prices(data_path)
        features = build_feature_audit(
            prices, window_config,
            durations=config["or_durations"],
            lookbacks=config["historical_width_lookbacks"],
        )
        outcomes, ambiguous = build_breakout_outcomes(
            prices, features,
            durations=config["or_durations"],
            horizons=config["outcome_horizons_minutes"],
        )
        contract = build_feature_contract(features)
        distributions, correlations = characterize_features(features)
        summary = feature_summary(features, outcomes, ambiguous)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        paths = {
            "feature_audit": OUTPUT_DIR / "mnq_orb_v0_2_DEV_feature_audit.csv",
            "feature_contract": OUTPUT_DIR / "mnq_orb_v0_2_feature_timing_contract.csv",
            "feature_distribution": OUTPUT_DIR / "mnq_orb_v0_2_DEV_feature_distributions.csv",
            "feature_correlation": OUTPUT_DIR / "mnq_orb_v0_2_DEV_feature_correlations.csv",
            "outcomes": OUTPUT_DIR / "mnq_orb_v0_2_DEV_print_breakout_outcomes.csv",
            "ambiguity_audit": OUTPUT_DIR / "mnq_orb_v0_2_DEV_print_ambiguity_audit.csv",
            "distribution_chart": OUTPUT_DIR / "mnq_orb_v0_2_DEV_feature_distributions.html",
            "correlation_chart": OUTPUT_DIR / "mnq_orb_v0_2_DEV_feature_correlations.html",
            "metadata": OUTPUT_DIR / "mnq_orb_v0_2_stage2_feature_metadata.json",
            "report": OUTPUT_DIR / "mnq_orb_v0_2_stage2_feature_report.md",
            "viewer_guide": OUTPUT_DIR / "mnq_orb_v0_2_feature_viewer_guide.md",
        }
        _write_csv(features, paths["feature_audit"])
        _write_csv(contract, paths["feature_contract"])
        _write_csv(distributions, paths["feature_distribution"])
        _write_csv(correlations, paths["feature_correlation"])
        _write_csv(outcomes, paths["outcomes"])
        _write_csv(ambiguous, paths["ambiguity_audit"])
        write_characterization_charts(
            features, correlations,
            distribution_path=paths["distribution_chart"],
            correlation_path=paths["correlation_chart"],
        )
        metadata = _metadata(config, window_config, summary, features, outcomes)
        paths["metadata"].write_text(json.dumps(metadata, indent=2, default=_json_default) + "\n", encoding="utf-8")
        paths["report"].write_text(_report(summary, window_config, features, correlations), encoding="utf-8")
        paths["viewer_guide"].write_text(_viewer_guide(), encoding="utf-8")

        artifact_specs = {
            "feature_audit": ("feature_table", "Canonical DEVELOPMENT feature audit", "data"),
            "feature_contract": ("feature_contract", "Feature timing and causality contract", "metadata"),
            "feature_distribution": ("descriptive_summary", "DEVELOPMENT feature distributions", "data"),
            "feature_correlation": ("descriptive_summary", "DEVELOPMENT feature correlations", "data"),
            "outcomes": ("outcome_table", "PRINT breakout excursion outcomes", "data"),
            "ambiguity_audit": ("audit", "PRINT ambiguity audit", "data"),
            "distribution_chart": ("chart", "DEVELOPMENT feature distributions", "chart"),
            "correlation_chart": ("chart", "DEVELOPMENT feature correlation heatmaps", "chart"),
            "metadata": ("metadata", "Stage 2 feature metadata", "metadata"),
            "report": ("report", "Stage 2 feature validation report", "documentation"),
            "viewer_guide": ("viewer_guide", "Feature-validation viewer guide", "documentation"),
        }
        for artifact_id, (artifact_type, title, category) in artifact_specs.items():
            run.register_artifact(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                title=title,
                path=paths[artifact_id],
                category=category,
                metadata={"partition": "DEVELOPMENT", "performance_metrics": False},
            )
        run.register_artifact(
            artifact_id="window_configuration",
            artifact_type="configuration",
            title="Pre-open window definitions",
            path=WINDOW_CONFIG_PATH,
            category="configuration",
        )
        run.register_artifact(
            artifact_id="component_registry",
            artifact_type="component_definitions",
            title="Reusable research component registry",
            path=PROJECT_ROOT / "config" / "components" / "research_components.json",
            category="metadata",
        )
        run.update(
            summary_metrics=summary,
            decision="continue",
            notes="Feature construction is complete for manual review. No V0.2 signal, filter, strategy rule, or performance conclusion was created.",
            known_limitations=[
                "Asia 20:00-00:00 ET and London 02:00-05:00 ET definitions are proposed and require human approval.",
                "Combined pre-open begins at the proposed Asia-window start and therefore inherits that approval dependency.",
                "PRINT outcomes start with the first full bar after the signal bar because intrabar post-break chronology is unobservable in one-minute OHLC.",
            ],
            warnings=[
                "NY PM is interpreted exclusively as New York pre-market (07:00-09:00 ET).",
                "Outcome columns are future labels and are not causal features.",
                "No Validation or OOS_BURNED file was loaded.",
            ],
        )

    print(json.dumps(summary, indent=2))
    print(f"Registered experiment: {run.experiment_id}")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)


def _metadata(config, window_config, summary, features, outcomes):
    warmups = {}
    for lookback in config["historical_width_lookbacks"]:
        column = f"or_width_hist_{lookback}_available"
        warmups[str(lookback)] = {
            "available_rows": int(features[column].sum()),
            "unavailable_rows": int((~features[column]).sum()),
        }
    outcome_counts = outcomes.groupby("or_minutes").size().astype(int).to_dict()
    return {
        "experiment_id": config["experiment_id"],
        "research_stage": config["research_stage"],
        "partition": "DEVELOPMENT",
        "development_range": [config["development_start"], config["development_end"]],
        "maximum_session_date_analyzed": summary["maximum_session_date"],
        "validation_or_oos_loaded": False,
        "timestamp_semantics": "timestamp_et = bar_end_time",
        "ny_pm_meaning": "New York pre-market",
        "window_configuration": window_config,
        "historical_width": {
            "lookbacks": config["historical_width_lookbacks"],
            "percentile_method": config["historical_percentile_method"],
            "warmup": warmups,
        },
        "gap_definition": {
            "prior_close": "close of prior trading session bar stamped 17:00 ET",
            "reopen": "open of current session first bar stamped 18:01 ET on prior calendar day",
            "filled": "price touched/crossed the prior close at or before the 09:30 bar-end",
            "partial": "price moved from reopen toward prior close without touching it",
            "open": "no fill; includes partial and untouched through 09:30",
        },
        "key_level_definitions": {
            "touch": "OR low <= level <= OR high",
            "trade_through": "strict move beyond the level from the OR-open side",
            "sweep": "strict trade-through followed by OR close on the original side",
            "close_through": "OR close on the opposite side from OR open",
            "reject": "touch or beyond followed by OR close on the original side; sweep is a strict subset",
        },
        "feature_rows": summary["feature_rows"],
        "feature_columns": len(features.columns),
        "outcome_events_by_or_minutes": {str(key): value for key, value in outcome_counts.items()},
        "outcome_columns_are_future_labels": True,
        "strategy_performance_calculated": False,
    }


def _report(summary, window_config, features, correlations) -> str:
    incomplete = {}
    for prefix in ("asia", "london", "ny_premarket", "overnight", "combined_preopen", "previous_rth"):
        column = f"{prefix}_feature_available"
        incomplete[prefix] = int((~features[column]).sum() / features["or_minutes"].nunique())
    non_self = correlations.loc[correlations["feature_x"] != correlations["feature_y"]].dropna(subset=["correlation"]).copy()
    non_self["absolute"] = non_self["correlation"].abs()
    top = non_self.sort_values("absolute", ascending=False).head(8)
    top_lines = "\n".join(
        f"- {row.or_minutes}m: `{row.feature_x}` vs `{row.feature_y}` = {row.correlation:.3f}"
        for row in top.itertuples(index=False)
    ) or "- No populated correlation pairs."
    windows = {item["window_id"]: item for item in window_config["windows"]}
    return f"""# MNQ ORB V0.2 Stage 2 Feature Validation

This artifact is descriptive feature validation only. It contains no strategy
profitability, threshold selection, ranking, or V0.2 trading rule.

## Scope

- Partition: DEVELOPMENT only, {summary['minimum_session_date']} through {summary['maximum_session_date']}.
- Sessions: {summary['sessions']}
- Feature rows: {summary['feature_rows']} (session x 15/20/30-minute OR)
- PRINT outcome events: {summary['outcome_events']}
- Ambiguous PRINT bars retained in a separate audit: {summary['ambiguous_print_bars']}
- Validation/OOS loaded: no

## Window definitions

- Asia Kill Zone: 20:00-00:00 ET; **proposed, human approval required**.
- London Kill Zone: 02:00-05:00 ET; **proposed, human approval required**.
- New York pre-market (legacy label NY PM): 07:00-09:00 ET; user specified.
- Globex overnight: 18:00-09:30 ET.
- Combined pre-open: 20:00-09:00 ET; inherits Asia-start approval dependency.

Under NT8 bar-end semantics, each conceptual window uses labels one minute
after its start through its end. NY pre-market therefore uses 07:01-09:00.

## Incomplete source windows by session

{json.dumps(incomplete, indent=2)}

Incomplete windows remain null/unavailable; no values are fabricated.

## Descriptive redundancy candidates for human review

{top_lines}

These correlations describe feature redundancy only. They are not related to
profitability and are not a feature ranking.

## Outcome separation

All future-looking fields live only in the breakout-outcome table and use the
`outcome_` prefix. The first measured bar is the first complete bar after the
PRINT signal bar, avoiding an unobservable within-bar chronology assumption.
"""


def _viewer_guide() -> str:
    return """# MNQ ORB V0.2 Feature Validation Viewer

Run from the repository root:

```powershell
.\\.venv\\Scripts\\python.exe -m streamlit run notebooks\\19_mnq_orb_v02_feature_viewer.py
```

Select a DEVELOPMENT session and 15/20/30-minute OR. The viewer overlays the
OR, prior RTH, overnight, proposed Asia/London, New York pre-market, and Globex
reference levels and shows the complete feature row below the chart.

This viewer contains no strategy performance. “NY PM” means New York
pre-market and is displayed as `NY Pre-Market`.
"""


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    main()
