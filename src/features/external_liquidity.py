"""External Liquidity (static): members, EQ/REQ structure versions, Previous Day references.

Specification: ``docs/project/EXTERNAL_LIQUIDITY_SPEC.md`` (D-133, D-134).
Generic Market Structure & Liquidity workstream; methodology-neutral.

Families:

- **Daily High / Low** — every *complete* Daily bar (``build_timeframe`` 1D)
  yields a standalone ``DAILY_HIGH`` (UPPER) and ``DAILY_LOW`` (LOWER)
  member, available at the Daily ``bar_end``.
- **Session / reference High / Low** — available M5 extrema of
  ``asia_2000_0000``, ``london_0200_0500``, ``ny_premarket_0700_0900`` and
  ``overnight_1800_0700`` (``SESSION_REFERENCE_HIGH`` / ``_LOW``); identical
  prices across families are kept as separate members.
- **Previous Day** — a derived reference view to the canonical Daily member
  of M5's previous expected session (never a separate member).
- **Daily and 4H EQ / REQ** — structure versions within fail-closed
  continuity segments (expected M3 schedule + completeness + contract),
  pair-outer formation barrier, EQ = 0 ticks, REQ = <= 6-tick chain with
  >= 2 distinct prices.  Daily structures group existing Daily members; a 4H
  extreme is a transient candidate until a confirmed structure promotes it
  (``HTF_EQREQ_HIGH`` / ``_LOW``, ``available_at`` = first confirmation).

No lifecycle, no Signals, no Swing Structure, no Internal Liquidity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from src.data.instruments import load_instrument
from src.data.sessions import SessionSpec
from src.data.timeframes import build_timeframe, expected_timeframe_schedule
from src.features.session_context import PREVIOUS_DAY_CONTEXT_ID, build_market_context
from src.liquidity.contract import (
    EQ,
    EXTENDED,
    EXTERNAL,
    FORMED,
    LOWER,
    MEMBER_COLUMNS,
    MERGED,
    REQ,
    STRUCTURE_COLUMNS,
    UPPER,
    assign_member_ids,
    assign_structure_ids,
    member_id,
    validate_liquidity_members,
    validate_liquidity_structures,
)
from src.state.contract import SPECIFIC, canonical_time

DEFINITION_VERSION = "external-liquidity-v1"
SESSION_CONTEXTS = ("asia_2000_0000", "london_0200_0500", "ny_premarket_0700_0900", "overnight_1800_0700")
STRUCTURE_TIMEFRAMES = ("1D", "4H")
TOLERANCE_TICKS = {EQ: 0, REQ: 6}

DAILY_HIGH, DAILY_LOW = "DAILY_HIGH", "DAILY_LOW"
SESSION_REFERENCE_HIGH, SESSION_REFERENCE_LOW = "SESSION_REFERENCE_HIGH", "SESSION_REFERENCE_LOW"
HTF_EQREQ_HIGH, HTF_EQREQ_LOW = "HTF_EQREQ_HIGH", "HTF_EQREQ_LOW"

# Continuity-break audit reasons, in precedence order when one boundary has several causes.
MISSING_EXPECTED_SESSION = "MISSING_EXPECTED_SESSION"
MISSING_EXPECTED_BUCKET = "MISSING_EXPECTED_BUCKET"
INCOMPLETE_BAR = "INCOMPLETE_BAR"
CONTRACT_CHANGE = "CONTRACT_CHANGE"
BREAK_PRECEDENCE = (MISSING_EXPECTED_SESSION, MISSING_EXPECTED_BUCKET, INCOMPLETE_BAR, CONTRACT_CHANGE)

PREVIOUS_DAY_REFERENCE_COLUMNS = [
    "target_trading_date", "previous_trading_date", "context_id", "field", "m5_context_ref", "member_id",
]
_SIDES = ((UPPER, "high"), (LOWER, "low"))


class ExternalLiquidityError(ValueError):
    """Raised for invalid inputs or a violated External Liquidity invariant."""


@dataclass(frozen=True)
class ExternalLiquidityResult:
    """Canonical tables plus audit tables (audit tables may carry prices: keep local)."""

    members: pd.DataFrame
    structures: pd.DataFrame
    previous_day_references: pd.DataFrame
    candidates: pd.DataFrame
    continuity_breaks: pd.DataFrame
    barrier_blocks: pd.DataFrame


def build_external_liquidity(
    bars: pd.DataFrame,
    session_spec: SessionSpec,
    *,
    instrument_id: str,
    market_context: pd.DataFrame | None = None,
    instrument_config_dir: Any = None,
    source_interval: Any = "1min",
) -> ExternalLiquidityResult:
    """Build static External Liquidity from canonical 1m bars.

    ``bars`` are canonical bar-end-labelled 1m bars (as for ``build_timeframe``).
    Daily and 4H bars come only from ``build_timeframe``; continuity uses
    ``expected_timeframe_schedule``.  ``market_context`` is the M5
    ``build_market_context`` summary for the same bars; when omitted it is
    computed.  Returns validated canonical members / structures and the
    Previous Day reference view, plus audit tables.
    """
    instrument = load_instrument(instrument_id) if instrument_config_dir is None \
        else load_instrument(instrument_id, config_dir=instrument_config_dir)
    tick = instrument.tick_size
    if market_context is None:
        market_context = build_market_context(bars, session_spec, instrument_id=instrument_id)

    member_rows: list[dict] = []
    daily = build_timeframe(bars, "1D", session_spec, source_interval=source_interval)
    daily_members = _daily_members(daily, instrument_id, tick)
    member_rows.extend(daily_members.values())
    member_rows.extend(_session_members(market_context, instrument_id, tick))

    structure_rows: list[dict] = []
    candidate_frames, break_frames, block_frames = [], [], []
    for timeframe in STRUCTURE_TIMEFRAMES:
        tf_bars = daily if timeframe == "1D" else build_timeframe(bars, timeframe, session_spec, source_interval=source_interval)
        segments, breaks = continuity_segments(tf_bars, timeframe, session_spec, source_interval=source_interval)
        break_frames.append(breaks)
        formed = _form_structures(segments, timeframe, instrument_id, tick, daily_members)
        structure_rows.extend(formed["structures"])
        member_rows.extend(formed["promoted"])
        candidate_frames.append(formed["candidates"])
        block_frames.append(formed["blocks"])

    members = validate_liquidity_members(assign_member_ids(pd.DataFrame(member_rows, columns=MEMBER_COLUMNS)))
    structures_frame = pd.DataFrame(structure_rows, columns=STRUCTURE_COLUMNS)
    structures = validate_liquidity_structures(assign_structure_ids(structures_frame), members) if structure_rows \
        else structures_frame
    references = previous_day_references(market_context, members, daily, instrument_id=instrument_id)
    return ExternalLiquidityResult(
        members=members,
        structures=structures,
        previous_day_references=references,
        candidates=pd.concat(candidate_frames, ignore_index=True),
        continuity_breaks=pd.concat(break_frames, ignore_index=True),
        barrier_blocks=pd.concat(block_frames, ignore_index=True),
    )


# ---------------------------------------------------------------------------
# EL-I2: standalone members and the Previous Day reference
# ---------------------------------------------------------------------------


def htf_source_ref(instrument_id: str, contract: str, timeframe: str, bar_end: Any) -> str:
    """Stable HTF bar provenance: ``HTF_BAR:<instrument>|<contract>|<tf>|<canonical bar_end UTC>``."""
    return f"HTF_BAR:{instrument_id}|{contract}|{timeframe}|{canonical_time(bar_end)}"


def m5_context_ref(context_id: str, field: str, target_trading_date: Any) -> str:
    return f"M5_CONTEXT:{context_id}:{field}:{pd.Timestamp(target_trading_date).date().isoformat()}"


def _daily_members(daily: pd.DataFrame, instrument_id: str, tick: Decimal) -> dict:
    """Complete Daily bars -> {(trading_date, orientation): member row}. Incomplete days give nothing."""
    out = {}
    for bar in daily.loc[daily["is_complete"]].itertuples(index=False):
        for orientation, field in _SIDES:
            price = float(getattr(bar, field))
            _ticks(price, tick)
            out[(bar.trading_date, orientation)] = _member_row(
                DAILY_HIGH if orientation == UPPER else DAILY_LOW, "1D", orientation, price,
                htf_source_ref(instrument_id, bar.contract, "1D", bar.bar_end), bar.bar_end, bar.bar_end,
                instrument_id, bar.contract,
            )
    return out


def _session_members(context: pd.DataFrame, instrument_id: str, tick: Decimal) -> list[dict]:
    rows = []
    selected = context.loc[context["context_id"].isin(SESSION_CONTEXTS) & context["is_available"].astype(bool)]
    for record in selected.itertuples(index=False):
        for orientation, field in _SIDES:
            price = float(getattr(record, f"observed_{field}"))
            _ticks(price, tick)
            rows.append(_member_row(
                SESSION_REFERENCE_HIGH if orientation == UPPER else SESSION_REFERENCE_LOW, record.context_id,
                orientation, price, m5_context_ref(record.context_id, field, record.target_trading_date),
                record.window_end, record.available_at, instrument_id, record.contract,
            ))
    return rows


def previous_day_references(
    context: pd.DataFrame,
    members: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    instrument_id: str,
) -> pd.DataFrame:
    """Derived view: M5 ``previous_day`` high/low -> canonical Daily member (no new member).

    The Daily member of M5's ``source_trading_date`` (its previous expected
    session) is looked up by deterministic id.  Raises
    ``ExternalLiquidityError`` when an available M5 Previous Day has no
    canonical Daily member or a different price; unavailable rows give none.
    """
    by_id = members.set_index("member_id")
    daily_ids = {}
    for bar in daily.loc[daily["is_complete"]].itertuples(index=False):
        for orientation, _ in _SIDES:
            daily_ids[(bar.trading_date, orientation)] = member_id(
                definition_version=DEFINITION_VERSION, liquidity_class=EXTERNAL,
                member_kind=DAILY_HIGH if orientation == UPPER else DAILY_LOW, reference_family="1D",
                orientation=orientation, instrument_id=instrument_id, contract_scope=SPECIFIC, contract=bar.contract,
                source_ref=htf_source_ref(instrument_id, bar.contract, "1D", bar.bar_end),
            )
    rows = []
    selected = context.loc[(context["context_id"] == PREVIOUS_DAY_CONTEXT_ID) & context["is_available"].astype(bool)]
    for record in selected.itertuples(index=False):
        previous_date = pd.Timestamp(record.source_trading_date).date()
        for orientation, field in _SIDES:
            mid = daily_ids.get((previous_date, orientation))
            if mid is None or mid not in by_id.index:
                raise ExternalLiquidityError(
                    f"previous_day {field} for {record.target_trading_date}: no canonical Daily member for {previous_date}"
                )
            m5_price = float(getattr(record, f"observed_{field}"))
            if float(by_id.loc[mid, "price"]) != m5_price:
                raise ExternalLiquidityError(
                    f"previous_day {field} for {record.target_trading_date}: M5 price {m5_price} != Daily member "
                    f"price {by_id.loc[mid, 'price']}"
                )
            rows.append({
                "target_trading_date": pd.Timestamp(record.target_trading_date).date(),
                "previous_trading_date": previous_date, "context_id": PREVIOUS_DAY_CONTEXT_ID, "field": field,
                "m5_context_ref": m5_context_ref(PREVIOUS_DAY_CONTEXT_ID, field, record.target_trading_date),
                "member_id": mid,
            })
    out = pd.DataFrame(rows, columns=PREVIOUS_DAY_REFERENCE_COLUMNS)
    return out.sort_values(["target_trading_date", "field"], kind="mergesort").reset_index(drop=True)


def _member_row(kind, family, orientation, price, source_ref, source_at, available_at, instrument_id, contract) -> dict:
    return {
        "member_id": None, "liquidity_class": EXTERNAL, "member_kind": kind, "reference_family": family,
        "orientation": orientation, "price": price, "source_ref": source_ref,
        "source_at": pd.Timestamp(source_at), "source_seq_domain": None, "source_seq": None,
        "available_at": pd.Timestamp(available_at), "available_seq_domain": None, "available_seq": None,
        "instrument_id": instrument_id, "contract_scope": SPECIFIC, "contract": contract,
        "definition_version": DEFINITION_VERSION,
    }


# ---------------------------------------------------------------------------
# EL-I3: continuity segments
# ---------------------------------------------------------------------------


def continuity_segments(
    tf_bars: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    *,
    source_interval: Any = "1min",
) -> tuple[list[pd.DataFrame], pd.DataFrame]:
    """Split ``build_timeframe`` output into fail-closed continuity segments.

    Walks the M3 **expected** schedule (``expected_timeframe_schedule``) from
    the first to the last observed bucket.  A segment holds consecutive
    expected buckets that are all present, all complete and of one contract.
    A missing expected session, a missing expected bucket, an incomplete bar
    or a contract change ends it.  Returns the segments (complete bars only)
    and one audit row per break boundary (reason by ``BREAK_PRECEDENCE``).
    """
    columns = ["timeframe", "break_index", "previous_bar_end", "next_bar_end", "reason",
               "missing_buckets", "missing_sessions", "incomplete_bars", "contract_changed"]
    if tf_bars.empty:
        return [], pd.DataFrame(columns=columns)
    observed = tf_bars.sort_values("bar_start", kind="mergesort").reset_index(drop=True)
    first_date, last_date = min(observed["trading_date"]), max(observed["trading_date"])
    dates = [first_date + timedelta(days=offset) for offset in range((last_date - first_date).days + 1)]
    schedule = expected_timeframe_schedule(dates, timeframe, session_spec, source_interval=source_interval).reset_index(drop=True)
    key = list(zip(schedule["trading_date"], schedule["bar_start"]))
    position = {k: i for i, k in enumerate(key)}
    observed_pos = [position.get((d, s)) for d, s in zip(observed["trading_date"], observed["bar_start"])]
    if any(p is None for p in observed_pos):
        raise ExternalLiquidityError(f"{timeframe}: an observed bar is not in the expected M3 schedule")
    by_pos = dict(zip(observed_pos, observed.itertuples(index=False)))
    dates_observed = set(observed["trading_date"])

    segments, current, breaks = [], [], []
    pending = {"missing_buckets": 0, "missing_sessions": set(), "incomplete_bars": 0}
    last_bar = None

    def close_segment():
        nonlocal current
        if current:
            segments.append(pd.DataFrame(current))
        current = []

    def record_break(next_bar, contract_changed):
        reasons = set()
        if pending["missing_sessions"]:
            reasons.add(MISSING_EXPECTED_SESSION)
        if pending["missing_buckets"]:
            reasons.add(MISSING_EXPECTED_BUCKET)
        if pending["incomplete_bars"]:
            reasons.add(INCOMPLETE_BAR)
        if contract_changed:
            reasons.add(CONTRACT_CHANGE)
        reason = next(r for r in BREAK_PRECEDENCE if r in reasons)
        breaks.append({
            "timeframe": timeframe, "break_index": len(breaks),
            "previous_bar_end": None if last_bar is None else last_bar.bar_end,
            "next_bar_end": None if next_bar is None else next_bar.bar_end, "reason": reason,
            "missing_buckets": pending["missing_buckets"], "missing_sessions": len(pending["missing_sessions"]),
            "incomplete_bars": pending["incomplete_bars"], "contract_changed": contract_changed,
        })

    for pos in range(min(observed_pos), max(observed_pos) + 1):
        bar = by_pos.get(pos)
        if bar is None or not bar.is_complete:
            close_segment()
            if bar is None:
                pending["missing_buckets"] += 1
                if schedule["trading_date"].iloc[pos] not in dates_observed:
                    pending["missing_sessions"].add(schedule["trading_date"].iloc[pos])
            else:
                pending["incomplete_bars"] += 1
            continue
        gap = pending["missing_buckets"] or pending["incomplete_bars"]
        contract_changed = last_bar is not None and bar.contract != last_bar.contract
        if last_bar is not None and (gap or contract_changed):
            close_segment()
            record_break(bar, contract_changed)
        current.append(bar._asdict())
        last_bar = bar
        pending = {"missing_buckets": 0, "missing_sessions": set(), "incomplete_bars": 0}
    close_segment()
    return segments, pd.DataFrame(breaks, columns=columns)


# ---------------------------------------------------------------------------
# EL-I3: EQ / REQ formation, promotion and structure versions
# ---------------------------------------------------------------------------


class _Components:
    """Union-find over candidate positions, tracking each component's latest emitted version."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.members = {i: {i} for i in range(n)}
        self.version = {}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] |= self.members.pop(rb)


def _form_structures(segments, timeframe, instrument_id, tick, daily_members) -> dict:
    structures, promoted, candidate_rows, blocks = [], {}, [], []
    for segment_index, segment in enumerate(segments):
        segment = segment.reset_index(drop=True)
        for orientation, field in _SIDES:
            prices = [float(value) for value in segment[field]]
            ticks = [_ticks(price, tick) for price in prices]
            # mirror lows so one "outer = max" rule serves both orientations
            values = ticks if orientation == UPPER else [-value for value in ticks]
            ids = [_candidate_member_id(segment.iloc[k], timeframe, orientation, instrument_id, daily_members)
                   for k in range(len(segment))]
            graphs = {stype: _Components(len(segment)) for stype in (EQ, REQ)}
            qualified = [False] * len(segment)
            for j in range(len(segment)):
                linked = {EQ: [], REQ: []}
                running_max = None  # outer extreme of bars strictly between i and j
                running_pos = None  # its bar; strict ">" keeps the one nearest j among equal extremes
                for i in range(j - 1, -1, -1):
                    distance = abs(values[i] - values[j])
                    blocked = running_max is not None and running_max > max(values[i], values[j])
                    for stype, tolerance in TOLERANCE_TICKS.items():
                        if distance <= tolerance:
                            if blocked:
                                blocks.append({
                                    "timeframe": timeframe, "orientation": orientation, "structure_type": stype,
                                    "segment": segment_index, "earlier_bar_end": segment["bar_end"].iloc[i],
                                    "later_bar_end": segment["bar_end"].iloc[j], "distance_ticks": distance,
                                    "blocking_bar_end": segment["bar_end"].iloc[running_pos],
                                    "blocking_excess_ticks": running_max - max(values[i], values[j]),
                                })
                            else:
                                linked[stype].append(i)
                    if running_max is None or values[i] > running_max:
                        running_max, running_pos = values[i], i
                at = segment["bar_end"].iloc[j]
                for stype in (EQ, REQ):
                    if not linked[stype]:
                        continue
                    graph = graphs[stype]
                    prior_versions = {graph.version[graph.find(i)] for i in linked[stype] if graph.find(i) in graph.version}
                    for i in linked[stype]:
                        graph.union(i, j)
                    root = graph.find(j)
                    component = sorted(graph.members[root])
                    distinct = len({ticks[k] for k in component})
                    if stype == REQ and distinct < 2:
                        continue
                    member_ids = tuple(sorted(ids[k] for k in component))
                    change = FORMED if not prior_versions else (EXTENDED if len(prior_versions) == 1 else MERGED)
                    row = {
                        "structure_id": None, "liquidity_class": EXTERNAL, "structure_type": stype,
                        "reference_family": timeframe, "orientation": orientation, "member_ids": member_ids,
                        "available_at": at, "available_seq_domain": None, "available_seq": None,
                        "instrument_id": instrument_id, "contract_scope": SPECIFIC,
                        "contract": segment["contract"].iloc[j], "change_kind": change,
                        "supersedes": tuple(sorted(prior_versions)), "definition_version": DEFINITION_VERSION,
                    }
                    row["structure_id"] = assign_structure_ids(pd.DataFrame([row]))["structure_id"].iloc[0]
                    graph.version[root] = row["structure_id"]
                    structures.append(row)
                    for k in component:
                        qualified[k] = True
                        if timeframe != "1D" and ids[k] not in promoted:
                            bar = segment.iloc[k]
                            promoted[ids[k]] = _member_row(
                                HTF_EQREQ_HIGH if orientation == UPPER else HTF_EQREQ_LOW, timeframe, orientation,
                                prices[k], htf_source_ref(instrument_id, bar["contract"], timeframe, bar["bar_end"]),
                                bar["bar_end"], at, instrument_id, bar["contract"],
                            )
            for k in range(len(segment)):
                candidate_rows.append({
                    "timeframe": timeframe, "orientation": orientation, "segment": segment_index,
                    "trading_date": segment["trading_date"].iloc[k], "bar_start": segment["bar_start"].iloc[k],
                    "bar_end": segment["bar_end"].iloc[k], "contract": segment["contract"].iloc[k],
                    "price": prices[k], "is_session_truncated": bool(segment["is_session_truncated"].iloc[k]),
                    "candidate_member_id": ids[k], "qualified": qualified[k],
                })
    return {
        "structures": structures,
        "promoted": list(promoted.values()),
        "candidates": pd.DataFrame(candidate_rows, columns=[
            "timeframe", "orientation", "segment", "trading_date", "bar_start", "bar_end", "contract", "price",
            "is_session_truncated", "candidate_member_id", "qualified"]),
        "blocks": pd.DataFrame(blocks, columns=[
            "timeframe", "orientation", "structure_type", "segment", "earlier_bar_end", "later_bar_end", "distance_ticks",
            "blocking_bar_end", "blocking_excess_ticks"]),
    }


def _candidate_member_id(bar, timeframe, orientation, instrument_id, daily_members) -> str:
    if timeframe == "1D":
        row = daily_members.get((bar["trading_date"], orientation))
        if row is None:  # segments contain only complete days, which always have members
            raise ExternalLiquidityError(f"missing Daily member for {bar['trading_date']}")
        return assign_member_ids(pd.DataFrame([row]))["member_id"].iloc[0]
    return member_id(
        definition_version=DEFINITION_VERSION, liquidity_class=EXTERNAL,
        member_kind=HTF_EQREQ_HIGH if orientation == UPPER else HTF_EQREQ_LOW, reference_family=timeframe,
        orientation=orientation, instrument_id=instrument_id, contract_scope=SPECIFIC, contract=bar["contract"],
        source_ref=htf_source_ref(instrument_id, bar["contract"], timeframe, bar["bar_end"]),
    )


def _ticks(price: float, tick: Decimal) -> int:
    """Exact integer tick index; off-grid prices raise (no epsilon comparison)."""
    quotient = Decimal(repr(float(price))) / tick
    if quotient != quotient.to_integral_value():
        raise ExternalLiquidityError(f"price {price} is not on the instrument tick grid ({tick})")
    return int(quotient)
