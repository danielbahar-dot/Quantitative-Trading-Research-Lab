"""M3 generic timeframe builder tests. Synthetic bars only; no market data."""

from datetime import date, time, timedelta
import unittest

import numpy as np
import pandas as pd

from src.data.sessions import (
    SessionError,
    assign_trading_date,
    assign_trading_dates,
    load_session_spec,
    with_calendar_overrides,
)
from src.data.timeframes import (
    OUTPUT_COLUMNS,
    STANDARD_TIMEFRAMES,
    TimeframeError,
    TimeframeSpec,
    build_timeframe,
    get_timeframe,
)

TZ = "America/New_York"
SPEC = load_session_spec()
WED = date(2026, 9, 23)  # session: Tue 2026-09-22 18:00 -> Wed 17:00


def et(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(TZ)


def session_bars(trading_date: date, contract: str = "MNQ 12-26", *, spec=SPEC) -> pd.DataFrame:
    """One synthetic 1m bar per minute of the session, bar-end labelled."""
    open_ts = pd.Timestamp.combine(trading_date - timedelta(days=1), time(18, 0)).tz_localize(TZ)
    close_ts = pd.Timestamp.combine(trading_date, time(17, 0)).tz_localize(TZ)
    labels = pd.date_range(open_ts + pd.Timedelta(minutes=1), close_ts, freq="min")
    return make_bars(labels, contract, trading_date)


def make_bars(labels, contract: str, trading_date: date | None = None) -> pd.DataFrame:
    labels = pd.DatetimeIndex(labels)
    base = 20000 + np.arange(len(labels)) * 0.25
    frame = pd.DataFrame(
        {
            "open": base,
            "high": base + 1.0,
            "low": base - 0.5,
            "close": base + 0.25,
            "volume": np.full(len(labels), 10),
            "contract": contract,
        },
        index=pd.DatetimeIndex(labels, name="timestamp_et"),
    )
    if trading_date is not None:
        frame["session_date"] = trading_date.isoformat()
    return frame


class TimeframeSpecTests(unittest.TestCase):
    def test_standard_timeframes(self):
        self.assertEqual(
            {key: spec.minutes for key, spec in STANDARD_TIMEFRAMES.items()},
            {"5m": 5, "15m": 15, "1H": 60, "4H": 240, "1D": None},
        )
        self.assertIs(get_timeframe("4H"), STANDARD_TIMEFRAMES["4H"])
        custom = TimeframeSpec("90m", 90)
        self.assertIs(get_timeframe(custom), custom)

    def test_invalid_timeframes(self):
        for minutes in (0, -5, 2.5, True):
            with self.subTest(minutes):
                with self.assertRaises(TimeframeError):
                    TimeframeSpec("x", minutes)
        with self.assertRaises(TimeframeError):
            TimeframeSpec("", 5)
        with self.assertRaises(TimeframeError):
            get_timeframe("3H")


class RegularSessionAggregationTests(unittest.TestCase):
    def setUp(self):
        self.bars = session_bars(WED)

    def test_bucket_counts_for_full_session(self):
        expected = {"5m": 276, "15m": 92, "1H": 23, "4H": 6, "1D": 1}
        for timeframe, count in expected.items():
            with self.subTest(timeframe):
                result = build_timeframe(self.bars, timeframe, SPEC)
                self.assertEqual(len(result), count)
                self.assertEqual(list(result.columns), OUTPUT_COLUMNS)
                self.assertTrue(result["is_complete"].all())
                self.assertEqual(int(result["observed_bars"].sum()), 1380)
                self.assertTrue((result["trading_date"] == WED).all())

    def test_five_minute_alignment_and_membership(self):
        result = build_timeframe(self.bars, "5m", SPEC)
        first, second = result.iloc[0], result.iloc[1]
        self.assertEqual((first["bar_start"], first["bar_end"]), (et("2026-09-22 18:00"), et("2026-09-22 18:05")))
        # Bars labelled 18:01..18:05 form the first bucket; 18:06 starts the second.
        source = self.bars.loc[et("2026-09-22 18:01"):et("2026-09-22 18:05")]
        self.assertEqual(first["open"], source["open"].iloc[0])
        self.assertEqual(first["close"], source["close"].iloc[-1])
        self.assertEqual(first["high"], source["high"].max())
        self.assertEqual(first["low"], source["low"].min())
        self.assertEqual(first["volume"], source["volume"].sum())
        self.assertEqual(second["open"], self.bars.loc[et("2026-09-22 18:06"), "open"])
        self.assertEqual(result.iloc[-1]["bar_end"], et("2026-09-23 17:00"))

    def test_four_hour_anchors_and_truncated_final_segment(self):
        result = build_timeframe(self.bars, "4H", SPEC)
        starts = [stamp.strftime("%H:%M") for stamp in result["bar_start"]]
        self.assertEqual(starts, ["18:00", "22:00", "02:00", "06:00", "10:00", "14:00"])
        self.assertEqual(result["expected_bars"].tolist(), [240, 240, 240, 240, 240, 180])
        self.assertEqual(result["is_session_truncated"].tolist(), [False] * 5 + [True])
        self.assertEqual(result.iloc[-1]["bar_end"], et("2026-09-23 17:00"))

    def test_daily_bar_spans_the_session(self):
        daily = build_timeframe(self.bars, "1D", SPEC).iloc[0]
        self.assertEqual((daily["bar_start"], daily["bar_end"]), (et("2026-09-22 18:00"), et("2026-09-23 17:00")))
        self.assertEqual(daily["expected_bars"], 1380)
        self.assertFalse(daily["is_session_truncated"])
        self.assertEqual(daily["high"], self.bars["high"].max())
        self.assertEqual(daily["open"], self.bars["open"].iloc[0])

    def test_hourly_bars_align_to_session_anchor(self):
        result = build_timeframe(self.bars, "1H", SPEC)
        self.assertTrue(all(stamp.minute == 0 for stamp in result["bar_start"]))
        self.assertEqual(result.iloc[0]["bar_start"], et("2026-09-22 18:00"))

    def test_generic_custom_timeframe(self):
        result = build_timeframe(self.bars, TimeframeSpec("90m", 90), SPEC)
        self.assertEqual(len(result), 16)
        self.assertEqual((result.iloc[-1]["bar_start"], result.iloc[-1]["bar_end"]),
                         (et("2026-09-23 16:30"), et("2026-09-23 17:00")))
        self.assertTrue(result.iloc[-1]["is_session_truncated"])
        self.assertFalse(result.iloc[:-1]["is_session_truncated"].any())


class AvailabilityTests(unittest.TestCase):
    def test_available_at_is_bar_end_and_index(self):
        result = build_timeframe(session_bars(WED), "15m", SPEC)
        self.assertTrue((result["available_at"] == result["bar_end"]).all())
        self.assertTrue((result.index == result["bar_end"]).all())
        self.assertEqual(result.index.name, "timestamp_et")
        self.assertEqual(str(result.index.tz), TZ)
        self.assertTrue(result.index.is_monotonic_increasing)

    def test_no_bar_is_available_before_its_last_source_bar(self):
        bars = session_bars(WED)
        result = build_timeframe(bars, "1H", SPEC)
        for row in result.itertuples():
            members = bars.loc[(bars.index > row.bar_start) & (bars.index <= row.bar_end)]
            self.assertGreaterEqual(row.available_at, members.index.max())

    def test_incomplete_bucket_keeps_nominal_availability(self):
        bars = session_bars(WED)
        dropped = [et("2026-09-22 18:03"), et("2026-09-22 18:04"), et("2026-09-22 18:05")]
        result = build_timeframe(bars.drop(index=dropped), "5m", SPEC)
        first = result.iloc[0]
        self.assertEqual((first["expected_bars"], first["observed_bars"]), (5, 2))
        self.assertFalse(first["is_complete"])
        self.assertEqual(first["available_at"], et("2026-09-22 18:05"))
        self.assertEqual(first["close"], bars.loc[et("2026-09-22 18:02"), "close"])

    def test_empty_bucket_is_not_synthesized(self):
        bars = session_bars(WED)
        gap = bars.index[(bars.index > et("2026-09-22 18:05")) & (bars.index <= et("2026-09-22 18:10"))]
        result = build_timeframe(bars.drop(index=gap), "5m", SPEC)
        self.assertEqual(len(result), 275)
        self.assertNotIn(et("2026-09-22 18:10"), result.index)


class MultiSessionTests(unittest.TestCase):
    def test_weekend_gap_and_sunday_anchor(self):
        friday = session_bars(date(2026, 9, 25), "MNQ 12-26")
        monday = session_bars(date(2026, 9, 28), "MNQ 12-26")
        result = build_timeframe(pd.concat([friday, monday]), "4H", SPEC)
        self.assertEqual(len(result), 12)
        monday_first = result[result["trading_date"] == date(2026, 9, 28)].iloc[0]
        self.assertEqual(monday_first["bar_start"], et("2026-09-27 18:00"))

    def test_dst_sessions_use_wall_clock_anchors(self):
        bars = pd.concat([session_bars(date(2026, 3, 6)), session_bars(date(2026, 3, 9))])
        result = build_timeframe(bars, "1H", SPEC)
        for day, utc_hour in ((date(2026, 3, 6), 23), (date(2026, 3, 9), 22)):
            with self.subTest(day):
                first = result[result["trading_date"] == day].iloc[0]
                self.assertEqual(first["bar_start"].strftime("%H:%M"), "18:00")
                self.assertEqual(first["bar_start"].tz_convert("UTC").hour, utc_hour)
                self.assertEqual(int((result["trading_date"] == day).sum()), 23)

    def test_contract_change_at_session_boundary_is_allowed(self):
        bars = pd.concat([session_bars(date(2026, 9, 24), "MNQ 09-26"), session_bars(date(2026, 9, 25), "MNQ 12-26")])
        result = build_timeframe(bars, "1D", SPEC)
        self.assertEqual(result["contract"].tolist(), ["MNQ 09-26", "MNQ 12-26"])

    def test_result_is_deterministic_and_order_independent(self):
        bars = pd.concat([session_bars(date(2026, 9, 24)), session_bars(date(2026, 9, 25))])
        first = build_timeframe(bars, "15m", SPEC)
        shuffled = bars.sample(frac=1.0, random_state=7)
        pd.testing.assert_frame_equal(first, build_timeframe(shuffled, "15m", SPEC))


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.spec = with_calendar_overrides(
            SPEC,
            [
                {"trading_date": "2026-09-23", "kind": "MODIFIED", "close_et": "13:00", "reason": "synthetic early close"},
                {"trading_date": "2026-09-24", "kind": "CLOSED", "reason": "synthetic closure"},
            ],
            coverage_start="2026-09-01",
            coverage_end="2026-09-30",
        )
        full = session_bars(WED)
        self.early = full[full.index <= et("2026-09-23 13:00")]

    def test_shortened_session_clips_buckets(self):
        daily = build_timeframe(self.early, "1D", self.spec).iloc[0]
        self.assertEqual(daily["bar_end"], et("2026-09-23 13:00"))
        self.assertTrue(daily["is_session_truncated"])
        self.assertTrue(daily["is_complete"])
        four_hour = build_timeframe(self.early, "4H", self.spec)
        last = four_hour.iloc[-1]
        self.assertEqual((last["bar_start"], last["bar_end"]), (et("2026-09-23 10:00"), et("2026-09-23 13:00")))
        self.assertEqual(last["expected_bars"], 180)

    def test_bars_after_early_close_are_rejected(self):
        with self.assertRaises(TimeframeError):
            build_timeframe(session_bars(WED), "1D", self.spec)

    def test_bars_on_closed_date_are_rejected(self):
        with self.assertRaises(TimeframeError):
            build_timeframe(session_bars(date(2026, 9, 24)), "1D", self.spec)

    def test_without_overrides_an_early_close_is_only_incomplete(self):
        daily = build_timeframe(self.early, "1D", SPEC).iloc[0]
        self.assertFalse(daily["is_complete"])
        self.assertFalse(daily["is_session_truncated"])
        self.assertEqual(daily["available_at"], et("2026-09-23 17:00"))


class InvalidSourceTests(unittest.TestCase):
    def test_mixed_contract_bucket_raises(self):
        bars = session_bars(WED)
        bars.loc[et("2026-09-22 18:03"), "contract"] = "MNQ 03-27"
        with self.assertRaises(TimeframeError) as context:
            build_timeframe(bars, "5m", SPEC)
        self.assertIn("contract", str(context.exception))

    def test_invalid_timestamps(self):
        for label in ("2026-09-22 18:00", "2026-09-22 17:30", "2026-09-26 12:00"):  # break, break, Saturday
            with self.subTest(label):
                with self.assertRaises(SessionError):
                    build_timeframe(make_bars([et(label)], "MNQ 12-26"), "5m", SPEC)
        misaligned = make_bars([et("2026-09-22 18:01:30")], "MNQ 12-26")
        with self.assertRaises(TimeframeError):
            build_timeframe(misaligned, "5m", SPEC)

    def test_invalid_frames(self):
        bars = session_bars(WED)
        cases = {
            "naive index": bars.tz_localize(None),
            "missing column": bars.drop(columns=["volume"]),
            "duplicate timestamps": pd.concat([bars.iloc[:3], bars.iloc[:1]]),
            "nan price": bars.assign(close=np.where(np.arange(len(bars)) == 5, np.nan, bars["close"])),
            "bad ohlc": bars.assign(high=bars["low"] - 1),
            "empty contract": bars.assign(contract=" "),
            "session_date mismatch": bars.assign(session_date="2026-09-22"),
            "empty": bars.iloc[:0],
        }
        for name, frame in cases.items():
            with self.subTest(name):
                with self.assertRaises(TimeframeError):
                    build_timeframe(frame, "5m", SPEC)
        with self.assertRaises(TimeframeError):
            build_timeframe(bars, "5m", SPEC, source_interval="2min")  # 2m does not divide 5m


class VectorizedTradingDateTests(unittest.TestCase):
    def test_vectorized_matches_scalar_across_a_dst_week(self):
        stamps = pd.date_range(et("2026-03-05 00:00"), et("2026-03-10 23:59"), freq="7min")
        valid = []
        for stamp in stamps:
            try:
                valid.append((stamp, assign_trading_date(stamp, SPEC, label="bar_end", bar_interval="1min")))
            except SessionError:
                continue
        index = pd.DatetimeIndex([stamp for stamp, _ in valid])
        vectorized = assign_trading_dates(index, SPEC, label="bar_end", bar_interval="1min")
        self.assertEqual(vectorized.tolist(), [expected for _, expected in valid])
        # Coverage sanity: sessions on both sides of the 2026-03-08 DST change.
        self.assertGreater(len(valid), 700)
        self.assertTrue({date(2026, 3, 6), date(2026, 3, 9)}.issubset(set(vectorized)))

    def test_vectorized_rejects_what_scalar_rejects(self):
        for label in ("2026-09-22 17:30", "2026-09-26 12:00"):
            with self.subTest(label):
                with self.assertRaises(SessionError):
                    assign_trading_dates([et(label)], SPEC)
        with self.assertRaises(SessionError):
            assign_trading_dates(pd.DatetimeIndex([pd.Timestamp("2026-09-22 10:00")]), SPEC)
        with self.assertRaises(SessionError):
            assign_trading_dates([et("2026-09-23 17:03")], SPEC, label="bar_end", bar_interval="5min")


if __name__ == "__main__":
    unittest.main()
