import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from src.experiments.mnq_orb_v02_features import (
    apply_human_review_decisions,
    build_breakout_outcomes,
    build_feature_audit,
    build_representative_review_queue,
    build_window_availability_audit,
)
from src.features.market_context import (
    WindowDefinition,
    add_causal_width_history,
    calculate_or_context,
    expected_bar_end_index,
    gap_context,
    level_interaction,
    ny_open_gap_context,
    summarize_window,
)
from src.visualization.feature_validation_viewer import (
    LEVEL_PRESETS,
    _scaled_numeric_range,
    _scaled_time_range,
    build_feature_validation_figure,
    liquidity_path_panel,
    machine_classification_panel,
    representative_review_panel,
    viewer_time_bounds,
)


ROOT = Path(__file__).resolve().parents[1]
ET = "America/New_York"


def make_owned_session(session_date: str, base: float = 100.0) -> pd.DataFrame:
    day = pd.Timestamp(session_date)
    index = pd.date_range(
        day - pd.Timedelta(days=1) + pd.Timedelta(hours=18, minutes=1),
        day + pd.Timedelta(hours=17),
        freq="min", tz=ET,
    )
    offset = np.arange(len(index), dtype=float) * 0.01
    frame = pd.DataFrame({
        "session_date": day.date(), "contract": "MNQ TEST",
        "open": base + offset, "high": base + offset + .75,
        "low": base + offset - .75, "close": base + offset + .25,
        "volume": 10,
    }, index=index)
    return frame


def window_config():
    return json.loads(
        (ROOT / "config" / "features" / "mnq_orb_v0_2_preopen_windows.json").read_text(encoding="utf-8")
    )


class FeatureWindowTests(unittest.TestCase):
    def test_session_windows_are_human_approved_and_rename_is_migratable(self):
        config = window_config()
        windows = {item["window_id"]: item for item in config["windows"]}
        for window_id in ("asia_kill_zone", "london_kill_zone", "ny_premarket", "overnight_context_2000_0900"):
            self.assertEqual(
                windows[window_id]["approval_status"],
                "HUMAN_VALIDATED_AND_FROZEN",
            )
        self.assertEqual(config["migration"]["combined_preopen"], "overnight_context_2000_0900")
        self.assertIn("combined_preopen", windows["overnight_context_2000_0900"]["legacy_window_ids"])

    def test_ny_premarket_uses_0701_through_0900_bar_end_labels(self):
        definition = WindowDefinition("ny_premarket", pd.Timestamp("07:00").time(), pd.Timestamp("09:00").time())
        expected = expected_bar_end_index(pd.Timestamp("2025-01-06").date(), definition)
        self.assertEqual(len(expected), 120)
        self.assertEqual(expected[0], pd.Timestamp("2025-01-06 07:01", tz=ET))
        self.assertEqual(expected[-1], pd.Timestamp("2025-01-06 09:00", tz=ET))
        self.assertNotIn(pd.Timestamp("2025-01-06 07:00", tz=ET), expected)

    def test_overnight_session_ownership_uses_prior_calendar_reopen(self):
        definition = WindowDefinition("overnight", pd.Timestamp("18:00").time(), pd.Timestamp("09:30").time(), -1)
        expected = expected_bar_end_index(pd.Timestamp("2025-01-06").date(), definition)
        self.assertEqual(expected[0], pd.Timestamp("2025-01-05 18:01", tz=ET))
        self.assertEqual(expected[-1], pd.Timestamp("2025-01-06 09:30", tz=ET))
        self.assertEqual(len(expected), 930)

    def test_incomplete_window_is_unavailable_not_fabricated(self):
        session = make_owned_session("2025-01-06").drop(pd.Timestamp("2025-01-06 08:00", tz=ET))
        definition = WindowDefinition("ny_premarket", pd.Timestamp("07:00").time(), pd.Timestamp("09:00").time())
        summary = summarize_window(session, pd.Timestamp("2025-01-06").date(), definition)
        self.assertFalse(summary["feature_available"])
        self.assertEqual(summary["observed_bars"], 119)
        self.assertTrue(pd.isna(summary["range_points"]))


class OpeningAuctionFeatureTests(unittest.TestCase):
    def test_or_context_uses_exact_15_20_30_bar_end_windows(self):
        session = make_owned_session("2025-01-06")
        session.loc[pd.Timestamp("2025-01-06 09:30", tz=ET), ["high", "low"]] = [9999, -9999]
        for duration in (15, 20, 30):
            with self.subTest(duration=duration):
                context = calculate_or_context(session, pd.Timestamp("2025-01-06").date(), duration)
                self.assertTrue(context["or_feature_available"])
                self.assertEqual(context["or_observed_bars"], duration)
                self.assertEqual(context["or_first_bar_end"], pd.Timestamp("2025-01-06 09:31", tz=ET))
                self.assertEqual(context["or_last_bar_end"], pd.Timestamp("2025-01-06 09:30", tz=ET) + pd.Timedelta(minutes=duration))
                self.assertLess(context["or_high"], 9999)
                self.assertGreater(context["or_low"], -9999)
                self.assertAlmostEqual(context["or_width_points"], context["or_high"] - context["or_low"])
                self.assertAlmostEqual(context["or_width_pct"], context["or_width_points"] / context["or_reference_price"])
                self.assertTrue(0 <= context["or_efficiency"] <= 1)
                self.assertTrue(0 <= context["or_clv"] <= 1)

    def test_historical_percentile_excludes_current_and_requires_full_warmup(self):
        rows = []
        for index in range(22):
            rows.append({"session_date": pd.Timestamp("2024-06-21").date() + pd.Timedelta(days=index), "or_minutes": 15, "or_width_points": float(index + 1)})
        result = add_causal_width_history(pd.DataFrame(rows), lookbacks=[20])
        self.assertFalse(result.iloc[19]["or_width_hist_20_available"])
        self.assertTrue(result.iloc[20]["or_width_hist_20_available"])
        self.assertEqual(result.iloc[20]["or_width_hist_20_sample_count"], 20)
        self.assertEqual(result.iloc[20]["or_width_hist_20_percentile"], 1.0)
        original = result.iloc[20]["or_width_hist_20_percentile"]
        rows[-1]["or_width_points"] = 1_000_000.0
        changed = add_causal_width_history(pd.DataFrame(rows), lookbacks=[20])
        self.assertEqual(changed.iloc[20]["or_width_hist_20_percentile"], original)

    def test_approved_width_history_family_uses_5_10_15_20_prior_sessions(self):
        rows = [
            {"session_date": pd.Timestamp("2024-06-21").date() + pd.Timedelta(days=index), "or_minutes": 15, "or_width_points": float(index + 1)}
            for index in range(22)
        ]
        result = add_causal_width_history(pd.DataFrame(rows))
        for lookback in (5, 10, 15, 20):
            with self.subTest(lookback=lookback):
                self.assertFalse(result.iloc[lookback - 1][f"or_width_hist_{lookback}_available"])
                self.assertTrue(result.iloc[lookback][f"or_width_hist_{lookback}_available"])
                self.assertEqual(result.iloc[lookback][f"or_width_hist_{lookback}_sample_count"], lookback)


class ContextLogicTests(unittest.TestCase):
    def test_gap_uses_prior_1700_close_and_current_1801_open(self):
        prior = make_owned_session("2025-01-05", 100)
        current = make_owned_session("2025-01-06", 110)
        prior.loc[pd.Timestamp("2025-01-05 17:00", tz=ET), "close"] = 100
        current.loc[pd.Timestamp("2025-01-05 18:01", tz=ET), "open"] = 110
        current.loc[pd.Timestamp("2025-01-06 08:00", tz=ET), "low"] = 99
        gap = gap_context(prior, current, pd.Timestamp("2025-01-06").date())
        self.assertTrue(gap["globex_reopen_gap_feature_available"])
        self.assertEqual(gap["globex_reopen_gap_points"], 10)
        self.assertAlmostEqual(gap["globex_reopen_gap_pct"], .10)
        self.assertEqual(gap["globex_reopen_gap_fill_state_at_0930"], "FILLED")

    def test_ny_open_gap_uses_prior_1614_close_and_current_0931_open(self):
        prior = make_owned_session("2025-01-05", 100)
        current = make_owned_session("2025-01-06", 110)
        prior.loc[pd.Timestamp("2025-01-05 16:14", tz=ET), "close"] = 101.25
        current.loc[pd.Timestamp("2025-01-06 09:31", tz=ET), "open"] = 103.50
        gap = ny_open_gap_context(prior, current, pd.Timestamp("2025-01-06").date())
        self.assertTrue(gap["ny_open_gap_feature_available"])
        self.assertEqual(gap["ny_open_gap_prior_1614_close"], 101.25)
        self.assertEqual(gap["ny_open_reference_price"], 103.50)
        self.assertEqual(gap["ny_open_gap_points"], 2.25)
        self.assertEqual(gap["ny_open_reference_timestamp"], pd.Timestamp("2025-01-06 09:31", tz=ET))

    def test_ny_open_gap_does_not_substitute_for_missing_1614_bar(self):
        prior = make_owned_session("2025-01-05").drop(pd.Timestamp("2025-01-05 16:14", tz=ET))
        current = make_owned_session("2025-01-06")
        gap = ny_open_gap_context(prior, current, pd.Timestamp("2025-01-06").date())
        self.assertFalse(gap["ny_open_gap_feature_available"])
        self.assertEqual(gap["ny_open_gap_missing_reason"], "MISSING_PRIOR_1614_BAR")
        self.assertTrue(pd.isna(gap["ny_open_gap_points"]))

    def test_touch_sweep_close_through_and_rejection_are_deterministic(self):
        swept = level_interaction(level=100, or_open=99, or_high=101, or_low=98, or_close=99.5, or_mid=99.5)
        self.assertTrue(swept["touched"])
        self.assertTrue(swept["traded_through"])
        self.assertTrue(swept["swept"])
        self.assertTrue(swept["rejected"])
        self.assertFalse(swept["closed_through"])
        closed = level_interaction(level=100, or_open=99, or_high=102, or_low=98, or_close=101, or_mid=100)
        self.assertTrue(closed["closed_through"])
        self.assertFalse(closed["swept"])

    def test_key_level_event_hierarchy_edge_cases(self):
        exact_touch = level_interaction(level=100, or_open=99, or_high=100, or_low=98, or_close=99.5, or_mid=99)
        self.assertTrue(exact_touch["touched"])
        self.assertFalse(exact_touch["traded_through"])
        self.assertTrue(exact_touch["rejected"])
        at_level = level_interaction(level=100, or_open=100, or_high=101, or_low=99, or_close=100.5, or_mid=100)
        self.assertEqual(at_level["start_side"], "AT")
        self.assertTrue(at_level["touched"])
        self.assertFalse(at_level["traded_through"])
        already_beyond = level_interaction(level=100, or_open=101, or_high=102, or_low=99, or_close=101, or_mid=100.5)
        self.assertTrue(already_beyond["traded_through"])
        self.assertTrue(already_beyond["swept"])
        repeated_crossing = level_interaction(level=100, or_open=99, or_high=102, or_low=98, or_close=99, or_mid=100)
        self.assertTrue(repeated_crossing["swept"])
        self.assertTrue(repeated_crossing["traded_through"])
        self.assertTrue(repeated_crossing["rejected"])
        self.assertFalse(repeated_crossing["closed_through"])

    def test_audit_has_one_row_per_session_duration_and_prior_rth_is_causal(self):
        prices = pd.concat([make_owned_session("2025-01-05", 100), make_owned_session("2025-01-06", 110)]).sort_index()
        audit = build_feature_audit(prices, window_config(), durations=[15, 20, 30], lookbacks=[20])
        self.assertEqual(len(audit), 6)
        self.assertFalse(audit.duplicated(["session_date", "or_minutes"]).any())
        second = audit.loc[audit["session_date"].eq(pd.Timestamp("2025-01-06").date())]
        prior = prices.loc[prices["session_date"].eq(pd.Timestamp("2025-01-05").date())].between_time("09:31", "16:00")
        prior_full = prices.loc[prices["session_date"].eq(pd.Timestamp("2025-01-05").date())]
        self.assertTrue(second["previous_day_feature_available"].all())
        self.assertTrue((second["previous_day_high"] == prior_full["high"].max()).all())
        self.assertTrue((second["previous_day_low"] == prior_full["low"].min()).all())
        self.assertTrue((second["previous_day_close"] == prior_full.loc[pd.Timestamp("2025-01-05 17:00", tz=ET), "close"]).all())
        self.assertTrue(second["previous_rth_feature_available"].all())
        self.assertTrue((second["previous_rth_high"] == prior["high"].max()).all())
        self.assertTrue(second["ny_premarket_feature_available"].all())
        self.assertTrue(second["row_feature_complete"].all())

    def test_previous_day_requires_only_completed_prior_futures_session_data(self):
        prior = make_owned_session("2025-01-05").drop(pd.Timestamp("2025-01-04 20:00", tz=ET))
        current = make_owned_session("2025-01-06")
        audit = build_feature_audit(pd.concat([prior, current]).sort_index(), window_config(), durations=[15], lookbacks=[5])
        row = audit.loc[audit["session_date"].eq(pd.Timestamp("2025-01-06").date())].iloc[0]
        self.assertFalse(row["previous_day_feature_available"])
        self.assertEqual(row["previous_day_missing_reason"], "INCOMPLETE_WINDOW")
        self.assertTrue(pd.isna(row["previous_day_high"]))

    def test_future_session_changes_do_not_change_prior_features(self):
        first = make_owned_session("2025-01-05", 100)
        second = make_owned_session("2025-01-06", 110)
        third = make_owned_session("2025-01-07", 120)
        base = build_feature_audit(pd.concat([first, second, third]).sort_index(), window_config(), durations=[15], lookbacks=[20])
        third.loc[:, ["open", "high", "low", "close"]] += 10000
        changed = build_feature_audit(pd.concat([first, second, third]).sort_index(), window_config(), durations=[15], lookbacks=[20])
        columns = [name for name in base.columns if name not in {"contract"}]
        pd.testing.assert_series_equal(base.iloc[1][columns], changed.iloc[1][columns], check_names=False)


class OutcomeAndViewerTests(unittest.TestCase):
    def test_outcomes_start_after_print_signal_bar_and_use_future_prefix(self):
        session_date = pd.Timestamp("2025-01-06").date()
        index = pd.date_range("2025-01-06 09:31", "2025-01-06 16:00", freq="min", tz=ET)
        prices = pd.DataFrame({
            "session_date": session_date, "contract": "MNQ TEST", "open": 95.0,
            "high": 99.0, "low": 91.0, "close": 95.0, "volume": 10,
        }, index=index)
        prices.loc[pd.Timestamp("2025-01-06 09:46", tz=ET), ["high", "low", "close"]] = [1000, 95, 101]
        for minute, high, low in ((47, 102, 98), (48, 103, 97), (49, 104, 96), (50, 105, 95), (51, 104, 94)):
            prices.loc[pd.Timestamp(f"2025-01-06 09:{minute}", tz=ET), ["high", "low"]] = [high, low]
        features = pd.DataFrame([{
            "session_date": session_date, "or_minutes": 15, "or_feature_available": True,
            "or_high": 100.0, "or_low": 90.0, "or_mid": 95.0,
        }])
        outcomes, _ = build_breakout_outcomes(prices, features, durations=[15], horizons=[5])
        long = outcomes.loc[outcomes["breakout_direction"].eq("LONG")].iloc[0]
        self.assertEqual(long["post_signal_bar_5m_mfe_points"], 5.0)
        self.assertEqual(long["post_signal_bar_5m_mae_points"], 6.0)
        self.assertNotEqual(long["post_signal_bar_5m_mfe_points"], 900.0)
        self.assertEqual(long["signal_bar_favorable_excursion_points"], 900.0)
        self.assertEqual(long["signal_bar_adverse_excursion_points"], 5.0)
        self.assertTrue(long["signal_bar_chronology_unknown"])
        self.assertTrue(all(name.startswith(("post_signal_bar_", "signal_bar_")) for name in outcomes.columns if "mfe" in name or "mae" in name or "excursion" in name))

    def test_overnight_unavailability_audit_classifies_missing_source_bars(self):
        first = make_owned_session("2025-01-05")
        second = make_owned_session("2025-01-06").drop(pd.Timestamp("2025-01-06 03:00", tz=ET))
        audit = build_window_availability_audit(pd.concat([first, second]).sort_index(), window_config())
        audit = audit.loc[audit["session_date"].eq(pd.Timestamp("2025-01-06").date())]
        self.assertEqual(set(audit["feature_window"]), {"overnight", "overnight_context_2000_0900"})
        self.assertTrue(audit["unavailable_reason"].eq("MISSING_SOURCE_BARS").all())
        self.assertTrue((audit["observed_bars"] < audit["expected_bars"]).all())

    def test_feature_viewer_contains_levels_but_no_performance(self):
        session = make_owned_session("2025-01-06")
        audit = build_feature_audit(session, window_config(), durations=[15], lookbacks=[20])
        figure = build_feature_validation_figure(session.between_time("07:00", "10:30"), audit.iloc[0], selected_levels=["OR High", "NY Pre-Market High"])
        self.assertFalse(figure.layout.meta["strategy_performance"])
        self.assertEqual(figure.layout.meta["ny_pm_meaning"], "New York pre-market")
        self.assertEqual(figure.layout.dragmode, "pan")
        self.assertFalse(figure.layout.xaxis.fixedrange)
        self.assertFalse(figure.layout.yaxis.fixedrange)
        self.assertIn("OR High", [trace.name for trace in figure.data])
        self.assertIn("NY Pre-Market High", [trace.name for trace in figure.data])
        or_high_trace = next(trace for trace in figure.data if trace.name == "OR High")
        self.assertEqual(or_high_trace.mode, "lines")
        self.assertEqual(or_high_trace.legendgroup, "feature-levels")
        self.assertNotIn("result_r", figure.to_json().lower())

    def test_viewer_presets_end_time_and_prior_reference_context(self):
        self.assertEqual(LEVEL_PRESETS["LONDON"], ["OR High", "OR Low", "OR Mid", "London High", "London Low"])
        self.assertIn("Previous Day High", LEVEL_PRESETS["PREVIOUS DAY"])
        start, end = viewer_time_bounds("2025-01-06", -1, pd.Timestamp("16:45").time(), pd.Timestamp("16:00").time())
        self.assertEqual(start, pd.Timestamp("2025-01-05 16:45", tz=ET))
        self.assertEqual(end, pd.Timestamp("2025-01-06 16:00", tz=ET))
        self.assertLess(pd.Timestamp("2025-01-05 17:00", tz=ET), end)

    def test_machine_classification_panel_exposes_neutral_event_hierarchy(self):
        session = make_owned_session("2025-01-06")
        audit = build_feature_audit(session, window_config(), durations=[15], lookbacks=[5])
        panel = machine_classification_panel(audit.iloc[0], "NY Pre-Market High")
        self.assertEqual(
            panel["Field"].tolist(),
            ["Reference level", "Reference price", "OR high", "OR low", "OR close", "OR open side", "TOUCH", "TRADE_THROUGH", "CLOSE_THROUGH", "REJECT", "SWEEP"],
        )

    def test_overnight_labels_explain_the_two_distinct_windows(self):
        overnight = LEVEL_PRESETS["OVERNIGHT"]
        self.assertIn("Overnight High (full Globex 18:00-09:30)", overnight)
        self.assertIn("Overnight Context High (20:00-09:00)", overnight)

    def test_liquidity_path_panel_is_plain_language_and_not_or_interaction(self):
        row = pd.Series({
            "asia_high": 110, "asia_low": 90,
            "london_high": 111, "london_low": 95,
            "ny_premarket_high": 109, "ny_premarket_low": 89,
            "london_took_asia_available": True,
            "london_took_asia_high": True, "london_took_asia_low": False,
            "london_took_asia_state": "HIGH_ONLY",
            "ny_premarket_took_london_available": True,
            "ny_premarket_took_london_high": False, "ny_premarket_took_london_low": True,
            "ny_premarket_took_london_state": "LOW_ONLY",
            "ny_premarket_took_asia_available": True,
            "ny_premarket_took_asia_high": False, "ny_premarket_took_asia_low": True,
            "ny_premarket_took_asia_state": "LOW_ONLY",
        })
        panel = liquidity_path_panel(row)
        self.assertEqual(panel["State"].tolist(), ["HIGH_ONLY", "LOW_ONLY", "LOW_ONLY"])
        self.assertIn("exceeded the Asia high", panel.iloc[0]["Plain-language meaning"])

    def test_axis_ranges_scale_independently(self):
        start = pd.Timestamp("2025-01-06 07:00", tz=ET)
        end = pd.Timestamp("2025-01-06 11:00", tz=ET)
        full_x = _scaled_time_range(start, end, 1.0)
        zoomed_x = _scaled_time_range(start, end, .8)
        self.assertLess(zoomed_x[1] - zoomed_x[0], full_x[1] - full_x[0])
        full_y = _scaled_numeric_range(100, 200, 1.0)
        expanded_y = _scaled_numeric_range(100, 200, 1.25)
        self.assertGreater(expanded_y[1] - expanded_y[0], full_y[1] - full_y[0])
        self.assertEqual(full_x, _scaled_time_range(start, end, 1.0))


class Stage2CompletionArtifactTests(unittest.TestCase):
    def test_review_queue_identifies_exact_trigger_and_human_decisions(self):
        feature_dir = ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "features"
        features = pd.read_csv(feature_dir / "mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv")
        availability = pd.read_csv(feature_dir / "mnq_orb_v0_2_stage2_completion_DEV_overnight_availability_audit.csv")
        queue = build_representative_review_queue(features, availability)

        previous_day = queue.loc[queue["review_case"].eq("PREVIOUS_DAY_LEVEL_TOUCH")].iloc[0]
        self.assertEqual(previous_day["trigger_id"], "previous_day_high")
        self.assertEqual(previous_day["reference_price"], 19981.0)
        self.assertTrue(previous_day["touch"])
        self.assertTrue(previous_day["trade_through"])
        self.assertFalse(previous_day["close_through"])
        self.assertTrue(previous_day["reject"])
        self.assertTrue(previous_day["sweep"])

        london = queue.loc[queue["review_case"].eq("LONDON_INTERACTION")].iloc[0]
        self.assertEqual(london["trigger_id"], "london_low")
        self.assertEqual(london["reference_price"], 19947.5)
        path = queue.loc[queue["review_case"].eq("LIQUIDITY_PATH_SEQUENCE")].iloc[0]
        self.assertEqual(path["trigger_id"], "london_took_asia")
        self.assertEqual(path["liquidity_path_state"], "HIGH_ONLY")
        self.assertTrue(path["took_earlier_high"])
        self.assertFalse(path["took_earlier_low"])
        self.assertIn("London took Asia", path["classification_summary"])

        decisions = json.loads(
            (ROOT / "config" / "features" / "mnq_orb_v0_2_stage2_human_reviews.json").read_text(encoding="utf-8")
        )
        reviewed = apply_human_review_decisions(queue, decisions["decisions"])
        self.assertEqual(int(reviewed["human_review_status"].eq("PASS").sum()), 14)
        self.assertEqual(int(reviewed["human_review_status"].eq("PENDING_HUMAN_REVIEW").sum()), 0)
        review_panel = representative_review_panel(previous_day)
        self.assertIn("trigger_label", review_panel["Field"].tolist())

    def test_completion_record_is_linked_registered_and_development_only(self):
        record_path = ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "records" / "mnq_orb_v0_2_stage2_feature_validation_completion.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["lineage"]["parent_experiment_ids"], ["mnq_orb_v0_2_stage2_feature_validation"])
        artifact_ids = {item["artifact_id"] for item in record["artifacts"]}
        self.assertTrue({"feature_audit", "outcome_contract", "availability_audit", "representative_review", "research_ideas"}.issubset(artifact_ids))
        index = json.loads((ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "experiment_index.json").read_text(encoding="utf-8"))
        self.assertIn(record["experiment_id"], {item["experiment_id"] for item in index["records"]})
        feature_path = ROOT / "experiments" / "projects" / "mnq_orb_v0_2" / "features" / "mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv"
        features = pd.read_csv(feature_path, usecols=["session_date"])
        dates = pd.to_datetime(features["session_date"])
        self.assertGreaterEqual(dates.min(), pd.Timestamp("2024-06-21"))
        self.assertLessEqual(dates.max(), pd.Timestamp("2025-06-30"))

    def test_stage2_freeze_is_14_of_14_and_reserved_data_was_not_accessed(self):
        project_dir = ROOT / "experiments" / "projects" / "mnq_orb_v0_2"
        record = json.loads(
            (project_dir / "records" / "mnq_orb_v0_2_stage2_feature_freeze_approval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["decision"], "freeze")
        self.assertEqual(record["research_stage"], "STAGE_2_FEATURES")
        self.assertEqual(record["lineage"]["parent_experiment_ids"], [
            "mnq_orb_v0_2_stage2_feature_validation_completion"
        ])
        self.assertEqual(record["scope"]["partition"], "DEVELOPMENT")
        self.assertFalse(record["reserved_data_exposed"])
        self.assertEqual(record["summary_metrics"]["representative_review_passed"], 14)
        self.assertEqual(record["summary_metrics"]["representative_review_pending"], 0)
        self.assertFalse(record["summary_metrics"]["validation_or_oos_accessed"])

        queue = pd.read_csv(
            project_dir / "features" / "mnq_orb_v0_2_stage2_final_human_review_queue.csv"
        )
        self.assertEqual(len(queue), 14)
        self.assertTrue(queue["human_review_status"].eq("PASS").all())
        self.assertFalse(queue["trigger_id"].isna().any())
        clean = queue.loc[queue["review_case"].eq("CLEAN_TRADE_THROUGH")].iloc[0]
        self.assertEqual(clean["trigger_id"], "previous_day_high")
        self.assertTrue(clean["trade_through"])
        self.assertTrue(clean["close_through"])
        self.assertFalse(clean["reject"])

        manifest = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        version = manifest["strategy_versions"][0]
        self.assertEqual(version["lifecycle_status"], "FEATURES_VALIDATED_AND_FROZEN")
        self.assertTrue(version["approved_for_next_phase"])


if __name__ == "__main__":
    unittest.main()
