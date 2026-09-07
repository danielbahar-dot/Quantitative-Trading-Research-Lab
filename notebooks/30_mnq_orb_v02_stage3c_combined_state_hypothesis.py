"""Run MNQ ORB V0.2 Stage 3C combined-state hypothesis test."""

from __future__ import annotations

from pathlib import Path
import json
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.experiment_registration import (  # noqa: E402
    create_experiment,
    finalize_experiment,
)
from src.experiments.mnq_orb_v02_combined_state_hypothesis import (  # noqa: E402
    EXPERIMENT_ID,
    HORIZONS,
    HYPOTHESIS_ID,
    LOOKBACKS,
    PRIMARY_HORIZONS,
    STATE_GROUPS,
    assert_development_input_path,
    characterize_combined_state,
    efficiency_intervals_from_step3,
    render_report,
    required_input_columns,
)


CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "experiments"
    / "mnq_orb_v0_2_stage3c_combined_state_hypothesis.json"
)
RECORD_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "projects"
    / "mnq_orb_v0_2"
    / "records"
    / f"{EXPERIMENT_ID}.json"
)


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    input_path = PROJECT_ROOT / config["inputs"]["canonical_stage3a_events"]
    step3_path = PROJECT_ROOT / config["inputs"]["stage3a_step3_efficiency_source"]
    assert_development_input_path(input_path)
    assert_development_input_path(step3_path)
    events = pd.read_csv(input_path, usecols=required_input_columns(), low_memory=False)
    if len(events) != 935:
        raise ValueError(f"Expected 935 canonical Stage-3A events, found {len(events)}")
    step3 = pd.read_csv(step3_path, low_memory=False)
    intervals = efficiency_intervals_from_step3(step3)
    master, stability, direction, assessment, audit = characterize_combined_state(
        events, intervals
    )

    output_paths = {
        key: PROJECT_ROOT / value for key, value in config["outputs"].items()
    }
    output_paths["master"].parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(output_paths["master"], index=False)
    stability.to_csv(output_paths["stability"], index=False)
    direction.to_csv(output_paths["direction"], index=False)
    output_paths["report"].write_text(
        render_report(master, stability, direction, assessment, audit),
        encoding="utf-8",
    )
    _plot_state_metric(master, "mfe", output_paths["mfe_plot"])
    _plot_state_metric(master, "mae", output_paths["mae_plot"])
    _plot_half_contrasts(stability, output_paths["half_plot"])
    _register(config, output_paths, assessment, audit)

    print(json.dumps(audit, indent=2, default=_json_default))
    print(assessment.to_string(index=False))
    for path in output_paths.values():
        print(path)


def _register(config, output_paths, assessment, audit) -> None:
    if RECORD_PATH.exists():
        raise ValueError(f"Experiment record already exists: {EXPERIMENT_ID}")
    run = create_experiment(
        experiment_id=EXPERIMENT_ID,
        project_id=config["project_id"],
        strategy_id=config["strategy_id"],
        strategy_version=config["strategy_version"],
        research_stage=config["research_stage"],
        gate="V0.2-STAGE3C-COMBINED-STATE",
        title="Stage 3C combined-state hypothesis test",
        experiment_type="PREDECLARED_COMBINED_STATE_HYPOTHESIS_TEST",
        hypothesis=config["hypothesis"]["statement"],
        description=(
            "Final DEVELOPMENT-only ORB round combining fixed causal OR-width "
            "bands with the unchanged 20-minute OR-efficiency quintiles."
        ),
        partition="DEVELOPMENT",
        confirmatory=False,
        reserved_data_exposed=False,
        parent_experiment_ids=[
            "mnq_orb_v0_2_stage2_feature_freeze_approval",
            "mnq_orb_v0_2_stage3a_conditional_state_characterization",
            "mnq_orb_v0_2_stage3b_london_interaction_event_characterization",
        ],
        source_gates=[
            "Frozen Stage-2 feature layer",
            "Stage 3A Step 2 causal OR-width findings",
            "Stage 3A Step 3 20m OR-efficiency finding",
            "Stage 3B weak/unstable result not promoted",
        ],
        configuration_path=CONFIG_PATH,
        configuration_parameters={
            "hypothesis_id": HYPOTHESIS_ID,
            "hypothesis_status": "DEVELOPMENT_ONLY",
            "or_minutes": 20,
            "lookbacks": list(LOOKBACKS),
            "state_groups": list(STATE_GROUPS),
            "thresholds_optimized": False,
            "strategy_diagnostic_completed": False,
        },
        dataset_id=config["dataset_id"],
        dataset_version=config["dataset_version"],
        data_hash=config["dataset_sha256"],
        instrument_id="MNQ",
        asset_class="futures",
        timeframe="1 minute",
        git_sha=config["source_git_sha"],
        status="running",
        notes="Stage 3C analysis is running on DEVELOPMENT only.",
        project_root=PROJECT_ROOT,
    )
    metadata = {
        "partition": "DEVELOPMENT",
        "analysis_step": "STAGE_3C_COMBINED_STATE",
        "hypothesis_id": HYPOTHESIS_ID,
        "hypothesis_validated": False,
        "strategy_performance": False,
        "validation_or_oos_accessed": False,
    }
    artifact_specs = {
        "master": ("analysis_table", "Stage 3C combined-state master", "analysis"),
        "stability": ("stability_table", "Stage 3C DEVELOPMENT-half stability", "analysis"),
        "direction": ("direction_breakdown", "Stage 3C LONG/SHORT breakdown", "analysis"),
        "report": ("research_report", "Stage 3C combined-state report", "documentation"),
        "mfe_plot": ("plot", "Stage 3C median 30m MFE", "visualization"),
        "mae_plot": ("plot", "Stage 3C median 30m MAE", "visualization"),
        "half_plot": ("plot", "Stage 3C DEV-half MFE contrasts", "visualization"),
    }
    for key, (artifact_type, title, category) in artifact_specs.items():
        run.register_artifact(
            artifact_id=f"stage3c_combined_state_{key}",
            artifact_type=artifact_type,
            title=title,
            path=output_paths[key],
            category=category,
            metadata=metadata,
        )
    run.register_artifact(
        artifact_id="stage3c_combined_state_configuration",
        artifact_type="configuration",
        title="Stage 3C combined-state configuration",
        path=CONFIG_PATH,
        category="configuration",
        metadata=metadata,
    )
    classification = audit["hypothesis_classification"]
    disposition = audit["orb_research_disposition"]
    decision = {
        "CONTINUED_IMMEDIATELY_AS_RESEARCH_CANDIDATE": "continue",
        "PARKED_AS_RESEARCH_CANDIDATE": "revise",
        "REJECTED_IN_CURRENT_FORM": "reject",
    }[disposition]
    finalize_experiment(
        EXPERIMENT_ID,
        decision=decision,
        summary_metrics={
            "analysis_status": "analysis_complete",
            "hypothesis_id": HYPOTHESIS_ID,
            "hypothesis_status": "DEVELOPMENT_ONLY",
            "hypothesis_classification": classification,
            "hypothesis_validated": False,
            "orb_research_disposition": disposition,
            "eligible_n_by_lookback": audit["eligible_n_by_lookback"],
            "group_counts_by_lookback": audit["group_counts_by_lookback"],
            "promotion_ready_lookbacks": audit["promotion_ready_lookbacks"],
            "combined_more_interpretable_lookbacks": audit[
                "combined_more_interpretable_lookbacks"
            ],
            "lookback_assessment": assessment.to_dict(orient="records"),
            "optional_frozen_strategy_diagnostic": audit[
                "optional_strategy_diagnostic"
            ],
            "reserved_data_exposed": False,
        },
        notes=(
            f"Stage 3C final ORB round completed on DEVELOPMENT. Classification: "
            f"{classification}. Disposition: {disposition}. The hypothesis is not "
            "validated and no strategy rule or performance simulation was produced."
        ),
        project_root=PROJECT_ROOT,
    )


def _plot_state_metric(master: pd.DataFrame, measure: str, path: Path) -> None:
    frame = master.loc[master["outcome_horizon"].eq("30m")].copy()
    colors = ["#0072B2", "#D55E00", "#999999"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharey=True)
    for axis, lookback in zip(axes.flat, LOOKBACKS):
        selected = frame.loc[frame["lookback_sessions"].eq(lookback)].sort_values(
            "state_order"
        )
        values = selected[f"median_{measure}_pct"].astype(float) * 100
        axis.bar(range(3), values, color=colors)
        axis.set_xticks(
            range(3), ["Elevated\nnot max-eff", "Elevated\nmax-eff", "Not elevated"]
        )
        axis.set_title(f"{lookback}-session width percentile")
        axis.grid(axis="y", alpha=0.25)
    axes[0, 0].set_ylabel(f"Median {measure.upper()} (% of breakout price)")
    axes[1, 0].set_ylabel(f"Median {measure.upper()} (% of breakout price)")
    fig.suptitle(
        f"MNQ ORB V0.2 DEVELOPMENT: 20m combined state and 30m {measure.upper()}"
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _save_plot(fig, path)


def _plot_half_contrasts(stability: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    x = np.arange(len(LOOKBACKS))
    width = 0.36
    for axis, horizon in zip(axes, PRIMARY_HORIZONS):
        for index, segment in enumerate(("DEV_FIRST_HALF", "DEV_SECOND_HALF")):
            values = []
            for lookback in LOOKBACKS:
                frame = stability.loc[
                    stability["lookback_sessions"].eq(lookback)
                    & stability["dev_segment"].eq(segment)
                    & stability["breakout_direction"].eq("ALL")
                    & stability["outcome_horizon"].eq(horizon)
                ]
                medians = frame.set_index("state_group")["median_mfe_pct"]
                values.append(
                    (
                        medians[STATE_GROUPS[0]] - medians[STATE_GROUPS[2]]
                    )
                    * 100
                )
            axis.bar(
                x + (index - 0.5) * width,
                values,
                width,
                label=segment.replace("DEV_", "").replace("_", " ").title(),
                color=("#0072B2", "#E69F00")[index],
            )
        axis.axhline(0, color="#555555", linewidth=1)
        axis.set_xticks(x, [f"{lookback}d" for lookback in LOOKBACKS])
        axis.set_title(f"{horizon} MFE contrast")
        axis.set_xlabel("Causal width lookback")
        axis.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Primary minus not elevated median MFE (percentage points)")
    axes[0].legend(frameon=False)
    fig.suptitle("MNQ ORB V0.2 DEVELOPMENT: combined-state half stability")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save_plot(fig, path)


def _save_plot(fig, path: Path) -> None:
    temporary = path.with_name(f".{path.stem}.tmp.png")
    fig.savefig(temporary, dpi=160, bbox_inches="tight")
    plt.close(fig)
    temporary.replace(path)


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    main()
