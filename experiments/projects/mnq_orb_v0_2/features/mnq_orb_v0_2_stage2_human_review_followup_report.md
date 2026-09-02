# MNQ ORB V0.2 Stage-2 Human Review Follow-up

This follow-up is DEVELOPMENT-only and does not change feature calculations,
signals, execution, or strategy rules. The original completion artifact remains
unchanged; this separate queue adds exact trigger evidence and human decisions.

## Reconciliation result

- Human-confirmed cases: 14
- Still pending: 0
- Calculation misclassifications found in the reviewed key-level examples: 0
- Auditability issue found: the original queue did not retain the exact high/low
  level or primitive flags that caused each category.
- Selection issue fixed: CLEAN_TRADE_THROUGH now requires TRADE_THROUGH,
  CLOSE_THROUGH, and not REJECT on the same exact previous-day level.

## Reviewed key-level evidence

- 2024-06-26 20m, Previous Day High 19981.00: touch/trade-through/reject/sweep
  true; close-through false. OR high 19981.50, OR close 19978.00.
- 2024-06-27 15m, Previous Day High 20070.50: touch/trade-through/
  close-through true; reject/sweep false. OR high 20101.25, OR close 20074.75.
- 2024-06-24 15m, Asia Low 19917.00: OR opened above and closed below after
  trading below. The supplied note's 19924.75 does not match the canonical Asia
  Low in this row.
- 2024-06-21 30m, London Low 19947.50: OR opened above, traded below, and closed
  19952.75 back above; reject/sweep true and close-through false.
- 2024-06-21 15m, NY pre-market Low 19978.25: OR opened above, traded below, and
  closed 19988.75 back above; reject/sweep true and close-through false.

## Liquidity-path example made explicit

For the queued 2024-06-24 15m row, liquidity path compares completed pre-open
window extremes; it is not an OR interaction:

- London vs Asia: HIGH_ONLY (London exceeded the Asia high, not the Asia low).
- NY pre-market vs London: LOW_ONLY (NY pre-market exceeded the London low, not
  the London high).
- NY pre-market vs Asia: NEITHER.

The project owner subsequently reviewed and passed this explicit sequence.

## Overnight terminology

- Full Globex Overnight H/L: 18:00-09:30 ET conceptual window (bar-end labels
  18:01-09:30).
- Overnight Context H/L: narrower 20:00-09:00 ET conceptual research window
  (bar-end labels 20:01-09:00).

Both are retained because the full Globex range includes the first two hours
after the 18:00 reopen and the final 30 minutes before RTH, while the context
range intentionally excludes those edge periods. They are distinct descriptive
features; neither has been selected as a trading rule.
