"""Reusable Plotly research viewer for opening-range studies.

The module deliberately owns only data loading, selection, and visualization.
Strategy logic and opening-range calculation remain elsewhere in the project.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
import warnings

import pandas as pd
import plotly.graph_objects as go

from src.backtesting.candidate_entries import build_candidate_entries


ET_TIMEZONE = "America/New_York"
SUPPORTED_OR_MINUTES = (5, 10, 15, 30)
SUPPORTED_BREAKOUT_TYPES = ("PRINT", "CLOSE")
ENTRY_CUTOFF = time(11, 30)

SIGNAL_COLUMNS = [
    "session_date",
    "direction",
    "breakout_type",
    "signal_time",
    "or_high",
    "or_low",
    "or_mid",
    "ambiguity_status",
]


def load_price_data(data_file: str | Path) -> pd.DataFrame:
    """Load validated MNQ candles with a timezone-aware ET index."""
    data_file = Path(data_file)
    required = {
        "timestamp_et",
        "session_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    available_columns = pd.read_csv(data_file, nrows=0).columns
    missing = required.difference(available_columns)
    if missing:
        raise ValueError(
            f"Price data is missing required columns: {', '.join(sorted(missing))}"
        )

    # source_file is useful for data lineage but not for charting. Avoiding it
    # materially reduces startup memory for the validated multi-year CSV.
    viewer_columns = required.union({"contract"}).intersection(available_columns)
    price_data = pd.read_csv(data_file, usecols=list(viewer_columns))

    # utc=True handles both EST and EDT offsets in a single source column.
    price_data["timestamp_et"] = (
        pd.to_datetime(price_data["timestamp_et"], utc=True, errors="raise")
        .dt.tz_convert(ET_TIMEZONE)
    )
    price_data["session_date"] = pd.to_datetime(
        price_data["session_date"], errors="raise"
    ).dt.date

    return price_data.set_index("timestamp_et").sort_index()


def load_or_levels(or_file: str | Path) -> pd.DataFrame:
    """Load the existing pre-calculated opening-range levels."""
    or_file = Path(or_file)
    or_levels = pd.read_csv(or_file)

    required = {
        "session_date",
        "or_minutes",
        "valid_or",
        "or_high",
        "or_low",
        "or_mid",
    }
    missing = required.difference(or_levels.columns)
    if missing:
        raise ValueError(
            f"OR data is missing required columns: {', '.join(sorted(missing))}"
        )

    or_levels["session_date"] = pd.to_datetime(
        or_levels["session_date"], errors="raise"
    ).dt.date
    or_levels["valid_or"] = _as_boolean(or_levels["valid_or"])
    return or_levels


def find_orb_signals(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
    *,
    start_date: str | date,
    end_date: str | date,
    or_minutes: int,
    breakout_type: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return first-per-direction ORB signals and skipped ambiguous PRINT bars."""
    selected_start_date = _as_date(start_date, "start_date")
    selected_end_date = _as_date(end_date, "end_date")
    selected_breakout_type = breakout_type.upper()
    _validate_selection(
        price_data,
        selected_start_date,
        selected_end_date,
        or_minutes,
        selected_breakout_type,
    )

    date_mask = price_data["session_date"].between(
        selected_start_date, selected_end_date, inclusive="both"
    )
    selected_prices = price_data.loc[date_mask]
    signal_rows: list[dict] = []
    ambiguous_rows: list[dict] = []

    for session_date, session_prices in selected_prices.groupby(
        "session_date", sort=True
    ):
        level_match = or_levels.loc[
            (or_levels["session_date"] == session_date)
            & (or_levels["or_minutes"] == or_minutes)
        ]
        if level_match.empty or not bool(level_match.iloc[0]["valid_or"]):
            continue

        level = level_match.iloc[0]
        or_high = float(level["or_high"])
        or_low = float(level["or_low"])
        or_mid = float(level["or_mid"])
        market_open = pd.Timestamp.combine(
            session_date, time(9, 30)
        ).tz_localize(ET_TIMEZONE)
        # NT8 labels each 1-minute bar by its end: timestamp_et = bar_end_time.
        # The first post-OR bar ends one minute after the last OR bar-end label.
        eligible_start = market_open + pd.Timedelta(minutes=or_minutes + 1)
        eligible_end = pd.Timestamp.combine(
            session_date, ENTRY_CUTOFF
        ).tz_localize(ET_TIMEZONE)
        eligible = session_prices.loc[
            (session_prices.index >= eligible_start)
            & (session_prices.index <= eligible_end)
        ]

        found_directions: set[str] = set()
        for signal_time, bar in eligible.iterrows():
            if selected_breakout_type == "PRINT":
                long_break = bool(bar["high"] > or_high)
                short_break = bool(bar["low"] < or_low)
                if long_break and short_break:
                    ambiguous_rows.append(
                        _signal_row(
                            session_date,
                            "AMBIGUOUS (LONG+SHORT)",
                            selected_breakout_type,
                            signal_time,
                            or_high,
                            or_low,
                            or_mid,
                            True,
                        )
                    )
                    continue
            else:
                long_break = bool(bar["close"] > or_high)
                short_break = bool(bar["close"] < or_low)

            if long_break and "LONG" not in found_directions:
                signal_rows.append(
                    _signal_row(
                        session_date,
                        "LONG",
                        selected_breakout_type,
                        signal_time,
                        or_high,
                        or_low,
                        or_mid,
                        False,
                    )
                )
                found_directions.add("LONG")
            if short_break and "SHORT" not in found_directions:
                signal_rows.append(
                    _signal_row(
                        session_date,
                        "SHORT",
                        selected_breakout_type,
                        signal_time,
                        or_high,
                        or_low,
                        or_mid,
                        False,
                    )
                )
                found_directions.add("SHORT")
            if len(found_directions) == 2:
                break

    signals = pd.DataFrame(signal_rows, columns=SIGNAL_COLUMNS)
    ambiguous = pd.DataFrame(ambiguous_rows, columns=SIGNAL_COLUMNS)
    return signals, ambiguous


def build_research_viewer(
    price_data: pd.DataFrame,
    or_levels: pd.DataFrame,
    *,
    start_date: str | date,
    end_date: str | date,
    or_minutes: int,
    breakout_type: str = "PRINT",
    start_time: str | time,
    end_time: str | time,
    instrument: str = "MNQ",
    execution_overlay: bool = False,
) -> go.Figure:
    """Build a multi-session ORB candlestick chart.

    OR level traces contain an explicit gap between sessions. This prevents
    Plotly from connecting one session's levels to another session's levels.
    """
    selected_start_date = _as_date(start_date, "start_date")
    selected_end_date = _as_date(end_date, "end_date")
    selected_start_time = _as_time(start_time, "start_time")
    selected_end_time = _as_time(end_time, "end_time")
    selected_breakout_type = breakout_type.upper()

    _validate_selection(
        price_data,
        selected_start_date,
        selected_end_date,
        or_minutes,
        selected_breakout_type,
    )
    if selected_start_time >= selected_end_time:
        raise ValueError("start_time must be earlier than end_time")

    date_mask = price_data["session_date"].between(
        selected_start_date, selected_end_date, inclusive="both"
    )
    chart_data = price_data.loc[date_mask].between_time(
        selected_start_time, selected_end_time, inclusive="both"
    ).copy()
    if chart_data.empty:
        raise ValueError(
            "No price bars found for the selected dates and intraday time window."
        )

    # A continuous display index removes overnight/weekend gaps while the
    # original ET timestamps remain available in the hover data.
    chart_data["_display_x"] = range(len(chart_data))
    session_dates = sorted(chart_data["session_date"].unique())
    hover_text = _candle_hover_text(chart_data)
    signals, ambiguous_bars = find_orb_signals(
        price_data,
        or_levels,
        start_date=selected_start_date,
        end_date=selected_end_date,
        or_minutes=or_minutes,
        breakout_type=selected_breakout_type,
    )
    candidates = (
        build_candidate_entries(price_data, signals, or_minutes=or_minutes)
        if execution_overlay
        else pd.DataFrame()
    )

    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=chart_data["_display_x"],
            open=chart_data["open"],
            high=chart_data["high"],
            low=chart_data["low"],
            close=chart_data["close"],
            name=instrument,
            text=hover_text,
            hoverinfo="text",
            increasing_line_color="#15803d",
            decreasing_line_color="#dc2626",
            legendrank=1,
        )
    )

    level_segments: dict[str, dict[str, list]] = {
        "OR High": {"x": [], "y": []},
        "OR Low": {"x": [], "y": []},
        "OR Mid": {"x": [], "y": []},
    }
    skipped_sessions: list[str] = []

    for session_date in session_dates:
        session_data = chart_data.loc[chart_data["session_date"] == session_date]
        level_row = or_levels.loc[
            (or_levels["session_date"] == session_date)
            & (or_levels["or_minutes"] == or_minutes)
        ]

        if level_row.empty or not bool(level_row.iloc[0]["valid_or"]):
            skipped_sessions.append(session_date.isoformat())
            continue

        level_row = level_row.iloc[0]
        session_x0 = int(session_data["_display_x"].min())
        session_x1 = int(session_data["_display_x"].max())

        _append_segment(
            level_segments["OR High"], session_x0, session_x1, level_row["or_high"]
        )
        _append_segment(
            level_segments["OR Low"], session_x0, session_x1, level_row["or_low"]
        )
        _append_segment(
            level_segments["OR Mid"], session_x0, session_x1, level_row["or_mid"]
        )

        market_open = pd.Timestamp.combine(session_date, time(9, 30)).tz_localize(
            ET_TIMEZONE
        )
        first_or_bar_end = market_open + pd.Timedelta(minutes=1)
        last_or_bar_end = market_open + pd.Timedelta(minutes=or_minutes)
        visible_or = session_data.loc[
            (session_data.index >= first_or_bar_end)
            & (session_data.index <= last_or_bar_end)
        ]
        if not visible_or.empty:
            figure.add_vrect(
                x0=float(visible_or["_display_x"].min()) - 0.5,
                x1=float(visible_or["_display_x"].max()) + 0.5,
                fillcolor="#f59e0b",
                opacity=0.12,
                layer="below",
                line_width=0,
            )

    for session_date in session_dates[1:]:
        session_x0 = float(
            chart_data.loc[
                chart_data["session_date"] == session_date, "_display_x"
            ].min()
        )
        figure.add_vline(
            x=session_x0 - 0.5,
            line_color="#cbd5e1",
            line_dash="dot",
            line_width=1,
            opacity=0.8,
            layer="below",
        )

    line_styles = {
        "OR High": {"color": "#b91c1c", "dash": "dash", "width": 1.5},
        "OR Low": {"color": "#1d4ed8", "dash": "dash", "width": 1.5},
        "OR Mid": {"color": "#6b7280", "dash": "dot", "width": 1.25},
    }
    for rank, name in enumerate(("OR High", "OR Low", "OR Mid"), start=10):
        segment = level_segments[name]
        if not segment["x"]:
            continue
        figure.add_trace(
            go.Scatter(
                x=segment["x"],
                y=segment["y"],
                mode="lines",
                name=name,
                line=line_styles[name],
                connectgaps=False,
                hovertemplate=f"{name}: %{{y:,.2f}}<extra></extra>",
                legendrank=rank,
            )
        )

    _add_signal_markers(
        figure,
        chart_data,
        signals,
        ambiguous_bars,
        candidates if execution_overlay else None,
    )
    if execution_overlay:
        _add_candidate_overlay(figure, chart_data, candidates)

    if skipped_sessions:
        warnings.warn(
            "OR overlays skipped because existing OR levels were missing or invalid "
            f"for: {', '.join(skipped_sessions)}",
            stacklevel=2,
        )

    tick_values, tick_labels = _build_time_ticks(chart_data, session_dates)
    full_x_range = [-0.75, len(chart_data) - 0.25]
    rendered_sessions = len(session_dates) - len(skipped_sessions)

    figure.update_layout(
        title=(
            f"{instrument} Research Viewer | "
            f"{selected_start_date.isoformat()} to {selected_end_date.isoformat()} | "
            f"{or_minutes}-minute OR | {selected_breakout_type} breakouts"
        ),
        template="plotly_white",
        xaxis_title="Time (ET)",
        yaxis_title="Price",
        dragmode="pan",
        hovermode="closest",
        hoverlabel={"align": "left"},
        height=850,
        margin={"l": 70, "r": 35, "t": 85, "b": 90},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        meta={
            "candles": len(chart_data),
            "sessions": len(session_dates),
            "rendered_or_sessions": rendered_sessions,
            "skipped_or_sessions": skipped_sessions,
            "breakout_type": selected_breakout_type,
            "long_signals": int((signals["direction"] == "LONG").sum()),
            "short_signals": int((signals["direction"] == "SHORT").sum()),
            "signal_count": len(signals),
            "ambiguous_bar_count": len(ambiguous_bars),
            "execution_overlay": bool(execution_overlay),
            "candidate_count": len(candidates),
            "valid_candidate_count": int(
                candidates["candidate_validity"].sum()
            ) if not candidates.empty else 0,
            "invalid_candidate_count": int(
                (~candidates["candidate_validity"]).sum()
            ) if not candidates.empty else 0,
            "full_x_range": full_x_range,
        },
        uirevision=(
            f"orb-research-viewer-v0.2-{selected_start_date}-{selected_end_date}-"
            f"{or_minutes}-{selected_breakout_type}-"
            f"{selected_start_time}-{selected_end_time}-{execution_overlay}"
        ),
    )
    figure.update_xaxes(
        type="linear",
        range=full_x_range,
        autorange=False,
        tickmode="array",
        tickvals=tick_values,
        ticktext=tick_labels,
        showticklabels=True,
        ticklabelposition="outside bottom",
        tickangle=0,
        tickfont={"size": 11},
        automargin=True,
        rangeslider_visible=False,
        fixedrange=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
    )
    figure.update_yaxes(
        automargin=True,
        fixedrange=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
    )
    return figure


def _validate_selection(
    price_data: pd.DataFrame,
    start_date: date,
    end_date: date,
    or_minutes: int,
    breakout_type: str,
) -> None:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if or_minutes not in SUPPORTED_OR_MINUTES:
        choices = ", ".join(str(value) for value in SUPPORTED_OR_MINUTES)
        raise ValueError(f"or_minutes must be one of: {choices}")
    if breakout_type not in SUPPORTED_BREAKOUT_TYPES:
        choices = ", ".join(SUPPORTED_BREAKOUT_TYPES)
        raise ValueError(f"breakout_type must be one of: {choices}")
    if not isinstance(price_data.index, pd.DatetimeIndex):
        raise TypeError("price_data must use a DatetimeIndex")


def _signal_row(
    session_date: date,
    direction: str,
    breakout_type: str,
    signal_time: pd.Timestamp,
    or_high: float,
    or_low: float,
    or_mid: float,
    ambiguity_status: bool,
) -> dict:
    return {
        "session_date": session_date,
        "direction": direction,
        "breakout_type": breakout_type,
        "signal_time": signal_time,
        "or_high": or_high,
        "or_low": or_low,
        "or_mid": or_mid,
        "ambiguity_status": ambiguity_status,
    }


def _add_signal_markers(
    figure: go.Figure,
    chart_data: pd.DataFrame,
    signals: pd.DataFrame,
    ambiguous_bars: pd.DataFrame,
    candidates: pd.DataFrame | None = None,
) -> None:
    display_lookup = chart_data["_display_x"]
    marker_styles = {
        "LONG": {"symbol": "triangle-up", "color": "#047857", "y_column": "low"},
        "SHORT": {
            "symbol": "triangle-down",
            "color": "#be123c",
            "y_column": "high",
        },
    }
    for rank, direction in enumerate(("LONG", "SHORT"), start=20):
        direction_signals = signals.loc[signals["direction"] == direction]
        visible = direction_signals.loc[
            direction_signals["signal_time"].isin(display_lookup.index)
        ]
        if visible.empty:
            continue
        style = marker_styles[direction]
        figure.add_trace(
            go.Scatter(
                x=[int(display_lookup.loc[value]) for value in visible["signal_time"]],
                y=[
                    float(chart_data.loc[value, style["y_column"]])
                    for value in visible["signal_time"]
                ],
                mode="markers",
                name=f"{direction.title()} signal",
                marker={
                    "symbol": style["symbol"],
                    "color": style["color"],
                    "size": 14,
                    "line": {"color": "#ffffff", "width": 1},
                },
                text=_signal_hover_text(visible, candidates),
                hoverinfo="text",
                legendrank=rank,
            )
        )

    visible_ambiguous = ambiguous_bars.loc[
        ambiguous_bars["signal_time"].isin(display_lookup.index)
    ]
    if not visible_ambiguous.empty:
        figure.add_trace(
            go.Scatter(
                x=[
                    int(display_lookup.loc[value])
                    for value in visible_ambiguous["signal_time"]
                ],
                y=list(visible_ambiguous["or_mid"]),
                mode="markers",
                name="Ambiguous PRINT bar",
                marker={
                    "symbol": "x",
                    "color": "#d97706",
                    "size": 13,
                    "line": {"width": 2},
                },
                text=_signal_hover_text(visible_ambiguous),
                hoverinfo="text",
                legendrank=22,
            )
        )


def _add_candidate_overlay(
    figure: go.Figure,
    chart_data: pd.DataFrame,
    candidates: pd.DataFrame,
) -> None:
    if candidates.empty:
        return

    display_lookup = chart_data["_display_x"]
    visible = candidates.loc[
        candidates["entry_time"].notna()
        & candidates["entry_time"].isin(display_lookup.index)
        & candidates["entry_price"].notna()
    ]
    if visible.empty:
        return

    marker_styles = {
        "LONG": {"symbol": "diamond-open", "color": "#065f46"},
        "SHORT": {"symbol": "diamond-open", "color": "#9f1239"},
    }
    valid = visible.loc[visible["candidate_validity"]]
    for rank, direction in enumerate(("LONG", "SHORT"), start=23):
        direction_entries = valid.loc[valid["direction"] == direction]
        if direction_entries.empty:
            continue
        style = marker_styles[direction]
        figure.add_trace(
            go.Scatter(
                x=[
                    int(display_lookup.loc[value])
                    for value in direction_entries["entry_time"]
                ],
                y=list(direction_entries["entry_price"]),
                mode="markers",
                name=f"{direction.title()} entry",
                marker={
                    "symbol": style["symbol"],
                    "color": style["color"],
                    "size": 12,
                    "line": {"width": 2},
                },
                text=_candidate_hover_text(direction_entries),
                hoverinfo="text",
                legendrank=rank,
            )
        )

    invalid = visible.loc[~visible["candidate_validity"]]
    if not invalid.empty:
        figure.add_trace(
            go.Scatter(
                x=[int(display_lookup.loc[value]) for value in invalid["entry_time"]],
                y=list(invalid["entry_price"]),
                mode="markers",
                name="Invalid candidate",
                marker={
                    "symbol": "x",
                    "color": "#7c2d12",
                    "size": 13,
                    "line": {"width": 2},
                },
                text=_candidate_hover_text(invalid),
                hoverinfo="text",
                legendrank=25,
            )
        )

    level_specs = {
        "Entry price": {
            "column": "entry_price",
            "color": "#0f766e",
            "dash": "solid",
        },
        "Initial stop": {
            "column": "initial_stop",
            "color": "#dc2626",
            "dash": "dash",
        },
        "Initial target": {
            "column": "initial_target",
            "color": "#16a34a",
            "dash": "dot",
        },
    }
    for rank, (name, spec) in enumerate(level_specs.items(), start=30):
        x_values: list[float | None] = []
        y_values: list[float | None] = []
        hover_values: list[str | None] = []
        for candidate in visible.itertuples(index=False):
            level = getattr(candidate, spec["column"])
            if pd.isna(level):
                continue
            session_data = chart_data.loc[
                chart_data["session_date"] == candidate.session_date
            ]
            entry_x = int(display_lookup.loc[candidate.entry_time])
            session_x1 = int(session_data["_display_x"].max())
            hover = _candidate_hover_row(candidate)
            x_values.extend([entry_x, session_x1, None])
            y_values.extend([float(level), float(level), None])
            hover_values.extend([hover, hover, None])
        if not x_values:
            continue
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="lines",
                name=name,
                line={
                    "color": spec["color"],
                    "dash": spec["dash"],
                    "width": 1.25,
                },
                connectgaps=False,
                text=hover_values,
                hoverinfo="text",
                legendrank=rank,
            )
        )


def _candidate_hover_text(candidates: pd.DataFrame) -> list[str]:
    return [
        _candidate_hover_row(candidate)
        for candidate in candidates.itertuples(index=False)
    ]


def _candidate_hover_row(candidate) -> str:
    entry_time = (
        candidate.entry_time.strftime("%Y-%m-%d %H:%M ET")
        if pd.notna(candidate.entry_time)
        else "N/A"
    )
    entry_price = (
        f"{candidate.entry_price:,.2f}"
        if pd.notna(candidate.entry_price)
        else "N/A"
    )
    risk_points = (
        f"{candidate.risk_points:,.2f}"
        if pd.notna(candidate.risk_points)
        else "N/A"
    )
    initial_target = (
        f"{candidate.initial_target:,.2f}"
        if pd.notna(candidate.initial_target)
        else "N/A"
    )
    invalid_reason = candidate.invalid_reason or ""
    entry_bar_open = _hover_price(candidate.entry_bar_open)
    entry_bar_high = _hover_price(candidate.entry_bar_high)
    entry_bar_low = _hover_price(candidate.entry_bar_low)
    entry_bar_close = _hover_price(candidate.entry_bar_close)
    return (
        f"<b>{candidate.direction} candidate</b>"
        f"<br>session_date: {candidate.session_date.isoformat()}"
        f"<br>contract: {candidate.contract}"
        f"<br>direction: {candidate.direction}"
        f"<br>OR duration: {candidate.or_minutes} minutes"
        f"<br>breakout_type: {candidate.breakout_type}"
        f"<br>signal_time: {candidate.signal_time.strftime('%Y-%m-%d %H:%M ET')}"
        f"<br>entry_time: {entry_time}"
        f"<br>entry_price: {entry_price}"
        f"<br><b>Entry bar OHLC (bar-end timestamp)</b>"
        f"<br>entry_bar_open: {entry_bar_open}"
        f"<br>entry_bar_high: {entry_bar_high}"
        f"<br>entry_bar_low: {entry_bar_low}"
        f"<br>entry_bar_close: {entry_bar_close}"
        f"<br>OR high: {candidate.or_high:,.2f}"
        f"<br>OR low: {candidate.or_low:,.2f}"
        f"<br>OR midpoint: {candidate.or_mid:,.2f}"
        f"<br>initial_stop: {candidate.initial_stop:,.2f}"
        f"<br>risk_points: {risk_points}"
        f"<br>initial_target: {initial_target}"
        f"<br>candidate_validity: {str(bool(candidate.candidate_validity)).lower()}"
        f"<br>invalid_reason: {invalid_reason}"
    )


def _signal_hover_text(
    events: pd.DataFrame,
    candidates: pd.DataFrame | None = None,
) -> list[str]:
    hover_text: list[str] = []
    for row in events.itertuples(index=False):
        execution_details = ""
        if candidates is not None and not candidates.empty:
            match = candidates.loc[
                (candidates["session_date"] == row.session_date)
                & (candidates["direction"] == row.direction)
                & (candidates["breakout_type"] == row.breakout_type)
                & (candidates["signal_time"] == row.signal_time)
            ]
            if not match.empty:
                candidate = next(match.itertuples(index=False))
                execution_details = (
                    f"<br><b>Candidate execution</b>"
                    f"<br>entry_time: {_hover_time(candidate.entry_time)}"
                    f"<br>entry_price: {_hover_price(candidate.entry_price)}"
                    f"<br><b>Entry bar OHLC (bar-end timestamp)</b>"
                    f"<br>entry_bar_open: {_hover_price(candidate.entry_bar_open)}"
                    f"<br>entry_bar_high: {_hover_price(candidate.entry_bar_high)}"
                    f"<br>entry_bar_low: {_hover_price(candidate.entry_bar_low)}"
                    f"<br>entry_bar_close: {_hover_price(candidate.entry_bar_close)}"
                )
        hover_text.append(
            (
            f"<b>{row.direction}</b>"
            f"<br>session_date: {row.session_date.isoformat()}"
            f"<br>direction: {row.direction}"
            f"<br>breakout_type: {row.breakout_type}"
            f"<br>signal_time: {row.signal_time.strftime('%Y-%m-%d %H:%M ET')}"
            f"<br>OR high: {row.or_high:,.2f}"
            f"<br>OR low: {row.or_low:,.2f}"
            f"<br>OR mid: {row.or_mid:,.2f}"
            f"<br>ambiguity status: {str(bool(row.ambiguity_status)).lower()}"
            f"{execution_details}"
            )
        )
    return hover_text


def _hover_time(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M ET") if pd.notna(value) else "N/A"


def _hover_price(value) -> str:
    return f"{value:,.2f}" if pd.notna(value) else "N/A"


def show_research_viewer(figure: go.Figure, *, renderer: str | None = None) -> None:
    """Open the viewer with pan, both-axis zoom, and mouse-wheel zoom enabled."""
    figure.show(
        renderer=renderer,
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "doubleClick": "reset",
            "responsive": True,
        },
    )


def _as_boolean(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values
    normalized = values.astype(str).str.strip().str.lower()
    invalid = ~normalized.isin({"true", "false"})
    if invalid.any():
        raise ValueError("valid_or must contain only True/False values")
    return normalized.eq("true")


def _as_date(value: str | date, label: str) -> date:
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a valid date") from error


def _as_time(value: str | time, label: str) -> time:
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a time such as '09:25'") from error


def _append_segment(
    segment: dict[str, list], x0: pd.Timestamp, x1: pd.Timestamp, level: float
) -> None:
    if pd.isna(level):
        return
    segment["x"].extend((x0, x1, None))
    segment["y"].extend((float(level), float(level), None))


def _candle_hover_text(price_data: pd.DataFrame) -> list[str]:
    contracts = (
        price_data["contract"].astype(str)
        if "contract" in price_data.columns
        else pd.Series("", index=price_data.index)
    )
    return [
        (
            f"<b>{timestamp.strftime('%Y-%m-%d %H:%M ET')}</b>"
            f"<br>{contract}"
            f"<br>Open: {row.open:,.2f}"
            f"<br>High: {row.high:,.2f}"
            f"<br>Low: {row.low:,.2f}"
            f"<br>Close: {row.close:,.2f}"
            f"<br>Volume: {row.volume:,.0f}"
        )
        for timestamp, row, contract in zip(
            price_data.index,
            price_data[["open", "high", "low", "close", "volume"]].itertuples(
                index=False
            ),
            contracts,
        )
    ]


def _build_time_ticks(
    chart_data: pd.DataFrame, session_dates: list[date]
) -> tuple[list[int], list[str]]:
    """Return readable date/time ticks for the compressed session axis."""
    ticks_per_session = max(1, min(4, 12 // len(session_dates)))
    tick_values: list[int] = []
    tick_labels: list[str] = []

    for session_date in session_dates:
        session_data = chart_data.loc[chart_data["session_date"] == session_date]
        if ticks_per_session == 1 or len(session_data) == 1:
            positions = [len(session_data) // 2]
        elif len(session_dates) == 1:
            last_position = len(session_data) - 1
            positions = sorted(
                {
                    round(index * last_position / (ticks_per_session - 1))
                    for index in range(ticks_per_session)
                }
            )
        else:
            # Do not place a tick on the final candle in a multi-session view;
            # it would collide with the next session's date label.
            positions = sorted(
                {
                    round(index * len(session_data) / ticks_per_session)
                    for index in range(ticks_per_session)
                }
            )

        for position_index, position in enumerate(positions):
            timestamp = session_data.index[position]
            tick_values.append(int(session_data["_display_x"].iloc[position]))
            if position_index == 0:
                tick_labels.append(
                    f"{session_date.isoformat()}<br>{timestamp.strftime('%H:%M')}"
                )
            else:
                tick_labels.append(timestamp.strftime("%H:%M"))

    return tick_values, tick_labels
