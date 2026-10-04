"""Canonical Swing contract tests (SW-I1; D-135 / D-138). Synthetic rows only; no detection."""

from pathlib import Path
import unittest

import pandas as pd

from src.market_structure.swing import (
    LOWER,
    ORIENTATIONS,
    SWING_COLUMNS,
    SWING_ID_PREFIX,
    SWING_TIMEFRAMES,
    UPPER,
    SwingContractError,
    SwingDefinitionSpec,
    assign_swing_ids,
    bar_span_ref,
    swing_id,
    validate_swing_points,
)

NY = "America/New_York"
T0 = pd.Timestamp("2026-01-05 09:35", tz=NY)
MIN5 = pd.Timedelta(minutes=5)
REF22 = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=2)


def t(i):
    return T0 + i * MIN5


def row(*, source=0, end=None, avail=None, orientation=UPPER, timeframe="5m", price=20000.25, contract="MNQ 03-26",
        instrument="MNQ", spec=REF22, **overrides):
    end = source if end is None else end
    avail = end + spec.right_depth if avail is None else avail
    out = {
        "swing_id": "pending", "orientation": orientation, "timeframe": timeframe, "price": price,
        "source_ref": bar_span_ref(instrument_id=instrument, contract=contract, timeframe=timeframe,
                                   first_bar_end=t(source), last_bar_end=t(end)),
        "source_at": t(source), "source_seq_domain": None, "source_seq": None, "source_end_at": t(end),
        "available_at": t(avail), "available_seq_domain": None, "available_seq": None,
        "instrument_id": instrument, "contract_scope": "SPECIFIC", "contract": contract,
        "left_depth": spec.left_depth, "right_depth": spec.right_depth, "definition_version": spec.definition_version,
    }
    out.update(overrides)
    return out


def swings(*rows):
    return assign_swing_ids(pd.DataFrame(list(rows), columns=list(SWING_COLUMNS)))


def key(**overrides):
    base = dict(definition_version="swing-pivot-v1", instrument_id="MNQ", contract_scope="SPECIFIC", contract="MNQ 03-26",
                timeframe="5m", orientation=UPPER, left_depth=2, right_depth=2,
                source_ref=bar_span_ref(instrument_id="MNQ", contract="MNQ 03-26", timeframe="5m",
                                        first_bar_end=t(0), last_bar_end=t(0)))
    base.update(overrides)
    return base


class DefinitionSpecTests(unittest.TestCase):
    def test_valid_explicit_depths(self):
        spec = SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=5, right_depth=2)
        self.assertEqual((spec.left_depth, spec.right_depth), (5, 2))
        with self.assertRaises(Exception):
            spec.left_depth = 3  # frozen

    def test_no_defaults(self):
        with self.assertRaises(TypeError):
            SwingDefinitionSpec(definition_version="v")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            SwingDefinitionSpec("v", 2, 2)  # type: ignore[misc]  keyword-only

    def test_invalid_depths_and_version(self):
        for bad in (0, -1, True, False, 2.0, "2", None):
            with self.subTest(bad=bad), self.assertRaises(SwingContractError):
                SwingDefinitionSpec(definition_version="v", left_depth=bad, right_depth=2)
            with self.subTest(bad=bad), self.assertRaises(SwingContractError):
                SwingDefinitionSpec(definition_version="v", left_depth=2, right_depth=bad)
        for bad in ("", "  ", " v", None, 1):
            with self.subTest(version=bad), self.assertRaises(SwingContractError):
                SwingDefinitionSpec(definition_version=bad, left_depth=2, right_depth=2)


class BarSpanTests(unittest.TestCase):
    def test_single_bar_exact_string(self):
        self.assertEqual(
            bar_span_ref(instrument_id="MNQ", contract="MNQ 12-26", timeframe="5m",
                         first_bar_end=pd.Timestamp("2026-01-05 09:35", tz=NY), last_bar_end=pd.Timestamp("2026-01-05 09:35", tz=NY)),
            "BAR_SPAN:MNQ|MNQ 12-26|5m|2026-01-05T14:35:00.000000000Z|2026-01-05T14:35:00.000000000Z")

    def test_plateau_exact_string(self):
        self.assertEqual(
            bar_span_ref(instrument_id="MNQ", contract="MNQ 12-26", timeframe="4H",
                         first_bar_end=pd.Timestamp("2026-01-05 14:00", tz=NY), last_bar_end=pd.Timestamp("2026-01-05 22:00", tz=NY)),
            "BAR_SPAN:MNQ|MNQ 12-26|4H|2026-01-05T19:00:00.000000000Z|2026-01-06T03:00:00.000000000Z")

    def test_timezone_representations_canonicalize(self):
        args = dict(instrument_id="MNQ", contract="C", timeframe="1H")
        self.assertEqual(bar_span_ref(**args, first_bar_end=t(0), last_bar_end=t(1)),
                         bar_span_ref(**args, first_bar_end=t(0).tz_convert("UTC"), last_bar_end=t(1).tz_convert("Europe/London")))

    def test_invalid_inputs(self):
        ok = dict(instrument_id="MNQ", contract="C", timeframe="5m", first_bar_end=t(0), last_bar_end=t(1))
        cases = {
            "first after last": dict(first_bar_end=t(2)),
            "timeframe": dict(timeframe="2H"),
            "empty contract": dict(contract=""),
            "untrimmed contract": dict(contract=" C"),
            "null contract": dict(contract=None),
            "pipe contract": dict(contract="A|B"),
            "newline contract": dict(contract="A\nB"),
            "naive time": dict(first_bar_end=pd.Timestamp("2026-01-05 09:35")),
            "lowercase instrument": dict(instrument_id="mnq"),
            "bad instrument": dict(instrument_id="M|Q"),
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(SwingContractError):
                bar_span_ref(**{**ok, **change})

    def test_malformed_refs_rejected_by_identity(self):
        good = key()["source_ref"]
        key_text = good.split(":", 1)[1]
        cases = {
            "wrong kind": "HTF_BAR:" + key_text,
            "four fields": "BAR_SPAN:MNQ|MNQ 03-26|5m|2026-01-05T14:35:00.000000000Z",
            "six fields": good + "|x",
            "non-canonical time": good.replace("14:35:00.000000000Z", "14:35:00Z"),
            "offset time": good.replace("2026-01-05T14:35:00.000000000Z", "2026-01-05T09:35:00.000000000-05:00", 1),
            "not a ref": "BAR_SPAN",
        }
        for name, ref in cases.items():
            with self.subTest(name), self.assertRaises(SwingContractError):
                swing_id(**key(source_ref=ref))


class SwingIdTests(unittest.TestCase):
    def test_deterministic_full_sha256(self):
        sid = swing_id(**key())
        self.assertRegex(sid, r"^sw_[0-9a-f]{64}$")
        self.assertTrue(sid.startswith(SWING_ID_PREFIX))
        self.assertEqual(sid, swing_id(**key()))

    def test_timezone_equivalent_inputs_same_id(self):
        utc_ref = bar_span_ref(instrument_id="MNQ", contract="MNQ 03-26", timeframe="5m",
                               first_bar_end=t(0).tz_convert("UTC"), last_bar_end=t(0).tz_convert("UTC"))
        self.assertEqual(swing_id(**key()), swing_id(**key(source_ref=utc_ref)))

    def test_natural_key_fields_change_id(self):
        base = swing_id(**key())
        def ref(**k):
            args = dict(instrument_id="MNQ", contract="MNQ 03-26", timeframe="5m", first_bar_end=t(0), last_bar_end=t(0))
            args.update(k)
            return bar_span_ref(**args)
        variants = {
            "orientation": key(orientation=LOWER),
            "timeframe": key(timeframe="15m", source_ref=ref(timeframe="15m")),
            "left depth": key(left_depth=3),
            "right depth": key(right_depth=3),
            "plateau extent": key(source_ref=ref(last_bar_end=t(1))),
            "contract": key(contract="MNQ 06-26", source_ref=ref(contract="MNQ 06-26")),
            "definition version": key(definition_version="swing-pivot-v2"),
        }
        ids = {name: swing_id(**args) for name, args in variants.items()}
        for name, value in ids.items():
            with self.subTest(name):
                self.assertNotEqual(value, base)
        self.assertEqual(len(set(ids.values())), len(ids))

    def test_price_and_availability_excluded(self):
        a = swings(row(price=20000.25, avail=2))["swing_id"].iloc[0]
        b = swings(row(price=19999.75, avail=7))["swing_id"].iloc[0]
        self.assertEqual(a, b)

    def test_rejects_malformed_identity_input(self):
        for change in (dict(contract_scope="AGNOSTIC"), dict(orientation="HIGH"), dict(left_depth=0), dict(right_depth=True),
                       dict(definition_version=""), dict(timeframe="2H"), dict(instrument_id="mnq"),
                       dict(contract="MNQ 06-26")):  # contract disagrees with the BAR_SPAN
            with self.subTest(change=change), self.assertRaises(SwingContractError):
                swing_id(**key(**change))


class ValidationTests(unittest.TestCase):
    def ok(self, frame, spec=REF22):
        return validate_swing_points(frame, spec)

    def raises(self, frame, pattern=".", spec=REF22):
        with self.assertRaisesRegex(SwingContractError, pattern):
            validate_swing_points(frame, spec)

    def test_valid_single_bar_and_plateau(self):
        out = self.ok(swings(row(source=0), row(source=3, end=5, price=20001.0)))
        self.assertEqual(list(out.columns), list(SWING_COLUMNS))
        self.assertEqual(str(out["source_at"].dt.tz), "UTC")
        single, plateau = out.iloc[0], out.iloc[1]
        self.assertTrue(single["source_at"] == single["source_end_at"] < single["available_at"])
        self.assertTrue(plateau["source_at"] < plateau["source_end_at"] < plateau["available_at"])
        self.assertTrue(out["source_seq"].isna().all() and out["available_seq_domain"].isna().all())

    def test_both_orientations_and_every_timeframe(self):
        rows = [row(source=i, orientation=o, timeframe=tf) for i, (o, tf) in
                enumerate((o, tf) for o in ORIENTATIONS for tf in SWING_TIMEFRAMES)]
        out = self.ok(swings(*rows))
        self.assertEqual(set(out["orientation"]), set(ORIENTATIONS))
        self.assertEqual(set(out["timeframe"]), set(SWING_TIMEFRAMES))

    def test_vocabulary_and_scope(self):
        good = swings(row())
        self.raises(good.assign(orientation=["HIGH"]), "orientation")
        bad_tf = swings(row())
        bad_tf["timeframe"] = ["2H"]
        self.raises(bad_tf, "timeframe")
        self.raises(good.assign(contract_scope=["AGNOSTIC"]), "contract_scope")
        for contract in (None, "", " MNQ"):
            with self.subTest(contract=contract):
                self.raises(good.assign(contract=[contract]), "contract")

    def test_price(self):
        good = swings(row())
        self.raises(good.assign(price=[20000.1]), "tick grid")
        self.raises(good.assign(price=[float("inf")]), "finite")
        self.raises(good.assign(price=[float("nan")]), "finite")
        self.raises(good.assign(price=["x"]), "finite")

    def test_sequences_must_be_null(self):
        good = swings(row())
        for column, value in (("source_seq_domain", "F"), ("source_seq", 1), ("available_seq_domain", "F"),
                              ("available_seq", 2)):
            with self.subTest(column=column):
                self.raises(good.assign(**{column: [value]}), column)

    def test_timing_invariant(self):
        # source_at > source_end_at
        bad = swings(row(source=2, end=2))
        bad["source_end_at"] = [t(1)]
        self.raises(bad, "source_at must not be after source_end_at")
        self.raises(swings(row(source=0, end=1, avail=1)), "strictly before available_at")
        self.raises(swings(row(source=0, end=3, avail=2)), "strictly before available_at")
        naive = swings(row())
        naive["available_at"] = naive["available_at"].dt.tz_localize(None)
        self.raises(naive, "timezone-aware")

    def test_bar_span_row_consistency(self):
        good = swings(row(source=1, end=2))
        def with_ref(**k):
            args = dict(instrument_id="MNQ", contract="MNQ 03-26", timeframe="5m", first_bar_end=t(1), last_bar_end=t(2))
            args.update(k)
            frame = good.copy()
            frame["source_ref"] = [bar_span_ref(**args)]
            return frame
        self.raises(with_ref(instrument_id="MES"), "instrument")
        self.raises(with_ref(contract="MNQ 06-26"), "contract")
        self.raises(with_ref(timeframe="15m"), "timeframe")
        self.raises(with_ref(first_bar_end=t(0)), "first bar end")
        self.raises(with_ref(last_bar_end=t(3)), "last bar end")
        other_kind = good.copy()
        other_kind["source_ref"] = ["HTF_BAR:MNQ|MNQ 03-26|5m|" + "2026-01-05T14:40:00.000000000Z"]
        self.raises(other_kind, "BAR_SPAN")

    def test_identity_checks(self):
        good = swings(row())
        tampered = good.copy()
        tampered["swing_id"] = ["sw_" + "0" * 64]
        self.raises(tampered, "does not match")
        self.raises(pd.concat([good, good], ignore_index=True), "duplicate swing_id")

    def test_schema_and_definition(self):
        good = swings(row())
        self.raises(good.assign(strength=[1]), "non-canonical columns")
        self.raises(good.drop(columns=["source_end_at"]), "missing required columns")
        self.raises(good, "definition_version", spec=SwingDefinitionSpec(definition_version="other", left_depth=2, right_depth=2))
        self.raises(good, "left_depth", spec=SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=3, right_depth=2))
        self.raises(good, "right_depth", spec=SwingDefinitionSpec(definition_version="swing-pivot-v1", left_depth=2, right_depth=1))
        self.raises(good.assign(left_depth=[True]), "left_depth")
        with self.assertRaisesRegex(SwingContractError, "SwingDefinitionSpec"):
            validate_swing_points(good, {"left_depth": 2})

    def test_shuffle_determinism_and_no_mutation(self):
        rows = [row(source=i, orientation=o, timeframe=tf, price=20000.0 + i)
                for i, (o, tf) in enumerate([(UPPER, "5m"), (LOWER, "5m"), (UPPER, "1H"), (LOWER, "4H"), (UPPER, "1m")])]
        rows.append(row(source=0, orientation=LOWER, timeframe="1m"))  # same times, different orientation/timeframe
        frame = swings(*rows)
        snapshot = frame.copy()
        baseline = self.ok(frame)
        pd.testing.assert_frame_equal(frame, snapshot)  # validator does not mutate
        for seed in range(4):
            pd.testing.assert_frame_equal(self.ok(frame.sample(frac=1, random_state=seed)), baseline)
        keys = list(zip(baseline["available_at"], baseline["source_at"]))
        self.assertEqual(keys, sorted(keys))

    def test_assign_does_not_mutate_or_derive(self):
        frame = pd.DataFrame([row(price=20000.5)], columns=list(SWING_COLUMNS))
        snapshot = frame.copy()
        out = assign_swing_ids(frame)
        pd.testing.assert_frame_equal(frame, snapshot)
        self.assertEqual(out["price"].iloc[0], 20000.5)
        self.assertEqual(out["available_at"].iloc[0], frame["available_at"].iloc[0])
        self.assertTrue(out["swing_id"].iloc[0].startswith("sw_"))

    def test_empty_frame(self):
        out = self.ok(pd.DataFrame(columns=list(SWING_COLUMNS)))
        self.assertTrue(out.empty)
        self.assertEqual(list(out.columns), list(SWING_COLUMNS))


class BoundaryTests(unittest.TestCase):
    def test_no_forbidden_dependencies(self):
        source = Path(__file__).resolve().parents[1].joinpath("src", "market_structure", "swing.py").read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
        forbidden = ("src.liquidity", "src.features", "src.signals", "strategy", "execution", "src.backtesting")
        self.assertFalse([line for line in imports for name in forbidden if name in line])

    def test_no_detector_api(self):
        import src.market_structure.swing as module
        for name in ("detect_swings", "build_swing_points", "find_pivots", "generate_swings"):
            self.assertFalse(hasattr(module, name))

    def test_no_interpretation_columns(self):
        for column in ("liquidity_class", "strength", "parent_swing_id", "child_swing_id", "range_id", "candidate_status",
                       "supersedes", "change_kind", "is_internal", "is_external", "is_target", "is_support",
                       "is_resistance", "major_minor", "consolidation_id"):
            self.assertNotIn(column, SWING_COLUMNS)
        self.assertEqual(len(SWING_COLUMNS), 18)


if __name__ == "__main__":
    unittest.main()
