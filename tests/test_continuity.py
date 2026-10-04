"""Generic expected-schedule continuity tests (SW-I0, D-137). Synthetic data only.

Fixtures build canonical 1m bars over the M3 expected 4H schedule (one price
per bucket), so presence, completeness and contract of every 4H bucket are
controlled exactly.
"""

from datetime import date
from pathlib import Path
import unittest

import pandas as pd

from src.data.continuity import (
    BREAK_COLUMNS,
    BREAK_PRECEDENCE,
    CONTRACT_CHANGE,
    INCOMPLETE_BAR,
    MISSING_EXPECTED_BUCKET,
    MISSING_EXPECTED_SESSION,
    ContinuityError,
    continuity_segments,
)
from src.data.sessions import load_session_spec, with_calendar_overrides
from src.data.timeframes import TimeframeSpec, build_timeframe, expected_timeframe_schedule
from src.features.external_liquidity import ExternalLiquidityError
from src.features.external_liquidity import continuity_segments as external_continuity_segments

SPEC = load_session_spec()
MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (21, 22, 23, 24, 25))
EARLY_SPEC = with_calendar_overrides(
    SPEC,
    [
        {"trading_date": "2026-09-23", "kind": "MODIFIED", "close_et": "13:00", "reason": "synthetic early close"},
        {"trading_date": "2026-09-24", "kind": "CLOSED", "reason": "synthetic closure"},
    ],
    coverage_start="2026-09-01",
    coverage_end="2026-09-30",
)


def bars_1m(dates, *, spec=SPEC, contracts=None, absent=(), incomplete=()):
    """1m bars over the expected 4H buckets of ``dates`` (flattened bucket index k)."""
    schedule = expected_timeframe_schedule(dates, "4H", spec).reset_index(drop=True)
    frames = []
    for k, row in schedule.iterrows():
        if k in absent:
            continue
        minutes = pd.date_range(row["bar_start"] + pd.Timedelta(minutes=1), row["bar_end"], freq="min")
        if k in incomplete:
            minutes = minutes[:-1]
        frames.append(pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1,
                                    "contract": contracts[k] if contracts else "MNQ 12-26"}, index=minutes))
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="timestamp_et")
    return out


def segments(bars, timeframe="4H", spec=SPEC):
    return continuity_segments(build_timeframe(bars, timeframe, spec), timeframe, spec)


class SegmentationTests(unittest.TestCase):
    def test_contiguous_expected_observations_form_one_segment(self):
        segs, breaks = segments(bars_1m([TUE, WED]))
        self.assertEqual([len(s) for s in segs], [12])
        self.assertTrue(breaks.empty)
        self.assertEqual(list(breaks.columns), BREAK_COLUMNS)
        ends = list(segs[0]["bar_end"])
        self.assertEqual(ends, sorted(ends))

    def test_complete_session_truncated_observation_is_valid(self):
        segs, _ = segments(bars_1m([TUE, WED]))
        seg = segs[0].reset_index(drop=True)
        truncated = seg.index[seg["is_session_truncated"]].tolist()
        self.assertEqual(len(truncated), 2)  # TUE and WED 14:00-17:00 buckets
        first = truncated[0]
        self.assertTrue(bool(seg.loc[first, "is_complete"]))
        self.assertEqual(seg.loc[first, "bar_end"].hour, 17)
        self.assertEqual(seg.loc[first + 1, "bar_start"].hour, 18)  # next expected session, no break

    def test_missing_expected_bucket_breaks(self):
        bars = bars_1m([TUE], absent={2})
        self.assertEqual(len(build_timeframe(bars, "4H", SPEC)), 5)
        segs, breaks = segments(bars)
        self.assertEqual([len(s) for s in segs], [2, 3])
        row = breaks.iloc[0]
        self.assertEqual((row["reason"], row["missing_buckets"], row["missing_sessions"], row["incomplete_bars"]),
                         (MISSING_EXPECTED_BUCKET, 1, 0, 0))

    def test_missing_expected_session_breaks(self):
        segs, breaks = segments(bars_1m([MON, TUE, WED], absent=set(range(6, 12))))
        self.assertEqual([len(s) for s in segs], [6, 6])
        row = breaks.iloc[0]
        self.assertEqual((row["reason"], row["missing_buckets"], row["missing_sessions"]), (MISSING_EXPECTED_SESSION, 6, 1))
        daily_segs, daily_breaks = segments(bars_1m([MON, TUE, WED], absent=set(range(6, 12))), "1D")
        self.assertEqual([len(s) for s in daily_segs], [1, 1])
        self.assertEqual(daily_breaks["reason"].tolist(), [MISSING_EXPECTED_SESSION])

    def test_incomplete_observation_breaks_and_is_excluded(self):
        bars = bars_1m([TUE], incomplete={3})
        segs, breaks = segments(bars)
        self.assertEqual([len(s) for s in segs], [3, 2])
        self.assertTrue(all(bool(c) for s in segs for c in s["is_complete"]))
        self.assertEqual((breaks.iloc[0]["reason"], breaks.iloc[0]["incomplete_bars"]), (INCOMPLETE_BAR, 1))

    def test_contract_change_breaks(self):
        segs, breaks = segments(bars_1m([TUE], contracts=["MNQ 09-26"] * 3 + ["MNQ 12-26"] * 3))
        self.assertEqual([len(s) for s in segs], [3, 3])
        self.assertEqual((breaks.iloc[0]["reason"], bool(breaks.iloc[0]["contract_changed"])), (CONTRACT_CHANGE, True))
        self.assertEqual({s["contract"].nunique() for s in segs}, {1})


class PrecedenceTests(unittest.TestCase):
    def test_order(self):
        self.assertEqual(BREAK_PRECEDENCE,
                         (MISSING_EXPECTED_SESSION, MISSING_EXPECTED_BUCKET, INCOMPLETE_BAR, CONTRACT_CHANGE))

    def test_session_outranks_contract_and_flag_is_kept(self):
        contracts = ["MNQ 09-26"] * 6 + ["X"] * 6 + ["MNQ 12-26"] * 6
        _, breaks = segments(bars_1m([MON, TUE, WED], contracts=contracts, absent=set(range(6, 12))))
        row = breaks.iloc[0]
        self.assertEqual((row["reason"], bool(row["contract_changed"])), (MISSING_EXPECTED_SESSION, True))

    def test_bucket_outranks_incomplete(self):
        _, breaks = segments(bars_1m([TUE], absent={2}, incomplete={3}))
        row = breaks.iloc[0]
        self.assertEqual((row["reason"], row["missing_buckets"], row["incomplete_bars"]), (MISSING_EXPECTED_BUCKET, 1, 1))

    def test_incomplete_outranks_contract(self):
        contracts = ["MNQ 09-26"] * 3 + ["MNQ 12-26"] * 3
        _, breaks = segments(bars_1m([TUE], contracts=contracts, incomplete={2}))
        row = breaks.iloc[0]
        self.assertEqual((row["reason"], bool(row["contract_changed"])), (INCOMPLETE_BAR, True))


class ScheduleAndBoundaryTests(unittest.TestCase):
    def test_verified_overrides_follow_the_schedule(self):
        # WED closes 13:00 (5 buckets), THU is a verified closure: not a missing session.
        segs, breaks = segments(bars_1m([TUE, WED, FRI], spec=EARLY_SPEC), spec=EARLY_SPEC)
        self.assertEqual([len(s) for s in segs], [6 + 5 + 6])
        self.assertTrue(breaks.empty)
        wed = segs[0][segs[0]["trading_date"] == WED]
        self.assertTrue(bool(wed["is_session_truncated"].iloc[-1]))
        self.assertEqual(wed["bar_end"].iloc[-1].hour, 13)

    def test_gaps_outside_the_observed_span_are_not_breaks(self):
        segs, breaks = segments(bars_1m([TUE, WED], absent={0, 1, 10, 11}))
        self.assertEqual([len(s) for s in segs], [8])
        self.assertTrue(breaks.empty)

    def test_incomplete_first_and_last_observations_are_excluded_without_break_rows(self):
        segs, breaks = segments(bars_1m([TUE, WED], incomplete={0, 11}))
        self.assertEqual([len(s) for s in segs], [10])
        self.assertTrue(breaks.empty)

    def test_one_minute_expected_schedule(self):
        bars = bars_1m([TUE])
        bars = bars.drop(bars.index[100])
        spec_1m = TimeframeSpec("1m", 1)
        segs, breaks = continuity_segments(build_timeframe(bars, spec_1m, SPEC), spec_1m, SPEC)
        self.assertEqual([len(s) for s in segs], [100, len(bars) - 100])
        self.assertEqual((breaks.iloc[0]["reason"], breaks.iloc[0]["missing_buckets"]), (MISSING_EXPECTED_BUCKET, 1))

    def test_empty_input(self):
        segs, breaks = continuity_segments(build_timeframe(bars_1m([TUE]), "4H", SPEC).iloc[0:0], "4H", SPEC)
        self.assertEqual(segs, [])
        self.assertTrue(breaks.empty)
        self.assertEqual(list(breaks.columns), BREAK_COLUMNS)


class DeterminismAndErrorTests(unittest.TestCase):
    def test_row_order_does_not_change_output(self):
        tf_bars = build_timeframe(bars_1m([MON, TUE, WED], absent={4, 13}, incomplete={8}), "4H", SPEC)
        base_segs, base_breaks = continuity_segments(tf_bars, "4H", SPEC)
        for seed in range(3):
            segs, breaks = continuity_segments(tf_bars.sample(frac=1, random_state=seed), "4H", SPEC)
            self.assertEqual(len(segs), len(base_segs))
            for got, want in zip(segs, base_segs):
                pd.testing.assert_frame_equal(got, want)
            pd.testing.assert_frame_equal(breaks, base_breaks)

    def test_observation_off_the_schedule_raises_continuity_error(self):
        tf_bars = build_timeframe(bars_1m([TUE]), "4H", SPEC)
        tf_bars.loc[tf_bars.index[1], "bar_start"] += pd.Timedelta(minutes=30)
        with self.assertRaisesRegex(ContinuityError, "not in the expected M3 schedule"):
            continuity_segments(tf_bars, "4H", SPEC)

    def test_external_wrapper_translates_the_error(self):
        tf_bars = build_timeframe(bars_1m([TUE]), "4H", SPEC)
        tf_bars.loc[tf_bars.index[1], "bar_start"] += pd.Timedelta(minutes=30)
        with self.assertRaisesRegex(ExternalLiquidityError, "4H: an observed bar is not in the expected M3 schedule") as raised:
            external_continuity_segments(tf_bars, "4H", SPEC)
        self.assertIsInstance(raised.exception.__cause__, ContinuityError)

    def test_external_wrapper_matches_shared_output(self):
        tf_bars = build_timeframe(bars_1m([MON, TUE, WED], absent={4, 13}, incomplete={8}), "4H", SPEC)
        shared, external = continuity_segments(tf_bars, "4H", SPEC), external_continuity_segments(tf_bars, "4H", SPEC)
        for got, want in zip(external[0], shared[0]):
            pd.testing.assert_frame_equal(got, want)
        pd.testing.assert_frame_equal(external[1], shared[1])

    def test_module_has_no_feature_or_liquidity_dependency(self):
        source = Path(__file__).resolve().parents[1].joinpath("src", "data", "continuity.py").read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
        self.assertFalse([line for line in imports if "src.features" in line or "src.liquidity" in line
                          or "src.signals" in line or "src.state" in line])


if __name__ == "__main__":
    unittest.main()
