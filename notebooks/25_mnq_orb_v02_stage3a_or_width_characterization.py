"""Run MNQ ORB V0.2 Stage-3A Step-2 causal OR-width characterization."""

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
from src.experiments.mnq_orb_v02_width_characterization import (  # noqa: E402
    BAND_LABELS,
    EXPECTED_OR_MINUTES,
    LOOKBACKS,
    assert_development_input_path,
    characterize_or_width,
    render_report,
)


EXPERIMENT_ID = "mnq_orb_v0_2_stage3a_conditional_state_characterization"
SIGNAL_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "signals"
INPUT_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step1b_DEV_directional_states.csv"
MASTER_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step2_DEV_or_width_characterization.csv"
STABILITY_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step2_DEV_or_width_stability.csv"
DIRECTION_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step2_DEV_or_width_direction_breakdown.csv"
REPORT_MD = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step2_DEV_or_width_report.md"
MFE_PLOT = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step2_DEV_median_mfe_30m.png"
MAE_PLOT = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step2_DEV_median_mae_30m.png"


def main() -> None:
    assert_development_input_path(INPUT_CSV)
    events = pd.read_csv(INPUT_CSV, low_memory=False)
    if len(events) != 935:
        raise ValueError(f"Expected 935 Step-1B rows, found {len(events)}")

    master, stability, direction, relationships, audit = characterize_or_width(events)
    master.to_csv(MASTER_CSV, index=False)
    stability.to_csv(STABILITY_CSV, index=False)
    direction.to_csv(DIRECTION_CSV, index=False)
    REPORT_MD.write_text(
        render_report(master, direction, relationships, audit), encoding="utf-8"
    )
    _plot_clean_30m(master, "mfe", MFE_PLOT)
    _plot_clean_30m(master, "mae", MAE_PLOT)
    _register_outputs(audit, relationships)

    print(json.dumps(audit, indent=2))
    print(relationships.to_string(index=False))
    for path in (MASTER_CSV, STABILITY_CSV, DIRECTION_CSV, REPORT_MD, MFE_PLOT, MAE_PLOT):
        print(path)


def _plot_clean_30m(master: pd.DataFrame, measure: str, path: Path) -> None:
    metric = f"median_{measure}_pct"
    colors = {5: "#0072B2", 10: "#E69F00", 15: "#009E73", 20: "#CC79A7"}
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), sharey=True)
    for axis, duration in zip(axes, EXPECTED_OR_MINUTES):
        frame = master[
            (master["or_minutes"].astype(str) == str(duration))
            & (master["outcome_horizon"] == "30m")
        ]
        for lookback in LOOKBACKS:
            selected = frame[frame["lookback_sessions"] == lookback].copy()
            selected["_order"] = selected["percentile_band"].map(
                {band: index for index, band in enumerate(BAND_LABELS)}
            )
            selected = selected.sort_values("_order")
            axis.plot(
                range(1, 6),
                selected[metric].astype(float) * 100,
                marker="o",
                linewidth=1.8,
                label=f"{lookback}-session",
                color=colors[lookback],
            )
        axis.set_title(f"{duration}m OR")
        axis.set_xticks(range(1, 6), ["0-.2", ".2-.4", ".4-.6", ".6-.8", ".8-1"])
        axis.set_xlabel("Frozen causal OR-width percentile band")
        axis.grid(alpha=0.25)
    axes[0].set_ylabel(f"Median {measure.upper()} (% of breakout price)")
    axes[-1].legend(frameon=False, title="Lookback")
    fig.suptitle(
        f"MNQ ORB V0.2 — DEVELOPMENT ONLY — post-signal 30m median {measure.upper()}",
        fontsize=13,
    )
    fig.tight_layout()
    temporary_path = path.with_name(f".{path.stem}.tmp.png")
    fig.savefig(temporary_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    temporary_path.replace(path)


def _register_outputs(audit: dict, relationships: pd.DataFrame) -> None:
    shared_metadata = {
        "partition": "DEVELOPMENT",
        "analysis_step": "STAGE_3A_STEP_2",
        "state_family": "CAUSAL_OR_WIDTH_STATE",
        "strategy_performance": False,
        "validation_or_oos_accessed": False,
    }
    artifacts = (
        ("stage3a_step2_or_width_master", "analysis_table", "Step 2 OR-width master characterization", MASTER_CSV, "text/csv", "analysis"),
        ("stage3a_step2_or_width_stability", "stability_table", "Step 2 OR-width DEVELOPMENT-half stability", STABILITY_CSV, "text/csv", "analysis"),
        ("stage3a_step2_or_width_direction", "direction_breakdown", "Step 2 OR-width LONG/SHORT breakdown", DIRECTION_CSV, "text/csv", "analysis"),
        ("stage3a_step2_or_width_report", "research_report", "Step 2 causal OR-width characterization report", REPORT_MD, "text/markdown", "documentation"),
        ("stage3a_step2_or_width_mfe_plot", "plot", "Step 2 median MFE by causal OR-width band", MFE_PLOT, "image/png", "visualization"),
        ("stage3a_step2_or_width_mae_plot", "plot", "Step 2 median MAE by causal OR-width band", MAE_PLOT, "image/png", "visualization"),
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
            metadata=shared_metadata,
            project_root=PROJECT_ROOT,
        )

    update_experiment(
        EXPERIMENT_ID,
        {
            "summary_metrics": {
                "stage3a_step2_or_width_characterization_complete": True,
                "characterization_analysis_started": True,
                "overall_stage3a_complete": False,
                "step2_input_rows": audit["input_rows"],
                "step2_eligible_n_by_lookback": audit["eligible_n_by_lookback"],
                "step2_unavailable_n_by_lookback": audit["unavailable_n_by_lookback"],
                "step2_development_split": audit["development_split"],
                "step2_relationship_label_counts": {
                    str(label): int(count)
                    for label, count in relationships["classification"].value_counts().items()
                },
                "validation_or_oos_accessed": False,
            },
            "notes": (
                "Stage 3A Step 2 causal OR-width characterization is complete on "
                "DEVELOPMENT. The overall Stage 3A experiment remains planned; no "
                "filter, preferred lookback, strategy performance, Validation, or "
                "OOS_BURNED result was produced."
            ),
            "warnings": [
                "Overall Stage 3A remains incomplete after the OR-width family analysis.",
                "No Validation or OOS_BURNED access is authorized or recorded.",
                "Descriptive candidate-state labels are not validated trading filters.",
                "Signal-bar excursion remains chronology_unknown and is excluded from clean results.",
            ],
        },
        project_root=PROJECT_ROOT,
    )


if __name__ == "__main__":
    main()
