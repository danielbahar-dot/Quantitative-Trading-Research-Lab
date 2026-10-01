"""M6B ORB level-interaction compatibility tests.

The ORB adapter must reuse the generic M6A engine and reproduce frozen ORB
output exactly.  ``frozen_reference`` below is a verbatim copy of the removed
``src.features.market_context.level_interaction`` kept *only* as a test
oracle.  The frozen-oracle parity test reads the local (Git-ignored)
DEVELOPMENT partition and skips with an explicit reason if it is absent.
"""

import json
from pathlib import Path
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from src.experiments import orb_level_interaction_compat as compat
from src.experiments.orb_level_interaction_compat import (
    ORB_INTERACTION_FIELDS,
    ORB_LEVEL_ORIENTATION,
    level_interaction,
    orb_window_interactions,
    unavailable_interaction,
)
from src.features.level_interactions import evaluate_level_interactions
from src.features.market_context import _safe_divide, calculate_or_context

ROOT = Path(__file__).resolve().parents[1]
TZ = "America/New_York"
FROZEN_AUDIT = ROOT / "experiments/projects/mnq_orb_v0_2/features/mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv"
DEV_PARTITION = ROOT / "data/processed/MNQ_raw_cleaned_ET_DEVELOPMENT.csv"
START = pd.Timestamp("2026-09-22 09:30", tz=TZ)


def frozen_reference(*, level, or_open, or_high, or_low, or_close, or_mid):
    """Verbatim frozen ORB formula (pre-M6B), used only as a test oracle."""
    if any(pd.isna(value) for value in (level, or_open, or_high, or_low, or_close, or_mid)):
        return unavailable_interaction()
    start_side = "BELOW" if or_open < level else ("ABOVE" if or_open > level else "AT")
    touched = bool(or_low <= level <= or_high)
    if start_side == "BELOW":
        traded_through = bool(or_high > level)
        closed_through = bool(or_close > level)
        swept = bool(traded_through and or_close <= level)
        rejected = bool(touched and or_close <= level)
    elif start_side == "ABOVE":
        traded_through = bool(or_low < level)
        closed_through = bool(or_close < level)
        swept = bool(traded_through and or_close >= level)
        rejected = bool(touched and or_close >= level)
    else:
        traded_through = closed_through = swept = rejected = False
    return {
        "available": True, "start_side": start_side,
        "distance_from_or_high_points": level - or_high,
        "distance_from_or_low_points": level - or_low,
        "distance_from_or_mid_points": level - or_mid,
        "distance_from_or_high_pct": _safe_divide(level - or_high, or_mid),
        "distance_from_or_low_pct": _safe_divide(level - or_low, or_mid),
        "distance_from_or_mid_pct": _safe_divide(level - or_mid, or_mid),
        "touched": touched, "traded_through": traded_through, "swept": swept,
        "closed_through": closed_through, "rejected": rejected,
    }


def window(level, o, h, lo, c, *, orientation="UPPER", minutes=30, start=START):
    return {"level": level, "orientation": orientation, "or_open": o, "or_high": h, "or_low": lo, "or_close": c,
            "or_mid": (h + lo) / 2.0, "window_start": start, "window_end": start + pd.Timedelta(minutes=minutes)}


def run(*windows, **kwargs):
    return orb_window_interactions(pd.DataFrame(list(windows)), **kwargs)


def same(a, b):
    return all((pd.isna(a[k]) and pd.isna(b[k])) or a[k] == b[k] for k in ORB_INTERACTION_FIELDS)


def random_windows(n, seed=11):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        o, c = rng.integers(392, 409, 2) * 0.25
        h = max(o, c) + rng.integers(0, 5) * 0.25
        lo = min(o, c) - rng.integers(0, 5) * 0.25
        level = float(rng.integers(390, 411) * 0.25)
        orientation = ("UPPER", "LOWER", "NEUTRAL")[i % 3]
        out.append(window(level, o, h, lo, c, orientation=orientation, minutes=(15, 20, 30)[i % 3],
                          start=START + pd.Timedelta(days=i)))
    return out


class GenericReuseTests(unittest.TestCase):
    def test_adapter_delegates_to_generic_engine(self):
        with mock.patch.object(compat, "evaluate_level_interactions", wraps=evaluate_level_interactions) as spy:
            run(window(100.0, 99.0, 101.0, 98.0, 99.5))
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(spy.call_args.kwargs["bar_interval"], pd.Timedelta(minutes=30))

    def test_flags_equal_generic_primitives_off_level(self):
        windows = [w for w in random_windows(600) if w["or_open"] != w["level"]]
        results = run(*windows)
        for w, result in zip(windows, results):
            bar = pd.DataFrame({"open": [w["or_open"]], "high": [w["or_high"]], "low": [w["or_low"]],
                                "close": [w["or_close"]], "contract": ["X"]},
                               index=pd.DatetimeIndex([w["window_end"]]))
            generic = evaluate_level_interactions(bar, pd.DataFrame([{
                "level_id": "L", "level_value": w["level"], "orientation": w["orientation"],
                "available_at": w["window_start"], "instrument_id": "MNQ", "contract_scope": "AGNOSTIC", "contract": None,
            }]), bar_interval=w["window_end"] - w["window_start"]).iloc[0]
            self.assertEqual(result["start_side"], generic["approach_side"])
            self.assertEqual((result["touched"], result["traded_through"], result["closed_through"],
                              result["rejected"], result["swept"]),
                             tuple(bool(generic[p]) for p in ("touch", "trade_through", "close_through", "reject", "sweep")))

    def test_randomized_equivalence_with_frozen_formula(self):
        windows = random_windows(1500)
        for w, result in zip(windows, run(*windows)):
            expected = frozen_reference(level=w["level"], or_open=w["or_open"], or_high=w["or_high"],
                                        or_low=w["or_low"], or_close=w["or_close"], or_mid=w["or_mid"])
            self.assertTrue(same(result, expected), (w, result, expected))

    def test_orientation_does_not_change_orb_output(self):
        for w in random_windows(300):
            results = [run({**w, "orientation": o})[0] for o in ("UPPER", "LOWER", "NEUTRAL")]
            self.assertTrue(same(results[0], results[1]) and same(results[0], results[2]))


class ApproachSideMappingTests(unittest.TestCase):
    def test_below_is_original_side_for_upper_level(self):
        result = run(window(100.0, 99.0, 100.25, 98.0, 99.75))[0]  # one-tick through, closes back: sweep
        self.assertEqual(result["start_side"], "BELOW")
        self.assertEqual((result["touched"], result["traded_through"], result["swept"], result["rejected"],
                          result["closed_through"]), (True, True, True, True, False))

    def test_above_is_far_side_for_upper_level(self):
        # An UPPER level (e.g. asia_high) with the OR opening above it: generic FAR_SIDE, ORB "ABOVE".
        result = run(window(100.0, 101.0, 101.5, 99.5, 99.75))[0]
        self.assertEqual(result["start_side"], "ABOVE")
        self.assertEqual((result["touched"], result["traded_through"], result["closed_through"]), (True, True, True))
        self.assertFalse(result["rejected"] or result["swept"])

    def test_lower_level_mirrors(self):
        below = run(window(100.0, 99.0, 100.5, 98.0, 100.25, orientation="LOWER"))[0]  # far side for LOWER
        self.assertEqual((below["start_side"], below["closed_through"]), ("BELOW", True))


class OpenAtLevelCompatibilityTests(unittest.TestCase):
    def test_directional_open_at_level_forces_directional_flags_false(self):
        w = window(100.0, 100.0, 101.0, 99.0, 100.5, orientation="UPPER")
        result = run(w)[0]
        self.assertEqual(result["start_side"], "AT")
        self.assertTrue(result["touched"])
        self.assertEqual([result[f] for f in compat.DIRECTIONAL_FLAGS], [False] * 4)
        generic = run(w, apply_open_at_level_compat=False)[0]
        self.assertTrue(generic["traded_through"] and generic["closed_through"])  # M6A original-side semantics

    def test_neutral_open_at_level_is_ambiguous_generically(self):
        w = window(100.0, 100.0, 101.0, 99.0, 100.5, orientation="NEUTRAL")
        self.assertEqual([run(w)[0][f] for f in compat.DIRECTIONAL_FLAGS], [False] * 4)
        self.assertEqual([run(w, apply_open_at_level_compat=False)[0][f] for f in compat.DIRECTIONAL_FLAGS], [None] * 4)

    def test_compat_only_affects_at_rows(self):
        windows = [w for w in random_windows(600) if w["or_open"] != w["level"]]
        on, off = run(*windows), run(*windows, apply_open_at_level_compat=False)
        self.assertTrue(all(same(a, b) for a, b in zip(on, off)))


class AggregatedWindowTests(unittest.TestCase):
    def test_or_window_is_one_aggregated_bar(self):
        index = pd.date_range(START + pd.Timedelta(minutes=1), periods=40, freq="min", name="timestamp_et")
        path = 100.0 + np.round(np.sin(np.arange(40) / 4.0) * 8) * 0.25
        bars = pd.DataFrame({"open": path, "high": path + 0.5, "low": path - 0.5, "close": path + 0.25,
                             "contract": "MNQ 12-26", "session_date": START.date()}, index=index)
        context = calculate_or_context(bars, START.date(), 15)
        first15 = bars.iloc[:15]
        self.assertEqual((context["or_open"], context["or_high"], context["or_low"], context["or_close"]),
                         (first15["open"].iloc[0], first15["high"].max(), first15["low"].min(), first15["close"].iloc[-1]))
        level = float(first15["high"].max())  # exact touch of the aggregated high
        result = run({"level": level, "orientation": "UPPER", **{k: context[k] for k in ("or_open", "or_high", "or_low", "or_close", "or_mid")},
                      "window_start": START, "window_end": START + pd.Timedelta(minutes=15)})[0]
        self.assertTrue(result["touched"])
        self.assertFalse(result["traded_through"])

    def test_windows_sharing_an_end_must_agree(self):
        a = window(100.0, 99.0, 101.0, 98.0, 99.5)
        b = {**a, "level": 99.0, "or_close": 100.0}
        with self.assertRaises(ValueError):
            run(a, b)


class SchemaAdapterTests(unittest.TestCase):
    def test_schema_order_and_types(self):
        result = run(window(100.0, 99.0, 101.0, 98.0, 99.5))[0]
        self.assertEqual(tuple(result), ORB_INTERACTION_FIELDS)
        self.assertIs(result["available"], True)
        self.assertEqual(result["distance_from_or_high_points"], -1.0)
        self.assertEqual(result["distance_from_or_mid_pct"], _safe_divide(100.0 - 99.5, 99.5))
        for name in ("touched", "traded_through", "swept", "closed_through", "rejected"):
            self.assertIsInstance(result[name], bool)

    def test_missing_inputs_are_unavailable(self):
        for missing in ("level", "or_open", "or_mid"):
            result = run({**window(100.0, 99.0, 101.0, 98.0, 99.5), missing: np.nan})[0]
            self.assertTrue(same(result, unavailable_interaction()))

    def test_scalar_legacy_signature(self):
        self.assertTrue(same(level_interaction(level=100, or_open=99, or_high=101, or_low=98, or_close=99.5, or_mid=99.5),
                             frozen_reference(level=100, or_open=99, or_high=101, or_low=98, or_close=99.5, or_mid=99.5)))

    def test_all_eighteen_frozen_levels_have_semantic_orientation(self):
        self.assertEqual(len(ORB_LEVEL_ORIENTATION), 18)
        for name, orientation in ORB_LEVEL_ORIENTATION.items():
            expected = "UPPER" if name.endswith("_high") else ("LOWER" if name.endswith("_low") else "NEUTRAL")
            self.assertEqual(orientation, expected, name)


class GenericSemanticsUnchangedTests(unittest.TestCase):
    def test_m6a_still_evaluates_directional_open_at_level(self):
        bar = pd.DataFrame({"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "contract": ["X"]},
                           index=pd.DatetimeIndex([START + pd.Timedelta(minutes=1)]))
        row = evaluate_level_interactions(bar, pd.DataFrame([{
            "level_id": "L", "level_value": 100.0, "orientation": "UPPER", "available_at": START,
            "instrument_id": "MNQ", "contract_scope": "AGNOSTIC", "contract": None}])).iloc[0]
        self.assertEqual((row["status"], row["approach_side"], row["approach_relation"]), ("EVALUATED", "AT", "ORIGINAL_SIDE"))
        self.assertTrue(row["trade_through"] and row["close_through"])


@unittest.skipUnless(DEV_PARTITION.is_file(), "local DEVELOPMENT partition not present (Git-ignored market data)")
class FrozenOracleParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.experiments.mnq_orb_v02_features import load_development_prices

        cls.prices = load_development_prices(DEV_PARTITION)
        cls.config = json.loads((ROOT / "config/features/mnq_orb_v0_2_preopen_windows.json").read_text(encoding="utf-8"))
        cls.frozen = pd.read_csv(FROZEN_AUDIT).sort_values(["session_date", "or_minutes"]).reset_index(drop=True)
        cls.level_columns = [c for c in cls.frozen.columns if c.startswith("level_")]

    def build(self):
        from src.experiments.mnq_orb_v02_features import build_feature_audit

        features = build_feature_audit(self.prices, self.config)
        now = pd.read_csv(pd.io.common.StringIO(features.to_csv(index=False)))
        return now.sort_values(["session_date", "or_minutes"]).reset_index(drop=True)

    def mismatches(self, now):
        return {c: int((~((self.frozen[c].astype(str) == now[c].astype(str))
                          | (self.frozen[c].isna() & now[c].isna()))).sum()) for c in self.level_columns}

    def test_all_234_interaction_columns_match_frozen_oracle(self):
        self.assertEqual(len(self.level_columns), 18 * 13)
        now = self.build()
        self.assertEqual([c for c in now.columns if c.startswith("level_")], self.level_columns)
        self.assertEqual({c: n for c, n in self.mismatches(now).items() if n}, {})

    def test_removing_open_at_level_compat_breaks_frozen_rows(self):
        import src.experiments.mnq_orb_v02_features as features_module

        original = compat.orb_window_interactions
        with mock.patch.object(features_module, "orb_window_interactions",
                               lambda w: original(w, apply_open_at_level_compat=False)):
            now = self.build()
        broken = {c: n for c, n in self.mismatches(now).items() if n}
        self.assertTrue(broken)
        self.assertTrue(all(c.rsplit("_", 1)[-1] in {"through", "swept", "rejected"} for c in broken), broken)
        self.assertEqual(broken["level_ny_open_reference_traded_through"], int((self.frozen["level_ny_open_reference_start_side"] == "AT").sum()))


if __name__ == "__main__":
    unittest.main()
