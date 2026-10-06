"""Shared liquidity consumption contract and External derived view (IL-I1; D-143). Synthetic only."""

from decimal import Decimal
import unittest

import pandas as pd

from ms_fixtures import BASE, SPEC, ohlc_bars, slot_end
from src.liquidity.consumption import (
    ACTIVE,
    CONSUMED,
    EXTERNAL_CLUSTER,
    EXTERNAL_DAILY,
    TERMINATED,
    ConsumableObject,
    ConsumableVersion,
    ConsumptionError,
    build_minute_tape,
    current_version,
    evaluate,
    external_objects,
    threshold_ticks,
)
from src.liquidity.contract import EXTENDED, FORMED, INTERNAL, LOWER, MERGED, REQ, EQ, UPPER

TICK = Decimal("0.25")


def ticks(price):
    return int(round((BASE + price) / 0.25))


def tape(rows, cutoff_k=None, **kwargs):
    bars = ohlc_bars(rows, "1m", **kwargs)
    cutoff = slot_end(len(rows) - 1 if cutoff_k is None else cutoff_k, "1m")
    return build_minute_tape(bars, SPEC, instrument_id="MNQ", replay_cutoff=cutoff, tick=TICK)


def obj(side, price, *, at_k, tol=4, contract="MNQ 12-26", versions=None, **kwargs):
    if versions is None:
        versions = ((f"v@{price}", price, tol, at_k),)
    return ConsumableObject("obj", "INTERNAL_LEVEL", INTERNAL, side, contract,
                            tuple(ConsumableVersion(ref, ticks(p), t, slot_end(k, "1m")) for ref, p, t, k in versions),
                            **kwargs)


FLAT = (50, 50.25, 49.75, 50)   # quiet minute around 20,050.00


def rows_with(*bars, n=12):
    rows = [FLAT] * n
    for k, row in bars:
        rows[k] = row
    return rows


class PredicateTests(unittest.TestCase):
    """E1 / E2 / E3 / E4: strict beyond θ, equality, gap-through, same-close admission."""

    def test_threshold(self):
        self.assertEqual(threshold_ticks(UPPER, 100, 4), 104)
        self.assertEqual(threshold_ticks(LOWER, 100, 6), 94)

    def test_e1_upper_within_equality_beyond(self):
        t = tape(rows_with((3, (50, 50.75, 50, 50.5)), (5, (50, 51.00, 50, 50.5)), (7, (50.5, 51.25, 50, 51))))
        out = evaluate(obj(UPPER, 50.00, at_k=1), t)
        self.assertEqual(out.status, CONSUMED)
        self.assertEqual(out.ended_at, slot_end(7, "1m"))
        self.assertEqual(out.threshold, ticks(51.00))
        self.assertEqual(out.excess_ticks, 1)
        self.assertFalse(out.gap_through)
        self.assertEqual(out.max_excursion_ticks, 4)          # 51.00 equality reached before consumption

    def test_e2_lower_and_gap_through(self):
        t = tape(rows_with((3, (-50, -49.75, -51.00, -50)), (5, (-50.5, -50, -51.25, -50.5))), )
        out = evaluate(obj(LOWER, -50.00, at_k=1), t)
        self.assertEqual((out.status, out.ended_at), (CONSUMED, slot_end(5, "1m")))
        t2 = tape(rows_with((4, (-52.00, -51.5, -52.25, -52))))
        out2 = evaluate(obj(LOWER, -50.00, at_k=1), t2)
        self.assertEqual(out2.ended_at, slot_end(4, "1m"))
        self.assertTrue(out2.gap_through)

    def test_e3_external_tolerance(self):
        t = tape(rows_with((3, (100, 101.50, 99, 100)), (6, (100, 101.75, 99, 100))))
        out = evaluate(obj(UPPER, 100.00, at_k=1, tol=6), t)
        self.assertEqual(out.ended_at, slot_end(6, "1m"))

    def test_e4_same_close_admission_not_tested_against_its_bar(self):
        t = tape(rows_with((4, (50, 52.00, 50, 51)), (6, (50, 51.25, 50, 51))))
        out = evaluate(obj(UPPER, 50.00, at_k=4), t)          # available at e(4); bar 4 itself exceeds θ
        self.assertEqual(out.ended_at, slot_end(6, "1m"))

    def test_prospective_versions_bar_uses_start_version(self):
        # v1 p=50.00 (θ 51.00) from k=1; v2 p=51.00 (θ 52.00) from e(5)
        versions = (("v1", 50.00, 4, 1), ("v2", 51.00, 4, 5))
        t = tape(rows_with((5, (50, 51.25, 50, 51)), (7, (51, 51.75, 51, 51.5)), (9, (51, 52.25, 51, 52))))
        out = evaluate(obj(UPPER, 0, at_k=1, versions=versions), t)
        self.assertEqual((out.status, out.ended_at, out.version_ref), (CONSUMED, slot_end(5, "1m"), "v1"))
        t2 = tape(rows_with((7, (51, 51.75, 51, 51.5)), (9, (51, 52.25, 51, 52))))
        out2 = evaluate(obj(UPPER, 0, at_k=1, versions=versions), t2)
        self.assertEqual((out2.ended_at, out2.version_ref), (slot_end(9, "1m"), "v2"))

    def test_later_version_never_undoes_consumption(self):
        versions = (("v1", 50.00, 4, 1), ("v2", 51.50, 4, 8))
        t = tape(rows_with((5, (50, 51.25, 50, 51))))
        out = evaluate(obj(UPPER, 0, at_k=1, versions=versions), t)
        self.assertEqual((out.status, out.version_ref), (CONSUMED, "v1"))

    def test_active_at_cutoff(self):
        out = evaluate(obj(UPPER, 50.00, at_k=1), tape(rows_with()))
        self.assertEqual((out.status, out.ended_at), (ACTIVE, None))


class TerminationTests(unittest.TestCase):
    def test_gap_terminates_as_data_gap(self):
        rows = rows_with()
        rows[6] = None                                         # missing expected minute
        out = evaluate(obj(UPPER, 50.00, at_k=1), tape(rows))
        self.assertEqual((out.status, out.reason, out.ended_at), (TERMINATED, "DATA_GAP", slot_end(6, "1m")))
        self.assertTrue(out.trigger_ref.startswith("CONTINUITY_BREAK:1m|"))

    def test_trailing_missing_minutes_terminate(self):
        rows = rows_with()[:6]
        bars = ohlc_bars(rows, "1m")
        t = build_minute_tape(bars, SPEC, instrument_id="MNQ", replay_cutoff=slot_end(9, "1m"), tick=TICK)
        out = evaluate(obj(UPPER, 50.00, at_k=1), t)
        self.assertEqual((out.reason, out.ended_at), ("DATA_GAP", slot_end(6, "1m")))

    def test_contract_change_terminates(self):
        contracts = ["MNQ 09-26"] * 6 + ["MNQ 12-26"] * 6
        out = evaluate(obj(UPPER, 50.00, at_k=1, contract="MNQ 09-26"), tape(rows_with(), contracts=contracts))
        self.assertEqual((out.reason, out.ended_at), ("CONTRACT_CHANGE", slot_end(6, "1m")))

    def test_caller_stop(self):
        out = evaluate(obj(UPPER, 50.00, at_k=1, stop_at=slot_end(4, "1m"), stop_reason="RELEASED"),
                       tape(rows_with((7, (50, 52, 50, 51)))))
        self.assertEqual((out.status, out.reason, out.ended_at), (TERMINATED, "RELEASED", slot_end(4, "1m")))

    def test_consumption_wins_over_stop_on_the_stop_bar(self):
        out = evaluate(obj(UPPER, 50.00, at_k=1, stop_at=slot_end(4, "1m"), stop_reason="MERGED"),
                       tape(rows_with((4, (50, 52, 50, 51)))))
        self.assertEqual((out.status, out.ended_at), (CONSUMED, slot_end(4, "1m")))

    def test_fail_closed_inputs(self):
        t = tape(rows_with())
        with self.assertRaises(ConsumptionError):
            evaluate(obj(UPPER, 50.00, at_k=1, contract="MNQ 03-27"), t)
        bad = ConsumableObject("x", "INTERNAL_LEVEL", INTERNAL, UPPER, "MNQ 12-26",
                               (ConsumableVersion("v", 1, 4, slot_end(1, "1m") + pd.Timedelta(seconds=30)),))
        with self.assertRaises(ConsumptionError):
            evaluate(bad, t)

    def test_zero_output_tape(self):
        bars = ohlc_bars(rows_with(), "1m")
        t = build_minute_tape(bars, SPEC, instrument_id="MNQ", replay_cutoff=slot_end(0, "1m") - pd.Timedelta(hours=1),
                              tick=TICK)
        self.assertEqual(t.episodes, [])


class ExternalViewTests(unittest.TestCase):
    def frames(self):
        t = lambda k: slot_end(k, "1m")  # noqa: E731
        members = pd.DataFrame([
            {"member_id": "lm_d1", "member_kind": "DAILY_HIGH", "price": BASE + 100, "available_at": t(1), "contract": "C"},
            {"member_id": "lm_d2", "member_kind": "DAILY_LOW", "price": BASE + 90, "available_at": t(1), "contract": "C"},
            {"member_id": "lm_s", "member_kind": "SESSION_REFERENCE_HIGH", "price": BASE + 95, "available_at": t(1),
             "contract": "C"},
            {"member_id": "lm_a", "member_kind": "HTF_EQREQ_HIGH", "price": BASE + 99, "available_at": t(2), "contract": "C"},
            {"member_id": "lm_b", "member_kind": "HTF_EQREQ_HIGH", "price": BASE + 100, "available_at": t(2), "contract": "C"},
            {"member_id": "lm_c", "member_kind": "HTF_EQREQ_HIGH", "price": BASE + 101, "available_at": t(4), "contract": "C"},
            {"member_id": "lm_e", "member_kind": "HTF_EQREQ_HIGH", "price": BASE + 102, "available_at": t(3), "contract": "C"},
            {"member_id": "lm_f", "member_kind": "HTF_EQREQ_HIGH", "price": BASE + 102.5, "available_at": t(3),
             "contract": "C"},
        ])
        base = {"structure_type": REQ, "reference_family": "4H", "orientation": UPPER, "contract": "C"}
        structures = pd.DataFrame([
            {**base, "structure_id": "ls_v1", "member_ids": ("lm_a", "lm_b"), "available_at": t(2), "change_kind": FORMED,
             "supersedes": ()},
            {**base, "structure_id": "ls_w1", "member_ids": ("lm_e", "lm_f"), "available_at": t(3), "change_kind": FORMED,
             "supersedes": ()},
            {**base, "structure_id": "ls_v2", "member_ids": ("lm_a", "lm_b", "lm_c"), "available_at": t(4),
             "change_kind": EXTENDED, "supersedes": ("ls_v1",)},
            {**base, "structure_id": "ls_m", "member_ids": ("lm_a", "lm_b", "lm_c", "lm_e", "lm_f"), "available_at": t(6),
             "change_kind": MERGED, "supersedes": ("ls_v2", "ls_w1")},
        ])
        return members, structures

    def test_daily_objects_and_lineages(self):
        objects = {o.obj.object_id: o for o in external_objects(*self.frames(), TICK)}
        daily = [o for o in objects.values() if o.obj.object_kind == EXTERNAL_DAILY]
        self.assertEqual(sorted(o.obj.object_id for o in daily), ["lm_d1", "lm_d2"])   # session refs excluded
        clusters = [o for o in objects.values() if o.obj.object_kind == EXTERNAL_CLUSTER]
        self.assertEqual(len(clusters), 3)                       # v-lineage, w-lineage, merged lineage
        v = next(o for o in clusters if o.obj.versions[0].version_ref == "ls_v1")
        self.assertEqual([x.version_ref for x in v.obj.versions], ["ls_v1", "ls_v2"])  # EXTENDED continues
        self.assertEqual([x.price_ticks for x in v.obj.versions], [ticks(100), ticks(101)])  # outermost moves
        self.assertEqual(v.obj.stop_at, slot_end(6, "1m"))
        self.assertEqual(v.obj.stop_reason, MERGED)
        merged = next(o for o in clusters if o.merged_from)
        self.assertEqual(len(merged.merged_from), 2)
        self.assertEqual(merged.obj.versions[0].price_ticks, ticks(102.5))
        self.assertTrue(all(o.obj.versions[0].tolerance_ticks == 6 for o in objects.values()))
        self.assertEqual(current_version(v.obj, slot_end(3, "1m")).version_ref, "ls_v1")
        self.assertEqual(current_version(v.obj, slot_end(4, "1m")).version_ref, "ls_v2")

    def test_eq_requires_one_price(self):
        members, structures = self.frames()
        structures.loc[0, "structure_type"] = EQ
        with self.assertRaises(ConsumptionError):
            external_objects(members, structures, TICK)


if __name__ == "__main__":
    unittest.main()
