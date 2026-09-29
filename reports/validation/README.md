# Validation reports

Tracked, compact validation evidence. These files contain no prices and are
derived from local, Git-ignored data.

## `m3_1_dev_daily_incompleteness.csv`

M3.1 audit of incomplete Daily derived bars (2026-09-29). There is one row
per incomplete Daily bar: 28 rows.

**Inputs**

- `data/processed/MNQ_raw_cleaned_ET_DEVELOPMENT.csv`: DEVELOPMENT partition
  only, 337,815 1m bars, 248 sessions from 2024-06-21 to 2025-06-30.
- Session model: `config/sessions/cme_globex_et.json` with an empty override
  calendar, so `calendar_verified` is False for every row.
- Builder: `src.data.timeframes.build_timeframe` (M3), timeframe `1D`.

**Method**

- For each trading date, the expected 1m bar-end grid runs from session open
  + 1 min through session close.
- Missing minutes are that grid minus the observed bars.
- Missing minutes are grouped into contiguous gaps. A gap is labeled start,
  end, or internal relative to the session.

**Classifications** (evidence-based; no holiday labels because the calendar
verifies nothing):

| Label | Meaning |
|---|---|
| `PARTIAL_DATASET_START` | Gap at the start of the first session in the partition |
| `LATE_SESSION_START` | Contiguous gap at session start |
| `EARLY_DATA_END` | Contiguous gap at session end |
| `MISSING_INTERNAL_MINUTES` | Gaps inside the session only |

- `contract_changed_vs_previous_present_session` is True when the contract
  differs from the previous session present in the data. It is empty for the
  first session.

**Cross-checks run with the audit** (not stored in the CSV):

- Per-bucket missing counts at 5m / 15m / 1H / 4H / 1D match an independent
  computation (0 mismatches).
- Observed totals equal the source rows.
- `session_date` matches the session model for all rows.

**Findings not visible in this file** (a session with no bars produces no
Daily bar):

- 19 weekday sessions are absent.
- 16 of them are Mon–Thu of each quarterly roll week.
- The other 3 (2024-12-25, 2025-01-01, 2025-04-18) are unverified closure
  candidates.

See DECISION_LOG D-120 / D-121.
