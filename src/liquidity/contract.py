"""Generic liquidity envelope: canonical members, structures and identities.

Specification: ``docs/project/EXTERNAL_LIQUIDITY_SPEC.md`` §10-§11 (D-134).
This module is methodology-neutral and family-neutral: it owns only the two
canonical tables, their deterministic identities and generic validation.
It contains no detection (no EQ/REQ, no session adapters), no lifecycle and
no registry.  External Liquidity lives in ``src/features/external_liquidity.py``.

- ``liquidity_members``: one row per canonical liquidity fact (the future
  lifecycle atom).  ``source_*`` is when the source observation completed;
  ``available_*`` is when it became causally available *as liquidity*
  (BEFORE or EQUAL under M7 ``compare_causal``).
- ``liquidity_structures``: immutable, content-addressed structure versions
  over members (``member_ids``), with static version history
  (``change_kind``, ``supersedes``) that is not lifecycle state.

Identities are full SHA-256 over canonical natural keys (M7 conventions):
``lm_`` (source identity; never availability or price) and ``ls_`` (sorted
member ids; never availability or history).  Causal keys, SourceRefs and
canonical time reuse public M7 primitives; errors they raise surface as
``LiquidityContractError`` with chaining.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import re
from typing import Any, Iterator

import numpy as np
import pandas as pd

from src.state.contract import (
    AFTER,
    AGNOSTIC,
    BEFORE,
    CONTRACT_SCOPES,
    EQUAL,
    INCOMPARABLE,
    SPECIFIC,
    CausalKey,
    StateContractError,
    canonical_ref,
    compare_causal,
)

EXTERNAL = "EXTERNAL"
INTERNAL = "INTERNAL"
LIQUIDITY_CLASSES = (EXTERNAL, INTERNAL)
UPPER = "UPPER"
LOWER = "LOWER"
ORIENTATIONS = (UPPER, LOWER)
EQ = "EQ"
REQ = "REQ"
STRUCTURE_TYPES = (EQ, REQ)
FORMED = "FORMED"
EXTENDED = "EXTENDED"
MERGED = "MERGED"
CHANGE_KINDS = (FORMED, EXTENDED, MERGED)
MEMBER_ID_PREFIX = "lm_"
STRUCTURE_ID_PREFIX = "ls_"

MEMBER_COLUMNS = (
    "member_id",
    "liquidity_class",
    "member_kind",
    "reference_family",
    "orientation",
    "price",
    "source_ref",
    "source_at",
    "source_seq_domain",
    "source_seq",
    "available_at",
    "available_seq_domain",
    "available_seq",
    "instrument_id",
    "contract_scope",
    "contract",
    "definition_version",
)
STRUCTURE_COLUMNS = (
    "structure_id",
    "liquidity_class",
    "structure_type",
    "reference_family",
    "orientation",
    "member_ids",
    "available_at",
    "available_seq_domain",
    "available_seq",
    "instrument_id",
    "contract_scope",
    "contract",
    "change_kind",
    "supersedes",
    "definition_version",
)
_SHARED_FIELDS = ("liquidity_class", "reference_family", "orientation", "instrument_id", "contract_scope",
                  "contract", "definition_version")
_UPPER_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9_]*")


class LiquidityContractError(ValueError):
    """Raised for any malformed liquidity member or structure."""


@contextmanager
def _boundary() -> Iterator[None]:
    """Translate errors from reused M7 primitives into LiquidityContractError."""
    try:
        yield
    except StateContractError as exc:
        raise LiquidityContractError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def member_id(
    *,
    definition_version: str,
    liquidity_class: str,
    member_kind: str,
    reference_family: str,
    orientation: str,
    instrument_id: str,
    contract_scope: str,
    contract: Any,
    source_ref: Any,
) -> str:
    """``lm_`` + full SHA-256 of the member's source identity.

    Price, ``source_at``, ``available_at`` and audit metadata are excluded, so
    a candidate promoted later keeps the same id regardless of confirmation.
    """
    with _boundary():
        ref = canonical_ref(source_ref)
    key = [definition_version, liquidity_class, member_kind, reference_family, orientation,
           instrument_id, contract_scope, _nullable(contract), ref]
    return MEMBER_ID_PREFIX + _sha256(key)


def structure_id(
    *,
    definition_version: str,
    liquidity_class: str,
    structure_type: str,
    reference_family: str,
    orientation: str,
    instrument_id: str,
    contract_scope: str,
    contract: Any,
    member_ids: Any,
) -> str:
    """``ls_`` + full SHA-256 over the sorted member ids (order-independent).

    ``available_at``, ``change_kind`` and ``supersedes`` are excluded; a
    changed member set is a new id by design.
    """
    key = [definition_version, liquidity_class, structure_type, reference_family, orientation,
           instrument_id, contract_scope, _nullable(contract), list(canonical_id_tuple(member_ids, "member_ids"))]
    return STRUCTURE_ID_PREFIX + _sha256(key)


def canonical_id_tuple(values: Any, name: str) -> tuple[str, ...]:
    """Sorted tuple of non-empty id strings (accepts list/tuple/ndarray).

    Duplicate ids are invalid input and raise; they are never silently deduplicated.
    """
    if values is None or (not isinstance(values, (list, tuple, np.ndarray)) and pd.isna(values)):
        return ()
    if isinstance(values, str) or not isinstance(values, (list, tuple, np.ndarray)):
        raise LiquidityContractError(f"{name} must be a sequence of ids")
    items = list(values)
    if not all(isinstance(item, str) and item for item in items):
        raise LiquidityContractError(f"{name} must contain non-empty strings")
    if len(items) != len(set(items)):
        duplicates = sorted({item for item in items if items.count(item) > 1})
        raise LiquidityContractError(f"{name} contains duplicate ids: {duplicates}")
    return tuple(sorted(items))


def assign_member_ids(members: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with canonical ``source_ref`` and computed ``member_id``."""
    frame = _require_frame(members, "members").copy()
    with _boundary():
        frame["source_ref"] = [canonical_ref(value) for value in frame["source_ref"]]
    frame["member_id"] = [
        member_id(
            definition_version=row.definition_version, liquidity_class=row.liquidity_class,
            member_kind=row.member_kind, reference_family=row.reference_family, orientation=row.orientation,
            instrument_id=row.instrument_id, contract_scope=row.contract_scope, contract=row.contract,
            source_ref=row.source_ref,
        )
        for row in frame.itertuples(index=False)
    ]
    return frame


def assign_structure_ids(structures: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with canonical ``member_ids`` / ``supersedes`` and ``structure_id``."""
    frame = _require_frame(structures, "structures").copy()
    frame["member_ids"] = [canonical_id_tuple(value, "member_ids") for value in frame["member_ids"]]
    if "supersedes" in frame.columns:
        frame["supersedes"] = [canonical_id_tuple(value, "supersedes") for value in frame["supersedes"]]
    frame["structure_id"] = [
        structure_id(
            definition_version=row.definition_version, liquidity_class=row.liquidity_class,
            structure_type=row.structure_type, reference_family=row.reference_family, orientation=row.orientation,
            instrument_id=row.instrument_id, contract_scope=row.contract_scope, contract=row.contract,
            member_ids=row.member_ids,
        )
        for row in frame.itertuples(index=False)
    ]
    return frame


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_liquidity_members(members: pd.DataFrame) -> pd.DataFrame:
    """Validate canonical liquidity members; return them normalized and ordered.

    Checks the exact schema, controlled vocabularies, finite prices, canonical
    SourceRefs, tz-aware times with co-null sequence pairs, source key BEFORE
    or EQUAL availability key (M7 semantics), contract scope, deterministic
    ids and uniqueness.  Times are returned in UTC.
    """
    frame = _exact_schema(members, MEMBER_COLUMNS, "members")
    if frame.empty:
        return frame
    for column in ("member_id", "member_kind", "reference_family", "instrument_id", "definition_version"):
        _require_tokens(frame[column], column)
    if not all(_UPPER_TOKEN_RE.fullmatch(value) for value in frame["member_kind"]):
        raise LiquidityContractError("member_kind must contain uppercase tokens")
    _check_vocabulary(frame, "liquidity_class", LIQUIDITY_CLASSES)
    _check_vocabulary(frame, "orientation", ORIENTATIONS)
    prices = pd.to_numeric(frame["price"], errors="coerce")
    if prices.isna().any() or not np.isfinite(prices.to_numpy(dtype=float)).all():
        raise LiquidityContractError("price must be finite")
    frame["price"] = prices.astype(float)
    with _boundary():
        canonical = [canonical_ref(value) for value in frame["source_ref"]]
    if canonical != list(frame["source_ref"]):
        raise LiquidityContractError("source_ref must be a canonical 'KIND:key' reference")
    frame = _normalize_keys(frame, ("source", "available"))
    source_keys = _keys(frame, "source")
    available_keys = _keys(frame, "available")
    for position, (source, available) in enumerate(zip(source_keys, available_keys)):
        relation = compare_causal(source, available)
        if relation == AFTER:
            raise LiquidityContractError(f"{frame['member_id'].iloc[position]}: available key precedes the source key")
        if relation == INCOMPARABLE:
            raise LiquidityContractError(f"{frame['member_id'].iloc[position]}: source and available keys are causally incomparable")
    _check_scope(frame)
    if frame["member_id"].duplicated().any():
        raise LiquidityContractError(f"duplicate member_id {frame.loc[frame['member_id'].duplicated(), 'member_id'].iloc[0]}")
    expected = assign_member_ids(frame)["member_id"]
    wrong = (expected != frame["member_id"]).to_numpy()
    if wrong.any():
        raise LiquidityContractError(f"{frame['member_id'].iloc[int(np.flatnonzero(wrong)[0])]}: member_id does not match its natural key")
    order = np.lexsort((
        _ranks(frame["member_id"]),
        _ranks(frame["member_kind"]),
        _ranks(frame["orientation"]),
        _ranks(frame["reference_family"]),
        _ranks(frame["liquidity_class"]),
        _seq_sort(frame["source_seq"]),
        _ranks(frame["source_seq_domain"]),
        _ns(frame["source_at"]),
        _seq_sort(frame["available_seq"]),
        _ranks(frame["available_seq_domain"]),
        _ns(frame["available_at"]),
    ))
    return frame.iloc[order].reset_index(drop=True)


def validate_liquidity_structures(structures: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """Validate structure versions against (validated) members; return them ordered.

    Checks the exact schema, controlled vocabularies, canonical sorted unique
    ``member_ids`` (>= 2) that all exist and share class / family /
    orientation / instrument / scope / contract / version with the
    structure, member availability BEFORE or EQUAL structure availability
    with at least one EQUAL (the confirming member), deterministic ids,
    uniqueness, and static version history: FORMED supersedes nothing,
    EXTENDED exactly one, MERGED two or more; superseded versions exist, have
    the same type and shared fields, are absorbed (member subset) and are
    causally earlier; no self-supersession.
    """
    member_frame = validate_liquidity_members(members)
    frame = _exact_schema(structures, STRUCTURE_COLUMNS, "structures")
    if frame.empty:
        return frame
    for column in ("structure_id", "reference_family", "instrument_id", "definition_version"):
        _require_tokens(frame[column], column)
    _check_vocabulary(frame, "liquidity_class", LIQUIDITY_CLASSES)
    _check_vocabulary(frame, "orientation", ORIENTATIONS)
    _check_vocabulary(frame, "structure_type", STRUCTURE_TYPES)
    _check_vocabulary(frame, "change_kind", CHANGE_KINDS)
    for column in ("member_ids", "supersedes"):
        normalized = []
        for value in frame[column]:
            raw = list(value) if isinstance(value, (list, tuple, np.ndarray)) else value
            canonical = canonical_id_tuple(value, column)
            if not isinstance(raw, list) or tuple(raw) != canonical:
                raise LiquidityContractError(f"{column} must be a canonical sorted unique tuple of ids")
            normalized.append(canonical)
        frame[column] = normalized
    if any(len(ids) < 2 for ids in frame["member_ids"]):
        raise LiquidityContractError("a structure needs at least 2 members")
    frame = _normalize_keys(frame, ("available",))
    _check_scope(frame)
    if frame["structure_id"].duplicated().any():
        raise LiquidityContractError(f"duplicate structure_id {frame.loc[frame['structure_id'].duplicated(), 'structure_id'].iloc[0]}")
    expected = assign_structure_ids(frame)["structure_id"]
    wrong = (expected != frame["structure_id"]).to_numpy()
    if wrong.any():
        raise LiquidityContractError(f"{frame['structure_id'].iloc[int(np.flatnonzero(wrong)[0])]}: structure_id does not match its natural key")

    by_member = member_frame.set_index("member_id")
    member_keys = dict(zip(member_frame["member_id"], _keys(member_frame, "available")))
    structure_keys = _keys(frame, "available")
    rows = {row.structure_id: (row, key) for row, key in zip(frame.itertuples(index=False), structure_keys)}
    for row, key in zip(frame.itertuples(index=False), structure_keys):
        missing = [mid for mid in row.member_ids if mid not in by_member.index]
        if missing:
            raise LiquidityContractError(f"{row.structure_id}: unknown member {missing[0]}")
        for field in _SHARED_FIELDS:
            values = set(by_member.loc[list(row.member_ids), field].map(_nullable))
            if values != {_nullable(getattr(row, field))}:
                raise LiquidityContractError(f"{row.structure_id}: members disagree with the structure on {field}")
        relations = [compare_causal(member_keys[mid], key) for mid in row.member_ids]
        if any(relation not in (BEFORE, EQUAL) for relation in relations):
            raise LiquidityContractError(f"{row.structure_id}: a member becomes available after the structure")
        if EQUAL not in relations:
            raise LiquidityContractError(f"{row.structure_id}: no member is available at the structure confirmation key")
        superseded = row.supersedes
        if row.structure_id in superseded:
            raise LiquidityContractError(f"{row.structure_id}: a structure cannot supersede itself")
        expected_count = {FORMED: (0, 0), EXTENDED: (1, 1), MERGED: (2, None)}[row.change_kind]
        if len(superseded) < expected_count[0] or (expected_count[1] is not None and len(superseded) > expected_count[1]):
            raise LiquidityContractError(f"{row.structure_id}: {row.change_kind} supersedes {len(superseded)} versions")
        for prior_id in superseded:
            if prior_id not in rows:
                raise LiquidityContractError(f"{row.structure_id}: superseded version {prior_id} is not present")
            prior, prior_key = rows[prior_id]
            if prior.structure_type != row.structure_type or any(
                _nullable(getattr(prior, field)) != _nullable(getattr(row, field)) for field in _SHARED_FIELDS
            ):
                raise LiquidityContractError(f"{row.structure_id}: superseded version {prior_id} is a different structure lineage")
            if not set(prior.member_ids) < set(row.member_ids):
                raise LiquidityContractError(f"{row.structure_id}: superseded version {prior_id} is not absorbed")
            if compare_causal(prior_key, key) != BEFORE:
                raise LiquidityContractError(f"{row.structure_id}: superseded version {prior_id} is not causally earlier")
    order = np.lexsort((
        _ranks(frame["structure_id"]),
        _ranks(frame["orientation"]),
        _ranks(frame["reference_family"]),
        _ranks(frame["structure_type"]),
        _ranks(frame["liquidity_class"]),
        _seq_sort(frame["available_seq"]),
        _ranks(frame["available_seq_domain"]),
        _ns(frame["available_at"]),
    ))
    return frame.iloc[order].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Plumbing (module-local)
# ---------------------------------------------------------------------------


def _sha256(key: list) -> str:
    return hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _require_frame(frame: Any, name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise LiquidityContractError(f"{name} must be a pandas DataFrame")
    return frame


def _exact_schema(frame: Any, columns: tuple[str, ...], name: str) -> pd.DataFrame:
    frame = _require_frame(frame, name)
    missing = [column for column in columns if column not in frame.columns]
    extra = [column for column in frame.columns if column not in columns]
    if missing:
        raise LiquidityContractError(f"{name} missing required columns: {missing}")
    if extra:
        raise LiquidityContractError(f"{name} have non-canonical columns: {extra}")
    return frame[list(columns)].reset_index(drop=True).copy()


def _require_tokens(series: pd.Series, name: str) -> None:
    if not all(isinstance(value, str) and value.strip() and value == value.strip() for value in series):
        raise LiquidityContractError(f"{name} must contain non-empty trimmed strings")


def _check_vocabulary(frame: pd.DataFrame, column: str, allowed: tuple[str, ...]) -> None:
    bad = sorted(set(frame[column].map(str)) - set(allowed))
    if bad or frame[column].isna().any():
        raise LiquidityContractError(f"{column} must be one of {allowed}, got {bad}")


def _check_scope(frame: pd.DataFrame) -> None:
    scope, contract = frame["contract_scope"], frame["contract"]
    if not scope.isin(CONTRACT_SCOPES).all():
        raise LiquidityContractError(f"contract_scope must be one of {CONTRACT_SCOPES}")
    present = contract.map(lambda value: isinstance(value, str) and bool(value.strip()))
    if (scope.eq(SPECIFIC) & ~present).any():
        raise LiquidityContractError("SPECIFIC scope requires a non-empty contract")
    if (scope.eq(AGNOSTIC) & contract.notna()).any():
        raise LiquidityContractError("AGNOSTIC scope must have a null contract")
    frame["contract"] = contract.astype(object).where(contract.notna(), None)


def _normalize_keys(frame: pd.DataFrame, prefixes: tuple[str, ...]) -> pd.DataFrame:
    for prefix in prefixes:
        frame[f"{prefix}_at"] = _utc(frame[f"{prefix}_at"], f"{prefix}_at")
        seq = pd.Series(frame[f"{prefix}_seq"])
        if pd.api.types.is_bool_dtype(seq.dtype) or any(isinstance(v, (bool, np.bool_, str)) for v in seq.dropna()):
            raise LiquidityContractError(f"{prefix}_seq must contain integers or nulls")
        try:
            frame[f"{prefix}_seq"] = pd.array(seq.to_numpy(dtype=object), dtype="Int64")
        except (TypeError, ValueError) as exc:
            raise LiquidityContractError(f"{prefix}_seq must contain integers or nulls") from exc
        domain = frame[f"{prefix}_seq_domain"]
        frame[f"{prefix}_seq_domain"] = domain.astype(object).where(domain.notna(), None)
        _keys(frame, prefix)  # validates co-null pairs and domain tokens through CausalKey
    return frame


def _keys(frame: pd.DataFrame, prefix: str) -> list[CausalKey]:
    with _boundary():
        return [
            CausalKey(at, domain, None if pd.isna(seq) else int(seq))
            for at, domain, seq in zip(frame[f"{prefix}_at"], frame[f"{prefix}_seq_domain"], frame[f"{prefix}_seq"])
        ]


def _utc(values: pd.Series, name: str) -> pd.Series:
    series = pd.Series(values)
    if series.isna().any():
        raise LiquidityContractError(f"{name} contains missing timestamps")
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        return series.dt.tz_convert("UTC").dt.as_unit("ns")
    if series.dtype == object and all(getattr(value, "tzinfo", None) is not None for value in series):
        return pd.to_datetime(series, utc=True).dt.as_unit("ns")
    raise LiquidityContractError(f"{name} must contain timezone-aware timestamps")


def _ranks(values: pd.Series) -> np.ndarray:
    """Deterministic sorted ranks for string keys (nulls first); never encounter order."""
    items = [None if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value) for value in values]
    rank = {value: position for position, value in enumerate(sorted({value for value in items if value is not None}))}
    return np.array([-1 if value is None else rank[value] for value in items], dtype=np.int64)


def _seq_sort(values: pd.Series) -> np.ndarray:
    return pd.Series(values).astype("Float64").fillna(-np.inf).to_numpy(dtype=float)


def _ns(values: pd.Series) -> np.ndarray:
    return pd.DatetimeIndex(values).tz_convert("UTC").as_unit("ns").asi8


def _nullable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if not isinstance(value, (str, tuple, list)) and pd.isna(value):
        return None
    return value
