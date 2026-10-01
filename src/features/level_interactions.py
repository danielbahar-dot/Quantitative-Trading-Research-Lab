"""Generic Level Interaction catalog (M6A): stateless, per completed bar.

Answers only: *what did this completed bar objectively do relative to this
already-available level?*  No lifecycle (first touch, active, consumed, ...);
that belongs to State / Signal / Strategy layers.  Specification:
``docs/project/M6_LEVEL_INTERACTIONS_SPEC.md`` (D-126).

Rules (exact integer ticks; tick size from M2 instrument metadata):

- Bar prices must lie on the tick grid and become integer ticks
  ``O, H, Lo, C``.  A level ``L`` may be off-grid; per level
  ``f = floor(L/t)``, ``c = ceil(L/t)`` (exact ``Decimal``), so the first
  tradable prices strictly above/below ``L`` are ``(f+1)*t`` / ``(c-1)*t``.
- ``approach_side`` from the bar open: ``BELOW`` (``O <= c-1``), ``ABOVE``
  (``O >= f+1``), ``AT`` (open exactly at ``L``).  ``AT`` counts as the
  original side for UPPER (up) / LOWER (down); for NEUTRAL no direction is
  invented (``AMBIGUOUS_APPROACH``: touch True, the other four <NA>).
- Upward (approach BELOW): TOUCH ``H>=c``; TRADE_THROUGH ``H>=f+1``;
  CLOSE_THROUGH ``C>=f+1``; REJECT ``H>=c & C<=f``; SWEEP ``H>=f+1 & C<=f``.
  Downward (approach ABOVE) mirrors with ``Lo`` and ``c-1`` / ``c``.
- ``approach_relation``: ORIGINAL_SIDE / FAR_SIDE for directional levels
  (orientation is semantic and never inferred), <NA> for NEUTRAL.
- Causality: a level applies to bars with ``bar_end >= available_at``; the
  confirming bar (``bar_start < available_at``) is ``PENDING_LEVEL``; earlier
  bars are never emitted.
- Applicability: optional immutable ``valid_from`` / ``valid_until`` bound
  the bars a level applies to (``valid_from <= bar_start < valid_until``).
  Evaluation eligibility is ``bar_start >= max(available_at, valid_from)``
  and ``bar_start < valid_until``; the confirming bar is emitted (as
  ``PENDING_LEVEL``) only when it lies inside that static window.  Enforced
  here in the generic engine, not only by helpers.  Static metadata, not
  lifecycle.
- ``contract_scope`` SPECIFIC: a different bar contract is
  ``CONTRACT_MISMATCH``; AGNOSTIC: never checked.  Nothing is stitched.
- Invalid input raises; it never becomes a status.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from src.data.instruments import load_instrument
from src.data.sessions import SessionSpec, assign_trading_dates, session_bounds, LABEL_BAR_END
from src.features.session_context import ONE_MINUTE, valid_context_levels

UPPER, LOWER, NEUTRAL = "UPPER", "LOWER", "NEUTRAL"
ORIENTATIONS = (UPPER, LOWER, NEUTRAL)
SPECIFIC, AGNOSTIC = "SPECIFIC", "AGNOSTIC"
CONTRACT_SCOPES = (SPECIFIC, AGNOSTIC)

EVALUATED = "EVALUATED"
AMBIGUOUS_APPROACH = "AMBIGUOUS_APPROACH"
PENDING_LEVEL = "PENDING_LEVEL"
CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
STATUSES = (EVALUATED, AMBIGUOUS_APPROACH, PENDING_LEVEL, CONTRACT_MISMATCH)

BELOW, ABOVE, AT = "BELOW", "ABOVE", "AT"
ORIGINAL_SIDE, FAR_SIDE = "ORIGINAL_SIDE", "FAR_SIDE"

PRIMITIVES = ("touch", "trade_through", "close_through", "reject", "sweep")
OFFSET_COLUMNS = ("open_offset_ticks", "high_offset_ticks", "low_offset_ticks", "close_offset_ticks")
REQUIRED_LEVEL_COLUMNS = (
    "level_id", "level_value", "orientation", "available_at", "instrument_id", "contract_scope", "contract",
)
PROVENANCE_COLUMNS = ("level_type", "source_feature", "source_trading_date", "definition_version")
OUTPUT_COLUMNS = [
    "bar_end", "bar_start", "bar_contract",
    "level_id", "level_value", "orientation", "instrument_id", "contract_scope", "level_contract",
    "available_at", "valid_from", "valid_until", "first_tradable_above", "first_tradable_below",
    "status", "approach_side", "approach_relation",
    *PRIMITIVES, *OFFSET_COLUMNS,
]
# M5 contexts whose close is a genuinely non-directional reference level.
NEUTRAL_CLOSE_CONTEXTS = ("previous_day", "previous_rth")
TICK_TOLERANCE = 1e-9


class LevelInteractionError(ValueError):
    """Raised for invalid level or bar input."""


def prepare_levels(
    levels: pd.DataFrame,
    *,
    instrument_config_dir: Any = None,
) -> tuple[pd.DataFrame, Decimal]:
    """Validate a level frame; add exact ``floor_ticks``/``ceil_ticks`` and first tradable prices."""
    if not isinstance(levels, pd.DataFrame):
        raise LevelInteractionError("levels must be a pandas DataFrame")
    missing = [column for column in REQUIRED_LEVEL_COLUMNS if column not in levels.columns]
    if missing:
        raise LevelInteractionError(f"levels missing required columns: {missing}")
    if levels.empty:
        raise LevelInteractionError("levels is empty")
    frame = levels.reset_index(drop=True).copy()
    for column in ("valid_from", "valid_until"):
        if column not in frame.columns:
            frame[column] = pd.NaT

    ids = frame["level_id"]
    if ids.isna().any() or not ids.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise LevelInteractionError("level_id must be a non-empty string")
    if ids.duplicated().any():
        raise LevelInteractionError(f"duplicate level_id: {ids[ids.duplicated()].iloc[0]!r}")
    bad_orientation = ~frame["orientation"].isin(ORIENTATIONS)
    if bad_orientation.any():
        raise LevelInteractionError(f"invalid orientation {frame.loc[bad_orientation, 'orientation'].iloc[0]!r}")
    bad_scope = ~frame["contract_scope"].isin(CONTRACT_SCOPES)
    if bad_scope.any():
        raise LevelInteractionError(f"invalid contract_scope {frame.loc[bad_scope, 'contract_scope'].iloc[0]!r}")
    for row in frame.itertuples():
        has_contract = isinstance(row.contract, str) and bool(row.contract.strip())
        if row.contract_scope == SPECIFIC and not has_contract:
            raise LevelInteractionError(f"level {row.level_id!r}: SPECIFIC scope requires a contract")
        if row.contract_scope == AGNOSTIC and not pd.isna(row.contract):
            raise LevelInteractionError(f"level {row.level_id!r}: AGNOSTIC scope must not carry a contract")

    values = pd.to_numeric(frame["level_value"], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise LevelInteractionError("level_value must be finite")
    frame["level_value"] = values.astype(float)
    frame["available_at"] = _tz_aware(frame["available_at"], "available_at", allow_null=False)
    frame["valid_from"] = _tz_aware(frame["valid_from"], "valid_from", allow_null=True)
    frame["valid_until"] = _tz_aware(frame["valid_until"], "valid_until", allow_null=True)
    early = frame["valid_until"].notna() & (frame["valid_until"] < frame["available_at"])
    if early.any():
        raise LevelInteractionError(f"level {frame.loc[early, 'level_id'].iloc[0]!r}: valid_until precedes available_at")
    inverted = frame["valid_from"].notna() & frame["valid_until"].notna() & (frame["valid_until"] <= frame["valid_from"])
    if inverted.any():
        raise LevelInteractionError(f"level {frame.loc[inverted, 'level_id'].iloc[0]!r}: valid_until must follow valid_from")

    instruments = frame["instrument_id"].dropna().unique()
    if frame["instrument_id"].isna().any() or len(instruments) != 1:
        raise LevelInteractionError("all levels in one call must share a single instrument_id")
    instrument_kwargs = {} if instrument_config_dir is None else {"config_dir": instrument_config_dir}
    tick = load_instrument(str(instruments[0]), **instrument_kwargs).tick_size

    floors, ceils = [], []
    for value in frame["level_value"]:
        quotient = Decimal(repr(float(value))) / tick
        floors.append(int(quotient.to_integral_value(rounding=ROUND_FLOOR)))
        ceils.append(int(quotient.to_integral_value(rounding=ROUND_CEILING)))
    frame["floor_ticks"] = np.asarray(floors, dtype=np.int64)
    frame["ceil_ticks"] = np.asarray(ceils, dtype=np.int64)
    frame["first_tradable_above"] = [float((f + 1) * tick) for f in floors]
    frame["first_tradable_below"] = [float((c - 1) * tick) for c in ceils]
    return frame, tick


def evaluate_level_interactions(
    bars: pd.DataFrame,
    levels: pd.DataFrame,
    *,
    bar_interval: Any = ONE_MINUTE,
    session_spec: SessionSpec | None = None,
    interactions_only: bool = False,
    instrument_config_dir: Any = None,
) -> pd.DataFrame:
    """Long/tidy interaction facts, one row per applicable (bar, level) pair.

    ``interactions_only`` keeps only rows whose ``touch`` is True (every
    primitive implies touch), which bounds memory for large evaluations.
    ``instrument_config_dir`` overrides the M2 instrument config directory.
    """
    level_frame, tick = prepare_levels(levels, instrument_config_dir=instrument_config_dir)
    interval = pd.Timedelta(bar_interval)
    source = _prepare_bars(bars, tick, interval, session_spec)
    bar_end = source.index
    for column in ("available_at", "valid_from", "valid_until"):
        level_frame[column] = pd.DatetimeIndex(level_frame[column]).tz_convert(bar_end.tz).as_unit(bar_end.unit)
    bar_index, level_index = _pairs(bar_end, level_frame, interval)
    if len(bar_index) == 0:
        return _empty_output(level_frame)

    tick_float = float(tick)
    lv = level_frame.iloc[level_index].reset_index(drop=True)
    b_end = bar_end[bar_index]
    b_start = b_end - interval
    bar_contract = source["contract"].to_numpy()[bar_index]
    O, H, Lo, C = (source[f"{name}_ticks"].to_numpy()[bar_index] for name in ("open", "high", "low", "close"))
    f = lv["floor_ticks"].to_numpy()
    c = lv["ceil_ticks"].to_numpy()
    orientation = lv["orientation"].to_numpy()

    pending = np.asarray(b_start < pd.DatetimeIndex(lv["available_at"]))
    specific = lv["contract_scope"].to_numpy() == SPECIFIC
    mismatch = ~pending & specific & (bar_contract != lv["contract"].to_numpy())
    active = ~pending & ~mismatch

    below = O <= c - 1
    above = O >= f + 1
    at = ~below & ~above
    upward = below | (at & (orientation == UPPER))
    downward = above | (at & (orientation == LOWER))
    ambiguous = active & at & (orientation == NEUTRAL)
    evaluated = active & ~ambiguous

    touch = np.where(upward, H >= c, Lo <= f)
    touch = touch | ambiguous  # NEUTRAL open exactly at the level: contact is objective
    trade = np.where(upward, H >= f + 1, Lo <= c - 1)
    close_through = np.where(upward, C >= f + 1, C <= c - 1)
    back = np.where(upward, C <= f, C >= c)
    reject = touch & back
    sweep = trade & back

    status = np.select([pending, mismatch, ambiguous], [PENDING_LEVEL, CONTRACT_MISMATCH, AMBIGUOUS_APPROACH], EVALUATED)
    side = np.select([below, above], [BELOW, ABOVE], AT).astype(object)
    side[~active] = None
    relation = np.select(
        [orientation == NEUTRAL, (orientation == UPPER) & upward, (orientation == LOWER) & downward],
        [None, ORIGINAL_SIDE, ORIGINAL_SIDE], FAR_SIDE,
    ).astype(object)
    relation[~evaluated] = None

    out = pd.DataFrame({
        "bar_end": b_end,
        "bar_start": b_start,
        "bar_contract": bar_contract,
        "level_id": lv["level_id"].to_numpy(),
        "level_value": lv["level_value"].to_numpy(),
        "orientation": orientation,
        "instrument_id": lv["instrument_id"].to_numpy(),
        "contract_scope": lv["contract_scope"].to_numpy(),
        "level_contract": lv["contract"].to_numpy(),
        "available_at": pd.DatetimeIndex(lv["available_at"]),
        "valid_from": pd.DatetimeIndex(lv["valid_from"]),
        "valid_until": pd.DatetimeIndex(lv["valid_until"]),
        "first_tradable_above": lv["first_tradable_above"].to_numpy(),
        "first_tradable_below": lv["first_tradable_below"].to_numpy(),
        "status": status,
        "approach_side": pd.array(side, dtype="string"),
        "approach_relation": pd.array(relation, dtype="string"),
        "touch": pd.arrays.BooleanArray(touch.astype(bool), ~active),
        "trade_through": pd.arrays.BooleanArray(trade.astype(bool), ~evaluated),
        "close_through": pd.arrays.BooleanArray(close_through.astype(bool), ~evaluated),
        "reject": pd.arrays.BooleanArray(reject.astype(bool), ~evaluated),
        "sweep": pd.arrays.BooleanArray(sweep.astype(bool), ~evaluated),
    })
    level_value = lv["level_value"].to_numpy()
    for column, name in zip(OFFSET_COLUMNS, ("open", "high", "low", "close")):
        raw = (source[name].to_numpy()[bar_index] - level_value) / tick_float
        out[column] = pd.arrays.FloatingArray(raw.astype(float), ~active)
    for column in PROVENANCE_COLUMNS:
        if column in lv.columns:
            out[column] = lv[column].to_numpy()
    if interactions_only:
        out = out[out["touch"].fillna(False).astype(bool)]
    columns = OUTPUT_COLUMNS + [column for column in PROVENANCE_COLUMNS if column in lv.columns]
    return out[columns].sort_values(["bar_end", "level_id"], kind="mergesort").reset_index(drop=True)


def market_context_levels(
    context: pd.DataFrame,
    session_spec: SessionSpec,
    *,
    context_ids: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Levels from the M5 valid tier: high -> UPPER, low -> LOWER, previous closes -> NEUTRAL.

    ``valid_from`` / ``valid_until`` are the target CME session open / close
    (static applicability matching M5 target-session scope); contract scope is
    SPECIFIC with the context's contract.
    """
    valid = valid_context_levels(context)
    if context_ids is not None:
        valid = valid[valid["context_id"].isin(context_ids)]
    rows: list[dict[str, Any]] = []
    sessions: dict = {}
    for record in valid.itertuples(index=False):
        day = record.target_trading_date
        if day not in sessions:
            sessions[day] = session_bounds(day, session_spec)
        fields: list[tuple[str, str]] = [("high", UPPER), ("low", LOWER)]
        if record.context_id in NEUTRAL_CLOSE_CONTEXTS:
            fields.append(("close", NEUTRAL))
        for field, orientation in fields:
            rows.append({
                "level_id": f"{record.context_id}:{field}:{day.isoformat()}",
                "level_value": float(getattr(record, field)),
                "orientation": orientation,
                "available_at": record.available_at,
                "valid_from": sessions[day].open,
                "valid_until": sessions[day].close,
                "instrument_id": record.instrument_id,
                "contract_scope": SPECIFIC,
                "contract": record.contract,
                "level_type": f"{record.context_id}_{field}",
                "source_feature": record.context_id,
                "source_trading_date": record.source_trading_date,
                "definition_version": record.definition_version,
            })
    return pd.DataFrame(rows, columns=[*REQUIRED_LEVEL_COLUMNS, "valid_from", "valid_until", *PROVENANCE_COLUMNS])


def evaluate_market_context_interactions(
    bars: pd.DataFrame,
    context: pd.DataFrame,
    session_spec: SessionSpec,
    *,
    context_ids: Sequence[str] | None = None,
    bar_interval: Any = ONE_MINUTE,
    interactions_only: bool = False,
) -> pd.DataFrame:
    """Evaluate M5-derived levels (``market_context_levels``) against canonical bars."""
    levels = market_context_levels(context, session_spec, context_ids=context_ids)
    return evaluate_level_interactions(
        bars, levels, bar_interval=bar_interval, session_spec=session_spec,
        interactions_only=interactions_only,
    )


def _prepare_bars(
    bars: pd.DataFrame,
    tick: Decimal,
    interval: pd.Timedelta,
    session_spec: SessionSpec | None,
) -> pd.DataFrame:
    if not isinstance(bars, pd.DataFrame):
        raise LevelInteractionError("bars must be a pandas DataFrame")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise LevelInteractionError("bars must have a timezone-aware DatetimeIndex of bar-end labels")
    if bars.empty:
        raise LevelInteractionError("bars is empty")
    required = ["open", "high", "low", "close", "contract"]
    missing = [column for column in required if column not in bars.columns]
    if missing:
        raise LevelInteractionError(f"bars missing required columns: {missing}")
    if bars.index.has_duplicates:
        raise LevelInteractionError("bars contain duplicate timestamps")
    if interval <= pd.Timedelta(0):
        raise LevelInteractionError("bar_interval must be positive")
    source = bars.sort_index()
    if source[required].isna().any().any():
        raise LevelInteractionError("bars contain missing OHLC or contract values")
    if (source["contract"].astype(str).str.strip() == "").any():
        raise LevelInteractionError("bars contain empty contract identifiers")
    prices = source[["open", "high", "low", "close"]].astype(float)
    if ((prices["high"] < prices[["open", "close"]].max(axis=1)) | (prices["low"] > prices[["open", "close"]].min(axis=1))).any():
        raise LevelInteractionError("bars contain inconsistent OHLC values")
    tick_float = float(tick)
    source = source.copy()
    source["contract"] = source["contract"].astype(str)
    for name in ("open", "high", "low", "close"):
        scaled = prices[name].to_numpy() / tick_float
        rounded = np.rint(scaled)
        if (np.abs(scaled - rounded) > TICK_TOLERANCE * np.maximum(1.0, np.abs(scaled))).any():
            raise LevelInteractionError(f"bar {name} prices are not on the instrument tick grid ({tick})")
        source[name] = prices[name].to_numpy()
        source[f"{name}_ticks"] = rounded.astype(np.int64)
    if session_spec is not None and "session_date" in source.columns:
        model = assign_trading_dates(source.index, session_spec, label=LABEL_BAR_END, bar_interval=interval).to_numpy()
        declared = pd.to_datetime(source["session_date"]).dt.date.to_numpy()
        if (declared != model).any():
            raise LevelInteractionError("bars session_date disagrees with the session model")
    return source


def _pairs(
    bar_end: pd.DatetimeIndex,
    levels: pd.DataFrame,
    interval: pd.Timedelta,
) -> tuple[np.ndarray, np.ndarray]:
    """(bar, level) pairs: bar_end >= available_at, valid_from <= bar_start < valid_until."""
    starts = bar_end.searchsorted(pd.DatetimeIndex(levels["available_at"]), side="left")
    has_from = levels["valid_from"].notna().to_numpy()
    if has_from.any():
        # bar_start >= valid_from  <=>  bar_end >= valid_from + interval
        from_starts = bar_end.searchsorted(pd.DatetimeIndex(levels.loc[has_from, "valid_from"]) + interval, side="left")
        starts[has_from] = np.maximum(starts[has_from], from_starts)
    ends = np.full(len(levels), len(bar_end), dtype=np.int64)
    bounded = levels["valid_until"].notna().to_numpy()
    if bounded.any():
        # bar_start < valid_until  <=>  bar_end < valid_until + interval
        ends[bounded] = bar_end.searchsorted(pd.DatetimeIndex(levels.loc[bounded, "valid_until"]) + interval, side="left")
    counts = np.maximum(ends - starts, 0)
    total = int(counts.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    level_index = np.repeat(np.arange(len(levels)), counts)
    offsets = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    bar_index = np.repeat(starts, counts) + offsets
    return bar_index.astype(np.int64), level_index.astype(np.int64)


def _empty_output(levels: pd.DataFrame) -> pd.DataFrame:
    columns = OUTPUT_COLUMNS + [column for column in PROVENANCE_COLUMNS if column in levels.columns]
    return pd.DataFrame(columns=columns)


def _tz_aware(values: pd.Series, name: str, *, allow_null: bool) -> pd.Series:
    if values.isna().all() and allow_null:
        return pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns, UTC]")
    if values.isna().any() and not allow_null:
        raise LevelInteractionError(f"{name} must not be null")
    stamps = [pd.Timestamp(value) if not pd.isna(value) else pd.NaT for value in values]
    if any(stamp is not pd.NaT and stamp.tzinfo is None for stamp in stamps):
        raise LevelInteractionError(f"{name} must be timezone-aware")
    utc = [stamp.tz_convert("UTC") if stamp is not pd.NaT else pd.NaT for stamp in stamps]
    return pd.Series(pd.DatetimeIndex(utc, tz="UTC"), index=values.index)
