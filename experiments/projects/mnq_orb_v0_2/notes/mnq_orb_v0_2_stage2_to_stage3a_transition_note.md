# ORB V0.2 — Research conclusions after Stage 2 / before conditional-state characterization

- Note type: research conclusion / transition note
- Evidence scope: DEVELOPMENT only
- New performance test: none
- Validation or OOS_BURNED exposure: none

## Conclusions

MNQ ORB V0.1 showed promising DEVELOPMENT performance, particularly for PRINT
breakouts and several 15m–30m configurations. The frozen candidates did not
generalize consistently into Validation: one weakened materially, two became
negative, and none passed.

Gate 8A found broad edge deterioration, parameter migration and instability,
weak persistence of DEVELOPMENT rankings into Validation, and likely
market-state dependence. Improved ambiguity and observability did not explain
the deterioration. Parameter tuning alone is therefore not a sufficient next
step.

The V0.2 working hypothesis is that ORB is a conditional setup whose behavior
depends on causal market state and structural context observable by breakout
time. Stage 2 built and froze the causal feature layer needed to examine that
hypothesis:

- OR geometry, efficiency, CLV, direction, and net move
- causal 5/10/15/20-session OR-width state
- Asia, London, New York pre-market, full overnight, and 20:00–09:00 context
- previous-day levels, gap features, and key-level interaction states
- separated signal-bar and post-signal-bar breakout excursion outcomes
- machine-stable definitions confirmed through 14/14 human-review cases

Stage 3A Step 1A added `ROOM TO NEXT KEY LEVEL`. It distinguishes breakouts
entering nearby known structure from breakouts with more open space, without
turning that distinction into a participation rule.

Features remain descriptive states, not trading rules. For example,
`SWEEP=true` is not a filter unless later evidence shows that the sweep state
materially and stably changes the same PRINT ORB outcome behavior.

The intended design path is:

```text
validated ORB signal
→ characterize causal state
→ qualify participation
→ trade only in states supported by stable evidence
```

The goal is not to stack many filters. The next phase will test which
predeclared state variables explain ORB behavior and which are noise, without
new stop/target sweeps, broad feature mining, machine learning, arbitrary
threshold optimization, or Validation/OOS_BURNED exposure.

## Open research question

Which causal states observable by the time of the OR breakout materially
change the behavior and expectancy of the same validated PRINT ORB signal?

The next planned phase is a DEVELOPMENT-only hypothesis-building diagnostic,
not a strategy backtest or approval of any state as a validated filter.
