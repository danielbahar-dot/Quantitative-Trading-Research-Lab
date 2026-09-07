"""Run Stage-3A Step-4 room-to-next-key-level characterization."""

from __future__ import annotations

from pathlib import Path
import json
import sys

import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.experiment_registration import (  # noqa: E402
    register_artifact,
    update_experiment,
)
from src.experiments.mnq_orb_v02_room_to_level_characterization import (  # noqa: E402
    EXPECTED_OR_MINUTES,
    KNOWN_LEVEL_STATE,
    NO_LEVEL_REPRESENTATION,
    NO_LEVEL_STATE,
    REPRESENTATION_TITLES,
    assert_development_input_path,
    characterize_room_to_level,
    render_report,
    required_input_columns,
)


EXPERIMENT_ID = "mnq_orb_v0_2_stage3a_conditional_state_characterization"
SIGNAL_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "signals"
INPUT_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step1b_DEV_directional_states.csv"
MASTER_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_room_to_level_characterization.csv"
STABILITY_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_room_to_level_stability.csv"
DIRECTION_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_room_to_level_direction_breakdown.csv"
TYPE_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_next_level_type_descriptive.csv"
REPORT_MD = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_room_to_level_report.md"
PLOT_PATHS = {
    "room_to_next_level_pct": SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_room_pct_30m.png",
    "room_to_next_level_or_widths": SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_room_or_widths_30m.png",
    NO_LEVEL_REPRESENTATION: SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step4_DEV_no_level_ahead_30m.png",
}


def main() -> None:
    assert_development_input_path(INPUT_CSV)
    events = pd.read_csv(INPUT_CSV, usecols=required_input_columns(), low_memory=False)
    if len(events) != 935:
        raise ValueError(f"Expected 935 Step-1B events, found {len(events)}")
    master, stability, direction, type_description, relationships, audit = (
        characterize_room_to_level(events)
    )
    if audit["equal_price_tie_n"] != 71:
        raise ValueError(
            f"Expected 71 frozen equal-price tie events, found {audit['equal_price_tie_n']}"
        )
    master.to_csv(MASTER_CSV, index=False)
    stability.to_csv(STABILITY_CSV, index=False)
    direction.to_csv(DIRECTION_CSV, index=False)
    type_description.to_csv(TYPE_CSV, index=False)
    REPORT_MD.write_text(
        render_report(master, direction, type_description, relationships, audit),
        encoding="utf-8",
    )
    for feature, path in PLOT_PATHS.items():
        if feature == NO_LEVEL_REPRESENTATION:
            _plot_no_level(master, path)
        else:
            _plot_distance(master, feature, path)
    _update_config()
    _register_outputs(audit, relationships)

    print(json.dumps(audit, indent=2))
    print(relationships.to_string(index=False))
    for path in (
        MASTER_CSV,
        STABILITY_CSV,
        DIRECTION_CSV,
        TYPE_CSV,
        REPORT_MD,
        *PLOT_PATHS.values(),
    ):
        print(path)


def _plot_distance(master: pd.DataFrame, feature: str, path: Path) -> None:
    frame = master[
        master["source_feature"].eq(feature)
        & master["outcome_horizon"].eq("30m")
        & master["or_minutes"].astype(str).isin({"15", "20", "30"})
        & master["state_label"].str.startswith("Q")
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharex="col")
    for column, duration in enumerate(EXPECTED_OR_MINUTES):
        selected = frame[frame["or_minutes"].astype(str).eq(str(duration))].sort_values(
            "state_order"
        )
        labels = selected["state_label"].tolist()
        for row, measure in enumerate(("mfe", "mae")):
            axis = axes[row, column]
            axis.plot(
                range(len(selected)),
                selected[f"median_{measure}_pct"].astype(float) * 100,
                marker="o",
                linewidth=2,
                markersize=6,
                color="#0072B2" if measure == "mfe" else "#D55E00",
            )
            axis.set_xticks(range(len(labels)), labels)
            axis.grid(alpha=0.25)
            if row == 0:
                axis.set_title(f"{duration}m OR")
            if column == 0:
                axis.set_ylabel(f"Median {measure.upper()} (% of breakout price)")
            if row == 1:
                axis.set_xlabel("Full-DEV quintile; no-level events excluded")
    fig.suptitle(
        f"MNQ ORB V0.2 DEVELOPMENT ONLY: {REPRESENTATION_TITLES[feature]} and clean 30m excursion",
        fontsize=13,
    )
    fig.tight_layout()
    _save_figure(fig, path)


def _plot_no_level(master: pd.DataFrame, path: Path) -> None:
    frame = master[
        master["source_feature"].eq(NO_LEVEL_REPRESENTATION)
        & master["outcome_horizon"].eq("30m")
        & master["or_minutes"].astype(str).isin({"15", "20", "30"})
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharex="col")
    for column, duration in enumerate(EXPECTED_OR_MINUTES):
        selected = frame[frame["or_minutes"].astype(str).eq(str(duration))].sort_values(
            "state_order"
        )
        labels = ["Known level", "No level"]
        for row, measure in enumerate(("mfe", "mae")):
            axis = axes[row, column]
            axis.scatter(
                range(len(selected)),
                selected[f"median_{measure}_pct"].astype(float) * 100,
                s=70,
                color="#0072B2" if measure == "mfe" else "#D55E00",
            )
            axis.set_xticks(range(len(labels)), labels)
            axis.grid(alpha=0.25)
            if row == 0:
                axis.set_title(f"{duration}m OR")
            if column == 0:
                axis.set_ylabel(f"Median {measure.upper()} (% of breakout price)")
            if row == 1:
                axis.set_xlabel("Separate categorical state")
    fig.suptitle(
        "MNQ ORB V0.2 DEVELOPMENT ONLY: known level vs no level ahead and clean 30m excursion",
        fontsize=13,
    )
    fig.tight_layout()
    _save_figure(fig, path)


def _save_figure(fig: plt.Figure, path: Path) -> None:
    temporary_path = path.with_name(f".{path.stem}.tmp.png")
    fig.savefig(temporary_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    temporary_path.replace(path)


def _update_config() -> None:
    path = PROJECT_ROOT / "config" / "experiments" / f"{EXPERIMENT_ID}.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.setdefault("execution", {})[
        "step4_room_to_next_key_level_characterization"
    ] = "complete"
    config["execution"]["overall_stage3a_complete"] = False
    config["execution"]["validation_accessed"] = False
    config["execution"]["oos_burned_accessed"] = False
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def _register_outputs(audit: dict[str, object], relationships: pd.DataFrame) -> None:
    metadata = {
        "partition": "DEVELOPMENT",
        "analysis_step": "STAGE_3A_STEP_4",
        "state_family": "ROOM_TO_NEXT_KEY_LEVEL",
        "strategy_performance": False,
        "combined_with_other_state_families": False,
        "validation_or_oos_accessed": False,
    }
    artifacts = [
        ("stage3a_step4_room_to_level_master", "analysis_table", "Step 4 room-to-level master characterization", MASTER_CSV, "text/csv", "analysis"),
        ("stage3a_step4_room_to_level_stability", "stability_table", "Step 4 room-to-level DEVELOPMENT-half stability", STABILITY_CSV, "text/csv", "analysis"),
        ("stage3a_step4_room_to_level_direction", "direction_breakdown", "Step 4 room-to-level LONG/SHORT breakdown", DIRECTION_CSV, "text/csv", "analysis"),
        ("stage3a_step4_next_level_type", "descriptive_table", "Step 4 frozen next-level-type description", TYPE_CSV, "text/csv", "analysis"),
        ("stage3a_step4_room_to_level_report", "research_report", "Step 4 room-to-next-key-level report", REPORT_MD, "text/markdown", "documentation"),
    ]
    for feature, path in PLOT_PATHS.items():
        artifacts.append(
            (
                f"stage3a_step4_{feature}_plot",
                "plot",
                f"Step 4 {REPRESENTATION_TITLES[feature]} 30m excursion plot",
                path,
                "image/png",
                "visualization",
            )
        )
    for artifact_id, artifact_type, title, path, mime_type, category in artifacts:
        register_artifact(
            EXPERIMENT_ID,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title,
            path=path,
            mime_type=mime_type,
            category=category,
            metadata=metadata,
            project_root=PROJECT_ROOT,
        )
    update_experiment(
        EXPERIMENT_ID,
        {
            "summary_metrics": {
                "stage3a_step4_room_to_next_key_level_characterization_complete": True,
                "overall_stage3a_complete": False,
                "step4_input_rows": audit["input_rows"],
                "step4_known_level_ahead_n": audit["known_level_ahead_n"],
                "step4_no_level_ahead_n": audit["no_level_ahead_n"],
                "step4_equal_price_tie_events": audit["equal_price_tie_n"],
                "step4_frozen_selection_mismatch_n": audit["frozen_selection_mismatch_n"],
                "step4_development_split": audit["development_split"],
                "step4_relationship_label_counts": {
                    str(label): int(count)
                    for label, count in relationships["classification"].value_counts().items()
                },
                "step4_other_state_families_combined": False,
                "validation_or_oos_accessed": False,
            },
            "notes": (
                "Stage 3A Step 4 room-to-next-key-level characterization is complete "
                "on DEVELOPMENT. The overall Stage 3A experiment remains planned. "
                "Equal-price ties retain frozen Step-1A type selection and are flagged "
                "only for descriptive sensitivity. No state-family combination, "
                "strategy filter, strategy performance, Validation, or OOS_BURNED "
                "result was produced."
            ),
            "warnings": [
                "Overall Stage 3A remains incomplete after room-to-next-key-level characterization.",
                "No Validation or OOS_BURNED access is authorized or recorded.",
                "Descriptive candidate-state labels are not validated trading filters.",
                "The 71 exact equal-price ties retain frozen Step-1A deterministic type selection.",
                "Next-level-type results are descriptive and include an untied-only sensitivity view.",
                "Step 4 does not combine room-to-level state with any other state family.",
            ],
        },
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    main()
