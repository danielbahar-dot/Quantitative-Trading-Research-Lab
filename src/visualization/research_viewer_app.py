"""Small local web interface for the Plotly Research Viewer."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from typing import Callable
from urllib.parse import parse_qs, urlparse
import webbrowser

import pandas as pd
import plotly
import plotly.io as pio

from src.backtesting.candidate_entries import build_candidate_entries
from src.backtesting.completed_trades import simulate_completed_trades
from src.visualization.research_viewer import (
    SUPPORTED_BREAKOUT_TYPES,
    SUPPORTED_OR_MINUTES,
    build_research_viewer,
    find_orb_signals,
    load_or_levels,
    load_price_data,
)


SignalBuilder = Callable[..., object]
SIGNAL_BUILDERS: dict[str, SignalBuilder] = {"ORB": build_research_viewer}


@dataclass(frozen=True)
class ViewerDefaults:
    start_date: str
    end_date: str
    or_minutes: int = 15
    start_time: str = "09:25"
    end_time: str = "11:45"
    signal: str = "ORB"
    breakout_type: str = "PRINT"
    execution_overlay: bool = False


@dataclass
class ViewerState:
    price_data: pd.DataFrame
    or_levels: pd.DataFrame
    defaults: ViewerDefaults

    @property
    def browser_config(self) -> dict:
        available_dates = sorted(self.price_data["session_date"].unique())
        return {
            "min_date": available_dates[0].isoformat(),
            "max_date": available_dates[-1].isoformat(),
            "start_date": self.defaults.start_date,
            "end_date": self.defaults.end_date,
            "or_minutes": self.defaults.or_minutes,
            "start_time": self.defaults.start_time,
            "end_time": self.defaults.end_time,
            "signal": self.defaults.signal,
            "breakout_type": self.defaults.breakout_type,
            "execution_overlay": self.defaults.execution_overlay,
            "signals": list(SIGNAL_BUILDERS),
            "breakout_types": list(SUPPORTED_BREAKOUT_TYPES),
            "or_choices": list(SUPPORTED_OR_MINUTES),
        }


def run_research_viewer_app(
    data_file: str | Path,
    or_file: str | Path,
    *,
    defaults: ViewerDefaults,
    host: str = "127.0.0.1",
    port: int = 8050,
    open_browser: bool = True,
) -> None:
    """Load the research data once, then run the local viewer interface."""
    print("Loading validated MNQ data...")
    state = ViewerState(
        price_data=load_price_data(data_file),
        or_levels=load_or_levels(or_file),
        defaults=defaults,
    )
    server = _create_server(host, port, state)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"

    if open_browser:
        Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    print(f"Research Viewer ready: {url}")
    print("Press Ctrl+C in this window when you are finished.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nResearch Viewer stopped.")
    finally:
        server.server_close()


def _create_server(host: str, preferred_port: int, state: ViewerState):
    handler = _handler_for(state)
    for port in range(preferred_port, preferred_port + 20):
        try:
            return ThreadingHTTPServer((host, port), handler)
        except OSError:
            continue
    raise OSError("Could not find an available local port for the Research Viewer")


def _handler_for(state: ViewerState):
    plotly_javascript = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"

    class ResearchViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request = urlparse(self.path)
            if request.path == "/":
                config = json.dumps(state.browser_config)
                page = INDEX_HTML.replace("__VIEWER_CONFIG__", config)
                self._send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
                return
            if request.path == "/plotly.min.js":
                self._send_bytes(
                    plotly_javascript.read_bytes(), "text/javascript; charset=utf-8"
                )
                return
            if request.path == "/api/figure":
                self._send_figure(parse_qs(request.query))
                return
            if request.path == "/api/signals.csv":
                self._send_signal_table(parse_qs(request.query))
                return
            if request.path == "/api/candidates.csv":
                self._send_candidate_table(parse_qs(request.query))
                return
            if request.path == "/api/trades.csv":
                self._send_trade_table(parse_qs(request.query))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _send_figure(self, query: dict[str, list[str]]) -> None:
            try:
                signal = _query_value(query, "signal", state.defaults.signal)
                builder = SIGNAL_BUILDERS.get(signal)
                if builder is None:
                    raise ValueError(f"Unknown signal: {signal}")

                figure = builder(
                    state.price_data,
                    state.or_levels,
                    start_date=_query_value(query, "start_date", state.defaults.start_date),
                    end_date=_query_value(query, "end_date", state.defaults.end_date),
                    or_minutes=int(
                        _query_value(query, "or_minutes", str(state.defaults.or_minutes))
                    ),
                    breakout_type=_query_value(
                        query, "breakout_type", state.defaults.breakout_type
                    ),
                    start_time=_query_value(query, "start_time", state.defaults.start_time),
                    end_time=_query_value(query, "end_time", state.defaults.end_time),
                    instrument="MNQ",
                    execution_overlay=_query_bool(
                        query,
                        "execution_overlay",
                        state.defaults.execution_overlay,
                    ),
                )
                payload = pio.to_json(figure, validate=False, pretty=False).encode("utf-8")
                self._send_bytes(payload, "application/json; charset=utf-8")
            except (TypeError, ValueError) as error:
                self._send_bytes(
                    json.dumps({"error": str(error)}).encode("utf-8"),
                    "application/json; charset=utf-8",
                    status=HTTPStatus.BAD_REQUEST,
                )

        def _send_signal_table(self, query: dict[str, list[str]]) -> None:
            try:
                signals, _ = find_orb_signals(
                    state.price_data,
                    state.or_levels,
                    start_date=_query_value(
                        query, "start_date", state.defaults.start_date
                    ),
                    end_date=_query_value(query, "end_date", state.defaults.end_date),
                    or_minutes=int(
                        _query_value(query, "or_minutes", str(state.defaults.or_minutes))
                    ),
                    breakout_type=_query_value(
                        query, "breakout_type", state.defaults.breakout_type
                    ),
                )
                export = signals.copy()
                if not export.empty:
                    export["session_date"] = export["session_date"].astype(str)
                    export["signal_time"] = export["signal_time"].map(
                        lambda value: value.isoformat()
                    )
                self._send_bytes(
                    export.to_csv(index=False).encode("utf-8"),
                    "text/csv; charset=utf-8",
                )
            except (TypeError, ValueError) as error:
                self._send_bytes(
                    str(error).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.BAD_REQUEST,
                )

        def _send_candidate_table(self, query: dict[str, list[str]]) -> None:
            try:
                or_minutes = int(
                    _query_value(query, "or_minutes", str(state.defaults.or_minutes))
                )
                signals, _ = find_orb_signals(
                    state.price_data,
                    state.or_levels,
                    start_date=_query_value(
                        query, "start_date", state.defaults.start_date
                    ),
                    end_date=_query_value(query, "end_date", state.defaults.end_date),
                    or_minutes=or_minutes,
                    breakout_type=_query_value(
                        query, "breakout_type", state.defaults.breakout_type
                    ),
                )
                export = build_candidate_entries(
                    state.price_data,
                    signals,
                    or_minutes=or_minutes,
                )
                if not export.empty:
                    export["session_date"] = export["session_date"].astype(str)
                    for column in ("signal_time", "entry_time"):
                        export[column] = export[column].map(
                            lambda value: value.isoformat()
                            if pd.notna(value)
                            else ""
                        )
                self._send_bytes(
                    export.to_csv(index=False).encode("utf-8"),
                    "text/csv; charset=utf-8",
                )
            except (TypeError, ValueError) as error:
                self._send_bytes(
                    str(error).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.BAD_REQUEST,
                )

        def _send_trade_table(self, query: dict[str, list[str]]) -> None:
            try:
                or_minutes = int(
                    _query_value(query, "or_minutes", str(state.defaults.or_minutes))
                )
                signals, _ = find_orb_signals(
                    state.price_data,
                    state.or_levels,
                    start_date=_query_value(
                        query, "start_date", state.defaults.start_date
                    ),
                    end_date=_query_value(query, "end_date", state.defaults.end_date),
                    or_minutes=or_minutes,
                    breakout_type=_query_value(
                        query, "breakout_type", state.defaults.breakout_type
                    ),
                )
                candidates = build_candidate_entries(
                    state.price_data,
                    signals,
                    or_minutes=or_minutes,
                )
                export = simulate_completed_trades(
                    state.price_data,
                    candidates,
                )
                if not export.empty:
                    export["session_date"] = export["session_date"].astype(str)
                    for column in ("signal_time", "entry_time", "exit_time"):
                        export[column] = export[column].map(
                            lambda value: value.isoformat()
                            if pd.notna(value)
                            else ""
                        )
                self._send_bytes(
                    export.to_csv(index=False).encode("utf-8"),
                    "text/csv; charset=utf-8",
                )
            except (TypeError, ValueError) as error:
                self._send_bytes(
                    str(error).encode("utf-8"),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.BAD_REQUEST,
                )

        def _send_bytes(
            self,
            payload: bytes,
            content_type: str,
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args) -> None:
            return

    return ResearchViewerHandler


def _query_value(query: dict[str, list[str]], name: str, default: str) -> str:
    values = query.get(name)
    return values[0] if values and values[0] else default


def _query_bool(query: dict[str, list[str]], name: str, default: bool) -> bool:
    value = _query_value(query, name, str(default).lower()).strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MNQ Research Viewer</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; color: #172033; background: #f5f7fb; }
    * { box-sizing: border-box; }
    html, body { height: 100%; overflow: hidden; }
    body { margin: 0; background: #f5f7fb; }
    main { height: 100vh; padding: 16px; display: flex; flex-direction: column; }
    .controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; padding: 14px; background: #fff; border: 1px solid #dce2ea; border-radius: 10px; }
    label { display: grid; gap: 5px; color: #4b5565; font-size: 12px; font-weight: 600; }
    input, select, button, .button-link { min-height: 38px; border: 1px solid #c8d0dc; border-radius: 7px; background: #fff; color: #172033; font: inherit; padding: 7px 10px; }
    button, .button-link { cursor: pointer; font-weight: 600; }
    button:hover, .button-link:hover { background: #eef3f9; }
    .button-link { display: inline-flex; align-items: center; text-decoration: none; }
    button.primary { background: #1f5fae; border-color: #1f5fae; color: #fff; }
    button.primary:hover { background: #184d8f; }
    button:disabled { cursor: wait; opacity: .65; }
    .axis-controls { display: flex; flex-wrap: wrap; gap: 7px; margin-left: auto; }
    .axis-controls button { font-size: 13px; }
    .status-row { min-height: 38px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; padding: 7px 4px 3px; color: #526071; font-size: 13px; }
    #error { color: #b42318; font-weight: 600; }
    #chart { width: 100%; min-height: 0; flex: 1 1 auto; background: #fff; border: 1px solid #dce2ea; border-radius: 10px; overflow: hidden; }
    @media (max-width: 980px) {
      html, body { height: auto; overflow: auto; }
      main { height: auto; min-height: 100vh; }
      .axis-controls { width: 100%; margin-left: 0; }
      #chart { height: 700px; min-height: 560px; flex: none; }
    }
  </style>
</head>
<body>
<main>
  <section class="controls" aria-label="Research Viewer controls">
    <label>Signal<select id="signal"></select></label>
    <label>Start date<input id="start-date" type="date"></label>
    <label>End date<input id="end-date" type="date"></label>
    <label>OR duration<select id="or-minutes"></select></label>
    <label>Breakout type<select id="breakout-type"></select></label>
    <label>Execution overlay<select id="execution-overlay"><option value="false">Off</option><option value="true">On</option></select></label>
    <label>Start time<input id="start-time" type="time"></label>
    <label>End time<input id="end-time" type="time"></label>
    <button id="update" class="primary" type="button">Update chart</button>
    <a id="signal-table" class="button-link" href="#" download="orb-signals.csv">Signal table (CSV)</a>
    <a id="candidate-table" class="button-link" href="#" download="orb-candidates.csv">Candidate table (CSV)</a>
    <a id="trade-table" class="button-link" href="#" download="orb-completed-trades.csv">Completed trades (CSV)</a>
    <div class="axis-controls" aria-label="Axis scaling controls">
      <button id="fit-all" type="button">Fit all</button><button id="auto-y" type="button">Auto Y</button>
      <button id="x-in" type="button">X zoom in</button><button id="x-out" type="button">X zoom out</button>
      <button id="y-in" type="button">Y zoom in</button><button id="y-out" type="button">Y zoom out</button>
    </div>
  </section>
  <div class="status-row">
    <span id="status">Loading chart…</span>
    <span>Wheel: X zoom · Shift + wheel: Y zoom · Drag: pan · Double-click: reset</span>
    <span id="error" role="alert"></span>
  </div>
  <div id="chart" role="img" aria-label="MNQ candlestick research chart"></div>
</main>
<script src="/plotly.min.js"></script>
<script>
  const viewerConfig = __VIEWER_CONFIG__;
  const chart = document.getElementById("chart");
  const status = document.getElementById("status");
  const error = document.getElementById("error");
  let figureReady = false;
  let fullXRange = null;

  function option(value, label = value) { const item = document.createElement("option"); item.value = value; item.textContent = label; return item; }
  function initializeControls() {
    const signal = document.getElementById("signal");
    viewerConfig.signals.forEach(value => signal.appendChild(option(value)));
    signal.value = viewerConfig.signal;
    const startDate = document.getElementById("start-date");
    const endDate = document.getElementById("end-date");
    for (const input of [startDate, endDate]) { input.min = viewerConfig.min_date; input.max = viewerConfig.max_date; }
    startDate.value = viewerConfig.start_date; endDate.value = viewerConfig.end_date;
    const orMinutes = document.getElementById("or-minutes");
    viewerConfig.or_choices.forEach(value => orMinutes.appendChild(option(value, `${value} min`)));
    orMinutes.value = String(viewerConfig.or_minutes);
    const breakoutType = document.getElementById("breakout-type");
    viewerConfig.breakout_types.forEach(value => breakoutType.appendChild(option(value)));
    breakoutType.value = viewerConfig.breakout_type;
    document.getElementById("execution-overlay").value = String(viewerConfig.execution_overlay);
    document.getElementById("start-time").value = viewerConfig.start_time;
    document.getElementById("end-time").value = viewerConfig.end_time;
  }
  function queryString() {
    return new URLSearchParams({ signal: document.getElementById("signal").value, start_date: document.getElementById("start-date").value, end_date: document.getElementById("end-date").value, or_minutes: document.getElementById("or-minutes").value, breakout_type: document.getElementById("breakout-type").value, execution_overlay: document.getElementById("execution-overlay").value, start_time: document.getElementById("start-time").value, end_time: document.getElementById("end-time").value }).toString();
  }
  async function updateChart() {
    const updateButton = document.getElementById("update");
    updateButton.disabled = true; error.textContent = ""; status.textContent = "Loading chart…";
    try {
      const response = await fetch(`/api/figure?${queryString()}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not build the chart");
      payload.layout.autosize = true;
      delete payload.layout.height;
      await Plotly.react(chart, payload.data, payload.layout, { responsive: true, displayModeBar: true, scrollZoom: false, doubleClick: "reset", displaylogo: false });
      const meta = payload.layout.meta || {}; fullXRange = meta.full_x_range || null;
      const skipped = (meta.skipped_or_sessions || []).length;
      const candidateStatus = meta.execution_overlay ? ` · ${meta.valid_candidate_count || 0} valid candidates · ${meta.invalid_candidate_count || 0} invalid` : "";
      const tradeStatus = meta.execution_overlay ? ` · ${meta.completed_trade_count || 0} completed trades · ${meta.excluded_trade_count || 0} excluded` : "";
      status.textContent = `${meta.sessions || 0} sessions · ${meta.candles || 0} candles · ${meta.long_signals || 0} long · ${meta.short_signals || 0} short · ${meta.ambiguous_bar_count || 0} ambiguous${candidateStatus}${tradeStatus}` + (skipped ? ` · OR unavailable for ${skipped} session(s)` : "");
      document.getElementById("signal-table").href = `/api/signals.csv?${queryString()}`;
      document.getElementById("candidate-table").href = `/api/candidates.csv?${queryString()}`;
      document.getElementById("trade-table").href = `/api/trades.csv?${queryString()}`;
      figureReady = true;
    } catch (problem) { error.textContent = problem.message; status.textContent = "Chart not updated"; }
    finally { updateButton.disabled = false; }
  }
  function zoomAxis(axisName, factor) {
    if (!figureReady) return;
    const axis = chart._fullLayout[axisName]; if (!axis || !axis.range) return;
    const low = Number(axis.range[0]); const high = Number(axis.range[1]); const center = (low + high) / 2; const half = ((high - low) * factor) / 2;
    Plotly.relayout(chart, { [`${axisName}.range`]: [center - half, center + half], [`${axisName}.autorange`]: false });
  }
  document.getElementById("update").addEventListener("click", updateChart);
  document.getElementById("fit-all").addEventListener("click", () => { if (!figureReady) return; const changes = {"yaxis.autorange": true}; if (fullXRange) { changes["xaxis.range"] = fullXRange; changes["xaxis.autorange"] = false; } Plotly.relayout(chart, changes); });
  document.getElementById("auto-y").addEventListener("click", () => { if (figureReady) Plotly.relayout(chart, {"yaxis.autorange": true}); });
  document.getElementById("x-in").addEventListener("click", () => zoomAxis("xaxis", .8));
  document.getElementById("x-out").addEventListener("click", () => zoomAxis("xaxis", 1.25));
  document.getElementById("y-in").addEventListener("click", () => zoomAxis("yaxis", .8));
  document.getElementById("y-out").addEventListener("click", () => zoomAxis("yaxis", 1.25));
  chart.addEventListener("wheel", event => { if (!figureReady) return; event.preventDefault(); zoomAxis(event.shiftKey ? "yaxis" : "xaxis", event.deltaY < 0 ? .82 : 1.22); }, {passive: false});
  initializeControls(); updateChart();
</script>
</body>
</html>
"""
