"""M5A generic Market Context tests. Synthetic 1m bars only; no market data."""

from datetime import date, time, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.data.instruments import InstrumentError
from src.data.sessions import load_session_spec, with_calendar_overrides
from src.data.timeframes import build_timeframe
from src.features.session_context import (
    ALIGN_AVAILABLE,
    ALIGN_CONTRACT_MISMATCH,
    ALIGN_PENDING,
    ALIGN_UNAVAILABLE_CONTEXT,
    DEFAULT_CONTEXT_CONFIG,
    INCOMPLETE_WINDOW,
    INSUFFICIENT_FUTURE_COVERAGE,
    INSUFFICIENT_HISTORY,
    MISSING_EXPECTED_SESSION,
    MIXED_CONTRACT,
    NO_OBSERVATIONS,
    NOT_SCHEDULED,
    PREVIOUS_DAY_CONTEXT_ID,
    SUMMARY_COLUMNS,
    UNAVAILABLE_REASONS,
    VALID_LEVEL_COLUMNS,
    MarketContextError,
    align_market_context,
    build_market_context,
    load_market_context_windows,
    valid_context_levels,
)

TZ = "America/New_York"
SPEC = load_session_spec()
MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in range(21, 26))
NEXT_MON = date(2026, 9, 28)
CONTRACT = "MNQ 12-26"
ALL_IDS = [
    "asia_2000_0000", "london_0200_0500", "overnight_1800_0700",
    "overnight_context_2000_0900", "ny_premarket_0700_0900", "previous_rth", PREVIOUS_DAY_CONTEXT_ID,
]


def et(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(TZ)


def session_bars(day: date, contract: str = CONTRACT, *, base: float | None = None) -> pd.DataFrame:
    start = pd.Timestamp.combine(day - timedelta(days=1), time(18, 0)).tz_localize(TZ)
    end = pd.Timestamp.combine(day, time(17, 0)).tz_localize(TZ)
    labels = pd.date_range(start + pd.Timedelta(minutes=1), end, freq="min")
    price = (base if base is not None else 20000 + day.toordinal() % 97 * 10) + np.arange(len(labels)) * 0.25
    return pd.DataFrame(
        {"open": price, "high": price + 1.0, "low": price - 0.5, "close": price + 0.25, "contract": contract},
        index=pd.DatetimeIndex(labels, name="timestamp_et"),
    )


def bars_for(*days: date, contract: str = CONTRACT) -> pd.DataFrame:
    return pd.concat([session_bars(day, contract) for day in days])


def build(bars: pd.DataFrame, spec=SPEC, **kwargs) -> pd.DataFrame:
    return build_market_context(bars, spec, instrument_id="MNQ", **kwargs)


def row(context: pd.DataFrame, context_id: str, target: date) -> pd.Series:
    match = context[(context["context_id"] == context_id) & (context["target_trading_date"] == target)]
    assert len(match) == 1, (context_id, target, len(match))
    return match.iloc[0]


class RegistryTests(unittest.TestCase):
    def test_generic_registry_contents(self):
        registry = load_market_context_windows(SPEC)
        self.assertEqual([definition.context_id for definition in registry.contexts], ALL_IDS)
        self.assertEqual(registry.get("previous_rth").window_id, "rth_0930_1600")
        self.assertEqual(registry.get(PREVIOUS_DAY_CONTEXT_ID).window, None)
        self.assertEqual(registry.get("overnight_context_2000_0900").context_type, "TARGET_SESSION_WINDOW")
        self.assertEqual(registry.get("previous_rth").context_type, "PREVIOUS_SESSION_WINDOW")
        self.assertEqual(registry.get(PREVIOUS_DAY_CONTEXT_ID).context_type, "PREVIOUS_SESSION")
        self.assertFalse(any(context_id.startswith("orb") for context_id in ALL_IDS))

    def test_invalid_registries(self):
        base = json.loads(DEFAULT_CONTEXT_CONFIG.read_text(encoding="utf-8"))

        def with_change(mutate):
            config = json.loads(json.dumps(base))
            mutate(config)
            return config

        cases = {
            "duplicate window": with_change(lambda c: c["windows"].append(dict(c["windows"][0]))),
            "window in maintenance break": with_change(lambda c: c["windows"][0].update(end_et="17:30", end_day_offset=0, start_et="16:30", start_day_offset=0)),
            "start not before end": with_change(lambda c: c["windows"][1].update(end_et="02:00")),
            "starts before session open": with_change(lambda c: c["windows"][0].update(start_et="17:00")),
            "unknown window": with_change(lambda c: c["contexts"][0].update(window_id="nope")),
            "bad source": with_change(lambda c: c["contexts"][0].update(source_session="YESTERDAY")),
            "reserved previous_day": with_change(lambda c: c["contexts"][0].update(context_id="previous_day")),
            "bad version": with_change(lambda c: c["contexts"][0].update(definition_version=0)),
            "session mismatch": with_change(lambda c: c.update(session_id="other")),
            "bad identifier": with_change(lambda c: c["contexts"][0].update(context_id="Asia-1")),
            "offset not integer": with_change(lambda c: c["windows"][0].update(start_day_offset="-1")),
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, config in cases.items():
                with self.subTest(name):
                    path = Path(folder) / "windows.json"
                    path.write_text(json.dumps(config), encoding="utf-8")
                    with self.assertRaises(MarketContextError):
                        load_market_context_windows(SPEC, path)


class NormalWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = bars_for(MON, TUE, WED)
        cls.context = build(cls.bars)

    def test_schema_and_one_row_per_target_and_context(self):
        self.assertEqual(list(self.context.columns), SUMMARY_COLUMNS)
        self.assertEqual(len(self.context), 3 * len(ALL_IDS))
        self.assertNotIn("high", self.context.columns)  # observed values only in the audit tier

    def test_expected_counts_windows_and_availability_times(self):
        expected = {
            "asia_2000_0000": (240, "2026-09-21 20:00", "2026-09-22 00:00"),
            "london_0200_0500": (180, "2026-09-22 02:00", "2026-09-22 05:00"),
            "overnight_1800_0700": (780, "2026-09-21 18:00", "2026-09-22 07:00"),
            "overnight_context_2000_0900": (780, "2026-09-21 20:00", "2026-09-22 09:00"),
            "ny_premarket_0700_0900": (120, "2026-09-22 07:00", "2026-09-22 09:00"),
            "previous_rth": (390, "2026-09-21 09:30", "2026-09-21 16:00"),
            PREVIOUS_DAY_CONTEXT_ID: (1380, "2026-09-20 18:00", "2026-09-21 17:00"),
        }
        for context_id, (count, start, end) in expected.items():
            with self.subTest(context_id):
                record = row(self.context, context_id, TUE)
                self.assertTrue(record["is_available"])
                self.assertTrue(pd.isna(record["unavailable_reason"]))  # null reason = available
                self.assertEqual((record["expected_count"], record["observed_count"], record["missing_count"]), (count, count, 0))
                self.assertEqual((record["window_start"], record["window_end"]), (et(start), et(end)))
                self.assertEqual(record["available_at"], et(end))
                self.assertEqual(record["contract"], CONTRACT)
                self.assertFalse(record["is_schedule_clipped"])
                self.assertFalse(record["calendar_verified"])  # empty calendar

    def test_source_trading_dates(self):
        self.assertEqual(row(self.context, "asia_2000_0000", TUE)["source_trading_date"], TUE)
        self.assertEqual(row(self.context, PREVIOUS_DAY_CONTEXT_ID, TUE)["source_trading_date"], MON)
        self.assertEqual(row(self.context, "previous_rth", TUE)["source_trading_date"], MON)

    def test_observed_values_match_member_bars(self):
        record = row(self.context, "asia_2000_0000", TUE)
        members = self.bars[(self.bars.index > et("2026-09-21 20:00")) & (self.bars.index <= et("2026-09-22 00:00"))]
        self.assertEqual(len(members), 240)
        self.assertEqual(record["observed_open"], members["open"].iloc[0])
        self.assertEqual(record["observed_high"], members["high"].max())
        self.assertEqual(record["observed_low"], members["low"].min())
        self.assertEqual(record["observed_close"], members["close"].iloc[-1])

    def test_previous_day_and_rth_close_bars(self):
        monday = self.bars.loc[self.bars.index <= et("2026-09-21 17:00")]
        previous_day = row(self.context, PREVIOUS_DAY_CONTEXT_ID, TUE)
        self.assertEqual(previous_day["observed_close"], monday.loc[et("2026-09-21 17:00"), "close"])
        self.assertEqual(previous_day["observed_high"], monday["high"].max())
        previous_rth = row(self.context, "previous_rth", TUE)
        self.assertEqual(previous_rth["observed_close"], monday.loc[et("2026-09-21 16:00"), "close"])
        self.assertEqual(previous_rth["observed_open"], monday.loc[et("2026-09-21 09:31"), "open"])

    def test_previous_day_matches_daily_timeframe_bar(self):
        daily = build_timeframe(self.bars.assign(volume=1), "1D", SPEC)
        monday_bar = daily[daily["trading_date"] == MON].iloc[0]
        previous_day = row(self.context, PREVIOUS_DAY_CONTEXT_ID, TUE)
        for field in ("open", "high", "low", "close"):
            self.assertEqual(previous_day[f"observed_{field}"], monday_bar[field])

    def test_previous_day_over_weekend_uses_friday(self):
        context = build(bars_for(FRI, NEXT_MON))
        record = row(context, PREVIOUS_DAY_CONTEXT_ID, NEXT_MON)
        self.assertTrue(record["is_available"])
        self.assertEqual(record["source_trading_date"], FRI)


class BoundaryTests(unittest.TestCase):
    def spike(self, stamp: str, value: float = 99999.0) -> pd.DataFrame:
        bars = bars_for(MON, TUE)
        bars.loc[et(stamp), "high"] = value
        return bars

    def test_window_start_bar_excluded_and_end_bar_included(self):
        context = build(self.spike("2026-09-21 20:00"))  # labelled at Asia start: belongs to overnight only
        self.assertLess(row(context, "asia_2000_0000", TUE)["observed_high"], 99999.0)
        self.assertEqual(row(context, "overnight_1800_0700", TUE)["observed_high"], 99999.0)
        context = build(self.spike("2026-09-22 00:00"))  # labelled at Asia end: included (midnight crossing)
        self.assertEqual(row(context, "asia_2000_0000", TUE)["observed_high"], 99999.0)
        self.assertEqual(row(context, "asia_2000_0000", TUE)["high_at"], et("2026-09-22 00:00"))

    def test_0900_boundary_and_0900_0930_gap(self):
        context = build(self.spike("2026-09-22 09:00"))
        self.assertEqual(row(context, "ny_premarket_0700_0900", TUE)["observed_high"], 99999.0)
        self.assertEqual(row(context, "overnight_context_2000_0900", TUE)["observed_high"], 99999.0)
        context = build(self.spike("2026-09-22 09:15"))  # 09:00-09:30 belongs to no window
        for context_id in ("ny_premarket_0700_0900", "overnight_context_2000_0900", "overnight_1800_0700"):
            with self.subTest(context_id):
                self.assertLess(row(context, context_id, TUE)["observed_high"], 99999.0)

    def test_1800_session_boundary(self):
        context = build(self.spike("2026-09-21 18:01"))  # first bar of Tuesday's session
        self.assertEqual(row(context, "overnight_1800_0700", TUE)["observed_high"], 99999.0)
        wednesday = build(bars_for(MON, TUE, WED).assign(high=lambda f: f["high"].where(f.index != et("2026-09-21 18:01"), 99999.0)))
        self.assertLess(row(wednesday, PREVIOUS_DAY_CONTEXT_ID, TUE)["observed_high"], 99999.0)  # Monday session
        self.assertEqual(row(wednesday, PREVIOUS_DAY_CONTEXT_ID, WED)["observed_high"], 99999.0)  # Tuesday session

    def test_high_at_is_first_occurrence(self):
        bars = bars_for(MON, TUE)
        bars.loc[[et("2026-09-22 02:10"), et("2026-09-22 04:00")], "high"] = 99999.0
        self.assertEqual(row(build(bars), "london_0200_0500", TUE)["high_at"], et("2026-09-22 02:10"))


class CompletenessTests(unittest.TestCase):
    def check(self, drop: list[str], reason: str, observed: int):
        bars = bars_for(MON, TUE).drop(index=[et(value) for value in drop])
        record = row(build(bars), "london_0200_0500", TUE)
        self.assertFalse(record["is_available"])
        self.assertEqual(record["unavailable_reason"], reason)
        self.assertEqual((record["expected_count"], record["observed_count"]), (180, observed))
        self.assertFalse(record["is_complete"])
        return record

    def test_missing_first_internal_and_last_minute(self):
        for stamp in ("2026-09-22 02:01", "2026-09-22 03:30", "2026-09-22 05:00"):
            with self.subTest(stamp):
                record = self.check([stamp], INCOMPLETE_WINDOW, 179)
                self.assertFalse(np.isnan(record["observed_high"]))  # diagnostics retained in the audit tier

    def test_zero_observations(self):
        drop = pd.date_range(et("2026-09-22 02:01"), et("2026-09-22 05:00"), freq="min").strftime("%Y-%m-%d %H:%M")
        record = self.check(list(drop), NO_OBSERVATIONS, 0)
        self.assertTrue(np.isnan(record["observed_high"]))

    def test_incomplete_context_never_reaches_valid_tier(self):
        bars = bars_for(MON, TUE).drop(index=[et("2026-09-22 03:30")])
        context = build(bars)
        valid = valid_context_levels(context)
        self.assertEqual(list(valid.columns), VALID_LEVEL_COLUMNS)
        self.assertFalse(((valid["context_id"] == "london_0200_0500") & (valid["target_trading_date"] == TUE)).any())
        aligned = align_market_context(bars, context, SPEC, context_ids=["london_0200_0500"])
        after = aligned.loc[aligned.index > et("2026-09-22 05:00")]
        after = after.loc[after.index <= et("2026-09-22 17:00")]
        self.assertTrue((after["london_0200_0500_status"] == ALIGN_UNAVAILABLE_CONTEXT).all())
        self.assertTrue(after["london_0200_0500_high"].isna().all())


class ScheduleTests(unittest.TestCase):
    def spec_with(self, override: dict):
        return with_calendar_overrides(SPEC, [override], coverage_start="2026-09-01", coverage_end="2026-09-30")

    def test_verified_early_close_clips_and_remains_available(self):
        spec = self.spec_with({"trading_date": "2026-09-22", "kind": "MODIFIED", "close_et": "13:00"})
        bars = bars_for(MON, TUE, WED)
        bars = bars.drop(index=bars.index[(bars.index > et("2026-09-22 13:00")) & (bars.index <= et("2026-09-22 17:00"))])
        context = build(bars, spec)
        previous_day = row(context, PREVIOUS_DAY_CONTEXT_ID, WED)
        self.assertTrue(previous_day["is_available"])
        self.assertTrue(previous_day["is_schedule_clipped"])
        self.assertEqual((previous_day["expected_count"], previous_day["window_end"]), (1140, et("2026-09-22 13:00")))
        self.assertTrue(previous_day["calendar_verified"])
        previous_rth = row(context, "previous_rth", WED)
        self.assertTrue(previous_rth["is_available"])
        self.assertEqual((previous_rth["expected_count"], previous_rth["available_at"]), (210, et("2026-09-22 13:00")))

    def test_window_outside_verified_schedule_is_not_scheduled(self):
        spec = self.spec_with({"trading_date": "2026-09-22", "kind": "MODIFIED", "open_et": "08:00", "open_day_offset": 0})
        bars = pd.concat([session_bars(MON), session_bars(TUE).loc[et("2026-09-22 08:01"):]])
        context = build(bars, spec)
        for context_id in ("asia_2000_0000", "london_0200_0500", "overnight_1800_0700"):
            with self.subTest(context_id):
                record = row(context, context_id, TUE)
                self.assertEqual(record["unavailable_reason"], NOT_SCHEDULED)
                self.assertEqual(record["expected_count"], 0)
                self.assertTrue(record["is_schedule_clipped"])
        premarket = row(context, "ny_premarket_0700_0900", TUE)
        self.assertTrue(premarket["is_available"])
        self.assertTrue(premarket["is_schedule_clipped"])
        self.assertEqual((premarket["window_start"], premarket["expected_count"]), (et("2026-09-22 08:00"), 60))

    def test_unverified_early_data_end_is_incomplete(self):
        bars = bars_for(MON, TUE, WED)
        bars = bars.drop(index=bars.index[(bars.index > et("2026-09-22 13:00")) & (bars.index <= et("2026-09-22 17:00"))])
        context = build(bars)
        self.assertEqual(row(context, PREVIOUS_DAY_CONTEXT_ID, WED)["unavailable_reason"], INCOMPLETE_WINDOW)
        self.assertEqual(row(context, "previous_rth", WED)["unavailable_reason"], INCOMPLETE_WINDOW)
        self.assertFalse(row(context, PREVIOUS_DAY_CONTEXT_ID, WED)["is_schedule_clipped"])

    def test_verified_closure_is_skipped_by_previous_day(self):
        spec = self.spec_with({"trading_date": "2026-09-22", "kind": "CLOSED", "reason": "synthetic closure"})
        context = build(bars_for(MON, WED), spec)
        self.assertNotIn(TUE, set(context["target_trading_date"]))
        record = row(context, PREVIOUS_DAY_CONTEXT_ID, WED)
        self.assertTrue(record["is_available"])
        self.assertEqual(record["source_trading_date"], MON)
        self.assertTrue(record["calendar_verified"])


class CoverageAndContinuityTests(unittest.TestCase):
    def test_insufficient_history_at_source_start(self):
        bars = session_bars(TUE).loc[et("2026-09-22 00:01"):]  # data starts mid-session
        context = build(bars)
        self.assertEqual(row(context, "asia_2000_0000", TUE)["unavailable_reason"], INSUFFICIENT_HISTORY)
        self.assertEqual(row(context, "overnight_1800_0700", TUE)["unavailable_reason"], INSUFFICIENT_HISTORY)
        self.assertEqual(row(context, PREVIOUS_DAY_CONTEXT_ID, TUE)["unavailable_reason"], INSUFFICIENT_HISTORY)
        self.assertTrue(row(context, "london_0200_0500", TUE)["is_available"])

    def test_insufficient_future_coverage_at_source_end(self):
        bars = pd.concat([session_bars(MON), session_bars(TUE).loc[:et("2026-09-22 08:00")]])
        context = build(bars)
        self.assertEqual(row(context, "ny_premarket_0700_0900", TUE)["unavailable_reason"], INSUFFICIENT_FUTURE_COVERAGE)
        self.assertTrue(row(context, "london_0200_0500", TUE)["is_available"])
        extended = build(bars, coverage=(et("2026-09-20 18:00"), et("2026-09-22 17:00")))
        self.assertEqual(row(extended, "ny_premarket_0700_0900", TUE)["unavailable_reason"], INCOMPLETE_WINDOW)
        with self.assertRaises(MarketContextError):
            build(bars, coverage=(et("2026-09-21 00:00"), et("2026-09-22 17:00")))  # excludes source bars

    def test_missing_expected_session_is_visible_and_never_replaced(self):
        context = build(bars_for(MON, WED))  # Tuesday entirely absent
        for context_id in ALL_IDS[:5]:
            with self.subTest(context_id):
                self.assertEqual(row(context, context_id, TUE)["unavailable_reason"], MISSING_EXPECTED_SESSION)
        previous_day = row(context, PREVIOUS_DAY_CONTEXT_ID, WED)
        self.assertEqual(previous_day["unavailable_reason"], MISSING_EXPECTED_SESSION)
        self.assertEqual(previous_day["source_trading_date"], TUE)  # not Monday
        self.assertTrue(np.isnan(previous_day["observed_high"]))
        self.assertEqual(row(context, "previous_rth", WED)["unavailable_reason"], MISSING_EXPECTED_SESSION)

    def test_mixed_contract_and_precedence(self):
        bars = bars_for(MON, TUE)
        bars.loc[et("2026-09-22 03:00"), "contract"] = "MNQ 03-27"
        record = row(build(bars), "london_0200_0500", TUE)
        self.assertEqual(record["unavailable_reason"], MIXED_CONTRACT)
        self.assertTrue(pd.isna(record["contract"]))
        self.assertEqual(record["contract_count"], 2)
        bars = bars.drop(index=[et("2026-09-22 04:00")])  # mixed and incomplete: MIXED_CONTRACT wins
        self.assertEqual(row(build(bars), "london_0200_0500", TUE)["unavailable_reason"], MIXED_CONTRACT)

    def test_reason_vocabulary_is_controlled(self):
        context = build(bars_for(MON, WED))
        reasons = set(context["unavailable_reason"].dropna())
        self.assertTrue(reasons.issubset(UNAVAILABLE_REASONS))


class AlignmentTests(unittest.TestCase):
    def test_pending_then_available_on_next_bar(self):
        bars = bars_for(MON, TUE)
        aligned = align_market_context(bars, build(bars), SPEC, context_ids=["asia_2000_0000"])
        self.assertEqual(aligned.loc[et("2026-09-22 00:00"), "asia_2000_0000_status"], ALIGN_PENDING)
        self.assertTrue(np.isnan(aligned.loc[et("2026-09-22 00:00"), "asia_2000_0000_high"]))
        self.assertEqual(aligned.loc[et("2026-09-22 00:01"), "asia_2000_0000_status"], ALIGN_AVAILABLE)
        self.assertFalse(np.isnan(aligned.loc[et("2026-09-22 00:01"), "asia_2000_0000_high"]))

    def test_previous_day_visible_from_first_bar_of_session(self):
        bars = bars_for(MON, TUE)
        context = build(bars)
        aligned = align_market_context(bars, context, SPEC, context_ids=[PREVIOUS_DAY_CONTEXT_ID], fields=("high", "close", "high_at"))
        first = aligned.loc[et("2026-09-21 18:01")]
        self.assertEqual(first["previous_day_status"], ALIGN_AVAILABLE)
        self.assertEqual(first["previous_day_high"], row(context, PREVIOUS_DAY_CONTEXT_ID, TUE)["observed_high"])
        self.assertIsInstance(first["previous_day_high_at"], pd.Timestamp)
        monday = aligned.loc[aligned.index <= et("2026-09-21 17:00")]  # Monday's previous day precedes coverage
        self.assertTrue((monday["previous_day_status"] == ALIGN_UNAVAILABLE_CONTEXT).all())

    def test_context_does_not_carry_into_another_trading_date(self):
        bars = bars_for(MON, TUE, WED).drop(index=[et("2026-09-22 22:00")])  # Wednesday's Asia incomplete
        aligned = align_market_context(bars, build(bars), SPEC, context_ids=["asia_2000_0000"])
        tuesday_late = aligned.loc[et("2026-09-22 16:00")]
        self.assertEqual(tuesday_late["asia_2000_0000_status"], ALIGN_AVAILABLE)
        wednesday = aligned.loc[(aligned.index > et("2026-09-22 18:00")) & (aligned.index <= et("2026-09-23 17:00"))]
        self.assertTrue((wednesday["asia_2000_0000_status"].isin([ALIGN_UNAVAILABLE_CONTEXT])).all())
        self.assertTrue(wednesday["asia_2000_0000_high"].isna().all())

    def test_contract_mismatch_blocks_value_but_not_summary(self):
        bars = pd.concat([session_bars(MON), session_bars(TUE, "MNQ 03-27")])
        context = build(bars)
        record = row(context, PREVIOUS_DAY_CONTEXT_ID, TUE)
        self.assertTrue(record["is_available"])
        self.assertEqual(record["contract"], CONTRACT)
        aligned = align_market_context(bars, context, SPEC, context_ids=[PREVIOUS_DAY_CONTEXT_ID])
        tuesday = aligned.loc[aligned.index > et("2026-09-21 18:00")]
        self.assertTrue((tuesday["previous_day_status"] == ALIGN_CONTRACT_MISMATCH).all())
        self.assertTrue(tuesday["previous_day_high"].isna().all())
        self.assertTrue(row(context, PREVIOUS_DAY_CONTEXT_ID, TUE)["is_available"])  # summary unchanged

    def test_invalid_alignment_requests(self):
        bars = bars_for(MON, TUE)
        context = build(bars)
        with self.assertRaises(MarketContextError):
            align_market_context(bars, context, SPEC, fields=("volume",))
        with self.assertRaises(MarketContextError):
            align_market_context(bars, context, SPEC, context_ids=["orb_overnight_1800_0930"])


class DstTests(unittest.TestCase):
    def test_both_transitions_keep_wall_clock_windows(self):
        for friday, monday in ((date(2026, 3, 6), date(2026, 3, 9)), (date(2026, 10, 30), date(2026, 11, 2))):
            with self.subTest(monday):
                context = build(bars_for(friday, monday))
                asia = row(context, "asia_2000_0000", monday)
                self.assertTrue(asia["is_available"])
                self.assertEqual(asia["window_start"].strftime("%a %H:%M"), "Sun 20:00")
                self.assertEqual(asia["expected_count"], 240)
                overnight = row(context, "overnight_1800_0700", monday)
                self.assertEqual((overnight["expected_count"], overnight["is_available"]), (780, True))
                previous_day = row(context, PREVIOUS_DAY_CONTEXT_ID, monday)
                self.assertEqual((previous_day["source_trading_date"], previous_day["expected_count"]), (friday, 1380))
                self.assertTrue(previous_day["is_available"])
        spring = row(build(bars_for(date(2026, 3, 6), date(2026, 3, 9))), "asia_2000_0000", date(2026, 3, 9))
        fall = row(build(bars_for(date(2026, 10, 30), date(2026, 11, 2))), "asia_2000_0000", date(2026, 11, 2))
        self.assertEqual(spring["window_start"].tz_convert("UTC").hour, 0)   # 20:00 EDT
        self.assertEqual(fall["window_start"].tz_convert("UTC").hour, 1)     # 20:00 EST


class InputTests(unittest.TestCase):
    def test_deterministic_and_order_independent(self):
        bars = bars_for(MON, TUE, WED)
        first = build(bars)
        pd.testing.assert_frame_equal(first, build(bars.sample(frac=1.0, random_state=3)))

    def test_invalid_inputs(self):
        bars = bars_for(MON, TUE)
        cases = {
            "naive": bars.tz_localize(None),
            "missing contract": bars.drop(columns=["contract"]),
            "nan price": bars.assign(high=np.where(np.arange(len(bars)) == 3, np.nan, bars["high"])),
            "session_date mismatch": bars.assign(session_date="2026-09-20"),
            "empty": bars.iloc[:0],
        }
        for name, frame in cases.items():
            with self.subTest(name):
                with self.assertRaises(MarketContextError):
                    build(frame)
        with self.assertRaises(InstrumentError):
            build_market_context(bars, SPEC, instrument_id="ZZZ")
        with self.assertRaises(MarketContextError):
            build(bars, context_ids=["asia_2000_0000", "asia_2000_0000"])


if __name__ == "__main__":
    unittest.main()
