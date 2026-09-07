"""Run Stage-3B London 30m interaction event characterization."""

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
    ExperimentRun,
    create_experiment,
)
from src.experiments.mnq_orb_v02_london_interaction_event_characterization import (  # noqa: E402
    EXPERIMENT_ID,
    HORIZONS,
    HYPOTHESIS_ID,
    PRIMARY_STATES,
    assert_development_input_path,
    build_london_interaction_events,
    build_orb_confirmation_comparison,
    build_review_queue,
    build_stability_table,
    build_timestamp_audit,
    characterize_anchor_outcomes,
    render_report,
    required_feature_columns,
    required_outcome_columns,
    required_price_columns,
)


CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "experiments"
    / "mnq_orb_v0_2_stage3b_london_interaction_event_characterization.json"
)
SIGNAL_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "signals"
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
    input_paths = {
        key: PROJECT_ROOT / value for key, value in config["inputs"].items()
    }
    for key in ("development_prices", "frozen_stage2_features", "frozen_stage2_print_outcomes"):
        assert_development_input_path(input_paths[key])

    features = pd.read_csv(
        input_paths["frozen_stage2_features"],
        usecols=required_feature_columns(),
        low_memory=False,
    )
    outcomes = pd.read_csv(
        input_paths["frozen_stage2_print_outcomes"],
        usecols=required_outcome_columns(),
        low_memory=False,
    )
    prices = pd.read_csv(
        input_paths["development_prices"],
        usecols=required_price_columns(),
        low_memory=False,
    )
    events, audit = build_london_interaction_events(features, prices, outcomes)
    timestamp_audit = build_timestamp_audit(events)
    or_close = characterize_anchor_outcomes(events, anchor_prefix="or_close_anchor")
    trade_through = characterize_anchor_outcomes(
        events, anchor_prefix="trade_through_anchor"
    )
    confirmation = build_orb_confirmation_comparison(events)
    stability, classification = build_stability_table(or_close)
    review_queue = build_review_queue(events)
    audit["chronology_failures"] = int((~timestamp_audit["chronology_valid"]).sum())
    audit["hypothesis_classification"] = classification
    audit["human_review_queue_n"] = int(len(review_queue))
    audit["human_review_complete"] = False

    output_paths = {
        key: PROJECT_ROOT / value for key, value in config["outputs"].items()
    }
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    csv_outputs = {
        "event_dataset": events,
        "timestamp_audit": timestamp_audit,
        "or_close_characterization": or_close,
        "trade_through_characterization": trade_through,
        "orb_confirmation_comparison": confirmation,
        "stability": stability,
        "human_review_queue": review_queue,
    }
    for key, frame in csv_outputs.items():
        frame.to_csv(output_paths[key], index=False)
    output_paths["report"].write_text(
        render_report(
            events,
            stability,
            confirmation,
            classification,
            audit,
            review_queue,
        ),
        encoding="utf-8",
    )
    _plot_or_close_excursion(stability, output_paths["or_close_plot"])
    _plot_timing_displacement(events, output_paths["timing_plot"])
    _plot_orb_groups(events, output_paths["orb_group_plot"])
    _register(config, output_paths, audit, classification)

    print(json.dumps(audit, indent=2, default=_json_default))
    print(json.dumps(classification, indent=2, default=_json_default))
    for path in output_paths.values():
        print(path)


def _register(config, output_paths, audit, classification) -> None:
    if RECORD_PATH.exists():
        run = ExperimentRun(experiment_id=EXPERIMENT_ID, project_root=PROJECT_ROOT)
    else:
        run = create_experiment(
            experiment_id=EXPERIMENT_ID,
            project_id=config["project_id"],
            strategy_id=config["strategy_id"],
            strategy_version=config["strategy_version"],
            research_stage=config["research_stage"],
            gate="V0.2-STAGE3B-LONDON-30M",
            title="Stage 3B London 30m interaction event characterization",
            experiment_type="EVENT_ANCHORED_SIGNAL_CHARACTERIZATION",
            hypothesis=config["hypothesis"]["statement"],
            description=(
                "DEVELOPMENT-only event study separating retrospective first-trade-through, "
                "causal OR-close confirmation, and unchanged later PRINT ORB anchors."
            ),
            partition="DEVELOPMENT",
            confirmatory=False,
            reserved_data_exposed=False,
            parent_experiment_ids=[
                "mnq_orb_v0_2_stage2_feature_freeze_approval",
                "mnq_orb_v0_2_stage3a_conditional_state_characterization",
            ],
            source_gates=[
                "Frozen Stage-2 feature layer",
                "Stage 3A Step 5 London 30m finding",
            ],
            configuration_path=CONFIG_PATH,
            configuration_parameters={
                "hypothesis_id": HYPOTHESIS_ID,
                "hypothesis_status": "HYPOTHESIS_CANDIDATE",
                "evidence_scope": "DEVELOPMENT_ONLY",
                "or_minutes": 30,
                "primary_states": list(PRIMARY_STATES),
                "human_review_complete": False,
            },
            dataset_id=config["dataset_id"],
            dataset_version=config["dataset_version"],
            data_hash=config["dataset_sha256"],
            instrument_id="MNQ",
            asset_class="futures",
            timeframe="1 minute",
            git_sha=config["source_git_sha"],
            status="running",
            notes="Stage 3B analysis is in progress until queued human review is completed.",
            project_root=PROJECT_ROOT,
        )
    artifact_specs = {
        "event_dataset": ("event_table", "London 30m interaction event dataset", "data"),
        "timestamp_audit": ("timestamp_audit", "London event timestamp audit", "analysis"),
        "or_close_characterization": ("analysis_table", "OR-close anchored characterization", "analysis"),
        "trade_through_characterization": ("descriptive_table", "Trade-through anchored retrospective characterization", "analysis"),
        "orb_confirmation_comparison": ("analysis_table", "ORB confirmation comparison", "analysis"),
        "stability": ("stability_table", "Stage 3B DEVELOPMENT-half stability", "analysis"),
        "human_review_queue": ("human_review_queue", "Stage 3B London representative review queue", "governance"),
        "report": ("research_report", "Stage 3B London interaction report", "documentation"),
        "or_close_plot": ("plot", "OR-close anchored MFE and MAE", "visualization"),
        "timing_plot": ("plot", "London interaction timing and displacement", "visualization"),
        "orb_group_plot": ("plot", "London interaction ORB groups", "visualization"),
    }
    metadata = {
        "partition": "DEVELOPMENT",
        "analysis_step": "STAGE_3B_LONDON_30M",
        "hypothesis_id": HYPOTHESIS_ID,
        "hypothesis_validated": False,
        "strategy_performance": False,
        "new_strategy_simulated": False,
        "validation_or_oos_accessed": False,
    }
    for key, (artifact_type, title, category) in artifact_specs.items():
        run.register_artifact(
            artifact_id=f"stage3b_london_{key}",
            artifact_type=artifact_type,
            title=title,
            path=output_paths[key],
            category=category,
            metadata=metadata,
        )
    run.register_artifact(
        artifact_id="stage3b_london_configuration",
        artifact_type="configuration",
        title="Stage 3B London interaction configuration",
        path=CONFIG_PATH,
        category="configuration",
        metadata=metadata,
    )
    run.update(
        status="running",
        decision="continue",
        summary_metrics={
            "analysis_status": "analysis_complete_human_review_pending",
            "hypothesis_id": HYPOTHESIS_ID,
            "hypothesis_status": "HYPOTHESIS_CANDIDATE_DEVELOPMENT_ONLY",
            "hypothesis_classification": classification["classification"],
            "hypothesis_validated": False,
            "total_london_interaction_events": audit["total_london_interaction_events"],
            "state_counts": audit["state_counts"],
            "hypothesis_directional_events": audit["hypothesis_directional_events"],
            "hypothesis_state_counts": audit["hypothesis_state_counts"],
            "orb_group_counts_by_state": audit["orb_group_counts_by_state"],
            "chronology_failures": audit["chronology_failures"],
            "human_review_queue_n": audit["human_review_queue_n"],
            "human_review_complete": False,
            "reserved_data_exposed": False,
        },
        notes=(
            "Stage 3B event analysis is complete on DEVELOPMENT. The experiment remains "
            "running because representative human review is pending. The hypothesis is a "
            "candidate only and is not validated or a strategy rule."
        ),
        known_limitations=[
            "Eventual CLOSE_THROUGH/SWEEP conditioning at first trade-through is retrospective.",
            "One-minute OHLC bars do not expose intrabar event ordering.",
            "The first later validated PRINT is selected deterministically when both directions occur.",
            "Sparse opposite-direction and no-ORB groups are labelled INSUFFICIENT_SAMPLE.",
        ],
        warnings=[
            "Human review remains pending.",
            "No Validation or OOS_BURNED data was accessed.",
            "No new entry, strategy, P&L, stop, target, or optimization was produced.",
        ],
        future_hypotheses=[
            "HYP-LONDON-ACCEPTANCE-01 may advance only after human review and a separately authorized validation protocol."
        ],
    )


def _plot_or_close_excursion(stability: pd.DataFrame, path: Path) -> None:
    frame = stability.loc[
        stability["level_scope"].eq("ALL")
        & stability["dev_segment"].eq("FULL_DEVELOPMENT")
    ].copy()
    x = np.arange(len(HORIZONS))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    colors = {"CLOSE_THROUGH": "#0072B2", "SWEEP": "#D55E00"}
    for axis, measure in zip(axes, ("mfe", "mae")):
        for state in PRIMARY_STATES:
            column = f"{state.lower()}_median_{measure}_pct"
            values = frame.set_index("outcome_horizon").reindex(HORIZONS)[column] * 100
            axis.plot(x, values, marker="o", linewidth=2, color=colors[state], label=state)
        axis.set_xticks(x, HORIZONS)
        axis.set_ylabel(f"Median {measure.upper()} (% of OR-close price)")
        axis.set_title(f"OR-close anchored {measure.upper()}")
        axis.grid(alpha=0.25)
    axes[0].legend(frameon=False)
    fig.suptitle("MNQ ORB V0.2 DEVELOPMENT: London 30m interaction")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save_plot(fig, path)


def _plot_timing_displacement(events: pd.DataFrame, path: Path) -> None:
    frame = events.loc[
        events["hypothesis_directional_context"]
        & events["interaction_state"].isin(PRIMARY_STATES)
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    timing = [
        frame.loc[frame["interaction_state"].eq(state), "first_trade_through_minutes_after_0930"].dropna()
        for state in PRIMARY_STATES
    ]
    displacement = [
        frame.loc[frame["interaction_state"].eq(state), "level_to_or_close_directional_displacement_points"].dropna()
        for state in PRIMARY_STATES
    ]
    axes[0].boxplot(timing, tick_labels=PRIMARY_STATES, showfliers=False)
    axes[0].set_ylabel("Minutes after 09:30")
    axes[0].set_title("First strict trade-through timing")
    axes[1].boxplot(displacement, tick_labels=PRIMARY_STATES, showfliers=False)
    axes[1].axhline(0, color="#555555", linewidth=1)
    axes[1].set_ylabel("Directional points")
    axes[1].set_title("London level to OR-close displacement")
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    fig.suptitle("MNQ ORB V0.2 DEVELOPMENT: event timing diagnostic")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save_plot(fig, path)


def _plot_orb_groups(events: pd.DataFrame, path: Path) -> None:
    frame = events.loc[
        events["hypothesis_directional_context"]
        & events["interaction_state"].isin(PRIMARY_STATES)
    ]
    groups = ["SAME_DIRECTION_ORB", "OPPOSITE_DIRECTION_ORB", "NO_ORB"]
    counts = (
        frame.groupby(["interaction_state", "orb_confirmation_group"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=PRIMARY_STATES, columns=groups, fill_value=0)
    )
    fig, axis = plt.subplots(figsize=(9, 4.8))
    x = np.arange(len(PRIMARY_STATES))
    width = 0.24
    colors = ["#009E73", "#CC79A7", "#999999"]
    for index, group in enumerate(groups):
        axis.bar(x + (index - 1) * width, counts[group], width, label=group, color=colors[index])
    axis.set_xticks(x, PRIMARY_STATES)
    axis.set_ylabel("Events")
    axis.set_title("First later validated 30m PRINT group")
    axis.legend(frameon=False, ncol=3, loc="upper center")
    axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
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
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    main()
