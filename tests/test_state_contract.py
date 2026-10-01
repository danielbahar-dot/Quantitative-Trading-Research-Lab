"""M7A generic State contract tests.

Synthetic namespaces only: no real lifecycle (liquidity, FVG, swings, ...) is
defined by M7.  ``test.lifecycle`` / ``test.structure`` exist only here.

The explicit causal-key truth table (``CausalKeyTruthTableTests``) is the
authoritative test of the comparator.  The randomized test compares the
vectorized materializer against a brute-force reference that itself uses
``compare_causal``; it validates the vectorization, not the comparator.
"""

import unittest

import numpy as np
import pandas as pd

from src.state.contract import (
    AFTER,
    BEFORE,
    EQUAL,
    INCOMPARABLE,
    AttributeSpec,
    CausalKey,
    SourceRef,
    StateContractError,
    StateNamespaceSpec,
    assign_transition_ids,
    canonical_source_refs,
    canonical_time,
    causal_precedes,
    compare_causal,
    materialize_state_to_bars,
    materialize_state_to_observations,
    prepare_entities,
    state_as_of,
    transition_id,
    validate_transitions,
)

TZ = "America/New_York"
T0 = pd.Timestamp("2026-09-22 10:00", tz=TZ)
MIN = pd.Timedelta(minutes=1)


def m(i):
    return T0 + i * MIN


LIFE = StateNamespaceSpec(
    namespace="test.lifecycle",
    entity_kind="level",
    initial_state="UNTOUCHED",
    allowed_states=("UNTOUCHED", "TOUCHED", "SWEPT", "RETIRED"),
    allowed_transitions=frozenset({
        ("UNTOUCHED", "TOUCHED"), ("UNTOUCHED", "SWEPT"),  # skip edge declared explicitly
        ("TOUCHED", "SWEPT"), ("SWEPT", "RETIRED"), ("TOUCHED", "RETIRED"),
    }),
    terminal_states=("RETIRED",),
    definition_version="test-v1",
    attributes=(AttributeSpec("penetration_ticks", "Int64"),),
)
STRUCTURE = StateNamespaceSpec(
    namespace="test.structure",
    entity_kind="level",
    initial_state="INTACT",
    allowed_states=("INTACT", "BROKEN"),
    allowed_transitions=frozenset({("INTACT", "BROKEN")}),
    terminal_states=("BROKEN",),
    definition_version="test-v1",
)


def entity(entity_id="E1", available_at=None, *, valid_from=None, valid_until=None, scope="AGNOSTIC",
           contract=None, domain=None, seq=None):
    return {"entity_id": entity_id, "available_at": m(0) if available_at is None else available_at,
            "available_seq_domain": domain, "available_seq": seq, "valid_from": valid_from,
            "valid_until": valid_until, "instrument_id": "MNQ", "contract_scope": scope, "contract": contract}


def entities(*rows):
    return pd.DataFrame(list(rows) or [entity()])


def tr(previous, new, at, *, domain=None, seq=None, available_at=None, available_domain=None, available_seq=None,
       entity_id="E1", spec=LIFE, trigger=None, refs=None, scope="AGNOSTIC", contract=None, **extra):
    same = available_at is None
    row = {
        "transition_id": "pending", "namespace": spec.namespace, "entity_id": entity_id,
        "previous_state": previous, "new_state": new,
        "transition_at": at, "transition_seq_domain": domain, "transition_seq": seq,
        "available_at": at if same else available_at,
        "available_seq_domain": domain if same else available_domain,
        "available_seq": seq if same else available_seq,
        "instrument_id": "MNQ", "contract_scope": scope, "contract": contract,
        "definition_version": spec.definition_version,
        "trigger_ref": trigger or SourceRef.for_event("M6_INTERACTION", f"lvl:{entity_id}", at, domain, seq).canonical,
    }
    if refs is not None:
        row["source_refs"] = refs
    row.update(extra)
    return row


def log(*rows):
    return assign_transition_ids(pd.DataFrame(list(rows)))


def raises(test, frame, spec=LIFE, ents=None, pattern=".", **kwargs):
    with test.assertRaisesRegex(StateContractError, pattern):
        validate_transitions(frame, spec, entities() if ents is None else ents, **kwargs)


def states(out):
    return dict(zip(out["entity_id"], out["state"].astype(object).where(out["state"].notna(), None)))


class NamespaceSpecTests(unittest.TestCase):
    def test_spec_fields(self):
        self.assertEqual(LIFE.initial_state, "UNTOUCHED")
        self.assertEqual(LIFE.entity_kind, "level")
        self.assertIn(("UNTOUCHED", "SWEPT"), LIFE.allowed_transitions)
        self.assertEqual(LIFE.terminal_states, ("RETIRED",))
        self.assertEqual(LIFE.definition_version, "test-v1")

    def test_invalid_specs_raise(self):
        base = dict(namespace="test.x", entity_kind="level", initial_state="A", allowed_states=("A", "B"),
                    allowed_transitions=frozenset({("A", "B")}), definition_version="v1")
        cases = {
            "initial not allowed": {"initial_state": "Z"},
            "self edge": {"allowed_transitions": frozenset({("A", "A")})},
            "undeclared edge state": {"allowed_transitions": frozenset({("A", "Z")})},
            "terminal exit": {"terminal_states": ("A",)},
            "unknown terminal": {"terminal_states": ("Z",)},
            "bad namespace": {"namespace": "Test X"},
            "bad entity kind": {"entity_kind": "Level"},
            "lowercase state": {"allowed_states": ("A", "b"), "allowed_transitions": frozenset()},
            "empty version": {"definition_version": " "},
            "duplicate attributes": {"attributes": (AttributeSpec("x", "Int64"), AttributeSpec("x", "Float64"))},
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(StateContractError):
                StateNamespaceSpec(**{**base, **change})
        with self.assertRaises(StateContractError):
            AttributeSpec("x", "object")

    def test_spec_is_frozen(self):
        with self.assertRaises(Exception):
            LIFE.initial_state = "TOUCHED"


class CausalKeyTruthTableTests(unittest.TestCase):
    """Authoritative comparator tests: equality, strict precedence, incomparability."""

    def test_a_exact_equality(self):
        t = m(2)
        self.assertEqual(compare_causal(CausalKey(t), CausalKey(t)), EQUAL)
        self.assertEqual(compare_causal(CausalKey(t, "A", 5), CausalKey(t, "A", 5)), EQUAL)
        self.assertFalse(causal_precedes(CausalKey(t), CausalKey(t)))
        # available key == transition key is a valid availability relationship...
        transitions = log(tr("UNTOUCHED", "SWEPT", t))
        validate_transitions(transitions, LIFE, entities())
        # ...but a generic consumer at that same key may not consume it
        self.assertEqual(states(state_as_of(transitions, LIFE, entities(), t))["E1"], "UNTOUCHED")
        out = materialize_state_to_observations(transitions, LIFE, entities(), pd.DataFrame({"observation_at": [t], "decision_at": [t]}))
        self.assertEqual(out["state"].tolist(), ["UNTOUCHED"])

    def test_b_same_domain_ordered_sequence(self):
        t = m(2)
        self.assertEqual(compare_causal(CausalKey(t, "A", 5), CausalKey(t, "A", 6)), BEFORE)
        self.assertEqual(compare_causal(CausalKey(t, "A", 6), CausalKey(t, "A", 5)), AFTER)
        self.assertTrue(causal_precedes(CausalKey(t, "A", 5), CausalKey(t, "A", 6)))

    def test_c_different_domains_are_incomparable(self):
        t = m(2)
        self.assertEqual(compare_causal(CausalKey(t, "A", 5), CausalKey(t, "B", 100)), INCOMPARABLE)
        self.assertEqual(compare_causal(CausalKey(t, "B", 100), CausalKey(t, "A", 5)), INCOMPARABLE)
        self.assertFalse(causal_precedes(CausalKey(t, "A", 5), CausalKey(t, "B", 100)))
        self.assertFalse(causal_precedes(CausalKey(t, "B", 100), CausalKey(t, "A", 5)))

    def test_d_one_sequence_missing_is_incomparable(self):
        t = m(2)
        self.assertEqual(compare_causal(CausalKey(t, "A", 5), CausalKey(t)), INCOMPARABLE)
        self.assertEqual(compare_causal(CausalKey(t), CausalKey(t, "A", 5)), INCOMPARABLE)

    def test_e_different_timestamps_order_first(self):
        self.assertEqual(compare_causal(CausalKey(m(1), "B", 100), CausalKey(m(2), "A", 1)), BEFORE)
        self.assertEqual(compare_causal(CausalKey(m(2)), CausalKey(m(1), "A", 999)), AFTER)
        self.assertEqual(compare_causal(CausalKey(m(1)), CausalKey(m(2), "A", 0)), BEFORE)

    def test_key_validation(self):
        for bad in (dict(seq_domain="A"), dict(seq=5), dict(seq_domain="", seq=5), dict(seq_domain="A", seq=1.5)):
            with self.subTest(bad), self.assertRaises(StateContractError):
                CausalKey(m(1), **bad)
        with self.assertRaises(StateContractError):
            CausalKey(pd.Timestamp("2026-09-22 10:00"))


class TransitionValidationTests(unittest.TestCase):
    def test_valid_transition_chain_and_skip_edge(self):
        out = validate_transitions(log(tr("UNTOUCHED", "SWEPT", m(2)), tr("SWEPT", "RETIRED", m(5))), LIFE, entities())
        self.assertEqual(out["new_state"].tolist(), ["SWEPT", "RETIRED"])
        self.assertTrue(out["transition_id"].str.fullmatch(r"st_[0-9a-f]{64}").all())

    def test_invalid_state_edge_self_terminal(self):
        cases = {
            "unknown state": (log(tr("UNTOUCHED", "FILLED", m(2))), "not allowed states"),
            "undeclared skip edge": (log(tr("UNTOUCHED", "RETIRED", m(2))), "edge .* is not allowed"),
            "self transition": (log(tr("UNTOUCHED", "UNTOUCHED", m(2))), "self transition"),
            "out of terminal": (log(tr("UNTOUCHED", "TOUCHED", m(1)), tr("TOUCHED", "RETIRED", m(2)),
                                    tr("RETIRED", "SWEPT", m(3))), "out of terminal state"),
        }
        for name, (frame, pattern) in cases.items():
            with self.subTest(name):
                raises(self, frame, pattern=pattern)

    def test_replay_consistency(self):
        # first transition must leave initial_state
        raises(self, log(tr("TOUCHED", "SWEPT", m(2))), pattern="initial_state")
        # every edge is individually allowed, but the history is inconsistent:
        # after UNTOUCHED->TOUCHED the entity is TOUCHED, so UNTOUCHED->SWEPT cannot follow
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2)), tr("UNTOUCHED", "SWEPT", m(3))), pattern="replayed history")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2)), tr("SWEPT", "RETIRED", m(3))), pattern="replayed history")

    def test_trigger_ref_required_and_unique_per_entity(self):
        frame = log(tr("UNTOUCHED", "TOUCHED", m(2)))
        raises(self, frame.drop(columns=["trigger_ref"]), pattern="trigger_ref")
        missing = frame.copy()
        missing["trigger_ref"] = [None]
        raises(self, missing, pattern="trigger_ref is required")
        shared = "TRADE:feed-event-42"
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), trigger=shared), tr("TOUCHED", "SWEPT", m(3), trigger=shared)),
               pattern="same entity_id \\+ namespace \\+ trigger_ref")
        # the same trigger may drive different entities
        two = log(tr("UNTOUCHED", "TOUCHED", m(2), trigger=shared), tr("UNTOUCHED", "SWEPT", m(2), trigger=shared, entity_id="E2"))
        self.assertEqual(len(validate_transitions(two, LIFE, entities(entity(), entity("E2")))), 2)

    def test_deterministic_full_sha256_identity(self):
        a = log(tr("UNTOUCHED", "TOUCHED", m(2)))
        b = log(tr("UNTOUCHED", "TOUCHED", m(2)))
        self.assertEqual(a["transition_id"].iloc[0], b["transition_id"].iloc[0])
        self.assertEqual(len(a["transition_id"].iloc[0]), len("st_") + 64)
        variants = [
            log(tr("UNTOUCHED", "SWEPT", m(2))), log(tr("UNTOUCHED", "TOUCHED", m(3))),
            log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=1)), log(tr("UNTOUCHED", "TOUCHED", m(2), domain="B", seq=1)),
            log(tr("UNTOUCHED", "TOUCHED", m(2), trigger="QUOTE:x")), log(tr("UNTOUCHED", "TOUCHED", m(2), refs=("M5_CONTEXT:c",))),
            log(tr("UNTOUCHED", "TOUCHED", m(2), entity_id="E2")),
        ]
        self.assertEqual(len({v["transition_id"].iloc[0] for v in variants} | {a["transition_id"].iloc[0]}), 8)
        raises(self, pd.concat([a, b], ignore_index=True), pattern="duplicate transition_id")
        tampered = a.copy()
        tampered.loc[0, "transition_id"] = "st_" + "0" * 64
        raises(self, tampered, pattern="does not match its natural key")

    def test_timezone_representation_does_not_change_identity(self):
        et = log(tr("UNTOUCHED", "TOUCHED", m(2), trigger="TRADE:x"))
        utc = log(tr("UNTOUCHED", "TOUCHED", m(2).tz_convert("UTC"), trigger="TRADE:x"))
        tokyo = log(tr("UNTOUCHED", "TOUCHED", m(2).tz_convert("Asia/Tokyo"), trigger="TRADE:x"))
        self.assertEqual({et["transition_id"].iloc[0], utc["transition_id"].iloc[0], tokyo["transition_id"].iloc[0]},
                         {et["transition_id"].iloc[0]})
        self.assertEqual(canonical_time(m(2).tz_convert("Asia/Tokyo")), "2026-09-22T14:02:00.000000000Z")

    def test_source_ref_order_does_not_change_identity_or_output(self):
        forward = log(tr("UNTOUCHED", "TOUCHED", m(2), refs=("M5_CONTEXT:a", "TRADE:b", "QUOTE:c")))
        backward = log(tr("UNTOUCHED", "TOUCHED", m(2), refs=["QUOTE:c", "TRADE:b", "M5_CONTEXT:a", "TRADE:b"]))
        self.assertEqual(forward["transition_id"].iloc[0], backward["transition_id"].iloc[0])
        out_f = validate_transitions(forward, LIFE, entities())
        raw = backward.copy()
        raw.at[0, "source_refs"] = ["QUOTE:c", "TRADE:b", "M5_CONTEXT:a"]  # supplied unordered
        out_b = validate_transitions(raw, LIFE, entities())
        pd.testing.assert_frame_equal(out_f, out_b)
        self.assertEqual(out_f["source_refs"].iloc[0], ("M5_CONTEXT:a", "QUOTE:c", "TRADE:b"))
        no_refs = validate_transitions(log(tr("UNTOUCHED", "TOUCHED", m(2))), LIFE, entities())
        self.assertEqual(no_refs["source_refs"].iloc[0], ())  # supporting provenance is optional

    def test_source_ref_structure(self):
        self.assertEqual(canonical_source_refs([SourceRef("TRADE", "x#2"), "M6_INTERACTION:lvl@t", "TRADE:x#2"]),
                         ("M6_INTERACTION:lvl@t", "TRADE:x#2"))
        for bad in (["lowercase:x"], ["NOKEY"], ["KIND: padded "], [3]):
            with self.subTest(bad), self.assertRaises(StateContractError):
                canonical_source_refs(bad)
        tick = SourceRef.for_event("TICK_INTERACTION", "MNQ", pd.Timestamp("2027-01-05 09:31:07.123456789", tz=TZ), "CME.MDP3", 88123)
        self.assertEqual(tick.canonical, "TICK_INTERACTION:MNQ@2027-01-05T14:31:07.123456789Z#CME.MDP3:88123")
        self.assertEqual(SourceRef.parse(tick.canonical), tick)  # round-trips; the key may contain ':'
        self.assertEqual(SourceRef("FUTURE_KIND_X", "anything").canonical, "FUTURE_KIND_X:anything")  # open kinds
        with self.assertRaises(StateContractError):
            SourceRef.for_event("TRADE", "MNQ", m(1), seq=5)  # sequence without its domain

    def test_typed_attributes(self):
        ok = log(tr("UNTOUCHED", "SWEPT", m(2), attr_penetration_ticks=3))
        ok["attr_penetration_ticks"] = ok["attr_penetration_ticks"].astype("Int64")
        validate_transitions(ok, LIFE, entities())
        raises(self, log(tr("UNTOUCHED", "SWEPT", m(2), attr_penetration_ticks="three")), pattern="must have dtype Int64")
        raises(self, log(tr("UNTOUCHED", "SWEPT", m(2), attr_sweep_price=1.0)), pattern="undeclared columns")
        raises(self, log(tr("UNTOUCHED", "SWEPT", m(2), metadata={"a": 1})), pattern="undeclared columns")  # no dict payload
        required = StateNamespaceSpec(**{**LIFE.__dict__, "attributes": (AttributeSpec("penetration_ticks", "Int64", required=True),)})
        raises(self, log(tr("UNTOUCHED", "SWEPT", m(2))), spec=required, pattern="required attribute")

    def test_schema_negative_cases(self):
        good = log(tr("UNTOUCHED", "TOUCHED", m(2)))
        naive = good.copy()
        naive["transition_at"] = naive["transition_at"].dt.tz_localize(None)
        raises(self, naive, pattern="timezone-aware")
        raises(self, good.drop(columns=["available_seq_domain"]), pattern="missing required columns")
        bad_seq = log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=1))
        bad_seq["transition_seq"] = [1.5]
        raises(self, bad_seq, pattern="integers")
        half = good.copy()
        half["transition_seq"] = pd.array([7], dtype="Int64")
        raises(self, half, pattern="both null or both present")
        raises(self, log(tr("INTACT", "BROKEN", m(2), spec=STRUCTURE)), pattern="namespace")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), entity_id="UNKNOWN")), pattern="unknown entity")


class TimingCausalityTests(unittest.TestCase):
    def test_available_key_must_not_precede_or_be_incomparable(self):
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), available_at=m(1))), pattern="precedes")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=101, available_at=m(2), available_domain="A", available_seq=100)),
               pattern="precedes")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=101, available_at=m(2))), pattern="incomparable")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=101, available_at=m(2), available_domain="B", available_seq=900)),
               pattern="incomparable")
        later = validate_transitions(log(tr("UNTOUCHED", "TOUCHED", m(2), available_at=m(4))), LIFE, entities())
        self.assertEqual(later["available_at"].iloc[0], m(4))

    def test_one_transition_per_causal_event_for_one_entity_and_namespace(self):
        no_order = "without causal precedence"
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2)), tr("TOUCHED", "SWEPT", m(2), trigger="TRADE:other")), pattern=no_order)
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=100), tr("TOUCHED", "SWEPT", m(2))), pattern=no_order)
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=100), tr("TOUCHED", "SWEPT", m(2), domain="B", seq=200)),
               pattern=no_order)
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=100),
                         tr("TOUCHED", "SWEPT", m(2), domain="A", seq=100, trigger="TRADE:other")), pattern=no_order)
        # bar policy: one OHLC bar that touches and sweeps records only UNTOUCHED -> SWEPT
        self.assertEqual(len(validate_transitions(log(tr("UNTOUCHED", "SWEPT", m(2))), LIFE, entities())), 1)

    def test_ordered_same_timestamp_events_allowed_with_reliable_sequence(self):
        out = validate_transitions(log(tr("TOUCHED", "SWEPT", m(2), domain="A", seq=101),
                                       tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=100)), LIFE, entities())
        self.assertEqual(out["new_state"].tolist(), ["TOUCHED", "SWEPT"])
        self.assertEqual(out["transition_seq"].tolist(), [100, 101])

    def test_simultaneous_events_are_not_globally_rejected(self):
        # two entities transition on the same unsequenced timestamp
        two_entities = log(tr("UNTOUCHED", "SWEPT", m(2)), tr("UNTOUCHED", "TOUCHED", m(2), entity_id="E2"))
        self.assertEqual(len(validate_transitions(two_entities, LIFE, entities(entity(), entity("E2")))), 2)
        # two namespaces transition on the same source event
        trigger = "M6_INTERACTION:lvl:E1@2026-09-22T14:02:00.000000000Z"
        life = validate_transitions(log(tr("UNTOUCHED", "SWEPT", m(2), trigger=trigger)), LIFE, entities())
        structure = validate_transitions(log(tr("INTACT", "BROKEN", m(2), trigger=trigger, spec=STRUCTURE)), STRUCTURE, entities())
        self.assertNotEqual(life["transition_id"].iloc[0], structure["transition_id"].iloc[0])

    def test_previous_state_must_be_available_to_the_next_source_event(self):
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), available_at=m(5)), tr("TOUCHED", "SWEPT", m(3))),
               pattern="cannot consume the previous state")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), available_at=m(3)), tr("TOUCHED", "SWEPT", m(3))),
               pattern="cannot consume the previous state")  # available exactly at the next event: not BEFORE

    def test_shuffled_input_gives_identical_canonical_output(self):
        ents = entities(entity(), entity("E2"), entity("E3"))
        life_rows = [tr("UNTOUCHED", "TOUCHED", m(2)), tr("TOUCHED", "SWEPT", m(4)), tr("UNTOUCHED", "SWEPT", m(2), entity_id="E2"),
                     tr("UNTOUCHED", "TOUCHED", m(3), domain="A", seq=7, entity_id="E3"),
                     tr("TOUCHED", "RETIRED", m(3), domain="A", seq=9, entity_id="E3", refs=("QUOTE:q", "M5_CONTEXT:c"))]
        struct_rows = [tr("INTACT", "BROKEN", m(2), spec=STRUCTURE), tr("INTACT", "BROKEN", m(5), spec=STRUCTURE, entity_id="E2")]
        obs = pd.DataFrame({"observation_at": [m(i) for i in range(8)], "decision_at": [m(i) for i in range(8)]})
        baseline = None
        rng = np.random.default_rng(11)
        for _ in range(6):
            life = log(*life_rows).sample(frac=1, random_state=int(rng.integers(0, 10_000))).reset_index(drop=True)
            struct = log(*struct_rows).sample(frac=1, random_state=int(rng.integers(0, 10_000))).reset_index(drop=True)
            shuffled_ents = ents.sample(frac=1, random_state=int(rng.integers(0, 10_000))).reset_index(drop=True)
            result = (
                validate_transitions(life, LIFE, shuffled_ents),
                validate_transitions(struct, STRUCTURE, shuffled_ents),
                materialize_state_to_observations(life, LIFE, shuffled_ents, obs),
                materialize_state_to_observations(struct, STRUCTURE, shuffled_ents, obs.iloc[::-1]),
            )
            if baseline is None:
                baseline = result
                continue
            for got, expected in zip(result, baseline):
                pd.testing.assert_frame_equal(got, expected)


class EntityApplicabilityTests(unittest.TestCase):
    def test_entity_contract_scope(self):
        prepared = prepare_entities(entities(entity(scope="SPECIFIC", contract="MNQ 12-26"), entity("E2")))
        self.assertEqual(list(prepared.index), ["E1", "E2"])
        bad = {
            "specific without contract": entity(scope="SPECIFIC"),
            "agnostic with contract": entity(contract="MNQ 12-26"),
            "unknown scope": entity(scope="ANY"),
            "until before from": entity(valid_from=m(5), valid_until=m(4)),
            "until before available": entity(available_at=m(5), valid_until=m(4)),
            "naive": entity(available_at=pd.Timestamp("2026-09-22 10:00")),
            "seq without domain": entity(seq=5),
        }
        for name, row in bad.items():
            with self.subTest(name), self.assertRaises(StateContractError):
                prepare_entities(entities(row))
        with self.assertRaises(StateContractError):
            prepare_entities(entities(entity(), entity()))

    def test_transition_identity_matches_entity_no_bridging(self):
        ents = entities(entity(scope="SPECIFIC", contract="MNQ 12-26"))
        validate_transitions(log(tr("UNTOUCHED", "TOUCHED", m(2), scope="SPECIFIC", contract="MNQ 12-26")), LIFE, ents)
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2), scope="SPECIFIC", contract="MNQ 03-27")), ents=ents, pattern="no contract bridging")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(2))), ents=ents, pattern="contract_scope differs")
        other_instrument = log(tr("UNTOUCHED", "TOUCHED", m(2)))
        other_instrument["instrument_id"] = "ES"
        raises(self, assign_transition_ids(other_instrument), pattern="instrument_id differs")

    def test_sequenced_entity_availability(self):
        t = m(2)
        ents = entities(entity(available_at=t, domain="A", seq=5))
        # a transition from the very event that made the entity known is rejected; a later one is accepted
        raises(self, log(tr("UNTOUCHED", "TOUCHED", t, domain="A", seq=5)), ents=ents, pattern="not causally known")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", t, domain="B", seq=6)), ents=ents, pattern="not causally known")
        transitions = log(tr("UNTOUCHED", "TOUCHED", t, domain="A", seq=7))
        validate_transitions(transitions, LIFE, ents)
        # initial_state does not bypass entity availability
        self.assertEqual(states(state_as_of(transitions, LIFE, ents, t, as_of_seq_domain="A", as_of_seq=5))["E1"], None)
        self.assertEqual(states(state_as_of(transitions, LIFE, ents, t, as_of_seq_domain="A", as_of_seq=6))["E1"], "UNTOUCHED")
        self.assertEqual(states(state_as_of(transitions, LIFE, ents, t, as_of_seq_domain="A", as_of_seq=8))["E1"], "TOUCHED")
        self.assertEqual(states(state_as_of(transitions, LIFE, ents, t))["E1"], None)  # unsequenced query: incomparable
        obs = pd.DataFrame({"observation_at": [t] * 3, "decision_at": [t] * 3,
                            "observation_seq_domain": ["A"] * 3, "observation_seq": [5, 6, 8],
                            "decision_seq_domain": ["A"] * 3, "decision_seq": [5, 6, 8]})
        out = materialize_state_to_observations(transitions, LIFE, ents, obs)
        self.assertEqual(out["observation_seq"].tolist(), [6, 8])
        self.assertEqual(out["state"].tolist(), ["UNTOUCHED", "TOUCHED"])

    def test_retained_universal_applicability_checks(self):
        # true for any trigger observation: known strictly before the event, and never before valid_from
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(0))), pattern="not causally known")
        raises(self, log(tr("UNTOUCHED", "TOUCHED", m(1))), ents=entities(entity(valid_from=m(2))), pattern="valid_from")

    def test_validation_assumes_no_observation_duration(self):
        import inspect

        self.assertEqual(list(inspect.signature(validate_transitions).parameters), ["transitions", "spec", "entities"])
        ents = entities(entity(valid_from=m(1), valid_until=m(5)))
        # No upper bound on transition_at and no tick/1m/5m distinction: an event key at or after valid_until
        # may be the end of a bar whose start was eligible (e.g. a 5m bar 10:04-10:09, or an unaligned bar).
        for at in (m(5), m(5) + pd.Timedelta(seconds=30), m(9)):
            with self.subTest(at=at):
                validate_transitions(log(tr("UNTOUCHED", "TOUCHED", at)), LIFE, ents)
        # identical records validate identically whatever the (unrecorded) trigger geometry; eligibility is upstream
        tick_like = log(tr("UNTOUCHED", "TOUCHED", m(4), domain="FEED", seq=1))
        bar_like = log(tr("UNTOUCHED", "TOUCHED", m(4)))
        self.assertEqual(len(validate_transitions(tick_like, LIFE, ents)), 1)
        self.assertEqual(len(validate_transitions(bar_like, LIFE, ents)), 1)


class StateAsOfTests(unittest.TestCase):
    def setUp(self):
        self.log = log(tr("UNTOUCHED", "TOUCHED", m(2)), tr("TOUCHED", "SWEPT", m(4), available_at=m(6)),
                       tr("SWEPT", "RETIRED", m(8)))
        self.ents = entities(entity(available_at=m(0), valid_from=m(1), valid_until=m(20)), entity("E2", available_at=m(3)))

    def state(self, at, **kwargs):
        return states(state_as_of(self.log, LIFE, self.ents, at, **kwargs))

    def test_strict_queries(self):
        self.assertEqual(self.state(m(0)), {"E1": None, "E2": None})            # entity available exactly here: not yet
        self.assertEqual(self.state(m(1)), {"E1": "UNTOUCHED", "E2": None})     # initial_state, no synthetic transition
        self.assertEqual(self.state(m(2))["E1"], "UNTOUCHED")                   # transition available at m(2): strict
        self.assertEqual(self.state(m(3)), {"E1": "TOUCHED", "E2": None})
        self.assertEqual(self.state(m(4)), {"E1": "TOUCHED", "E2": "UNTOUCHED"})  # entities independent
        self.assertEqual(self.state(m(5))["E1"], "TOUCHED")                     # between transition_at and available_at
        self.assertEqual(self.state(m(6))["E1"], "TOUCHED")
        self.assertEqual(self.state(m(7))["E1"], "SWEPT")
        self.assertEqual(self.state(m(9))["E1"], "RETIRED")                     # terminal persists
        self.assertEqual(self.state(m(20))["E1"], None)                         # at valid_until: not applicable

    def test_same_timestamp_sequence_ordering(self):
        transitions = log(tr("UNTOUCHED", "TOUCHED", m(2), domain="A", seq=100), tr("TOUCHED", "SWEPT", m(2), domain="A", seq=101))
        ents = entities(entity())
        query = lambda **kw: states(state_as_of(transitions, LIFE, ents, m(2), **kw))["E1"]  # noqa: E731
        self.assertEqual(query(as_of_seq_domain="A", as_of_seq=100), "UNTOUCHED")
        self.assertEqual(query(as_of_seq_domain="A", as_of_seq=101), "TOUCHED")
        self.assertEqual(query(as_of_seq_domain="A", as_of_seq=102), "SWEPT")
        self.assertEqual(query(as_of_seq_domain="B", as_of_seq=999), "UNTOUCHED")  # other domain: incomparable
        self.assertEqual(query(), "UNTOUCHED")                                     # unsequenced: incomparable

    def test_two_namespaces_independent(self):
        structure = log(tr("INTACT", "BROKEN", m(4), spec=STRUCTURE))
        self.assertEqual(states(state_as_of(structure, STRUCTURE, self.ents, m(5)))["E1"], "BROKEN")
        self.assertEqual(self.state(m(5))["E1"], "TOUCHED")

    def test_output_shape(self):
        out = state_as_of(self.log, LIFE, self.ents, m(9))
        self.assertEqual(list(out.columns), ["entity_id", "namespace", "applicable", "state", "transition_id"])
        self.assertTrue(out.loc[out["entity_id"] == "E2", "transition_id"].isna().all())


class ObservationMaterializationTests(unittest.TestCase):
    def test_tick_like_sequence(self):
        t = m(2)
        transitions = log(tr("UNTOUCHED", "SWEPT", t, domain="A", seq=100))
        obs = pd.DataFrame({
            "observation_at": [t, t, t, t, m(3)],
            "observation_seq_domain": ["A", "A", "A", "B", None],
            "observation_seq": pd.array([99, 100, 101, 500, pd.NA], dtype="Int64"),
        })
        obs["decision_at"], obs["decision_seq_domain"], obs["decision_seq"] = obs["observation_at"], obs["observation_seq_domain"], obs["observation_seq"]
        out = materialize_state_to_observations(transitions, LIFE, entities(), obs)
        got = dict(zip(zip(out["observation_seq_domain"].fillna("-"), out["observation_seq"].astype("Float64").fillna(-1)), out["state"]))
        self.assertEqual(got[("A", 99)], "UNTOUCHED")
        self.assertEqual(got[("A", 100)], "UNTOUCHED")  # seq 100 created the transition: cannot consume it
        self.assertEqual(got[("A", 101)], "SWEPT")      # seq 101 sees it
        self.assertEqual(got[("B", 500)], "UNTOUCHED")  # other domain: no order inferred
        self.assertEqual(got[("-", -1)], "SWEPT")       # later timestamp

    def test_unsequenced_same_timestamp_is_ambiguous(self):
        t = m(2)
        for transitions in (log(tr("UNTOUCHED", "SWEPT", t)), log(tr("UNTOUCHED", "SWEPT", t, domain="A", seq=100))):
            out = materialize_state_to_observations(transitions, LIFE, entities(), pd.DataFrame({"observation_at": [t], "decision_at": [t]}))
            self.assertEqual(out["state"].tolist(), ["UNTOUCHED"])  # no ordering assumed

    def test_no_state_before_applicability_and_no_future_leakage(self):
        ents = entities(entity(available_at=m(1), valid_from=m(2), valid_until=m(6)))
        transitions = log(tr("UNTOUCHED", "TOUCHED", m(4)))
        times = [m(i) for i in range(8)]
        out = materialize_state_to_observations(transitions, LIFE, ents, pd.DataFrame({"observation_at": times, "decision_at": times}))
        self.assertEqual(out["observation_at"].tolist(), [m(i) for i in (2, 3, 4, 5)])
        self.assertEqual(out["state"].tolist(), ["UNTOUCHED", "UNTOUCHED", "UNTOUCHED", "TOUCHED"])
        self.assertEqual(str(out["observation_at"].dt.tz), TZ)

    def test_invalid_observations_raise(self):
        transitions = log(tr("UNTOUCHED", "TOUCHED", m(2)))
        bad = {
            "decision after observation": pd.DataFrame({"observation_at": [m(1)], "decision_at": [m(2)]}),
            "duplicate keys": pd.DataFrame({"observation_at": [m(1), m(1)], "decision_at": [m(1), m(1)]}),
            "seq without domain": pd.DataFrame({"observation_at": [m(1)], "decision_at": [m(1)], "decision_seq": [3]}),
        }
        for name, obs in bad.items():
            with self.subTest(name), self.assertRaises(StateContractError):
                materialize_state_to_observations(transitions, LIFE, entities(), obs)


class RandomizedReferenceTests(unittest.TestCase):
    """Vectorized materialization equals a brute-force replay (validates vectorization only)."""

    def build(self, rng, sequenced):
        ents, rows = [], []
        for e in range(4):
            entity_id = f"E{e}"
            start = int(rng.integers(0, 10))
            lag = int(rng.integers(0, 3))
            ents.append(entity(entity_id, m(start), valid_from=m(start + lag), valid_until=m(start + int(rng.integers(20, 50)))))
            state, minute, seq = "UNTOUCHED", start + lag + 1, 0
            for new in ("TOUCHED", "SWEPT", "RETIRED"):
                if rng.random() < 0.25:
                    break
                same_minute = sequenced and rng.random() < 0.5
                minute = minute if same_minute else minute + int(rng.integers(1, 6))
                seq = seq + 1 if sequenced else None
                delay = 0 if same_minute else int(rng.integers(0, 3))
                rows.append(tr(state, new, m(minute), domain="A" if sequenced else None, seq=seq, entity_id=entity_id,
                               available_at=m(minute + delay) if delay else None,
                               available_domain="A" if sequenced and delay else None, available_seq=seq if delay else None))
                minute += delay
                state = new
        return entities(*ents), (log(*rows) if rows else None)

    @staticmethod
    def reference(transitions, ents, observations):
        def visible(at, domain, seq, d_at, d_domain, d_seq):
            norm = lambda v: None if v is None or pd.isna(v) else v  # noqa: E731
            return causal_precedes(CausalKey(at, norm(domain), norm(seq)), CausalKey(d_at, norm(d_domain), norm(d_seq)))
        rows = []
        prepared = prepare_entities(ents).reset_index(drop=True)
        for obs in observations.itertuples(index=False):
            for e in prepared.itertuples(index=False):
                if not visible(e.available_at, e.available_seq_domain, e.available_seq, obs.decision_at, obs.decision_seq_domain, obs.decision_seq):
                    continue
                if (not pd.isna(e.valid_from) and obs.decision_at < e.valid_from) or (not pd.isna(e.valid_until) and obs.decision_at >= e.valid_until):
                    continue
                state = LIFE.initial_state
                chain = transitions[transitions["entity_id"] == e.entity_id]
                chain = chain.assign(_s=chain["transition_seq"].astype("Float64").fillna(-1)).sort_values(["transition_at", "_s"])
                for t in chain.itertuples(index=False):
                    if visible(t.available_at, t.available_seq_domain, t.available_seq, obs.decision_at, obs.decision_seq_domain, obs.decision_seq):
                        state = t.new_state
                rows.append((obs.observation_at, obs.observation_seq if not pd.isna(obs.observation_seq) else -1, e.entity_id, state))
        return sorted(rows, key=lambda r: (r[0], r[1], r[2]))

    def test_matches_brute_force(self):
        rng = np.random.default_rng(3)
        for trial in range(25):
            sequenced = trial % 2 == 0
            ents, transitions = self.build(rng, sequenced)
            if transitions is None:
                continue
            minutes = sorted(set(int(v) for v in rng.integers(0, 60, 30)))
            if sequenced:
                obs = pd.DataFrame({"observation_at": [m(i) for i in minutes for _ in range(3)],
                                    "observation_seq": [s for _ in minutes for s in (0, 2, 4)]})
                obs["observation_seq_domain"] = "A"
            else:
                obs = pd.DataFrame({"observation_at": [m(i) for i in minutes], "observation_seq": [None] * len(minutes),
                                    "observation_seq_domain": [None] * len(minutes)})
            obs["decision_at"], obs["decision_seq_domain"], obs["decision_seq"] = obs["observation_at"], obs["observation_seq_domain"], obs["observation_seq"]
            got = materialize_state_to_observations(transitions, LIFE, ents, obs)
            got_rows = sorted(zip(got["observation_at"], got["observation_seq"].astype("Float64").fillna(-1), got["entity_id"], got["state"]),
                              key=lambda r: (r[0], r[1], r[2]))
            prepared_obs = obs.assign(observation_seq=obs["observation_seq"].astype("Int64"), decision_seq=obs["decision_seq"].astype("Int64"))
            self.assertEqual(got_rows, self.reference(transitions, ents, prepared_obs), f"trial {trial}")


class BarWrapperTests(unittest.TestCase):
    def bars(self, n=8, step=MIN):
        return pd.DataFrame({"close": np.arange(n, dtype=float)}, index=pd.DatetimeIndex([T0 + i * step for i in range(n)]))

    def test_confirming_bar_cannot_consume_next_bar_can(self):
        transitions = log(tr("UNTOUCHED", "SWEPT", m(3)))  # confirmed by the bar ending m(3)
        out = materialize_state_to_bars(transitions, LIFE, entities(), self.bars(), bar_interval=MIN)
        got = dict(zip(out["bar_end"], out["state"]))
        self.assertEqual((got[m(3)], got[m(4)]), ("UNTOUCHED", "SWEPT"))
        self.assertEqual(list(out.columns), ["bar_end", "bar_start", "entity_id", "namespace", "state", "transition_id"])

    def test_no_default_timeframe_and_explicit_bar_start(self):
        transitions = log(tr("UNTOUCHED", "SWEPT", m(3)))
        with self.assertRaisesRegex(StateContractError, "explicit bar_interval"):
            materialize_state_to_bars(transitions, LIFE, entities(), self.bars())
        bars = self.bars()
        bars["bar_start"] = bars.index - MIN
        from_column = materialize_state_to_bars(transitions, LIFE, entities(), bars)
        from_interval = materialize_state_to_bars(transitions, LIFE, entities(), self.bars(), bar_interval=MIN)
        pd.testing.assert_frame_equal(from_column, from_interval)
        both = materialize_state_to_bars(transitions, LIFE, entities(), bars, bar_interval=MIN)  # consistent: accepted
        pd.testing.assert_frame_equal(both, from_interval)
        with self.assertRaisesRegex(StateContractError, "disagree"):
            materialize_state_to_bars(transitions, LIFE, entities(), bars, bar_interval=pd.Timedelta(minutes=5))

    def test_other_timeframes(self):
        for step in (pd.Timedelta(minutes=5), pd.Timedelta(minutes=15), pd.Timedelta(hours=1)):
            with self.subTest(step=step):
                confirm = T0 + 3 * step
                ents = entities(entity(available_at=T0))
                transitions = log(tr("UNTOUCHED", "SWEPT", confirm))
                out = materialize_state_to_bars(transitions, LIFE, ents, self.bars(step=step), bar_interval=step)
                got = dict(zip(out["bar_end"], out["state"]))
                self.assertEqual((got[confirm], got[confirm + step]), ("UNTOUCHED", "SWEPT"))
                self.assertEqual(out["bar_end"].min(), T0 + step)  # bar_start >= entity available_at

    def test_bar_rule_matches_m5_m6_including_mid_bar_availability(self):
        ents = entities(entity(available_at=T0 + pd.Timedelta(seconds=30)))
        transitions = log(tr("UNTOUCHED", "TOUCHED", m(3), available_at=m(3) + pd.Timedelta(seconds=10)))
        out = materialize_state_to_bars(transitions, LIFE, ents, self.bars(), bar_interval=MIN)
        self.assertEqual(out["bar_end"].min(), m(2))
        got = dict(zip(out["bar_end"], out["state"]))
        self.assertEqual((got[m(4)], got[m(5)]), ("UNTOUCHED", "TOUCHED"))

    def test_valid_from_and_valid_until_respected(self):
        ents = entities(entity(available_at=m(0), valid_from=m(2), valid_until=m(5)))
        transitions = log(tr("UNTOUCHED", "TOUCHED", m(4)))
        out = materialize_state_to_bars(transitions, LIFE, ents, self.bars(), bar_interval=MIN)
        self.assertEqual(out["bar_end"].tolist(), [m(3), m(4), m(5)])  # bar_start in [m(2), m(5))
        self.assertEqual(out["state"].tolist(), ["UNTOUCHED", "UNTOUCHED", "TOUCHED"])

    def test_final_eligible_bar_at_valid_until(self):
        for step in (MIN, pd.Timedelta(minutes=5)):
            with self.subTest(step=step):
                until = T0 + 5 * step
                ents = entities(entity(available_at=T0, valid_until=until))
                transitions = log(tr("UNTOUCHED", "TOUCHED", until))  # caused by the final eligible bar, ending at valid_until
                validate_transitions(transitions, LIFE, ents)
                out = materialize_state_to_bars(transitions, LIFE, ents, self.bars(step=step), bar_interval=step)
                self.assertEqual(out["bar_end"].max(), until)        # bar_start = until - step < valid_until: eligible
                self.assertEqual(out["state"].iloc[-1], "UNTOUCHED")  # the final bar cannot consume its own transition
                self.assertEqual(len(out), 5)

    def test_bar_wrapper_validates_index(self):
        with self.assertRaises(StateContractError):
            materialize_state_to_bars(log(tr("UNTOUCHED", "TOUCHED", m(2))), LIFE, entities(),
                                      pd.DataFrame(index=pd.DatetimeIndex([pd.Timestamp("2026-09-22 10:00")])), bar_interval=MIN)


if __name__ == "__main__":
    unittest.main()
