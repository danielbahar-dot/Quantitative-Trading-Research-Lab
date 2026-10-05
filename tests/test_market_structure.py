"""Generic Market Structure engine tests (MS-I2; MARKET_STRUCTURE_SPEC rev 2.5, D-139–D-142). Synthetic only."""

import random
import unittest
from unittest import mock

import pandas as pd

from ms_fixtures import (
    EX_A,
    EX_B,
    EX_C,
    SPEC,
    event_story,
    ohlc_bars,
    role_story,
    run_structure,
    slot_end,
    structure_definition,
)
from src.market_structure.structure import (
    BULLISH,
    CONTRACT_CHANGE,
    CONTRACT_CHANGE_REESTABLISHMENT,
    DATA_GAP,
    DATA_GAP_REESTABLISHMENT,
    DATA_START,
    PROTECTION,
    RESET,
    StructureError,
    build_market_structure,
    continuity_ref,
    direction_namespace,
    role_namespace,
    run_market_structure,
)
from src.market_structure.swing import bar_span_ref
from src.data.continuity import ContinuityError, continuity_segments
from src.market_structure import structure as structure_module
from src.state.contract import materialize_state_to_bars, validate_transitions

A, B = "MNQ 09-26", "MNQ 12-26"
TABLES = ("swing_breaks", "episodes", "roles", "events", "anomalies", "direction_transitions", "role_transitions")


def m7(frame):
    return frame.drop(columns=["run_id"])


def restricted(run, cutoff):
    """Every output table restricted to available_at <= cutoff, without run identity."""
    out = {}
    for name in TABLES:
        frame = getattr(run, name)
        column = "bar_end" if name == "anomalies" else "available_at"
        keep = pd.to_datetime(frame[column], utc=True) <= cutoff if len(frame) else []
        out[name] = frame.loc[keep].drop(columns=["run_id"]).reset_index(drop=True) if len(frame) else frame.drop(
            columns=["run_id"])
    return out


def assert_same(got, want, obj):
    if got.empty and want.empty:
        assert list(got.columns) == list(want.columns), obj
        return
    pd.testing.assert_frame_equal(got, want, obj=obj)


class SpecExampleTests(unittest.TestCase):
    """§H.0 EX-A / EX-B / EX-C derived outcomes (H.1, H.5, H.6, H.8)."""

    def test_ex_a_establishment_retained_and_replaced_protection(self):
        run = run_structure(EX_A)
        self.assertEqual(event_story(run), [(10, "ESTABLISHMENT", BULLISH, "U110@5"), (18, "BOS", BULLISH, "U118@12"),
                                            (26, "BOS", BULLISH, "U126@20")])
        self.assertEqual(role_story(run), [
            ("BULL_ANCHOR", "L100@2", 4, "ENDED", 10),
            ("BEAR_ANCHOR", "U110@5", 7, "BROKEN", 10),
            ("BULL_CANDIDATE_TARGET", "U110@5", 7, "CONSUMED", 10),
            ("BEAR_CANDIDATE_TARGET", "L104@7", 9, "ENDED", 10),
            ("PROTECTION", "L104@7", 10, "REPLACED", 26),
            ("TARGET", "U118@12", 14, "CONSUMED", 18),
            ("TARGET", "U126@20", 22, "CONSUMED", 26),
            ("PROTECTION", "L112@22", 26, None, None),
        ])

    def test_retained_protection_keeps_identity_and_parent(self):
        run = run_structure(EX_A)
        protections = run.roles[run.roles["role_kind"] == PROTECTION].sort_values("assigned_at")
        events = run.events.set_index("kind")
        first, second = protections.iloc[0], protections.iloc[1]
        establishment = run.events[run.events["kind"] == "ESTABLISHMENT"].iloc[0]
        bos = run.events[run.events["kind"] == "BOS"].sort_values("event_at")
        self.assertEqual(first["parent_key"], establishment["event_id"])     # promotion event, never updated
        self.assertEqual(second["parent_key"], bos.iloc[1]["event_id"])
        at_bos1 = run.role_transitions[run.role_transitions["transition_at"] == bos.iloc[0]["event_at"]]
        self.assertNotIn(first["role_id"], set(at_bos1["entity_id"]))      # no transition at BOS without replacement
        self.assertIn(first["role_id"], bos.iloc[0]["role_refs"])           # read by the BOS
        self.assertEqual(len(events), 3)
        target2 = run.roles[(run.roles["role_kind"] == "TARGET")].sort_values("assigned_at").iloc[1]
        self.assertEqual(target2["parent_key"], bos.iloc[0]["event_id"])   # target is leg-scoped

    def test_ex_b_equal_targets_and_pullbacks(self):
        run = run_structure(EX_B)
        self.assertEqual(event_story(run), [(14, "ESTABLISHMENT", BULLISH, "U110@5")])
        story = role_story(run)
        self.assertIn(("BULL_CANDIDATE_TARGET", "U110@5", 7, "CONSUMED", 14), story)
        self.assertIn(("PROTECTION", "L104@7", 14, None, None), story)       # earliest of the equal pullbacks
        self.assertFalse([s for s in story if s[1] == "U110@9"])             # equal later target never a role

    def test_ex_c_choch_reseed_stale_deepest_and_waiting(self):
        run = run_structure(EX_C)
        self.assertEqual(event_story(run), [(10, "ESTABLISHMENT", BULLISH, "U110@5"), (30, "CHOCH", "BEARISH", "L104@7")])
        story = role_story(run)
        for expected in [
            ("PROTECTION", "L104@7", 10, "BROKEN", 30),
            ("TARGET", "U130@13", 15, "ENDED", 30),
            ("BULL_ANCHOR", "L102@17", 30, None, None),
            ("BULL_CANDIDATE_TARGET", "U120@21", 30, "RETIRED", 38),
            ("BEAR_ANCHOR", "U130@13", 30, None, None),
            ("BEAR_CANDIDATE_TARGET", "L102@17", 30, None, None),
            ("BULL_CANDIDATE_TARGET", "U123@38", 40, None, None),
        ]:
            self.assertIn(expected, story)
        self.assertFalse([s for s in story if s[1] == "U116@25"])            # ignored candidate never resurrected
        dirs = run.direction_transitions
        self.assertEqual(list(zip(dirs["previous_state"], dirs["new_state"])),
                         [("UNDEFINED", BULLISH), (BULLISH, "UNDEFINED")])

    def test_t1_same_close_target_after_failed_establishment(self):
        rows = list(EX_C[:41])
        rows[36] = (111, 125, 110, 115)      # wick to 125 (close <= 120): swing high confirmed by observation 38
        run = run_structure(rows)
        story = role_story(run)
        self.assertIn(("BULL_CANDIDATE_TARGET", "U120@21", 30, "RETIRED", 38), story)
        self.assertIn(("BULL_CANDIDATE_TARGET", "U125@36", 38, None, None), story)   # assigned at e(N)
        self.assertEqual([e for e in event_story(run) if e[0] == 38], [])               # failure not revised
        bars = pd.DataFrame({"bar_start": [slot_end(38)]}, index=pd.DatetimeIndex([slot_end(39)]))
        roles = materialize_state_to_bars(m7(run.role_transitions), role_namespace(structure_definition()),
                                          run.role_entities, bars)
        new = run.roles[run.roles["swing_id"].isin(
            run.swings.loc[run.swings["price"] == 20125, "swing_id"])]["role_id"].iloc[0]
        self.assertIn(new, set(roles["entity_id"]))                             # usable from N+1 (bar_start = e(N))
        at_n = pd.DataFrame({"bar_start": [slot_end(37)]}, index=pd.DatetimeIndex([slot_end(38)]))
        self.assertNotIn(new, set(materialize_state_to_bars(m7(run.role_transitions),
                                                            role_namespace(structure_definition()),
                                                            run.role_entities, at_n)["entity_id"]))


class SimultaneousAdmissionTests(unittest.TestCase):
    """H.3: an outside bar confirms a Swing High and a Swing Low in one batch (L0: shared last plateau bar)."""

    ROWS = [(105, 106, 104, 105), (105, 108, 103, 104), (104, 105, 101, 102), (102, 107, 102, 106),
            (106, 110, 105, 107), (107, 108, 104, 105), (105, 106, 103, 104), (104, 112, 100, 106),
            (106, 109, 103, 105), (105, 108, 102, 104)]

    def test_outside_bar_replaces_both_anchors_in_one_batch(self):
        run = run_structure(self.ROWS)
        self.assertEqual(role_story(run), [
            ("BULL_ANCHOR", "L101@2", 4, "SUPERSEDED", 9),
            ("BEAR_ANCHOR", "U110@4", 6, "SUPERSEDED", 9),
            ("BULL_CANDIDATE_TARGET", "U110@4", 6, "ENDED", 9),
            ("BEAR_ANCHOR", "U112@7", 9, None, None),
            ("BULL_ANCHOR", "L100@7", 9, None, None),
        ])
        self.assertTrue(run.events.empty)   # admissions and rescans never classify or change direction


class InvalidationTests(unittest.TestCase):
    def test_anchor_invalidation_restarts_from_empty_k2(self):
        rows = EX_A[:5] + [(103, 104, 99, 99.5), (99.5, 100, 97, 98), (98, 99, 96, 97), (97, 98, 95.5, 96),
                           (96, 99, 96, 98.5), (98.5, 100, 97, 99.5), (99.5, 101, 99, 100.5)]
        run = run_structure(rows)
        self.assertEqual(role_story(run), [
            ("BULL_ANCHOR", "L100@2", 4, "BROKEN", 5),          # c@5 = 99.5 < 100 (D14 invalidation)
            ("BEAR_ANCHOR", "U108@4", 6, None, None),
            ("BEAR_CANDIDATE_TARGET", "L95.5@8", 10, None, None),
            ("BULL_ANCHOR", "L95.5@8", 10, None, None),          # reseeded only by the next admission
        ])
        self.assertTrue(run.events.empty)


class StateContractTests(unittest.TestCase):
    def test_m7a_validity_and_bar_materialization(self):
        run = run_structure(EX_C)
        definition = structure_definition()
        validate_transitions(m7(run.direction_transitions), direction_namespace(definition), run.direction_entities)
        validate_transitions(m7(run.role_transitions), role_namespace(definition), run.role_entities)
        bars = run.observations[["bar_start"]]
        states = materialize_state_to_bars(m7(run.direction_transitions), direction_namespace(definition),
                                           run.direction_entities, bars)
        by_end = dict(zip(pd.to_datetime(states["bar_end"], utc=True), states["state"]))
        self.assertEqual(by_end[slot_end(10)], "UNDEFINED")   # the establishing bar does not see itself
        self.assertEqual(by_end[slot_end(11)], BULLISH)
        self.assertEqual(by_end[slot_end(30)], BULLISH)
        self.assertEqual(by_end[slot_end(31)], "UNDEFINED")

    def test_no_entity_created_and_exited_at_one_instant(self):
        run = run_structure(EX_C)
        created = dict(zip(run.roles["role_id"], run.roles["assigned_at"]))
        for row in run.role_transitions.itertuples(index=False):
            self.assertLess(created[row.entity_id], row.transition_at)

    def test_role_uniqueness_per_kind(self):
        run = run_structure(EX_C)
        exits = dict(zip(run.role_transitions["entity_id"], run.role_transitions["transition_at"]))
        for instant in sorted(set(run.roles["assigned_at"])):
            active = run.roles[(run.roles["assigned_at"] <= instant)
                               & run.roles["role_id"].map(lambda r: r not in exits or exits[r] > instant)]
            self.assertFalse(active["role_kind"].duplicated().any(), instant)

    def test_ids_are_deterministic_and_prefixed(self):
        a, b = run_structure(EX_A), run_structure(EX_A)
        for name in TABLES:
            pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name))
        self.assertTrue(a.episodes["episode_id"].str.startswith("se_").all())
        self.assertTrue(a.roles["role_id"].str.startswith("sr_").all())
        self.assertTrue(a.events["event_id"].str.startswith("sx_").all())
        self.assertTrue(a.run_id.startswith("mr_"))

    def test_iteration_order_independence(self):
        bars = ohlc_bars(EX_C)
        cutoff = slot_end(len(EX_C) - 1)
        base = build_market_structure(bars, "5m", SPEC, structure_definition(), instrument_id="MNQ",
                                      replay_cutoff=cutoff)
        shuffled = run_market_structure(base.observations.sample(frac=1, random_state=3),
                                        base.swings.sample(frac=1, random_state=5), "5m", SPEC,
                                        structure_definition(), instrument_id="MNQ", replay_cutoff=cutoff)
        for name in TABLES:
            pd.testing.assert_frame_equal(getattr(base, name).drop(columns="run_id"),
                                          getattr(shuffled, name).drop(columns="run_id"))

    def test_revision_creates_a_new_run_with_explicit_fact_diffs(self):
        rows = list(EX_A)
        revised = list(EX_A)
        revised[12] = (114, 118.25, 113, 116)   # same T1 span, revised high
        a, b = run_structure(rows), run_structure(revised)
        self.assertNotEqual(a.run_id, b.run_id)
        ta = a.roles[a.roles["role_kind"] == "TARGET"].iloc[0]
        tb = b.roles[b.roles["role_kind"] == "TARGET"].iloc[0]
        self.assertEqual(ta["swing_id"], tb["swing_id"])            # swing identity excludes price
        self.assertNotEqual(ta["fact_hash"], tb["fact_hash"])


class ResetAdapterTests(unittest.TestCase):
    """§G.2, §G.2a, CB-1 / CB-2 (MS-T11, MS-T21 … MS-T25)."""

    ROWS = EX_A[:14]

    def test_gap_same_contract(self):
        rows = self.ROWS + [None, None] + EX_A[16:20]
        run = run_structure(rows)
        ep = run.episodes
        self.assertEqual(list(ep["opening_cause"]), [DATA_START, DATA_GAP_REESTABLISHMENT])
        reset = run.events[run.events["kind"] == RESET].iloc[0]
        self.assertEqual(pd.Timestamp(reset["event_at"]), slot_end(14))
        self.assertEqual(reset["reset_reason"], DATA_GAP)
        self.assertEqual(ep.iloc[1]["opening_ref"], reset["reset_ref"])
        self.assertFalse(ep.iloc[1]["opening_contract_changed"])
        self.assertIsNone(ep.iloc[1]["opening_contract_change_ref"])

    def test_cb1_gap_then_contract_change(self):
        rows = self.ROWS + [None, None] + EX_A[16:20]
        contracts = [A] * 16 + [B] * 4
        run = run_structure(rows, contracts=contracts)
        ep = run.episodes
        reset = run.events[run.events["kind"] == RESET].iloc[0]
        self.assertEqual(reset["reset_reason"], DATA_GAP)                    # primary reason; no contract flag
        self.assertEqual(reset["reset_ref"], continuity_ref("5m", A, slot_end(14)))
        new = ep.iloc[1]
        self.assertEqual(new["opening_cause"], DATA_GAP_REESTABLISHMENT)
        self.assertEqual((new["contract"], new["previous_contract"]), (B, A))
        self.assertTrue(new["opening_contract_changed"])
        self.assertEqual(new["opening_ref"], reset["reset_ref"])
        self.assertEqual(new["opening_contract_change_ref"],
                         bar_span_ref(instrument_id="MNQ", contract=B, timeframe="5m", first_bar_end=slot_end(16),
                                      last_bar_end=slot_end(16)))
        self.assertEqual(pd.Timestamp(new["available_at"]), slot_end(16))
        # the reset row is identical before and after the roll evidence exists
        early = run_structure(rows, contracts=contracts, cutoff_k=15)
        self.assertEqual(len(early.episodes), 1)
        pd.testing.assert_frame_equal(early.events.drop(columns="run_id"), run.events[
            run.events["available_at"] <= slot_end(15)].drop(columns="run_id").reset_index(drop=True))

    def test_cb2_pure_contract_change(self):
        rows = list(EX_A[:20])
        contracts = [A] * 12 + [B] * 8
        run = run_structure(rows, contracts=contracts)
        ep = run.episodes
        reset = run.events[run.events["kind"] == RESET].iloc[0]
        self.assertEqual(reset["reset_reason"], CONTRACT_CHANGE)
        self.assertEqual(pd.Timestamp(reset["event_at"]), slot_end(12))
        self.assertEqual(pd.Timestamp(ep.iloc[1]["first_bar_end"]), slot_end(12))
        self.assertEqual(ep.iloc[1]["opening_cause"], CONTRACT_CHANGE_REESTABLISHMENT)
        self.assertEqual(ep.iloc[1]["opening_ref"], reset["reset_ref"])
        self.assertTrue(ep.iloc[1]["opening_contract_changed"])
        # obs 12 closes above the old A target region but is never classified against A state
        self.assertFalse(((run.events["kind"] != RESET) & (run.events["available_at"] == slot_end(12))).any())
        contract_of = dict(zip(run.episodes["episode_id"], run.episodes["contract"]))
        for frame in (run.roles, run.events):
            self.assertTrue((frame["episode_id"].map(contract_of) == frame["contract"]).all())
        role_contract = dict(zip(run.roles["role_id"], run.roles["contract"]))
        self.assertTrue((run.role_transitions["entity_id"].map(role_contract) == run.role_transitions["contract"]).all())
        self.assertTrue((run.direction_transitions["entity_id"].map(contract_of)
                         == run.direction_transitions["contract"]).all())

    def test_trailing_incomplete_observation_resets_without_a_break_row(self):
        rows = list(EX_A[:16])
        run = run_structure(rows, incomplete={15})
        self.assertEqual(len(run.episodes), 1)
        reset = run.events[run.events["kind"] == RESET]
        self.assertEqual(len(reset), 1)
        self.assertEqual(pd.Timestamp(reset.iloc[0]["event_at"]), slot_end(15))
        early = run_structure(rows, incomplete={15}, cutoff_k=14)
        self.assertTrue(early.events[early.events["kind"] == RESET].empty)

    def test_trailing_missing_sessions_after_last_observed_date(self):
        rows = list(EX_A[:16])
        bars = ohlc_bars(rows)
        far = slot_end(400)   # expected observations with no data at all
        run = build_market_structure(bars, "5m", SPEC, structure_definition(), instrument_id="MNQ", replay_cutoff=far)
        reset = run.events[run.events["kind"] == RESET].iloc[0]
        self.assertEqual(pd.Timestamp(reset["event_at"]), slot_end(16))
        self.assertEqual(run.manifest["replay_cutoff"][:10], far.strftime("%Y-%m-%d"))

    def test_replay_cutoffs_inside_a_gap(self):
        rows = self.ROWS + [None, None, None] + EX_A[17:22]
        contracts = [A] * 17 + [B] * 5
        full = run_structure(rows, contracts=contracts)
        reset_full = full.events[full.events["kind"] == RESET].drop(columns="run_id").reset_index(drop=True)
        for k in (13, 14, 15, 16, 17, 18, 21):
            cutoff = slot_end(k)
            run = run_structure(rows, contracts=contracts, cutoff_k=k)
            got, want = restricted(run, cutoff), restricted(full, cutoff)
            for name in TABLES:
                assert_same(got[name], want[name], f"{name}@{k}")
            resets = run.events[run.events["kind"] == RESET]
            self.assertEqual(len(resets), int(k >= 14), k)
            if k >= 14:
                pd.testing.assert_frame_equal(resets.drop(columns="run_id").reset_index(drop=True), reset_full)
            self.assertEqual(len(run.episodes), 1 + int(k >= 17), k)

    def test_prefix_equivalence_grid(self):
        full = run_structure(EX_C)
        for k in range(0, len(EX_C), 3):
            cutoff = slot_end(k)
            run = run_structure(EX_C, cutoff_k=k)
            got, want = restricted(run, cutoff), restricted(full, cutoff)
            for name in TABLES:
                assert_same(got[name], want[name], f"{name}@{k}")

    def test_only_incomplete_observations_give_zero_episodes(self):
        rows = list(EX_A[:6])
        run = run_structure(rows, incomplete=set(range(len(rows))))
        self.assertEqual(len(run.observations), 6)                       # nonempty input
        self.assertFalse(run.observations["is_complete"].any())
        for name in TABLES:
            self.assertTrue(getattr(run, name).empty, name)
        self.assertTrue(run.swings.empty and run.direction_entities.empty and run.role_entities.empty)

    def test_zero_episodes_still_fail_closed_on_continuity_mismatch(self):
        rows = list(EX_A[:6])
        bars = ohlc_bars(rows, incomplete=set(range(len(rows))))

        def with_phantom_break(*args, **kwargs):
            segments, breaks = continuity_segments(*args, **kwargs)
            phantom = pd.DataFrame([{column: None for column in breaks.columns}])
            return segments, pd.concat([breaks, phantom], ignore_index=True)

        with mock.patch.object(structure_module, "continuity_segments", side_effect=with_phantom_break):
            with self.assertRaises(ContinuityError):
                build_market_structure(bars, "5m", SPEC, structure_definition(), instrument_id="MNQ",
                                       replay_cutoff=slot_end(5))

        def with_phantom_segment(*args, **kwargs):
            segments, breaks = continuity_segments(*args, **kwargs)
            return segments + [pd.DataFrame({"bar_end": [slot_end(0)]})], breaks

        with mock.patch.object(structure_module, "continuity_segments", side_effect=with_phantom_segment):
            with self.assertRaises(ContinuityError):
                build_market_structure(bars, "5m", SPEC, structure_definition(), instrument_id="MNQ",
                                       replay_cutoff=slot_end(5))

    def test_cutoff_is_required_and_timezone_aware(self):
        bars = ohlc_bars(EX_A)
        with self.assertRaises(StructureError):
            build_market_structure(bars, "5m", SPEC, structure_definition(), instrument_id="MNQ", replay_cutoff=None)
        with self.assertRaises(StructureError):
            build_market_structure(bars, "5m", SPEC, structure_definition(), instrument_id="MNQ",
                                   replay_cutoff=pd.Timestamp("2026-09-15 10:00"))


class DualEstablishmentSearchTests(unittest.TestCase):
    """MS-T18 supporting evidence (not proof): random walks never produce a DUAL_ESTABLISHMENT anomaly."""

    def test_random_walks(self):
        rng = random.Random(20261005)
        for trial in range(12):
            price, rows = 100.0, []
            for _ in range(140):
                o = price
                c = max(10.0, o + rng.choice([-3, -2, -1, -0.5, 0, 0.5, 1, 2, 3]))
                h = max(o, c) + rng.choice([0, 0.25, 0.5, 1, 2])
                lo = min(o, c) - rng.choice([0, 0.25, 0.5, 1, 2])
                rows.append((o, h, lo, c))
                price = c
            run = run_structure(rows)
            self.assertTrue(run.anomalies.empty, trial)
            definition = structure_definition()
            validate_transitions(m7(run.role_transitions), role_namespace(definition), run.role_entities)


if __name__ == "__main__":
    unittest.main()
