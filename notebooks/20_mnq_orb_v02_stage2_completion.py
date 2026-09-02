"""Complete MNQ ORB V0.2 Stage 2 feature validation on DEVELOPMENT only.

This runner extends the immutable initial Stage-2 record with a linked
completion experiment.  It does not calculate strategy performance, define
entry filters, or load Validation/OOS_BURNED.
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
    build_outcome_contract,
    build_representative_review_queue,
    build_window_availability_audit,
    characterize_features,
    feature_summary,
    load_development_prices,
    read_json,
    write_characterization_charts,
)


CONFIG_PATH = PROJECT_ROOT / "config" / "experiments" / "mnq_orb_v0_2_stage2_feature_validation_completion.json"
WINDOW_CONFIG_PATH = PROJECT_ROOT / "config" / "features" / "mnq_orb_v0_2_preopen_windows.json"
COMPONENT_REGISTRY_PATH = PROJECT_ROOT / "config" / "components" / "research_components.json"
IDEAS_PATH = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "research_ideas.json"
OUTPUT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "features"


def main() -> None:
    config = read_json(CONFIG_PATH)
    window_config = read_json(WINDOW_CONFIG_PATH)
    run = create_experiment(
        experiment_id=config["experiment_id"],
        project_id=config["project_id"],
        strategy_id=config["strategy_id"],
        strategy_version=config["strategy_version"],
        research_stage=config["research_stage"],
        gate="V0.2-S2-COMPLETION",
        title="Stage 2 feature validation completion",
        experiment_type="FEATURE_VALIDATION",
        hypothesis="Approved session windows and added causal context features can be fully audited and visually reviewed without strategy performance analysis.",
        description="DEVELOPMENT-only Stage-2 completion: approved definitions, previous-day levels, NY-open gap, short causal width history, signal-bar descriptive excursion, missing-data diagnosis, and viewer validation support.",
        partition="DEVELOPMENT",
        confirmatory=False,
        reserved_data_exposed=False,
        parent_experiment_ids=["mnq_orb_v0_2_stage2_feature_validation"],
        source_gates=["V0.2 Stage 2 initial feature validation", "V0.2 Stage 2 completion review"],
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
        prices = load_development_prices(PROJECT_ROOT / config["dataset_path"])
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
        feature_contract = build_feature_contract(features)
        outcome_contract = build_outcome_contract(outcomes)
        availability = build_window_availability_audit(prices, window_config)
        review_queue = build_representative_review_queue(features, availability)
        distributions, correlations = characterize_features(features)
        summary = feature_summary(features, outcomes, ambiguous)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        prefix = "mnq_orb_v0_2_stage2_completion"
        paths = {
            "feature_audit": OUTPUT_DIR / f"{prefix}_DEV_feature_audit.csv",
            "feature_contract": OUTPUT_DIR / f"{prefix}_feature_timing_contract.csv",
            "outcome_contract": OUTPUT_DIR / f"{prefix}_outcome_contract.csv",
            "feature_distribution": OUTPUT_DIR / f"{prefix}_DEV_feature_distributions.csv",
            "feature_correlation": OUTPUT_DIR / f"{prefix}_DEV_feature_correlations.csv",
            "outcomes": OUTPUT_DIR / f"{prefix}_DEV_print_breakout_outcomes.csv",
            "ambiguity_audit": OUTPUT_DIR / f"{prefix}_DEV_print_ambiguity_audit.csv",
            "availability_audit": OUTPUT_DIR / f"{prefix}_DEV_overnight_availability_audit.csv",
            "representative_review": OUTPUT_DIR / f"{prefix}_representative_review_queue.csv",
            "distribution_chart": OUTPUT_DIR / f"{prefix}_DEV_feature_distributions.html",
            "correlation_chart": OUTPUT_DIR / f"{prefix}_DEV_feature_correlations.html",
            "metadata": OUTPUT_DIR / f"{prefix}_metadata.json",
            "report": OUTPUT_DIR / f"{prefix}_report.md",
            "viewer_guide": OUTPUT_DIR / f"{prefix}_viewer_guide.md",
        }
        for frame, path in (
            (features, paths["feature_audit"]),
            (feature_contract, paths["feature_contract"]),
            (outcome_contract, paths["outcome_contract"]),
            (distributions, paths["feature_distribution"]),
            (correlations, paths["feature_correlation"]),
            (outcomes, paths["outcomes"]),
            (ambiguous, paths["ambiguity_audit"]),
            (availability, paths["availability_audit"]),
            (review_queue, paths["representative_review"]),
        ):
            frame.to_csv(path, index=False)
        write_characterization_charts(
            features, correlations,
            distribution_path=paths["distribution_chart"],
            correlation_path=paths["correlation_chart"],
        )
        metadata = _metadata(config, window_config, prices, features, outcomes, availability, review_queue, summary)
        paths["metadata"].write_text(json.dumps(metadata, indent=2, default=_json_default) + "\n", encoding="utf-8")
        paths["report"].write_text(_report(metadata), encoding="utf-8")
        paths["viewer_guide"].write_text(_viewer_guide(), encoding="utf-8")

        artifact_specs = {
            "feature_audit": ("feature_table", "Canonical Stage-2 completion DEVELOPMENT feature audit", "data"),
            "feature_contract": ("feature_contract", "Stage-2 completion feature timing contract", "metadata"),
            "outcome_contract": ("outcome_contract", "Signal-bar and post-signal outcome contract", "metadata"),
            "feature_distribution": ("descriptive_summary", "DEVELOPMENT feature distributions", "data"),
            "feature_correlation": ("descriptive_summary", "DEVELOPMENT feature correlations", "data"),
            "outcomes": ("outcome_table", "PRINT descriptive excursion outcomes", "data"),
            "ambiguity_audit": ("audit", "PRINT ambiguity audit", "data"),
            "availability_audit": ("audit", "Overnight unavailable-reason audit", "data"),
            "representative_review": ("human_review_queue", "Representative feature-validation review queue", "data"),
            "distribution_chart": ("chart", "DEVELOPMENT feature distributions", "chart"),
            "correlation_chart": ("chart", "DEVELOPMENT feature correlations", "chart"),
            "metadata": ("metadata", "Stage-2 completion metadata", "metadata"),
            "report": ("report", "Stage-2 completion report", "documentation"),
            "viewer_guide": ("viewer_guide", "Stage-2 completion viewer guide", "documentation"),
        }
        for artifact_id, (artifact_type, title, category) in artifact_specs.items():
            run.register_artifact(
                artifact_id=artifact_id, artifact_type=artifact_type, title=title,
                path=paths[artifact_id], category=category,
                metadata={"partition": "DEVELOPMENT", "performance_metrics": False},
            )
        for artifact_id, artifact_type, title, path, category in (
            ("completion_configuration", "configuration", "Stage-2 completion configuration", CONFIG_PATH, "configuration"),
            ("window_configuration", "configuration", "Approved pre-open window definitions", WINDOW_CONFIG_PATH, "configuration"),
            ("component_registry", "component_definitions", "Reusable research component registry", COMPONENT_REGISTRY_PATH, "metadata"),
            ("research_ideas", "research_backlog", "Untested research-idea backlog", IDEAS_PATH, "documentation"),
        ):
            run.register_artifact(
                artifact_id=artifact_id, artifact_type=artifact_type, title=title,
                path=path, category=category,
                metadata={"performance_metrics": False},
            )
        run.update(
            summary_metrics=summary,
            decision="continue",
            notes="Stage-2 completion evidence is ready for human visual/data review. Final Stage-2 freeze is not automatic; no V0.2 strategy rule or performance result was created.",
            known_limitations=[
                "Ten DEVELOPMENT sessions lack the requested prior 16:14 reference; NY_OPEN_GAP remains unavailable for the following sessions rather than substituting another bar.",
                "Quarterly contract-roll source gaps and isolated missing bars keep affected overnight features unavailable under the unchanged completeness rule.",
                "Signal-bar excursion is observable only as unordered OHLC extremes and is explicitly CHRONOLOGY_UNKNOWN.",
            ],
            warnings=[
                "NY PM means New York pre-market (07:00-09:00 ET).",
                "Outcome columns are descriptive future labels, not causal features or execution inputs.",
                "No Validation or OOS_BURNED file was loaded.",
                "Human representative-session review remains required before Stage 2 freeze.",
            ],
        )

    print(json.dumps(metadata, indent=2, default=_json_default))
    print(f"Registered experiment: {run.experiment_id}")


def _metadata(config, window_config, prices, features, outcomes, availability, review_queue, summary):
    warmup = {}
    for lookback in config["historical_width_lookbacks"]:
        column = f"or_width_hist_{lookback}_available"
        warmup[str(lookback)] = {
            "available_rows": int(features[column].sum()),
            "unavailable_rows": int((~features[column].astype(bool)).sum()),
        }
    times = pd.Series(prices.index.strftime("%H:%M"), index=prices.index)
    sessions_1614 = int(prices.loc[times.eq("16:14"), "session_date"].nunique())
    sessions_0931 = int(prices.loc[times.eq("09:31"), "session_date"].nunique())
    unavailable_reasons = (
        availability.groupby(["feature_window", "unavailable_reason"]).size().rename("sessions").reset_index().to_dict("records")
        if not availability.empty else []
    )
    return {
        "experiment_id": config["experiment_id"],
        "parent_experiment_id": "mnq_orb_v0_2_stage2_feature_validation",
        "research_stage": "STAGE_2_FEATURES",
        "partition": "DEVELOPMENT",
        "development_range": [config["development_start"], config["development_end"]],
        "maximum_session_date_analyzed": summary["maximum_session_date"],
        "validation_or_oos_loaded": False,
        "strategy_performance_calculated": False,
        "timestamp_semantics": "timestamp_et = bar_end_time",
        "approved_windows": {
            "ASIA_KZ": "20:00-00:00 ET; bar ends 20:01-00:00",
            "LONDON_KZ": "02:00-05:00 ET; bar ends 02:01-05:00",
            "NY_PRE_MARKET": "07:00-09:00 ET; bar ends 07:01-09:00",
            "OVERNIGHT_CONTEXT_2000_0900": "20:00-09:00 ET; bar ends 20:01-09:00",
        },
        "window_configuration": window_config,
        "previous_day_definition": "Previous futures trading session owned by session_date, bar ends from prior-calendar-day 18:01 through trading-date 17:00; complete prior session only.",
        "ny_open_gap_definition": {
            "prior_reference": "prior trading day's bar stamped 16:14 ET close",
            "prior_reference_bar_meaning": "activity ending at 16:14 under NT8 bar-end labels",
            "current_reference": "current bar stamped 09:31 ET open, representing the 09:30:00 New York open",
            "earliest_bar_data_availability": "09:31 ET",
            "sessions_with_1614_bar": sessions_1614,
            "sessions_with_0931_bar": sessions_0931,
            "no_substitution": True,
        },
        "globex_reopen_gap_definition": "Prior 17:00 close to following 18:01 bar open; fill state through 09:30; unchanged semantics with explicit field names.",
        "historical_width": {"lookbacks": config["historical_width_lookbacks"], "warmup": warmup},
        "signal_bar_outcome": {
            "fields": [column for column in outcomes if column.startswith("signal_bar_")],
            "chronology_unknown": True,
            "execution_input": False,
            "clean_post_signal_prefix": "post_signal_bar_",
        },
        "overnight_unavailable_reasons": unavailable_reasons,
        "representative_review_cases": int(len(review_queue)),
        "representative_review_pending": int(review_queue["human_review_status"].eq("PENDING_HUMAN_REVIEW").sum()),
        "feature_rows": int(len(features)),
        "feature_columns": int(len(features.columns)),
        "outcome_events": int(len(outcomes)),
        "outcome_events_by_or_minutes": {str(key): int(value) for key, value in outcomes.groupby("or_minutes").size().items()},
        "ambiguous_print_bars": summary["ambiguous_print_bars"],
        "final_stage2_human_approval_required": True,
    }


def _report(metadata) -> str:
    warmup = metadata["historical_width"]["warmup"]
    warmup_lines = "\n".join(f"- {key} sessions: {value['available_rows']} populated rows" for key, value in warmup.items())
    missing_lines = "\n".join(
        f"- {row['feature_window']} / {row['unavailable_reason']}: {row['sessions']} sessions"
        for row in metadata["overnight_unavailable_reasons"]
    ) or "- No unavailable overnight observations."
    return f"""# MNQ ORB V0.2 Stage 2 Feature Validation Completion

This is DEVELOPMENT-only feature validation. No strategy performance, feature
optimization, entry filter, or V0.2 trading rule was calculated.

## Approved definitions

- Asia KZ: 20:00-00:00 ET.
- London KZ: 02:00-05:00 ET.
- New York pre-market: 07:00-09:00 ET.
- `combined_preopen` migrated to `OVERNIGHT_CONTEXT_2000_0900`, a continuous
  20:00-09:00 contextual range rather than a union of named windows.

All use NT8 bar-end labels: a conceptual start is represented by the first bar
stamped one minute later.

## Previous-day and gap families

Previous-day H/L/C use the complete prior futures trading day owned by
`session_date`: prior-calendar-day 18:01 through trading-date 17:00 bar ends.
Previous RTH H/L/C remain optional reusable features.

`GLOBEX_REOPEN_GAP` remains the prior 17:00 close to 18:01 reopen concept.
`NY_OPEN_GAP` is separate: prior trading day's 16:14 bar close versus the
current 09:31 bar open (the 09:30 market open). The 16:14 reference exists in
{metadata['ny_open_gap_definition']['sessions_with_1614_bar']} of 248 source
sessions; missing bars are not substituted.

## Causal OR-width history

{warmup_lines}

Every populated value uses only the exact prior completed sessions of the same
OR duration. Current-session data never enters its own reference distribution.

## Outcome separation

Signal-bar favorable/adverse excursion is retained as unordered OHLC evidence
and always labelled `signal_bar_chronology_unknown = true`. Clean MFE/MAE fields
use the `post_signal_bar_` prefix and begin with the first complete bar after
the PRINT signal bar. Neither family changes execution logic.

## Overnight missing-data diagnosis

{missing_lines}

Completeness rules were not weakened. The detailed audit records expected and
observed bars, actual first/last timestamps, and reason for every unavailable
overnight/context observation.

## Human review status

The viewer includes validation presets, prior-session context, selectable end
times through 16:00, independent X/Y navigation, an interactive legend, and a
neutral TOUCH / TRADE_THROUGH / CLOSE_THROUGH / REJECT / SWEEP panel.
{metadata['representative_review_cases']} representative review cases are queued.
Final Stage-2 freeze still requires human visual/data approval.

## Isolation

- Feature audit: {metadata['feature_rows']} session x OR-duration rows and {metadata['feature_columns']} columns.
- Maximum session date: {metadata['maximum_session_date_analyzed']}.
- Validation/OOS loaded: no.
- Strategy performance calculated: no.
"""


def _viewer_guide() -> str:
    return """# MNQ ORB V0.2 Stage-2 Completion Viewer

Run from the repository root:

```powershell
.\\.venv\\Scripts\\python.exe -m streamlit run notebooks\\19_mnq_orb_v02_feature_viewer.py
```

Use validation presets or manual overlays. The default `PREVIOUS DAY` preset
shows primary full-trading-day references; previous RTH remains optional.
Select `Prior 16:45 · gap validation` to see the prior 16:14/17:00 references,
18:01 reopen, and overnight development. Chart end is selectable through 16:00.

Click legend entries to hide/show individual levels. X and Y zoom buttons act
independently; dragging an axis pans/scales that axis. The machine-classification
tab shows neutral key-level event primitives. The representative-case selector
navigates directly to the queued session, duration, and preset; the follow-up
queue identifies the exact triggering high/low and its primitive flags.

`Overnight High/Low` means the full 18:00-09:30 Globex window. `Overnight
Context High/Low` means the narrower 20:00-09:00 research window, excluding the
first two hours after reopen and the final 30 minutes before RTH. The dedicated
liquidity-path tab compares later completed pre-open windows with earlier ones
and explains HIGH_ONLY / LOW_ONLY / BOTH / NEITHER in plain language.

No strategy performance is displayed or calculated.
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
