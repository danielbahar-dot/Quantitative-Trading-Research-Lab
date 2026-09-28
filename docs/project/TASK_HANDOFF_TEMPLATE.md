# Task Handoff Template

Copy this block to send a small, bounded job to Claude Code. Fill every
section; write "none" rather than deleting a section. Claude will stop and
report if a required section is missing or ambiguous.

```markdown
# Task: <short title>   (ID: <T-YYYYMMDD-NN>)

## Task objective
<One or two sentences. What should exist or be true when done.>

## Authoritative specification
<The exact definition to implement, or a path to it
(e.g. docs/specs/<name>.md, DECISION_LOG D-NNN). Include: inputs, outputs,
causal availability rule, timestamp/session semantics, tolerances, IDs,
lifecycle states. Claude implements this; it does not extend it.>

## Allowed files
- <paths Claude may create or modify>

## Forbidden files
- Frozen ORB modules, configs, and artifacts (unless listed above)
- SYSTEM_DESIGN_AND_NAUTILUS_TRANSFER_ARCHITECTURE.md and the .docx
- data/ (read-only), experiments/projects/* frozen outputs
- <anything else>

## Required tests
- Unit: <…>
- Invariants: <…>
- Edge cases: <…>
- Negative cases: <…>
- Regression: <existing suites that must still pass>

## Required validation
- Audit/export: <table and columns>
- Visual validation: <viewer/chart, sample cases, who reviews>
- Partition: <DEVELOPMENT only | other, with authorization>

## Non-goals
- <explicitly out of scope, e.g. no strategy logic, no performance metrics,
  no optimization, no refactoring>

## Stop conditions
Stop and report (do not guess) if:
- the spec is ambiguous or contradicts existing frozen semantics;
- a forbidden file would need to change;
- tests reveal a conflict with validated artifacts;
- <task-specific conditions>

## Deliverables
- <code, tests, audit files, doc updates (WORK_PROGRESS, CHANGELOG, …)>

## End-of-task report
Use the standard report in CLAUDE.md. No commit/push unless stated here:
Commit authorized: <no | yes — message/branch>
```
