from pathlib import Path
import unittest

from src.experiments.experiment_index import load_experiment_index
from src.visualization.research_dashboard import (
    CSV_PREVIEW_ROWS,
    VIEW_OPTIONS,
    compare_experiments,
    filter_experiment_index,
    run_dashboard,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ResearchDashboardTests(unittest.TestCase):
    def test_dashboard_is_read_only_and_has_required_views(self):
        self.assertTrue(callable(run_dashboard))
        self.assertEqual(
            VIEW_OPTIONS,
            ("Overview", "Experiments", "Strategy Versions", "Datasets / Partitions"),
        )
        self.assertEqual(CSV_PREVIEW_ROWS, 100)

    def test_experiment_filter_searches_gate_title_id_and_type(self):
        index = load_experiment_index(PROJECT_ROOT)
        result = filter_experiment_index(index, search="post-validation")
        self.assertEqual(result["gate"].tolist(), ["8A"])
        result = filter_experiment_index(index, partition="VALIDATION")
        self.assertEqual(result["gate"].tolist(), ["7"])

    def test_comparison_includes_only_common_metric_keys(self):
        result = compare_experiments(
            ["orb_gate6a_dev_print_static_r", "orb_gate6b_dev_fixed_target_stop"],
            PROJECT_ROOT,
        )
        self.assertEqual(len(result), 2)
        self.assertIn("configurations", result.columns)
        self.assertNotIn("baseline_controls_reproduced", result.columns)

    def test_streamlit_startup_smoke(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as error:
            self.skipTest(str(error))
        app = AppTest.from_file(str(PROJECT_ROOT / "notebooks" / "17_research_dashboard.py"), default_timeout=30)
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("MNQ ORB" in title.value for title in app.title))


if __name__ == "__main__":
    unittest.main()
