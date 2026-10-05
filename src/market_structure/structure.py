"""Generic Market Structure engine (MS-I2; D-139, D-140, D-141, D-142).

Specification: ``docs/project/MARKET_STRUCTURE_SPEC.md`` rev 2.5.

Per (timeframe, definition) and per continuity episode of one contract:

- **Reset-detection adapter** (§G.2a): episodes, ``DATA_GAP`` /
  ``CONTRACT_CHANGE`` resets and openings come from the M3 expected schedule
  up to an explicit, required ``replay_cutoff``.  Frozen shared continuity
  (``src.data.continuity``) is unchanged and is checked fail-closed for
  agreement; its retrospective break rows supply only opening provenance.
- **Batch post-close processing** (§F) for every complete observation N:
  classify N against the pre-state ``S_N`` → breaches at N → admissions at
  ``e(N)`` → history markers → deterministic rescan ``F_N`` → set-based
  diff materialized at ``e(N)``.
- **State** (§C.3–§C.7): episodes are M7A ``structure.direction`` entities;
  every role assignment (anchor, candidate target, protection, target) is
  its own ``structure.role`` entity.  Events are module-owned rows.

Selections are exact rescans over eligible facts (§E) implemented with
suffix "leftmost best" segment trees over swings ordered by source span.
Under one Swing definition, eligibility order equals source order for
same-orientation swings (§E.2a L0′), so the leftmost-best tie-break is the
approved N-1 / D11 order.  No Signal adapter, MSS, liquidity or hierarchy.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.continuity import (
    CONTRACT_CHANGE as CONTINUITY_CONTRACT_CHANGE,
    INCOMPLETE_BAR,
    MISSING_EXPECTED_BUCKET,
    MISSING_EXPECTED_SESSION,
    ContinuityError,
    continuity_segments,
)
from src.data.instruments import DEFAULT_INSTRUMENT_CONFIG_DIR, load_instrument
from src.data.sessions import SessionSpec
from src.data.timeframes import (
    DEFAULT_SOURCE_INTERVAL,
    TimeframeSpec,
    build_timeframe,
    expected_timeframe_schedule,
    validate_source_bars,
)
from src.market_structure.swing import LOWER, SWING_TIMEFRAMES, UPPER, SwingDefinitionSpec, bar_span_ref
from src.market_structure.swing_breaks import (
    price_ticks,
    sha256_key,
    structure_break_ref,
    swing_breaks_from_segments,
)
from src.market_structure.swing_detector import build_swing_points
from src.state.contract import (
    SPECIFIC,
    SourceRef,
    StateNamespaceSpec,
    canonical_time,
    transition_id,
    validate_transitions,
)

ENGINE_VERSION = "ms-engine-1"

# namespaces and states (§C.7)
DIRECTION_NAMESPACE = "structure.direction"
ROLE_NAMESPACE = "structure.role"
UNDEFINED, BULLISH, BEARISH, RESET = "UNDEFINED", "BULLISH", "BEARISH", "RESET"
ACTIVE = "ACTIVE"
CONSUMED, BROKEN, REPLACED, RETIRED, SUPERSEDED, ENDED = "CONSUMED", "BROKEN", "REPLACED", "RETIRED", "SUPERSEDED", "ENDED"
EXIT_PRECEDENCE = (CONSUMED, BROKEN, REPLACED, RETIRED, SUPERSEDED, ENDED)
ESTABLISHED, PROTECTION_BROKEN, DATA_GAP, CONTRACT_CHANGE = "ESTABLISHED", "PROTECTION_BROKEN", "DATA_GAP", "CONTRACT_CHANGE"

# roles (§C.4)
BULL_ANCHOR, BEAR_ANCHOR = "BULL_ANCHOR", "BEAR_ANCHOR"
BULL_CANDIDATE_TARGET, BEAR_CANDIDATE_TARGET = "BULL_CANDIDATE_TARGET", "BEAR_CANDIDATE_TARGET"
PROTECTION, TARGET = "PROTECTION", "TARGET"
ROLE_KINDS = (BULL_ANCHOR, BEAR_ANCHOR, BULL_CANDIDATE_TARGET, BEAR_CANDIDATE_TARGET, PROTECTION, TARGET)

# events, openings, anomalies (§C.3, §C.5, §C.6)
ESTABLISHMENT, BOS, CHOCH = "ESTABLISHMENT", "BOS", "CHOCH"
EVENT_KINDS = (ESTABLISHMENT, BOS, CHOCH, RESET)
DATA_START = "DATA_START"
DATA_GAP_REESTABLISHMENT = "DATA_GAP_REESTABLISHMENT"
CONTRACT_CHANGE_REESTABLISHMENT = "CONTRACT_CHANGE_REESTABLISHMENT"
OPENING_CAUSES = (DATA_START, DATA_GAP_REESTABLISHMENT, CONTRACT_CHANGE_REESTABLISHMENT)
DUAL_ESTABLISHMENT = "DUAL_ESTABLISHMENT"
GAP_REASONS = (MISSING_EXPECTED_SESSION, MISSING_EXPECTED_BUCKET, INCOMPLETE_BAR)

EPISODE_PREFIX, ROLE_PREFIX, EVENT_PREFIX, RUN_PREFIX = "se_", "sr_", "sx_", "mr_"
SWING_REF_KIND, EVENT_REF_KIND, CONTINUITY_REF_KIND = "SWING", "STRUCTURE_EVENT", "CONTINUITY_BREAK"
BULL, BEAR = "BULL", "BEAR"

EPISODE_COLUMNS = (
    "episode_id", "timeframe", "first_bar_end", "available_at", "opening_cause", "opening_ref", "previous_contract",
    "opening_contract_changed", "opening_contract_change_ref", "instrument_id", "contract_scope", "contract",
    "definition_version", "run_id",
)
ROLE_COLUMNS = (
    "role_id", "episode_id", "role_kind", "swing_id", "parent_key", "parent_role_id", "direction_context",
    "assigned_at", "available_at", "assigned_by_refs", "swing_price_ticks", "swing_available_at", "swing_source_at",
    "swing_source_end_at", "episode_opening_cause", "timeframe", "instrument_id", "contract_scope", "contract",
    "definition_version", "fact_hash", "run_id",
)
EVENT_COLUMNS = (
    "event_id", "episode_id", "kind", "direction", "pre_direction", "post_direction", "event_at", "available_at",
    "break_id", "swing_id", "reset_reason", "reset_ref", "role_refs", "transition_refs", "classification_version",
    "episode_opening_cause", "timeframe", "instrument_id", "contract_scope", "contract", "fact_hash", "run_id",
)
ANOMALY_COLUMNS = ("episode_id", "bar_end", "anomaly_kind", "evidence", "timeframe", "instrument_id", "contract",
                   "run_id")


class StructureError(ValueError):
    """Raised for invalid Market Structure inputs or internal contract violations."""


# ---------------------------------------------------------------------------
# Definition and namespaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class StructureDefinitionSpec:
    """Explicit structure definition (§C.1); no free parameters, no defaults."""

    definition_version: str
    break_definition_version: str
    swing_definition: SwingDefinitionSpec

    def __post_init__(self) -> None:
        for name in ("definition_version", "break_definition_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise StructureError(f"{name} must be a non-empty trimmed string, got {value!r}")
        if not isinstance(self.swing_definition, SwingDefinitionSpec):
            raise StructureError("swing_definition must be a SwingDefinitionSpec")


def direction_namespace(definition: StructureDefinitionSpec) -> StateNamespaceSpec:
    edges = {(UNDEFINED, BULLISH), (UNDEFINED, BEARISH), (BULLISH, UNDEFINED), (BEARISH, UNDEFINED),
             (UNDEFINED, RESET), (BULLISH, RESET), (BEARISH, RESET)}
    return StateNamespaceSpec(namespace=DIRECTION_NAMESPACE, entity_kind="structure_episode", initial_state=UNDEFINED,
                              allowed_states=(UNDEFINED, BULLISH, BEARISH, RESET), allowed_transitions=frozenset(edges),
                              definition_version=definition.definition_version, terminal_states=(RESET,))


def role_namespace(definition: StructureDefinitionSpec) -> StateNamespaceSpec:
    return StateNamespaceSpec(namespace=ROLE_NAMESPACE, entity_kind="structure_role", initial_state=ACTIVE,
                              allowed_states=(ACTIVE, *EXIT_PRECEDENCE),
                              allowed_transitions=frozenset((ACTIVE, state) for state in EXIT_PRECEDENCE),
                              definition_version=definition.definition_version, terminal_states=EXIT_PRECEDENCE)


# ---------------------------------------------------------------------------
# References and identities
# ---------------------------------------------------------------------------


def continuity_ref(timeframe: str, contract: str, at: Any) -> str:
    return SourceRef(CONTINUITY_REF_KIND, f"{timeframe}|{contract}|{canonical_time(at)}").canonical


def swing_ref(swing_id_value: str) -> str:
    return SourceRef(SWING_REF_KIND, swing_id_value).canonical


def event_ref(event_id_value: str) -> str:
    return SourceRef(EVENT_REF_KIND, event_id_value).canonical


def episode_id(definition: StructureDefinitionSpec, *, instrument_id: str, contract: str, timeframe: str,
               first_bar_end: Any) -> str:
    swing = definition.swing_definition
    return sha256_key(EPISODE_PREFIX, [definition.definition_version, swing.definition_version, swing.left_depth,
                                       swing.right_depth, instrument_id, SPECIFIC, contract, timeframe,
                                       canonical_time(first_bar_end)])


def role_id(*, episode: str, role_kind: str, swing_id_value: str, parent_key: str, assigned_at: Any) -> str:
    return sha256_key(ROLE_PREFIX, [episode, role_kind, swing_id_value, parent_key, canonical_time(assigned_at)])


def event_id(definition: StructureDefinitionSpec, *, episode: str, kind: str, direction: str | None,
             break_or_reset_ref: str) -> str:
    return sha256_key(EVENT_PREFIX, [definition.definition_version, episode, kind, direction, break_or_reset_ref])


# ---------------------------------------------------------------------------
# Reset-detection adapter (§G.2a)
# ---------------------------------------------------------------------------


@dataclass
class Episode:
    """One continuity episode of one contract, as detected by the adapter."""

    contract: str
    rows: pd.DataFrame
    opening_cause: str
    previous_contract: str | None = None
    opening_ref: str | None = None
    opening_contract_changed: bool = False
    reset_at: pd.Timestamp | None = None
    reset_reason: str | None = None
    reset_ref: str | None = None


def _schedule_timeframe(timeframe: str):
    if timeframe not in SWING_TIMEFRAMES:
        raise StructureError(f"timeframe must be one of {SWING_TIMEFRAMES}, got {timeframe!r}")
    return TimeframeSpec("1m", 1) if timeframe == "1m" else timeframe


def require_cutoff(replay_cutoff: Any) -> pd.Timestamp:
    """The explicit replay cutoff: a timezone-aware instant (no default, never inferred)."""
    if replay_cutoff is None:
        raise StructureError("replay_cutoff is required (no default; never inferred from the data)")
    stamp = pd.Timestamp(replay_cutoff)
    if stamp is pd.NaT or pd.isna(stamp) or stamp.tzinfo is None:
        raise StructureError(f"replay_cutoff must be a timezone-aware timestamp, got {replay_cutoff!r}")
    return stamp.tz_convert("UTC")


def detect_structure_episodes(
    observations: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    *,
    replay_cutoff: Any,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> list[Episode]:
    """Schedule-based episode / reset detection up to ``replay_cutoff`` (§G.2a).

    ``observations`` are the prepared target-timeframe observations (M3 shape,
    incomplete ones included).  Only observations and expected positions with
    ``bar_end <= replay_cutoff`` are evaluated.  The result is checked
    fail-closed against frozen ``continuity_segments`` (``ContinuityError``).
    """
    tf_spec = _schedule_timeframe(timeframe)
    cutoff = require_cutoff(replay_cutoff)
    obs = observations.loc[(_utc(observations["bar_end"]) <= cutoff).to_numpy()]
    if obs.empty:
        return []
    obs = obs.sort_values("bar_start", kind="mergesort").reset_index(drop=True)
    tz = session_spec.timezone
    first_date = min(obs["trading_date"])
    last_date = cutoff.tz_convert(tz).date() + timedelta(days=1)
    dates = [first_date + timedelta(days=k) for k in range((last_date - first_date).days + 1)]
    schedule = expected_timeframe_schedule(dates, tf_spec, session_spec, source_interval=source_interval)
    schedule = schedule.loc[(_utc(schedule["bar_end"]) <= cutoff).to_numpy()].reset_index(drop=True)
    position = {key: i for i, key in enumerate(zip(schedule["trading_date"], schedule["bar_start"]))}
    observed = [position.get(key) for key in zip(obs["trading_date"], obs["bar_start"])]
    if any(p is None for p in observed):
        raise ContinuityError(f"{timeframe}: an observed bar is not in the expected schedule")
    by_pos = dict(zip(observed, range(len(obs))))
    ends = list(schedule["bar_end"])
    complete = obs["is_complete"].astype(bool).to_numpy()
    contracts = obs["contract"].to_numpy()
    obs_ends = list(obs["bar_end"])

    episodes: list[Episode] = []
    active: list[int] | None = None
    current: Episode | None = None
    closed: Episode | None = None

    def finish():
        nonlocal active
        current.rows = obs.iloc[active].reset_index(drop=True)
        active = None

    for pos in range(min(observed), len(schedule)):
        row_index = by_pos.get(pos)
        valid = row_index is not None and bool(complete[row_index])
        if not valid:
            if active is not None:
                current.reset_at = pd.Timestamp(ends[pos])
                current.reset_reason = DATA_GAP
                current.reset_ref = continuity_ref(timeframe, current.contract, ends[pos])
                finish()
                closed = current
            continue
        contract = contracts[row_index]
        if active is None:
            if not episodes:
                current = Episode(contract=contract, rows=obs.iloc[[]], opening_cause=DATA_START)
            else:
                current = Episode(contract=contract, rows=obs.iloc[[]], opening_cause=DATA_GAP_REESTABLISHMENT,
                                  previous_contract=closed.contract, opening_ref=closed.reset_ref,
                                  opening_contract_changed=contract != closed.contract)
            episodes.append(current)
            active = []
        elif contract != current.contract:
            at = pd.Timestamp(obs_ends[row_index])
            current.reset_at, current.reset_reason = at, CONTRACT_CHANGE
            current.reset_ref = continuity_ref(timeframe, current.contract, at)
            finish()
            closed = current
            current = Episode(contract=contract, rows=obs.iloc[[]], opening_cause=CONTRACT_CHANGE_REESTABLISHMENT,
                              previous_contract=closed.contract, opening_ref=closed.reset_ref,
                              opening_contract_changed=True)
            episodes.append(current)
            active = []
        active.append(row_index)
    if active is not None:
        finish()
    _check_agreement(episodes, obs, tf_spec, session_spec, source_interval, timeframe)
    return episodes


def _check_agreement(episodes, obs, tf_spec, session_spec, source_interval, timeframe) -> None:
    """INV-17: adapter episodes == continuity segments; non-trailing boundaries == break rows."""
    segments, breaks = continuity_segments(obs, tf_spec, session_spec, source_interval=source_interval)
    if len(segments) != len(episodes):
        raise ContinuityError(f"{timeframe}: adapter episodes ({len(episodes)}) differ from continuity segments "
                              f"({len(segments)})")
    for episode, segment in zip(episodes, segments):
        if list(_utc(episode.rows["bar_end"])) != list(_utc(segment["bar_end"])):
            raise ContinuityError(f"{timeframe}: adapter episode differs from its continuity segment")
    if len(breaks) != max(len(episodes) - 1, 0):   # zero episodes (no complete observation) -> zero break rows
        raise ContinuityError(f"{timeframe}: {len(breaks)} continuity break rows for {len(episodes)} episodes")
    for k, brk in enumerate(breaks.itertuples(index=False), start=1):
        before, after = episodes[k - 1], episodes[k]
        if pd.Timestamp(brk.previous_bar_end) != pd.Timestamp(before.rows["bar_end"].iloc[-1]) or \
                pd.Timestamp(brk.next_bar_end) != pd.Timestamp(after.rows["bar_end"].iloc[0]):
            raise ContinuityError(f"{timeframe}: break row {k - 1} bar ends disagree with the adapter boundary")
        expected = DATA_GAP if brk.reason in GAP_REASONS else (
            CONTRACT_CHANGE if brk.reason == CONTINUITY_CONTRACT_CHANGE else None)
        if expected is None or before.reset_reason != expected:
            raise ContinuityError(f"{timeframe}: break row {k - 1} reason {brk.reason} disagrees with reset "
                                  f"{before.reset_reason}")
        if bool(brk.contract_changed) != after.opening_contract_changed:
            raise ContinuityError(f"{timeframe}: break row {k - 1} contract_changed disagrees with the opening")
    for episode in episodes[:-1]:
        if episode.reset_at is None:
            raise ContinuityError(f"{timeframe}: a non-final episode has no reset")


# ---------------------------------------------------------------------------
# Selection structures
# ---------------------------------------------------------------------------

_SENTINEL = (1 << 62, 1 << 62)


class _BestTree:
    """Point updates and "best over the suffix [lo, n)" with leftmost tie-break.

    Keys are integers where smaller is better (callers negate for maxima).
    """

    def __init__(self, n: int) -> None:
        size = 1
        while size < max(n, 1):
            size *= 2
        self.size = size
        self.tree = [_SENTINEL] * (2 * size)

    def set(self, index: int, key: int | None) -> None:
        pos = index + self.size
        self.tree[pos] = _SENTINEL if key is None else (key, index)
        pos >>= 1
        while pos:
            left, right = self.tree[2 * pos], self.tree[2 * pos + 1]
            self.tree[pos] = left if left <= right else right
            pos >>= 1

    def best(self, lo: int) -> int | None:
        left, right = lo + self.size, 2 * self.size
        result = _SENTINEL
        while left < right:
            if left & 1:
                result = min(result, self.tree[left])
                left += 1
            if right & 1:
                right -= 1
                result = min(result, self.tree[right])
            left >>= 1
            right >>= 1
        return None if result == _SENTINEL else result[1]


class _Swing:
    __slots__ = ("swing_id", "orientation", "price", "a", "b", "av", "brk", "break_id", "row", "index")

    def __init__(self, swing_id_value, orientation, price, a, b, av, brk, break_id_value, row):
        self.swing_id, self.orientation, self.price = swing_id_value, orientation, price
        self.a, self.b, self.av, self.brk, self.break_id, self.row = a, b, av, brk, break_id_value, row
        self.index = -1


class _Side:
    """One orientation of one episode: swings ordered by source span plus a best-tree."""

    def __init__(self, swings: list[_Swing], orientation: str) -> None:
        self.orientation = orientation
        self.swings = sorted(swings, key=lambda s: (s.a, s.b, s.swing_id))
        for index, swing in enumerate(self.swings):
            swing.index = index
        self.a = [s.a for s in self.swings]
        self.b = [s.b for s in self.swings]
        self.tree = _BestTree(len(self.swings))

    def key(self, swing: _Swing) -> int:
        return -swing.price if self.orientation == UPPER else swing.price

    def admit(self, swing: _Swing) -> None:
        self.tree.set(swing.index, self.key(swing))

    def remove(self, swing: _Swing) -> None:
        self.tree.set(swing.index, None)

    def best_from(self, lo: int) -> _Swing | None:
        if lo >= len(self.swings):
            return None
        found = self.tree.best(lo)
        return None if found is None else self.swings[found]

    def best_after(self, ref: _Swing) -> _Swing | None:
        """Best alive swing strictly after ``ref``'s span (``a > ref.b``)."""
        return self.best_from(bisect_right(self.a, ref.b))

    def best_in_scope(self, scope_a: int) -> _Swing | None:
        return self.best_from(bisect_left(self.a, scope_a))

    def best_since(self, baseline: _Swing, expansion: int) -> _Swing | None:
        """Best alive swing after the baseline span that reaches the expansion (``b >= E``)."""
        return self.best_from(max(bisect_right(self.a, baseline.b), bisect_left(self.b, expansion)))


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class _Role:
    role_id: str
    kind: str
    swing: _Swing
    parent_key: str
    assigned_pos: int
    parent_role_id: str | None = None


@dataclass
class _Output:
    episodes: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    events: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)
    direction_transitions: list = field(default_factory=list)
    role_transitions: list = field(default_factory=list)


_OPPOSITE = {BULLISH: BEARISH, BEARISH: BULLISH}
_SIDE_DIRECTION = {BULL: BULLISH, BEAR: BEARISH}


class _EpisodeEngine:
    """Batch processing of one episode (§F)."""

    def __init__(self, ctx: dict, episode: Episode, episode_key: str, swings: list[_Swing], out: _Output) -> None:
        self.ctx, self.episode, self.episode_id, self.out = ctx, episode, episode_key, out
        rows = episode.rows
        self.ends = list(rows["bar_end"])
        self.closes = price_ticks(rows["close"].to_numpy(), ctx["tick"])
        self.upper = _Side([s for s in swings if s.orientation == UPPER], UPPER)
        self.lower = _Side([s for s in swings if s.orientation == LOWER], LOWER)
        self.admit_at: dict[int, list[_Swing]] = {}
        self.breach_at: dict[int, list[_Swing]] = {}
        for swing in swings:
            self.admit_at.setdefault(swing.av, []).append(swing)
            if swing.brk is not None:
                self.breach_at.setdefault(swing.brk, []).append(swing)
        self.direction = UNDEFINED
        self.roles: dict[str, _Role] = {}           # role kind -> active role (uniqueness, K-10)
        self.scope_a, self.scope_key = 0, episode_key
        self.choch_pos: int | None = None
        self.expansion: int | None = None
        self.baseline: _Swing | None = None
        self.leg_event: str | None = None
        self.protection: tuple[_Swing, str] | None = None   # (swing, promotion event id)

    # -- helpers -------------------------------------------------------------------------------
    def side_of(self, orientation):
        return self.upper if orientation == UPPER else self.lower

    def trigger(self, pos: int) -> str:
        ctx = self.ctx
        return bar_span_ref(instrument_id=ctx["instrument_id"], contract=self.episode.contract,
                            timeframe=ctx["timeframe"], first_bar_end=self.ends[pos], last_bar_end=self.ends[pos])

    def pullback(self, side: str, reference: _Swing) -> _Swing | None:
        """Deepest eligible pullback strictly after ``reference`` (trees still hold the s(N) set)."""
        return (self.lower if side == BULL else self.upper).best_after(reference)

    def run(self) -> None:
        for pos in range(len(self.ends)):
            self.batch(pos)
        if self.episode.reset_at is not None:
            self.reset()

    # -- one post-close batch ---------------------------------------------------------------------
    def batch(self, pos: int) -> None:
        close = int(self.closes[pos])
        pre_roles = dict(self.roles)
        reasons: dict[str, set] = {}
        read: set[str] = set()
        event = None   # (kind, direction, pre, post, swing)
        anomaly = None
        consumed: set[str] = set()
        replaced_by: _Swing | None = None

        def flag(role: _Role | None, reason: str):
            if role is not None:
                reasons.setdefault(role.role_id, set()).add(reason)

        # (a) classify N against S_N
        if self.direction == UNDEFINED:
            qualified = {}
            for side, anchor_kind, target_kind in ((BULL, BULL_ANCHOR, BULL_CANDIDATE_TARGET),
                                                   (BEAR, BEAR_ANCHOR, BEAR_CANDIDATE_TARGET)):
                anchor = self.roles.get(anchor_kind)
                if anchor is None:
                    continue
                if (side == BULL and close < anchor.swing.price) or (side == BEAR and close > anchor.swing.price):
                    flag(anchor, BROKEN)   # D14 invalidation
                    continue
                target = self.roles.get(target_kind)
                if target is None:
                    continue
                if (side == BULL and close > target.swing.price) or (side == BEAR and close < target.swing.price):
                    pstar = self.pullback(side, target.swing)
                    ok = pstar is not None and (
                        pstar.price > anchor.swing.price if side == BULL else pstar.price < anchor.swing.price)
                    if ok and self.choch_pos is not None:
                        ok = pstar.a > self.choch_pos   # freshness: source_at > e(X)
                    qualified[side] = (ok, anchor, target, pstar)
            winners = [side for side, item in qualified.items() if item[0]]
            for side, (ok, anchor, target, pstar) in qualified.items():
                if not (ok and len(winners) == 1):
                    flag(target, RETIRED)   # K-4 / K-8 failure, or K-11 anomaly
            if len(winners) == 1:
                side = winners[0]
                _, anchor, target, pstar = qualified[side]
                direction = _SIDE_DIRECTION[side]
                event = (ESTABLISHMENT, direction, UNDEFINED, direction, target.swing)
                flag(target, CONSUMED)
                consumed.add(target.role_id)
                read.update({anchor.role_id, target.role_id})
                establish = (direction, target.swing, pstar)
            elif len(winners) == 2:
                anomaly = {side: qualified[side] for side in winners}
                establish = None
            else:
                establish = None
        else:
            protection = self.roles[PROTECTION]
            target = self.roles.get(TARGET)
            bull = self.direction == BULLISH
            establish = None
            if (bull and close < protection.swing.price) or (not bull and close > protection.swing.price):
                event = (CHOCH, _OPPOSITE[self.direction], self.direction, UNDEFINED, protection.swing)
                flag(protection, BROKEN)
                read.add(protection.role_id)
                if target is not None:
                    read.add(target.role_id)
            elif target is not None and ((bull and close > target.swing.price) or
                                         (not bull and close < target.swing.price)):
                event = (BOS, self.direction, self.direction, self.direction, target.swing)
                flag(target, CONSUMED)
                consumed.add(target.role_id)
                read.update({protection.role_id, target.role_id})
                pstar = self.pullback(BULL if bull else BEAR, target.swing)
                if pstar is not None and ((bull and pstar.price > protection.swing.price) or
                                          (not bull and pstar.price < protection.swing.price)):
                    replaced_by = pstar
                    flag(protection, REPLACED)

        event_key = None
        if event is not None:
            kind, direction, _, _, broken = event
            if broken.brk != pos or broken.break_id is None:
                raise StructureError(f"{broken.swing_id}: classified break at {self.ends[pos]} has no matching "
                                     "swing_breaks row")
            event_key = event_id(self.ctx["definition"], episode=self.episode_id, kind=kind, direction=direction,
                                 break_or_reset_ref=broken.break_id)

        # (b) breaches at N, (c) admissions at e(N)
        for swing in self.breach_at.get(pos, ()):
            self.side_of(swing.orientation).remove(swing)
        admitted = self.admit_at.get(pos, ())
        for swing in admitted:
            if swing.brk is not None and swing.brk <= pos:
                raise StructureError(f"{swing.swing_id}: breached before admission")
            self.side_of(swing.orientation).admit(swing)

        # (d) history markers
        if event is not None:
            kind, direction = event[0], event[1]
            if kind == ESTABLISHMENT:
                _, consumed_swing, pstar = establish
                self.direction = direction
                self.baseline, self.expansion, self.leg_event = consumed_swing, pos, event_key
                self.protection = (pstar, event_key)
            elif kind == BOS:
                self.baseline, self.expansion, self.leg_event = event[4], pos, event_key
                if replaced_by is not None:
                    self.protection = (replaced_by, event_key)
            elif kind == CHOCH:
                self.direction = UNDEFINED
                self.scope_a, self.scope_key, self.choch_pos = event[4].a, event_key, pos
                self.baseline = self.expansion = self.leg_event = self.protection = None

        if event is None and anomaly is None and not admitted and not reasons and pos not in self.breach_at:
            return  # nothing can change the selection

        # (e) final roles F_N by deterministic rescan
        desired: list[tuple[str, _Swing, str, str | None]] = []   # (kind, swing, parent_key, parent_role_id)
        new_roles: dict[str, _Role] = {}

        def place(kind, swing, parent_key, parent_role_id=None):
            old = self.roles.get(kind)
            if old is not None and old.swing is swing and old.parent_key == parent_key:
                new_roles[kind] = old
            else:
                new_roles[kind] = _Role(role_id(episode=self.episode_id, role_kind=kind, swing_id_value=swing.swing_id,
                                                parent_key=parent_key, assigned_at=self.ends[pos]),
                                        kind, swing, parent_key, pos, parent_role_id)
            return new_roles[kind]

        if self.direction == UNDEFINED:
            for anchor_kind, target_kind, anchor_side, target_side in (
                    (BULL_ANCHOR, BULL_CANDIDATE_TARGET, self.lower, self.upper),
                    (BEAR_ANCHOR, BEAR_CANDIDATE_TARGET, self.upper, self.lower)):
                anchor_swing = anchor_side.best_in_scope(self.scope_a)
                if anchor_swing is None:
                    continue
                anchor = place(anchor_kind, anchor_swing, self.scope_key)
                target_swing = target_side.best_after(anchor_swing)
                if target_swing is not None:
                    place(target_kind, target_swing, anchor.role_id, anchor.role_id)
        else:
            swing, promotion = self.protection
            place(PROTECTION, swing, promotion)
            bull = self.direction == BULLISH
            candidate = (self.upper if bull else self.lower).best_since(self.baseline, self.expansion)
            if candidate is not None and ((bull and candidate.price > self.baseline.price) or
                                          (not bull and candidate.price < self.baseline.price)):
                place(TARGET, candidate, self.leg_event)

        # (f) materialize diff(S_N, F_N) at e(N)
        exits = [role for kind, role in pre_roles.items() if new_roles.get(kind) is not role]
        created = [role for kind, role in new_roles.items() if pre_roles.get(kind) is not role]
        for role in exits:
            if self._superseded(role, new_roles.get(role.kind)):
                flag(role, SUPERSEDED)
        trigger = self.trigger(pos)
        batch_refs = []
        if event is not None:
            batch_refs.append(event_ref(event_key))
        transition_ids = []
        for role in sorted(exits, key=lambda r: r.role_id):
            state = next(s for s in EXIT_PRECEDENCE if s in reasons.get(role.role_id, {ENDED}) or s == ENDED)
            refs = [swing_ref(role.swing.swing_id), *batch_refs]
            if role.swing.brk == pos:
                refs.append(structure_break_ref(role.swing.break_id))
            successor = new_roles.get(role.kind)
            if state in (SUPERSEDED, REPLACED) and successor is not None:
                refs.append(swing_ref(successor.swing.swing_id))
            transition_ids.append(self.role_exit(role, state, self.ends[pos], trigger, refs))
        for role in sorted(created, key=lambda r: r.role_id):
            self.emit_role(role, trigger, [swing_ref(role.swing.swing_id), *batch_refs])
        self.roles = new_roles

        if event is not None:
            kind, direction, pre, post, broken = event
            if pre != post:
                refs = [structure_break_ref(broken.break_id), event_ref(event_key), swing_ref(broken.swing_id)]
                transition_ids.append(self.direction_transition(pre, post, self.ends[pos], trigger, refs,
                                                                ESTABLISHED if kind == ESTABLISHMENT else PROTECTION_BROKEN))
            self.emit_event(event_key, kind, direction, pre, post, self.ends[pos], broken,
                            sorted(read | {r.role_id for r in exits} | {r.role_id for r in created}),
                            sorted(transition_ids))
        if anomaly is not None:
            evidence = {side: {"anchor": item[1].swing.swing_id, "candidate_target": item[2].swing.swing_id,
                               "pullback": item[3].swing_id if item[3] is not None else None,
                               "break_id": item[2].swing.break_id}
                        for side, item in sorted(anomaly.items())}
            self.out.anomalies.append({"episode_id": self.episode_id, "bar_end": self.ends[pos],
                                       "anomaly_kind": DUAL_ESTABLISHMENT,
                                       "evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                                       "timeframe": self.ctx["timeframe"], "instrument_id": self.ctx["instrument_id"],
                                       "contract": self.episode.contract})

    def _superseded(self, role: _Role, successor: _Role | None) -> bool:
        """A strictly more extreme selection of the same kind (same anchor for candidate targets; K-7, D14)."""
        if successor is None or successor.swing is role.swing or role.kind == PROTECTION:
            return False
        if role.kind in (BULL_CANDIDATE_TARGET, BEAR_CANDIDATE_TARGET) and successor.parent_key != role.parent_key:
            return False
        new, old = successor.swing.price, role.swing.price
        if role.kind == TARGET:
            return new > old if self.direction == BULLISH else new < old
        lower_is_more = role.kind in (BULL_ANCHOR, BEAR_CANDIDATE_TARGET)
        return new < old if lower_is_more else new > old

    def reset(self) -> None:
        episode = self.episode
        at, ref = episode.reset_at, episode.reset_ref
        key = event_id(self.ctx["definition"], episode=self.episode_id, kind=RESET, direction=None,
                       break_or_reset_ref=ref)
        transition_ids = []
        for role in sorted(self.roles.values(), key=lambda r: r.role_id):
            transition_ids.append(self.role_exit(role, ENDED, at, ref, [swing_ref(role.swing.swing_id), event_ref(key)]))
        transition_ids.append(self.direction_transition(self.direction, RESET, at, ref, [event_ref(key)],
                                                        episode.reset_reason))
        self.emit_event(key, RESET, None, self.direction, RESET, at, None,
                        sorted(r.role_id for r in self.roles.values()), sorted(transition_ids),
                        reset=(episode.reset_reason, ref))
        self.roles = {}
        self.direction = RESET

    # -- emitters ---------------------------------------------------------------------------------
    def role_exit(self, role: _Role, state: str, at, trigger: str, refs: list[str]) -> str:
        ctx = self.ctx
        tid = transition_id(namespace=ROLE_NAMESPACE, definition_version=ctx["definition"].definition_version,
                            entity_id=role.role_id, previous_state=ACTIVE, new_state=state, transition_at=at,
                            trigger_ref=trigger, source_refs=refs)
        self.out.role_transitions.append(self.transition_row(tid, ROLE_NAMESPACE, role.role_id, ACTIVE, state, at,
                                                             trigger, refs, None))
        return tid

    def direction_transition(self, previous: str, new: str, at, trigger: str, refs: list[str], reason: str) -> str:
        ctx = self.ctx
        tid = transition_id(namespace=DIRECTION_NAMESPACE, definition_version=ctx["definition"].definition_version,
                            entity_id=self.episode_id, previous_state=previous, new_state=new, transition_at=at,
                            trigger_ref=trigger, source_refs=refs)
        self.out.direction_transitions.append(self.transition_row(tid, DIRECTION_NAMESPACE, self.episode_id, previous,
                                                                  new, at, trigger, refs, reason))
        return tid

    def transition_row(self, tid, namespace, entity, previous, new, at, trigger, refs, reason) -> dict:
        ctx = self.ctx
        return {"transition_id": tid, "namespace": namespace, "entity_id": entity, "previous_state": previous,
                "new_state": new, "transition_at": at, "transition_seq_domain": None, "transition_seq": None,
                "available_at": at, "available_seq_domain": None, "available_seq": None,
                "instrument_id": ctx["instrument_id"], "contract_scope": SPECIFIC, "contract": self.episode.contract,
                "definition_version": ctx["definition"].definition_version, "trigger_ref": trigger,
                "source_refs": tuple(sorted(set(refs))), "reason_code": reason}

    def emit_role(self, role: _Role, trigger: str, refs: list[str]) -> None:
        ctx, swing = self.ctx, role.swing
        if role.kind in (BULL_ANCHOR, BULL_CANDIDATE_TARGET):
            context = BULLISH
        elif role.kind in (BEAR_ANCHOR, BEAR_CANDIDATE_TARGET):
            context = BEARISH
        else:
            context = self.direction
        row = swing.row
        facts = [swing.price, canonical_time(row.available_at), canonical_time(row.source_at),
                 canonical_time(row.source_end_at)]
        self.out.roles.append({
            "role_id": role.role_id, "episode_id": self.episode_id, "role_kind": role.kind, "swing_id": swing.swing_id,
            "parent_key": role.parent_key, "parent_role_id": role.parent_role_id, "direction_context": context,
            "assigned_at": self.ends[role.assigned_pos], "available_at": self.ends[role.assigned_pos],
            "assigned_by_refs": tuple(sorted({trigger, *refs})), "swing_price_ticks": swing.price,
            "swing_available_at": row.available_at, "swing_source_at": row.source_at,
            "swing_source_end_at": row.source_end_at, "episode_opening_cause": self.episode.opening_cause,
            "timeframe": ctx["timeframe"], "instrument_id": ctx["instrument_id"], "contract_scope": SPECIFIC,
            "contract": self.episode.contract, "definition_version": ctx["definition"].definition_version,
            "fact_hash": sha256_key("", facts),
        })

    def emit_event(self, key, kind, direction, pre, post, at, broken: _Swing | None, role_refs, transition_refs,
                   reset=None) -> None:
        ctx = self.ctx
        if broken is not None:
            close = int(self.closes[broken.brk])
            facts = [broken.price, close, canonical_time(at)]
        else:
            facts = [reset[1]]
        self.out.events.append({
            "event_id": key, "episode_id": self.episode_id, "kind": kind, "direction": direction,
            "pre_direction": pre, "post_direction": post, "event_at": at, "available_at": at,
            "break_id": broken.break_id if broken is not None else None,
            "swing_id": broken.swing_id if broken is not None else None,
            "reset_reason": reset[0] if reset else None, "reset_ref": reset[1] if reset else None,
            "role_refs": tuple(role_refs), "transition_refs": tuple(transition_refs),
            "classification_version": ctx["definition"].definition_version,
            "episode_opening_cause": self.episode.opening_cause, "timeframe": ctx["timeframe"],
            "instrument_id": ctx["instrument_id"], "contract_scope": SPECIFIC, "contract": self.episode.contract,
            "fact_hash": sha256_key("", facts),
        })


# ---------------------------------------------------------------------------
# Public runners
# ---------------------------------------------------------------------------


@dataclass
class MarketStructureRun:
    """All outputs of one run (one timeframe, one definition, one replay cutoff)."""

    manifest: dict
    swings: pd.DataFrame
    swing_breaks: pd.DataFrame
    episodes: pd.DataFrame
    roles: pd.DataFrame
    events: pd.DataFrame
    anomalies: pd.DataFrame
    direction_transitions: pd.DataFrame
    role_transitions: pd.DataFrame
    direction_entities: pd.DataFrame
    role_entities: pd.DataFrame
    observations: pd.DataFrame = field(repr=False, default=None)
    episode_segments: list = field(repr=False, default_factory=list)

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]


def build_market_structure(
    bars: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    definition: StructureDefinitionSpec,
    *,
    instrument_id: str,
    replay_cutoff: Any,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
) -> MarketStructureRun:
    """End-to-end run from canonical 1m source bars up to ``replay_cutoff``.

    Source bars ending after the cutoff are never read.  Observations come
    from M3 ``build_timeframe`` (``TimeframeSpec("1m", 1)`` for 1m) and swings
    from the frozen ``build_swing_points``, both on the truncated source.
    """
    cutoff = require_cutoff(replay_cutoff)
    source = validate_source_bars(bars)
    source = source.loc[source.index <= cutoff]
    if source.empty:
        raise StructureError("no source bars at or before replay_cutoff")
    observations = build_timeframe(source, _schedule_timeframe(timeframe), session_spec, source_interval=source_interval)
    swings = build_swing_points(source, timeframe, session_spec, definition.swing_definition,
                                instrument_id=instrument_id, instrument_config_dir=instrument_config_dir,
                                source_interval=source_interval)
    fingerprint = hashlib.sha256(pd.util.hash_pandas_object(source[["open", "high", "low", "close", "volume", "contract"]],
                                                            index=True).to_numpy().tobytes()).hexdigest()
    return run_market_structure(observations, swings, timeframe, session_spec, definition, instrument_id=instrument_id,
                                replay_cutoff=cutoff, instrument_config_dir=instrument_config_dir,
                                source_interval=source_interval, source_fingerprint=fingerprint)


def run_market_structure(
    observations: pd.DataFrame,
    swings: pd.DataFrame,
    timeframe: str,
    session_spec: SessionSpec,
    definition: StructureDefinitionSpec,
    *,
    instrument_id: str,
    replay_cutoff: Any,
    instrument_config_dir: str | Path = DEFAULT_INSTRUMENT_CONFIG_DIR,
    source_interval: Any = DEFAULT_SOURCE_INTERVAL,
    source_fingerprint: str | None = None,
) -> MarketStructureRun:
    """Run the engine on prepared observations and canonical swings of one timeframe."""
    if not isinstance(definition, StructureDefinitionSpec):
        raise StructureError("definition must be a StructureDefinitionSpec")
    cutoff = require_cutoff(replay_cutoff)
    swing_def = definition.swing_definition
    if not swings.empty:
        if (swings["timeframe"] != timeframe).any() or (swings["instrument_id"] != instrument_id).any():
            raise StructureError("swings must belong to the requested timeframe and instrument")
        if ((swings["definition_version"] != swing_def.definition_version)
                | (swings["left_depth"] != swing_def.left_depth) | (swings["right_depth"] != swing_def.right_depth)).any():
            raise StructureError("swings do not match the structure's swing_definition")
    if not swings.empty:
        swings = swings.loc[(_utc(swings["available_at"]) <= cutoff).to_numpy()].reset_index(drop=True)
    tick = Decimal(str(load_instrument(instrument_id, instrument_config_dir).tick_size))
    episodes = detect_structure_episodes(observations, timeframe, session_spec, replay_cutoff=cutoff,
                                         source_interval=source_interval)
    segments = [episode.rows for episode in episodes]
    breaks = swing_breaks_from_segments(swings, segments, timeframe=timeframe,
                                        break_definition_version=definition.break_definition_version,
                                        instrument_id=instrument_id, tick_size=tick)
    ctx = {"definition": definition, "timeframe": timeframe, "instrument_id": instrument_id, "tick": tick}
    out = _Output()

    locate: dict[int, tuple[int, int]] = {}
    for k, episode in enumerate(episodes):
        for position, end in enumerate(_utc(episode.rows["bar_end"])):
            locate[end.value] = (k, position)
    break_of = {r.swing_id: r for r in breaks.itertuples(index=False)}
    per_episode: list[list[_Swing]] = [[] for _ in episodes]
    levels = price_ticks(swings["price"].to_numpy(), tick) if not swings.empty else []
    for row, level in zip(swings.itertuples(index=False), levels):
        a = locate.get(pd.Timestamp(row.source_at).value)
        b = locate.get(pd.Timestamp(row.source_end_at).value)
        av = locate.get(pd.Timestamp(row.available_at).value)
        if a is None or b is None or av is None or not (a[0] == b[0] == av[0]):
            raise StructureError(f"{row.swing_id}: swing span and confirmation are not inside one episode")
        if episodes[a[0]].contract != row.contract:
            raise StructureError(f"{row.swing_id}: swing contract differs from its episode")
        brk = break_of.get(row.swing_id)
        brk_pos = None
        if brk is not None:
            located = locate.get(pd.Timestamp(brk.bar_end).value)
            if located is None or located[0] != a[0]:
                raise StructureError(f"{row.swing_id}: break observation outside the swing's episode")
            brk_pos = located[1]
        per_episode[a[0]].append(_Swing(row.swing_id, row.orientation, int(level), a[1], b[1], av[1], brk_pos,
                                        brk.break_id if brk is not None else None, row))

    for k, episode in enumerate(episodes):
        first = episode.rows["bar_end"].iloc[0]
        key = episode_id(definition, instrument_id=instrument_id, contract=episode.contract, timeframe=timeframe,
                         first_bar_end=first)
        change_ref = None
        if episode.opening_contract_changed:
            change_ref = bar_span_ref(instrument_id=instrument_id, contract=episode.contract, timeframe=timeframe,
                                      first_bar_end=first, last_bar_end=first)
        out.episodes.append({
            "episode_id": key, "timeframe": timeframe, "first_bar_end": first, "available_at": first,
            "opening_cause": episode.opening_cause, "opening_ref": episode.opening_ref,
            "previous_contract": episode.previous_contract,
            "opening_contract_changed": bool(episode.opening_contract_changed),
            "opening_contract_change_ref": change_ref, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
            "contract": episode.contract, "definition_version": definition.definition_version,
        })
        _EpisodeEngine(ctx, episode, key, per_episode[k], out).run()

    manifest = {
        "engine_version": ENGINE_VERSION,
        "instrument_id": instrument_id,
        "timeframe": timeframe,
        "definition_version": definition.definition_version,
        "break_definition_version": definition.break_definition_version,
        "swing_definition": [swing_def.definition_version, swing_def.left_depth, swing_def.right_depth],
        "replay_cutoff": canonical_time(cutoff),
        "tick_size": str(tick),
        "session": [session_spec.session_id, session_spec.timezone, str(session_spec.calendar_coverage),
                    sorted(str(o) for o in session_spec.overrides.values())],
        "source_fingerprint": source_fingerprint,
        "observation_fingerprint": _frame_hash(observations, ["bar_start", "bar_end", "open", "high", "low", "close",
                                                              "contract", "is_complete"]),
        "swing_fingerprint": _frame_hash(swings, ["swing_id", "price", "available_at"]) if not swings.empty else None,
    }
    manifest["run_id"] = sha256_key(RUN_PREFIX, [manifest[k] for k in sorted(manifest)])
    run_id = manifest["run_id"]

    episodes_frame = _frame(out.episodes, EPISODE_COLUMNS, run_id, ("first_bar_end", "available_at"))
    roles_frame = _frame(out.roles, ROLE_COLUMNS, run_id, ("assigned_at", "available_at", "swing_available_at",
                                                           "swing_source_at", "swing_source_end_at"))
    events_frame = _frame(out.events, EVENT_COLUMNS, run_id, ("event_at", "available_at"))
    anomalies_frame = _frame(out.anomalies, ANOMALY_COLUMNS, run_id, ("bar_end",))
    direction_entities = pd.DataFrame({
        "entity_id": episodes_frame["episode_id"], "available_at": episodes_frame["available_at"],
        "valid_from": pd.NaT, "valid_until": pd.NaT, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
        "contract": episodes_frame["contract"]})
    role_entities = pd.DataFrame({
        "entity_id": roles_frame["role_id"], "available_at": roles_frame["assigned_at"],
        "valid_from": pd.NaT, "valid_until": pd.NaT, "instrument_id": instrument_id, "contract_scope": SPECIFIC,
        "contract": roles_frame["contract"]})
    for frame in (direction_entities, role_entities):
        for column in ("valid_from", "valid_until"):
            frame[column] = pd.Series([pd.NaT] * len(frame), dtype="datetime64[ns, UTC]")
    direction_transitions = _transitions(out.direction_transitions)
    role_transitions = _transitions(out.role_transitions)
    direction_transitions = validate_transitions(direction_transitions, direction_namespace(definition), direction_entities)
    role_transitions = validate_transitions(role_transitions, role_namespace(definition), role_entities)
    for frame in (direction_transitions, role_transitions):
        frame["run_id"] = run_id
    breaks = breaks.copy()
    breaks["run_id"] = run_id
    (breaks, episodes_frame, roles_frame, events_frame, anomalies_frame, direction_transitions,
     role_transitions) = (_text_as_object(frame) for frame in (breaks, episodes_frame, roles_frame, events_frame,
                                                               anomalies_frame, direction_transitions, role_transitions))
    return MarketStructureRun(manifest=manifest, swings=swings, swing_breaks=breaks, episodes=episodes_frame,
                              roles=roles_frame, events=events_frame, anomalies=anomalies_frame,
                              direction_transitions=direction_transitions, role_transitions=role_transitions,
                              direction_entities=direction_entities, role_entities=role_entities,
                              observations=observations, episode_segments=segments)


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


def _utc(values: Any) -> pd.Series:
    return pd.to_datetime(pd.Series(values).reset_index(drop=True), utc=True)


def _text_as_object(frame: pd.DataFrame) -> pd.DataFrame:
    """Content-independent dtypes: every text column is ``object`` (pandas may otherwise infer ``str``)."""
    frame = frame.copy()
    for column in frame.columns:
        if pd.api.types.is_string_dtype(frame[column].dtype) and not isinstance(frame[column].dtype, pd.CategoricalDtype):
            values = frame[column].astype(object)
            frame[column] = values.where(frame[column].notna().to_numpy(), None)
    return frame


def _frame_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame is None or frame.empty:
        return sha256_key("", [])
    work = frame[columns].copy()
    for column in work.columns:
        if isinstance(work[column].dtype, pd.DatetimeTZDtype):
            work[column] = work[column].dt.tz_convert("UTC")
    return hashlib.sha256(pd.util.hash_pandas_object(work, index=False).to_numpy().tobytes()).hexdigest()


def _frame(rows: list[dict], columns: tuple[str, ...], run_id: str, times: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=[c for c in columns if c != "run_id"])
    for column in times:
        frame[column] = pd.to_datetime(frame[column], utc=True) if len(frame) else pd.Series(
            dtype="datetime64[ns, UTC]")
    frame["run_id"] = run_id
    frame = frame[list(columns)]
    sort = [c for c in ("available_at", "bar_end", "role_id", "event_id", "episode_id") if c in frame.columns]
    return frame.sort_values(sort, kind="mergesort").reset_index(drop=True) if len(frame) else frame


def _transitions(rows: list[dict]) -> pd.DataFrame:
    columns = ["transition_id", "namespace", "entity_id", "previous_state", "new_state", "transition_at",
               "transition_seq_domain", "transition_seq", "available_at", "available_seq_domain", "available_seq",
               "instrument_id", "contract_scope", "contract", "definition_version", "trigger_ref", "source_refs",
               "reason_code"]
    frame = pd.DataFrame(rows, columns=columns)
    for column in ("transition_at", "available_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True) if len(frame) else pd.Series(
            dtype="datetime64[ns, UTC]")
    return frame
