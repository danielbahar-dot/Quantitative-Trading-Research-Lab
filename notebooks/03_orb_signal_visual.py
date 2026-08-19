"""Run the interactive ORB Research Viewer v0.2."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visualization.research_viewer_app import (  # noqa: E402
    ViewerDefaults,
    run_research_viewer_app,
)


# ============================================================
# STARTUP DEFAULTS - all of these can also be changed in the browser
# ============================================================

START_DATE = "2025-01-06"  # One session: use the same start and end date.
END_DATE = "2025-01-08"    # Multiple sessions: use an inclusive date range.

OR_MINUTES = 15             # Choose 5, 10, 15, or 30.
BREAKOUT_TYPE = "PRINT"     # Choose PRINT or CLOSE.

START_TIME = "09:25"        # Intraday chart window, Eastern Time.
END_TIME = "11:45"


# Validated inputs used by the viewer. Usually no changes are needed here.
DATA_FILE = PROJECT_ROOT / "data" / "MNQ_raw_cleaned_ET.csv"
OR_FILE = PROJECT_ROOT / "data" / "processed" / "mnq_or_levels.csv"
PORT = 8050


def main() -> None:
    run_research_viewer_app(
        DATA_FILE,
        OR_FILE,
        defaults=ViewerDefaults(
            start_date=START_DATE,
            end_date=END_DATE,
            or_minutes=OR_MINUTES,
            breakout_type=BREAKOUT_TYPE,
            start_time=START_TIME,
            end_time=END_TIME,
        ),
        port=PORT,
    )


if __name__ == "__main__":
    main()
