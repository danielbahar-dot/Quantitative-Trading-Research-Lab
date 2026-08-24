# Gate 6B.2 — fixed-target/stop ambiguity robustness

This DEVELOPMENT-only gate tests how all 75 Gate 6B configurations respond to
three explicit PRINT entry-bar chronology conventions. It does not add a
parameter, define an OR-width filter, inspect reserved periods, or select a
strategy.

## Scenarios

- **EXCLUDED:** frozen Gate 6B behavior; `AMBIGUOUS_ENTRY_STOP` is excluded.
- **ENTRY_FIRST:** entry precedes the same-bar stop touch, producing an immediate
  -1R stop. The accepted trade consumes the session allowance.
- **ADVERSE_MOVE_FIRST:** the adverse entry-bar move precedes entry. The entry
  bar is not reused for execution inference; evaluation starts on the next
  one-minute bar. The accepted entry consumes the session allowance.

EXCLUDED is built directly from the frozen Gate 6B candidate and trade audits.
ENTRY_FIRST is synthesized from the frozen candidate prices. Gate 6B does not
store the future OHLC path for excluded candidates, so ADVERSE_MOVE_FIRST uses
the existing validated next-bar resolver only for records already classified
`AMBIGUOUS_ENTRY_STOP`. Signals, candidates, ordinary trades, and EXCLUDED
execution are not regenerated.

## Integrity and interpretation

- Scope: 2024-06-21 through 2025-06-30 only.
- Configurations: 75; scenario rows: 225.
- EXCLUDED reproduces every required Gate 6B metric exactly.
- Gate 6B and Gate 6B.1 artifact hashes are unchanged.
- One accepted entry maximum per session/configuration/scenario is enforced.
- `AMBIGUOUS_STOP_TARGET` remains an unresolved performance exclusion. If it
  arises after an ADVERSE_MOVE_FIRST entry, that accepted entry still consumes
  the session allowance and blocks later candidates.
- Chronology range is the observed maximum Avg R minus minimum Avg R across the
  three scenarios; it does not assume which scenario is numerically best.

The outputs are robustness evidence for human review, not a ranked candidate
list. Detailed summary, trade audit, OR-width interaction, metadata, and five
interactive charts share the `orb_gate6b2_DEV_ambiguity_robustness_` prefix.
