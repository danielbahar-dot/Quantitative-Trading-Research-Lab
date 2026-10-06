"""Synthetic Internal Liquidity scenarios: injected atoms / External tables over a canonical 1m tape.

Prices are relative to ``BASE`` (20,000.00); ``k`` indexes expected 1m slots (``slot_end(k, "1m")``).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

import pandas as pd

from ms_fixtures import BASE, CONTRACT, DAYS, SPEC, ohlc_bars, schedule
from src.liquidity.consumption import build_minute_tape
from src.liquidity.contract import EQ, EXTENDED, EXTERNAL, FORMED, INTERNAL, LOWER, MERGED, REQ, UPPER
from src.liquidity.internal_formation import InternalFormationResult
from src.liquidity.internal_liquidity import run_internal_liquidity

TICK = Decimal("0.25")
FLAT = (50, 50.25, 49.75, 50)


def ticks(price: float) -> int:
    return int(round((BASE + price) / 0.25))


@lru_cache(maxsize=None)
def _minute_ends() -> tuple:
    return tuple(pd.to_datetime(schedule("1m", DAYS[:3])["bar_end"]).dt.tz_convert("UTC"))


def at(k: int) -> pd.Timestamp:
    if k < 0:
        raise IndexError(k)
    return _minute_ends()[k]


def flat_rows(n: int, changes: dict | None = None) -> list:
    rows = [FLAT] * n
    for k, row in (changes or {}).items():
        rows[k] = row
    return rows


class Scenario:
    def __init__(self, rows, *, contracts=None, absent=(), cutoff_k=None):
        self.rows = list(rows)
        self.contracts = contracts
        self.absent = set(absent)
        self.cutoff_k = len(self.rows) - 1 if cutoff_k is None else cutoff_k
        self.i_members, self.i_structures, self.spans = [], [], {}
        self.x_members, self.x_structures = [], []

    def contract_at(self, k):
        return self.contracts[k] if self.contracts else CONTRACT

    # ---- internal atoms ------------------------------------------------------------------------
    def swing(self, name, side, price, k, *, tf="5m", span=None):
        kind = "INTERNAL_SWING_HIGH" if side == UPPER else "INTERNAL_SWING_LOW"
        self._member(self.i_members, name, kind, tf, side, price, k, INTERNAL)
        a, b = span if span is not None else (k - 2, k - 2)
        self.spans[name] = (at(a - 1).value, at(b).value, tf)
        return name

    def candle(self, name, side, price, k, *, span=None):
        kind = "INTERNAL_CANDLE_HIGH" if side == UPPER else "INTERNAL_CANDLE_LOW"
        self._member(self.i_members, name, kind, "1H", side, price, k, INTERNAL)
        a, b = span if span is not None else (k - 2, k)
        self.spans[name] = (at(a - 1).value, at(b).value, "1H")
        return name

    def structure(self, name, stype, side, members, k, *, tf="5m", change=FORMED, supersedes=()):
        self._structure(self.i_structures, name, stype, tf, side, members, k, change, supersedes, INTERNAL)
        return name

    # ---- External ------------------------------------------------------------------------------
    def daily(self, name, side, price, k, *, source_k=None):
        kind = "DAILY_HIGH" if side == UPPER else "DAILY_LOW"
        self._member(self.x_members, name, kind, "1D", side, price, k, EXTERNAL, source_k=source_k)
        return name

    def htf(self, name, side, price, k, *, tf="4H"):
        kind = "HTF_EQREQ_HIGH" if side == UPPER else "HTF_EQREQ_LOW"
        self._member(self.x_members, name, kind, tf, side, price, k, EXTERNAL)
        return name

    def cluster(self, name, stype, side, members, k, *, tf="4H", change=FORMED, supersedes=()):
        self._structure(self.x_structures, name, stype, tf, side, members, k, change, supersedes, EXTERNAL)
        return name

    def _member(self, rows, name, kind, tf, side, price, k, cls, source_k=None):
        rows.append({"member_id": name, "liquidity_class": cls, "member_kind": kind, "reference_family": tf,
                     "orientation": side, "price": BASE + price, "source_ref": f"TEST:{name}",
                     "source_at": at(k if source_k is None else source_k), "source_seq_domain": None,
                     "source_seq": None, "available_at": at(k), "available_seq_domain": None, "available_seq": None,
                     "instrument_id": "MNQ", "contract_scope": "SPECIFIC", "contract": self.contract_at(k),
                     "definition_version": "test"})

    def _structure(self, rows, name, stype, tf, side, members, k, change, supersedes, cls):
        rows.append({"structure_id": name, "liquidity_class": cls, "structure_type": stype, "reference_family": tf,
                     "orientation": side, "member_ids": tuple(members), "available_at": at(k),
                     "available_seq_domain": None, "available_seq": None, "instrument_id": "MNQ",
                     "contract_scope": "SPECIFIC", "contract": self.contract_at(k), "change_kind": change,
                     "supersedes": tuple(supersedes), "definition_version": "test"})

    # ---- run -----------------------------------------------------------------------------------
    def tape(self, cutoff_k=None):
        bars = ohlc_bars(self.rows, "1m", contracts=self.contracts, absent=self.absent, dates=DAYS[:3])
        cutoff = at(self.cutoff_k if cutoff_k is None else cutoff_k)
        return build_minute_tape(bars, SPEC, instrument_id="MNQ", replay_cutoff=cutoff, tick=TICK)

    def run(self, cutoff_k=None):
        tape = self.tape(cutoff_k)
        cutoff = tape.replay_cutoff
        im = pd.DataFrame(self.i_members, columns=_MEMBER_COLUMNS)
        im = im.loc[pd.to_datetime(im["available_at"], utc=True) <= cutoff].reset_index(drop=True)
        ist = pd.DataFrame(self.i_structures, columns=_STRUCTURE_COLUMNS)
        ist = ist.loc[pd.to_datetime(ist["available_at"], utc=True) <= cutoff].reset_index(drop=True)
        formation = InternalFormationResult(members=im, structures=ist, swings={}, observations={},
                                            spans=dict(self.spans), barrier_blocks=[])
        xm = pd.DataFrame(self.x_members, columns=_MEMBER_COLUMNS)
        xs = pd.DataFrame(self.x_structures, columns=_STRUCTURE_COLUMNS)
        spans = dict(self.spans)
        for m in self.x_members:
            end = pd.Timestamp(m["source_at"])
            spans[("bar", m["reference_family"], end.value)] = (end.value - 60_000_000_000 * 4, end.value,
                                                                m["reference_family"])
        return run_internal_liquidity(formation, xm, xs, tape, instrument_id="MNQ", tick=TICK, spans=spans)


_MEMBER_COLUMNS = ["member_id", "liquidity_class", "member_kind", "reference_family", "orientation", "price",
                   "source_ref", "source_at", "source_seq_domain", "source_seq", "available_at", "available_seq_domain",
                   "available_seq", "instrument_id", "contract_scope", "contract", "definition_version"]
_STRUCTURE_COLUMNS = ["structure_id", "liquidity_class", "structure_type", "reference_family", "orientation",
                      "member_ids", "available_at", "available_seq_domain", "available_seq", "instrument_id",
                      "contract_scope", "contract", "change_kind", "supersedes", "definition_version"]


