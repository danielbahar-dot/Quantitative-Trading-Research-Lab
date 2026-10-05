"""Swing candidate audit + invariant tests (SW-I3). Synthetic data only."""

from pathlib import Path
import unittest

import pandas as pd

from src.data.continuity import CONTRACT_CHANGE, INCOMPLETE_BAR, MISSING_EXPECTED_BUCKET, MISSING_EXPECTED_SESSION
from src.market_structure.swing import LOWER, SWING_TIMEFRAMES, UPPER, swing_id
from src.market_structure.swing_audit import (
    AUDIT_STATUSES,
    CANDIDATE_AUDIT_COLUMNS,
    CONFIRMED,
    CONTINUITY_BREAK,
    INSUFFICIENT_FUTURE_COVERAGE,
    INSUFFICIENT_LEFT_HISTORY,
    INVALIDATED_STRICT_EXCEED,
    INVARIANTS,
    audit_swing_candidates,
    swing_invariants,
)
from src.market_structure.swing_detector import build_swing_points
from test_swing_detector import BASE, DEF11, REF22, SPEC, bars_for, ends

TICKS_PER_POINT = 4


def audit(bars, tf="5m", definition=REF22):
    return audit_swing_candidates(bars, tf, SPEC, definition, instrument_id="MNQ")


def at(frame, orientation, source_index, tf="5m"):
    e = ends(tf)
    hit = frame[(frame["orientation"] == orientation) & (frame["source_at"] == e[source_index])]
    assert len(hit) == 1, hit
    return hit.iloc[0]


class StatusTests(unittest.TestCase):
    def test_schema_and_vocabulary(self):
        out = audit(bars_for("5m", [100, 103, 110, 106, 105]))
        self.assertEqual(list(out.columns), list(CANDIDATE_AUDIT_COLUMNS))
        self.assertEqual(AUDIT_STATUSES, (CONFIRMED, INVALIDATED_STRICT_EXCEED, INSUFFICIENT_LEFT_HISTORY,
                                          INSUFFICIENT_FUTURE_COVERAGE, CONTINUITY_BREAK))
        self.assertTrue(set(out["status"]) <= set(AUDIT_STATUSES))

    def test_confirmed(self):
        e = ends("5m")
        row = at(audit(bars_for("5m", [100, 103, 110, 106, 105])), UPPER, 2)
        self.assertEqual((row["status"], row["available_at"], row["price"]), (CONFIRMED, e[4], BASE + 110))
        self.assertTrue(row["swing_id"].startswith("sw_"))
        self.assertTrue(pd.isna(row["invalidating_side"]) and pd.isna(row["break_reason"]))

    def test_left_strict_exceed_nearest(self):
        e = ends("5m")
        row = at(audit(bars_for("5m", [113, 112, 110, 106, 105])), UPPER, 2)
        self.assertEqual((row["status"], row["invalidating_side"], row["invalidating_bar_end"], row["invalidating_excess_ticks"]),
                         (INVALIDATED_STRICT_EXCEED, "LEFT", e[1], 2 * TICKS_PER_POINT))
        self.assertTrue(pd.isna(row["swing_id"]) and pd.isna(row["available_at"]))

    def test_right_strict_exceed_first(self):
        e = ends("5m")
        row = at(audit(bars_for("5m", [100, 103, 110, 106, 111, 112, 100])), UPPER, 2)
        self.assertEqual((row["status"], row["invalidating_side"], row["invalidating_bar_end"], row["invalidating_excess_ticks"]),
                         (INVALIDATED_STRICT_EXCEED, "RIGHT", e[4], 1 * TICKS_PER_POINT))

    def test_lower_excess_is_positive_magnitude(self):
        e = ends("5m")
        lows = [60, 57, 50, 49.5, 55]
        row = at(audit(bars_for("5m", [l + 50 for l in lows], lows)), LOWER, 2)
        self.assertEqual((row["status"], row["invalidating_bar_end"], row["invalidating_excess_ticks"]),
                         (INVALIDATED_STRICT_EXCEED, e[3], 2))

    def test_observed_right_exceed_before_break_stays_invalidated(self):
        row = at(audit(bars_for("5m", [100, 103, 110, 111, 0, 100, 101, 102], absent={4})), UPPER, 2)
        self.assertEqual((row["status"], row["invalidating_side"]), (INVALIDATED_STRICT_EXCEED, "RIGHT"))
        self.assertTrue(pd.isna(row["break_reason"]))

    def test_insufficient_left_history(self):
        out = audit(bars_for("5m", [100, 110, 105, 104, 103]))
        self.assertEqual(at(out, UPPER, 1)["status"], INSUFFICIENT_LEFT_HISTORY)

    def test_insufficient_future_coverage_at_data_end(self):
        self.assertEqual(at(audit(bars_for("5m", [100, 103, 110, 106])), UPPER, 2)["status"], INSUFFICIENT_FUTURE_COVERAGE)

    def test_continuity_break_reasons(self):
        cases = {
            MISSING_EXPECTED_BUCKET: dict(highs=[100, 103, 110, 106, 0, 100, 101], absent={4}),
            INCOMPLETE_BAR: dict(highs=[100, 103, 110, 106, 105, 100, 101], incomplete={4}),
            CONTRACT_CHANGE: dict(highs=[100, 103, 110, 106, 105, 100, 101], contracts=["A"] * 4 + ["B"] * 3),
        }
        for reason, case in cases.items():
            with self.subTest(reason):
                row = at(audit(bars_for("5m", case.pop("highs"), **case)), UPPER, 2)
                self.assertEqual((row["status"], row["break_reason"]), (CONTINUITY_BREAK, reason))
                self.assertTrue(pd.isna(row["swing_id"]))

    def test_missing_session_and_precedence(self):
        highs = [90, 95, 100, 104, 110, 104] + [0] * 6 + [100, 101, 103, 101, 100, 99]
        row = at(audit(bars_for("4H", highs, absent=set(range(6, 12))), "4H"), UPPER, 4, "4H")
        self.assertEqual((row["status"], row["break_reason"]), (CONTINUITY_BREAK, MISSING_EXPECTED_SESSION))
        contracts = ["A"] * 6 + ["X"] * 6 + ["B"] * 6  # session gap outranks the contract change at the same boundary
        row = at(audit(bars_for("4H", highs, contracts=contracts, absent=set(range(6, 12))), "4H"), UPPER, 4, "4H")
        self.assertEqual(row["break_reason"], MISSING_EXPECTED_SESSION)


class CandidateShapeTests(unittest.TestCase):
    def test_equal_values_do_not_invalidate_and_separated_equals_are_separate(self):
        out = audit(bars_for("5m", [98, 100, 110, 105, 110, 100, 99]))
        rows = out[(out["orientation"] == UPPER) & (out["price"] == BASE + 110)]
        self.assertEqual(rows["status"].tolist(), [CONFIRMED, CONFIRMED])

    def test_adjacent_plateau_is_one_candidate(self):
        e = ends("5m")
        out = audit(bars_for("5m", [98, 100, 110, 110, 105, 104]))
        rows = out[(out["orientation"] == UPPER) & (out["price"] == BASE + 110)]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows.iloc[0]["source_at"], rows.iloc[0]["source_end_at"], rows.iloc[0]["status"]),
                         (e[2], e[3], CONFIRMED))

    def test_every_observation_belongs_to_exactly_one_candidate(self):
        bars = bars_for("5m", [100, 101, 101, 99, 99, 99, 104, 102])
        out = audit(bars)
        for orientation in (UPPER, LOWER):
            spans = out[out["orientation"] == orientation][["source_at", "source_end_at"]]
            covered = sum(((pd.Series(ends("5m")[:8]) >= s) & (pd.Series(ends("5m")[:8]) <= t)).sum()
                          for s, t in spans.itertuples(index=False))
            self.assertEqual(covered, 8)


class ReconciliationTests(unittest.TestCase):
    FIXTURES = [
        dict(highs=[100, 103, 110, 106, 105], lows=[60, 57, 50, 54, 55]),
        dict(highs=[98, 100, 110, 105, 110, 100, 99]),
        dict(highs=[98, 100, 110, 110, 110, 105, 104, 109, 101, 100]),
        dict(highs=[100, 103, 110, 106, 0, 100, 103, 112, 106, 105], absent={4}),
        dict(highs=[100, 103, 110, 111, 108, 107], contracts=["A"] * 3 + ["B"] * 3),
    ]

    def test_confirmed_audit_equals_canonical(self):
        for definition in (REF22, DEF11):
            for fixture in self.FIXTURES:
                fixture = dict(fixture)
                bars = bars_for("5m", fixture.pop("highs"), fixture.pop("lows", None), **fixture)
                with self.subTest(definition=definition, fixture=fixture):
                    canonical = build_swing_points(bars, "5m", SPEC, definition, instrument_id="MNQ")
                    confirmed = audit(bars, definition=definition).query("status == @CONFIRMED")
                    self.assertEqual(set(confirmed["swing_id"]), set(canonical["swing_id"]))

    def test_all_six_timeframes_reconcile(self):
        for tf in SWING_TIMEFRAMES:
            with self.subTest(tf=tf):
                bars = bars_for(tf, [100, 103, 110, 106, 105, 104, 108, 103], [60, 57, 50, 54, 55, 51, 56, 52])
                canonical = build_swing_points(bars, tf, SPEC, REF22, instrument_id="MNQ")
                confirmed = audit_swing_candidates(bars, tf, SPEC, REF22, instrument_id="MNQ").query("status == @CONFIRMED")
                self.assertEqual(set(confirmed["swing_id"]), set(canonical["swing_id"]))
                for row in confirmed.itertuples(index=False):
                    self.assertEqual(row.swing_id, swing_id(
                        definition_version=row.definition_version, instrument_id=row.instrument_id, contract_scope="SPECIFIC",
                        contract=row.contract, timeframe=row.timeframe, orientation=row.orientation,
                        left_depth=row.left_depth, right_depth=row.right_depth, source_ref=row.source_ref))


class InvariantTests(unittest.TestCase):
    def test_canonical_swings_have_zero_violations(self):
        bars = bars_for("5m", [98, 100, 110, 110, 105, 104, 109, 101, 100], [60, 57, 50, 50, 55, 51, 56, 52, 53])
        swings = build_swing_points(bars, "5m", SPEC, REF22, instrument_id="MNQ")
        report = swing_invariants(swings, bars, "5m", SPEC, REF22, instrument_id="MNQ")
        self.assertEqual(int(report["violations"].sum()), 0, report[report["violations"] > 0])
        self.assertEqual(len(report), 2 * (len(INVARIANTS) - 1))

    def test_tampered_swing_is_detected(self):
        bars = bars_for("5m", [98, 100, 110, 106, 105, 104])
        swings = build_swing_points(bars, "5m", SPEC, REF22, instrument_id="MNQ")
        tampered = swings.copy()
        tampered["available_at"] = tampered["available_at"] + pd.Timedelta(minutes=5)
        report = swing_invariants(tampered, bars, "5m", SPEC, REF22, instrument_id="MNQ").set_index(["orientation", "invariant"])
        self.assertEqual(report.loc[(UPPER, "available_at_rth_post_plateau_bar_end"), "violations"], 1)
        self.assertEqual(report.loc[(UPPER, "passes_validate_swing_points"), "violations"], 0)  # envelope still valid


class BoundaryTests(unittest.TestCase):
    def test_audit_does_not_use_detector_internals(self):
        source = Path(__file__).resolve().parents[1].joinpath("src", "market_structure", "swing_audit.py").read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
        self.assertFalse([line for line in imports if "swing_detector" in line])
        self.assertNotIn("_confirmed_plateaus", source)
        self.assertNotIn("_one_minute_observations", source)
        self.assertNotIn("_tick_indices", source)


if __name__ == "__main__":
    unittest.main()
