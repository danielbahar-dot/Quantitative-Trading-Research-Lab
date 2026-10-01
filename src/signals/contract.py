"""Generic Signal contract (M7B): immutable, reusable market events.

Specification: ``docs/project/M7_STATE_SIGNAL_CONTRACTS_SPEC.md``, section
"M7B FINAL CONTRACT" (D-132).

A Signal describes *what happened*, never *what trade to place*.  It is an
immutable point event: no ACTIVE/EXPIRED state, no validity window, no
execution fields.  It may derive from a feature, an interaction, a
StateTransition (even one created by the same causal event) or several
sources; consuming it still requires a causally later observation, which
is a downstream (strategy) concern, not part of this module.

Causal, provenance and identity semantics are the M7A ones, reused from the
public primitives of ``src.state.contract`` (``CausalKey``,
``compare_causal``, ``SourceRef``, ``canonical_ref``,
``canonical_source_refs``, ``canonical_time``, ``AttributeSpec``).  No
private State helper is imported; the small DataFrame plumbing below is
Signal-local.  Errors raised by reused M7A primitives are re-raised as
``SignalContractError`` with exception chaining.

``validate_signals`` checks the envelope only.  It does not check whether
the upstream trigger observation was eligible, whether ``subject_id``
resolves to a live entity, cross-layer source timing, or strategy and
execution eligibility.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterator

import numpy as np
import pandas as pd

from src.state.contract import (
    AFTER,
    AGNOSTIC,
    ATTRIBUTE_PREFIX,
    BEFORE,
    CONTRACT_SCOPES,
    EQUAL,
    INCOMPARABLE,
    SPECIFIC,
    AttributeSpec,
    CausalKey,
    StateContractError,
    canonical_ref,
    canonical_source_refs,
    canonical_time,
    compare_causal,
)

DIRECTIONS = ("BULLISH", "BEARISH", "NEUTRAL")
FORBIDDEN_EXECUTION_FIELDS = (
    "entry", "entry_price", "entry_time",
    "stop", "stop_loss", "stop_price", "initial_stop",
    "take_profit", "target", "target_price", "initial_target",
    "limit_price",
    "quantity", "size", "position_size",
    "order_type", "order_side",
    "risk", "risk_points", "r_multiple",
    "trade_id",
)
SIGNAL_COLUMNS = (
    "signal_id",
    "signal_type",
    "definition_version",
    "subject_id",
    "event_at",
    "event_seq_domain",
    "event_seq",
    "available_at",
    "available_seq_domain",
    "available_seq",
    "instrument_id",
    "contract_scope",
    "contract",
    "direction",
    "trigger_ref",
)
OPTIONAL_SIGNAL_COLUMNS = ("source_refs",)
SIGNAL_ID_PREFIX = "sg_"
SEMANTIC_EVENT_KEY = (
    "signal_type", "definition_version", "instrument_id", "contract_scope", "contract",
    "subject_id", "event_at", "event_seq_domain", "event_seq", "direction",
)

_SIGNAL_TYPE_RE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*")
_LOWER_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")
_FORBIDDEN = frozenset(FORBIDDEN_EXECUTION_FIELDS)


class SignalContractError(ValueError):
    """Raised for any malformed Signal definition or Signal record."""


@contextmanager
def _signal_boundary() -> Iterator[None]:
    """Translate errors from reused M7A primitives into SignalContractError."""
    try:
        yield
    except StateContractError as exc:
        raise SignalContractError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SignalDefinitionSpec:
    """Definition-owned semantics of one signal type.

    ``allowed_directions`` empty means the definition is undirected (direction
    must be null); otherwise each Signal carries exactly one declared value.
    NEUTRAL has no implicit behaviour.  ``subject_kind`` names the kind of
    the primary subject, so rows do not repeat it.
    """

    signal_type: str
    subject_kind: str
    definition_version: str
    allowed_directions: tuple[str, ...] = ()
    attributes: tuple[AttributeSpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_directions", tuple(self.allowed_directions))
        object.__setattr__(self, "attributes", tuple(self.attributes))
        if not isinstance(self.signal_type, str) or not _SIGNAL_TYPE_RE.fullmatch(self.signal_type):
            raise SignalContractError(f"signal_type must be dotted lowercase tokens, got {self.signal_type!r}")
        if not isinstance(self.subject_kind, str) or not _LOWER_TOKEN_RE.fullmatch(self.subject_kind):
            raise SignalContractError(f"subject_kind must be a lowercase token, got {self.subject_kind!r}")
        if not isinstance(self.definition_version, str) or not self.definition_version.strip():
            raise SignalContractError("definition_version must be a non-empty string")
        directions = self.allowed_directions
        if len(set(directions)) != len(directions):
            raise SignalContractError(f"{self.signal_type}: allowed_directions must be unique")
        unknown = [direction for direction in directions if direction not in DIRECTIONS]
        if unknown:
            raise SignalContractError(f"{self.signal_type}: directions {unknown} are not in {DIRECTIONS}")
        for attribute in self.attributes:
            if not isinstance(attribute, AttributeSpec):
                raise SignalContractError(f"{self.signal_type}: attributes must be AttributeSpec instances")
            if attribute.name in _FORBIDDEN:
                raise SignalContractError(f"{self.signal_type}: attribute {attribute.column} is an execution field")
        names = [attribute.name for attribute in self.attributes]
        if len(set(names)) != len(names):
            raise SignalContractError(f"{self.signal_type}: duplicate attribute names")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def signal_id(
    *,
    signal_type: str,
    definition_version: str,
    instrument_id: str,
    contract_scope: str,
    contract: Any,
    subject_id: str,
    event_at: Any,
    event_seq_domain: Any = None,
    event_seq: Any = None,
    direction: Any = None,
    trigger_ref: Any,
    source_refs: Any = (),
) -> str:
    """Deterministic id: ``sg_`` + full SHA-256 of the canonical natural key.

    Availability and attribute values are not part of the identity; the
    event time is canonical UTC and ``source_refs`` are canonicalized, so
    timezone representation and reference order never change the id.
    """
    with _signal_boundary():
        key = CausalKey(event_at, event_seq_domain, event_seq)
        natural_key = [
            signal_type,
            definition_version,
            instrument_id,
            contract_scope,
            _nullable(contract),
            subject_id,
            canonical_time(key.at),
            key.seq_domain,
            key.seq,
            _nullable(direction),
            canonical_ref(trigger_ref),
            list(canonical_source_refs(source_refs)),
        ]
    payload = json.dumps(natural_key, ensure_ascii=False, separators=(",", ":"))
    return SIGNAL_ID_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assign_signal_ids(signals: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with canonical references and computed ``signal_id``."""
    if not isinstance(signals, pd.DataFrame):
        raise SignalContractError("signals must be a pandas DataFrame")
    frame = signals.copy()
    with _signal_boundary():
        frame["trigger_ref"] = [canonical_ref(value) for value in frame["trigger_ref"]]
        frame["source_refs"] = [
            canonical_source_refs(value)
            for value in (frame["source_refs"] if "source_refs" in frame.columns else [()] * len(frame))
        ]
    optional = {column: frame[column] if column in frame.columns else [None] * len(frame)
                for column in ("event_seq_domain", "event_seq", "direction", "contract")}
    frame["signal_id"] = [
        signal_id(
            signal_type=row.signal_type, definition_version=row.definition_version, instrument_id=row.instrument_id,
            contract_scope=row.contract_scope, contract=contract, subject_id=row.subject_id, event_at=row.event_at,
            event_seq_domain=domain, event_seq=seq, direction=direction, trigger_ref=row.trigger_ref,
            source_refs=row.source_refs,
        )
        for row, domain, seq, direction, contract in zip(
            frame.itertuples(index=False), optional["event_seq_domain"], optional["event_seq"],
            optional["direction"], optional["contract"],
        )
    ]
    return frame


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_signals(signals: pd.DataFrame, definition: SignalDefinitionSpec) -> pd.DataFrame:
    """Validate Signal rows for one definition; return them canonicalized and ordered.

    Checks schema, definition conformity, direction, event/availability
    causality (M7A ``compare_causal``: BEFORE or EQUAL), sequence-domain
    pairing, contract rules, SourceRef canonical form, trigger/source
    overlap, identity, duplicate ids, semantic-event uniqueness, typed
    attributes and forbidden execution fields.  Timestamps are returned in
    UTC.  It does not check upstream trigger eligibility, subject
    resolution, cross-layer source timing, or strategy/execution eligibility.
    """
    if not isinstance(definition, SignalDefinitionSpec):
        raise SignalContractError("definition must be a SignalDefinitionSpec")
    frame = _check_schema(signals, definition)
    if frame.empty:
        return frame
    _check_envelope(frame, definition)
    with _signal_boundary():
        event_keys = _causal_keys(frame, "event")
        available_keys = _causal_keys(frame, "available")
        frame["trigger_ref"] = [canonical_ref(value) for value in frame["trigger_ref"]]
        frame["source_refs"] = [canonical_source_refs(value) for value in frame["source_refs"]]
    overlap = [trigger in refs for trigger, refs in zip(frame["trigger_ref"], frame["source_refs"])]
    if any(overlap):
        raise SignalContractError(f"{_first(frame, overlap)}: trigger_ref must not also appear in source_refs")
    for position, (event, available) in enumerate(zip(event_keys, available_keys)):
        relation = compare_causal(event, available)
        if relation == AFTER:
            raise SignalContractError(f"{frame['signal_id'].iloc[position]}: available key precedes the event key")
        if relation == INCOMPARABLE:
            raise SignalContractError(f"{frame['signal_id'].iloc[position]}: available key is causally incomparable with the event key")
        assert relation in (BEFORE, EQUAL)
    for attribute in definition.attributes:
        _check_attribute(frame, attribute)
    _check_identity(frame)
    return _canonical_order(frame)


def _check_schema(signals: pd.DataFrame, definition: SignalDefinitionSpec) -> pd.DataFrame:
    if not isinstance(signals, pd.DataFrame):
        raise SignalContractError("signals must be a pandas DataFrame")
    forbidden = [
        column for column in signals.columns
        if str(column).lower() in _FORBIDDEN
        or (str(column).lower().startswith(ATTRIBUTE_PREFIX) and str(column).lower()[len(ATTRIBUTE_PREFIX):] in _FORBIDDEN)
    ]
    if forbidden:
        raise SignalContractError(f"signals contain execution fields {forbidden}; a Signal describes an event, not a trade")
    missing = [column for column in SIGNAL_COLUMNS if column not in signals.columns]
    if missing:
        raise SignalContractError(f"signals missing required columns: {missing}")
    declared = {attribute.column for attribute in definition.attributes}
    extra = [
        column for column in signals.columns
        if column not in SIGNAL_COLUMNS and column not in OPTIONAL_SIGNAL_COLUMNS and column not in declared
    ]
    if extra:
        raise SignalContractError(f"signals have undeclared columns {extra}; extensions must be declared attr_* columns")
    frame = signals.reset_index(drop=True).copy()
    if "source_refs" not in frame.columns:
        frame["source_refs"] = [()] * len(frame)
    return frame


def _check_envelope(frame: pd.DataFrame, definition: SignalDefinitionSpec) -> None:
    for column in ("signal_id", "instrument_id"):
        if not all(isinstance(value, str) and value.strip() for value in frame[column]):
            raise SignalContractError(f"{column} must contain non-empty strings")
    if (frame["signal_type"] != definition.signal_type).any():
        raise SignalContractError(f"signals contain a signal_type other than {definition.signal_type!r}")
    if (frame["definition_version"] != definition.definition_version).any():
        raise SignalContractError(f"signals contain a definition_version other than {definition.definition_version!r}")
    for value in frame["subject_id"]:
        if not isinstance(value, str) or not value or value != value.strip() or "\n" in value or "\r" in value:
            raise SignalContractError(f"subject_id must be a non-empty trimmed single-line string, got {value!r}")
    for column in ("event_at", "available_at"):
        frame[column] = _utc_column(frame[column], column)
    for prefix in ("event", "available"):
        frame[f"{prefix}_seq"] = _int_column(frame[f"{prefix}_seq"], f"{prefix}_seq")
        frame[f"{prefix}_seq_domain"] = frame[f"{prefix}_seq_domain"].astype(object).where(frame[f"{prefix}_seq_domain"].notna(), None)
    scope, contract = frame["contract_scope"], frame["contract"]
    if not scope.isin(CONTRACT_SCOPES).all():
        raise SignalContractError(f"contract_scope must be one of {CONTRACT_SCOPES}, got {scope[~scope.isin(CONTRACT_SCOPES)].iloc[0]!r}")
    present = contract.map(lambda value: isinstance(value, str) and bool(value.strip()))
    if (scope.eq(SPECIFIC) & ~present).any():
        raise SignalContractError("SPECIFIC scope requires a non-empty contract")
    if (scope.eq(AGNOSTIC) & contract.notna()).any():
        raise SignalContractError("AGNOSTIC scope must have a null contract")
    frame["contract"] = contract.astype(object).where(contract.notna(), None)
    directions = frame["direction"].astype(object).where(frame["direction"].notna(), None)
    if not definition.allowed_directions:
        if directions.notna().any():
            raise SignalContractError(f"{definition.signal_type} is undirected: direction must be null")
    else:
        bad = [value for value in directions if value not in definition.allowed_directions]
        if bad:
            raise SignalContractError(
                f"{definition.signal_type}: direction must be one of {definition.allowed_directions}, got {bad[0]!r}"
            )
    frame["direction"] = directions
    if frame["trigger_ref"].isna().any():
        raise SignalContractError("trigger_ref is required for every signal")


def _causal_keys(frame: pd.DataFrame, prefix: str) -> list[CausalKey]:
    """Per-row M7A CausalKeys (validates the co-null domain/sequence pair)."""
    return [
        CausalKey(at, domain, None if pd.isna(seq) else int(seq))
        for at, domain, seq in zip(frame[f"{prefix}_at"], frame[f"{prefix}_seq_domain"], frame[f"{prefix}_seq"])
    ]


def _check_identity(frame: pd.DataFrame) -> None:
    if frame["signal_id"].duplicated().any():
        raise SignalContractError(f"duplicate signal_id {frame.loc[frame['signal_id'].duplicated(), 'signal_id'].iloc[0]}")
    expected = assign_signal_ids(frame)["signal_id"]
    wrong = (expected != frame["signal_id"]).to_numpy()
    if wrong.any():
        raise SignalContractError(f"{_first(frame, wrong)}: signal_id does not match its natural key")
    semantic = pd.Series([
        json.dumps([
            row.signal_type, row.definition_version, row.instrument_id, row.contract_scope, row.contract,
            row.subject_id, canonical_time(row.event_at), row.event_seq_domain,
            None if pd.isna(row.event_seq) else int(row.event_seq), row.direction,
        ])
        for row in frame.itertuples(index=False)
    ])
    repeated = semantic.duplicated().to_numpy()
    if repeated.any():
        raise SignalContractError(
            f"{_first(frame, repeated)}: a second signal for the same semantic event "
            "(type, version, instrument, contract, subject, event key, direction)"
        )


def _canonical_order(frame: pd.DataFrame) -> pd.DataFrame:
    order = np.lexsort((
        _ranks(frame["signal_id"]),
        _ranks(frame["direction"]),
        _ranks(frame["subject_id"]),
        _ranks(frame["contract"]),
        _ranks(frame["contract_scope"]),
        _ranks(frame["instrument_id"]),
        _ranks(frame["signal_type"]),
        _seq_sort(frame["event_seq"]),
        _ranks(frame["event_seq_domain"]),
        _ns(frame["event_at"]),
        _seq_sort(frame["available_seq"]),
        _ranks(frame["available_seq_domain"]),
        _ns(frame["available_at"]),
    ))
    return frame.iloc[order].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Signal-local DataFrame plumbing
# ---------------------------------------------------------------------------


def _utc_column(values: pd.Series, name: str) -> pd.Series:
    series = pd.Series(values)
    if series.isna().any():
        raise SignalContractError(f"{name} contains missing timestamps")
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        return series.dt.tz_convert("UTC").dt.as_unit("ns")
    if series.dtype == object and all(getattr(value, "tzinfo", None) is not None for value in series):
        return pd.to_datetime(series, utc=True).dt.as_unit("ns")
    raise SignalContractError(f"{name} must contain timezone-aware timestamps")


def _int_column(values: pd.Series, name: str) -> pd.Series:
    series = pd.Series(values)
    if pd.api.types.is_bool_dtype(series.dtype) or any(isinstance(value, (bool, np.bool_, str)) for value in series.dropna()):
        raise SignalContractError(f"{name} must contain integers or nulls")
    try:
        return pd.Series(pd.array(series.to_numpy(dtype=object), dtype="Int64"), index=series.index)
    except (TypeError, ValueError) as exc:
        raise SignalContractError(f"{name} must contain integers or nulls") from exc


def _check_attribute(frame: pd.DataFrame, attribute: AttributeSpec) -> None:
    column = attribute.column
    if column not in frame.columns:
        if attribute.required:
            raise SignalContractError(f"required attribute column {column} is missing")
        return
    series = frame[column]
    if attribute.required and series.isna().any():
        raise SignalContractError(f"required attribute {column} contains nulls")
    if series.isna().all():
        return
    dtype = series.dtype
    values = series.dropna()
    ok = {
        "Int64": pd.api.types.is_integer_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype),
        "Float64": pd.api.types.is_float_dtype(dtype),
        "boolean": pd.api.types.is_bool_dtype(dtype),
        "string": (pd.api.types.is_string_dtype(dtype) or dtype == object) and all(isinstance(value, str) for value in values),
        "datetime": isinstance(dtype, pd.DatetimeTZDtype),
    }[attribute.dtype]
    if not ok:
        raise SignalContractError(f"attribute {column} must have dtype {attribute.dtype}, got {dtype}")


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
    return None if value is None or (not isinstance(value, str) and pd.isna(value)) else value


def _first(frame: pd.DataFrame, mask: Any) -> str:
    return str(frame["signal_id"].iloc[int(np.flatnonzero(np.asarray(mask))[0])])
