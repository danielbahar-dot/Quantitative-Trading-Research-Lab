"""M5B ORB Market Context compatibility tests.

Unit tests use synthetic bars.  The frozen-oracle parity test reads the local
(Git-ignored) DEVELOPMENT partition and skips with an explicit reason if it is
absent.
"""

from datetime import date, time, timedelta
import json
import math
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from src.data.sessions import load_session_spec, previous_expected_session
from src.experiments.orb_market_context_compat import (
    COMPATIBILITY,
    GENERIC,
    LEGACY_PREVIOUS_SESSION_PREFIXES,
    ORB_CONTEXT_SOURCES,
    ORB_SUMMARY_KEYS,
    assert_orb_window_config_matches,
    load_orb_compatibility_registry,
    orb_window_summaries,
    previous_available_session_legacy_orb,
    to_orb_window_summary,
)
from src.features.market_context import WindowDefinition, load_context_windows, summarize_window
from src.features.session_context import (
    MarketContextError,
    PREVIOUS_DAY_CONTEXT_ID,
    build_market_context,
    load_market_context_windows,
)

ROOT = Path(__file__).resolve().parents[1]
TZ = "America/New_York"
SPEC = load_session_spec()
MON, TUE, WED, THU = (date(2026, 9, day) for day in (21, 22, 23, 24))
FROZEN_AUDIT = ROOT / "experiments/projects/mnq_orb_v0_2/features/mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv"
DEV_PARTITION = ROOT / "data/processed/MNQ_raw_cleaned_ET_DEVELOPMENT.csv"


def orb_config() -> dict:
    return json.loads((ROOT / "config/features/mnq_orb_v0_2_preopen_windows.json").read_text(encoding="utf-8"))


def session(day: date, base: float = 100.0) -> pd.DataFrame:
    start = pd.Timestamp.combine(day - timedelta(days=1), time(18, 0)).tz_localize(TZ)
    labels = pd.date_range(start + pd.Timedelta(minutes=1), pd.Timestamp.combine(day, time(17, 0)).tz_localize(TZ), freq="min")
    wave = base + np.sin(np.arange(len(labels)) / 37.0) * 5
    return pd.DataFrame(
        {"session_date": day, "contract": "MNQ TEST", "open": wave, "high": wave + 1.25,
         "low": wave - 0.75, "close": wave + 0.25, "volume": 10},
        index=pd.DatetimeIndex(labels, name="timestamp_et"),
    )


def legacy_summary(rows: pd.DataFrame, day: date, window: WindowDefinition) -> dict:
    return summarize_window(rows, day, window)


def assert_summary_equal(test: unittest.TestCase, actual: dict, expected: dict, label: str):
    test.assertEqual(list(actual), list(expected), label)
    for key in expected:
        a, b = actual[key], expected[key]
        if isinstance(b, float) and math.isnan(b):
            test.assertTrue(isinstance(a, float) and math.isnan(a), f"{label}.{key}: {a!r} != NaN")
        elif b is pd.NaT or (b is not None and not isinstance(b, (str, bool, float, int, np.integer)) and pd.isna(b)):
            test.assertTrue(pd.isna(a), f"{label}.{key}: {a!r} != NaT")
        else:
            test.assertEqual(a, b, f"{label}.{key}")


class GenericReuseTests(unittest.TestCase):
    def test_orb_consumes_generic_definitions_where_identical(self):
        generic = load_market_context_windows(SPEC)
        for prefix in ("asia", "london", "ny_premarket", "overnight_context_2000_0900", "previous_rth", "previous_day"):
            with self.subTest(prefix):
                registry, context_id, _ = ORB_CONTEXT_SOURCES[prefix]
                self.assertEqual(registry, GENERIC)
                self.assertIsNotNone(generic.get(context_id))
        self.assertEqual(ORB_CONTEXT_SOURCES["overnight"][:2], (COMPATIBILITY, "orb_overnight_1800_0930"))
        self.assertEqual(ORB_CONTEXT_SOURCES["previous_rth"][1], "previous_rth")
        self.assertEqual(generic.get("previous_rth").window_id, "rth_0930_1600")

    def test_compatibility_registry_holds_only_genuinely_different_definitions(self):
        compat_ids = {definition.context_id for definition in load_orb_compatibility_registry(SPEC).contexts}
        self.assertEqual(compat_ids - {PREVIOUS_DAY_CONTEXT_ID}, {"orb_overnight_1800_0930"})
        generic_ids = {definition.context_id for definition in load_market_context_windows(SPEC).contexts}
        self.assertFalse(any(context_id.startswith("orb_") for context_id in generic_ids))
        self.assertIn("overnight_context_2000_0900", generic_ids)  # single, generic implementation
        self.assertNotIn("overnight_context_2000_0900", compat_ids)

    def test_frozen_orb_window_config_matches_catalog_and_drift_is_rejected(self):
        generic, compat = load_market_context_windows(SPEC), load_orb_compatibility_registry(SPEC)
        assert_orb_window_config_matches(orb_config(), generic, compat)
        drifted = orb_config()
        next(item for item in drifted["windows"] if item["window_id"] == "asia_kill_zone")["start_time_et"] = "20:30"
        with self.assertRaises(MarketContextError):
            assert_orb_window_config_matches(drifted, generic, compat)


class LegacyAdapterTests(unittest.TestCase):
    def test_previous_available_session_is_explicitly_legacy(self):
        dataset = [MON, WED]  # Tuesday absent
        self.assertEqual(previous_available_session_legacy_orb(WED, dataset, SPEC).trading_date, MON)
        self.assertIsNone(previous_available_session_legacy_orb(MON, dataset, SPEC))
        self.assertEqual(previous_expected_session(WED, SPEC).trading_date, TUE)  # generic default unchanged

    def test_legacy_overnight_is_1800_0930(self):
        prices = pd.concat([session(MON), session(TUE)])
        summaries = orb_window_summaries(prices, orb_config(), SPEC)
        overnight = summaries[TUE]["overnight"]
        self.assertEqual(overnight["expected_bars"], 930)
        self.assertEqual(overnight["last_bar_end"], pd.Timestamp("2026-09-22 09:30", tz=TZ))
        generic = build_market_context(prices, SPEC, instrument_id="MNQ", context_ids=["overnight_1800_0700"])
        self.assertEqual(int(generic.iloc[-1]["expected_count"]), 780)  # generic Overnight untouched


class SchemaAdapterTests(unittest.TestCase):
    def record(self, **overrides):
        base = {
            "window_start": pd.Timestamp("2026-09-21 20:00", tz=TZ), "window_end": pd.Timestamp("2026-09-22 00:00", tz=TZ),
            "expected_count": 240, "observed_count": 240, "is_complete": True, "is_available": True,
            "observed_open": 100.0, "observed_high": 104.0, "observed_low": 99.0, "observed_close": 102.0,
            "high_at": pd.Timestamp("2026-09-21 21:00", tz=TZ), "low_at": pd.Timestamp("2026-09-21 22:00", tz=TZ),
        }
        base.update(overrides)
        return base

    def test_complete_record_maps_to_orb_schema(self):
        summary = to_orb_window_summary(self.record(), "asia_kill_zone")
        self.assertEqual(tuple(summary), ORB_SUMMARY_KEYS)
        self.assertTrue(summary["feature_available"])
        self.assertEqual(summary["missing_reason"], "")
        self.assertEqual(summary["first_bar_end"], pd.Timestamp("2026-09-21 20:01", tz=TZ))
        self.assertEqual((summary["range_points"], summary["net_move_points"], summary["direction"]), (5.0, 2.0, "UP"))
        self.assertAlmostEqual(summary["efficiency"], 0.4)
        self.assertEqual(summary["range_pct"], 5.0 / 100.0)

    def test_incomplete_and_no_prior_session(self):
        incomplete = to_orb_window_summary(self.record(observed_count=239, is_complete=False, is_available=False), "asia_kill_zone")
        self.assertFalse(incomplete["feature_available"])
        self.assertEqual(incomplete["missing_reason"], "INCOMPLETE_WINDOW")
        self.assertTrue(math.isnan(incomplete["high"]) and incomplete["direction"] is None and incomplete["high_timestamp"] is pd.NaT)
        no_prior = to_orb_window_summary(self.record(observed_count=0, is_complete=False), "trading_day", no_prior_session=True)
        self.assertEqual(no_prior["missing_reason"], "NO_PRIOR_SESSION")
        self.assertTrue(pd.isna(no_prior["available_at"]))

    def test_legacy_availability_is_completeness_only(self):
        # Frozen ORB had no contract concept: a complete window was available.
        # (Zero mixed-contract windows exist in DEVELOPMENT; generic M5A reports MIXED_CONTRACT.)
        summary = to_orb_window_summary(self.record(is_available=False), "asia_kill_zone")
        self.assertTrue(summary["feature_available"])


class LegacyEquivalenceTests(unittest.TestCase):
    """The migrated path equals the retained legacy ``summarize_window`` on synthetic data."""

    def test_windows_and_previous_sessions_match_legacy_computation(self):
        tue = session(TUE, 110).drop(index=[pd.Timestamp("2026-09-22 03:00", tz=TZ)])  # incomplete London/overnight
        prices = pd.concat([session(MON, 100), tue, session(THU, 120)])  # Wednesday absent
        summaries = orb_window_summaries(prices, orb_config(), SPEC)
        windows = load_context_windows(orb_config())
        legacy_ids = {"asia": "asia_kill_zone", "london": "london_kill_zone", "ny_premarket": "ny_premarket",
                      "overnight": "overnight", "overnight_context_2000_0900": "overnight_context_2000_0900"}
        trading_day = WindowDefinition("trading_day", time(18, 0), time(17, 0), -1)
        rth = WindowDefinition("rth", time(9, 30), time(16, 0))
        dataset = [MON, TUE, THU]
        for position, day in enumerate(dataset):
            rows = prices[prices["session_date"] == day]
            for prefix, window_id in legacy_ids.items():
                assert_summary_equal(self, summaries[day][prefix], legacy_summary(rows, day, windows[window_id]), f"{day}.{prefix}")
            if position == 0:
                continue
            prior = dataset[position - 1]
            prior_rows = prices[prices["session_date"] == prior]
            assert_summary_equal(self, summaries[day]["previous_day"], legacy_summary(prior_rows, prior, trading_day), f"{day}.previous_day")
            assert_summary_equal(self, summaries[day]["previous_rth"], legacy_summary(prior_rows, prior, rth), f"{day}.previous_rth")
        self.assertEqual(summaries[MON]["previous_day"]["missing_reason"], "NO_PRIOR_SESSION")

    def test_negative_generic_selector_would_change_orb_previous_day(self):
        prices = pd.concat([session(MON, 100), session(THU, 120)])  # Tue/Wed absent
        legacy = orb_window_summaries(prices, orb_config(), SPEC)[THU]["previous_day"]
        self.assertTrue(legacy["feature_available"])  # frozen policy: previous AVAILABLE session (Monday)
        generic = build_market_context(prices, SPEC, instrument_id="MNQ", context_ids=[PREVIOUS_DAY_CONTEXT_ID])
        thursday = generic[generic["target_trading_date"] == THU].iloc[0]
        self.assertEqual(thursday["unavailable_reason"], "MISSING_EXPECTED_SESSION")  # generic: expected Wednesday
        self.assertIn("previous_day", LEGACY_PREVIOUS_SESSION_PREFIXES)


@unittest.skipUnless(DEV_PARTITION.is_file(), "local DEVELOPMENT partition not present (Git-ignored market data)")
class FrozenOracleParityTests(unittest.TestCase):
    def test_migrated_orb_audit_matches_frozen_stage2_feature_audit(self):
        from src.experiments.mnq_orb_v02_features import build_feature_audit, load_development_prices

        prices = load_development_prices(DEV_PARTITION)
        features = build_feature_audit(prices, orb_config())
        frozen = pd.read_csv(FROZEN_AUDIT).sort_values(["session_date", "or_minutes"]).reset_index(drop=True)
        now = pd.read_csv(pd.io.common.StringIO(features.to_csv(index=False)))
        now = now.sort_values(["session_date", "or_minutes"]).reset_index(drop=True)
        self.assertEqual(list(now.columns), list(frozen.columns))
        mismatched = [
            column for column in frozen.columns
            if not ((frozen[column].astype(str) == now[column].astype(str)) | (frozen[column].isna() & now[column].isna())).all()
        ]
        self.assertEqual(mismatched, [])


if __name__ == "__main__":
    unittest.main()
