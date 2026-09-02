"""Record the human-approved MNQ ORB V0.2 Stage-2 feature freeze.

This governance runner reads only the existing DEVELOPMENT feature/audit
artifacts. It does not load Validation or OOS, calculate performance, or define
V0.2 strategy rules. The prior completion experiment remains immutable; this
linked record captures the subsequent 14/14 human approval decision.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments import create_experiment  # noqa: E402
from src.experiments.mnq_orb_v02_features import (  # noqa: E402
    apply_human_review_decisions,
    build_representative_review_queue,
    read_json,
)


CONFIG_PATH = PROJECT_ROOT / "config" / "experiments" / "mnq_orb_v0_2_stage2_feature_freeze_approval.json"
COMPONENT_REGISTRY_PATH = PROJECT_ROOT / "config" / "components" / "research_components.json"
OUTPUT_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "features"


def main() -> None:
    config = read_json(CONFIG_PATH)
    decisions_path = PROJECT_ROOT / config["human_review_decisions_path"]
    feature_path = PROJECT_ROOT / config["feature_audit_path"]
    availability_path = PROJECT_ROOT / config["availability_audit_path"]
    feature_contract_path = PROJECT_ROOT / config["feature_contract_path"]
    window_config_path = PROJECT_ROOT / config["window_config_path"]

    run = create_experiment(
        experiment_id=config["experiment_id"],
        project_id=config["project_id"],
        strategy_id=config["strategy_id"],
        strategy_version=config["strategy_version"],
        research_stage=config["research_stage"],
        gate="V0.2-S2-FREEZE",
        title="Stage 2 feature validation human approval and freeze",
        experiment_type="FEATURE_FREEZE_APPROVAL",
        hypothesis="The completed causal feature package satisfies automated invariants and all representative human visual checks and can be frozen before signal research.",
        description="Append-only DEVELOPMENT-only governance record for 14/14 human review PASS, exact trigger_id evidence, and Stage-2 feature freeze.",
        partition=config["partition"],
        confirmatory=False,
        reserved_data_exposed=False,
        parent_experiment_ids=["mnq_orb_v0_2_stage2_feature_validation_completion"],
        source_gates=["V0.2 Stage 2 completion", "V0.2 Stage 2 human visual review"],
        configuration_path=CONFIG_PATH,
        configuration_parameters={
            "human_review_completion_date": config["human_review_completion_date"],
            "required_passes": 14,
            "validation_or_oos_loaded": False,
        },
        dataset_id=config["dataset_id"],
        dataset_version=config["dataset_version"],
        data_hash=config["dataset_sha256"],
        instrument_id="MNQ",
        asset_class="futures",
        timeframe="1 minute",
        project_root=PROJECT_ROOT,
    )

    with run:
        # These are existing DEVELOPMENT-only Stage-2 artifacts. No reserved
        # partition file is opened anywhere in this approval runner.
        features = pd.read_csv(feature_path)
        availability = pd.read_csv(availability_path)
        decisions = read_json(decisions_path)
        queue = build_representative_review_queue(features, availability)
        queue = apply_human_review_decisions(queue, decisions["decisions"])
        metadata = _validate_and_describe(config, features, queue)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        paths = {
            "final_review_queue": OUTPUT_DIR / "mnq_orb_v0_2_stage2_final_human_review_queue.csv",
            "freeze_metadata": OUTPUT_DIR / "mnq_orb_v0_2_stage2_feature_freeze_metadata.json",
            "freeze_report": OUTPUT_DIR / "mnq_orb_v0_2_stage2_feature_freeze_report.md",
        }
        queue.to_csv(paths["final_review_queue"], index=False)
        paths["freeze_metadata"].write_text(
            json.dumps(metadata, indent=2, default=_json_default) + "\n", encoding="utf-8"
        )
        paths["freeze_report"].write_text(_report(metadata, queue), encoding="utf-8")

        for artifact_id, artifact_type, title, path, category in (
            ("final_review_queue", "human_review_queue", "Final 14-of-14 Stage-2 human review queue", paths["final_review_queue"], "data"),
            ("freeze_metadata", "freeze", "Stage-2 feature freeze metadata", paths["freeze_metadata"], "metadata"),
            ("freeze_report", "report", "Final Stage-2 feature freeze report", paths["freeze_report"], "documentation"),
            ("feature_audit", "feature_table", "Frozen DEVELOPMENT feature audit", feature_path, "data"),
            ("availability_audit", "audit", "Frozen missing-source availability audit", availability_path, "data"),
            ("feature_contract", "feature_contract", "Frozen feature timing contract", feature_contract_path, "metadata"),
            ("human_decisions", "human_review_decisions", "Versioned human review decisions", decisions_path, "governance"),
            ("window_configuration", "configuration", "Frozen pre-open window definitions", window_config_path, "configuration"),
            ("component_registry", "component_definitions", "Validated Stage-2 component registry", COMPONENT_REGISTRY_PATH, "metadata"),
            ("freeze_configuration", "configuration", "Stage-2 feature freeze configuration", CONFIG_PATH, "configuration"),
        ):
            run.register_artifact(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                title=title,
                path=path,
                category=category,
                metadata={
                    "partition": "DEVELOPMENT",
                    "performance_metrics": False,
                    "human_review_completion_date": config["human_review_completion_date"],
                    "validation_or_oos_accessed": False,
                },
            )
        run.update(
            summary_metrics={
                "representative_review_cases": metadata["representative_review_cases"],
                "representative_review_passed": metadata["representative_review_passed"],
                "representative_review_pending": 0,
                "feature_rows": metadata["feature_rows"],
                "feature_columns": metadata["feature_columns"],
                "maximum_session_date": metadata["maximum_session_date"],
                "validation_or_oos_accessed": False,
            },
            decision="freeze",
            notes="Human review completed 2026-09-02: all 14 representative Stage-2 cases passed. Features are validated and frozen for the next research stage; this is not strategy or deployment approval.",
            known_limitations=[
                "Incomplete source windows remain explicitly unavailable; completeness rules were not weakened.",
                "Liquidity-path states compare completed window extremes and do not encode intrawindow chronology.",
                "Signal-bar excursion remains unordered OHLC evidence and is not an execution input.",
            ],
            warnings=[
                "No Validation or OOS_BURNED data was accessed.",
                "No strategy performance was calculated and no V0.2 signal or trading rule was defined.",
            ],
        )

    print(json.dumps(metadata, indent=2, default=_json_default))
    print(f"Registered experiment: {run.experiment_id}")


def _validate_and_describe(config, features: pd.DataFrame, queue: pd.DataFrame) -> dict:
    dates = pd.to_datetime(features["session_date"])
    if dates.min() < pd.Timestamp(config["development_start"]):
        raise AssertionError("Pre-DEVELOPMENT session entered the feature freeze")
    if dates.max() > pd.Timestamp(config["development_end"]):
        raise AssertionError("Validation or OOS session entered the feature freeze")
    if config.get("validation_or_oos_loaded") is not False:
        raise AssertionError("Freeze config must explicitly prohibit reserved-data access")
    if len(queue) != 14 or not queue["human_review_status"].eq("PASS").all():
        raise AssertionError("Stage-2 freeze requires exactly 14/14 representative PASS decisions")
    if queue["trigger_id"].isna().any() or queue["trigger_id"].astype(str).str.strip().eq("").any():
        raise AssertionError("Every representative case requires a machine-stable trigger_id")
    clean = queue.loc[queue["review_case"].eq("CLEAN_TRADE_THROUGH")].iloc[0]
    if not (
        clean["trigger_id"] == "previous_day_high"
        and bool(clean["trade_through"])
        and bool(clean["close_through"])
        and not bool(clean["reject"])
    ):
        raise AssertionError("CLEAN_TRADE_THROUGH predicates do not reconcile on one trigger_id")
    return {
        "experiment_id": config["experiment_id"],
        "research_stage": "STAGE_2_FEATURES",
        "lifecycle_status": "FEATURES_VALIDATED_AND_FROZEN",
        "decision": "freeze",
        "human_review_completion_date": config["human_review_completion_date"],
        "representative_review_cases": int(len(queue)),
        "representative_review_passed": int(queue["human_review_status"].eq("PASS").sum()),
        "representative_review_pending": int(queue["human_review_status"].eq("PENDING_HUMAN_REVIEW").sum()),
        "feature_rows": int(len(features)),
        "feature_columns": int(len(features.columns)),
        "minimum_session_date": dates.min().date().isoformat(),
        "maximum_session_date": dates.max().date().isoformat(),
        "partition": "DEVELOPMENT",
        "validation_or_oos_accessed": False,
        "strategy_performance_calculated": False,
        "trigger_identifier_field": "trigger_id",
        "same_level_multi_predicate_enforced": True,
        "next_phase_authorized": "STAGE_3_SIGNALS",
        "next_phase_started": False,
    }


def _report(metadata: dict, queue: pd.DataFrame) -> str:
    level_rows = queue.loc[queue["trigger_type"].eq("KEY_LEVEL_INTERACTION")]
    identifiers = "\n".join(
        f"- `{row.review_case}` -> `{row.trigger_id}`"
        for row in level_rows.itertuples(index=False)
    )
    return f"""# MNQ ORB V0.2 Stage 2 Feature Validation — Final Freeze

## Decision

- Lifecycle state: **FEATURES_VALIDATED_AND_FROZEN**
- Experiment decision: **freeze**
- Human review completion date: **{metadata['human_review_completion_date']}**
- Representative reviews: **{metadata['representative_review_passed']}/{metadata['representative_review_cases']} PASS**
- Next authorized stage: **STAGE_3_SIGNALS** (not started by this gate)

This approval freezes the Stage-2 feature definitions and evidence. It does not
approve a V0.2 strategy, signal, execution model, performance claim, or live use.

## Corrected representative-review contract

Every populated representative case stores a machine-stable `trigger_id`, not
only human-readable text. Key-level examples are:

{identifiers}

`CLEAN_TRADE_THROUGH` is selected only when `TRADE_THROUGH=true`,
`CLOSE_THROUGH=true`, and `REJECT=false` all belong to the same exact
`trigger_id`. Queue enrichment independently resolves that level and fails if
the predicates cannot be reconciled on one reference level.

The liquidity-path case stores the exact comparison key (`london_took_asia`)
and explicit HIGH_ONLY/LOW_ONLY/BOTH/NEITHER evidence. Gap and availability
cases likewise store stable feature identifiers.

## Human review completion

All 14 representative cases passed, including narrow/wide OR, previous-day
touch/trade-through/sweep/close-through, Asia/London/NY pre-market interaction,
liquidity path, Globex gap FILLED/PARTIAL/OPEN, and incomplete source-window
handling.

## Data isolation

- Partition loaded: DEVELOPMENT only.
- Session range: {metadata['minimum_session_date']} through {metadata['maximum_session_date']}.
- Validation accessed: no.
- OOS_BURNED accessed: no.
- Strategy performance calculated: no.

## Frozen limitations

- Incomplete source windows remain unavailable rather than being fabricated.
- Liquidity-path comparisons do not reconstruct intrawindow chronology.
- Signal-bar excursion remains unordered OHLC evidence and is not an execution input.
"""


def _json_default(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    main()
