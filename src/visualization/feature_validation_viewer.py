"""Read-only candle and data-panel viewer for causal feature validation."""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.experiments.mnq_orb_v02_features import load_development_prices


LEVEL_SPECS = {
    "OR High": ("or_high", "#b91c1c", "dash"),
    "OR Low": ("or_low", "#1d4ed8", "dash"),
    "OR Mid": ("or_mid", "#6b7280", "dot"),
    "Previous Day High": ("previous_day_high", "#4f46e5", "dash"),
    "Previous Day Low": ("previous_day_low", "#4f46e5", "dash"),
    "Previous Day Close": ("previous_day_close", "#4f46e5", "dot"),
    "Previous RTH High": ("previous_rth_high", "#7c3aed", "dash"),
    "Previous RTH Low": ("previous_rth_low", "#7c3aed", "dash"),
    "Previous RTH Close": ("previous_rth_close", "#7c3aed", "dot"),
    "Overnight High (full Globex 18:00-09:30)": ("overnight_high", "#0891b2", "dash"),
    "Overnight Low (full Globex 18:00-09:30)": ("overnight_low", "#0891b2", "dash"),
    "Overnight Context High (20:00-09:00)": ("overnight_context_2000_0900_high", "#0e7490", "dot"),
    "Overnight Context Low (20:00-09:00)": ("overnight_context_2000_0900_low", "#0e7490", "dot"),
    "Asia High": ("asia_high", "#ca8a04", "dot"),
    "Asia Low": ("asia_low", "#ca8a04", "dot"),
    "London High": ("london_high", "#9333ea", "dot"),
    "London Low": ("london_low", "#9333ea", "dot"),
    "NY Pre-Market High": ("ny_premarket_high", "#059669", "dash"),
    "NY Pre-Market Low": ("ny_premarket_low", "#059669", "dash"),
    "Globex Reopen": ("globex_reopen_price", "#0f766e", "solid"),
    "Prior 17:00 Close": ("globex_reopen_gap_prior_1700_close", "#dc2626", "solid"),
    "Prior 16:14 Close": ("ny_open_gap_prior_1614_close", "#be123c", "dot"),
    "NY Open Reference": ("ny_open_reference_price", "#be123c", "solid"),
}

OR_LEVELS = ["OR High", "OR Low", "OR Mid"]
LEVEL_PRESETS = {
    "OR": OR_LEVELS,
    "PREVIOUS DAY": [*OR_LEVELS, "Previous Day High", "Previous Day Low", "Previous Day Close"],
    "PREVIOUS RTH": [*OR_LEVELS, "Previous RTH High", "Previous RTH Low", "Previous RTH Close"],
    "OVERNIGHT": [
        *OR_LEVELS,
        "Overnight High (full Globex 18:00-09:30)",
        "Overnight Low (full Globex 18:00-09:30)",
        "Overnight Context High (20:00-09:00)",
        "Overnight Context Low (20:00-09:00)",
    ],
    "ASIA": [*OR_LEVELS, "Asia High", "Asia Low"],
    "LONDON": [*OR_LEVELS, "London High", "London Low"],
    "NY PRE-MARKET": [*OR_LEVELS, "NY Pre-Market High", "NY Pre-Market Low"],
    "GLOBEX GAP": [*OR_LEVELS, "Prior 17:00 Close", "Globex Reopen"],
    "NY OPEN GAP": [*OR_LEVELS, "Prior 16:14 Close", "NY Open Reference"],
    "LIQUIDITY PATH": [*OR_LEVELS, "Asia High", "Asia Low", "London High", "London Low", "NY Pre-Market High", "NY Pre-Market Low"],
    "ALL": list(LEVEL_SPECS),
}

REFERENCE_LEVEL_IDS = {
    name: column.removesuffix("_price")
    for name, (column, _, _) in LEVEL_SPECS.items()
    if name not in OR_LEVELS and column not in {"previous_day_high", "previous_day_low", "previous_day_close", "previous_rth_high", "previous_rth_low", "previous_rth_close", "overnight_high", "overnight_low", "overnight_context_2000_0900_high", "overnight_context_2000_0900_low", "asia_high", "asia_low", "london_high", "london_low", "ny_premarket_high", "ny_premarket_low"}
}
REFERENCE_LEVEL_IDS.update({
    "Previous Day High": "previous_day_high", "Previous Day Low": "previous_day_low", "Previous Day Close": "previous_day_close",
    "Previous RTH High": "previous_rth_high", "Previous RTH Low": "previous_rth_low", "Previous RTH Close": "previous_rth_close",
    "Overnight High (full Globex 18:00-09:30)": "overnight_high",
    "Overnight Low (full Globex 18:00-09:30)": "overnight_low",
    "Overnight Context High (20:00-09:00)": "overnight_context_2000_0900_high",
    "Overnight Context Low (20:00-09:00)": "overnight_context_2000_0900_low",
    "Asia High": "asia_high", "Asia Low": "asia_low", "London High": "london_high", "London Low": "london_low",
    "NY Pre-Market High": "ny_premarket_high", "NY Pre-Market Low": "ny_premarket_low",
    "Globex Reopen": "globex_reopen", "Prior 17:00 Close": "globex_reopen_prior_1700_close",
    "Prior 16:14 Close": "ny_open_prior_1614_close", "NY Open Reference": "ny_open_reference",
})


def build_feature_validation_figure(
    session_prices: pd.DataFrame,
    feature_row: pd.Series,
    *,
    selected_levels: Iterable[str] | None = None,
) -> go.Figure:
    """Build a one-session feature-validation chart with no strategy results."""
    levels = list(selected_levels or LEVEL_SPECS)
    figure = go.Figure(go.Candlestick(
        x=session_prices.index,
        open=session_prices["open"], high=session_prices["high"],
        low=session_prices["low"], close=session_prices["close"],
        name=str(feature_row.get("contract", "MNQ")),
        increasing_line_color="#15803d", decreasing_line_color="#dc2626",
    ))
    for name in levels:
        column, color, dash = LEVEL_SPECS[name]
        value = feature_row.get(column)
        if pd.isna(value):
            continue
        figure.add_trace(go.Scatter(
            x=[session_prices.index.min(), session_prices.index.max()],
            y=[float(value), float(value)],
            mode="lines",
            name=name,
            legendgroup="feature-levels",
            line={"color": color, "dash": dash, "width": 1.2},
            hovertemplate=f"{name}: %{{y:,.2f}}<extra></extra>",
        ))
    session_date = pd.Timestamp(feature_row["session_date"])
    tz = session_prices.index.tz
    for start, end, color, label in (
        (session_date - pd.Timedelta(days=1) + pd.Timedelta(hours=20), session_date, "#f59e0b", "Asia KZ"),
        (session_date + pd.Timedelta(hours=2), session_date + pd.Timedelta(hours=5), "#a855f7", "London KZ"),
        (session_date + pd.Timedelta(hours=7), session_date + pd.Timedelta(hours=9), "#10b981", "NY Pre-Market"),
        (session_date + pd.Timedelta(hours=9, minutes=30), session_date + pd.Timedelta(hours=9, minutes=30 + int(feature_row["or_minutes"])), "#f97316", "Opening Range"),
    ):
        figure.add_vrect(
            x0=start.tz_localize(tz), x1=end.tz_localize(tz), fillcolor=color,
            opacity=.08, line_width=0, annotation_text=label, annotation_position="top left",
        )
    figure.update_layout(
        title=f"MNQ ORB V0.2 Feature Validation · {feature_row['session_date']} · {int(feature_row['or_minutes'])}m OR",
        template="plotly_white", height=720, xaxis_title="Time (ET)", yaxis_title="Price",
        hovermode="x unified", dragmode="pan",
        legend={
            "orientation": "h", "yanchor": "bottom", "y": 1.02,
            "xanchor": "left", "x": 0,
            "groupclick": "toggleitem",
        },
        meta={"strategy_performance": False, "ny_pm_meaning": "New York pre-market"},
    )
    figure.update_xaxes(rangeslider_visible=False, fixedrange=False)
    figure.update_yaxes(fixedrange=False)
    return figure


def run_feature_validation_viewer(project_root: str | Path) -> None:
    root = Path(project_root)
    st.set_page_config(page_title="MNQ V0.2 Feature Validation", layout="wide")
    st.title("MNQ ORB V0.2 · Feature Validation")
    st.info("DEVELOPMENT-only causal feature inspection. No strategy performance is shown. NY PM means New York pre-market.")
    prices = _cached_prices(str(root / "data" / "processed" / "MNQ_raw_cleaned_ET_DEVELOPMENT.csv"))
    feature_dir = root / "experiments" / "projects" / "mnq_orb_v0_2" / "features"
    features = _cached_features(str(feature_dir / "mnq_orb_v0_2_stage2_completion_DEV_feature_audit.csv"))
    sessions = sorted(features["session_date"].unique())
    review_path = feature_dir / "mnq_orb_v0_2_stage2_final_human_review_queue.csv"
    if not review_path.exists():
        review_path = feature_dir / "mnq_orb_v0_2_stage2_human_review_followup_queue.csv"
    if not review_path.exists():
        review_path = feature_dir / "mnq_orb_v0_2_stage2_completion_representative_review_queue.csv"
    review_queue = _cached_review_queue(str(review_path)) if review_path.exists() else pd.DataFrame()
    review_options = ["Manual selection"] + (
        review_queue["review_case"].astype(str).tolist() if not review_queue.empty else []
    )
    selected_review_case = st.selectbox(
        "Representative review case",
        review_options,
        help="Selecting a queued case navigates to its session, OR duration, and validation preset.",
    )
    review_target = None
    if selected_review_case != "Manual selection":
        review_target = review_queue.loc[review_queue["review_case"].eq(selected_review_case)].iloc[0]
        st.dataframe(
            representative_review_panel(review_target), width="stretch", hide_index=True,
        )
        st.caption(
            "The viewer is read-only. Human decisions are kept in a versioned review artifact; "
            "the table above identifies the exact machine-classified level and primitives."
        )
    default_date = (
        pd.Timestamp(review_target["session_date"]).date()
        if review_target is not None and pd.notna(review_target["session_date"])
        else sessions[max(0, len(sessions) - 20)]
    )
    default_duration = (
        int(review_target["or_minutes"])
        if review_target is not None and pd.notna(review_target["or_minutes"])
        else 15
    )
    default_preset = (
        str(review_target.get("validation_preset"))
        if review_target is not None and pd.notna(review_target.get("validation_preset"))
        else "PREVIOUS DAY"
    )
    if default_preset not in LEVEL_PRESETS:
        default_preset = "PREVIOUS DAY"
    controls = st.columns([1.2, 1.0, 1.4, 4.0])
    widget_suffix = selected_review_case.replace(" ", "_")
    selected_date = controls[0].selectbox(
        "Session", sessions, index=sessions.index(default_date),
        key=f"feature_viewer_session_{widget_suffix}",
    )
    durations = [15, 20, 30]
    selected_duration = controls[1].selectbox(
        "OR duration", durations, index=durations.index(default_duration),
        key=f"feature_viewer_duration_{widget_suffix}",
    )
    selected_preset = controls[2].selectbox(
        "Validation preset", list(LEVEL_PRESETS),
        index=list(LEVEL_PRESETS).index(default_preset),
        key=f"feature_viewer_preset_{widget_suffix}",
    )
    if st.session_state.get("feature_viewer_last_preset") != selected_preset:
        st.session_state["feature_viewer_level_selection"] = list(LEVEL_PRESETS[selected_preset])
        st.session_state["feature_viewer_last_preset"] = selected_preset
    selected_levels = controls[3].multiselect(
        "Level overlays", list(LEVEL_SPECS), key="feature_viewer_level_selection"
    )
    range_controls = st.columns([1.5, 1.0, 4.0])
    start_options = {
        "Prior 16:45 · gap validation": (-1, time(16, 45)),
        "Prior 18:01 · full Globex": (-1, time(18, 1)),
        "Prior 20:00 · context": (-1, time(20, 0)),
        "Current 00:00": (0, time(0, 0)),
        "Current 07:00": (0, time(7, 0)),
    }
    start_label = range_controls[0].selectbox("Chart start", list(start_options), index=2)
    end_options = [time(hour, minute) for hour in range(9, 17) for minute in (0, 30)] + [time(16, 0)]
    end_options = sorted(set(value for value in end_options if value >= time(9, 30)))
    end_time = range_controls[1].selectbox("Chart end", end_options, index=end_options.index(time(12, 0)))
    context_key = (str(selected_date), int(selected_duration), start_label, str(end_time))
    if st.session_state.get("feature_viewer_context") != context_key:
        st.session_state["feature_viewer_context"] = context_key
        st.session_state["feature_viewer_x_scale"] = 1.0
        st.session_state["feature_viewer_y_scale"] = 1.0
    zoom_controls = st.columns([1, 1, 1, 1, 1, 1, 4])
    if zoom_controls[0].button("Fit all"):
        st.session_state["feature_viewer_x_scale"] = 1.0
        st.session_state["feature_viewer_y_scale"] = 1.0
    if zoom_controls[1].button("Auto Y"):
        st.session_state["feature_viewer_y_scale"] = 1.0
    if zoom_controls[2].button("X zoom in"):
        st.session_state["feature_viewer_x_scale"] *= 0.8
    if zoom_controls[3].button("X zoom out"):
        st.session_state["feature_viewer_x_scale"] *= 1.25
    if zoom_controls[4].button("Y zoom in"):
        st.session_state["feature_viewer_y_scale"] *= 0.8
    if zoom_controls[5].button("Y zoom out"):
        st.session_state["feature_viewer_y_scale"] *= 1.25
    row = features.loc[
        features["session_date"].eq(selected_date)
        & features["or_minutes"].eq(selected_duration)
    ].iloc[0]
    date_value = pd.Timestamp(selected_date).date()
    start_offset, start_time = start_options[start_label]
    start_stamp, end_stamp = viewer_time_bounds(date_value, start_offset, start_time, end_time)
    session_prices = prices.loc[
        (prices.index >= start_stamp) & (prices.index <= end_stamp)
    ]
    figure = build_feature_validation_figure(session_prices, row, selected_levels=selected_levels)
    figure.update_xaxes(range=_scaled_time_range(
        session_prices.index.min(), session_prices.index.max(),
        st.session_state["feature_viewer_x_scale"],
    ))
    level_values = [
        float(row[LEVEL_SPECS[name][0]])
        for name in selected_levels
        if pd.notna(row.get(LEVEL_SPECS[name][0]))
    ]
    price_values = [float(session_prices["low"].min()), float(session_prices["high"].max()), *level_values]
    figure.update_yaxes(range=_scaled_numeric_range(
        min(price_values), max(price_values),
        st.session_state["feature_viewer_y_scale"],
    ))
    st.caption("Legend: click a level name to hide/show its line. Independent scale: use X/Y zoom buttons. Independent pan: drag an axis. Double-click the chart to reset the Plotly view.")
    st.plotly_chart(
        figure,
        width="stretch",
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "doubleClick": "reset",
            "responsive": True,
            "displaylogo": False,
        },
    )
    st.subheader("Feature data panel")
    families = st.tabs([
        "Opening range", "Pre-open", "Liquidity path", "Historical width",
        "Key levels", "Machine classification", "Availability / audit",
    ])
    with families[0]:
        _show_fields(row, [name for name in row.index if name.startswith("or_") and "hist_" not in name])
    with families[1]:
        _show_fields(row, [name for name in row.index if name.startswith(("asia_", "london_", "ny_premarket_", "overnight_", "combined_preopen_", "gap_", "reopen_", "globex_")) or "_took_" in name])
        st.caption(
            "Full Globex overnight is 18:00-09:30 ET. Overnight context is the narrower "
            "20:00-09:00 ET research window; it excludes the first two hours after reopen "
            "and the final 30 minutes before RTH."
        )
    with families[2]:
        st.dataframe(liquidity_path_panel(row), width="stretch", hide_index=True)
        st.caption(
            "'Took high/low' compares completed pre-open window extremes only. It is not an "
            "OR interaction, signal, or claim about the intrawindow order of events."
        )
    with families[3]:
        _show_fields(row, [name for name in row.index if name.startswith("or_width_hist_")])
    with families[4]:
        _show_fields(row, [name for name in row.index if name.startswith("level_") or name.endswith("_price")])
    with families[5]:
        reference_options = list(REFERENCE_LEVEL_IDS)
        default_reference = review_target.get("trigger_label") if review_target is not None else None
        reference_index = reference_options.index(default_reference) if default_reference in reference_options else 0
        selected_reference = st.selectbox(
            "Reference level", reference_options, index=reference_index,
            key=f"feature_viewer_reference_{widget_suffix}",
        )
        st.dataframe(
            machine_classification_panel(row, selected_reference),
            width="stretch", hide_index=True,
        )
        st.caption(
            "TOUCH = reached the level · TRADE_THROUGH = traded strictly beyond it from the OR-open side · "
            "CLOSE_THROUGH = OR closed on the opposite side · REJECT = touched/beyond then closed on the original side · "
            "SWEEP = TRADE_THROUGH + REJECT. These are neutral event descriptors, not signals."
        )
    with families[6]:
        _show_fields(row, [name for name in row.index if "available" in name or "missing" in name or "observed_bars" in name or "expected_bars" in name])
    if not review_queue.empty:
        passed = int(review_queue["human_review_status"].eq("PASS").sum())
        pending = int(review_queue["human_review_status"].eq("PENDING_HUMAN_REVIEW").sum())
        with st.expander(f"Representative visual-validation queue · {passed} passed · {pending} pending"):
            st.dataframe(review_queue, width="stretch", hide_index=True)


@st.cache_data(show_spinner="Loading DEVELOPMENT bars…")
def _cached_prices(path: str) -> pd.DataFrame:
    return load_development_prices(path)


@st.cache_data(show_spinner=False)
def _cached_features(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.date
    return frame


@st.cache_data(show_spinner=False)
def _cached_review_queue(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def machine_classification_panel(row: pd.Series, selected_reference: str) -> pd.DataFrame:
    """Return the selected key level, OR context, and neutral event states."""
    level_id = REFERENCE_LEVEL_IDS[selected_reference]
    reference_column = LEVEL_SPECS[selected_reference][0]
    prefix = f"level_{level_id}_"
    fields = [
        ("Reference level", selected_reference),
        ("Reference price", row.get(reference_column)),
        ("OR high", row.get("or_high")),
        ("OR low", row.get("or_low")),
        ("OR close", row.get("or_close")),
        ("OR open side", row.get(f"{prefix}start_side")),
        ("TOUCH", row.get(f"{prefix}touched")),
        ("TRADE_THROUGH", row.get(f"{prefix}traded_through")),
        ("CLOSE_THROUGH", row.get(f"{prefix}closed_through")),
        ("REJECT", row.get(f"{prefix}rejected")),
        ("SWEEP", row.get(f"{prefix}swept")),
    ]
    return pd.DataFrame({"Field": [name for name, _ in fields], "Value": [_display_value(value) for _, value in fields]})


def representative_review_panel(review: pd.Series) -> pd.DataFrame:
    """Show the exact queued evidence instead of an ambiguous high/low label."""
    names = [
        "review_case", "session_date", "or_minutes", "validation_preset",
        "trigger_label", "reference_price", "or_open", "or_high", "or_low", "or_close",
        "start_side", "touch", "trade_through", "close_through", "reject", "sweep",
        "classification_summary", "human_review_status", "human_notes",
    ]
    fields = [(name, review.get(name)) for name in names if name in review.index]
    return pd.DataFrame({
        "Field": [name for name, _ in fields],
        "Value": [_display_value(value) for _, value in fields],
    })


def liquidity_path_panel(row: pd.Series) -> pd.DataFrame:
    """Explain each later-window versus earlier-window extreme comparison."""
    display = {"asia": "Asia", "london": "London", "ny_premarket": "NY pre-market"}
    rows: list[dict[str, Any]] = []
    for later, earlier in (
        ("london", "asia"),
        ("ny_premarket", "london"),
        ("ny_premarket", "asia"),
    ):
        key = f"{later}_took_{earlier}"
        available = _as_optional_bool(row.get(f"{key}_available"))
        took_high = _as_optional_bool(row.get(f"{key}_high")) if available else None
        took_low = _as_optional_bool(row.get(f"{key}_low")) if available else None
        state = row.get(f"{key}_state") if available else "UNAVAILABLE"
        rows.append({
            "Comparison": f"{display[later]} vs {display[earlier]}",
            "Earlier high": _display_value(row.get(f"{earlier}_high")),
            "Earlier low": _display_value(row.get(f"{earlier}_low")),
            "Later high": _display_value(row.get(f"{later}_high")),
            "Later low": _display_value(row.get(f"{later}_low")),
            "Took earlier high": _display_value(took_high),
            "Took earlier low": _display_value(took_low),
            "State": _display_value(state),
            "Plain-language meaning": _liquidity_path_meaning(
                display[later], display[earlier], took_high, took_low, available
            ),
        })
    return pd.DataFrame(rows)


def _as_optional_bool(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _liquidity_path_meaning(
    later: str,
    earlier: str,
    took_high: bool | None,
    took_low: bool | None,
    available: bool | None,
) -> str:
    if not available:
        return "One or both source windows are incomplete."
    sides = []
    if took_high:
        sides.append("high")
    if took_low:
        sides.append("low")
    if not sides:
        return f"{later} stayed within the {earlier} high/low extremes."
    return f"{later} exceeded the {earlier} {' and '.join(sides)} extreme(s)."


def _show_fields(row: pd.Series, names: list[str]) -> None:
    values: list[dict[str, Any]] = []
    for name in names:
        value = row[name]
        displayed = _display_value(value)
        values.append({"Feature": name, "Value": displayed})
    st.dataframe(pd.DataFrame(values), width="stretch", hide_index=True)


def _display_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value)).lower()
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.8g}"
    return str(value)


def _scaled_time_range(
    minimum: pd.Timestamp,
    maximum: pd.Timestamp,
    scale: float,
) -> list[pd.Timestamp]:
    center = minimum + (maximum - minimum) / 2
    half = (maximum - minimum) * max(float(scale), 0.05) / 2
    return [center - half, center + half]


def viewer_time_bounds(
    session_date: Any,
    start_day_offset: int,
    start_time: time,
    end_time: time,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Resolve viewer bounds while retaining requested prior-session context."""
    date_value = pd.Timestamp(session_date).date()
    start = pd.Timestamp.combine(date_value, start_time).tz_localize("America/New_York")
    start += pd.Timedelta(days=int(start_day_offset))
    end = pd.Timestamp.combine(date_value, end_time).tz_localize("America/New_York")
    if end <= start:
        raise ValueError("Viewer end must be after its start")
    return start, end


def _scaled_numeric_range(minimum: float, maximum: float, scale: float) -> list[float]:
    span = max(float(maximum) - float(minimum), 0.25)
    center = (float(minimum) + float(maximum)) / 2
    half = span * 1.05 * max(float(scale), 0.05) / 2
    return [center - half, center + half]
