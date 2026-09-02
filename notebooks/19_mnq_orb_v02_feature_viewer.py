"""Launch the MNQ ORB V0.2 DEVELOPMENT feature-validation viewer."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.visualization.feature_validation_viewer import run_feature_validation_viewer  # noqa: E402


run_feature_validation_viewer(PROJECT_ROOT)
