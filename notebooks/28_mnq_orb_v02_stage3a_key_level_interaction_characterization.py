"""Run Stage-3A Step-5 key-level interaction characterization."""

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
from src.experiments.mnq_orb_v02_key_level_interaction_characterization import (  # noqa: E402
    EXPECTED_OR_MINUTES,
    INTERACTION_STATES,
    LEVEL_FAMILIES,
    LEVEL_FAMILY_TITLES,
    assert_development_input_path,
    characterize_key_level_interactions,
    render_report,
    required_input_columns,
)


EXPERIMENT_ID = "mnq_orb_v0_2_stage3a_conditional_state_characterization"
SIGNAL_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "signals"
INPUT_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step1b_DEV_directional_states.csv"
MASTER_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step5_DEV_key_level_interaction_characterization.csv"
STABILITY_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step5_DEV_key_level_interaction_stability.csv"
DIRECTION_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step5_DEV_key_level_interaction_direction_breakdown.csv"
REPORT_MD = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step5_DEV_key_level_interaction_report.md"
PLOT_PATHS = {
    measure: SIGNAL_DIR / f"mnq_orb_v0_2_stage3a_step5_DEV_key_level_interaction_{measure}_30m.png"
    for measure in ("mfe", "mae")
}


def main() -> None:
    assert_development_input_path(INPUT_CSV)
    events = pd.read_csv(INPUT_CSV, usecols=required_input_columns(), low_memory=False)
    if len(events) != 935:
        raise ValueError(f"Expected 935 Step-1B events, found {len(events)}")
    master, stability, direction, relationships, audit = (
        characterize_key_level_interactions(events)
    )
    master.to_csv(MASTER_CSV, index=False)
    stability.to_csv(STABILITY_CSV, index=False)
    direction.to_csv(DIRECTION_CSV, index=False)
    REPORT_MD.write_text(
        render_report(master, direction, relationships, audit), encoding="utf-8"
    )
    for measure, path in PLOT_PATHS.items():
        _plot_interaction_states(master, measure, path)
    _update_config()
    _register_outputs(audit, relationships)

    print(json.dumps(audit, indent=2))
    print(relationships.to_string(index=False))
    for path in (MASTER_CSV, STABILITY_CSV, DIRECTION_CSV, REPORT_MD, *PLOT_PATHS.values()):
        print(path)


def _plot_interaction_states(master: pd.DataFrame, measure: str, path: Path) -> None:
    frame = master[
        master["outcome_horizon"].eq("30m")
        & master["or_minutes"].astype(str).isin({"15", "20", "30"})
    ]
    labels = ["None", "Touch", "Close", "Reject", "Sweep"]
    colors = {15: "#0072B2", 20: "#009E73", 30: "#D55E00"}
    fig, axes = plt.subplots(2, 2, figsize=(15, 9), sharex=True)
    for axis, family in zip(axes.flat, LEVEL_FAMILIES):
        family_frame = frame[frame["level_family"].eq(family)]
        for duration in EXPECTED_OR_MINUTES:
            selected = family_frame[
                family_frame["or_minutes"].astype(str).eq(str(duration))
            ].sort_values("state_order")
            available = selected["event_n"].ge(5) & selected[f"median_{measure}_pct"].notna()
            axis.scatter(
                selected.loc[available, "state_order"] - 1,
                selected.loc[available, f"median_{measure}_pct"] * 100,
                s=65,
                color=colors[duration],
                label=f"{duration}m OR",
            )
        axis.set_title(LEVEL_FAMILY_TITLES[family])
        axis.set_xticks(range(len(INTERACTION_STATES)), labels)
        axis.grid(alpha=0.25)
        axis.set_ylabel(f"Median {measure.upper()} (% of breakout price)")
    handles, legend_labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center", ncol=3, frameon=False)
    fig.suptitle(
        f"MNQ ORB V0.2 DEVELOPMENT ONLY: key-level interaction and clean 30m {measure.upper()}",
        fontsize=13,
        y=0.98,
    )
    fig.text(
        0.5,
        0.02,
        "Markers require N ≥ 5; missing sparse-state markers are intentional",
        ha="center",
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.93))
    temporary_path = path.with_name(f".{path.stem}.tmp.png")
    fig.savefig(temporary_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    temporary_path.replace(path)


def _update_config() -> None:
    path = PROJECT_ROOT / "config" / "experiments" / f"{EXPERIMENT_ID}.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.setdefault("execution", {})[
        "step5_key_level_interaction_characterization"
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
        "analysis_step": "STAGE_3A_STEP_5",
        "state_family": "KEY_LEVEL_INTERACTION_AT_OR",
        "strategy_performance": False,
        "combined_with_other_state_families": False,
        "validation_or_oos_accessed": False,
    }
    artifacts = [
        ("stage3a_step5_key_level_interaction_master", "analysis_table", "Step 5 key-level interaction master characterization", MASTER_CSV, "text/csv", "analysis"),
        ("stage3a_step5_key_level_interaction_stability", "stability_table", "Step 5 key-level interaction DEVELOPMENT-half stability", STABILITY_CSV, "text/csv", "analysis"),
        ("stage3a_step5_key_level_interaction_direction", "direction_breakdown", "Step 5 key-level interaction LONG/SHORT breakdown", DIRECTION_CSV, "text/csv", "analysis"),
        ("stage3a_step5_key_level_interaction_report", "research_report", "Step 5 key-level interaction report", REPORT_MD, "text/markdown", "documentation"),
    ]
    for measure, path in PLOT_PATHS.items():
        artifacts.append(
            (
                f"stage3a_step5_key_level_interaction_{measure}_plot",
                "plot",
                f"Step 5 key-level interaction clean 30m {measure.upper()} plot",
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
                "stage3a_step5_key_level_interaction_characterization_complete": True,
                "overall_stage3a_complete": False,
                "step5_input_rows": audit["input_rows"],
                "step5_family_event_rows": audit["family_event_rows"],
                "step5_eligible_n_by_family": audit["eligible_n_by_family"],
                "step5_unavailable_n_by_family": audit["unavailable_n_by_family"],
                "step5_category_counts_by_family": audit["category_counts_by_family"],
                "step5_development_split": audit["development_split"],
                "step5_relationship_label_counts": {
                    str(label): int(count)
                    for label, count in relationships["classification"].value_counts().items()
                },
                "step5_other_state_families_combined": False,
                "validation_or_oos_accessed": False,
            },
            "notes": (
                "Stage 3A Step 5 key-level interaction characterization is complete "
                "on DEVELOPMENT. The overall Stage 3A experiment remains planned. "
                "Frozen primitives are preserved beneath a deterministic analysis-only "
                "state hierarchy. No state-family combination, strategy filter, strategy "
                "performance, Validation, or OOS_BURNED result was produced."
            ),
            "warnings": [
                "Overall Stage 3A remains incomplete after key-level interaction characterization.",
                "No Validation or OOS_BURNED access is authorized or recorded.",
                "Descriptive candidate-state labels are not validated trading filters.",
                "Non-sweep REJECTION and TOUCH_ONLY states are sparse and remain descriptive.",
                "Step 5 does not combine key-level interaction with any other state family.",
            ],
        },
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    main()
