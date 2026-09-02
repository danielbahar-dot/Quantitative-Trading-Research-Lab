# MNQ ORB V0.2 Feature Validation Viewer

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m streamlit run notebooks\19_mnq_orb_v02_feature_viewer.py
```

Select a DEVELOPMENT session and 15/20/30-minute OR. The viewer overlays the
OR, prior RTH, overnight, proposed Asia/London, New York pre-market, and Globex
reference levels and shows the complete feature row below the chart.

Use `X zoom in/out` and `Y zoom in/out` to expand either axis independently.
`Fit all` resets both axes, `Auto Y` resets the price scale, and dragging an
axis pans that axis independently.

Every selected price level appears in the chart legend with its matching color
and line style. Click a legend entry to hide or restore that individual level.

This viewer contains no strategy performance. “NY PM” means New York
pre-market and is displayed as `NY Pre-Market`.
