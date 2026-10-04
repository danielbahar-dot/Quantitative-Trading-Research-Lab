"""Generic liquidity envelope tests (EL-I1). Synthetic rows only."""

import unittest

import numpy as np
import pandas as pd

from src.liquidity.contract import (
    EQ,
    EXTENDED,
    FORMED,
    MEMBER_COLUMNS,
    MERGED,
    REQ,
    STRUCTURE_COLUMNS,
    LiquidityContractError,
    assign_member_ids,
    assign_structure_ids,
    member_id,
    structure_id,
    validate_liquidity_members,
    validate_liquidity_structures,
)
from src.state.contract import StateContractError

TZ = "America/New_York"
T0 = pd.Timestamp("2026-09-22 18:00", tz=TZ)
H4 = pd.Timedelta(hours=4)


def t(i):
    return T0 + i * H4


def member(i, price=100.0, *, kind="HTF_EQREQ_HIGH", orientation="UPPER", family="4H", contract="MNQ 12-26",
           scope="SPECIFIC", source_at=None, available_at=None, source_seq=(None, None), available_seq=(None, None),
           ref=None):
    source_at = t(i) if source_at is None else source_at
    return {
        "member_id": "pending", "liquidity_class": "EXTERNAL", "member_kind": kind, "reference_family": family,
        "orientation": orientation, "price": price,
        "source_ref": ref or f"HTF_BAR:MNQ|{contract}|{family}|{source_at.tz_convert('UTC').isoformat()}",
        "source_at": source_at, "source_seq_domain": source_seq[0], "source_seq": source_seq[1],
        "available_at": source_at if available_at is None else available_at,
        "available_seq_domain": available_seq[0], "available_seq": available_seq[1],
        "instrument_id": "MNQ", "contract_scope": scope, "contract": contract if scope == "SPECIFIC" else None,
        "definition_version": "el-v1",
    }


def members(*rows):
    return assign_member_ids(pd.DataFrame(list(rows)))


def structure(member_frame, ids, at, *, kind=FORMED, supersedes=(), stype=EQ, **overrides):
    first = member_frame.set_index("member_id").loc[ids[0]]
    row = {
        "structure_id": "pending", "liquidity_class": first["liquidity_class"], "structure_type": stype,
        "reference_family": first["reference_family"], "orientation": first["orientation"],
        "member_ids": tuple(ids), "available_at": at, "available_seq_domain": None, "available_seq": None,
        "instrument_id": "MNQ", "contract_scope": first["contract_scope"], "contract": first["contract"],
        "change_kind": kind, "supersedes": tuple(supersedes), "definition_version": "el-v1",
    }
    row.update(overrides)
    return row


def structures(*rows):
    return assign_structure_ids(pd.DataFrame(list(rows)))


class MemberIdentityTests(unittest.TestCase):
    def test_full_sha256_and_natural_key(self):
        base = members(member(0))
        mid = base["member_id"].iloc[0]
        self.assertRegex(mid, r"^lm_[0-9a-f]{64}$")
        variants = {
            "source": member(1),
            "orientation": member(0, orientation="LOWER", kind="HTF_EQREQ_LOW"),
            "kind": member(0, kind="DAILY_HIGH"),
            "contract": member(0, contract="MNQ 03-27"),
            "family": member(0, family="1D"),
        }
        ids = {name: members(row)["member_id"].iloc[0] for name, row in variants.items()}
        self.assertNotIn(mid, ids.values())
        self.assertEqual(len(set(ids.values())), len(ids))

    def test_price_and_availability_are_not_identity(self):
        a = members(member(0, price=100.0))["member_id"].iloc[0]
        b = members(member(0, price=105.0, available_at=t(3)))["member_id"].iloc[0]
        self.assertEqual(a, b)  # a promoted candidate keeps its id whatever its confirmation time

    def test_source_ref_key_is_opaque_text(self):
        # M7 SourceRef keys are opaque: the generic id hashes the ref text and does not parse timestamps,
        # so differently written times are different ids.  Timezone canonicalization is the producer's job
        # (External's htf_source_ref, tested in test_external_liquidity.py).
        ref_ny = f"HTF_BAR:MNQ|MNQ 12-26|4H|{t(0).isoformat()}"
        ref_utc = f"HTF_BAR:MNQ|MNQ 12-26|4H|{t(0).tz_convert('UTC').isoformat()}"
        kwargs = dict(definition_version="v", liquidity_class="EXTERNAL", member_kind="DAILY_HIGH", reference_family="1D",
                      orientation="UPPER", instrument_id="MNQ", contract_scope="SPECIFIC", contract="C")
        self.assertEqual(member_id(**kwargs, source_ref=ref_utc), member_id(**kwargs, source_ref=ref_utc))
        self.assertNotEqual(member_id(**kwargs, source_ref=ref_ny), member_id(**kwargs, source_ref=ref_utc))


class MemberValidationTests(unittest.TestCase):
    def raises(self, frame, pattern="."):
        with self.assertRaisesRegex(LiquidityContractError, pattern):
            validate_liquidity_members(frame)

    def test_valid_and_normalized(self):
        out = validate_liquidity_members(members(member(1), member(0)))
        self.assertEqual(list(out.columns), list(MEMBER_COLUMNS))
        self.assertEqual(str(out["source_at"].dt.tz), "UTC")
        self.assertEqual(out["source_at"].tolist(), [t(0), t(1)])

    def test_causality(self):
        validate_liquidity_members(members(member(0, available_at=t(2))))  # BEFORE
        validate_liquidity_members(members(member(0)))                      # EQUAL
        self.raises(members(member(2, available_at=t(1))), "precedes")     # AFTER
        validate_liquidity_members(members(member(0, source_seq=("F", 5), available_seq=("F", 6))))
        self.raises(members(member(0, source_seq=("F", 6), available_seq=("F", 5))), "precedes")
        self.raises(members(member(0, source_seq=("A", 5), available_seq=("B", 9))), "incomparable")
        self.raises(members(member(0, source_seq=("A", 5))), "incomparable")  # unsequenced availability at the same time

    def test_contract_and_schema(self):
        self.raises(members(member(0, contract=None)), "SPECIFIC scope requires")
        agnostic = member(0, scope="AGNOSTIC")
        validate_liquidity_members(members(agnostic))
        with_contract = members(agnostic)
        with_contract["contract"] = ["X"]
        self.raises(assign_member_ids(with_contract), "AGNOSTIC scope")
        bad_ref = member(0)
        bad_ref["source_ref"] = "not a ref"
        with self.assertRaises(LiquidityContractError) as raised:
            members(bad_ref)
        self.assertIsInstance(raised.exception.__cause__, StateContractError)
        good = members(member(0))
        self.raises(good.assign(state="ACTIVE"), "non-canonical columns")
        self.raises(good.drop(columns=["available_seq"]), "missing required columns")
        self.raises(good.assign(price=[float("inf")]), "finite")
        self.raises(good.assign(orientation=["UP"]), "orientation")
        self.raises(good.assign(liquidity_class=["ICT"]), "liquidity_class")
        naive = good.copy()
        naive["source_at"] = naive["source_at"].dt.tz_localize(None)
        self.raises(naive, "timezone-aware")
        half = good.copy()
        half["source_seq"] = pd.array([3], dtype="Int64")
        self.raises(half, "both null or both present")

    def test_identity_checks(self):
        good = members(member(0))
        self.raises(pd.concat([good, good], ignore_index=True), "duplicate member_id")
        tampered = good.copy()
        tampered.loc[0, "member_id"] = "lm_" + "0" * 64
        self.raises(tampered, "does not match")

    def test_shuffle_determinism(self):
        rows = [member(i, price=100 + i) for i in range(6)] + [member(i, orientation="LOWER", kind="HTF_EQREQ_LOW") for i in range(3)]
        baseline = validate_liquidity_members(members(*rows))
        rng = np.random.default_rng(1)
        for _ in range(5):
            shuffled = members(*rows).sample(frac=1, random_state=int(rng.integers(0, 9999))).reset_index(drop=True)
            pd.testing.assert_frame_equal(validate_liquidity_members(shuffled), baseline)


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.members = members(member(0), member(1), member(2, price=101.0), member(3, price=100.5),
                               member(0, orientation="LOWER", kind="HTF_EQREQ_LOW"),
                               member(4, contract="MNQ 03-27"))
        self.ids = list(self.members["member_id"])

    def raises(self, frame, pattern="."):
        with self.assertRaisesRegex(LiquidityContractError, pattern):
            validate_liquidity_structures(frame, self.members)

    def test_identity(self):
        a, b, c = self.ids[:3]
        s1 = structures(structure(self.members, [a, b], t(1)))
        sid = s1["structure_id"].iloc[0]
        self.assertRegex(sid, r"^ls_[0-9a-f]{64}$")
        self.assertEqual(structures(structure(self.members, [b, a], t(1)))["structure_id"].iloc[0], sid)  # order invariant
        self.assertEqual(structures(structure(self.members, [a, b], t(1), available_at=t(1)))["structure_id"].iloc[0], sid)
        self.assertNotEqual(structures(structure(self.members, [a, b, c], t(2)))["structure_id"].iloc[0], sid)
        kwargs = dict(definition_version="el-v1", liquidity_class="EXTERNAL", structure_type=EQ, reference_family="4H",
                      orientation="UPPER", instrument_id="MNQ", contract_scope="SPECIFIC", contract="MNQ 12-26")
        self.assertEqual(structure_id(**kwargs, member_ids=[b, a]), sid)
        self.assertNotEqual(structure_id(**{**kwargs, "structure_type": REQ}, member_ids=[a, b]), sid)

    def test_valid_and_invalid_structures(self):
        a, b, c, d, low, other = self.ids
        out = validate_liquidity_structures(structures(structure(self.members, [a, b], t(1))), self.members)
        self.assertEqual(list(out.columns), list(STRUCTURE_COLUMNS))
        self.raises(structures(structure(self.members, [a, "lm_" + "1" * 64], t(1))), "unknown member")
        self.raises(structures(structure(self.members, [a, low], t(1))), "orientation")
        self.raises(structures(structure(self.members, [a, other], t(4))), "contract")
        self.raises(structures(structure(self.members, [a], t(0))), "at least 2")
        dup = structures(structure(self.members, [a, b], t(1)))
        dup.at[0, "member_ids"] = (a, a, b)
        self.raises(dup, "duplicate ids")
        unsorted = structures(structure(self.members, [a, b], t(1)))
        unsorted.at[0, "member_ids"] = tuple(sorted([a, b], reverse=True))
        self.raises(unsorted, "canonical sorted unique")
        self.raises(structures(structure(self.members, [a, b], t(0))), "after the structure")       # before b exists
        self.raises(structures(structure(self.members, [a, b], t(5))), "no member is available")   # no confirming member
        self.raises(structures(structure(self.members, [a, b], t(1), structure_type="XEQ")), "structure_type")
        tampered = structures(structure(self.members, [a, b], t(1)))
        tampered.loc[0, "structure_id"] = "ls_" + "0" * 64
        self.raises(tampered, "does not match")
        twice = structures(structure(self.members, [a, b], t(1)))
        self.raises(pd.concat([twice, twice], ignore_index=True), "duplicate structure_id")

    def test_change_history(self):
        a, b, c, d = self.ids[:4]
        v1 = structures(structure(self.members, [a, b], t(1)))
        v1_id = v1["structure_id"].iloc[0]
        v2 = structures(structure(self.members, [c, d], t(3), stype=REQ))
        ext = structures(structure(self.members, [a, b, c], t(2), kind=EXTENDED, supersedes=[v1_id], stype=EQ))
        validate_liquidity_structures(pd.concat([v1, ext], ignore_index=True), self.members)
        self.raises(pd.concat([v1, structures(structure(self.members, [a, b, c], t(2), kind=FORMED, supersedes=[v1_id]))],
                              ignore_index=True), "FORMED supersedes 1")
        self.raises(pd.concat([v1, structures(structure(self.members, [a, b, c], t(2), kind=MERGED, supersedes=[v1_id]))],
                              ignore_index=True), "MERGED supersedes 1")
        self.raises(structures(structure(self.members, [a, b, c], t(2), kind=EXTENDED, supersedes=["ls_" + "2" * 64])),
                    "not present")
        # EQ cannot supersede REQ (different lineage)
        req_c_d = structures(structure(self.members, [c, d], t(3), stype=REQ))
        bad = structures(structure(self.members, [a, b, c, d], t(3), kind=EXTENDED, supersedes=[req_c_d["structure_id"].iloc[0]], stype=EQ))
        self.raises(pd.concat([req_c_d, bad], ignore_index=True), "different structure lineage")
        # merge of two same-type versions
        eq_v1 = structures(structure(self.members, [a, b], t(1), stype=REQ))
        req_cd = structures(structure(self.members, [c, d], t(3), stype=REQ))
        e = members(member(5, price=100.25))
        all_members = pd.concat([self.members, e], ignore_index=True)
        merged = structures(structure(all_members, [a, b, c, d, e["member_id"].iloc[0]], t(5), kind=MERGED,
                                      supersedes=[eq_v1["structure_id"].iloc[0], req_cd["structure_id"].iloc[0]], stype=REQ))
        out = validate_liquidity_structures(pd.concat([eq_v1, req_cd, merged], ignore_index=True), all_members)
        self.assertEqual(out["change_kind"].tolist(), [FORMED, FORMED, MERGED])
        self.assertEqual(len(out.iloc[-1]["supersedes"]), 2)
        self.assertTrue(v2["structure_id"].iloc[0])

    def test_duplicate_ids_rejected_not_deduplicated(self):
        a, b, c = self.ids[:3]
        with self.assertRaisesRegex(LiquidityContractError, "member_ids contains duplicate ids"):
            structures(structure(self.members, [a, b, a], t(1)))
        with self.assertRaisesRegex(LiquidityContractError, "member_ids contains duplicate ids"):
            structure_id(definition_version="el-v1", liquidity_class="EXTERNAL", structure_type=EQ, reference_family="4H",
                         orientation="UPPER", instrument_id="MNQ", contract_scope="SPECIFIC", contract="MNQ 12-26",
                         member_ids=[a, b, b])
        v1 = structures(structure(self.members, [a, b], t(1)))["structure_id"].iloc[0]
        with self.assertRaisesRegex(LiquidityContractError, "supersedes contains duplicate ids"):
            structures(structure(self.members, [a, b, c], t(2), kind=EXTENDED, supersedes=[v1, v1]))

    def test_unsorted_unique_ids_canonicalize_deterministically(self):
        a, b, c = self.ids[:3]
        v1 = structures(structure(self.members, [a, b], t(1)))["structure_id"].iloc[0]
        v2 = structures(structure(self.members, [a, c], t(2)))["structure_id"].iloc[0]
        orders = [[a, b, c], [c, a, b], [b, c, a]]
        outs = [structures(structure(self.members, ids, t(2), kind=MERGED, supersedes=sups))
                for ids, sups in zip(orders, ([v1, v2], [v2, v1], [v2, v1]))]
        for out in outs:
            self.assertEqual(out["member_ids"].iloc[0], tuple(sorted([a, b, c])))
            self.assertEqual(out["supersedes"].iloc[0], tuple(sorted([v1, v2])))
            self.assertEqual(out["structure_id"].iloc[0], outs[0]["structure_id"].iloc[0])

    def test_self_supersession_rejected(self):
        a, b, c = self.ids[:3]
        row = structures(structure(self.members, [a, b, c], t(2), kind=EXTENDED))
        row.at[0, "supersedes"] = (row["structure_id"].iloc[0],)
        self.raises(row, "supersede itself")

    def test_shuffle_determinism(self):
        a, b, c, d = self.ids[:4]
        rows = [structure(self.members, [a, b], t(1)), structure(self.members, [c, d], t(3), stype=REQ),
                structure(self.members, [a, c], t(2), stype=REQ)]
        baseline = validate_liquidity_structures(structures(*rows), self.members)
        for seed in range(4):
            shuffled = structures(*rows).sample(frac=1, random_state=seed).reset_index(drop=True)
            pd.testing.assert_frame_equal(validate_liquidity_structures(shuffled, self.members.sample(frac=1, random_state=seed)), baseline)


if __name__ == "__main__":
    unittest.main()
