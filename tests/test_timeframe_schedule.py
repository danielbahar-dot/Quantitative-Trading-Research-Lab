"""M3 expected-timeframe-schedule API tests (EL-I0). Synthetic bars only.

``reference_build_timeframe`` below is a frozen pre-refactor
geometry/aggregation reference for valid source fixtures.  It reproduces the
pre-refactor bucket geometry, aggregation and metrics, but not every input
validation path.  It is kept only as a parity oracle showing that the
shared-geometry refactor changed no output on valid fixtures.
"""

from datetime import date, time, timedelta
import unittest

import numpy as np
import pandas as pd

from src.data.sessions import (
    LABEL_BAR_END,
    assign_trading_dates,
    load_session_spec,
    session_bounds,
    with_calendar_overrides,
)
from src.data.timeframes import (
    DEFAULT_SOURCE_INTERVAL,
    OUTPUT_COLUMNS,
    REQUIRED_COLUMNS,
    SCHEDULE_COLUMNS,
    STANDARD_TIMEFRAMES,
    TimeframeError,
    TimeframeSpec,
    build_timeframe,
    expected_timeframe_schedule,
    get_timeframe,
)

TZ = "America/New_York"
SPEC = load_session_spec()
TUE, WED, THU, FRI = (date(2026, 9, day) for day in (22, 23, 24, 25))
EARLY_SPEC = with_calendar_overrides(
    SPEC,
    [
        {"trading_date": "2026-09-23", "kind": "MODIFIED", "close_et": "13:00", "reason": "synthetic early close"},
        {"trading_date": "2026-09-24", "kind": "CLOSED", "reason": "synthetic closure"},
    ],
    coverage_start="2026-09-01",
    coverage_end="2026-09-30",
)


def et(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(TZ)


def session_bars(trading_date: date, contract: str = "MNQ 12-26", *, close: time = time(17, 0)) -> pd.DataFrame:
    open_ts = pd.Timestamp.combine(trading_date - timedelta(days=1), time(18, 0)).tz_localize(TZ)
    close_ts = pd.Timestamp.combine(trading_date, close).tz_localize(TZ)
    labels = pd.date_range(open_ts + pd.Timedelta(minutes=1), close_ts, freq="min")
    base = 20000 + np.arange(len(labels)) * 0.25
    frame = pd.DataFrame(
        {"open": base, "high": base + 1.0, "low": base - 0.5, "close": base + 0.25,
         "volume": np.full(len(labels), 10), "contract": contract},
        index=pd.DatetimeIndex(labels, name="timestamp_et"),
    )
    frame["session_date"] = trading_date.isoformat()
    return frame


def spans(schedule: pd.DataFrame) -> list[tuple[str, str]]:
    return [(start.strftime("%H:%M"), end.strftime("%H:%M")) for start, end in zip(schedule["bar_start"], schedule["bar_end"])]


# ---------------------------------------------------------------------------
# Frozen pre-refactor geometry/aggregation reference for valid source fixtures
# (parity oracle only; input validation paths are not reproduced)
# ---------------------------------------------------------------------------


def _reference_session_frames(trading_dates, session_spec):
    regular_spec = with_calendar_overrides(session_spec, [])
    regular_length = (
        pd.Timedelta(days=1)
        - (pd.Timedelta(hours=session_spec.open_time.hour, minutes=session_spec.open_time.minute)
           - pd.Timedelta(hours=session_spec.close_time.hour, minutes=session_spec.close_time.minute))
    )
    anchors, opens, closes, nominal = {}, {}, {}, {}
    for day in trading_dates:
        actual = session_bounds(day, session_spec)
        if not actual.is_open:
            raise TimeframeError(f"Source bars present on {actual.kind} date {day}")
        regular = session_bounds(day, regular_spec)
        if regular.close - regular.open != regular_length:
            raise TimeframeError(f"Session {day} spans a DST transition; unsupported")
        anchors[day], opens[day], closes[day] = regular.open, actual.open, actual.close
        nominal[day] = regular_length
    return anchors, opens, closes, nominal


def reference_build_timeframe(bars, timeframe, session_spec, *, source_interval=DEFAULT_SOURCE_INTERVAL):
    spec = get_timeframe(timeframe)
    interval = pd.Timedelta(source_interval)
    bucket_length = pd.Timedelta(minutes=spec.minutes) if spec.minutes is not None else None
    source = bars.sort_index()
    labels = source.index
    trading_dates = assign_trading_dates(labels, session_spec, label=LABEL_BAR_END, bar_interval=interval).to_numpy()
    anchors, opens, closes, nominal = _reference_session_frames(sorted(set(trading_dates)), session_spec)
    work = pd.DataFrame({
        "trading_date": trading_dates,
        "source_start": labels - interval,
        "source_end": labels,
        **{column: source[column].to_numpy() for column in REQUIRED_COLUMNS},
    })
    work["anchor"] = work["trading_date"].map(anchors)
    work["session_open"] = work["trading_date"].map(opens)
    work["session_close"] = work["trading_date"].map(closes)
    offset = work["source_start"] - work["anchor"]
    if bucket_length is None:
        work["bucket"] = 0
        nominal_start = work["anchor"]
        nominal_end = work["anchor"] + work["trading_date"].map(nominal)
        work["nominal_length"] = work["trading_date"].map(nominal)
    else:
        work["bucket"] = (offset // bucket_length).astype("int64")
        nominal_start = work["anchor"] + work["bucket"] * bucket_length
        nominal_end = nominal_start + bucket_length
        work["nominal_length"] = bucket_length
    work["bar_start"] = nominal_start.where(nominal_start >= work["session_open"], work["session_open"])
    work["bar_end"] = nominal_end.where(nominal_end <= work["session_close"], work["session_close"])
    grouped = work.groupby(["trading_date", "bucket"], sort=True)
    output = grouped.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), contract=("contract", "first"), contract_count=("contract", "nunique"),
        bar_start=("bar_start", "first"), bar_end=("bar_end", "first"),
        nominal_length=("nominal_length", "first"), observed_bars=("open", "size"),
    ).reset_index()
    duration = output["bar_end"] - output["bar_start"]
    output["expected_bars"] = (duration // interval).astype("int64")
    output["observed_bars"] = output["observed_bars"].astype("int64")
    output["is_complete"] = output["observed_bars"] == output["expected_bars"]
    output["is_session_truncated"] = duration < output["nominal_length"]
    output["available_at"] = output["bar_end"]
    output["timeframe"] = spec.timeframe_id
    output = output[OUTPUT_COLUMNS]
    output.index = pd.DatetimeIndex(output["bar_end"], name="timestamp_et")
    return output


class BuildTimeframeParityTests(unittest.TestCase):
    """The shared-geometry refactor leaves build_timeframe output unchanged."""

    def fixtures(self):
        full = pd.concat([session_bars(TUE), session_bars(WED)])
        gappy = full.drop(full.index[(full.index >= et("2026-09-22 22:00")) & (full.index < et("2026-09-23 02:30"))])
        holes = full.drop(full.index[::7])
        return {
            "two full sessions": (full, SPEC),
            "missing bucket and partial bucket": (gappy, SPEC),
            "scattered missing minutes": (holes, SPEC),
            "verified early close": (session_bars(WED, close=time(13, 0)), EARLY_SPEC),
            "unverified early close": (session_bars(WED, close=time(13, 0)), SPEC),
        }

    def test_all_standard_timeframes_match_frozen_reference(self):
        for name, (bars, spec) in self.fixtures().items():
            for timeframe in STANDARD_TIMEFRAMES:
                with self.subTest(fixture=name, timeframe=timeframe):
                    pd.testing.assert_frame_equal(
                        build_timeframe(bars, timeframe, spec), reference_build_timeframe(bars, timeframe, spec), check_exact=True
                    )


class ScheduleTests(unittest.TestCase):
    def test_normal_4h_session(self):
        schedule = expected_timeframe_schedule(WED, "4H", SPEC)
        self.assertEqual(list(schedule.columns), SCHEDULE_COLUMNS)
        self.assertEqual(spans(schedule), [("18:00", "22:00"), ("22:00", "02:00"), ("02:00", "06:00"),
                                           ("06:00", "10:00"), ("10:00", "14:00"), ("14:00", "17:00")])
        self.assertEqual(schedule["expected_bars"].tolist(), [240, 240, 240, 240, 240, 180])
        self.assertEqual(schedule["is_session_truncated"].tolist(), [False] * 5 + [True])
        self.assertTrue((schedule["available_at"] == schedule["bar_end"]).all())
        self.assertEqual(schedule["bar_start"].iloc[0], et("2026-09-22 18:00"))
        self.assertEqual(set(schedule["trading_date"]), {WED})
        self.assertEqual(schedule.index.name, "timestamp_et")

    def test_final_4h_bucket(self):
        last = expected_timeframe_schedule(WED, "4H", SPEC).iloc[-1]
        self.assertEqual((last["bar_start"], last["bar_end"]), (et("2026-09-23 14:00"), et("2026-09-23 17:00")))
        self.assertEqual(last["expected_bars"], 180)
        self.assertTrue(last["is_session_truncated"])

    def test_normal_daily(self):
        schedule = expected_timeframe_schedule(WED, "1D", SPEC)
        self.assertEqual(len(schedule), 1)
        row = schedule.iloc[0]
        self.assertEqual((row["bar_start"], row["bar_end"]), (et("2026-09-22 18:00"), et("2026-09-23 17:00")))
        self.assertEqual(row["expected_bars"], 23 * 60)
        self.assertFalse(row["is_session_truncated"])

    def test_minute_timeframes(self):
        for timeframe, minutes in (("5m", 5), ("15m", 15), ("1H", 60)):
            with self.subTest(timeframe=timeframe):
                schedule = expected_timeframe_schedule(WED, timeframe, SPEC)
                self.assertEqual(len(schedule), 23 * 60 // minutes)
                self.assertTrue((schedule["expected_bars"] == minutes).all())
                self.assertFalse(schedule["is_session_truncated"].any())
                self.assertTrue((schedule["bar_start"].iloc[1:].to_numpy() == schedule["bar_end"].iloc[:-1].to_numpy()).all())
        custom = expected_timeframe_schedule(WED, TimeframeSpec("90m", 90), SPEC)
        self.assertEqual(spans(custom)[-1], ("16:30", "17:00"))  # 23h = 15 x 90m + 30m: clipped final bucket
        self.assertTrue(custom["is_session_truncated"].iloc[-1])

    def test_matches_build_timeframe_geometry_for_observed_buckets(self):
        bars = pd.concat([session_bars(TUE), session_bars(WED)])
        for timeframe in STANDARD_TIMEFRAMES:
            with self.subTest(timeframe=timeframe):
                built = build_timeframe(bars, timeframe, SPEC)
                schedule = expected_timeframe_schedule([TUE, WED], timeframe, SPEC)
                pd.testing.assert_frame_equal(built[SCHEDULE_COLUMNS], schedule, check_exact=True)

    def test_verified_shortened_session(self):
        schedule = expected_timeframe_schedule(WED, "4H", EARLY_SPEC)
        self.assertEqual(spans(schedule), [("18:00", "22:00"), ("22:00", "02:00"), ("02:00", "06:00"),
                                           ("06:00", "10:00"), ("10:00", "13:00")])
        self.assertTrue(schedule["is_session_truncated"].iloc[-1])
        self.assertEqual(schedule["expected_bars"].iloc[-1], 180)
        daily = expected_timeframe_schedule(WED, "1D", EARLY_SPEC).iloc[0]
        self.assertEqual(daily["bar_end"], et("2026-09-23 13:00"))
        self.assertTrue(daily["is_session_truncated"])
        built = build_timeframe(session_bars(WED, close=time(13, 0)), "4H", EARLY_SPEC)
        pd.testing.assert_frame_equal(built[SCHEDULE_COLUMNS], schedule, check_exact=True)

    def test_expected_empty_bucket_is_listed_but_not_synthesized(self):
        bars = session_bars(WED)
        gap = (bars.index > et("2026-09-22 22:00")) & (bars.index <= et("2026-09-23 02:00"))  # the whole 22:00-02:00 bucket
        built = build_timeframe(bars.loc[~gap], "4H", SPEC)
        schedule = expected_timeframe_schedule(WED, "4H", SPEC)
        self.assertNotIn(("22:00", "02:00"), spans(built))
        self.assertIn(("22:00", "02:00"), spans(schedule))
        self.assertEqual(len(built), 5)
        self.assertEqual(len(schedule), 6)
        missing = schedule.loc[~schedule["bar_start"].isin(built["bar_start"])]
        self.assertEqual(spans(missing), [("22:00", "02:00")])

    def test_multi_date_ordering_and_deduplication(self):
        schedule = expected_timeframe_schedule(["2026-09-23", TUE, pd.Timestamp("2026-09-23"), FRI], "4H", SPEC)
        self.assertEqual(schedule["trading_date"].drop_duplicates().tolist(), [TUE, WED, FRI])
        self.assertTrue(schedule["bar_start"].is_monotonic_increasing)
        self.assertEqual(len(schedule), 18)
        pd.testing.assert_frame_equal(schedule, expected_timeframe_schedule([FRI, WED, TUE], "4H", SPEC))

    def test_source_interval_validation(self):
        with self.assertRaises(TimeframeError):
            expected_timeframe_schedule(WED, "4H", SPEC, source_interval="0min")
        with self.assertRaises(TimeframeError):
            expected_timeframe_schedule(WED, "15m", SPEC, source_interval="7min")
        five = expected_timeframe_schedule(WED, "4H", SPEC, source_interval="5min")
        self.assertEqual(five["expected_bars"].tolist(), [48, 48, 48, 48, 48, 36])
        with self.assertRaises(TimeframeError):
            expected_timeframe_schedule(WED, "3H", SPEC)
        with self.assertRaises(TimeframeError):
            expected_timeframe_schedule(object(), "4H", SPEC)
        with self.assertRaises(TimeframeError):
            expected_timeframe_schedule([None], "4H", SPEC)

    def test_dst_weeks_use_session_model_offsets(self):
        # DST ends 2026-11-01 (a Sunday, outside any session): the Monday session is regular in EST.
        before = expected_timeframe_schedule(date(2026, 10, 30), "4H", SPEC)
        after = expected_timeframe_schedule(date(2026, 11, 2), "4H", SPEC)
        self.assertEqual(spans(before), spans(after))
        self.assertEqual(str(before["bar_start"].iloc[0].utcoffset()), "-1 day, 20:00:00")  # EDT
        self.assertEqual(str(after["bar_start"].iloc[0].utcoffset()), "-1 day, 19:00:00")   # EST
        self.assertEqual(after["expected_bars"].tolist(), [240, 240, 240, 240, 240, 180])

    def test_closed_and_non_trading_dates_produce_no_rows(self):
        self.assertTrue(expected_timeframe_schedule(THU, "4H", EARLY_SPEC).empty)  # verified CLOSED override
        self.assertTrue(expected_timeframe_schedule(date(2026, 9, 26), "4H", SPEC).empty)  # Saturday
        mixed = expected_timeframe_schedule([WED, THU, FRI], "1D", EARLY_SPEC)
        self.assertEqual(mixed["trading_date"].tolist(), [WED, FRI])
        empty = expected_timeframe_schedule([], "4H", SPEC)
        self.assertEqual(list(empty.columns), SCHEDULE_COLUMNS)
        self.assertTrue(empty.empty)

    def test_unverified_missing_session_is_still_expected(self):
        # Without an override, a weekday is an expected session even if no source data exists for it.
        self.assertEqual(len(expected_timeframe_schedule(THU, "4H", SPEC)), 6)


if __name__ == "__main__":
    unittest.main()
