"""M2 generic instrument metadata tests. Synthetic configs only; no market data."""

from dataclasses import FrozenInstanceError
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.data.instruments import (
    DEFAULT_INSTRUMENT_CONFIG_DIR,
    InstrumentConfigError,
    InstrumentError,
    InstrumentNotFoundError,
    InstrumentSpec,
    is_tick_aligned,
    load_instrument,
    normalize_instrument_id,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FREEZE_METADATA = (
    PROJECT_ROOT / "experiments" / "projects" / "mnq_orb_v0_1" / "freeze"
    / "dev_candidate_freeze" / "orb_gate6c_DEV_freeze_metadata.json"
)

VALID_TEXT = """{
  "instrument_id": "TST",
  "name": "Synthetic test future",
  "asset_class": "futures",
  "exchange": "TEST",
  "currency": "USD",
  "tick_size_points": %(tick)s,
  "tick_value_usd": %(tick_value)s,
  "point_value_usd": %(point)s
}"""


class TempConfigMixin:
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._folder.name)

    def tearDown(self):
        self._folder.cleanup()

    def write(self, text: str, name: str = "tst.json") -> Path:
        path = self.config_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_numbers(self, tick="0.25", point="2.0", tick_value="0.5") -> Path:
        return self.write(VALID_TEXT % {"tick": tick, "point": point, "tick_value": tick_value})


class MnqConfigTests(unittest.TestCase):
    def test_mnq_loads_from_authoritative_config(self):
        spec = load_instrument("MNQ")
        self.assertIsInstance(spec, InstrumentSpec)
        self.assertEqual(spec.instrument_id, "MNQ")
        self.assertEqual((spec.asset_class, spec.exchange, spec.currency), ("futures", "CME", "USD"))
        self.assertEqual(Path(spec.source_path), DEFAULT_INSTRUMENT_CONFIG_DIR / "mnq.json")

    def test_economics_are_exact_decimals(self):
        spec = load_instrument("MNQ")
        for value in (spec.tick_size, spec.point_value, spec.tick_value):
            self.assertIs(type(value), Decimal)
        self.assertEqual(spec.tick_size, Decimal("0.25"))
        self.assertEqual(spec.point_value, Decimal("2.0"))
        self.assertEqual(spec.tick_value, Decimal("0.5"))
        self.assertEqual(spec.tick_size * spec.point_value, spec.tick_value)

    def test_spec_is_immutable(self):
        spec = load_instrument("MNQ")
        with self.assertRaises(FrozenInstanceError):
            spec.tick_size = Decimal("0.5")

    def test_instrument_id_normalization(self):
        self.assertEqual(normalize_instrument_id("  mnq "), "MNQ")
        self.assertEqual(load_instrument("mnq"), load_instrument("MNQ"))
        for bad in ("", "  ", "../mnq", "mnq/x", "MN Q", None, 5):
            with self.subTest(repr(bad)):
                with self.assertRaises(InstrumentError):
                    normalize_instrument_id(bad)

    def test_unknown_instrument_is_not_substituted(self):
        with self.assertRaises(InstrumentNotFoundError) as context:
            load_instrument("ZZZ")
        self.assertIn("ZZZ", str(context.exception))
        self.assertIsInstance(context.exception, LookupError)


class LegacyCompatibilityTests(unittest.TestCase):
    def test_legacy_tick_size_constant_matches_config(self):
        # candidate_entries imports only stdlib/pandas and defines constants;
        # importing it has no side effects.
        from src.backtesting.candidate_entries import TICK_SIZE

        self.assertEqual(Decimal(str(TICK_SIZE)), load_instrument("MNQ").tick_size)

    def test_mnq_config_matches_frozen_orb_provenance_hash(self):
        # The Gate 6C freeze records this file's SHA-256; the config is
        # authoritative but must not drift from frozen ORB provenance.
        recorded = json.loads(FREEZE_METADATA.read_text(encoding="utf-8"))
        hashes = {Path(key.replace("\\", "/")).as_posix(): value
                  for key, value in recorded["source_artifact_sha256"].items()}
        actual = hashlib.sha256((DEFAULT_INSTRUMENT_CONFIG_DIR / "mnq.json").read_bytes()).hexdigest()
        self.assertEqual(actual, hashes["config/instruments/mnq.json"])


class InvalidConfigTests(TempConfigMixin, unittest.TestCase):
    def test_synthetic_valid_config_loads(self):
        self.write_numbers()
        spec = load_instrument("tst", config_dir=self.config_dir)
        self.assertEqual(spec.tick_value, Decimal("0.5"))

    def test_exact_decimal_relationship(self):
        # 0.1 x 3 == 0.3 exactly in Decimal, but not in binary floating point.
        self.assertNotEqual(0.1 * 3, 0.3)
        self.write_numbers(tick="0.1", point="3", tick_value="0.3")
        spec = load_instrument("TST", config_dir=self.config_dir)
        self.assertEqual(spec.tick_size * spec.point_value, spec.tick_value)

    def test_missing_file_and_directory(self):
        with self.assertRaises(InstrumentNotFoundError):
            load_instrument("TST", config_dir=self.config_dir)
        with self.assertRaises(InstrumentConfigError):
            load_instrument("TST", config_dir=self.config_dir / "does_not_exist")

    def test_malformed_json(self):
        for text in ('{"instrument_id": "TST",', "[1, 2, 3]", '{"tick_size_points": NaN}'):
            with self.subTest(text):
                self.write(text)
                with self.assertRaises(InstrumentConfigError):
                    load_instrument("TST", config_dir=self.config_dir)

    def test_missing_required_fields(self):
        base = json.loads(VALID_TEXT % {"tick": "0.25", "point": "2.0", "tick_value": "0.5"})
        for field in list(base):
            with self.subTest(field):
                config = {key: value for key, value in base.items() if key != field}
                self.write(json.dumps(config))
                with self.assertRaises(InstrumentConfigError) as context:
                    load_instrument("TST", config_dir=self.config_dir)
                self.assertIn(field, str(context.exception))

    def test_non_positive_and_non_numeric_values(self):
        cases = {
            "zero tick": {"tick": "0", "tick_value": "0"},
            "negative tick": {"tick": "-0.25", "tick_value": "-0.5"},
            "zero point value": {"point": "0", "tick_value": "0"},
            "negative point value": {"point": "-2.0", "tick_value": "-0.5"},
            "zero tick value": {"tick_value": "0"},
            "negative tick value": {"tick_value": "-0.5"},
            "string tick": {"tick": '"0.25"'},
            "boolean point value": {"point": "true"},
            "null tick value": {"tick_value": "null"},
            "infinite tick": {"tick": "Infinity"},
        }
        for name, numbers in cases.items():
            with self.subTest(name):
                self.write_numbers(**numbers)
                with self.assertRaises(InstrumentConfigError):
                    load_instrument("TST", config_dir=self.config_dir)

    def test_inconsistent_tick_economics(self):
        self.write_numbers(tick_value="0.51")
        with self.assertRaises(InstrumentConfigError) as context:
            load_instrument("TST", config_dir=self.config_dir)
        self.assertIn("tick_value_usd", str(context.exception))

    def test_identity_mismatch_and_currency(self):
        self.write((VALID_TEXT % {"tick": "0.25", "point": "2.0", "tick_value": "0.5"})
                   .replace('"TST"', '"MNQ"'))
        with self.assertRaises(InstrumentConfigError):
            load_instrument("TST", config_dir=self.config_dir)
        self.write((VALID_TEXT % {"tick": "0.25", "point": "2.0", "tick_value": "0.5"})
                   .replace('"USD"', '"EUR"'))
        with self.assertRaises(InstrumentConfigError):
            load_instrument("TST", config_dir=self.config_dir)


class TickAlignmentTests(unittest.TestCase):
    TICK = Decimal("0.25")

    def test_aligned_prices(self):
        for price in (Decimal("20053.75"), "20053.50", 20053, 20053.25, Decimal("0"), Decimal("-1.25")):
            with self.subTest(repr(price)):
                self.assertTrue(is_tick_aligned(price, self.TICK))

    def test_unaligned_prices(self):
        for price in (Decimal("20053.10"), "20053.01", 20053.3, Decimal("0.2500001")):
            with self.subTest(repr(price)):
                self.assertFalse(is_tick_aligned(price, self.TICK))

    def test_decimal_precision_edges(self):
        self.assertFalse(is_tick_aligned(0.1 + 0.2, Decimal("0.1")))  # 0.30000000000000004
        self.assertTrue(is_tick_aligned(Decimal("0.3"), Decimal("0.1")))
        self.assertTrue(is_tick_aligned(Decimal("20053.7500"), self.TICK))  # trailing zeros

    def test_invalid_inputs(self):
        for price in (True, None, "abc", float("nan"), Decimal("Infinity")):
            with self.subTest(repr(price)):
                with self.assertRaises(InstrumentError):
                    is_tick_aligned(price, self.TICK)
        for tick in (0.25, Decimal("0"), Decimal("-0.25"), Decimal("NaN")):
            with self.subTest(repr(tick)):
                with self.assertRaises(InstrumentError):
                    is_tick_aligned(Decimal("1"), tick)


if __name__ == "__main__":
    unittest.main()
