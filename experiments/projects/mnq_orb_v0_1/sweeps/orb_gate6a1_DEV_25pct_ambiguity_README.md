# Gate 6A.1 — 25% stop entry-bar ambiguity sensitivity

This is a separate DEVELOPMENT-only sensitivity layer over the 20 Gate 6A
25%-stop configurations. It does not alter the Gate 6A tables or strategy code.

- `OBSERVED` exactly preserves Gate 6A exclusion and daily-selection behavior.
- `PESSIMISTIC` assumes entry precedes the same-bar stop touch, resolves the
  candidate as an executed -1R stop, and reapplies the daily trade limit.
- `OPTIMISTIC` assumes the adverse entry-bar excursion precedes entry, ignores
  the remainder of the entry bar, begins evaluation on the next one-minute bar,
  and reapplies the daily trade limit.

The sensitivity CSV contains 20 configurations x three scenarios. The trade
CSV is scenario-level audit evidence. Metadata includes before/after SHA-256
hashes proving that all Gate 6A artifacts remained unchanged. Interactive HTML
files show ambiguity rate, Average-R bounds, sensitivity width, and PF bounds.

No configuration is ranked or selected here. Validation and OOS_BURNED are not
loaded for performance analysis.
