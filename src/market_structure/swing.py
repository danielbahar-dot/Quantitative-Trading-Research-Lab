"""Canonical Swing Structure contract: definition spec, schema, BAR_SPAN provenance, identity.

Specification: ``docs/project/SWING_STRUCTURE_SPEC.md`` (D-135, D-136, D-138).
This module is the canonical *fact envelope* only (SW-I1).  It contains no
detection: no pivot search, plateau discovery, window checks, candidate
audit, continuity consumption or cross-timeframe projection.  It cannot
prove that a row is a real swing; that needs source-bar history (detector).

- ``SwingDefinitionSpec``: explicit ``definition_version``, ``left_depth``
  and ``right_depth`` (>= 1, no defaults).  The equality / plateau policy is
  fixed by ``definition_version``.
- ``swing_points`` (``SWING_COLUMNS``): confirmed, immutable swing facts.
- ``BAR_SPAN:<instrument_id>|<contract>|<timeframe>|<first_bar_end_utc>|<last_bar_end_utc>``:
  canonical source-span provenance, interpreted here (not by M7 SourceRef).
- ``swing_id``: ``sw_`` + full SHA-256 over the D-138 natural key; never
  price, availability, audit status or cross-timeframe context.

Reuses public M7 primitives (``SPECIFIC``, ``SourceRef``, ``canonical_time``)
and M2 instrument metadata; their errors surface as ``SwingContractError``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from src.data.instruments import (
    DEFAULT_INSTRUMENT_CONFIG_DIR,
    InstrumentError,
    is_tick_aligned,
    load_instrument,
    normalize_instrument_id,
)
from src.state.contract import SPECIFIC, SourceRef, StateContractError, canonical_time

UPPER = "UPPER"
LOWER = "LOWER"
ORIENTATIONS = (UPPER, LOWER)
SWING_TIMEFRAMES = ("1m", "5m", "15m", "1H", "4H", "1D")
SWING_ID_PREFIX = "sw_"
BAR_SPAN_KIND = "BAR_SPAN"

SWING_COLUMNS = (
    "swing_id",
    "orientation",
    "timeframe",
    "price",
    "source_ref",
    "source_at",
    "source_seq_domain",
    "source_seq",
    "source_end_at",
    "available_at",
    "available_seq_domain",
    "available_seq",
    "instrument_id",
    "contract_scope",
    "contract",
    "left_depth",
    "right_depth",
    "definition_version",
)
_SEQUENCE_COLUMNS = ("source_seq_domain", "source_seq", "available_seq_domain", "available_seq")
_CANONICAL_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z")


class SwingContractError(ValueError):
    """Raised for an invalid Swing definition, source ref, identity input or swing row."""


@contextmanager
def _boundary() -> Iterator[None]:
    """Translate errors from reused M7 / M2 primitives into SwingContractError."""
    try:
        yield
    except (StateContractError, InstrumentError) as exc:
        raise SwingContractError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SwingDefinitionSpec:
    """Explicit Swing definition (D-135 / D-138); no defaults, no registry."""

    definition_version: str
    left_depth: int
    right_depth: int

    def __post_init__(self) -> None:
        _require_token(self.definition_version, "definition_version")
        _require_depth(self.left_depth, "left_depth")
        _require_depth(self.right_depth, "right_depth")


# ---------------------------------------------------------------------------
# BAR_SPAN provenance
# ---------------------------------------------------------------------------


def bar_span_ref(*, instrument_id: str, contract: str, timeframe: str, first_bar_end: Any, last_bar_end: Any) -> str:
    """Canonical ``BAR_SPAN:<instrument_id>|<contract>|<timeframe>|<first_utc>|<last_utc>``.

    ``first_bar_end == last_bar_end`` for a single-bar source; ``<`` for a
    plateau.  Times use M7 ``canonical_time`` (timezone-aware inputs only).
    """
    _require_instrument_id(instrument_id)
    _require_contract(contract)
    _require_timeframe(timeframe)
    with _boundary():
        first, last = canonical_time(first_bar_end), canonical_time(last_bar_end)
    if pd.Timestamp(first) > pd.Timestamp(last):
        raise SwingContractError(f"BAR_SPAN first_bar_end {first} is after last_bar_end {last}")
    return SourceRef(BAR_SPAN_KIND, "|".join((instrument_id, contract, timeframe, first, last))).canonical


def _parse_bar_span(ref: Any) -> tuple[str, str, str, str, str]:
    """Validate a canonical BAR_SPAN ref; return (instrument_id, contract, timeframe, first, last)."""
    with _boundary():
        parsed = SourceRef.parse(ref)
    if parsed.kind != BAR_SPAN_KIND:
        raise SwingContractError(f"swing source_ref must be a {BAR_SPAN_KIND} reference, got kind {parsed.kind!r}")
    parts = parsed.key.split("|")
    if len(parts) != 5:
        raise SwingContractError(f"BAR_SPAN key must have 5 '|'-separated fields, got {len(parts)}")
    instrument_id, contract, timeframe, first, last = parts
    for text in (first, last):
        if not _CANONICAL_TIME_RE.fullmatch(text):
            raise SwingContractError(f"BAR_SPAN timestamp {text!r} is not canonical UTC")
        with _boundary():
            if canonical_time(pd.Timestamp(text)) != text:
                raise SwingContractError(f"BAR_SPAN timestamp {text!r} does not round-trip canonically")
    canonical = bar_span_ref(instrument_id=instrument_id, contract=contract, timeframe=timeframe,
                             first_bar_end=pd.Timestamp(first), last_bar_end=pd.Timestamp(last))
    if canonical != parsed.canonical:
        raise SwingContractError(f"BAR_SPAN ref {parsed.canonical!r} is not canonical")
    return instrument_id, contract, timeframe, first, last


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def swing_id(
    *,
    definition_version: str,
    instrument_id: str,
    contract_scope: str,
    contract: str,
    timeframe: str,
    orientation: str,
    left_depth: int,
    right_depth: int,
    source_ref: Any,
) -> str:
    """``sw_`` + full SHA-256 over the D-138 natural key.

    Price, ``available_at``, audit status and cross-timeframe context are
    excluded; the BAR_SPAN ref carries the full source-span identity.
    """
    _require_token(definition_version, "definition_version")
    _require_instrument_id(instrument_id)
    if contract_scope != SPECIFIC:
        raise SwingContractError(f"contract_scope must be {SPECIFIC!r}, got {contract_scope!r}")
    _require_contract(contract)
    _require_timeframe(timeframe)
    if orientation not in ORIENTATIONS:
        raise SwingContractError(f"orientation must be one of {ORIENTATIONS}, got {orientation!r}")
    _require_depth(left_depth, "left_depth")
    _require_depth(right_depth, "right_depth")
    ref_instrument, ref_contract, ref_timeframe, first, last = _parse_bar_span(source_ref)
    if (ref_instrument, ref_contract, ref_timeframe) != (instrument_id, contract, timeframe):
        raise SwingContractError("BAR_SPAN instrument / contract / timeframe disagree with the identity fields")
    ref = bar_span_ref(instrument_id=instrument_id, contract=contract, timeframe=timeframe,
                       first_bar_end=pd.Timestamp(first), last_bar_end=pd.Timestamp(last))
    key = [definition_version, instrument_id, contract_scope, contract, timeframe, orientation,
           int(left_depth), int(right_depth), ref]
    digest = hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return SWING_ID_PREFIX + digest


def assign_swing_ids(swings: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with canonical BAR_SPAN ``source_ref`` and computed ``swing_id``.

    Never derives or changes price, availability or depths; not a detector.
    """
    frame = _require_frame(swings, "swings").copy()
    refs = []
    for value in frame["source_ref"]:
        instrument_id, contract, timeframe, first, last = _parse_bar_span(value)
        refs.append(bar_span_ref(instrument_id=instrument_id, contract=contract, timeframe=timeframe,
                                 first_bar_end=pd.Timestamp(first), last_bar_end=pd.Timestamp(last)))
    frame["source_ref"] = refs
    frame["swing_id"] = [
        swing_id(
            definition_version=row.definition_version, instrument_id=row.instrument_id,
            contract_scope=row.contract_scope, contract=row.contract, timeframe=row.timeframe,
            orientation=row.orientation, left_depth=row.left_depth, right_depth=row.right_depth,
            source_ref=row.source_ref,
        )
        for row in frame.itertuples(index=False)
    ]
    return frame


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_swing_points(
    swings: pd.DataFrame,
    definition: SwingDefinitionSpec,
    *,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
) -> pd.DataFrame:
    """Validate canonical ``swing_points`` rows; return them normalized and ordered.

    Checks the exact schema, conformity to ``definition``, vocabularies,
    ``SPECIFIC`` scope and contract text, instrument metadata, finite
    tick-aligned prices, null bar sequences, timezone-aware times with
    ``source_at <= source_end_at < available_at``, BAR_SPAN agreement with the
    row, deterministic ids and uniqueness.  Times are returned in UTC; rows
    are ordered by (``available_at``, ``source_at``, ``timeframe``,
    ``orientation``, ``swing_id``).

    It validates the fact envelope only: without source bars it cannot check
    that a row is a real local extremum, a maximal plateau, inside one
    continuity segment, or confirmed exactly ``right_depth`` observations
    before ``available_at`` (detector validation).
    """
    if not isinstance(definition, SwingDefinitionSpec):
        raise SwingContractError("definition must be a SwingDefinitionSpec")
    frame = _exact_schema(swings, SWING_COLUMNS, "swings")
    if frame.empty:
        return frame

    for column in ("swing_id", "definition_version", "instrument_id"):
        if not all(isinstance(value, str) and value.strip() and value == value.strip() for value in frame[column]):
            raise SwingContractError(f"{column} must contain non-empty trimmed strings")
    if (frame["definition_version"] != definition.definition_version).any():
        raise SwingContractError(f"definition_version must be {definition.definition_version!r}")
    for column, expected in (("left_depth", definition.left_depth), ("right_depth", definition.right_depth)):
        for value in frame[column]:
            _require_depth(value, column)
        if (frame[column].astype("int64") != expected).any():
            raise SwingContractError(f"{column} must be {expected} for this definition")
        frame[column] = frame[column].astype("int64")

    _check_vocabulary(frame["orientation"], "orientation", ORIENTATIONS)
    _check_vocabulary(frame["timeframe"], "timeframe", SWING_TIMEFRAMES)
    _check_vocabulary(frame["contract_scope"], "contract_scope", (SPECIFIC,))
    for value in frame["contract"]:
        _require_contract(value)
    for value in frame["instrument_id"]:
        _require_instrument_id(value)

    with _boundary():
        tick = {inst: load_instrument(inst, instrument_config_dir).tick_size for inst in frame["instrument_id"].unique()}
    if pd.api.types.is_bool_dtype(frame["price"].dtype) or any(isinstance(v, (bool, np.bool_)) for v in frame["price"]):
        raise SwingContractError("price must be numeric")
    prices = pd.to_numeric(frame["price"], errors="coerce")
    if prices.isna().any() or not np.isfinite(prices.to_numpy(dtype=float)).all():
        raise SwingContractError("price must be finite")
    frame["price"] = prices.astype(float)
    with _boundary():
        off_grid = [i for i, (price, inst) in enumerate(zip(frame["price"], frame["instrument_id"]))
                    if not is_tick_aligned(price, tick[inst])]
    if off_grid:
        raise SwingContractError(f"{frame['swing_id'].iloc[off_grid[0]]}: price is not on the instrument tick grid")

    for column in _SEQUENCE_COLUMNS:
        if frame[column].notna().any():
            raise SwingContractError(f"{column} must be null for bar-sourced swings")
    frame["source_seq_domain"] = pd.Series([None] * len(frame), dtype=object)
    frame["available_seq_domain"] = pd.Series([None] * len(frame), dtype=object)
    frame["source_seq"] = pd.array([pd.NA] * len(frame), dtype="Int64")
    frame["available_seq"] = pd.array([pd.NA] * len(frame), dtype="Int64")

    for column in ("source_at", "source_end_at", "available_at"):
        frame[column] = _utc(frame[column], column)
    if (frame["source_at"] > frame["source_end_at"]).any():
        raise SwingContractError("source_at must not be after source_end_at")
    if (frame["source_end_at"] >= frame["available_at"]).any():
        raise SwingContractError("source_end_at must be strictly before available_at")

    for row in frame.itertuples(index=False):
        if not isinstance(row.source_ref, str):
            raise SwingContractError(f"{row.swing_id}: source_ref must be a canonical BAR_SPAN string")
        instrument_id, contract, timeframe, first, last = _parse_bar_span(row.source_ref)
        if row.source_ref != bar_span_ref(instrument_id=instrument_id, contract=contract, timeframe=timeframe,
                                          first_bar_end=pd.Timestamp(first), last_bar_end=pd.Timestamp(last)):
            raise SwingContractError(f"{row.swing_id}: source_ref is not canonical")
        if instrument_id != row.instrument_id:
            raise SwingContractError(f"{row.swing_id}: BAR_SPAN instrument disagrees with instrument_id")
        if contract != row.contract:
            raise SwingContractError(f"{row.swing_id}: BAR_SPAN contract disagrees with contract")
        if timeframe != row.timeframe:
            raise SwingContractError(f"{row.swing_id}: BAR_SPAN timeframe disagrees with timeframe")
        if first != canonical_time(row.source_at):
            raise SwingContractError(f"{row.swing_id}: BAR_SPAN first bar end disagrees with source_at")
        if last != canonical_time(row.source_end_at):
            raise SwingContractError(f"{row.swing_id}: BAR_SPAN last bar end disagrees with source_end_at")

    if frame["swing_id"].duplicated().any():
        raise SwingContractError(f"duplicate swing_id {frame.loc[frame['swing_id'].duplicated(), 'swing_id'].iloc[0]}")
    expected = assign_swing_ids(frame)["swing_id"]
    wrong = (expected != frame["swing_id"]).to_numpy()
    if wrong.any():
        raise SwingContractError(f"{frame['swing_id'].iloc[int(np.flatnonzero(wrong)[0])]}: swing_id does not match its natural key")

    order = np.lexsort((
        _ranks(frame["swing_id"]),
        _ranks(frame["orientation"]),
        np.array([SWING_TIMEFRAMES.index(value) for value in frame["timeframe"]], dtype=np.int64),
        _ns(frame["source_at"]),
        _ns(frame["available_at"]),
    ))
    return frame.iloc[order].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Plumbing (module-local)
# ---------------------------------------------------------------------------


def _require_token(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SwingContractError(f"{name} must be a non-empty trimmed string, got {value!r}")


def _require_depth(value: Any, name: str) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or int(value) < 1:
        raise SwingContractError(f"{name} must be an integer >= 1, got {value!r}")


def _require_instrument_id(value: Any) -> None:
    with _boundary():
        canonical = normalize_instrument_id(value)
    if canonical != value:
        raise SwingContractError(f"instrument_id must be canonical ({canonical!r}), got {value!r}")


def _require_contract(value: Any) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SwingContractError(f"contract must be a non-empty trimmed string, got {value!r}")
    if "|" in value or "\n" in value or "\r" in value:
        raise SwingContractError(f"contract must not contain '|' or line breaks, got {value!r}")


def _require_timeframe(value: Any) -> None:
    if value not in SWING_TIMEFRAMES:
        raise SwingContractError(f"timeframe must be one of {SWING_TIMEFRAMES}, got {value!r}")


def _require_frame(frame: Any, name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise SwingContractError(f"{name} must be a pandas DataFrame")
    return frame


def _exact_schema(frame: Any, columns: tuple[str, ...], name: str) -> pd.DataFrame:
    frame = _require_frame(frame, name)
    missing = [column for column in columns if column not in frame.columns]
    extra = [column for column in frame.columns if column not in columns]
    if missing:
        raise SwingContractError(f"{name} missing required columns: {missing}")
    if extra:
        raise SwingContractError(f"{name} have non-canonical columns: {extra}")
    return frame[list(columns)].reset_index(drop=True).copy()


def _check_vocabulary(series: pd.Series, name: str, allowed: tuple[str, ...]) -> None:
    bad = sorted({str(value) for value in series if value not in allowed})
    if bad:
        raise SwingContractError(f"{name} must be one of {allowed}, got {bad}")


def _utc(values: pd.Series, name: str) -> pd.Series:
    series = pd.Series(values)
    if series.isna().any():
        raise SwingContractError(f"{name} contains missing timestamps")
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        return series.dt.tz_convert("UTC").dt.as_unit("ns")
    if series.dtype == object and all(getattr(value, "tzinfo", None) is not None for value in series):
        return pd.to_datetime(series, utc=True).dt.as_unit("ns")
    raise SwingContractError(f"{name} must contain timezone-aware timestamps")


def _ranks(values: pd.Series) -> np.ndarray:
    """Deterministic sorted ranks for string keys; never encounter order."""
    rank = {value: position for position, value in enumerate(sorted(set(values)))}
    return np.array([rank[value] for value in values], dtype=np.int64)


def _ns(values: pd.Series) -> np.ndarray:
    return pd.DatetimeIndex(values).tz_convert("UTC").as_unit("ns").asi8
