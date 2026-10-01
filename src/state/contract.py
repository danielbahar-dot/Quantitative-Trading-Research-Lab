"""Generic State contract (M7A): an event-based state-transition log.

Specification: ``docs/project/M7_STATE_SIGNAL_CONTRACTS_SPEC.md`` §0
(D-129, as amended by the M7A validation decisions, D-130).

M7 owns the *envelope* only: schema, membership, causal and identity
validation, ordering, and replay.  It owns no lifecycle vocabulary, no
transition conditions, no reset/expiry rules and no mapping from
interactions to states; those belong to the module that declares a
``StateNamespaceSpec``.

Causal model (not bar-specific):

- A causal key is ``(at, seq_domain, seq)``: a tz-aware timestamp plus an
  optional sequence that is meaningful only inside its sequence domain
  (e.g. one feed).  ``seq_domain`` and ``seq`` are co-null.
- ``compare_causal(a, b)`` returns ``BEFORE``, ``AFTER``, ``EQUAL`` or
  ``INCOMPARABLE``.  Timestamps order first.  At equal timestamps,
  sequences order only when both are present in the same domain; equal
  domain + sequence, or both unsequenced, is ``EQUAL``; anything else is
  ``INCOMPARABLE``.  Nothing is ever ordered without evidence.
- Generic consumers are strict: a key is visible at a decision point only
  if it is ``BEFORE`` it, so the observation that creates a transition (or
  makes an entity known) can never consume it.  The single exception is
  ``materialize_state_to_bars``: under ``BAR_END`` labels the previous
  ``bar_end`` equal to the next ``bar_start`` is a real interval boundary
  (``bar_start >= available_at``, the M5/M6 rule).

Canonical storage is the transition log; ``materialize_state_to_*`` derive
views.  Invalid input raises ``StateContractError``; there are no runtime
``INVALID_*`` statuses.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

SPECIFIC = "SPECIFIC"
AGNOSTIC = "AGNOSTIC"
CONTRACT_SCOPES = (SPECIFIC, AGNOSTIC)

BEFORE = "BEFORE"
AFTER = "AFTER"
EQUAL = "EQUAL"
INCOMPARABLE = "INCOMPARABLE"

TRANSITION_COLUMNS = (
    "transition_id",
    "namespace",
    "entity_id",
    "previous_state",
    "new_state",
    "transition_at",
    "transition_seq_domain",
    "transition_seq",
    "available_at",
    "available_seq_domain",
    "available_seq",
    "instrument_id",
    "contract_scope",
    "contract",
    "definition_version",
    "trigger_ref",
)
OPTIONAL_TRANSITION_COLUMNS = ("source_refs", "reason_code")
ENTITY_COLUMNS = (
    "entity_id",
    "available_at",
    "valid_from",
    "valid_until",
    "instrument_id",
    "contract_scope",
    "contract",
)
OBSERVATION_COLUMNS = ("observation_at", "decision_at")
ATTRIBUTE_PREFIX = "attr_"
ATTRIBUTE_DTYPES = ("Int64", "Float64", "boolean", "string", "datetime")
TRANSITION_ID_PREFIX = "st_"

_NAMESPACE_RE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*")
_LOWER_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")
_UPPER_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9_]*")
_DOMAIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")

_STRICT = "strict"          # K BEFORE D: every generic consumer
_BAR_BOUNDARY = "boundary"  # K BEFORE D, or equal ``at`` with both keys unsequenced (bar wrapper only)


class StateContractError(ValueError):
    """Raised for any malformed state specification, entity or transition."""


# ---------------------------------------------------------------------------
# Specifications
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttributeSpec:
    """A module-declared typed ``attr_<name>`` column."""

    name: str
    dtype: str
    required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _LOWER_TOKEN_RE.fullmatch(self.name):
            raise StateContractError(f"attribute name must be a lowercase token, got {self.name!r}")
        if self.dtype not in ATTRIBUTE_DTYPES:
            raise StateContractError(f"attribute {self.name!r}: dtype must be one of {ATTRIBUTE_DTYPES}")

    @property
    def column(self) -> str:
        return f"{ATTRIBUTE_PREFIX}{self.name}"


@dataclass(frozen=True, kw_only=True)
class StateNamespaceSpec:
    """Module-owned vocabulary and transition graph for one state namespace.

    ``initial_state`` holds from the moment an entity becomes applicable until
    its first real transition; no synthetic creation transition exists.
    Terminal states have no outgoing edges: a namespace that wants a state to
    be exitable does not declare it terminal.
    """

    namespace: str
    entity_kind: str
    initial_state: str
    allowed_states: tuple[str, ...]
    allowed_transitions: frozenset[tuple[str, str]]
    definition_version: str
    terminal_states: tuple[str, ...] = ()
    attributes: tuple[AttributeSpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_states", tuple(self.allowed_states))
        object.__setattr__(self, "allowed_transitions", frozenset(tuple(edge) for edge in self.allowed_transitions))
        object.__setattr__(self, "terminal_states", tuple(self.terminal_states))
        object.__setattr__(self, "attributes", tuple(self.attributes))
        if not isinstance(self.namespace, str) or not _NAMESPACE_RE.fullmatch(self.namespace):
            raise StateContractError(f"namespace must be dotted lowercase tokens, got {self.namespace!r}")
        if not isinstance(self.entity_kind, str) or not _LOWER_TOKEN_RE.fullmatch(self.entity_kind):
            raise StateContractError(f"entity_kind must be a lowercase token, got {self.entity_kind!r}")
        if not isinstance(self.definition_version, str) or not self.definition_version.strip():
            raise StateContractError("definition_version must be a non-empty string")
        states = self.allowed_states
        if not states or len(set(states)) != len(states):
            raise StateContractError(f"{self.namespace}: allowed_states must be non-empty and unique")
        for state in states:
            if not isinstance(state, str) or not _UPPER_TOKEN_RE.fullmatch(state):
                raise StateContractError(f"{self.namespace}: state names must be uppercase tokens, got {state!r}")
        if self.initial_state not in states:
            raise StateContractError(f"{self.namespace}: initial_state {self.initial_state!r} is not an allowed state")
        for source, target in self.allowed_transitions:
            if source not in states or target not in states:
                raise StateContractError(f"{self.namespace}: edge {(source, target)} uses an undeclared state")
            if source == target:
                raise StateContractError(f"{self.namespace}: self transition {source} -> {target} is not allowed")
        unknown_terminals = set(self.terminal_states) - set(states)
        if unknown_terminals:
            raise StateContractError(f"{self.namespace}: terminal states {sorted(unknown_terminals)} are not allowed states")
        exits = sorted(edge for edge in self.allowed_transitions if edge[0] in self.terminal_states)
        if exits:
            raise StateContractError(f"{self.namespace}: terminal states cannot have outgoing edges {exits}")
        names = [attribute.name for attribute in self.attributes]
        if len(set(names)) != len(names):
            raise StateContractError(f"{self.namespace}: duplicate attribute names")


# ---------------------------------------------------------------------------
# Causal keys
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CausalKey:
    """``(at, seq_domain, seq)``; ``seq_domain`` and ``seq`` are co-null."""

    at: pd.Timestamp
    seq_domain: str | None = None
    seq: int | None = None

    def __post_init__(self) -> None:
        stamp = pd.Timestamp(self.at)
        if stamp is pd.NaT or pd.isna(stamp) or stamp.tzinfo is None:
            raise StateContractError(f"causal key timestamp must be timezone-aware, got {self.at!r}")
        domain = None if self.seq_domain is None or pd.isna(self.seq_domain) else self.seq_domain
        seq = None if self.seq is None or pd.isna(self.seq) else _as_int(self.seq, "seq")
        if (domain is None) != (seq is None):
            raise StateContractError("seq_domain and seq must be both null or both present")
        if domain is not None and (not isinstance(domain, str) or not _DOMAIN_RE.fullmatch(domain)):
            raise StateContractError(f"seq_domain must be a non-empty token, got {domain!r}")
        object.__setattr__(self, "at", stamp)
        object.__setattr__(self, "seq_domain", domain)
        object.__setattr__(self, "seq", seq)


def compare_causal(a: CausalKey, b: CausalKey) -> str:
    """Return ``BEFORE``, ``AFTER``, ``EQUAL`` or ``INCOMPARABLE`` for ``a`` versus ``b``."""
    if a.at != b.at:
        return BEFORE if a.at < b.at else AFTER
    if a.seq is None and b.seq is None:
        return EQUAL
    if a.seq is None or b.seq is None or a.seq_domain != b.seq_domain:
        return INCOMPARABLE
    if a.seq == b.seq:
        return EQUAL
    return BEFORE if a.seq < b.seq else AFTER


def causal_precedes(a: CausalKey, b: CausalKey) -> bool:
    """Strict causal precedence ``a ≺ b`` (``BEFORE``)."""
    return compare_causal(a, b) == BEFORE


@dataclass(frozen=True)
class _Keys:
    """Vectorized causal keys: ns timestamps, presence mask, domain, sequence."""

    ns: np.ndarray
    has: np.ndarray
    dom: np.ndarray
    val: np.ndarray

    def take(self, index) -> "_Keys":
        return _Keys(self.ns[index], self.has[index], self.dom[index], self.val[index])

    def repeat(self, count: int) -> "_Keys":
        return _Keys(np.repeat(self.ns, count), np.repeat(self.has, count), np.repeat(self.dom, count), np.repeat(self.val, count))


def _before(a: _Keys, b: _Keys) -> np.ndarray:
    same_domain = a.has & b.has & (a.dom == b.dom)
    return (a.ns < b.ns) | ((a.ns == b.ns) & same_domain & (a.val < b.val))


def _equal(a: _Keys, b: _Keys) -> np.ndarray:
    both_null = ~a.has & ~b.has
    same = a.has & b.has & (a.dom == b.dom) & (a.val == b.val)
    return (a.ns == b.ns) & (both_null | same)


def _visible(key: _Keys, decision: _Keys, mode: str) -> np.ndarray:
    if mode == _STRICT:
        return _before(key, decision)
    if mode == _BAR_BOUNDARY:
        return _before(key, decision) | ((key.ns == decision.ns) & ~key.has & ~decision.has)
    raise AssertionError(mode)


def _frame_keys(at: pd.Series, domain: pd.Series, seq: pd.Series) -> _Keys:
    ns = _ns(pd.DatetimeIndex(at))
    seq_series = pd.Series(seq).astype("Int64")
    has = seq_series.notna().to_numpy()
    dom = np.array([value if isinstance(value, str) else "" for value in pd.Series(domain)], dtype=object)
    return _Keys(ns, has, dom, seq_series.fillna(0).to_numpy(dtype=np.int64))


def _scalar_keys(key: CausalKey) -> _Keys:
    return _Keys(
        np.array([key.at.as_unit("ns").value]),
        np.array([key.seq is not None]),
        np.array([key.seq_domain or ""], dtype=object),
        np.array([key.seq or 0], dtype=np.int64),
    )


# ---------------------------------------------------------------------------
# Source references and identity
# ---------------------------------------------------------------------------


def canonical_time(value: Any) -> str:
    """Canonical UTC text with nanoseconds, e.g. ``2024-12-10T14:31:00.000000000Z``."""
    stamp = pd.Timestamp(value)
    if stamp is pd.NaT or pd.isna(stamp):
        raise StateContractError("canonical_time requires a timestamp, got NaT")
    if stamp.tzinfo is None:
        raise StateContractError(f"timestamp {stamp} must be timezone-aware")
    utc = stamp.tz_convert("UTC")
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond * 1000 + utc.nanosecond:09d}Z"


@dataclass(frozen=True, order=True)
class SourceRef:
    """Typed, stable provenance reference serialized as ``KIND:key``.

    ``kind`` is an uppercase token from an open set (e.g. ``M5_CONTEXT``,
    ``M6_INTERACTION``, ``TICK_INTERACTION``, ``TRADE``, ``QUOTE``,
    ``BOOK_EVENT``, ``STATE_TRANSITION``, ``SIGNAL``); new kinds need no
    change to State semantics.  ``key`` is a semantic identifier, never a
    DataFrame row position, path or temporary index.
    """

    kind: str
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not _UPPER_TOKEN_RE.fullmatch(self.kind):
            raise StateContractError(f"SourceRef kind must be an uppercase token, got {self.kind!r}")
        if not isinstance(self.key, str) or not self.key or self.key != self.key.strip() or "\n" in self.key:
            raise StateContractError(f"SourceRef key must be a non-empty trimmed single-line string, got {self.key!r}")

    @property
    def canonical(self) -> str:
        return f"{self.kind}:{self.key}"

    @classmethod
    def parse(cls, text: Any) -> "SourceRef":
        if isinstance(text, SourceRef):
            return text
        if not isinstance(text, str) or ":" not in text:
            raise StateContractError(f"source ref must be 'KIND:key', got {text!r}")
        kind, key = text.split(":", 1)
        return cls(kind, key)

    @classmethod
    def for_event(cls, kind: str, subject: str, at: Any, seq_domain: Any = None, seq: Any = None) -> "SourceRef":
        """Reference a timestamped event: ``subject@<canonical UTC>[#<domain>:<seq>]``."""
        if not isinstance(subject, str) or not subject:
            raise StateContractError("SourceRef.for_event requires a non-empty subject")
        key = CausalKey(at, seq_domain, seq)
        text = f"{subject}@{canonical_time(key.at)}"
        if key.seq is not None:
            text += f"#{key.seq_domain}:{key.seq}"
        return cls(kind, text)


def canonical_ref(ref: SourceRef | str) -> str:
    """Validate one reference and return its canonical ``KIND:key`` text."""
    return SourceRef.parse(ref).canonical


def canonical_source_refs(refs: Any) -> tuple[str, ...]:
    """Canonical supporting provenance: sorted, unique ``KIND:key`` strings (may be empty)."""
    if refs is None or (not isinstance(refs, (list, tuple, np.ndarray, str, SourceRef)) and pd.isna(refs)):
        return ()
    if isinstance(refs, (str, SourceRef)):
        refs = [refs]
    if not isinstance(refs, (list, tuple, np.ndarray)):
        raise StateContractError(f"source_refs must be a sequence of 'KIND:key' references, got {type(refs).__name__}")
    return tuple(sorted({canonical_ref(ref) for ref in refs}))


def transition_id(
    *,
    namespace: str,
    definition_version: str,
    entity_id: str,
    previous_state: str,
    new_state: str,
    transition_at: Any,
    transition_seq_domain: Any = None,
    transition_seq: Any = None,
    trigger_ref: SourceRef | str,
    source_refs: Any = (),
) -> str:
    """Deterministic id: ``st_`` + full SHA-256 of the canonical natural key.

    The key covers namespace, version, entity, previous/new state, the
    transition causal key (UTC time, sequence domain and sequence), the
    trigger reference and the canonical supporting references, so timezone
    representation and reference input order never change the id.
    """
    key = CausalKey(transition_at, transition_seq_domain, transition_seq)
    natural_key = [
        namespace,
        definition_version,
        entity_id,
        previous_state,
        new_state,
        canonical_time(key.at),
        key.seq_domain,
        key.seq,
        canonical_ref(trigger_ref),
        list(canonical_source_refs(source_refs)),
    ]
    payload = json.dumps(natural_key, ensure_ascii=False, separators=(",", ":"))
    return TRANSITION_ID_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assign_transition_ids(transitions: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with canonical references and computed ``transition_id``."""
    frame = transitions.copy()
    frame["trigger_ref"] = [canonical_ref(value) for value in frame["trigger_ref"]]
    frame["source_refs"] = [
        canonical_source_refs(value)
        for value in (frame["source_refs"] if "source_refs" in frame.columns else [()] * len(frame))
    ]
    domains = frame["transition_seq_domain"] if "transition_seq_domain" in frame.columns else [None] * len(frame)
    seqs = frame["transition_seq"] if "transition_seq" in frame.columns else [None] * len(frame)
    frame["transition_id"] = [
        transition_id(
            namespace=row.namespace, definition_version=row.definition_version, entity_id=row.entity_id,
            previous_state=row.previous_state, new_state=row.new_state, transition_at=row.transition_at,
            transition_seq_domain=domain, transition_seq=seq, trigger_ref=row.trigger_ref, source_refs=row.source_refs,
        )
        for row, domain, seq in zip(frame.itertuples(index=False), domains, seqs)
    ]
    return frame


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def prepare_entities(entities: pd.DataFrame) -> pd.DataFrame:
    """Validate the caller-provided entity applicability frame.

    Returns a copy indexed by ``entity_id`` with UTC timestamps and the
    nullable ``available_seq_domain`` / ``available_seq`` pair.
    """
    if not isinstance(entities, pd.DataFrame):
        raise StateContractError("entities must be a pandas DataFrame")
    missing = [column for column in ENTITY_COLUMNS if column not in entities.columns]
    if missing:
        raise StateContractError(f"entities missing required columns: {missing}")
    frame = entities.reset_index(drop=True).copy()
    _require_tokens(frame["entity_id"], "entity_id")
    if frame["entity_id"].duplicated().any():
        raise StateContractError(f"duplicate entity_id: {frame.loc[frame['entity_id'].duplicated(), 'entity_id'].iloc[0]!r}")
    frame["available_at"] = _tz_column(frame["available_at"], "entities.available_at", allow_null=False)
    frame["valid_from"] = _tz_column(frame["valid_from"], "entities.valid_from", allow_null=True)
    frame["valid_until"] = _tz_column(frame["valid_until"], "entities.valid_until", allow_null=True)
    frame["available_seq_domain"], frame["available_seq"] = _sequence_pair(
        frame.get("available_seq_domain"), frame.get("available_seq"), "entities.available", frame.index
    )
    bounded = frame["valid_until"].notna()
    if (bounded & frame["valid_from"].notna() & (frame["valid_until"] <= frame["valid_from"])).any():
        raise StateContractError("entities: valid_until must follow valid_from")
    if (bounded & (frame["valid_until"] < frame["available_at"])).any():
        raise StateContractError("entities: valid_until precedes available_at")
    _require_tokens(frame["instrument_id"], "entities.instrument_id")
    _check_scope(frame["contract_scope"], frame["contract"], "entities")
    return frame.set_index("entity_id", drop=False)


def validate_transitions(
    transitions: pd.DataFrame,
    spec: StateNamespaceSpec,
    entities: pd.DataFrame,
) -> pd.DataFrame:
    """Validate a transition log for one namespace; return it canonicalized and ordered.

    Validates the integrity, causality, provenance and replay consistency of
    the State transition log: the first transition leaves ``initial_state``,
    every later one leaves the actual preceding state, the preceding
    transition is causally available (``BEFORE``) to the next source event,
    and at most one transition exists per causal source event and per
    ``trigger_ref``.

    It does not independently re-evaluate whether the upstream trigger
    observation was eligible to interact with the entity: exact
    trigger-observation eligibility (tick vs bar geometry, decision instant,
    static window) is owned by the source feature/interaction module.  Only
    applicability checks valid for every observation type are applied (see
    ``_check_entities``).
    """
    if not isinstance(spec, StateNamespaceSpec):
        raise StateContractError("spec must be a StateNamespaceSpec")
    entity_frame = prepare_entities(entities)
    frame = _check_transition_schema(transitions, spec)
    if frame.empty:
        return frame
    t_keys = _frame_keys(frame["transition_at"], frame["transition_seq_domain"], frame["transition_seq"])
    a_keys = _frame_keys(frame["available_at"], frame["available_seq_domain"], frame["available_seq"])
    _check_states(frame, spec)
    not_later = _before(t_keys, a_keys) | _equal(t_keys, a_keys)
    if not not_later.all():
        early = _before(a_keys, t_keys)
        reason = "available key precedes transition key" if early[~not_later].any() else "available key is causally incomparable with transition key"
        raise StateContractError(f"{_first_id(frame, ~not_later)}: {reason}")
    _check_entities(frame, entity_frame, t_keys)
    _check_ids(frame)
    _check_chains(frame, spec, t_keys, a_keys)
    return _canonical_order(frame)


def _check_transition_schema(transitions: pd.DataFrame, spec: StateNamespaceSpec) -> pd.DataFrame:
    if not isinstance(transitions, pd.DataFrame):
        raise StateContractError("transitions must be a pandas DataFrame")
    missing = [column for column in TRANSITION_COLUMNS if column not in transitions.columns]
    if missing:
        raise StateContractError(f"transitions missing required columns: {missing}")
    declared = {attribute.column: attribute for attribute in spec.attributes}
    extra = [
        column for column in transitions.columns
        if column not in TRANSITION_COLUMNS and column not in OPTIONAL_TRANSITION_COLUMNS and column not in declared
    ]
    if extra:
        raise StateContractError(f"transitions have undeclared columns {extra}; extensions must be declared attr_* columns")
    frame = transitions.reset_index(drop=True).copy()
    for column in ("transition_id", "entity_id", "previous_state", "new_state", "instrument_id"):
        _require_tokens(frame[column], column)
    if (frame["namespace"] != spec.namespace).any():
        raise StateContractError(f"transitions contain a namespace other than {spec.namespace!r}")
    if (frame["definition_version"] != spec.definition_version).any():
        raise StateContractError(f"transitions contain a definition_version other than {spec.definition_version!r}")
    frame["transition_at"] = _tz_column(frame["transition_at"], "transition_at", allow_null=False)
    frame["available_at"] = _tz_column(frame["available_at"], "available_at", allow_null=False)
    frame["transition_seq_domain"], frame["transition_seq"] = _sequence_pair(
        frame["transition_seq_domain"], frame["transition_seq"], "transition", frame.index
    )
    frame["available_seq_domain"], frame["available_seq"] = _sequence_pair(
        frame["available_seq_domain"], frame["available_seq"], "available", frame.index
    )
    _check_scope(frame["contract_scope"], frame["contract"], "transitions")
    if frame["trigger_ref"].isna().any():
        raise StateContractError("trigger_ref is required for every transition")
    frame["trigger_ref"] = [canonical_ref(value) for value in frame["trigger_ref"]]
    frame["source_refs"] = [
        canonical_source_refs(value)
        for value in (frame["source_refs"] if "source_refs" in frame.columns else [()] * len(frame))
    ]
    if "reason_code" in frame.columns:
        codes = frame["reason_code"].dropna()
        if not all(isinstance(code, str) and code.strip() for code in codes):
            raise StateContractError("reason_code must be null or a non-empty string")
    for attribute in spec.attributes:
        _check_attribute(frame, attribute)
    return frame


def _check_states(frame: pd.DataFrame, spec: StateNamespaceSpec) -> None:
    allowed = set(spec.allowed_states)
    for column in ("previous_state", "new_state"):
        unknown = sorted(set(frame[column]) - allowed)
        if unknown:
            raise StateContractError(f"{spec.namespace}: {column} values {unknown} are not allowed states")
    same = (frame["previous_state"] == frame["new_state"]).to_numpy()
    if same.any():
        raise StateContractError(f"{_first_id(frame, same)}: self transition is not allowed")
    terminal = frame["previous_state"].isin(spec.terminal_states).to_numpy()
    if terminal.any():
        raise StateContractError(f"{_first_id(frame, terminal)}: transition out of terminal state")
    edges = list(zip(frame["previous_state"], frame["new_state"]))
    illegal = np.array([edge not in spec.allowed_transitions for edge in edges])
    if illegal.any():
        position = int(np.flatnonzero(illegal)[0])
        raise StateContractError(f"{frame['transition_id'].iloc[position]}: edge {edges[position]} is not allowed in {spec.namespace}")


def _check_entities(frame: pd.DataFrame, entities: pd.DataFrame, t_keys: _Keys) -> None:
    """Entity identity, contract consistency, and universally valid applicability.

    Retained (true for any trigger observation, tick or bar of any size):
    the entity is causally known strictly before the transition key, and
    ``transition_at >= valid_from`` (an observation's decision instant never
    follows its event time).  Deliberately *not* checked: the exact
    ``valid_from <= decision < valid_until`` window and any upper bound on
    ``transition_at`` (a bar may end after ``valid_until`` while its start was
    still valid).  Those are upstream trigger-eligibility rules.
    """
    unknown = ~frame["entity_id"].isin(entities.index)
    if unknown.any():
        raise StateContractError(f"transitions reference unknown entity {frame.loc[unknown, 'entity_id'].iloc[0]!r}")
    entity = entities.loc[frame["entity_id"]]
    for column in ("instrument_id", "contract_scope"):
        if (entity[column].to_numpy() != frame[column].to_numpy()).any():
            raise StateContractError(f"transition {column} differs from its entity")
    same_contract = (entity["contract"].isna().to_numpy() & frame["contract"].isna().to_numpy()) | (
        entity["contract"].to_numpy() == frame["contract"].to_numpy()
    )
    if not same_contract.all():
        raise StateContractError(f"{_first_id(frame, ~same_contract)}: transition contract differs from its entity (no contract bridging)")
    e_keys = _frame_keys(entity["available_at"], entity["available_seq_domain"], entity["available_seq"])
    # the event that makes the entity known (or a simultaneous/incomparable one) cannot transition it
    known = _before(e_keys, t_keys)
    if not known.all():
        raise StateContractError(f"{_first_id(frame, ~known)}: entity is not causally known before the transition's source event")
    valid_from = pd.DatetimeIndex(entity["valid_from"])
    transition_at = pd.DatetimeIndex(frame["transition_at"])
    before = np.asarray(valid_from.notna() & (transition_at < valid_from))
    if before.any():
        raise StateContractError(f"{_first_id(frame, before)}: transition precedes the entity's valid_from")


def _check_ids(frame: pd.DataFrame) -> None:
    if frame["transition_id"].duplicated().any():
        raise StateContractError(f"duplicate transition_id {frame.loc[frame['transition_id'].duplicated(), 'transition_id'].iloc[0]}")
    expected = assign_transition_ids(frame)["transition_id"]
    wrong = (expected != frame["transition_id"]).to_numpy()
    if wrong.any():
        raise StateContractError(f"{_first_id(frame, wrong)}: transition_id does not match its natural key")
    repeated = frame.duplicated(["entity_id", "trigger_ref"]).to_numpy()
    if repeated.any():
        raise StateContractError(f"{_first_id(frame, repeated)}: a second transition for the same entity_id + namespace + trigger_ref")


def _check_chains(frame: pd.DataFrame, spec: StateNamespaceSpec, t_keys: _Keys, a_keys: _Keys) -> None:
    order = _chain_positions(frame)
    entity_ids = frame["entity_id"].to_numpy()[order]
    previous = frame["previous_state"].to_numpy()[order]
    new = frame["new_state"].to_numpy()[order]
    same_entity = np.r_[False, entity_ids[1:] == entity_ids[:-1]]
    cur = order[same_entity]
    prev = order[np.flatnonzero(same_entity) - 1]
    # an order-dependent chain needs strict causal precedence between consecutive source events
    ordered = _before(t_keys.take(prev), t_keys.take(cur))
    if not ordered.all():
        raise StateContractError(
            f"{frame['transition_id'].iloc[cur[~ordered][0]]}: order-dependent transitions for one entity and namespace "
            "without causal precedence (same causal event, or simultaneous / incomparable keys)"
        )
    first = ~same_entity
    if (previous[first] != spec.initial_state).any():
        position = order[np.flatnonzero(first & (previous != spec.initial_state))[0]]
        raise StateContractError(f"{frame['transition_id'].iloc[position]}: an entity's first transition must leave initial_state {spec.initial_state!r}")
    if not same_entity.any():
        return
    broken = previous[same_entity] != new[np.flatnonzero(same_entity) - 1]
    if broken.any():
        raise StateContractError(f"{frame['transition_id'].iloc[cur[broken][0]]}: previous_state does not match the entity's replayed history")
    consumable = _before(a_keys.take(prev), t_keys.take(cur))
    if not consumable.all():
        raise StateContractError(
            f"{frame['transition_id'].iloc[cur[~consumable][0]]}: source event cannot consume the previous state "
            "(the previous transition is not causally available to it)"
        )


def _chain_positions(frame: pd.DataFrame) -> np.ndarray:
    """Positions ordered by entity, then transition key (null sequences first)."""
    seq = frame["transition_seq"].astype("Float64").fillna(-np.inf).to_numpy(dtype=float)
    return np.lexsort((
        seq,
        _codes(frame["transition_seq_domain"]),
        _ns(pd.DatetimeIndex(frame["transition_at"])),
        _codes(frame["entity_id"]),
    ))


def _canonical_order(frame: pd.DataFrame) -> pd.DataFrame:
    order = np.lexsort((
        _codes(frame["transition_id"]),
        _codes(frame["entity_id"]),
        _codes(frame["namespace"]),
        frame["transition_seq"].astype("Float64").fillna(-np.inf).to_numpy(dtype=float),
        _codes(frame["transition_seq_domain"]),
        _ns(pd.DatetimeIndex(frame["transition_at"])),
        frame["available_seq"].astype("Float64").fillna(-np.inf).to_numpy(dtype=float),
        _codes(frame["available_seq_domain"]),
        _ns(pd.DatetimeIndex(frame["available_at"])),
    ))
    return frame.iloc[order].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Replay / materialization
# ---------------------------------------------------------------------------


def state_as_of(
    transitions: pd.DataFrame,
    spec: StateNamespaceSpec,
    entities: pd.DataFrame,
    as_of_at: Any,
    *,
    as_of_seq_domain: Any = None,
    as_of_seq: Any = None,
) -> pd.DataFrame:
    """State available **immediately before** the query causal point.

    Strict: an entity or transition becoming available exactly at the query
    key is not visible there.  ``state`` is ``<NA>`` where the entity is not
    applicable (not yet known, decision timestamp before ``valid_from`` or
    at/after ``valid_until``); ``initial_state`` before its first visible
    transition; otherwise the latest visible transition.
    """
    log = validate_transitions(transitions, spec, entities)
    entity_frame = prepare_entities(entities)
    query = _scalar_keys(CausalKey(as_of_at, as_of_seq_domain, as_of_seq))
    count = len(entity_frame)
    e_keys = _frame_keys(entity_frame["available_at"], entity_frame["available_seq_domain"], entity_frame["available_seq"])
    applicable = _visible(e_keys, query.repeat(count), _STRICT)
    applicable &= _window_mask(entity_frame, pd.DatetimeIndex([pd.Timestamp(as_of_at)] * count))

    visible_log = log
    if not log.empty:
        a_keys = _frame_keys(log["available_at"], log["available_seq_domain"], log["available_seq"])
        visible_log = log.loc[_visible(a_keys, query.repeat(len(log)), _STRICT)]
    latest = _latest_by_entity(visible_log)
    states = pd.array([pd.NA] * count, dtype="string")
    ids = pd.array([pd.NA] * count, dtype="string")
    for position, entity_id in enumerate(entity_frame["entity_id"]):
        if not applicable[position]:
            continue
        row = latest.get(entity_id)
        states[position] = spec.initial_state if row is None else row[0]
        ids[position] = pd.NA if row is None else row[1]
    return pd.DataFrame({
        "entity_id": entity_frame["entity_id"].to_numpy(),
        "namespace": spec.namespace,
        "applicable": applicable,
        "state": states,
        "transition_id": ids,
    })


def materialize_state_to_observations(
    transitions: pd.DataFrame,
    spec: StateNamespaceSpec,
    entities: pd.DataFrame,
    observations: pd.DataFrame,
) -> pd.DataFrame:
    """Generic core: state visible to each observation at its decision key (strict).

    ``observations`` has ``observation_at`` / ``decision_at`` (tz-aware) and
    optional ``observation_seq_domain`` / ``observation_seq`` and
    ``decision_seq_domain`` / ``decision_seq`` pairs.  One output row per
    (observation, applicable entity).  An entity or transition is visible iff
    its availability key is ``BEFORE`` the decision key, so the observation
    that caused a transition never sees it.
    """
    return _materialize(transitions, spec, entities, observations, _STRICT)


def materialize_state_to_bars(
    transitions: pd.DataFrame,
    spec: StateNamespaceSpec,
    entities: pd.DataFrame,
    bars: pd.DataFrame | pd.DatetimeIndex,
    *,
    bar_interval: Any = None,
) -> pd.DataFrame:
    """``BAR_END`` convenience wrapper over the observation materializer.

    Each bar is an observation with ``observation_at = bar_end`` and
    ``decision_at = bar_start`` (sequences null).  ``bar_start`` comes from a
    ``bar_start`` column when present, otherwise from an explicit
    ``bar_interval``; there is no default timeframe.  Only this wrapper
    applies the bar-boundary convention: a previous ``bar_end`` equal to the
    next ``bar_start`` is a real interval boundary, so a bar sees state with
    ``available_at <= bar_start`` (the M5/M6 rule) and never sees a
    transition caused by itself.
    """
    index = bars if isinstance(bars, pd.DatetimeIndex) else getattr(bars, "index", None)
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise StateContractError("bars must have a timezone-aware DatetimeIndex of bar-end labels")
    if index.has_duplicates:
        raise StateContractError("bars contain duplicate timestamps")
    interval = None
    if bar_interval is not None:
        interval = pd.Timedelta(bar_interval)
        if interval <= pd.Timedelta(0):
            raise StateContractError("bar_interval must be positive")
    if isinstance(bars, pd.DataFrame) and "bar_start" in bars.columns:
        bar_start = pd.DatetimeIndex(_tz_column(bars["bar_start"], "bar_start", allow_null=False)).tz_convert(index.tz)
        if interval is not None and ((index - bar_start) != interval).any():
            raise StateContractError("bar_start column and bar_interval disagree")
    elif interval is not None:
        bar_start = index - interval
    else:
        raise StateContractError("materialize_state_to_bars needs a bar_start column or an explicit bar_interval")
    if (bar_start >= index).any():
        raise StateContractError("bar_start must precede bar_end")
    observations = pd.DataFrame({"observation_at": index, "decision_at": bar_start})
    out = _materialize(transitions, spec, entities, observations, _BAR_BOUNDARY)
    out = out.rename(columns={"observation_at": "bar_end", "decision_at": "bar_start"})
    return out[["bar_end", "bar_start", "entity_id", "namespace", "state", "transition_id"]]


def _materialize(transitions, spec, entities, observations, mode: str) -> pd.DataFrame:
    log = validate_transitions(transitions, spec, entities)
    entity_frame = prepare_entities(entities)
    output_tz = _input_tz(observations, "observation_at")
    obs = _prepare_observations(observations)
    d_keys = _frame_keys(obs["decision_at"], obs["decision_seq_domain"], obs["decision_seq"])
    order = np.argsort(d_keys.ns, kind="mergesort")
    sorted_d = d_keys.ns[order]
    chains = {entity_id: group for entity_id, group in log.groupby("entity_id", sort=False)} if not log.empty else {}

    parts: list[pd.DataFrame] = []
    for entity in entity_frame.itertuples(index=False):
        start_ns = _ns(pd.DatetimeIndex([entity.available_at]))[0]
        if not pd.isna(entity.valid_from):
            start_ns = max(start_ns, _ns(pd.DatetimeIndex([entity.valid_from]))[0])
        lo = np.searchsorted(sorted_d, start_ns, side="left")
        hi = len(sorted_d) if pd.isna(entity.valid_until) else np.searchsorted(
            sorted_d, _ns(pd.DatetimeIndex([entity.valid_until]))[0], side="left"
        )
        candidates = order[lo:hi]
        if len(candidates) == 0:
            continue
        e_keys = _frame_keys(pd.Series([entity.available_at]), pd.Series([entity.available_seq_domain]),
                             pd.Series([entity.available_seq], dtype="Int64")).repeat(len(candidates))
        rows = candidates[_visible(e_keys, d_keys.take(candidates), mode)]
        if len(rows) == 0:
            continue
        state = np.full(len(rows), spec.initial_state, dtype=object)
        ids = np.full(len(rows), None, dtype=object)
        chain = chains.get(entity.entity_id)
        if chain is not None:
            chain = chain.iloc[_chain_positions(chain)]
            c_keys = _frame_keys(chain["available_at"], chain["available_seq_domain"], chain["available_seq"])
            decision = d_keys.take(rows)
            visible = _visible(
                _Keys(c_keys.ns[None, :], c_keys.has[None, :], c_keys.dom[None, :], c_keys.val[None, :]),
                _Keys(decision.ns[:, None], decision.has[:, None], decision.dom[:, None], decision.val[:, None]),
                mode,
            )
            count = visible.sum(axis=1)
            seen = count > 0
            state[seen] = chain["new_state"].to_numpy()[count[seen] - 1]
            ids[seen] = chain["transition_id"].to_numpy()[count[seen] - 1]
        selected = obs.iloc[rows].reset_index(drop=True)
        parts.append(pd.DataFrame({
            "observation_at": selected["observation_at"],
            "observation_seq_domain": selected["observation_seq_domain"],
            "observation_seq": selected["observation_seq"],
            "decision_at": selected["decision_at"],
            "decision_seq_domain": selected["decision_seq_domain"],
            "decision_seq": selected["decision_seq"],
            "entity_id": entity.entity_id,
            "namespace": spec.namespace,
            "state": pd.array(state, dtype="string"),
            "transition_id": pd.array(ids, dtype="string"),
        }))
    columns = [
        "observation_at", "observation_seq_domain", "observation_seq", "decision_at", "decision_seq_domain",
        "decision_seq", "entity_id", "namespace", "state", "transition_id",
    ]
    if not parts:
        return pd.DataFrame(columns=columns)
    out = pd.concat(parts, ignore_index=True)
    out["observation_at"] = out["observation_at"].dt.tz_convert(output_tz)
    out["decision_at"] = out["decision_at"].dt.tz_convert(output_tz)
    position = np.lexsort((
        _codes(out["entity_id"]),
        out["observation_seq"].astype("Float64").fillna(-np.inf).to_numpy(dtype=float),
        _codes(out["observation_seq_domain"]),
        _ns(pd.DatetimeIndex(out["observation_at"])),
    ))
    return out.iloc[position].reset_index(drop=True)[columns]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prepare_observations(observations: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(observations, pd.DataFrame):
        raise StateContractError("observations must be a pandas DataFrame")
    missing = [column for column in OBSERVATION_COLUMNS if column not in observations.columns]
    if missing:
        raise StateContractError(f"observations missing required columns: {missing}")
    obs = observations.reset_index(drop=True).copy()
    obs["observation_at"] = _tz_column(obs["observation_at"], "observation_at", allow_null=False)
    obs["decision_at"] = _tz_column(obs["decision_at"], "decision_at", allow_null=False)
    for prefix in ("observation", "decision"):
        obs[f"{prefix}_seq_domain"], obs[f"{prefix}_seq"] = _sequence_pair(
            obs.get(f"{prefix}_seq_domain"), obs.get(f"{prefix}_seq"), prefix, obs.index
        )
    o_keys = _frame_keys(obs["observation_at"], obs["observation_seq_domain"], obs["observation_seq"])
    d_keys = _frame_keys(obs["decision_at"], obs["decision_seq_domain"], obs["decision_seq"])
    if not (_before(d_keys, o_keys) | _equal(d_keys, o_keys)).all():
        raise StateContractError("an observation's decision key must not be later than (or incomparable with) the observation key")
    identity = pd.DataFrame({
        "at": o_keys.ns, "domain": obs["observation_seq_domain"].fillna(""),
        "seq": obs["observation_seq"].astype("Float64").fillna(np.nan),
    })
    if identity.duplicated().any():
        raise StateContractError("observations contain duplicate observation keys")
    return obs


def _latest_by_entity(log: pd.DataFrame) -> dict[str, tuple[str, str]]:
    latest: dict[str, tuple[str, str]] = {}
    if log.empty:
        return latest
    for entity_id, group in log.groupby("entity_id", sort=False):
        last = group.iloc[_chain_positions(group)].iloc[-1]
        latest[entity_id] = (last["new_state"], last["transition_id"])
    return latest


def _window_mask(entities: pd.DataFrame, decision_at: pd.DatetimeIndex) -> np.ndarray:
    valid_from = pd.DatetimeIndex(entities["valid_from"])
    valid_until = pd.DatetimeIndex(entities["valid_until"])
    after_start = np.asarray(valid_from.isna() | (decision_at >= valid_from))
    before_end = np.asarray(valid_until.isna() | (decision_at < valid_until))
    return after_start & before_end


def _input_tz(frame: Any, column: str):
    """Timezone of a caller's timestamp column (materialized output is returned in it)."""
    if not isinstance(frame, pd.DataFrame) or column not in frame.columns:
        return "UTC"
    series = frame[column]
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        return series.dt.tz
    first = series.dropna()
    return (getattr(first.iloc[0], "tzinfo", None) or "UTC") if len(first) else "UTC"


def _ns(index: pd.DatetimeIndex) -> np.ndarray:
    return index.tz_convert("UTC").as_unit("ns").asi8 if index.tz is not None else index.as_unit("ns").asi8


def _tz_column(values: pd.Series, name: str, *, allow_null: bool) -> pd.Series:
    series = pd.Series(values)
    if series.isna().all():
        if len(series) and not allow_null:
            raise StateContractError(f"{name} contains missing timestamps")
        return pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        converted = series
    elif series.dtype == object:
        stamps = series.dropna()
        if not all(hasattr(value, "tzinfo") for value in stamps):
            raise StateContractError(f"{name} must contain timestamps")
        if any(getattr(value, "tzinfo", None) is None for value in stamps):
            raise StateContractError(f"{name} must be timezone-aware")
        converted = pd.to_datetime(series, utc=True)
    else:
        raise StateContractError(f"{name} must be timezone-aware timestamps, got dtype {series.dtype}")
    if not allow_null and converted.isna().any():
        raise StateContractError(f"{name} contains missing timestamps")
    return converted.dt.tz_convert("UTC").dt.as_unit("ns")


def _sequence_pair(domain: Any, seq: Any, name: str, index: pd.Index) -> tuple[pd.Series, pd.Series]:
    """Validate a co-null (seq_domain, seq) pair; returns object and Int64 series."""
    seq_series = _seq_column(seq, f"{name}_seq", index)
    if domain is None:
        domain_series = pd.Series([None] * len(index), index=index, dtype=object)
    else:
        domain_series = pd.Series(domain, index=index).astype(object).where(pd.Series(domain, index=index).notna(), None)
    has_domain = domain_series.notna().to_numpy()
    if (has_domain != seq_series.notna().to_numpy()).any():
        raise StateContractError(f"{name}_seq_domain and {name}_seq must be both null or both present")
    if not all(isinstance(value, str) and _DOMAIN_RE.fullmatch(value) for value in domain_series.dropna()):
        raise StateContractError(f"{name}_seq_domain must contain non-empty domain tokens")
    return domain_series, seq_series


def _seq_column(values: Any, name: str, index: pd.Index) -> pd.Series:
    if values is None:
        return pd.Series(pd.array([pd.NA] * len(index), dtype="Int64"), index=index)
    series = pd.Series(values, index=index)
    if pd.api.types.is_bool_dtype(series.dtype) or any(isinstance(value, (bool, np.bool_, str)) for value in series.dropna()):
        raise StateContractError(f"{name} must contain integers or nulls")
    try:
        return pd.Series(pd.array(series.to_numpy(dtype=object), dtype="Int64"), index=index)
    except (TypeError, ValueError) as exc:
        raise StateContractError(f"{name} must contain integers or nulls") from exc


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, (bool, np.bool_, str)) or not float(value).is_integer():
        raise StateContractError(f"{name} must be an integer, got {value!r}")
    return int(value)


def _require_tokens(series: pd.Series, name: str) -> None:
    if not all(isinstance(value, str) and value.strip() for value in series):
        raise StateContractError(f"{name} must contain non-empty strings")


def _check_scope(scope: pd.Series, contract: pd.Series, where: str) -> None:
    invalid = ~scope.isin(CONTRACT_SCOPES)
    if invalid.any():
        raise StateContractError(f"{where}: contract_scope must be one of {CONTRACT_SCOPES}, got {scope[invalid].iloc[0]!r}")
    present = contract.notna() & contract.map(lambda value: isinstance(value, str) and bool(value.strip()))
    if (scope.eq(SPECIFIC) & ~present).any():
        raise StateContractError(f"{where}: SPECIFIC scope requires a non-empty contract")
    if (scope.eq(AGNOSTIC) & contract.notna()).any():
        raise StateContractError(f"{where}: AGNOSTIC scope must have a null contract")


def _check_attribute(frame: pd.DataFrame, attribute: AttributeSpec) -> None:
    column = attribute.column
    if column not in frame.columns:
        if attribute.required:
            raise StateContractError(f"required attribute column {column} is missing")
        return
    series = frame[column]
    if attribute.required and series.isna().any():
        raise StateContractError(f"required attribute {column} contains nulls")
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
        raise StateContractError(f"attribute {column} must have dtype {attribute.dtype}, got {dtype}")


def _codes(series: pd.Series) -> np.ndarray:
    """Integer codes over *sorted* uniques (nulls -1): independent of row encounter order."""
    return pd.factorize(pd.Series(series).astype(object), sort=True)[0]


def _first_id(frame: pd.DataFrame, mask: np.ndarray) -> str:
    return str(frame["transition_id"].iloc[int(np.flatnonzero(np.asarray(mask))[0])])
