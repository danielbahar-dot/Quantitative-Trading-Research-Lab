"""Generic multi-timeframe Swing detector tests (SW-I2). Synthetic data only.

The fixture builds canonical 1m source bars over the expected schedule of the
TARGET timeframe with an exact high and low per target observation: the first
minute of each target bucket carries the high and every minute sits at the
low, so the M3 (or direct 1m) observation extremes are fully controlled.
"""

from datetime import date, timedelta
import unittest
from unittest import mock

import pandas as pd

from src.data.continuity import continuity_segments
from src.data.sessions import load_session_spec, with_calendar_overrides
from src.data.timeframes import TimeframeSpec, build_timeframe, expected_timeframe_schedule
from src.market_structure import swing_detector
from src.market_structure.swing import (
    LOWER,
    SWING_COLUMNS,
    SWING_TIMEFRAMES,
    UPPER,
    SwingContractError,
    SwingDefinitionSpec,
    bar_span_ref,
    swing_id,
    validate_swing_points,
)
from src.market_structure.swing_detector import build_swing_points

SPEC = load_session_spec()
NY = "America/New_York"
BASE = 20000.0
REF22 = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2)
DEF11 = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=1, right_depth=1)
DEF12 = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=1, right_depth=2)
DAYS = [date(2026, 9, 14) + timedelta(days=d) for d in range(19) if (date(2026, 9, 14) + timedelta(days=d)).weekday() < 5]
WED, FRI = date(2026, 9, 23), date(2026, 9, 25)
EARLY_SPEC = with_calendar_overrides(
    SPEC,
    [
        {"trading_date": "2026-09-23", "kind": "MODIFIED", "close_et": "13:00", "reason": "synthetic early close"},
        {"trading_date": "2026-09-24", "kind": "CLOSED", "reason": "synthetic closure"},
    ],
    coverage_start="2026-09-01",
    coverage_end="2026-09-30",
)
ONE_MINUTE = TimeframeSpec("1m", 1)


def schedule(tf, spec=SPEC, dates=DAYS):
    return expected_timeframe_schedule(dates, ONE_MINUTE if tf == "1m" else tf, spec).reset_index(drop=True)


def bars_for(tf, highs, lows=None, *, contracts=None, absent=(), incomplete=(), spec=SPEC, dates=DAYS):
    """Canonical 1m bars whose ``tf`` observations k = 0..len(highs)-1 have exactly highs[k] / lows[k]."""
    sched = schedule(tf, spec, dates)
    lows = lows if lows is not None else [h - 50 for h in highs]
    frames = []
    for k in range(len(highs)):
        if k in absent:
            continue
        row = sched.iloc[k]
        minutes = pd.date_range(row["bar_start"] + pd.Timedelta(minutes=1), row["bar_end"], freq="min")
        if k in incomplete:
            minutes = minutes[:-1]
        low, high = BASE + lows[k], BASE + highs[k]
        frame = pd.DataFrame({"open": low, "high": low, "low": low, "close": low, "volume": 1,
                              "contract": contracts[k] if contracts else "MNQ 12-26"}, index=minutes)
        frame.iloc[0, frame.columns.get_loc("high")] = high
        frames.append(frame)
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="timestamp_et")
    return out


def detect(bars, tf, definition=REF22, spec=SPEC):
    return build_swing_points(bars, tf, spec, definition, instrument_id="MNQ")


def side(out, orientation):
    return out[out["orientation"] == orientation].reset_index(drop=True)


def ends(tf, spec=SPEC, dates=DAYS):
    return [ts.tz_convert("UTC") for ts in schedule(tf, spec, dates)["bar_end"]]


class BasicDetectorTests(unittest.TestCase):
    def test_valid_upper_and_lower(self):
        out = detect(bars_for("5m", [100, 103, 110, 106, 105], lows=[60, 57, 50, 54, 55]), "5m")
        e = ends("5m")
        hi, lo = side(out, UPPER), side(out, LOWER)
        self.assertEqual((len(hi), len(lo)), (1, 1))
        self.assertEqual((hi.loc[0, "price"], hi.loc[0, "source_at"], hi.loc[0, "available_at"]), (BASE + 110, e[2], e[4]))
        self.assertEqual((lo.loc[0, "price"], lo.loc[0, "source_at"], lo.loc[0, "available_at"]), (BASE + 50, e[2], e[4]))

    def test_strict_one_tick_invalidation_and_successor(self):
        out = side(detect(bars_for("5m", [100, 103, 110, 110.25, 108, 107]), "5m"), UPPER)
        self.assertEqual(out["price"].tolist(), [BASE + 110.25])  # 110 invalidated; 110.25 is its own swing
        out = side(detect(bars_for("5m", [100, 103, 110, 111, 108, 107]), "5m"), UPPER)
        self.assertEqual(out["price"].tolist(), [BASE + 111])

    def test_explicit_depths(self):
        bars = bars_for("5m", [100, 110, 105, 104, 120, 119, 118])
        e = ends("5m")
        one_two = side(detect(bars, "5m", DEF12), UPPER)  # L=1, R=2
        self.assertEqual(list(zip(one_two["price"], one_two["available_at"])), [(BASE + 110, e[3]), (BASE + 120, e[6])])
        two_two = side(detect(bars, "5m", REF22), UPPER)  # L=2 excludes 110 (needs 2 left bars)
        self.assertEqual(two_two["price"].tolist(), [BASE + 120])
        self.assertTrue((two_two["left_depth"] == 2).all() and (one_two["left_depth"] == 1).all())


class PlateauTests(unittest.TestCase):
    def test_one_two_and_three_bar_plateaus(self):
        e = ends("5m")
        for highs, (a, b) in (([98, 100, 110, 105, 104], (2, 2)),
                              ([98, 100, 110, 110, 105, 104], (2, 3)),
                              ([98, 100, 110, 110, 110, 105, 104], (2, 4))):
            with self.subTest(highs=highs):
                out = side(detect(bars_for("5m", highs), "5m"), UPPER)
                self.assertEqual(len(out), 1)
                swing = out.iloc[0]
                self.assertEqual((swing["source_at"], swing["source_end_at"], swing["available_at"]), (e[a], e[b], e[b + 2]))
                self.assertEqual(swing["source_ref"], bar_span_ref(instrument_id="MNQ", contract="MNQ 12-26", timeframe="5m",
                                                                   first_bar_end=e[a], last_bar_end=e[b]))

    def test_4h_plateau_across_session_boundary(self):
        # buckets 0-5 are the first trading day (bucket 5 = 14:00-17:00), bucket 6 is the next 18:00-22:00
        highs = [90, 91, 92, 95, 100, 110, 110, 104, 103]
        out = side(detect(bars_for("4H", highs), "4H"), UPPER)
        sched = schedule("4H")
        self.assertTrue(bool(sched.loc[5, "is_session_truncated"]))
        self.assertEqual((sched.loc[5, "bar_end"].hour, sched.loc[6, "bar_start"].hour), (17, 18))
        e = ends("4H")
        self.assertEqual(len(out), 1)
        self.assertEqual((out.loc[0, "source_at"], out.loc[0, "source_end_at"], out.loc[0, "available_at"]), (e[5], e[6], e[8]))

    def test_real_breaks_terminate_plateaus(self):
        # equal 110s on either side of a break are two separate (unconfirmable) candidates, never one plateau
        highs = [90, 95, 100, 110, 110, 104, 103, 102]
        cases = {
            "missing bucket": dict(tf="5m", absent={4}, highs=[90, 95, 100, 110, 0, 110, 104, 103]),
            "incomplete": dict(tf="5m", incomplete={4}, highs=[90, 95, 100, 110, 110, 110, 104, 103]),
            "contract": dict(tf="5m", contracts=["A"] * 4 + ["B"] * 4, highs=highs),
        }
        for name, case in cases.items():
            with self.subTest(name):
                tf = case.pop("tf")
                out = side(detect(bars_for(tf, case.pop("highs"), **case), tf), UPPER)
                self.assertTrue(out.empty, out)
        # missing session: 4H, day 2 absent; equal 110s at the end of day 1 and start of day 3
        highs = [90, 95, 100, 104, 105, 110] + [0] * 6 + [110, 104, 103, 102, 101, 100]
        out = side(detect(bars_for("4H", highs, absent=set(range(6, 12))), "4H"), UPPER)
        self.assertTrue(out.empty)


class EqualityTests(unittest.TestCase):
    def test_separated_equal_extrema_both_confirm(self):
        e = ends("5m")
        hi = side(detect(bars_for("5m", [100, 110, 105, 110, 100]), "5m", DEF11), UPPER)
        self.assertEqual(list(zip(hi["source_at"], hi["available_at"])), [(e[1], e[2]), (e[3], e[4])])
        lows = [110, 100, 105, 100, 110]
        lo = side(detect(bars_for("5m", [l + 50 for l in lows], lows), "5m", DEF11), LOWER)
        self.assertEqual(list(zip(lo["price"], lo["source_at"])), [(BASE + 100, e[1]), (BASE + 100, e[3])])

    def test_b_prime_equal_inside_each_others_windows(self):
        e = ends("5m")
        hi = side(detect(bars_for("5m", [98, 100, 110, 105, 110, 100, 99]), "5m", REF22), UPPER)
        self.assertEqual(list(zip(hi["source_at"], hi["available_at"])), [(e[2], e[4]), (e[4], e[6])])

    def test_equality_never_invalidates_but_one_tick_does(self):
        # 110 / 109.75 / 110: the separated equal 110s both confirm (L=R=1)
        self.assertEqual(len(side(detect(bars_for("5m", [100, 105, 110, 109.75, 110, 100]), "5m", DEF11), UPPER)), 2)
        # 110 then 110.25 inside its right window: one tick invalidates 110; 110.25 confirms
        out = side(detect(bars_for("5m", [100, 105, 110, 110.25, 100]), "5m", DEF11), UPPER)
        self.assertEqual(out["price"].tolist(), [BASE + 110.25])


class BoundaryTests(unittest.TestCase):
    def test_insufficient_left_history(self):
        self.assertTrue(side(detect(bars_for("5m", [100, 110, 105, 104]), "5m"), UPPER).empty)

    def test_insufficient_future_at_dataset_end(self):
        self.assertTrue(side(detect(bars_for("5m", [100, 103, 110, 106]), "5m"), UPPER).empty)

    def test_insufficient_future_at_segment_end(self):
        bars = bars_for("5m", [100, 103, 110, 106, 0, 105, 104, 103, 102], absent={4})
        self.assertTrue(side(detect(bars, "5m"), UPPER).empty)


class ContinuityTests(unittest.TestCase):
    def check_segment_bounded(self, **kwargs):
        # a confirmable pattern split by the break: neither side has enough observations
        out = side(detect(bars_for("5m", [100, 103, 110, 106, 105, 104, 103, 102], **kwargs), "5m"), UPPER)
        return out

    def test_incomplete_bar(self):
        self.assertTrue(self.check_segment_bounded(incomplete={3}).empty)

    def test_missing_expected_bucket(self):
        self.assertTrue(self.check_segment_bounded(absent={3}).empty)

    def test_contract_change(self):
        self.assertTrue(self.check_segment_bounded(contracts=["A"] * 3 + ["B"] * 5).empty)

    def test_missing_expected_session(self):
        highs = [90, 95, 100, 104, 110, 104] + [0] * 6 + [100, 101, 103, 101, 100, 99]
        out = side(detect(bars_for("4H", highs, absent=set(range(6, 12))), "4H"), UPPER)
        e = ends("4H")
        self.assertEqual(out["source_at"].tolist(), [e[14]])  # 110 lacks R=2 inside its segment; 103 confirms

    def test_detection_inside_each_segment(self):
        highs = [100, 103, 110, 106, 105, 0, 100, 103, 112, 106, 105]
        out = side(detect(bars_for("5m", highs, absent={5}), "5m"), UPPER)
        self.assertEqual(out["price"].tolist(), [BASE + 110, BASE + 112])
        self.assertEqual(out["contract"].nunique(), 1)


class ScheduleTests(unittest.TestCase):
    def test_session_truncated_4h_source(self):
        highs = [90, 91, 92, 100, 104, 110, 104, 103]
        out = side(detect(bars_for("4H", highs), "4H"), UPPER)
        e = ends("4H")
        self.assertEqual((out.loc[0, "source_at"], out.loc[0, "available_at"]), (e[5], e[7]))
        self.assertTrue(bool(schedule("4H").loc[5, "is_session_truncated"]))

    def test_verified_shortened_session(self):
        dates = [date(2026, 9, 22), WED, FRI]  # WED closes 13:00 (last bucket 10-13), THU verified closed
        sched = schedule("4H", EARLY_SPEC, dates)
        self.assertEqual(len(sched), 6 + 5 + 6)
        highs = [90, 91, 92, 93, 94, 95, 96, 97, 100, 104, 110, 104, 103, 102]
        out = side(detect(bars_for("4H", highs, spec=EARLY_SPEC, dates=dates), "4H", spec=EARLY_SPEC), UPPER)
        e = ends("4H", EARLY_SPEC, dates)
        self.assertTrue(bool(sched.loc[10, "is_session_truncated"]))
        self.assertEqual((out.loc[0, "source_at"], out.loc[0, "available_at"]), (e[10], e[12]))  # confirmed on FRI

    def test_weekend_is_not_a_break(self):
        days = DAYS[:5]  # MON..FRI, next week continues
        k = 6 * 4 + 5   # FRI 14:00-17:00 bucket of the first week
        highs = [80] * (k - 2) + [90, 100, 110, 104, 103]
        out = side(detect(bars_for("4H", highs), "4H"), UPPER)
        e = ends("4H")
        self.assertEqual(days[-1].weekday(), 4)
        self.assertEqual((out.loc[0, "source_at"], out.loc[0, "available_at"]), (e[k], e[k + 2]))
        nxt = schedule("4H").loc[k + 1, "bar_start"].tz_convert(NY)
        self.assertEqual((nxt.weekday(), nxt.hour), (6, 18))  # the next observation opens Sunday 18:00 ET

    def test_daily_weekend_continuity(self):
        out = side(detect(bars_for("1D", [100, 103, 110, 106, 105]), "1D"), UPPER)  # FRI peak? index 2 = WED
        e = ends("1D")
        self.assertEqual((out.loc[0, "source_at"], out.loc[0, "available_at"]), (e[2], e[4]))
        out = side(detect(bars_for("1D", [100, 101, 102, 103, 110, 106, 105]), "1D"), UPPER)  # FRI peak, MON/TUE confirm
        self.assertEqual((out.loc[0, "source_at"], out.loc[0, "available_at"]), (e[4], e[6]))


class StructuralTests(unittest.TestCase):
    def test_same_observation_upper_and_lower(self):
        out = detect(bars_for("5m", [100, 101, 105, 102, 101], lows=[95, 94, 90, 93, 94]), "5m")
        self.assertEqual(set(out["orientation"]), {UPPER, LOWER})
        self.assertEqual(out["source_at"].nunique(), 1)

    def test_no_alternation(self):
        flat_lows = [50] * 7
        out = detect(bars_for("5m", [100, 105, 100, 106, 100, 107, 100], flat_lows), "5m", DEF11)
        self.assertEqual(out["orientation"].tolist(), [UPPER, UPPER, UPPER])

    def test_reference_22_counts_synthetic(self):
        highs = [10, 11, 12, 11, 10, 11, 13, 12, 11, 10]
        out = detect(bars_for("5m", highs, lows=[h - 5 for h in highs]), "5m", REF22)
        self.assertEqual((len(side(out, UPPER)), len(side(out, LOWER))), (2, 1))


class MultiTimeframeTests(unittest.TestCase):
    PATTERN_H = [100, 103, 110, 106, 105]
    PATTERN_L = [60, 57, 50, 54, 55]

    def test_every_supported_timeframe(self):
        self.assertEqual(SWING_TIMEFRAMES, ("1m", "5m", "15m", "1H", "4H", "1D"))
        for tf in SWING_TIMEFRAMES:
            with self.subTest(tf=tf):
                out = detect(bars_for(tf, self.PATTERN_H, self.PATTERN_L), tf)
                e = ends(tf)
                self.assertEqual(out["timeframe"].unique().tolist(), [tf])
                hi, lo = side(out, UPPER), side(out, LOWER)
                self.assertEqual((hi.loc[0, "price"], lo.loc[0, "price"]), (BASE + 110, BASE + 50))
                self.assertEqual((hi.loc[0, "source_at"], hi.loc[0, "available_at"]), (e[2], e[4]))
                pd.testing.assert_frame_equal(validate_swing_points(out, REF22), out)

    def test_same_generic_detector_for_every_timeframe(self):
        for tf in SWING_TIMEFRAMES:
            with self.subTest(tf=tf), mock.patch.object(
                    swing_detector, "_confirmed_plateaus", wraps=swing_detector._confirmed_plateaus) as spy:
                detect(bars_for(tf, self.PATTERN_H, self.PATTERN_L), tf)
                self.assertEqual(spy.call_count, 2)  # one segment x two orientations
                self.assertEqual({call.args[1:] for call in spy.call_args_list}, {(2, 2)})

    def test_higher_timeframes_use_m3_and_1m_does_not(self):
        for tf in SWING_TIMEFRAMES:
            with self.subTest(tf=tf), mock.patch.object(swing_detector, "build_timeframe", wraps=build_timeframe) as m3:
                detect(bars_for(tf, self.PATTERN_H, self.PATTERN_L), tf)
                if tf == "1m":
                    m3.assert_not_called()
                else:
                    m3.assert_called_once()
                    self.assertEqual(m3.call_args.args[1], tf)

    def test_timeframe_independence(self):
        bars = bars_for("15m", self.PATTERN_H, self.PATTERN_L)
        alone = detect(bars, "15m")
        for other in ("1m", "5m", "1H"):
            detect(bars, other)
        pd.testing.assert_frame_equal(detect(bars, "15m"), alone)


class OneMinuteTests(unittest.TestCase):
    def test_direct_canonical_observations_preserve_source(self):
        bars = bars_for("1m", [100, 103, 110, 106, 105], [60, 57, 50, 54, 55])
        prepared = swing_detector._one_minute_observations(bars, SPEC, "1min")
        for column in ("open", "high", "low", "close", "volume", "contract"):
            self.assertEqual(prepared[column].tolist(), bars[column].tolist(), column)
        self.assertTrue((pd.DatetimeIndex(prepared["bar_end"]) == bars.index).all())
        self.assertTrue((prepared["available_at"] == prepared["bar_end"]).all())
        self.assertTrue((prepared["bar_end"] - prepared["bar_start"] == pd.Timedelta(minutes=1)).all())
        self.assertTrue(((prepared["observed_bars"] == 1) & (prepared["expected_bars"] == 1) & prepared["is_complete"]).all())
        self.assertFalse(prepared["is_session_truncated"].any())
        self.assertEqual(prepared["timeframe"].unique().tolist(), ["1m"])

    def test_direct_path_matches_m3_one_minute_cross_check(self):
        bars = bars_for("1m", [100, 103, 110, 106, 105, 0, 104, 103, 111, 102, 101], absent={5})
        direct = swing_detector._one_minute_observations(bars, SPEC, "1min")
        m3 = build_timeframe(bars, ONE_MINUTE, SPEC)  # test-only cross-check
        for column in ("trading_date", "bar_start", "bar_end", "high", "low", "contract", "expected_bars",
                       "observed_bars", "is_complete", "is_session_truncated"):
            self.assertEqual(direct[column].tolist(), m3[column].tolist(), column)
        d_segs, d_breaks = continuity_segments(direct, ONE_MINUTE, SPEC)
        m_segs, m_breaks = continuity_segments(m3, ONE_MINUTE, SPEC)
        self.assertEqual([len(s) for s in d_segs], [len(s) for s in m_segs])
        pd.testing.assert_frame_equal(d_breaks, m_breaks)

    def test_one_minute_output_and_bad_interval(self):
        out = detect(bars_for("1m", [100, 103, 110, 106, 105], [60, 57, 50, 54, 55]), "1m")
        self.assertEqual(out["timeframe"].unique().tolist(), ["1m"])
        with self.assertRaisesRegex(SwingContractError, "1-minute source interval"):
            build_swing_points(bars_for("1m", [100, 103]), "1m", SPEC, REF22, instrument_id="MNQ", source_interval="5min")


class CausalityAndContractTests(unittest.TestCase):
    def test_timing_invariant_and_identity(self):
        out = detect(bars_for("5m", [98, 100, 110, 110, 105, 104, 103, 109, 101, 100]), "5m", REF22)
        self.assertTrue(((out["source_at"] <= out["source_end_at"]) & (out["source_end_at"] < out["available_at"])).all())
        for row in out.itertuples(index=False):
            self.assertEqual(row.swing_id, swing_id(
                definition_version=row.definition_version, instrument_id=row.instrument_id, contract_scope=row.contract_scope,
                contract=row.contract, timeframe=row.timeframe, orientation=row.orientation, left_depth=row.left_depth,
                right_depth=row.right_depth, source_ref=row.source_ref))
        self.assertEqual(list(out.columns), list(SWING_COLUMNS))

    def test_shuffled_input_is_deterministic(self):
        bars = bars_for("1m", [100, 103, 110, 106, 105, 104, 108, 103, 102], [60, 57, 50, 54, 55, 51, 56, 52, 53])
        for tf in ("1m", "5m"):
            base = detect(bars if tf == "1m" else bars_for("5m", [100, 103, 110, 106, 105]), tf)
            source = bars if tf == "1m" else bars_for("5m", [100, 103, 110, 106, 105])
            for seed in range(3):
                pd.testing.assert_frame_equal(detect(source.sample(frac=1, random_state=seed), tf), base)

    def test_errors(self):
        bars = bars_for("5m", [100, 103, 110, 106, 105])
        with self.assertRaisesRegex(SwingContractError, "tick grid"):
            detect(bars_for("5m", [100, 103, 110.1, 106, 105]), "5m")
        for bad in ("2H", TimeframeSpec("5m", 5), None):
            with self.subTest(tf=bad), self.assertRaisesRegex(SwingContractError, "timeframe"):
                build_swing_points(bars, bad, SPEC, REF22, instrument_id="MNQ")
        with self.assertRaises(TypeError):
            build_swing_points(bars, "5m", SPEC, instrument_id="MNQ")  # type: ignore[call-arg]
        with self.assertRaisesRegex(SwingContractError, "SwingDefinitionSpec"):
            build_swing_points(bars, "5m", SPEC, {"left_depth": 2}, instrument_id="MNQ")
        with self.assertRaisesRegex(SwingContractError, "canonical"):
            build_swing_points(bars, "5m", SPEC, REF22, instrument_id="mnq")
        with self.assertRaises(SwingContractError):
            build_swing_points(bars.iloc[0:0], "5m", SPEC, REF22, instrument_id="MNQ")  # M3 source error translated

    def test_empty_result(self):
        out = detect(bars_for("5m", [100, 101, 102, 103, 104], lows=[50, 51, 52, 53, 54]), "5m")
        self.assertTrue(out.empty)
        self.assertEqual(list(out.columns), list(SWING_COLUMNS))
        validate_swing_points(out, REF22)


if __name__ == "__main__":
    unittest.main()
