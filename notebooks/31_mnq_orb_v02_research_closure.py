"""Register the final MNQ ORB V0.2 research conclusion and close Stage 3A."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.experiment_registration import (  # noqa: E402
    ExperimentRun,
    finalize_experiment,
)


STAGE3A_EXPERIMENT_ID = "mnq_orb_v0_2_stage3a_conditional_state_characterization"
STAGE3C_EXPERIMENT_ID = "mnq_orb_v0_2_stage3c_combined_state_hypothesis"
NOTE_PATH = (
    PROJECT_ROOT
    / "experiments"
    / "projects"
    / "mnq_orb_v0_2"
    / "notes"
    / "mnq_orb_v0_2_final_development_research_conclusion.md"
)


def main() -> None:
    run = ExperimentRun(experiment_id=STAGE3A_EXPERIMENT_ID, project_root=PROJECT_ROOT)
    run.register_artifact(
        artifact_id="final_development_research_conclusion",
        artifact_type="research_conclusion_note",
        title="MNQ ORB V0.2 — Final DEVELOPMENT Research Conclusion",
        path=NOTE_PATH,
        mime_type="text/markdown",
        category="documentation",
        metadata={
            "partition": "DEVELOPMENT",
            "research_cycle_status": "PARKED_AS_RESEARCH_CANDIDATE",
            "hypothesis_id": "HYP-ORB-STATE-01",
            "hypothesis_classification": "POTENTIALLY_INFORMATIVE",
            "hypothesis_validated": False,
            "analysis_executed": False,
            "validation_or_oos_accessed": False,
        },
    )
    run.update(
        decision="revise",
        summary_metrics={
            "overall_stage3a_complete": True,
            "research_cycle_closed": True,
            "final_research_disposition": "PARKED_AS_RESEARCH_CANDIDATE",
            "final_hypothesis_id": "HYP-ORB-STATE-01",
            "final_hypothesis_classification": "POTENTIALLY_INFORMATIVE",
            "final_hypothesis_validated": False,
            "stage3c_experiment_id": STAGE3C_EXPERIMENT_ID,
            "five_session_result_status": "POST_HOC_OBSERVATION_NOT_SELECTED",
            "another_orb_cycle_authorized": False,
            "validation_or_oos_accessed": False,
            "reserved_data_exposed": False,
        },
        notes=(
            "Stage 3A and the MNQ ORB V0.2 research cycle are closed. The final "
            "disposition is PARKED_AS_RESEARCH_CANDIDATE. HYP-ORB-STATE-01 is "
            "POTENTIALLY_INFORMATIVE, UNVALIDATED, and PARKED. The 5-session "
            "result remains a post-hoc observation and was not selected as a rule."
        ),
        warnings=[
            "No Validation or OOS_BURNED data was accessed during research closure.",
            "The 5-session lookback must not be selected post hoc as a strategy rule.",
            "No V0.2 participation state, filter, or strategy version is approved.",
        ],
        future_hypotheses=[
            "The 5-session observation may be revisited only in a separately authorized future research cycle without treating it as a preselected rule."
        ],
    )
    finalize_experiment(
        STAGE3A_EXPERIMENT_ID,
        decision="revise",
        summary_metrics={
            "analysis_status": "COMPLETE_RESEARCH_CYCLE_PARKED",
        },
        notes=(
            "MNQ ORB V0.2 DEVELOPMENT research is complete and parked. The current "
            "PRINT ORB formulation lacks a sufficiently stable causal participation "
            "state to justify another strategy version."
        ),
        project_root=PROJECT_ROOT,
    )
    print(NOTE_PATH)
    print(STAGE3A_EXPERIMENT_ID)
    print("PARKED_AS_RESEARCH_CANDIDATE")


if __name__ == "__main__":
    main()
