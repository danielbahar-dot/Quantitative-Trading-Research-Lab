"""M6A generic level-interaction tests. Synthetic bars only; no market data."""

from datetime import date, time, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.data.instruments import InstrumentError
from src.data.sessions import load_session_spec
from src.features.level_interactions import (
    AMBIGUOUS_APPROACH,
    CONTRACT_MISMATCH,
    EVALUATED,
    OUTPUT_COLUMNS,
    PENDING_LEVEL,
    PRIMITIVES,
    LevelInteractionError,
    evaluate_level_interactions,
    evaluate_market_context_interactions,
    market_context_levels,
)
from src.features.session_context import build_market_context

TZ = "America/New_York"
SPEC = load_session_spec()
T0 = pd.Timestamp("2026-09-22 10:00", tz=TZ)  # a Tuesday RTH minute
L = 100.0


def bars_from(rows, contract="MNQ 12-26", start=T0):
    """rows: (open, high, low, close); consecutive 1m bar-end labels from ``start``."""
    index = pd.DatetimeIndex([start + pd.Timedelta(minutes=i) for i in range(len(rows))], name="timestamp_et")
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    frame["contract"] = contract
    return frame


def level(value=L, orientation="UPPER", available_at=None, valid_until=None, *, level_id="L1",
          scope="SPECIFIC", contract="MNQ 12-26", instrument="MNQ", valid_from=None):
    return {
        "level_id": level_id, "level_value": value, "orientation": orientation,
        "available_at": available_at if available_at is not None else T0 - pd.Timedelta(minutes=10),
        "valid_from": valid_from, "valid_until": valid_until, "instrument_id": instrument, "contract_scope": scope,
        "contract": contract if scope == "SPECIFIC" else None,
    }


def evaluate(rows, *levels, **kwargs):
    return evaluate_level_interactions(bars_from(rows), pd.DataFrame(list(levels)), **kwargs)


def facts(row) -> tuple:
    return tuple(None if pd.isna(row[name]) else bool(row[name]) for name in PRIMITIVES)


# (name, OHLC for an UPPER level at 100, expected approach, relation, (touch, trade, close, reject, sweep))
UPPER_CASES = [
    ("below, no interaction", (99.0, 99.75, 98.5, 99.5), "BELOW", "ORIGINAL_SIDE", (False, False, False, False, False)),
    ("exact touch, close back", (99.0, 100.0, 98.75, 99.75), "BELOW", "ORIGINAL_SIDE", (True, False, False, True, False)),
    ("exact touch, close at level", (99.0, 100.0, 98.75, 100.0), "BELOW", "ORIGINAL_SIDE", (True, False, False, True, False)),
    ("one-tick trade-through, sweep", (99.0, 100.25, 98.75, 99.75), "BELOW", "ORIGINAL_SIDE", (True, True, False, True, True)),
    ("multi-tick trade-through, close through", (99.0, 101.0, 98.75, 100.5), "BELOW", "ORIGINAL_SIDE", (True, True, True, False, False)),
    ("close exactly one tick beyond", (99.0, 100.25, 98.75, 100.25), "BELOW", "ORIGINAL_SIDE", (True, True, True, False, False)),
    ("open exactly at level", (100.0, 100.0, 99.5, 99.75), "AT", "ORIGINAL_SIDE", (True, False, False, True, False)),
    ("open at level, close through", (100.0, 100.5, 99.75, 100.25), "AT", "ORIGINAL_SIDE", (True, True, True, False, False)),
    ("fully above (far side)", (101.0, 101.5, 100.5, 101.0), "ABOVE", "FAR_SIDE", (False, False, False, False, False)),
    ("gap above then returns to level", (101.0, 101.0, 100.0, 100.5), "ABOVE", "FAR_SIDE", (True, False, False, True, False)),
    ("gap above, far-side sweep", (101.0, 101.0, 99.75, 100.25), "ABOVE", "FAR_SIDE", (True, True, False, True, True)),
    ("gap above, far-side close-through", (101.0, 101.0, 99.5, 99.75), "ABOVE", "FAR_SIDE", (True, True, True, False, False)),
]


def mirror(ohlc):
    o, h, lo, c = ohlc
    return (2 * L - o, 2 * L - lo, 2 * L - h, 2 * L - c)


class DirectionalCaseTests(unittest.TestCase):
    def check_cases(self, orientation, transform, side_map):
        for name, ohlc, side, relation, expected in UPPER_CASES:
            with self.subTest(orientation=orientation, case=name):
                out = evaluate([transform(ohlc)], level(orientation=orientation))
                row = out.iloc[0]
                self.assertEqual(row["status"], EVALUATED)
                self.assertEqual(row["approach_side"], side_map[side])
                self.assertEqual(row["approach_relation"], relation)
                self.assertEqual(facts(row), expected)

    def test_upper_cases(self):
        self.check_cases("UPPER", lambda ohlc: ohlc, {"BELOW": "BELOW", "ABOVE": "ABOVE", "AT": "AT"})

    def test_lower_cases_mirror_upper_exactly(self):
        self.check_cases("LOWER", mirror, {"BELOW": "ABOVE", "ABOVE": "BELOW", "AT": "AT"})

    def test_offsets_are_raw_signed_and_unclipped(self):
        row = evaluate([(99.0, 100.25, 98.75, 99.75)], level()).iloc[0]
        self.assertEqual((row["open_offset_ticks"], row["high_offset_ticks"], row["low_offset_ticks"], row["close_offset_ticks"]),
                         (-4.0, 1.0, -5.0, -1.0))
        lower = evaluate([(99.0, 100.25, 98.75, 99.75)], level(orientation="LOWER")).iloc[0]
        self.assertEqual(lower["high_offset_ticks"], 1.0)  # plain price direction, not orientation-normalized


class NeutralTests(unittest.TestCase):
    def test_neutral_uses_geometric_approach_without_relation(self):
        up = evaluate([(99.0, 100.25, 98.75, 99.75)], level(orientation="NEUTRAL")).iloc[0]
        self.assertEqual((up["approach_side"], up["status"]), ("BELOW", EVALUATED))
        self.assertTrue(pd.isna(up["approach_relation"]))
        self.assertEqual(facts(up), (True, True, False, True, True))
        down = evaluate([(101.0, 101.0, 99.5, 99.75)], level(orientation="NEUTRAL")).iloc[0]
        self.assertEqual((down["approach_side"], facts(down)), ("ABOVE", (True, True, True, False, False)))

    def test_neutral_open_at_level_is_ambiguous(self):
        row = evaluate([(100.0, 100.5, 99.5, 100.25)], level(orientation="NEUTRAL")).iloc[0]
        self.assertEqual(row["status"], AMBIGUOUS_APPROACH)
        self.assertEqual(row["approach_side"], "AT")
        self.assertTrue(pd.isna(row["approach_relation"]))
        self.assertEqual(facts(row), (True, None, None, None, None))
        self.assertEqual(row["open_offset_ticks"], 0.0)


class OffGridLevelTests(unittest.TestCase):
    def test_first_tradable_prices_and_equivalences(self):
        off = 100.125  # between ticks 100.00 and 100.25
        out = evaluate([
            (99.5, 100.0, 99.25, 99.75),    # reaches 100.00 only: no touch
            (99.5, 100.25, 99.25, 100.0),   # first tradable above reached, closes back
            (99.5, 100.5, 99.25, 100.25),   # close-through
        ], level(off))
        self.assertEqual((out.iloc[0]["first_tradable_above"], out.iloc[0]["first_tradable_below"]), (100.25, 100.0))
        self.assertEqual(facts(out.iloc[0]), (False, False, False, False, False))
        self.assertEqual(facts(out.iloc[1]), (True, True, False, True, True))
        self.assertEqual(facts(out.iloc[2]), (True, True, True, False, False))
        self.assertTrue((out["touch"] == out["trade_through"]).all())
        self.assertTrue((out["reject"] == out["sweep"]).all())
        self.assertEqual(out.iloc[1]["high_offset_ticks"], 0.5)
        self.assertFalse((out["approach_side"] == "AT").any())


class InvariantTests(unittest.TestCase):
    def test_invariants_on_randomized_bars(self):
        rng = np.random.default_rng(7)
        rows = []
        for _ in range(2000):
            o, c = rng.integers(390, 411, 2) * 0.25
            h = max(o, c) + rng.integers(0, 6) * 0.25
            lo = min(o, c) - rng.integers(0, 6) * 0.25
            rows.append((o, h, lo, c))
        levels = [level(value, orientation, level_id=f"{orientation}{value}")
                  for value in (100.0, 100.125, 99.9)
                  for orientation in ("UPPER", "LOWER", "NEUTRAL")]
        out = evaluate(rows, *levels)
        ev = out[out["status"] == EVALUATED]
        self.assertGreater(len(ev), 10000)
        t, tt, ct, rj, sw = (ev[name].astype(bool) for name in PRIMITIVES)
        self.assertTrue((~tt | t).all() and (~ct | t).all() and (~ct | tt).all() and (~rj | t).all())
        self.assertTrue((~sw | t).all() and (~sw | tt).all() and (~sw | rj).all())
        self.assertTrue((sw == (tt & rj)).all())
        self.assertTrue((~sw | ~ct).all())
        self.assertTrue((t == (ct ^ rj)).all())
        on_grid = ev["level_value"] == 100.0
        exact = on_grid & ((ev["high_offset_ticks"] == 0) | (ev["low_offset_ticks"] == 0)) & t
        self.assertTrue(exact.any())
        self.assertTrue((exact & ~tt).any())  # exact on-grid TOUCH does not imply TRADE_THROUGH
        off_grid = ev["level_value"] != 100.0
        self.assertTrue((t[off_grid] == tt[off_grid]).all() and (rj[off_grid] == sw[off_grid]).all())
        self.assertTrue(((rj & ~sw)[on_grid]).any())  # REJECT does not imply SWEEP on-grid
        not_eval = out[out["status"] != EVALUATED]
        self.assertTrue(set(not_eval["status"]) <= {AMBIGUOUS_APPROACH})


class CausalityAndScopeTests(unittest.TestCase):
    def test_confirming_bar_is_pending_and_earlier_bars_are_not_emitted(self):
        rows = [(99.0, 100.25, 98.75, 99.75)] * 4
        confirming = T0 + pd.Timedelta(minutes=1)
        out = evaluate(rows, level(available_at=confirming))
        self.assertEqual(out["bar_end"].tolist(), [T0 + pd.Timedelta(minutes=i) for i in (1, 2, 3)])
        pending = out.iloc[0]
        self.assertEqual(pending["status"], PENDING_LEVEL)
        self.assertEqual(facts(pending), (None,) * 5)
        self.assertTrue(pd.isna(pending["approach_side"]) and pd.isna(pending["high_offset_ticks"]))
        self.assertEqual(out.iloc[1]["status"], EVALUATED)

    def test_level_known_mid_bar_makes_the_straddling_bar_pending(self):
        # Known at 10:00:30: the bar 10:00-10:01 contains the confirmation instant
        # (bar_start < available_at), so it is PENDING; the next bar is evaluated.
        out = evaluate([(99.0, 99.5, 98.5, 99.0)] * 3, level(available_at=T0 + pd.Timedelta(seconds=30)))
        self.assertEqual(out["bar_end"].tolist(), [T0 + pd.Timedelta(minutes=1), T0 + pd.Timedelta(minutes=2)])
        self.assertEqual(out["status"].tolist(), [PENDING_LEVEL, EVALUATED])

    def test_valid_until_bounds_applicability(self):
        out = evaluate([(99.0, 99.5, 98.5, 99.0)] * 5, level(valid_until=T0 + pd.Timedelta(minutes=2)))
        self.assertEqual(out["bar_end"].max(), T0 + pd.Timedelta(minutes=2))
        self.assertEqual(len(out), 3)

    def test_valid_from_bounds_start_and_suppresses_out_of_window_pending(self):
        rows = [(99.0, 99.5, 98.5, 99.0)] * 5
        # Confirmed by the bar ending T0+1, applicable only from T0+2 (bar_start >= valid_from).
        out = evaluate(rows, level(available_at=T0 + pd.Timedelta(minutes=1), valid_from=T0 + pd.Timedelta(minutes=2)))
        self.assertEqual(out["bar_end"].tolist(), [T0 + pd.Timedelta(minutes=i) for i in (3, 4)])
        self.assertTrue((out["status"] == EVALUATED).all())  # confirming bar lies outside the window
        inside = evaluate(rows, level(available_at=T0 + pd.Timedelta(minutes=2), valid_from=T0))
        self.assertEqual(inside.iloc[0]["status"], PENDING_LEVEL)  # confirming bar inside the window
        with self.assertRaises(LevelInteractionError):
            evaluate(rows, level(valid_from=T0 + pd.Timedelta(minutes=3), valid_until=T0 + pd.Timedelta(minutes=2)))

    def test_window_bounds_use_bar_start_for_unaligned_instants(self):
        rows = [(99.0, 99.5, 98.5, 99.0)] * 5
        # bar_start < valid_until: the bar starting T0+1 (ending T0+2) straddles T0+1:30 and is included.
        out = evaluate(rows, level(valid_until=T0 + pd.Timedelta(minutes=1, seconds=30)))
        self.assertEqual(out["bar_end"].tolist(), [T0 + pd.Timedelta(minutes=i) for i in (0, 1, 2)])
        # bar_start >= valid_from: the bar starting T0 (ending T0+1) straddles T0:30 and is excluded.
        out = evaluate(rows, level(valid_from=T0 + pd.Timedelta(seconds=30)))
        self.assertEqual(out["bar_end"].min(), T0 + pd.Timedelta(minutes=2))
        # A confirming bar whose bar_start lies inside the window is emitted as PENDING even if it
        # straddles valid_until; no later bar is applicable.
        out = evaluate(rows, level(available_at=T0 + pd.Timedelta(minutes=1, seconds=30),
                                   valid_until=T0 + pd.Timedelta(minutes=1, seconds=45)))
        self.assertEqual(out["bar_end"].tolist(), [T0 + pd.Timedelta(minutes=2)])
        self.assertEqual(out["status"].tolist(), [PENDING_LEVEL])


class ApplicabilityBoundaryTests(unittest.TestCase):
    """Eligibility: bar_start >= max(available_at, valid_from) and bar_start < valid_until."""

    ROWS = [(99.0, 99.5, 98.5, 99.0)] * 6  # bar_end T0..T0+5, bar_start = bar_end - 1m

    def run_level(self, **kwargs):
        out = evaluate(self.ROWS, level(**kwargs))
        return [(int((end - T0) / pd.Timedelta(minutes=1)), status) for end, status in zip(out["bar_end"], out["status"])]

    def test_bar_start_equal_to_valid_from_is_eligible(self):
        rows = self.run_level(valid_from=T0 + pd.Timedelta(minutes=1))
        self.assertEqual(rows[0], (2, EVALUATED))  # bar_start T0+1 == valid_from

    def test_bar_start_before_valid_from_is_not_eligible(self):
        rows = self.run_level(valid_from=T0 + pd.Timedelta(minutes=1))
        self.assertNotIn(1, [m for m, _ in rows])  # bar_start T0 < valid_from

    def test_bar_start_equal_to_valid_until_is_not_eligible(self):
        rows = self.run_level(valid_until=T0 + pd.Timedelta(minutes=2))
        self.assertNotIn(3, [m for m, _ in rows])  # bar_start T0+2 == valid_until

    def test_final_bar_ending_at_valid_until_is_eligible(self):
        rows = self.run_level(valid_until=T0 + pd.Timedelta(minutes=2))
        self.assertEqual(rows[-1], (2, EVALUATED))  # bar_end == valid_until, bar_start < valid_until

    def test_available_at_later_than_valid_from_controls(self):
        rows = self.run_level(available_at=T0 + pd.Timedelta(minutes=2), valid_from=T0)
        self.assertEqual(rows[:2], [(2, PENDING_LEVEL), (3, EVALUATED)])

    def test_valid_from_later_than_available_at_controls(self):
        rows = self.run_level(available_at=T0 - pd.Timedelta(minutes=10), valid_from=T0 + pd.Timedelta(minutes=2))
        self.assertEqual(rows, [(3, EVALUATED), (4, EVALUATED), (5, EVALUATED)])

    def test_null_valid_from_leaves_available_at_in_control(self):
        rows = self.run_level(available_at=T0 + pd.Timedelta(minutes=1))
        self.assertEqual(rows, [(1, PENDING_LEVEL)] + [(m, EVALUATED) for m in (2, 3, 4, 5)])

    def test_null_valid_until_has_no_static_upper_cutoff(self):
        rows = self.run_level()
        self.assertEqual(rows, [(m, EVALUATED) for m in range(6)])


class ContractTests(unittest.TestCase):
    def test_specific_and_agnostic_scope(self):
        rows = [(99.0, 100.25, 98.75, 99.75)]
        mismatch = evaluate_level_interactions(bars_from(rows, "MNQ 03-27"), pd.DataFrame([level()])).iloc[0]
        self.assertEqual(mismatch["status"], CONTRACT_MISMATCH)
        self.assertEqual(facts(mismatch), (None,) * 5)
        agnostic = evaluate_level_interactions(bars_from(rows, "MNQ 03-27"), pd.DataFrame([level(scope="AGNOSTIC")])).iloc[0]
        self.assertEqual(agnostic["status"], EVALUATED)
        self.assertEqual(facts(agnostic), (True, True, False, True, True))

    def test_scope_contract_consistency_is_enforced(self):
        bad_specific = level()
        bad_specific["contract"] = None
        bad_agnostic = level(scope="AGNOSTIC")
        bad_agnostic["contract"] = "MNQ 12-26"
        for bad in (bad_specific, bad_agnostic):
            with self.subTest(bad["contract_scope"]):
                with self.assertRaises(LevelInteractionError):
                    evaluate([(99.0, 99.5, 98.5, 99.0)], bad)


class TickSizeTests(unittest.TestCase):
    def test_alternate_tick_from_instrument_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "tst.json").write_text(json.dumps({
                "instrument_id": "TST", "name": "Synthetic", "asset_class": "futures", "exchange": "TEST",
                "currency": "USD", "tick_size_points": 0.1, "point_value_usd": 10, "tick_value_usd": 1,
            }), encoding="utf-8")
            lvl = level(10.0, instrument="TST")
            rows = [(9.9, 10.1, 9.8, 9.9), (0.1 + 0.2 + 9.6, 10.0, 9.8, 9.9)]  # 9.9000000000000004 accepted
            out = evaluate(rows, lvl, instrument_config_dir=folder)
            self.assertEqual(facts(out.iloc[0]), (True, True, False, True, True))  # one 0.1 tick beyond
            self.assertEqual(out.iloc[0]["first_tradable_above"], 10.1)
            self.assertEqual(facts(out.iloc[1]), (True, False, False, True, False))
            with self.assertRaises(LevelInteractionError):
                evaluate([(9.9, 10.15, 9.8, 9.9)], lvl, instrument_config_dir=folder)  # off-grid bar price

    def test_mnq_tick_comes_from_metadata(self):
        out = evaluate([(99.0, 100.25, 98.75, 99.75)], level())
        self.assertEqual(out.iloc[0]["first_tradable_above"], 100.25)
        with self.assertRaises(LevelInteractionError):
            evaluate([(99.0, 100.1, 98.75, 99.75)], level())  # 100.1 is off the 0.25 grid
        with self.assertRaises(InstrumentError):
            evaluate([(99.0, 99.5, 98.5, 99.0)], level(instrument="ZZZ"))


class ValidationTests(unittest.TestCase):
    def test_invalid_input_raises(self):
        good_rows = [(99.0, 99.5, 98.5, 99.0)]
        cases = {
            "orientation": (good_rows, [level(orientation="SIDEWAYS")]),
            "scope": (good_rows, [{**level(), "contract_scope": "ANY"}]),
            "nan level": (good_rows, [level(float("nan"))]),
            "naive available_at": (good_rows, [level(available_at=pd.Timestamp("2026-09-22 09:00"))]),
            "valid_until before available_at": (good_rows, [level(valid_until=T0 - pd.Timedelta(hours=1))]),
            "duplicate id": (good_rows, [level(), level(99.0)]),
            "two instruments": (good_rows, [level(), level(level_id="L2", instrument="MES")]),
            "inconsistent ohlc": ([(99.0, 98.5, 98.0, 99.0)], [level()]),
            "nan price": ([(99.0, float("nan"), 98.5, 99.0)], [level()]),
        }
        for name, (rows, levels) in cases.items():
            with self.subTest(name):
                with self.assertRaises((LevelInteractionError, InstrumentError)):
                    evaluate(rows, *levels)
        with self.assertRaises(LevelInteractionError):
            evaluate_level_interactions(bars_from(good_rows).tz_localize(None), pd.DataFrame([level()]))


class RepresentationTests(unittest.TestCase):
    def test_nullable_dtypes_and_false_vs_na(self):
        out = evaluate([(99.0, 99.5, 98.5, 99.0)] * 2, level(available_at=T0))
        self.assertEqual(list(out.columns), OUTPUT_COLUMNS)
        for name in PRIMITIVES:
            self.assertEqual(str(out[name].dtype), "boolean")
        self.assertTrue(out.iloc[0][list(PRIMITIVES)].isna().all())    # pending: not evaluated
        self.assertFalse(out.iloc[1][list(PRIMITIVES)].isna().any())   # evaluated
        self.assertFalse(out.iloc[1][list(PRIMITIVES)].astype(bool).any())  # and all genuinely False

    def test_deterministic_and_order_independent(self):
        rows = [(99.0, 100.25, 98.75, 99.75), (101.0, 101.0, 99.75, 100.25), (100.0, 100.5, 99.5, 100.25)]
        levels = [level(100.0, level_id="a"), level(100.0, "LOWER", level_id="b"), level(100.125, "NEUTRAL", level_id="c")]
        first = evaluate(rows, *levels)
        bars = bars_from(rows).iloc[::-1]
        second = evaluate_level_interactions(bars, pd.DataFrame(levels[::-1]))
        pd.testing.assert_frame_equal(first, second)

    def test_interactions_only_filter(self):
        rows = [(99.0, 99.5, 98.5, 99.0), (99.0, 100.25, 98.75, 99.75)]
        out = evaluate(rows, level(), interactions_only=True)
        self.assertEqual(len(out), 1)
        self.assertTrue(out.iloc[0]["touch"])


class MarketContextHelperTests(unittest.TestCase):
    @staticmethod
    def session(day: date, base: float) -> pd.DataFrame:
        start = pd.Timestamp.combine(day - timedelta(days=1), time(18, 0)).tz_localize(TZ)
        labels = pd.date_range(start + pd.Timedelta(minutes=1), pd.Timestamp.combine(day, time(17, 0)).tz_localize(TZ), freq="min")
        wave = base + np.round(np.sin(np.arange(len(labels)) / 40.0) * 20) * 0.25
        return pd.DataFrame({"open": wave, "high": wave + 0.5, "low": wave - 0.5, "close": wave + 0.25,
                             "contract": "MNQ 12-26"}, index=pd.DatetimeIndex(labels, name="timestamp_et"))

    def test_m5_levels_orientation_scope_and_valid_until(self):
        mon, tue = date(2026, 9, 21), date(2026, 9, 22)
        bars = pd.concat([self.session(mon, 100.0), self.session(tue, 101.0)])
        context = build_market_context(bars, SPEC, instrument_id="MNQ")
        levels = market_context_levels(context, SPEC)
        tuesday = levels[levels["level_id"].str.endswith(tue.isoformat())].set_index("level_id")
        self.assertEqual(tuesday.loc[f"asia_2000_0000:high:{tue}", "orientation"], "UPPER")
        self.assertEqual(tuesday.loc[f"asia_2000_0000:low:{tue}", "orientation"], "LOWER")
        self.assertEqual(tuesday.loc[f"previous_day:close:{tue}", "orientation"], "NEUTRAL")
        self.assertNotIn(f"asia_2000_0000:close:{tue}", tuesday.index)
        self.assertTrue((tuesday["valid_from"] == pd.Timestamp("2026-09-21 18:00", tz=TZ)).all())
        self.assertTrue((tuesday["valid_until"] == pd.Timestamp("2026-09-22 17:00", tz=TZ)).all())
        self.assertTrue((tuesday["contract_scope"] == "SPECIFIC").all())

        out = evaluate_market_context_interactions(bars, context, SPEC,
                                                   context_ids=["previous_day", "previous_rth", "asia_2000_0000"])
        session_open, session_close = pd.Timestamp("2026-09-21 18:00", tz=TZ), pd.Timestamp("2026-09-22 17:00", tz=TZ)
        tuesday_rows = out[out["level_id"].str.endswith(tue.isoformat())]
        self.assertTrue((tuesday_rows["bar_start"] >= session_open).all())  # target-session scope (start)
        self.assertTrue((tuesday_rows["bar_end"] <= session_close).all())   # target-session scope (end)
        prev_day = out[out["level_id"] == f"previous_day:high:{tue}"]
        self.assertEqual(prev_day.iloc[0]["bar_end"], pd.Timestamp("2026-09-21 18:01", tz=TZ))
        self.assertTrue((prev_day["status"] == EVALUATED).all())  # confirming bar is in the source session
        prev_rth = out[out["level_id"] == f"previous_rth:high:{tue}"]
        self.assertEqual(prev_rth["bar_end"].min(), pd.Timestamp("2026-09-21 18:01", tz=TZ))  # not Mon 16:01-17:00
        asia = out[out["level_id"] == f"asia_2000_0000:high:{tue}"]
        self.assertEqual(asia.iloc[0]["bar_end"], pd.Timestamp("2026-09-22 00:00", tz=TZ))
        self.assertEqual(asia.iloc[0]["status"], PENDING_LEVEL)  # in-session confirming bar


if __name__ == "__main__":
    unittest.main()
