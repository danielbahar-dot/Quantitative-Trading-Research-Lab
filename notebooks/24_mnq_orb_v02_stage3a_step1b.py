"""Build MNQ ORB V0.2 Stage-3A Step-1B directional states.

This DEVELOPMENT-only runner preserves every Step-1A row and field, adds only
the predeclared OR/breakout directional-state fields, and writes a construction
audit. It does not characterize outcomes, create buckets, or register/complete
an experiment.
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
    build_directional_state_events,
    render_step1b_audit_report,
)


SIGNAL_DIR = PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "signals"
STEP1A_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step1a_DEV_breakout_events.csv"
OUTPUT_CSV = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step1b_DEV_directional_states.csv"
AUDIT_REPORT = SIGNAL_DIR / "mnq_orb_v0_2_stage3a_step1b_audit.md"


def main() -> None:
    step1a = pd.read_csv(STEP1A_CSV, low_memory=False)
    output, audit = build_directional_state_events(step1a)

    output.to_csv(OUTPUT_CSV, index=False)
    AUDIT_REPORT.write_text(
        render_step1b_audit_report(output, audit), encoding="utf-8"
    )

    print(json.dumps(audit, indent=2))
    print(f"Output CSV: {OUTPUT_CSV}")
    print(f"Audit report: {AUDIT_REPORT}")


if __name__ == "__main__":
    main()
