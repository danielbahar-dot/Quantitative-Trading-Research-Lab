# MNQ ORB V0.2 — Final DEVELOPMENT Research Conclusion

- Note type: final research conclusion / cycle closure
- Evidence scope: current MNQ PRINT ORB research only
- OR family: 15m, 20m, and 30m
- Research disposition: `PARKED_AS_RESEARCH_CANDIDATE`
- New research executed for this closure: none
- Validation or OOS_BURNED exposure during this closure: none

## Final interpretation

> ORB contains conditional information, especially through causal relative OR
> width, but the current MNQ PRINT ORB formulation does not yet have a
> sufficiently stable causal participation state to justify another strategy
> version.

This is not a universal rejection of opening-range breakout research. The
conclusion applies to the currently studied MNQ PRINT ORB, the 15m/20m/30m OR
family, the current DEVELOPMENT/Validation evidence, and the current feature
set and execution framework.

## Research conclusions

- V0.1 produced promising DEVELOPMENT performance but failed confirmatory
  Validation.
- Gate 8A showed broad edge deterioration and parameter instability. Execution
  ambiguity was not the primary cause.
- V0.2 therefore investigated causal conditional states rather than performing
  another parameter sweep.
- Stage 2 produced, validated, and froze the causal feature layer.
- Stage 3A found causal OR-width state to be the clearest recurring descriptor
  of breakout excursion.
- Higher relative OR width generally increased MFE, but often increased MAE as
  well.
- The 20m highest OR-efficiency state showed consistent deterioration. Most
  other internal-structure features were weak or unstable.
- Room to the next known key level was weak or unstable and is not promoted.
- London key-level interaction initially appeared promising. Stage 3B showed
  temporal and directional instability, so the London state was not promoted.
- Stage 3C tested one predeclared combined state: elevated causal OR width with
  non-maximum OR efficiency.
- The combined state increased MFE across the 5/10/15/20-session causal width
  lookbacks, but excursion quality was not sufficiently stable across
  lookbacks and DEVELOPMENT halves.
- The 5-session definition was the only lookback satisfying every promotion
  guardrail.

## Five-session observation guardrail

The 5/10/15/20-session lookbacks were predeclared, and Stage 3C did not permit
best-lookback selection. Selecting the 5-session result now as a participation
rule would be post-hoc optimization. It is preserved only as an observation
under `HYP-ORB-STATE-01` for possible future, separately authorized research.
It is not a strategy rule, validated filter, or approved next version.

## Final status

- ORB V0.2 disposition: `PARKED_AS_RESEARCH_CANDIDATE`
- `HYP-ORB-STATE-01`: `POTENTIALLY_INFORMATIVE`
- Validation status: `UNVALIDATED`
- Hypothesis disposition: `PARKED`
- Immediate new ORB optimization cycle: not authorized

## Evidence lineage

| Research link | Canonical evidence |
| --- | --- |
| ORB V0.1 DEVELOPMENT exploration | `experiments/projects/mnq_orb_v0_1/sweeps/README.md` |
| V0.1 candidate freeze | `experiments/projects/mnq_orb_v0_1/freeze/dev_candidate_freeze/orb_gate6c_DEV_shortlist_report.md` |
| Gate 7 confirmatory Validation | `experiments/projects/mnq_orb_v0_1/validation/orb_v01_gate7_VALIDATION_report.md` |
| Gate 8A diagnosis | `experiments/projects/mnq_orb_v0_1/postmortem/gate8a/gate8a_report.md` |
| V0.2 Stage 2 feature freeze | `mnq_orb_v0_2_stage2_feature_freeze_approval` and `experiments/projects/mnq_orb_v0_2/features/mnq_orb_v0_2_stage2_feature_freeze_report.md` |
| Stage 3A Step 2 OR-width characterization | `experiments/projects/mnq_orb_v0_2/signals/mnq_orb_v0_2_stage3a_step2_DEV_or_width_report.md` |
| Stage 3A Step 3 OR structure | `experiments/projects/mnq_orb_v0_2/signals/mnq_orb_v0_2_stage3a_step3_DEV_or_structure_report.md` |
| Stage 3A Step 4 room to level | `experiments/projects/mnq_orb_v0_2/signals/mnq_orb_v0_2_stage3a_step4_DEV_room_to_level_report.md` |
| Stage 3A Step 5 key-level interaction | `experiments/projects/mnq_orb_v0_2/signals/mnq_orb_v0_2_stage3a_step5_DEV_key_level_interaction_report.md` |
| Stage 3B London event characterization | `mnq_orb_v0_2_stage3b_london_interaction_event_characterization` and `experiments/projects/mnq_orb_v0_2/signals/mnq_orb_v0_2_stage3b_DEV_london_30m_report.md` |
| Stage 3C combined-state hypothesis | `mnq_orb_v0_2_stage3c_combined_state_hypothesis` and `experiments/projects/mnq_orb_v0_2/signals/mnq_orb_v0_2_stage3c_DEV_combined_state_report.md` |

Historical experiment decisions remain unchanged. The Stage 3C experiment is
complete, DEVELOPMENT-only, unvalidated, and records
`reserved_data_exposed=false` with lifecycle decision `revise`.
