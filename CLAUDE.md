# CLAUDE.md — Operating Instructions for Claude Code

How Claude must behave in this repository. Keep this file short and
operational; project knowledge lives in the continuity set below.

## Continuity set (read at the start of every session)

1. `CLAUDE.md` — how to behave (this file).
2. `MEMORY.md` — what the next agent must know.
3. `docs/project/WORK_PROGRESS.md` — where exactly we are now.
4. `docs/project/DECISION_LOG.md` — why we chose this.

Reference as needed: `docs/project/` (overview, architecture map, roadmap,
quality control, research governance, templates), `README.md`,
`docs/RESEARCH_LIFECYCLE_V1.md`, `docs/AUTOMATIC_EXPERIMENT_REGISTRATION.md`.

## Repository purpose

The original Quantitative Trading Research Lab: causal, reproducible
quantitative trading research on VectorBT plus custom execution. It is the
research source of truth for current work. A separate NautilusTrader platform
is the eventual runtime; do **not** redesign this repository around Nautilus.

## Claude's role

- Claude is the **implementation and execution agent**.
- Design authority (research definitions, architecture, strategy logic,
  acceptance criteria) is maintained **outside Claude** (in ChatGPT, relayed by
  the user). Implement specifications; do not author them.
- When a requirement is ambiguous or underspecified, **stop and report the
  ambiguity**. Do not invent definitions (e.g. swing, MSS, session boundaries,
  tolerances, bar anchors).

## Hard rules

- **Causality:** no look-ahead at any layer. Every feature/state/signal must
  have an explicit availability timestamp. Keep future-looking outcome columns
  separate and clearly prefixed (existing convention: `outcome_`).
- **Timestamp/session semantics:** data is Eastern Time NinjaTrader 1-minute
  bars with `timestamp_et = bar_end_time`. Never silently change timezones,
  bar labeling, session windows, or `session_date` ownership. Frozen windows
  live in `config/features/mnq_orb_v0_2_preopen_windows.json`.
- **Layer separation:** FEATURE ≠ STATE ≠ SIGNAL ≠ STRATEGY ≠ EXECUTION.
- **Frozen research is read-only:** do not modify frozen ORB definitions,
  configs, artifacts under `experiments/projects/`, reviewed records, or
  validated outputs. ORB is `PARKED_AS_RESEARCH_CANDIDATE`.
- **ICT is a separate research family.** Never implement ICT work as an
  extension of ORB modules. Reusing generic ORB infrastructure requires an
  explicit instruction.
- **Partitions:** do not access VALIDATION or OOS_BURNED data unless a task
  explicitly authorizes it. Do not run optimization or backtests unless asked.
- **Nautilus documents** (`SYSTEM_DESIGN_AND_NAUTILUS_TRANSFER_ARCHITECTURE.md`,
  the `.docx`) are not to be modified.
- **Small, bounded changes.** Touch only files the task allows. No unrelated
  refactors, renames, formatting sweeps, or import-path moves.
- **Tests are required** for any deterministic feature: unit, invariant,
  edge-case, and negative-case tests (see `docs/project/QUALITY_CONTROL.md`).
- **Performance never justifies a definition.** Do not change a rule because
  results look better.
- **Git:** no commit, push, branch deletion, or history rewrite without
  explicit authorization in the current task.
- Raw data is immutable. Never overwrite a completed run or frozen artifact;
  reruns get a new `run_id`.

## Environment

- Windows; Python via `.\.venv\Scripts\python.exe` (Python 3.13 target).
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` (config in `pyproject.toml`).
- Market data, processed tables, and local ledgers are Git-ignored and local.

## Standard end-of-task report

1. Objective and outcome (done / partial / blocked).
2. Files created / modified / deleted (exact paths).
3. Tests run and results (command + pass/fail counts); tests not run and why.
4. Causality / timestamp assumptions made or verified.
5. Validation status of any feature touched (see status vocabulary in
   `docs/project/QUALITY_CONTROL.md`).
6. Ambiguities encountered and how they were handled (stopped / flagged).
7. Deviations from the spec, if any.
8. Git status; confirmation of no commit/push unless authorized.
9. Suggested next step (not executed).

After meaningful work, update `docs/project/WORK_PROGRESS.md` (and
`DECISION_LOG.md` / `CHANGELOG.md` / `MEMORY.md` only when their triggers apply).
