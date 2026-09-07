"""Run Stage-3A Step-3 OR internal-structure characterization."""

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
from src.experiments.mnq_orb_v02_or_structure_characterization import (  # noqa: E402
    ALIGNMENT_FEATURE,
    EXPECTED_OR_MINUTES,
    FEATURES,
    FEATURE_TITLES,
    assert_development_input_path,
    characterize_or_structure,
    render_report,
    required_input_columns,
)


EXPERIMENT_ID = "mnq_orb_v0_2_stage3a_conditional_state_characterization"
SIGNAL_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "signals"
INPUT_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step1b_DEV_directional_states.csv"
MASTER_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step3_DEV_or_structure_characterization.csv"
STABILITY_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step3_DEV_or_structure_stability.csv"
DIRECTION_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step3_DEV_or_structure_direction_breakdown.csv"
REPORT_MD = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step3_DEV_or_structure_report.md"
PLOT_PATHS = {
    feature: SIGNAL_DIR / f"mnq_orb_v0_2_stage3a_step3_DEV_{feature}_30m.png"
    for feature in FEATURES
}


def main() -> None:
    assert_development_input_path(INPUT_CSV)
    events = pd.read_csv(INPUT_CSV, usecols=required_input_columns(), low_memory=False)
    if len(events) != 935:
        raise ValueError(f"Expected 935 Step-1B events, found {len(events)}")
    master, stability, direction, relationships, audit = characterize_or_structure(events)
    master.to_csv(MASTER_CSV, index=False)
    stability.to_csv(STABILITY_CSV, index=False)
    direction.to_csv(DIRECTION_CSV, index=False)
    REPORT_MD.write_text(
        render_report(master, direction, relationships, audit), encoding="utf-8"
    )
    for feature, path in PLOT_PATHS.items():
        _plot_feature(master, feature, path)
    _register_outputs(audit, relationships)

    print(json.dumps(audit, indent=2))
    print(relationships.to_string(index=False))
    for path in (MASTER_CSV, STABILITY_CSV, DIRECTION_CSV, REPORT_MD, *PLOT_PATHS.values()):
        print(path)


def _plot_feature(master: pd.DataFrame, feature: str, path: Path) -> None:
    frame = master[
        (master["source_feature"] == feature)
        & (master["outcome_horizon"] == "30m")
        & (master["or_minutes"].astype(str) != "ALL")
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharex="col")
    for column, duration in enumerate(EXPECTED_OR_MINUTES):
        selected = frame[frame["or_minutes"].astype(str) == str(duration)].sort_values(
            "state_order"
        )
        labels = selected["state_label"].tolist()
        for row, measure in enumerate(("mfe", "mae")):
            axis = axes[row, column]
            axis.plot(
                range(len(selected)),
                selected[f"median_{measure}_pct"].astype(float) * 100,
                marker="o",
                linewidth=0 if feature == ALIGNMENT_FEATURE else 2,
                markersize=7 if feature == ALIGNMENT_FEATURE else 6,
                color="#0072B2" if measure == "mfe" else "#D55E00",
            )
            axis.set_xticks(range(len(labels)), labels)
            axis.grid(alpha=0.25)
            if row == 0:
                axis.set_title(f"{duration}m OR")
            if column == 0:
                axis.set_ylabel(f"Median {measure.upper()} (% of breakout price)")
            if row == 1:
                axis.set_xlabel(
                    "Alignment state" if feature == ALIGNMENT_FEATURE else "Full-DEV quintile"
                )
    fig.suptitle(
        f"MNQ ORB V0.2 DEVELOPMENT ONLY: {FEATURE_TITLES[feature]} and post-signal 30m excursion",
        fontsize=13,
    )
    if feature == ALIGNMENT_FEATURE:
        fig.text(
            0.5,
            0.01,
            "FLAT: N=3, 15m only; shown descriptively and excluded from relationship classification",
            ha="center",
            fontsize=9,
            color="#555555",
        )
    if feature == ALIGNMENT_FEATURE:
        fig.tight_layout(rect=(0, 0.045, 1, 1))
    else:
        fig.tight_layout()
    temporary_path = path.with_name(f".{path.stem}.tmp.png")
    fig.savefig(temporary_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    temporary_path.replace(path)


def _register_outputs(audit: dict[str, object], relationships: pd.DataFrame) -> None:
    metadata = {
        "partition": "DEVELOPMENT",
        "analysis_step": "STAGE_3A_STEP_3",
        "state_family": "OR_INTERNAL_STRUCTURE",
        "strategy_performance": False,
        "combined_with_or_width": False,
        "validation_or_oos_accessed": False,
    }
    artifacts = [
        ("stage3a_step3_or_structure_master", "analysis_table", "Step 3 OR-structure master characterization", MASTER_CSV, "text/csv", "analysis"),
        ("stage3a_step3_or_structure_stability", "stability_table", "Step 3 OR-structure DEVELOPMENT-half stability", STABILITY_CSV, "text/csv", "analysis"),
        ("stage3a_step3_or_structure_direction", "direction_breakdown", "Step 3 OR-structure LONG/SHORT breakdown", DIRECTION_CSV, "text/csv", "analysis"),
        ("stage3a_step3_or_structure_report", "research_report", "Step 3 OR internal-structure report", REPORT_MD, "text/markdown", "documentation"),
    ]
    for feature, path in PLOT_PATHS.items():
        artifacts.append(
            (
                f"stage3a_step3_{feature}_plot",
                "plot",
                f"Step 3 {FEATURE_TITLES[feature]} 30m excursion plot",
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
                "stage3a_step3_or_structure_characterization_complete": True,
                "overall_stage3a_complete": False,
                "step3_input_rows": audit["input_rows"],
                "step3_available_n_by_feature": audit["available_n_by_feature"],
                "step3_missing_n_by_feature": audit["missing_n_by_feature"],
                "step3_development_split": audit["development_split"],
                "step3_relationship_label_counts": {
                    str(label): int(count)
                    for label, count in relationships["classification"].value_counts().items()
                },
                "step3_other_state_families_combined": False,
                "validation_or_oos_accessed": False,
            },
            "notes": (
                "Stage 3A Step 3 OR internal-structure characterization is complete "
                "on DEVELOPMENT. The overall Stage 3A experiment remains planned. "
                "No state-family combination, strategy filter, strategy performance, "
                "Validation, or OOS_BURNED result was produced."
            ),
            "warnings": [
                "Overall Stage 3A remains incomplete after the OR internal-structure analysis.",
                "No Validation or OOS_BURNED access is authorized or recorded.",
                "Descriptive candidate-state labels are not validated trading filters.",
                "Only three FLAT alignment events exist; FLAT is reported but excluded from relationship classification.",
                "Step 3 does not combine internal structure with OR-width state.",
            ],
        },
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    main()
