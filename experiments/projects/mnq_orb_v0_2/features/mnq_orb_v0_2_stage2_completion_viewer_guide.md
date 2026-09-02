# MNQ ORB V0.2 Stage-2 Completion Viewer

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m streamlit run notebooks\19_mnq_orb_v02_feature_viewer.py
```

Use validation presets or manual overlays. The default `PREVIOUS DAY` preset
shows primary full-trading-day references; previous RTH remains optional.
Select `Prior 16:45 · gap validation` to see the prior 16:14/17:00 references,
18:01 reopen, and overnight development. Chart end is selectable through 16:00.

Click legend entries to hide/show individual levels. X and Y zoom buttons act
independently; dragging an axis pans/scales that axis. The machine-classification
tab shows neutral key-level event primitives. The representative queue is for
human notes and remains pending until manually reviewed.

No strategy performance is displayed or calculated.
