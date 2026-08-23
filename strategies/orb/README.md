# Opening Range Breakout strategy family

This directory owns the human-readable ORB family specification. ORB logic may
be paired with different instruments or universes; MNQ facts are supplied by
instrument and dataset configuration rather than treated as universal ORB
rules.

Every version must define the opening-range clock/timestamp convention,
duration, breakout definition, entry/exit rules, ambiguity handling, session
cutoffs, trade limits, parameter domains, and supported data constraints.

The validated reference is MNQ ORB V0.1. Its implementation still uses the
established modules under `src/features/` and `src/backtesting/`; moving those
imports is deferred until a second strategy makes a shared interface concrete.

