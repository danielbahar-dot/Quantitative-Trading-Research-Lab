# Gate 6A sweeps

This directory contains the Gate 6A DEVELOPMENT-only PRINT response surface.
The versioned grid is 10/15/20/30m x 25%/50% static stops x
1/1.5/2/2.5/3R targets: exactly 40 configurations. The 5m duration is excluded.

`orb_gate6a_DEV_print_static_r_sweep.csv` is the canonical configuration table.
The trade and candidate-audit CSVs provide traceability, metadata records the
scope and assertions, and the five HTML files visualize the requested metrics.
All four midpoint/2R control cells reproduced the validated DEVELOPMENT
baselines exactly. No configuration is automatically ranked or selected.

## Gate 6A.1 ambiguity sensitivity

Gate 6A.1 bounds the 25%-stop `AMBIGUOUS_ENTRY_STOP` chronology using observed,
pessimistic, and optimistic scenarios. It is sensitivity evidence only and does
not change Gate 6A or select a strategy.

## Gate 6B fixed target/stop surface

Gate 6B contains 75 DEVELOPMENT-only PRINT configurations: 15/20/30-minute ORs,
40/50/60/75/100-point targets, and midpoint, 25%-OR, or fixed 30/40/50-point
stops. Its summary, trade, candidate-audit, OR-width diagnostic, metadata, and
interactive response-surface artifacts are prefixed
`orb_gate6b_DEV_fixed_target_stop_`.

## Gate 6B.1 OR-width relationship analysis

Gate 6B.1 reads the frozen Gate 6B artifacts only. It does not rerun the
strategy. It analyzes `or_high - or_low` by duration-specific equal-count
quintiles, conditional performance, ambiguity, and target/stop-to-OR ratios.
The stable ordinal tie method sorts by width then session date; equal widths can
span neighboring bins. Cells below 30 executed trades are retained and labeled
`LOW_SAMPLE`. All outputs are DEVELOPMENT-only and prefixed `orb_gate6b1_DEV_`.

## Gate 6B.2 ambiguity robustness

Gate 6B.2 maps all 75 Gate 6B cells under EXCLUDED, ENTRY_FIRST, and
ADVERSE_MOVE_FIRST chronology conventions. EXCLUDED is reconstructed from the
frozen Gate 6B artifacts; only candidates already labeled
`AMBIGUOUS_ENTRY_STOP` are replayed from the next bar for ADVERSE_MOVE_FIRST.
Session eligibility is recomputed chronologically in every scenario. No
configuration is selected. Outputs are prefixed
`orb_gate6b2_DEV_ambiguity_robustness_`.
