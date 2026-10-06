"""Independent audit and invariant tests (MS-I3; MARKET_STRUCTURE_SPEC §I). Synthetic only."""

import random
import unittest

import pandas as pd

from ms_fixtures import EX_A, EX_B, EX_C, SPEC, run_structure, slot_end
from src.market_structure.structure import RESET
from src.market_structure.structure_audit import INVARIANT_NAMES, reconcile, reference_structure, structure_invariants

A, B = "MNQ 09-26", "MNQ 12-26"


def random_rows(seed, length=150):
    rng = random.Random(seed)
    price, rows = 100.0, []
    for _ in range(length):
        o = price
        c = max(10.0, o + rng.choice([-3, -2, -1, -0.5, 0, 0.5, 1, 2, 3]))
        rows.append((o, max(o, c) + rng.choice([0, 0.25, 0.5, 1, 2]), min(o, c) - rng.choice([0, 0.25, 0.5, 1, 2]), c))
        price = c
    return rows


def mismatches(run):
    rec = reconcile(run, reference_structure(run, SPEC))
    return int(rec[["engine_only", "reference_only"]].to_numpy().sum()), rec


def violations(run):
    inv = structure_invariants(run, SPEC)
    return inv.set_index("invariant")["violations"]


class ReconciliationTests(unittest.TestCase):
    def test_spec_examples_match_the_independent_reference(self):
        for rows in (EX_A, EX_B, EX_C):
            run = run_structure(rows)
            count, rec = mismatches(run)
            self.assertEqual(count, 0, rec)
            self.assertGreater(rec["engine"].sum(), 0)

    def test_random_walks_match_the_independent_reference(self):
        for seed in range(8):
            run = run_structure(random_rows(seed))
            count, rec = mismatches(run)
            self.assertEqual(count, 0, (seed, rec))

    def test_reconciliation_detects_a_changed_event(self):
        run = run_structure(EX_C)
        run.events.loc[run.events["kind"] == "CHOCH", "direction"] = "BULLISH"
        self.assertGreater(mismatches(run)[0], 0)

    def test_reconciliation_detects_a_changed_exit_state(self):
        run = run_structure(EX_A)
        row = run.role_transitions.index[run.role_transitions["new_state"] == "REPLACED"][0]
        run.role_transitions.loc[row, "new_state"] = "ENDED"
        self.assertGreater(mismatches(run)[0], 0)


class InvariantTests(unittest.TestCase):
    def test_all_invariants_zero_on_examples_gaps_and_rolls(self):
        cases = [
            (EX_A, {}), (EX_B, {}), (EX_C, {}),
            (EX_A[:14] + [None, None] + EX_A[16:20], {}),
            (EX_A[:14] + [None, None] + EX_A[16:20], {"contracts": [A] * 16 + [B] * 4}),
            (list(EX_A[:20]), {"contracts": [A] * 12 + [B] * 8}),
            (list(EX_A[:16]), {"incomplete": {15}}),
            (random_rows(11), {}),
        ]
        for rows, kwargs in cases:
            v = violations(run_structure(rows, **kwargs))
            self.assertEqual(len(v), 17)
            self.assertEqual(int(v.sum()), 0, v[v > 0])

    def test_invariant_names_are_stable(self):
        self.assertEqual(tuple(structure_invariants(run_structure(EX_A), SPEC)["invariant"]), INVARIANT_NAMES)

    def test_zero_episode_run_audits_clean(self):
        run = run_structure(list(EX_A[:6]), incomplete=set(range(6)))
        inv = structure_invariants(run, SPEC)
        self.assertEqual(tuple(inv["invariant"]), INVARIANT_NAMES)
        self.assertEqual(int(inv["violations"].sum()), 0)
        count, rec = mismatches(run)
        self.assertEqual(count, 0, rec)

    def test_zero_episode_run_with_output_is_a_violation(self):
        run = run_structure(list(EX_A[:6]), incomplete=set(range(6)))
        run.events = run_structure(EX_A).events
        self.assertGreater(int(structure_invariants(run, SPEC)["violations"].sum()), 0)

    def test_inv1_anomaly_rows_fail(self):
        run = run_structure(EX_A)
        run.anomalies.loc[0] = [run.episodes["episode_id"].iloc[0], slot_end(5), "DUAL_ESTABLISHMENT", "{}", "5m",
                                "MNQ", "MNQ 12-26", run.run_id]
        self.assertEqual(violations(run)["INV-1 no structure_anomalies rows"], 1)

    def test_inv12_pinned_fact_drift_detected(self):
        run = run_structure(EX_A)
        run.roles.loc[0, "swing_price_ticks"] += 1
        self.assertGreater(violations(run)["INV-12 pinned facts equal input facts"], 0)

    def test_inv13_moved_reset_detected(self):
        run = run_structure(EX_A[:14] + [None, None] + EX_A[16:20])
        run.events.loc[run.events["kind"] == RESET, "event_at"] = slot_end(15)
        self.assertGreater(violations(run)["INV-13 RESET onsets follow the schedule rule and are <= replay_cutoff"], 0)

    def test_inv16_bad_opening_provenance_detected(self):
        run = run_structure(EX_A[:14] + [None, None] + EX_A[16:20], contracts=[A] * 16 + [B] * 4)
        run.episodes.loc[run.episodes["opening_cause"] != "DATA_START", "opening_contract_changed"] = False
        self.assertGreater(violations(run)["INV-16 contract-boundary provenance (CB-1 / CB-2)"], 0)

    def test_inv7_duplicate_active_role_detected(self):
        run = run_structure(EX_A)
        duplicate = run.roles[run.roles["role_kind"] == "PROTECTION"].iloc[[1]].copy()
        duplicate["role_id"] = "sr_" + "1" * 64
        duplicate["assigned_at"] = pd.Timestamp(duplicate["assigned_at"].iloc[0])
        run.roles = pd.concat([run.roles, duplicate], ignore_index=True)
        self.assertGreater(violations(run)["INV-7 active-role uniqueness"], 0)

    def test_inv14_protection_transition_at_bos_without_replacement_detected(self):
        run = run_structure(EX_A)
        bos1 = run.events[run.events["kind"] == "BOS"].sort_values("event_at").iloc[0]["event_at"]
        row = run.role_transitions.index[run.role_transitions["new_state"] == "REPLACED"][0]
        run.role_transitions.loc[row, "transition_at"] = bos1
        run.role_transitions.loc[row, "available_at"] = bos1
        self.assertGreater(violations(run)[
            "INV-14 protection exits only REPLACED/BROKEN/ENDED; untouched by BOS without replacement"], 0)


if __name__ == "__main__":
    unittest.main()
