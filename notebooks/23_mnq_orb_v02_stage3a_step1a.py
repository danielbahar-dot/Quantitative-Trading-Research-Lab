"""Build MNQ ORB V0.2 Stage-3A Step-1A artifacts on DEVELOPMENT only.

This runner joins frozen Stage-2 artifacts and adds only room to the next known
key level. It does not load Validation/OOS_BURNED, run performance analysis, or
register an experiment.
"""

from __future__ import annotations

from pathlib import Path
import json
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.mnq_orb_v02_stage3a import (  # noqa: E402
    build_stage3a_breakout_events,
    render_audit_report,
)


FROZEN_FEATURES = (
    PROJECT_ROOT
    / "experiments"
    / "projects"
    / "mnq_orb_v0_2"
    / "features"
    / "mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv"
)
FROZEN_OUTCOMES = (
    PROJECT_ROOT
    / "experiments"
    / "projects"
    / "mnq_orb_v0_2"
    / "features"
    / "mnq_orb_v0_2_stage2_completion_DEV_print_breakout_outcomes.csv"
)
OUTPUT_DIR = (
    PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "signals"
)
OUTPUT_CSV = OUTPUT_DIR / "mnq_orb_v0_2_stage3a_step1a_DEV_breakout_events.csv"
AUDIT_REPORT = OUTPUT_DIR / "mnq_orb_v0_2_stage3a_step1a_audit.md"


def main() -> None:
    features = pd.read_csv(FROZEN_FEATURES, low_memory=False)
    outcomes = pd.read_csv(FROZEN_OUTCOMES, low_memory=False)
    output, audit = build_stage3a_breakout_events(features, outcomes)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_CSV, index=False)
    AUDIT_REPORT.write_text(render_audit_report(output, audit), encoding="utf-8")

    print(json.dumps(audit, indent=2))
    print(f"Output CSV: {OUTPUT_CSV}")
    print(f"Audit report: {AUDIT_REPORT}")


if __name__ == "__main__":
    main()
