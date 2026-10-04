"""External Liquidity tests (EL-I2 / EL-I3). Synthetic data only.

Fixtures build canonical 1m bars from the M3 expected 4H schedule with an
exact high and low per 4H bucket (the first minute carries the high; every
minute sits at the bucket low), so Daily and 4H extremes are fully controlled.
"""

from datetime import date
import unittest

import numpy as np
import pandas as pd

from src.data.sessions import load_session_spec, with_calendar_overrides
from src.data.timeframes import build_timeframe, expected_timeframe_schedule
from src.features.external_liquidity import (
    CONTRACT_CHANGE,
    DEFINITION_VERSION,
    INCOMPLETE_BAR,
    MISSING_EXPECTED_BUCKET,
    MISSING_EXPECTED_SESSION,
    ExternalLiquidityError,
    build_external_liquidity,
    continuity_segments,
    htf_source_ref,
    m5_context_ref,
)
from src.liquidity.contract import EQ, EXTENDED, FORMED, MERGED, REQ

TZ = "America/New_York"
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
CONTEXT_COLUMNS = ["context_id", "is_available", "observed_high", "observed_low", "target_trading_date",
                   "source_trading_date", "window_end", "available_at", "contract"]
EMPTY_CONTEXT = pd.DataFrame(columns=CONTEXT_COLUMNS)


def bars_for(dates, highs=None, lows=None, *, spec=SPEC, contracts=None, absent=(), incomplete=(), shift=None):
    """1m bars over the expected 4H buckets of ``dates`` (flattened index k across dates).

    Unspecified highs rise by 25 points per bucket from 3000 and unspecified lows fall by 25 points from 700,
    far from the test ranges (highs ~1500, lows ~900), so they never link unless a test sets them.
    """
    schedule = expected_timeframe_schedule(dates, "4H", spec).reset_index(drop=True)
    n = len(schedule)
    highs = list(highs or []) + [3000 + 25 * k for k in range(len(highs or []), n)]
    lows = list(lows or []) + [700 - 25 * k for k in range(len(lows or []), n)]
    frames = []
    for k, row in schedule.iterrows():
        if k in absent:
            continue
        minutes = pd.date_range(row["bar_start"] + pd.Timedelta(minutes=1), row["bar_end"], freq="min")
        if k in incomplete:
            minutes = minutes[:-1]
        low, high = float(lows[k]), float(highs[k])
        frame = pd.DataFrame({"open": low, "high": low, "low": low, "close": low, "volume": 1,
                              "contract": (contracts[k] if contracts else "MNQ 12-26")}, index=minutes)
        frame.iloc[0, frame.columns.get_loc("high")] = high
        frames.append(frame)
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="timestamp_et")
    return out


def build(bars, context=EMPTY_CONTEXT, spec=SPEC):
    return build_external_liquidity(bars, spec, instrument_id="MNQ", market_context=context)


def bucket_ends(dates, spec=SPEC):
    return list(expected_timeframe_schedule(dates, "4H", spec)["bar_end"])


def four_hour(result, stype=None, orientation="UPPER"):
    frame = result.structures
    frame = frame[(frame["reference_family"] == "4H") & (frame["orientation"] == orientation)]
    return frame if stype is None else frame[frame["structure_type"] == stype]


def member_prices(result, structure_row):
    by_id = result.members.set_index("member_id")
    return sorted(by_id.loc[list(structure_row["member_ids"]), "price"].tolist())


class DailyMemberTests(unittest.TestCase):
    def test_complete_day_creates_high_and_low(self):
        result = build(bars_for([TUE]))
        daily = result.members[result.members["reference_family"] == "1D"]
        self.assertEqual(sorted(daily["member_kind"]), ["DAILY_HIGH", "DAILY_LOW"])
        day_bar = build_timeframe(bars_for([TUE]), "1D", SPEC).iloc[0]
        high = daily[daily["member_kind"] == "DAILY_HIGH"].iloc[0]
        self.assertEqual(high["price"], day_bar["high"])
        self.assertEqual(high["orientation"], "UPPER")
        self.assertEqual(high["source_at"], day_bar["bar_end"])
        self.assertEqual(high["available_at"], day_bar["bar_end"])
        self.assertEqual((high["contract"], high["contract_scope"]), ("MNQ 12-26", "SPECIFIC"))
        self.assertEqual(high["source_ref"], htf_source_ref("MNQ", "MNQ 12-26", "1D", day_bar["bar_end"]))
        self.assertTrue(result.structures.empty or not (result.structures["reference_family"] == "1D").any())

    def test_incomplete_day_creates_nothing(self):
        result = build(bars_for([TUE, WED], incomplete={7}))  # one minute missing on WED
        days = result.members[result.members["reference_family"] == "1D"]
        self.assertEqual(len(days), 2)
        self.assertEqual(set(days["source_at"].dt.tz_convert(TZ).dt.date), {TUE})

    def test_source_ref_is_timezone_canonical(self):
        end = pd.Timestamp("2026-09-22 17:00", tz=TZ)
        self.assertEqual(htf_source_ref("MNQ", "C", "1D", end), htf_source_ref("MNQ", "C", "1D", end.tz_convert("UTC")))
        self.assertIn("2026-09-22T21:00:00.000000000Z", htf_source_ref("MNQ", "C", "1D", end))


class SessionAndPreviousDayTests(unittest.TestCase):
    def context(self, rows):
        return pd.DataFrame(rows, columns=CONTEXT_COLUMNS)

    def row(self, context_id, high, low, *, target=WED, available=True, source=TUE):
        end = pd.Timestamp(f"{target.isoformat()} 05:00", tz=TZ)
        return {"context_id": context_id, "is_available": available, "observed_high": high, "observed_low": low,
                "target_trading_date": target, "source_trading_date": source, "window_end": end, "available_at": end,
                "contract": "MNQ 12-26"}

    def test_allowed_families_unavailable_and_excluded(self):
        rows = [self.row(ctx, 1500.0 + i, 1400.0 - i) for i, ctx in enumerate(
            ["asia_2000_0000", "london_0200_0500", "ny_premarket_0700_0900", "overnight_1800_0700"])]
        rows += [self.row("overnight_context_2000_0900", 1600.0, 1300.0), self.row("previous_rth", 1700.0, 1200.0),
                 self.row("asia_2000_0000", 1550.0, 1450.0, target=THU, available=False)]
        result = build(bars_for([TUE, WED]), self.context(rows))
        session = result.members[result.members["member_kind"].str.startswith("SESSION_REFERENCE")]
        self.assertEqual(len(session), 8)
        self.assertEqual(set(session["reference_family"]),
                         {"asia_2000_0000", "london_0200_0500", "ny_premarket_0700_0900", "overnight_1800_0700"})
        asia_high = session[(session["reference_family"] == "asia_2000_0000") & (session["orientation"] == "UPPER")].iloc[0]
        self.assertEqual(asia_high["source_ref"], m5_context_ref("asia_2000_0000", "high", WED))
        self.assertEqual(asia_high["member_kind"], "SESSION_REFERENCE_HIGH")

    def test_identical_prices_across_families_stay_separate(self):
        rows = [self.row("london_0200_0500", 1500.0, 1400.0), self.row("overnight_1800_0700", 1500.0, 1390.0)]
        result = build(bars_for([TUE, WED]), self.context(rows))
        highs = result.members[(result.members["member_kind"] == "SESSION_REFERENCE_HIGH")]
        self.assertEqual(len(highs), 2)
        self.assertEqual(highs["price"].tolist(), [1500.0, 1500.0])
        self.assertEqual(highs["member_id"].nunique(), 2)

    def test_previous_day_reference(self):
        bars = bars_for([TUE, WED])
        tue = build_timeframe(bars, "1D", SPEC).iloc[0]
        result = build(bars, self.context([self.row("previous_day", tue["high"], tue["low"])]))
        refs = result.previous_day_references
        self.assertEqual(len(refs), 2)
        daily = result.members[result.members["reference_family"] == "1D"].set_index("member_id")
        for ref in refs.itertuples(index=False):
            self.assertIn(ref.member_id, daily.index)
            self.assertEqual(ref.previous_trading_date, TUE)
            self.assertEqual(ref.target_trading_date, WED)
            self.assertEqual(ref.m5_context_ref, m5_context_ref("previous_day", ref.field, WED))
        self.assertFalse((result.members["reference_family"] == "previous_day").any())  # no duplicate member
        unavailable = build(bars, self.context([self.row("previous_day", tue["high"], tue["low"], available=False)]))
        self.assertTrue(unavailable.previous_day_references.empty)

    def test_previous_day_fails_closed(self):
        bars = bars_for([TUE, WED])
        tue = build_timeframe(bars, "1D", SPEC).iloc[0]
        with self.assertRaisesRegex(ExternalLiquidityError, "!= Daily member price"):
            build(bars, self.context([self.row("previous_day", tue["high"] + 0.25, tue["low"])]))
        with self.assertRaisesRegex(ExternalLiquidityError, "no canonical Daily member"):
            build(bars_for([TUE, WED], incomplete={2}),
                  self.context([self.row("previous_day", tue["high"], tue["low"])]))


class ContinuityTests(unittest.TestCase):
    def segments(self, bars, timeframe="4H", spec=SPEC):
        return continuity_segments(build_timeframe(bars, timeframe, spec), timeframe, spec)

    def test_adjacent_complete_buckets_and_session_boundary_are_continuous(self):
        segments, breaks = self.segments(bars_for([TUE, WED]))
        self.assertEqual(len(segments), 1)
        self.assertEqual(len(segments[0]), 12)  # includes 14:00-17:00 -> next session 18:00
        self.assertTrue(breaks.empty)

    def test_incomplete_middle_bucket_breaks(self):
        segments, breaks = self.segments(bars_for([TUE], incomplete={2}))
        self.assertEqual([len(s) for s in segments], [2, 3])
        self.assertEqual(breaks["reason"].tolist(), [INCOMPLETE_BAR])

    def test_absent_middle_bucket_breaks(self):
        bars = bars_for([TUE], absent={1})
        self.assertEqual(len(build_timeframe(bars, "4H", SPEC)), 5)  # M3 emits no row for it
        segments, breaks = self.segments(bars)
        self.assertEqual([len(s) for s in segments], [1, 4])
        self.assertEqual(breaks["reason"].tolist(), [MISSING_EXPECTED_BUCKET])

    def test_non_adjacent_same_date_bars_break(self):
        segments, breaks = self.segments(bars_for([TUE], absent={1, 2, 3, 4}))
        self.assertEqual([len(s) for s in segments], [1, 1])
        self.assertEqual(breaks.iloc[0]["missing_buckets"], 4)

    def test_missing_expected_session_breaks(self):
        bars = bars_for([MON, TUE, WED], absent=set(range(6, 12)))
        segments, breaks = self.segments(bars)
        self.assertEqual(breaks["reason"].tolist(), [MISSING_EXPECTED_SESSION])
        daily_segments, daily_breaks = self.segments(bars, "1D")
        self.assertEqual([len(s) for s in daily_segments], [1, 1])
        self.assertEqual(daily_breaks["reason"].tolist(), [MISSING_EXPECTED_SESSION])

    def test_contract_change_breaks(self):
        contracts = ["MNQ 09-26"] * 3 + ["MNQ 12-26"] * 3
        segments, breaks = self.segments(bars_for([TUE], contracts=contracts))
        self.assertEqual([len(s) for s in segments], [3, 3])
        self.assertEqual(breaks["reason"].tolist(), [CONTRACT_CHANGE])

    def test_verified_shortened_session_follows_schedule(self):
        bars = bars_for([TUE, WED, FRI], spec=EARLY_SPEC)  # WED closes 13:00 (5 buckets), THU verified closed
        segments, breaks = self.segments(bars, spec=EARLY_SPEC)
        self.assertEqual(len(segments), 1)
        self.assertEqual(len(segments[0]), 6 + 5 + 6)
        self.assertTrue(breaks.empty)

    def test_daily_consecutive_sessions_are_continuous(self):
        segments, breaks = self.segments(bars_for([MON, TUE, WED]), "1D")
        self.assertEqual([len(s) for s in segments], [3])
        self.assertTrue(breaks.empty)


class BarrierAndEqTests(unittest.TestCase):
    def test_intervening_equality_allowed_and_adjacent_eq(self):
        result = build(bars_for([TUE], highs=[1500, 1500, 1500]))
        eq = four_hour(result, EQ)
        self.assertEqual(member_prices(result, eq.iloc[-1]), [1500.0, 1500.0, 1500.0])

    def test_non_adjacent_eq_with_lower_intervening(self):
        result = build(bars_for([TUE], highs=[1500, 1499, 1500]))
        eq = four_hour(result, EQ)
        self.assertEqual(len(eq), 1)
        self.assertEqual(member_prices(result, eq.iloc[0]), [1500.0, 1500.0])

    def test_strict_upper_break_blocks_eq(self):
        result = build(bars_for([TUE], highs=[1500, 1500.25, 1500]))
        self.assertTrue(four_hour(result, EQ).empty)
        self.assertGreaterEqual(len(result.barrier_blocks[result.barrier_blocks["structure_type"] == EQ]), 1)

    def test_strict_lower_break_blocks_eq(self):
        result = build(bars_for([TUE], lows=[900, 899.75, 900]))
        self.assertTrue(four_hour(result, EQ, "LOWER").empty)
        result_ok = build(bars_for([TUE], lows=[900, 900.25, 900]))
        self.assertEqual(member_prices(result_ok, four_hour(result_ok, EQ, "LOWER").iloc[0]), [900.0, 900.0])

    def blocker(self, result, orientation, stype, earlier, later):
        blocks = result.barrier_blocks
        hit = blocks[(blocks["orientation"] == orientation) & (blocks["structure_type"] == stype)
                     & (blocks["earlier_bar_end"] == earlier) & (blocks["later_bar_end"] == later)]
        self.assertEqual(len(hit), 1)
        return hit.iloc[0]

    def test_strict_upper_barrier_records_blocking_bar(self):
        ends = bucket_ends([TUE])
        # bars 1 and 3 tie at the outer extreme; the representative is the one nearest the later endpoint
        result = build(bars_for([TUE], highs=[1500, 1501, 1500.5, 1501, 1500]))
        row = self.blocker(result, "UPPER", EQ, ends[0], ends[4])
        self.assertEqual(row["blocking_bar_end"], ends[3])
        self.assertEqual(row["blocking_excess_ticks"], 4)
        self.assertNotIn([1500.0, 1500.0], [member_prices(result, r) for _, r in four_hour(result, EQ).iterrows()])
        req = self.blocker(result, "UPPER", REQ, ends[0], ends[2])  # 1500 / 1500.5 blocked by bar 1 (1501)
        self.assertEqual((req["blocking_bar_end"], req["blocking_excess_ticks"]), (ends[1], 2))
        self.assertIn([1501.0, 1501.0], [member_prices(result, r) for _, r in four_hour(result, EQ).iterrows()])

    def test_strict_lower_barrier_records_blocking_bar(self):
        ends = bucket_ends([TUE])
        result = build(bars_for([TUE], lows=[900, 899, 899.5, 899, 900]))
        row = self.blocker(result, "LOWER", EQ, ends[0], ends[4])
        self.assertEqual(row["blocking_bar_end"], ends[3])
        self.assertEqual(row["blocking_excess_ticks"], 4)
        self.assertNotIn([900.0, 900.0], [member_prices(result, r) for _, r in four_hour(result, EQ, "LOWER").iterrows()])
        single = build(bars_for([TUE], lows=[900, 899.75, 900]))
        row = self.blocker(single, "LOWER", EQ, ends[0], ends[2])
        self.assertEqual((row["blocking_bar_end"], row["blocking_excess_ticks"]), (ends[1], 1))

    def test_touch_records_no_block(self):
        result = build(bars_for([TUE], highs=[1500, 1500, 1500], lows=[900, 900, 900]))
        self.assertTrue(result.barrier_blocks.empty)
        self.assertEqual(len(four_hour(result, EQ)), 2)
        self.assertEqual(len(four_hour(result, EQ, "LOWER")), 2)

    def test_confirming_bar_excluded_and_req_pair_envelope(self):
        allowed = build(bars_for([TUE], highs=[1500, 1500.5, 1501.25]))  # intervening inside the pair envelope
        req = four_hour(allowed, REQ)
        self.assertIn([1500.0, 1500.5, 1501.25], [member_prices(allowed, row) for _, row in req.iterrows()])
        blocked = build(bars_for([TUE], highs=[1500, 1501.5, 1501.25]))  # intervening beyond the outer pair price
        pairs = [tuple(member_prices(blocked, row)) for _, row in four_hour(blocked, REQ).iterrows()]
        self.assertNotIn((1500.0, 1501.25), pairs)

    def test_pure_equality_emits_eq_only(self):
        result = build(bars_for([TUE], highs=[1500, 1500]))
        self.assertEqual(len(four_hour(result, EQ)), 1)
        self.assertTrue(four_hour(result, REQ).empty)


class ReqTests(unittest.TestCase):
    def test_tolerance_and_exact_prices(self):
        for ticks in range(1, 7):
            with self.subTest(ticks=ticks):
                result = build(bars_for([TUE], highs=[1500, 1500 + 0.25 * ticks]))
                req = four_hour(result, REQ)
                self.assertEqual(len(req), 1)
                self.assertEqual(member_prices(result, req.iloc[0]), [1500.0, 1500 + 0.25 * ticks])
        self.assertTrue(four_hour(build(bars_for([TUE], highs=[1500, 1501.75])), REQ).empty)  # 7 ticks

    def test_chain_connectivity(self):
        result = build(bars_for([TUE], highs=[1500, 1501.5, 1503]))  # A-C = 12 ticks, A-B = B-C = 6
        last = four_hour(result, REQ).sort_values("available_at").iloc[-1]
        self.assertEqual(member_prices(result, last), [1500.0, 1501.5, 1503.0])

    def test_req_needs_two_distinct_prices_and_forms_after_pure_eq(self):
        result = build(bars_for([TUE], highs=[1500, 1500, 1501]))
        eq, req = four_hour(result, EQ), four_hour(result, REQ)
        self.assertEqual(len(eq), 1)
        self.assertEqual(len(req), 1)
        self.assertEqual(req.iloc[0]["change_kind"], FORMED)  # not EXTENDED from the EQ
        self.assertEqual(req.iloc[0]["supersedes"], ())
        self.assertEqual(member_prices(result, req.iloc[0]), [1500.0, 1500.0, 1501.0])


class PromotionTests(unittest.TestCase):
    def test_lone_candidate_is_not_a_member(self):
        result = build(bars_for([TUE]))
        self.assertFalse((result.members["reference_family"] == "4H").any())
        self.assertTrue((~result.candidates[result.candidates["timeframe"] == "4H"]["qualified"]).all())

    def test_historical_candidate_promoted_later_and_stable(self):
        ends = bucket_ends([TUE])
        result = build(bars_for([TUE], highs=[1500, 1490, 1495, 1500, 1480, 1500]))
        h4 = result.members[result.members["reference_family"] == "4H"].sort_values("source_at")
        a, b, c = h4.iloc[0], h4.iloc[1], h4.iloc[2]
        self.assertEqual((a["source_at"], a["available_at"]), (ends[0], ends[3]))  # promoted at B's close
        self.assertLess(a["source_at"], a["available_at"])
        self.assertEqual(b["source_at"], b["available_at"])                        # confirming candidate
        self.assertEqual(c["available_at"], ends[5])
        self.assertEqual(a["available_at"], ends[3])  # later growth (C) did not move A's availability
        self.assertEqual(h4["member_kind"].unique().tolist(), ["HTF_EQREQ_HIGH"])

    def test_simultaneous_eq_and_req_create_one_member(self):
        result = build(bars_for([TUE], highs=[1501, 1500, 1500]))
        h4 = result.members[result.members["reference_family"] == "4H"]
        self.assertEqual(len(h4), 3)
        self.assertEqual(h4["member_id"].nunique(), 3)

    def test_no_retrospective_liquidity(self):
        ends = bucket_ends([TUE])
        result = build(bars_for([TUE], highs=[1500, 1490, 1500, 1500]))
        first = four_hour(result, EQ).sort_values("available_at").iloc[0]
        self.assertEqual(first["available_at"], ends[2])
        self.assertEqual(len(first["member_ids"]), 2)  # the later 1500 at ends[3] is not used early


class VersionTests(unittest.TestCase):
    def test_formed_extended(self):
        result = build(bars_for([TUE], highs=[1500, 1500.5, 1501]))
        req = four_hour(result, REQ).sort_values("available_at")
        self.assertEqual(req["change_kind"].tolist(), [FORMED, EXTENDED])
        self.assertEqual(req.iloc[1]["supersedes"], (req.iloc[0]["structure_id"],))
        self.assertEqual(len(req.iloc[1]["member_ids"]), 3)

    def test_merged_without_survivor(self):
        result = build(bars_for([TUE], highs=[1503, 1503.5, 1500, 1500.5, 1502]))
        req = four_hour(result, REQ).sort_values("available_at")
        self.assertEqual(req["change_kind"].tolist(), [FORMED, FORMED, MERGED])
        merged = req.iloc[-1]
        self.assertEqual(merged["supersedes"], tuple(sorted(req.iloc[:2]["structure_id"])))
        self.assertNotIn(merged["structure_id"], set(req.iloc[:2]["structure_id"]))
        self.assertEqual(member_prices(result, merged), [1500.0, 1500.5, 1502.0, 1503.0, 1503.5])

    def test_eq_and_req_histories_are_independent(self):
        # A=B=1500 (EQ), C=1499 forms REQ {A,B,C}, D=1500 extends both (C inside the pair envelope)
        result = build(bars_for([TUE], highs=[1500, 1500, 1499, 1500]))
        eq = four_hour(result, EQ).sort_values("available_at")
        req = four_hour(result, REQ).sort_values("available_at")
        self.assertEqual(req["change_kind"].tolist(), [FORMED, EXTENDED])
        eq_ids, req_ids = set(eq["structure_id"]), set(req["structure_id"])
        for _, row in eq.iterrows():
            self.assertTrue(set(row["supersedes"]) <= eq_ids)
        for _, row in req.iterrows():
            self.assertTrue(set(row["supersedes"]) <= req_ids)
        self.assertEqual(eq["change_kind"].tolist(), [FORMED, EXTENDED])

    def test_each_version_is_superseded_at_most_once(self):
        # audit invariant: monotonic component history never branches from one predecessor
        for highs in ([1500, 1500.5, 1501, 1501.25], [1503, 1503.5, 1500, 1500.5, 1502, 1502.25], [1500, 1500, 1499, 1500]):
            result = build(bars_for([TUE], highs=highs))
            predecessors = [sid for sups in result.structures["supersedes"] for sid in sups]
            self.assertTrue(predecessors)
            self.assertEqual(len(predecessors), len(set(predecessors)), highs)

    def test_daily_structures_group_existing_members(self):
        # TUE and WED daily highs equal (bucket 5 of TUE, bucket 5 of WED), all other buckets lower
        highs = [2000, 2001, 2002, 2003, 2004, 2500, 2010, 2011, 2012, 2013, 2014, 2500]
        result = build(bars_for([TUE, WED], highs=highs))
        daily_eq = result.structures[(result.structures["reference_family"] == "1D") & (result.structures["structure_type"] == EQ)]
        self.assertEqual(len(daily_eq), 1)
        daily = result.members[result.members["reference_family"] == "1D"].set_index("member_id")
        members = daily.loc[list(daily_eq.iloc[0]["member_ids"])]
        self.assertEqual(sorted(members["member_kind"]), ["DAILY_HIGH", "DAILY_HIGH"])
        self.assertTrue((members["source_at"] == members["available_at"]).all())  # availability unchanged
        self.assertEqual(daily_eq.iloc[0]["available_at"], members["available_at"].max())


class ContractTickCausalityTests(unittest.TestCase):
    def test_mixed_contract_cannot_form(self):
        # TUE last bucket and WED first bucket are adjacent with equal highs, but the contract rolls in between
        # (a single Daily bar can never mix contracts; M3 raises for that).
        contracts = ["MNQ 09-26"] * 6 + ["MNQ 12-26"] * 6
        highs = [1490, 1491, 1492, 1493, 1494, 1500, 1500]
        self.assertTrue(four_hour(build(bars_for([TUE, WED], highs=highs, contracts=contracts)), EQ).empty)
        same = build(bars_for([TUE, WED], highs=highs))
        self.assertEqual(len(four_hour(same, EQ)), 1)  # control: same contract forms the EQ

    def test_off_grid_candidate_fails_clearly(self):
        with self.assertRaisesRegex(ExternalLiquidityError, "tick grid"):
            build(bars_for([TUE], highs=[1500.1]))

    def test_structures_never_use_future_members(self):
        result = build(bars_for([TUE, WED], highs=[1500, 1500, 1500.5, 1501, 1499, 1500]))
        members = result.members.set_index("member_id")
        for _, row in result.structures.iterrows():
            self.assertTrue((members.loc[list(row["member_ids"]), "available_at"] <= row["available_at"]).all())
            self.assertTrue((members.loc[list(row["member_ids"]), "source_at"] <= row["available_at"]).all())

    def test_shuffled_input_is_deterministic(self):
        bars = bars_for([TUE, WED], highs=[1500, 1500, 1500.5, 1501, 1499, 1500])
        baseline = build(bars)
        shuffled = build(bars.sample(frac=1, random_state=3))
        for name in ("members", "structures", "previous_day_references", "candidates", "continuity_breaks"):
            pd.testing.assert_frame_equal(getattr(shuffled, name), getattr(baseline, name))

    def test_definition_version_and_class(self):
        result = build(bars_for([TUE], highs=[1500, 1500]))
        self.assertEqual(set(result.members["definition_version"]), {DEFINITION_VERSION})
        self.assertEqual(set(result.structures["liquidity_class"]), {"EXTERNAL"})


if __name__ == "__main__":
    unittest.main()
