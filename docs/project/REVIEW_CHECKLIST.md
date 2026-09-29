# Review Checklist — accepting a Claude Code change

Short version for daily use. Full checklists: [QUALITY_CONTROL](QUALITY_CONTROL.md).

- [ ] **Diff reviewed** (`git diff`, `git status`) — every changed file expected.
- [ ] **No unrelated changes** — no drive-by refactors, renames, reformatting,
      or edits to frozen ORB / Nautilus / data files.
- [ ] **Tests pass** — full suite run; new tests cover unit, invariant, edge,
      and negative cases for any deterministic feature.
- [ ] **Causal assumptions verified** — availability timestamp, same-bar vs
      next-bar, bar-end labeling, session/timezone unchanged.
- [ ] **Feature availability verified** — warm-up/null behavior and no
      look-ahead confirmed on real examples.
- [ ] **New config documented** — new parameters/files explained; no hidden
      defaults; tolerances match DECISION_LOG.
- [ ] **Visual validation status** stated (`TESTED` vs `VISUALLY_VALIDATED`).
- [ ] **Spec match** — no definitions invented; ambiguities reported, not guessed.
- [ ] **Documentation updated** — WORK_PROGRESS (always); DECISION_LOG /
      CHANGELOG / MEMORY when applicable.
- [ ] **No commit/push** unless approved for this task.
