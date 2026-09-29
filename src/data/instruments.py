"""Generic instrument metadata loaded from ``config/instruments/<id>.json``.

The instrument config is the single authoritative source for tick size, point
value, and tick value.  Values are parsed directly from the JSON text into
``Decimal`` (never through binary floats) and validated exactly, including
``tick_value == tick_size * point_value``.  There are no defaults: missing or
invalid metadata raises an ``InstrumentError``.

Canonical schema (field names follow the existing ``mnq.json``, whose content
hash is recorded in frozen ORB provenance and must not change):

- ``instrument_id``: root identity, e.g. ``MNQ`` (not a dated contract);
- ``name``, ``asset_class``, ``exchange``, ``currency``;
- ``tick_size_points``, ``point_value_usd``, ``tick_value_usd``: JSON numbers.

Session facts belong to ``src/data/sessions.py``; contract-roll behavior is
out of scope.  Legacy constants such as
``src.backtesting.candidate_entries.TICK_SIZE`` are temporary compatibility
artifacts guarded by tests, not independent sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
import json
import re

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INSTRUMENT_CONFIG_DIR = PROJECT_ROOT / "config" / "instruments"

REQUIRED_TEXT_FIELDS = ("instrument_id", "name", "asset_class", "exchange", "currency")
TICK_SIZE_FIELD = "tick_size_points"
POINT_VALUE_FIELD = "point_value_usd"
TICK_VALUE_FIELD = "tick_value_usd"
# The economic fields are denominated in USD by name.
ECONOMICS_CURRENCY = "USD"
INSTRUMENT_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_.-]*$")


class InstrumentError(ValueError):
    """Base error for instrument metadata problems."""


class InstrumentNotFoundError(InstrumentError, LookupError):
    """No configuration exists for the requested instrument."""


class InstrumentConfigError(InstrumentError):
    """An instrument configuration is malformed, incomplete, or inconsistent."""


@dataclass(frozen=True)
class InstrumentSpec:
    """Immutable, validated instrument metadata. Economics are exact Decimals."""

    instrument_id: str
    name: str
    asset_class: str
    exchange: str
    currency: str
    tick_size: Decimal
    point_value: Decimal
    tick_value: Decimal
    source_path: str


def normalize_instrument_id(instrument_id: str) -> str:
    """Return the canonical upper-case instrument ID or raise ``InstrumentError``."""
    if not isinstance(instrument_id, str):
        raise InstrumentError(f"Instrument ID must be a string, got {type(instrument_id).__name__}")
    normalized = instrument_id.strip().upper()
    if not INSTRUMENT_ID_PATTERN.fullmatch(normalized):
        raise InstrumentError(f"Invalid instrument ID: {instrument_id!r}")
    return normalized


def load_instrument(
    instrument_id: str,
    config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
) -> InstrumentSpec:
    """Load and validate ``<config_dir>/<instrument_id lower-case>.json``."""
    normalized = normalize_instrument_id(instrument_id)
    directory = Path(config_dir)
    if not directory.is_dir():
        raise InstrumentConfigError(f"Instrument config directory not found: {directory}")
    path = directory / f"{normalized.lower()}.json"
    if not path.is_file():
        raise InstrumentNotFoundError(
            f"No instrument config for {normalized!r} (expected {path})"
        )

    try:
        config = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, InstrumentConfigError) as error:
        raise InstrumentConfigError(f"Malformed instrument config {path}: {error}") from error
    if not isinstance(config, dict):
        raise InstrumentConfigError(f"Instrument config {path} must be a JSON object")

    def fail(message: str) -> InstrumentConfigError:
        return InstrumentConfigError(f"Instrument {normalized!r} ({path}): {message}")

    text = {}
    for field in REQUIRED_TEXT_FIELDS:
        value = config.get(field)
        if not isinstance(value, str) or not value.strip():
            raise fail(f"missing or empty required field {field!r}")
        text[field] = value.strip()
    if normalize_instrument_id(text["instrument_id"]) != normalized:
        raise fail(f"instrument_id {text['instrument_id']!r} does not match the requested instrument")
    if text["currency"] != ECONOMICS_CURRENCY:
        raise fail(f"currency must be {ECONOMICS_CURRENCY} for *_usd economic fields")

    tick_size = _positive_decimal(config, TICK_SIZE_FIELD, fail)
    point_value = _positive_decimal(config, POINT_VALUE_FIELD, fail)
    tick_value = _positive_decimal(config, TICK_VALUE_FIELD, fail)
    if tick_size * point_value != tick_value:
        raise fail(
            f"{TICK_VALUE_FIELD} {tick_value} != {TICK_SIZE_FIELD} {tick_size} "
            f"x {POINT_VALUE_FIELD} {point_value}"
        )

    return InstrumentSpec(
        instrument_id=normalized,
        name=text["name"],
        asset_class=text["asset_class"],
        exchange=text["exchange"],
        currency=text["currency"],
        tick_size=tick_size,
        point_value=point_value,
        tick_value=tick_value,
        source_path=str(path),
    )


def is_tick_aligned(price: Decimal | int | float | str, tick_size: Decimal) -> bool:
    """True when ``price`` is an exact multiple of ``tick_size`` (Decimal arithmetic).

    Floats are converted through their shortest string representation, so a
    float carrying binary error (e.g. ``0.1 + 0.2``) is reported as unaligned.
    """
    if not isinstance(tick_size, Decimal) or not tick_size.is_finite() or tick_size <= 0:
        raise InstrumentError(f"tick_size must be a positive finite Decimal, got {tick_size!r}")
    value = _to_decimal(price)
    return value % tick_size == 0


def _positive_decimal(config: dict[str, Any], field: str, fail) -> Decimal:
    if field not in config:
        raise fail(f"missing required field {field!r}")
    value = config[field]
    if not isinstance(value, Decimal):
        raise fail(f"{field!r} must be a JSON number, got {type(value).__name__}")
    if not value.is_finite() or value <= 0:
        raise fail(f"{field!r} must be positive and finite, got {value}")
    return value


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise InstrumentError("Boolean is not a valid price")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Decimal(value)
        except InvalidOperation as error:
            raise InstrumentError(f"Invalid price: {value!r}") from error
    elif isinstance(value, float):
        result = Decimal(str(value))
    else:
        raise InstrumentError(f"Unsupported price type: {type(value).__name__}")
    if not result.is_finite():
        raise InstrumentError(f"Price must be finite, got {value!r}")
    return result


def _reject_constant(token: str) -> None:
    raise InstrumentConfigError(f"non-finite JSON constant {token!r} is not allowed")
