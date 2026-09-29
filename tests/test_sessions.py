"""M1 generic session model tests. Synthetic timestamps only; no market data."""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.data.sessions import (
    CLOSED,
    EXCHANGE_CLOSED,
    IN_SESSION,
    MAINTENANCE_BREAK,
    MODIFIED,
    NON_TRADING_DAY,
    REGULAR,
    SessionError,
    SessionOverride,
    assign_trading_date,
    get_session_override,
    is_in_session,
    is_maintenance_break,
    load_session_spec,
    next_expected_session,
    previous_expected_session,
    session_bounds,
    session_status,
    with_calendar_overrides,
)

TZ = "America/New_York"
ONE_MINUTE = pd.Timedelta(minutes=1)

# Calendar anchors (2026): Mon 09-21 ... Fri 09-25, Sat 09-26, Sun 09-27, Mon 09-28.
MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in range(21, 26))
SAT, SUN, NEXT_MON = date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28)


def et(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(TZ)


def utc(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


class SessionSpecLoadingTests(unittest.TestCase):
    def test_authoritative_config_loads_generic_facts_only(self):
        spec = load_session_spec()
        self.assertEqual(spec.session_id, "cme_globex_et")
        self.assertEqual(spec.timezone, TZ)
        self.assertEqual((spec.open_time.isoformat(), spec.open_day_offset), ("18:00:00", -1))
        self.assertEqual(spec.close_time.isoformat(), "17:00:00")
        self.assertEqual((spec.break_start, spec.break_end), (spec.close_time, spec.open_time))
        self.assertEqual(spec.trading_weekdays, frozenset(range(5)))
        self.assertEqual(dict(spec.overrides), {})
        self.assertIsNone(spec.calendar_coverage)
        config = json.loads(Path(spec.source_path).read_text(encoding="utf-8"))
        self.assertNotIn("windows", config)

    def test_invalid_configs_are_rejected(self):
        base = json.loads(Path(load_session_spec().source_path).read_text(encoding="utf-8"))
        base.pop("calendar")
        cases = {
            "missing timezone": {k: v for k, v in base.items() if k != "timezone"},
            "unknown timezone": {**base, "timezone": "Mars/Olympus"},
            "break mismatch": {**base, "maintenance_break": {"start_et": "16:00", "end_et": "18:00"}},
            "same-day open": {**base, "session_open": {"time_et": "18:00", "day_offset": 0}},
            "bad weekday": {**base, "trading_weekdays": ["MON", "FUNDAY"]},
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, config in cases.items():
                with self.subTest(name):
                    path = Path(folder) / "session.json"
                    path.write_text(json.dumps(config), encoding="utf-8")
                    with self.assertRaises(SessionError):
                        load_session_spec(path)

    def test_declared_but_missing_calendar_fails_loudly(self):
        base = json.loads(Path(load_session_spec().source_path).read_text(encoding="utf-8"))
        base["calendar"]["overrides_file"] = "does_not_exist.json"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.json"
            path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaises(SessionError):
                load_session_spec(path)


class RegularSessionTests(unittest.TestCase):
    def setUp(self):
        self.spec = load_session_spec()

    def test_regular_session_bounds(self):
        bounds = session_bounds(WED, self.spec)
        self.assertEqual(bounds.kind, REGULAR)
        self.assertEqual(bounds.open, et("2026-09-22 18:00"))
        self.assertEqual(bounds.close, et("2026-09-23 17:00"))
        self.assertEqual(bounds.close - bounds.open, pd.Timedelta(hours=23))
        self.assertIsNotNone(bounds.open.tzinfo)
        self.assertFalse(bounds.calendar_verified)  # no coverage declared yet

    def test_close_boundary_at_1700(self):
        self.assertEqual(assign_trading_date(et("2026-09-23 16:59:59.999999"), self.spec), WED)
        self.assertEqual(session_status(et("2026-09-23 16:59"), self.spec), IN_SESSION)
        self.assertEqual(session_status(et("2026-09-23 17:00"), self.spec), MAINTENANCE_BREAK)
        with self.assertRaises(SessionError):
            assign_trading_date(et("2026-09-23 17:00"), self.spec)

    def test_maintenance_break_window(self):
        for clock in ("17:00", "17:30", "17:59:59"):
            with self.subTest(clock):
                stamp = et(f"2026-09-23 {clock}")
                self.assertTrue(is_maintenance_break(stamp, self.spec))
                self.assertFalse(is_in_session(stamp, self.spec))
                with self.assertRaises(SessionError):
                    assign_trading_date(stamp, self.spec)
        self.assertFalse(is_maintenance_break(et("2026-09-23 16:59"), self.spec))
        self.assertFalse(is_maintenance_break(et("2026-09-23 18:00"), self.spec))

    def test_new_session_starts_at_1800(self):
        self.assertEqual(assign_trading_date(et("2026-09-22 18:00"), self.spec), WED)
        self.assertEqual(session_status(et("2026-09-22 18:00"), self.spec), IN_SESSION)
        self.assertEqual(session_status(et("2026-09-22 17:59:59"), self.spec), MAINTENANCE_BREAK)

    def test_trading_date_across_midnight(self):
        for value in ("2026-09-22 23:59", "2026-09-23 00:00", "2026-09-23 00:01", "2026-09-23 09:30"):
            with self.subTest(value):
                self.assertEqual(assign_trading_date(et(value), self.spec), WED)

    def test_friday_evening_and_weekend_are_closed(self):
        self.assertEqual(assign_trading_date(et("2026-09-25 16:59"), self.spec), FRI)
        friday_close = et("2026-09-25 17:30")
        self.assertFalse(is_maintenance_break(friday_close, self.spec))
        self.assertEqual(session_status(friday_close, self.spec), NON_TRADING_DAY)
        for value in ("2026-09-25 18:30", "2026-09-26 12:00", "2026-09-27 12:00", "2026-09-27 17:30"):
            with self.subTest(value):
                self.assertEqual(session_status(et(value), self.spec), NON_TRADING_DAY)
                with self.assertRaises(SessionError):
                    assign_trading_date(et(value), self.spec)
        self.assertEqual(session_bounds(SAT, self.spec).kind, NON_TRADING_DAY)
        self.assertEqual(session_bounds(SUN, self.spec).kind, NON_TRADING_DAY)

    def test_weekly_boundary_statuses(self):
        # (timestamp, status, maintenance break?, owning trading date or None)
        cases = [
            ("2026-09-25 16:59", IN_SESSION, False, FRI),         # Friday before close
            ("2026-09-25 17:00", NON_TRADING_DAY, False, None),   # Friday close: weekend begins
            ("2026-09-25 17:30", NON_TRADING_DAY, False, None),
            ("2026-09-25 18:00", NON_TRADING_DAY, False, None),   # no Friday evening open
            ("2026-09-26 00:00", NON_TRADING_DAY, False, None),   # Saturday
            ("2026-09-26 12:00", NON_TRADING_DAY, False, None),
            ("2026-09-26 18:00", NON_TRADING_DAY, False, None),
            ("2026-09-27 12:00", NON_TRADING_DAY, False, None),   # Sunday before open
            ("2026-09-27 17:30", NON_TRADING_DAY, False, None),
            ("2026-09-27 18:00", IN_SESSION, False, NEXT_MON),    # Monday session opens
            ("2026-09-28 17:30", MAINTENANCE_BREAK, True, None),  # Mon-Thu break
            ("2026-09-24 17:30", MAINTENANCE_BREAK, True, None),  # Thursday break
        ]
        for value, status, in_break, owner in cases:
            with self.subTest(value):
                stamp = et(value)
                self.assertEqual(session_status(stamp, self.spec), status)
                self.assertEqual(is_maintenance_break(stamp, self.spec), in_break)
                if owner is None:
                    with self.assertRaises(SessionError):
                        assign_trading_date(stamp, self.spec)
                else:
                    self.assertEqual(assign_trading_date(stamp, self.spec), owner)

    def test_sunday_evening_opens_monday_session(self):
        self.assertEqual(assign_trading_date(et("2026-09-27 18:00"), self.spec), NEXT_MON)
        self.assertEqual(session_status(et("2026-09-27 18:00"), self.spec), IN_SESSION)
        self.assertFalse(is_in_session(et("2026-09-27 17:59"), self.spec))
        self.assertEqual(session_bounds(NEXT_MON, self.spec).open, et("2026-09-27 18:00"))


class TimezoneAndDstTests(unittest.TestCase):
    def setUp(self):
        self.spec = load_session_spec()

    def test_naive_timestamps_are_rejected(self):
        for value in (pd.Timestamp("2026-09-23 10:00"), datetime(2026, 9, 23, 10, 0), date(2026, 9, 23)):
            with self.subTest(repr(value)):
                with self.assertRaises(SessionError):
                    assign_trading_date(value, self.spec)

    def test_same_instant_in_any_timezone_gives_same_result(self):
        instants = (
            utc("2026-09-23 21:59"),  # 17:59 EDT
            utc("2026-09-23 22:00"),  # 18:00 EDT
        )
        self.assertEqual(session_status(instants[0], self.spec), MAINTENANCE_BREAK)
        self.assertEqual(assign_trading_date(instants[1], self.spec), THU)
        self.assertEqual(
            assign_trading_date(instants[1].tz_convert("Asia/Tokyo"), self.spec),
            assign_trading_date(instants[1], self.spec),
        )

    def test_spring_forward_uses_local_wall_clock(self):
        # DST starts Sunday 2026-03-08 02:00 ET.
        friday = session_bounds(date(2026, 3, 6), self.spec)
        monday = session_bounds(date(2026, 3, 9), self.spec)
        self.assertEqual(friday.open.tz_convert("UTC"), utc("2026-03-05 23:00"))  # 18:00 EST
        self.assertEqual(monday.open.tz_convert("UTC"), utc("2026-03-08 22:00"))  # 18:00 EDT
        self.assertEqual(friday.close - friday.open, pd.Timedelta(hours=23))
        self.assertEqual(monday.close - monday.open, pd.Timedelta(hours=23))
        # 22:30 UTC is 18:30 EDT (open) although it would be 17:30 under fixed EST.
        self.assertEqual(assign_trading_date(utc("2026-03-08 22:30"), self.spec), date(2026, 3, 9))
        self.assertEqual(session_status(utc("2026-03-06 22:30"), self.spec), NON_TRADING_DAY)

    def test_fall_back_uses_local_wall_clock(self):
        # DST ends Sunday 2026-11-01 02:00 ET.
        friday = session_bounds(date(2026, 10, 30), self.spec)
        monday = session_bounds(date(2026, 11, 2), self.spec)
        self.assertEqual(friday.open.tz_convert("UTC"), utc("2026-10-29 22:00"))  # 18:00 EDT
        self.assertEqual(monday.open.tz_convert("UTC"), utc("2026-11-01 23:00"))  # 18:00 EST
        self.assertEqual(monday.close - monday.open, pd.Timedelta(hours=23))
        # 22:30 UTC is 17:30 EST on Sunday: closed, not yet Monday.
        with self.assertRaises(SessionError):
            assign_trading_date(utc("2026-11-01 22:30"), self.spec)
        self.assertEqual(assign_trading_date(utc("2026-11-01 23:00"), self.spec), date(2026, 11, 2))


class BarLabelTests(unittest.TestCase):
    def setUp(self):
        self.spec = load_session_spec()

    def test_bar_end_labels_follow_bar_start(self):
        kwargs = {"label": "bar_end", "bar_interval": ONE_MINUTE}
        # 18:01 bar-end covers 18:00-18:01: first bar of the next session.
        self.assertEqual(assign_trading_date(et("2026-09-22 18:01"), self.spec, **kwargs), WED)
        # 17:00 bar-end covers 16:59-17:00: last bar of its own session.
        self.assertEqual(assign_trading_date(et("2026-09-23 17:00"), self.spec, **kwargs), WED)
        self.assertEqual(session_status(et("2026-09-23 17:00"), self.spec, **kwargs), IN_SESSION)
        # 18:00 bar-end covers 17:59-18:00: inside the break.
        self.assertTrue(is_maintenance_break(et("2026-09-22 18:00"), self.spec, **kwargs))
        with self.assertRaises(SessionError):
            assign_trading_date(et("2026-09-22 18:00"), self.spec, **kwargs)

    def test_bar_spanning_the_close_is_rejected(self):
        with self.assertRaises(SessionError):
            assign_trading_date(et("2026-09-23 17:03"), self.spec, label="bar_end", bar_interval="5min")
        self.assertEqual(
            session_status(et("2026-09-23 17:03"), self.spec, label="bar_end", bar_interval="5min"),
            EXCHANGE_CLOSED,
        )

    def test_invalid_label_arguments(self):
        stamp = et("2026-09-23 10:00")
        with self.assertRaises(SessionError):
            assign_trading_date(stamp, self.spec, label="bar_end")
        with self.assertRaises(SessionError):
            assign_trading_date(stamp, self.spec, bar_interval=ONE_MINUTE)
        with self.assertRaises(SessionError):
            assign_trading_date(stamp, self.spec, label="bar_start", bar_interval=ONE_MINUTE)
        with self.assertRaises(SessionError):
            assign_trading_date(stamp, self.spec, label="bar_end", bar_interval=pd.Timedelta(0))


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.base = load_session_spec()
        self.spec = with_calendar_overrides(
            self.base,
            [
                {"trading_date": "2026-09-23", "kind": CLOSED, "reason": "synthetic closure"},
                {"trading_date": "2026-09-24", "kind": MODIFIED, "close_et": "13:00",
                 "reason": "synthetic early close"},
            ],
            coverage_start="2026-09-01",
            coverage_end="2026-09-30",
        )

    def test_full_closure_override(self):
        bounds = session_bounds(WED, self.spec)
        self.assertEqual(bounds.kind, CLOSED)
        self.assertIsNone(bounds.open)
        self.assertTrue(bounds.calendar_verified)
        self.assertEqual(get_session_override(WED, self.spec).reason, "synthetic closure")
        self.assertEqual(session_status(et("2026-09-23 10:00"), self.spec), EXCHANGE_CLOSED)
        # Ownership is a clock convention; overrides only change tradability.
        self.assertEqual(assign_trading_date(et("2026-09-23 10:00"), self.spec), WED)

    def test_shortened_session_override(self):
        bounds = session_bounds(THU, self.spec)
        self.assertEqual(bounds.kind, MODIFIED)
        self.assertEqual((bounds.open, bounds.close), (et("2026-09-23 18:00"), et("2026-09-24 13:00")))
        self.assertEqual(session_status(et("2026-09-24 12:59"), self.spec), IN_SESSION)
        self.assertEqual(session_status(et("2026-09-24 13:00"), self.spec), EXCHANGE_CLOSED)
        self.assertEqual(session_status(et("2026-09-24 16:00"), self.spec), EXCHANGE_CLOSED)
        kwargs = {"label": "bar_end", "bar_interval": ONE_MINUTE}
        self.assertEqual(session_status(et("2026-09-24 13:00"), self.spec, **kwargs), IN_SESSION)
        self.assertEqual(session_status(et("2026-09-24 13:01"), self.spec, **kwargs), EXCHANGE_CLOSED)

    def test_regular_dates_inside_coverage_are_verified(self):
        self.assertTrue(session_bounds(TUE, self.spec).calendar_verified)
        self.assertFalse(session_bounds(date(2026, 10, 5), self.spec).calendar_verified)
        self.assertIsNone(get_session_override(TUE, self.spec))

    def test_replacing_the_calendar_does_not_mutate_the_base_spec(self):
        self.assertEqual(dict(self.base.overrides), {})
        self.assertEqual(session_bounds(WED, self.base).kind, REGULAR)

    def test_invalid_overrides_are_rejected(self):
        cases = {
            "weekend": [{"trading_date": "2026-09-26", "kind": CLOSED}],
            "outside coverage": [{"trading_date": "2026-10-05", "kind": CLOSED}],
            "duplicate": [{"trading_date": "2026-09-23", "kind": CLOSED}] * 2,
            "closed with times": [{"trading_date": "2026-09-23", "kind": CLOSED, "close_et": "13:00"}],
            "extends past close": [{"trading_date": "2026-09-23", "kind": MODIFIED, "close_et": "17:30"}],
            "equals regular": [{"trading_date": "2026-09-23", "kind": MODIFIED, "close_et": "17:00"}],
            "no change": [{"trading_date": "2026-09-23", "kind": MODIFIED}],
            "unknown kind": [{"trading_date": "2026-09-23", "kind": "HALF_DAY"}],
            "unknown field": [{"trading_date": "2026-09-23", "kind": CLOSED, "note": "x"}],
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                with self.assertRaises(SessionError):
                    with_calendar_overrides(
                        self.base, overrides, coverage_start="2026-09-01", coverage_end="2026-09-30"
                    )
        with self.assertRaises(SessionError):
            with_calendar_overrides(self.base, [], coverage_start="2026-09-01")
        with self.assertRaises(SessionError):
            session_bounds(datetime(2026, 9, 23, 10, 0), self.base)

    def test_override_objects_are_accepted(self):
        spec = with_calendar_overrides(self.base, [SessionOverride(WED, CLOSED, reason="object")])
        self.assertEqual(session_bounds(WED, spec).kind, CLOSED)


class ExpectedSessionTests(unittest.TestCase):
    def setUp(self):
        self.base = load_session_spec()

    def test_previous_and_next_skip_the_weekend(self):
        previous = previous_expected_session(NEXT_MON, self.base)
        following = next_expected_session(FRI, self.base)
        self.assertEqual(previous.trading_date, FRI)
        self.assertEqual(following.trading_date, NEXT_MON)
        self.assertEqual(previous_expected_session(WED, self.base).trading_date, TUE)
        # Without calendar coverage an intervening closure cannot be ruled out.
        self.assertFalse(previous.calendar_verified)

    def test_previous_and_next_skip_explicit_closures(self):
        spec = with_calendar_overrides(
            self.base,
            [{"trading_date": "2026-09-23", "kind": CLOSED, "reason": "synthetic closure"}],
            coverage_start="2026-09-01",
            coverage_end="2026-09-30",
        )
        previous = previous_expected_session(THU, spec)
        self.assertEqual(previous.trading_date, TUE)
        self.assertTrue(previous.calendar_verified)
        self.assertEqual(next_expected_session(TUE, spec).trading_date, THU)
        self.assertEqual(previous_expected_session(NEXT_MON, spec).trading_date, FRI)

    def test_result_is_unverified_when_search_leaves_coverage(self):
        spec = with_calendar_overrides(self.base, [], coverage_start="2026-09-22", coverage_end="2026-09-30")
        self.assertTrue(previous_expected_session(WED, spec).calendar_verified)
        self.assertFalse(previous_expected_session(TUE, spec).calendar_verified)

    def test_search_is_bounded(self):
        closures = [
            {"trading_date": (date(2026, 9, 1) + timedelta(days=offset)).isoformat(), "kind": CLOSED}
            for offset in range(30)
            if (date(2026, 9, 1) + timedelta(days=offset)).weekday() < 5
        ]
        spec = with_calendar_overrides(self.base, closures)
        with self.assertRaises(SessionError):
            next_expected_session(date(2026, 9, 1), spec)


if __name__ == "__main__":
    unittest.main()
