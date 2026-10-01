"""M7B generic Signal contract tests (synthetic definitions only).

No real signal family (liquidity, FVG, MSS, swing, ORB ...) is defined;
``test.*`` definitions exist only here.
"""

import unittest

import numpy as np
import pandas as pd

from src.signals.contract import (
    DIRECTIONS,
    FORBIDDEN_EXECUTION_FIELDS,
    SignalContractError,
    SignalDefinitionSpec,
    assign_signal_ids,
    signal_id,
    validate_signals,
)
from src.state.contract import (
    AttributeSpec,
    SourceRef,
    StateContractError,
    StateNamespaceSpec,
    assign_transition_ids,
    validate_transitions,
)

TZ = "America/New_York"
T0 = pd.Timestamp("2026-09-22 10:00", tz=TZ)
MIN = pd.Timedelta(minutes=1)


def m(i):
    return T0 + i * MIN


SWEEP = SignalDefinitionSpec(
    signal_type="test.sweep",
    subject_kind="level",
    definition_version="v1",
    allowed_directions=("BULLISH", "BEARISH"),
    attributes=(AttributeSpec("extreme_price", "Float64"), AttributeSpec("side", "string")),
)
TOUCH = SignalDefinitionSpec(signal_type="test.touch", subject_kind="level", definition_version="v1")
TRIAD = SignalDefinitionSpec(signal_type="test.shift", subject_kind="structure", definition_version="v1",
                             allowed_directions=("BULLISH", "BEARISH", "NEUTRAL"))
STRICT_ATTR = SignalDefinitionSpec(signal_type="test.gap", subject_kind="gap", definition_version="v1",
                                   attributes=(AttributeSpec("gap_ticks", "Int64", required=True),))


def sig(definition=SWEEP, *, subject="lvl:pdl:2026-09-22", at=None, domain=None, seq=None, available_at=None,
        available_domain=None, available_seq=None, direction="BULLISH", trigger=None, refs=None,
        scope="SPECIFIC", contract="MNQ 12-26", instrument="MNQ", **extra):
    at = m(2) if at is None else at
    same = available_at is None
    row = {
        "signal_id": "pending", "signal_type": definition.signal_type, "definition_version": definition.definition_version,
        "subject_id": subject, "event_at": at, "event_seq_domain": domain, "event_seq": seq,
        "available_at": at if same else available_at,
        "available_seq_domain": domain if same else available_domain,
        "available_seq": seq if same else available_seq,
        "instrument_id": instrument, "contract_scope": scope, "contract": contract,
        "direction": direction if definition.allowed_directions else None,
        "trigger_ref": trigger or SourceRef.for_event("M6_INTERACTION", subject, at, domain, seq).canonical,
    }
    if refs is not None:
        row["source_refs"] = refs
    row.update(extra)
    return row


def frame(*rows):
    return assign_signal_ids(pd.DataFrame(list(rows)))


def one_id(**kwargs):
    return frame(sig(**kwargs))["signal_id"].iloc[0]


class Raises:
    def raises(self, signals, definition=SWEEP, pattern="."):
        with self.assertRaisesRegex(SignalContractError, pattern):
            validate_signals(signals, definition)


class DefinitionSpecTests(unittest.TestCase):
    def test_valid_definition(self):
        self.assertEqual(SWEEP.subject_kind, "level")
        self.assertEqual(TOUCH.allowed_directions, ())
        self.assertEqual(DIRECTIONS, ("BULLISH", "BEARISH", "NEUTRAL"))

    def test_invalid_definitions(self):
        base = dict(signal_type="test.x", subject_kind="level", definition_version="v1")
        cases = {
            "bad signal_type": {"signal_type": "Test X"},
            "bad subject_kind": {"subject_kind": "Level Kind"},
            "empty version": {"definition_version": ""},
            "duplicate direction": {"allowed_directions": ("BULLISH", "BULLISH")},
            "invalid direction": {"allowed_directions": ("LONG",)},
            "forbidden attribute": {"attributes": (AttributeSpec("entry_price", "Float64"),)},
            "duplicate attribute": {"attributes": (AttributeSpec("x", "Int64"), AttributeSpec("x", "Int64"))},
            "non-spec attribute": {"attributes": ("attr_x",)},
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(SignalContractError):
                SignalDefinitionSpec(**{**base, **change})
        with self.assertRaises(TypeError):
            SignalDefinitionSpec(signal_type="test.x", definition_version="v1")  # subject_kind is required
        for field in FORBIDDEN_EXECUTION_FIELDS:
            with self.subTest(field), self.assertRaises(SignalContractError):
                SignalDefinitionSpec(**base, attributes=(AttributeSpec(field, "Float64"),))


class DirectionTests(Raises, unittest.TestCase):
    def test_declared_directions_accepted(self):
        for direction in ("BULLISH", "BEARISH", "NEUTRAL"):
            with self.subTest(direction):
                validate_signals(frame(sig(TRIAD, subject="s1", direction=direction)), TRIAD)

    def test_undirected_requires_null(self):
        validate_signals(frame(sig(TOUCH)), TOUCH)
        row = sig(TOUCH)
        row["direction"] = "BULLISH"
        self.raises(frame(row), TOUCH, "undirected")

    def test_directed_rejects_null_and_undeclared_and_action_words(self):
        for direction in (None, "NEUTRAL", "LONG", "SHORT", "BUY", "SELL"):
            with self.subTest(direction):
                self.raises(frame(sig(direction=direction)), SWEEP, "direction must be one of")


class SchemaTests(Raises, unittest.TestCase):
    def test_valid_row(self):
        out = validate_signals(frame(sig()), SWEEP)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out["event_at"].dt.tz), "UTC")
        self.assertEqual(out["source_refs"].iloc[0], ())

    def test_subject_id_is_free_form_but_well_formed(self):
        validate_signals(frame(sig(subject="MNQ/CME:previous_day:low@2026-09-22#v2")), SWEEP)
        for bad in ("", " padded", "two\nlines"):
            with self.subTest(bad):
                self.raises(frame(sig(subject=bad, trigger="M6_INTERACTION:x")), SWEEP, "subject_id")

    def test_missing_unexpected_and_naive(self):
        good = frame(sig())
        self.raises(good.drop(columns=["trigger_ref"]), pattern="missing required columns")
        self.raises(good.drop(columns=["available_seq_domain"]), pattern="missing required columns")
        self.raises(good.assign(reason_code="X"), pattern="undeclared columns")
        self.raises(good.assign(metadata=[{"a": 1}]), pattern="undeclared columns")
        naive = good.copy()
        naive["event_at"] = naive["event_at"].dt.tz_localize(None)
        self.raises(naive, pattern="timezone-aware")
        self.raises(good.assign(signal_type="test.other"), pattern="signal_type other")

    def test_sequence_domain_pairing(self):
        seq_only = sig()
        seq_only.update(event_seq=5, available_seq=5)
        domain_only = sig()
        domain_only.update(event_seq_domain="FEED", available_seq_domain="FEED")
        for row in (seq_only, domain_only):
            with self.subTest(row["event_seq"]):
                self.raises(pd.DataFrame([row]), pattern="both null or both present")


class CausalityTests(Raises, unittest.TestCase):
    def test_event_before_or_equal_availability(self):
        validate_signals(frame(sig(available_at=m(5))), SWEEP)  # BEFORE
        validate_signals(frame(sig()), SWEEP)                   # EQUAL
        self.raises(frame(sig(available_at=m(1))), pattern="precedes")  # AFTER

    def test_same_timestamp_sequences(self):
        ok = sig(domain="FEED", seq=5, available_at=m(2), available_domain="FEED", available_seq=6)
        validate_signals(frame(ok), SWEEP)
        reversed_ = sig(domain="FEED", seq=6, available_at=m(2), available_domain="FEED", available_seq=5)
        self.raises(frame(reversed_), pattern="precedes")
        cross = sig(domain="A", seq=5, available_at=m(2), available_domain="B", available_seq=900)
        self.raises(frame(cross), pattern="incomparable")
        partial = sig(domain="A", seq=5, available_at=m(2))  # available unsequenced at the same timestamp
        self.raises(frame(partial), pattern="incomparable")


class ProvenanceTests(Raises, unittest.TestCase):
    def test_trigger_required_and_source_refs_optional(self):
        missing = frame(sig())
        missing["trigger_ref"] = [None]
        self.raises(missing, pattern="trigger_ref is required")
        out = validate_signals(frame(sig(refs=("TRADE:b", "M5_CONTEXT:a", "TRADE:b"))), SWEEP)
        self.assertEqual(out["source_refs"].iloc[0], ("M5_CONTEXT:a", "TRADE:b"))

    def test_ref_format_and_open_kinds(self):
        validate_signals(frame(sig(trigger="FUTURE_ORDERBOOK_KIND:feed@x#7", refs=("ANOTHER_NEW_KIND:k",))), SWEEP)
        bad = sig()
        bad["trigger_ref"] = "lowercase:x"
        with self.assertRaises(SignalContractError):
            frame(bad)
        unparsed = sig(refs=("M5_CONTEXT:a",))
        unparsed_frame = frame(unparsed)
        unparsed_frame.at[0, "source_refs"] = ("NOKEY",)
        self.raises(unparsed_frame, pattern="KIND:key")

    def test_trigger_must_not_repeat_in_source_refs(self):
        trigger = "M6_INTERACTION:lvl@x"
        self.raises(frame(sig(trigger=trigger, refs=(trigger, "M5_CONTEXT:a"))), pattern="must not also appear")


class IdentityTests(unittest.TestCase):
    def test_full_sha256(self):
        self.assertRegex(one_id(), r"^sg_[0-9a-f]{64}$")

    def test_invariances(self):
        base = one_id(trigger="TRADE:t")
        self.assertEqual(one_id(trigger="TRADE:t", at=m(2).tz_convert("UTC")), base)
        self.assertEqual(one_id(trigger="TRADE:t", at=m(2).tz_convert("Asia/Tokyo")), base)
        self.assertEqual(one_id(refs=("TRADE:b", "M5_CONTEXT:a")), one_id(refs=["M5_CONTEXT:a", "TRADE:b"]))
        self.assertEqual(one_id(available_at=m(9)), one_id())                          # availability is not identity
        self.assertEqual(one_id(attr_extreme_price=101.25), one_id(attr_extreme_price=99.0))  # attributes are not identity

    def test_natural_key_fields_change_id(self):
        base = one_id()
        variants = {
            "sequence domain": one_id(domain="A", seq=1, trigger="TRADE:t"),
            "other domain": one_id(domain="B", seq=1, trigger="TRADE:t"),
            "instrument": one_id(instrument="ES"),
            "contract": one_id(contract="MNQ 03-27"),
            "agnostic": one_id(scope="AGNOSTIC", contract=None),
            "trigger": one_id(trigger="TRADE:other"),
            "supporting provenance": one_id(refs=("M5_CONTEXT:a",)),
            "direction": one_id(direction="BEARISH"),
            "subject": one_id(subject="lvl:pdh:2026-09-22"),
            "event time": one_id(at=m(3)),
        }
        self.assertNotIn(base, variants.values())
        self.assertNotEqual(variants["sequence domain"], variants["other domain"])
        self.assertEqual(len(set(variants.values())), len(variants))

    def test_validation_recomputes_id(self):
        tampered = frame(sig())
        tampered.loc[0, "signal_id"] = "sg_" + "0" * 64
        with self.assertRaisesRegex(SignalContractError, "does not match"):
            validate_signals(tampered, SWEEP)


class UniquenessTests(Raises, unittest.TestCase):
    def test_duplicates(self):
        row = sig()
        self.raises(pd.concat([frame(row), frame(row)], ignore_index=True), pattern="duplicate signal_id")
        self.raises(frame(sig(refs=("M5_CONTEXT:a",)), sig(refs=("M5_CONTEXT:b",))), pattern="same semantic event")
        self.raises(frame(sig(trigger="TRADE:one"), sig(trigger="TRADE:two")), pattern="same semantic event")
        # availability is not identity: a re-published copy is the same id, rejected as a duplicate
        self.raises(frame(sig(), sig(available_at=m(5))), pattern="duplicate signal_id")

    def test_one_trigger_many_signals(self):
        trigger = "M6_INTERACTION:lvl@2026-09-22T14:02:00.000000000Z"
        # different subjects from the same trigger
        out = validate_signals(frame(sig(trigger=trigger), sig(trigger=trigger, subject="lvl:asia_low:2026-09-22")), SWEEP)
        self.assertEqual(len(out), 2)
        # a different signal type from the same trigger
        validate_signals(frame(sig(TOUCH, trigger=trigger)), TOUCH)
        # opposite directions are distinct when the definition allows both
        both = validate_signals(frame(sig(direction="BULLISH"), sig(direction="BEARISH")), SWEEP)
        self.assertEqual(both["direction"].tolist(), ["BEARISH", "BULLISH"])


class ContractTests(Raises, unittest.TestCase):
    def test_scope_rules(self):
        validate_signals(frame(sig()), SWEEP)
        validate_signals(frame(sig(scope="AGNOSTIC", contract=None)), SWEEP)
        self.raises(frame(sig(contract=None)), pattern="SPECIFIC scope requires")
        self.raises(frame(sig(scope="AGNOSTIC")), pattern="AGNOSTIC scope must have a null")
        self.raises(frame(sig(scope="ANY")), pattern="contract_scope must be one of")


class AttributeAndExecutionBoundaryTests(Raises, unittest.TestCase):
    def test_typed_attributes(self):
        ok = frame(sig(attr_extreme_price=101.25, attr_side="above"))  # objective metadata, incl. a 'side'
        validate_signals(ok, SWEEP)
        self.raises(frame(sig(attr_extreme_price="high")), pattern="must have dtype Float64")
        self.raises(frame(sig(attr_unknown=1)), pattern="undeclared columns")
        missing = sig(STRICT_ATTR, subject="gap:1")
        self.raises(frame(missing), STRICT_ATTR, "required attribute")
        present = frame(sig(STRICT_ATTR, subject="gap:1", attr_gap_ticks=4))
        present["attr_gap_ticks"] = present["attr_gap_ticks"].astype("Int64")
        validate_signals(present, STRICT_ATTR)

    def test_every_forbidden_field_rejected_directly_and_as_attribute(self):
        good = frame(sig())
        for field in FORBIDDEN_EXECUTION_FIELDS:
            for column in (field, f"attr_{field}"):
                with self.subTest(column):
                    self.raises(good.assign(**{column: 1.0}), pattern="execution fields")

    def test_no_fuzzy_matching(self):
        # names merely containing a forbidden word are ordinary (undeclared) columns, not execution fields
        with self.assertRaisesRegex(SignalContractError, "undeclared columns"):
            validate_signals(frame(sig()).assign(target_level_kind="x"), SWEEP)


class DeterminismTests(unittest.TestCase):
    def test_shuffled_rows_identical_output(self):
        rows = [
            sig(subject="b"), sig(subject="a"), sig(subject="a", direction="BEARISH"),
            sig(subject="c", at=m(1)), sig(subject="d", domain="A", seq=3, trigger="TRADE:x"),
            sig(subject="e", domain="B", seq=1, trigger="TRADE:y"), sig(subject="f", available_at=m(7)),
        ]
        baseline = validate_signals(frame(*rows), SWEEP)
        rng = np.random.default_rng(5)
        for _ in range(6):
            shuffled = frame(*rows).sample(frac=1, random_state=int(rng.integers(0, 10_000))).reset_index(drop=True)
            pd.testing.assert_frame_equal(validate_signals(shuffled, SWEEP), baseline)

    def test_incomparable_rows_order_is_deterministic_only(self):
        rows = [sig(subject="z", domain="B", seq=1, trigger="TRADE:z"), sig(subject="y", domain="A", seq=9, trigger="TRADE:y")]
        a = validate_signals(frame(*rows), SWEEP)
        b = validate_signals(frame(*reversed(rows)), SWEEP)
        pd.testing.assert_frame_equal(a, b)
        # domain A sorts before B for reproducibility; the two events remain causally INCOMPARABLE
        self.assertEqual(a["event_seq_domain"].tolist(), ["A", "B"])


class StateInteropTests(unittest.TestCase):
    def test_signal_may_derive_from_same_event_transition(self):
        namespace = StateNamespaceSpec(namespace="test.lifecycle", entity_kind="level", initial_state="UNTOUCHED",
                                       allowed_states=("UNTOUCHED", "SWEPT"),
                                       allowed_transitions=frozenset({("UNTOUCHED", "SWEPT")}), definition_version="v1")
        entities = pd.DataFrame([{"entity_id": "lvl:pdl:2026-09-22", "available_at": m(0), "valid_from": None,
                                  "valid_until": None, "instrument_id": "MNQ", "contract_scope": "SPECIFIC",
                                  "contract": "MNQ 12-26"}])
        m6 = SourceRef.for_event("M6_INTERACTION", "lvl:pdl:2026-09-22", m(2)).canonical
        transition = assign_transition_ids(pd.DataFrame([{
            "transition_id": "x", "namespace": "test.lifecycle", "entity_id": "lvl:pdl:2026-09-22",
            "previous_state": "UNTOUCHED", "new_state": "SWEPT", "transition_at": m(2), "transition_seq_domain": None,
            "transition_seq": None, "available_at": m(2), "available_seq_domain": None, "available_seq": None,
            "instrument_id": "MNQ", "contract_scope": "SPECIFIC", "contract": "MNQ 12-26",
            "definition_version": "v1", "trigger_ref": m6,
        }]))
        validate_transitions(transition, namespace, entities)
        trigger = SourceRef("STATE_TRANSITION", transition["transition_id"].iloc[0]).canonical
        out = validate_signals(frame(sig(trigger=trigger, refs=(m6,))), SWEEP)  # same causal key as the transition
        self.assertEqual(out["trigger_ref"].iloc[0], trigger)
        self.assertEqual(out["event_at"].iloc[0], transition["transition_at"].iloc[0])


class ErrorBoundaryTests(unittest.TestCase):
    def test_reused_primitive_errors_are_translated_with_chaining(self):
        self.assertFalse(issubclass(SignalContractError, StateContractError))
        self.assertTrue(issubclass(SignalContractError, ValueError))
        cases = {
            "malformed ref": dict(trigger_ref="not-a-ref"),
            "seq without domain": dict(event_seq=3),
            "naive time": dict(event_at=pd.Timestamp("2026-09-22 10:00")),
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(SignalContractError) as raised:
                signal_id(signal_type="test.sweep", definition_version="v1", instrument_id="MNQ",
                          contract_scope="SPECIFIC", contract="MNQ 12-26", subject_id="s",
                          **{"event_at": m(2), "trigger_ref": "TRADE:t", **change})
            self.assertIsInstance(raised.exception.__cause__, StateContractError)


if __name__ == "__main__":
    unittest.main()
