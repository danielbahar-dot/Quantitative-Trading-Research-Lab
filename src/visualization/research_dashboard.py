"""Read-only Streamlit Research Dashboard for experiment and artifact navigation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import pandas as pd
import streamlit as st

from src.experiments.experiment_index import (
    get_experiment,
    list_artifacts,
    load_dataset_catalog,
    load_experiment_index,
    load_project_manifests,
    preview_csv,
    preview_text,
    repository_root,
)


VIEW_OPTIONS = ("Overview", "Experiments", "Strategy Versions", "Datasets / Partitions")
CSV_PREVIEW_ROWS = 100
CSV_PREVIEW_COLUMNS = 40
TEXT_PREVIEW_CHARACTERS = 200_000
DOWNLOAD_LIMIT_BYTES = 5 * 1024 * 1024


def run_dashboard(project_root: str | Path | None = None) -> None:
    root = repository_root(project_root)
    st.set_page_config(
        page_title="Research Dashboard",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _styles()
    manifests = _cached_manifests(str(root), _registry_signature(root))
    index = _cached_index(str(root), _registry_signature(root))
    if not manifests or index.empty:
        st.error("No reviewed project experiment index was found.")
        return

    manifest_by_id = {manifest["project_id"]: manifest for manifest in manifests}
    project_labels = {manifest["project_name"]: manifest["project_id"] for manifest in manifests}
    st.sidebar.title("Research Dashboard")
    st.sidebar.caption("Ledger + artifact explorer · read-only")
    project_label = st.sidebar.selectbox("Project", list(project_labels))
    project_id = project_labels[project_label]
    manifest = manifest_by_id[project_id]
    project_index = index.loc[index["project_id"].eq(project_id)]
    versions = [item["strategy_version"] for item in manifest.get("strategy_versions", [])]
    if not versions:
        versions = sorted(project_index["strategy_version"].dropna().unique())
    version = st.sidebar.selectbox("Strategy version", versions)
    view = st.sidebar.radio("View", VIEW_OPTIONS)
    selected = project_index.loc[project_index["strategy_version"].eq(version)].reset_index(drop=True)
    st.sidebar.divider()
    st.sidebar.info("This dashboard cannot run, edit, or delete experiments or artifacts.")

    if view == "Overview":
        _overview(manifest, version, selected, root)
    elif view == "Experiments":
        _experiments_view(manifest, version, selected, root)
    elif view == "Strategy Versions":
        _strategy_versions(manifest, version, selected)
    else:
        _datasets_view(project_id, selected, root)


@st.cache_data(show_spinner=False)
def _cached_index(root: str, signature: str) -> pd.DataFrame:
    del signature
    return load_experiment_index(root)


@st.cache_data(show_spinner=False)
def _cached_manifests(root: str, signature: str) -> list[dict[str, Any]]:
    del signature
    return load_project_manifests(root)


def _registry_signature(root: Path) -> str:
    paths = list((root / "experiments" / "projects").glob("*/experiment_index.json"))
    paths += list((root / "experiments" / "projects").glob("*/project.json"))
    return "|".join(f"{path}:{path.stat().st_mtime_ns}" for path in sorted(paths))


def _styles() -> None:
    st.markdown(
        """
        <style>
          .block-container {padding-top: 1.4rem; padding-bottom: 3rem;}
          .read-only-banner {padding:.7rem 1rem;border:1px solid #bfd2ea;background:#eef6ff;border-radius:.6rem;color:#254b73;margin-bottom:1rem;}
          .lifecycle {font-weight:650;letter-spacing:.01em;padding:.7rem 0 1rem;color:#28415d;}
          .artifact-path {font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.8rem;color:#596878;overflow-wrap:anywhere;}
          .muted {color:#65758b;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _header(title: str, subtitle: str | None = None) -> None:
    st.title(title)
    st.markdown(
        '<div class="read-only-banner"><b>Read-only research navigation.</b> '
        "Artifacts are shown from their canonical project paths; nothing is copied or modified.</div>",
        unsafe_allow_html=True,
    )
    if subtitle:
        st.caption(subtitle)


def _overview(manifest: dict[str, Any], version: str, index: pd.DataFrame, root: Path) -> None:
    version_record = _version_record(manifest, version)
    _header(f"{manifest['project_name']} · {version}", "Project overview and lifecycle handoff")
    cols = st.columns(4)
    cols[0].metric("Instrument", manifest.get("instrument_id") or "Unknown")
    cols[1].metric("Strategy family", manifest.get("strategy_family") or "Unknown")
    cols[2].metric("Indexed experiments", len(index))
    cols[3].metric("Indexed artifacts", int(index["artifact_count"].sum()))
    lifecycle = version_record.get("lifecycle", [])
    if lifecycle:
        st.markdown(f'<div class="lifecycle">{" → ".join(lifecycle)}</div>', unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        st.subheader("Current state")
        st.write(version_record.get("lifecycle_status") or "Unknown")
        st.markdown("**Decision**")
        st.write(version_record.get("decision") or "Unknown")
    with right:
        st.subheader("Current handoff")
        st.write(version_record.get("handoff") or "Not recorded")
        exposed = int(index["reserved_data_exposed"].sum())
        st.markdown("**Partition exposure**")
        st.write(f"{exposed} indexed experiment(s) explicitly used reserved or historically exposed data.")

    st.subheader("Lifecycle experiments")
    st.dataframe(
        _ledger_display(index), width="stretch", hide_index=True,
        column_config={"Confirmatory": st.column_config.CheckboxColumn(), "Reserved data exposed": st.column_config.CheckboxColumn()},
    )
    st.subheader("Artifact inventory")
    inventory = _artifact_inventory(index, root)
    if inventory.empty:
        st.info("No artifacts are registered for this project/version.")
    else:
        counts = inventory.groupby(["category", "type"], as_index=False).size().rename(columns={"size": "artifacts"})
        st.dataframe(counts, width="stretch", hide_index=True)


def _experiments_view(manifest: dict[str, Any], version: str, index: pd.DataFrame, root: Path) -> None:
    _header(f"Experiment Ledger · {manifest['project_name']} {version}", "Search, compare, and inspect registered research artifacts")
    filters = st.columns([2.2, 1.2, 1.2, 1.2, 1.4])
    search = filters[0].text_input("Search", placeholder="Gate, title, ID, type…")
    partition = filters[1].selectbox("Partition", ["All", *sorted(index["partition"].unique())])
    status = filters[2].selectbox("Status", ["All", *sorted(index["status"].unique())])
    decision = filters[3].selectbox("Decision", ["All", *sorted(index["decision"].unique())])
    experiment_type = filters[4].selectbox("Type", ["All", *sorted(index["experiment_type"].unique())])
    filtered = filter_experiment_index(
        index, search=search, partition=partition, status=status,
        decision=decision, experiment_type=experiment_type,
    )
    if filtered.empty:
        st.warning("No experiments match the current filters.")
        return

    display = _ledger_display(filtered)
    event = st.dataframe(
        display, width="stretch", hide_index=True, on_select="rerun",
        selection_mode="single-row", key="experiment_ledger_table",
    )
    row_selection = event.selection.rows if event and hasattr(event, "selection") else []
    selected_from_table = filtered.iloc[row_selection[0]]["experiment_id"] if row_selection else None
    options = filtered["experiment_id"].tolist()
    if selected_from_table in options:
        st.session_state["selected_experiment_id"] = selected_from_table
    current = st.session_state.get("selected_experiment_id")
    if current not in options:
        current = options[0]
    label_map = {
        row.experiment_id: f"Gate {row.gate} · {row.title}"
        for row in filtered.itertuples(index=False)
    }
    experiment_id = st.selectbox(
        "Selected experiment", options, index=options.index(current),
        format_func=lambda value: label_map[value],
    )
    st.session_state["selected_experiment_id"] = experiment_id

    with st.expander("Compare experiments", expanded=False):
        comparison_ids = st.multiselect(
            "Choose 2–4 compatible experiments", options,
            format_func=lambda value: label_map[value], max_selections=4,
        )
        if len(comparison_ids) >= 2:
            st.dataframe(compare_experiments(comparison_ids, root), width="stretch", hide_index=True)
        else:
            st.caption("Select at least two experiments. Only matching summary-metric keys are compared.")

    _experiment_detail(get_experiment(experiment_id, root), root)


def filter_experiment_index(
    index: pd.DataFrame,
    *,
    search: str = "",
    partition: str = "All",
    status: str = "All",
    decision: str = "All",
    experiment_type: str = "All",
) -> pd.DataFrame:
    output = index.copy()
    if search.strip():
        needle = search.strip().lower()
        haystack = output[["experiment_id", "gate", "title", "experiment_type"]].astype(str).agg(" ".join, axis=1).str.lower()
        output = output.loc[haystack.str.contains(needle, regex=False)]
    for column, value in (("partition", partition), ("status", status), ("decision", decision), ("experiment_type", experiment_type)):
        if value != "All":
            output = output.loc[output[column].eq(value)]
    return output.reset_index(drop=True)


def compare_experiments(experiment_ids: list[str], root: Path) -> pd.DataFrame:
    if not 2 <= len(experiment_ids) <= 4:
        raise ValueError("Experiment comparison requires 2–4 experiment IDs")
    records = [get_experiment(experiment_id, root) for experiment_id in experiment_ids]
    common = set(records[0]["summary_metrics"])
    for record in records[1:]:
        common &= set(record["summary_metrics"])
    rows = []
    for record in records:
        partition = record["scope"]["partition"]
        rows.append({
            "Experiment": record["experiment_id"], "Gate": record["gate"],
            "Partition": " + ".join(partition) if isinstance(partition, list) else partition,
            "Decision": record["decision"], "Status": record["status"],
            **{key: record["summary_metrics"].get(key) for key in sorted(common)},
        })
    return pd.DataFrame(rows)


def _experiment_detail(record: dict[str, Any], root: Path) -> None:
    st.divider()
    st.subheader(f"Gate {record['gate']} · {record['title']}")
    if record.get("warnings"):
        for warning in record["warnings"]:
            st.warning(warning)
    summary_tab, chart_tab, artifact_tab, lineage_tab, notes_tab = st.tabs(
        ["Summary", "Charts", "Data & Artifacts", "Lineage", "Notes / Decision"]
    )
    with summary_tab:
        _summary_tab(record)
    with chart_tab:
        _charts_tab(record["resolved_artifacts"], root)
    with artifact_tab:
        _artifacts_tab(record["resolved_artifacts"], root)
    with lineage_tab:
        _lineage_tab(record, root)
    with notes_tab:
        _notes_tab(record)


def _summary_tab(record: dict[str, Any]) -> None:
    left, right = st.columns(2)
    with left:
        st.markdown("**Purpose / hypothesis**")
        st.write(record.get("hypothesis") or "Unknown")
        st.markdown("**Description**")
        st.write(record.get("description") or "Unknown")
        st.markdown("**Partition**")
        st.write(_partition_label(record["scope"]["partition"]))
    with right:
        st.markdown("**Status / decision**")
        st.write(f"{record['status'].upper()} · {record['decision'].upper()}")
        st.markdown("**Research role**")
        st.write("Confirmatory" if record["confirmatory"] else "Exploratory / diagnostic")
        st.markdown("**Reserved data exposed**")
        st.write("Yes" if record["reserved_data_exposed"] else "No")
    metrics = record.get("summary_metrics", {})
    if metrics:
        st.markdown("**Summary metrics**")
        metric_columns = st.columns(min(4, len(metrics)))
        for index, (key, value) in enumerate(metrics.items()):
            metric_columns[index % len(metric_columns)].metric(key.replace("_", " ").title(), _format_value(value))
    repro = record["reproducibility"]
    st.markdown("**Reproducibility**")
    st.dataframe(pd.DataFrame([
        {"Dataset": repro.get("dataset_id"), "Data hash": repro.get("data_hash"),
         "Config": repro.get("config_path"), "Git SHA": repro.get("git_sha"),
         "Run timestamp": repro.get("run_timestamp")}
    ]), width="stretch", hide_index=True)


def _charts_tab(artifacts: list[dict[str, Any]], root: Path) -> None:
    charts = [artifact for artifact in artifacts if artifact["type"] == "chart"]
    if not charts:
        st.info("No chart artifacts are registered for this experiment.")
        return
    st.caption(f"{len(charts)} chart artifact(s). HTML is loaded only when a preview is expanded.")
    for artifact in charts:
        with st.expander(artifact["title"]):
            _artifact_header(artifact)
            if not artifact["exists"]:
                st.error("The registered artifact is missing from this checkout.")
                continue
            st.markdown(f"[Open local HTML in browser]({artifact['file_uri']})")
            if st.toggle("Embed chart", key=f"embed-{artifact['artifact_id']}"):
                if artifact["size_bytes"] > 2_000_000:
                    st.warning("HTML exceeds the safe inline-preview bound. Use the local-file link instead.")
                else:
                    st.iframe(root / artifact["path"], height=720)


def _artifacts_tab(artifacts: list[dict[str, Any]], root: Path) -> None:
    data_artifacts = [artifact for artifact in artifacts if artifact["type"] != "chart"]
    if not data_artifacts:
        st.info("No data or document artifacts are registered for this experiment.")
        return
    table = pd.DataFrame([{
        "Title": artifact["title"], "Type": artifact["type"],
        "Path": artifact["path"], "Size": _format_bytes(artifact["size_bytes"]),
        "Available": artifact["exists"],
    } for artifact in data_artifacts])
    st.dataframe(table, width="stretch", hide_index=True)
    artifact_map = {artifact["artifact_id"]: artifact for artifact in data_artifacts}
    selected_id = st.selectbox(
        "Preview artifact", list(artifact_map),
        format_func=lambda value: f"{artifact_map[value]['type']} · {artifact_map[value]['title']}",
    )
    artifact = artifact_map[selected_id]
    _artifact_header(artifact)
    if not artifact["exists"]:
        st.error("The registered artifact is missing from this checkout.")
        return
    st.markdown(f"[Open canonical local file]({artifact['file_uri']})")
    suffix = Path(artifact["path"]).suffix.lower()
    try:
        if suffix == ".csv":
            frame = preview_csv(artifact["path"], root, max_rows=CSV_PREVIEW_ROWS, max_columns=CSV_PREVIEW_COLUMNS)
            st.caption(f"Bounded preview: first {len(frame)} rows and at most {CSV_PREVIEW_COLUMNS} columns.")
            st.dataframe(frame, width="stretch", hide_index=True)
        elif suffix == ".json":
            text, truncated = preview_text(artifact["path"], root, max_characters=TEXT_PREVIEW_CHARACTERS)
            if truncated:
                st.warning("JSON exceeds the bounded preview size; showing raw truncated text.")
                st.code(text, language="json")
            else:
                st.json(json.loads(text))
        elif suffix == ".md":
            text, truncated = preview_text(artifact["path"], root, max_characters=TEXT_PREVIEW_CHARACTERS)
            st.markdown(text)
            if truncated:
                st.warning("Markdown preview was truncated.")
        else:
            st.info("Inline preview is not available for this file type.")
    except (OSError, ValueError, pd.errors.ParserError, json.JSONDecodeError) as error:
        st.error(f"Preview unavailable: {error}")
    if artifact["size_bytes"] is not None and artifact["size_bytes"] <= DOWNLOAD_LIMIT_BYTES:
        with Path(artifact["resolved_path"]).open("rb") as source:
            st.download_button(
                "Download a copy", source.read(), file_name=Path(artifact["path"]).name,
                mime=artifact.get("mime_type") or "application/octet-stream",
                key=f"download-{artifact['artifact_id']}",
            )
    elif artifact["size_bytes"]:
        st.caption("Large artifact: use the canonical path instead of loading the complete file into dashboard memory.")


def _artifact_header(artifact: dict[str, Any]) -> None:
    st.markdown(f"**{artifact['title']}** · `{artifact['type']}` · {_format_bytes(artifact['size_bytes'])}")
    if artifact.get("description"):
        st.write(artifact["description"])
    st.markdown(f'<div class="artifact-path">{artifact["path"]}</div>', unsafe_allow_html=True)


def _lineage_tab(record: dict[str, Any], root: Path) -> None:
    parent_ids = record["lineage"]["parent_experiment_ids"]
    child_ids = record.get("child_experiment_ids", [])
    st.markdown("**Source gates**")
    st.write(" → ".join(record["lineage"]["source_gates"]) or "None recorded")
    for label, ids in (("Parent experiments", parent_ids), ("Child experiments", child_ids)):
        st.markdown(f"**{label}**")
        if not ids:
            st.write("None")
            continue
        rows = []
        for experiment_id in ids:
            linked = get_experiment(experiment_id, root)
            rows.append({"Experiment ID": experiment_id, "Gate": linked["gate"], "Title": linked["title"]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _notes_tab(record: dict[str, Any]) -> None:
    st.markdown("**Decision**")
    st.write(record["decision"].upper())
    st.markdown("**Notes**")
    st.write(record.get("notes") or "No additional notes recorded.")
    if record.get("warnings"):
        st.markdown("**Warnings / limitations**")
        for warning in record["warnings"]:
            st.warning(warning)
    if record.get("future_hypotheses"):
        st.markdown("**Recorded future hypotheses**")
        for item in record["future_hypotheses"]:
            st.write(f"- {item}")


def _strategy_versions(manifest: dict[str, Any], version: str, index: pd.DataFrame) -> None:
    record = _version_record(manifest, version)
    _header(f"Strategy Version · {manifest['project_name']} {version}", "Version-scoped lifecycle and decisions")
    st.markdown(f"### {record.get('title', version)}")
    st.markdown(f'<div class="lifecycle">{" → ".join(record.get("lifecycle", []))}</div>', unsafe_allow_html=True)
    left, right = st.columns(2)
    left.markdown("**Lifecycle status**")
    left.write(record.get("lifecycle_status") or "Unknown")
    right.markdown("**Current decision**")
    right.write(record.get("decision") or "Unknown")
    st.markdown("**Handoff**")
    st.write(record.get("handoff") or "Not recorded")
    st.dataframe(_ledger_display(index), width="stretch", hide_index=True)


def _datasets_view(project_id: str, index: pd.DataFrame, root: Path) -> None:
    _header("Datasets / Partitions", "Informational provenance view; editing is disabled")
    datasets = [item for item in load_dataset_catalog(root) if item.get("project_id") == project_id]
    if not datasets:
        st.info("No dataset configuration is registered for this project.")
        return
    for dataset in datasets:
        instrument = dataset.get("instrument", {})
        st.subheader(dataset.get("dataset_id", "Unknown dataset"))
        cols = st.columns(4)
        cols[0].metric("Instrument", instrument.get("name") or dataset.get("instrument_id") or "Unknown")
        cols[1].metric("Asset class", dataset.get("asset_class") or "Unknown")
        cols[2].metric("Timezone", dataset.get("timezone") or "Unknown")
        cols[3].metric("Timestamp semantics", dataset.get("timestamp_semantics") or "Unknown")
        st.write(f"Source: `{dataset.get('source_file') or 'Unknown'}`")
        st.write(f"Configuration: `{dataset.get('config_path')}`")
        partitions = []
        for partition in dataset.get("partitions", []):
            displayed_name = "OOS_BURNED" if partition["name"] == "OOS" and dataset.get("current_orb_v01_oos_status") == "BURNED" else partition["name"]
            exposed = bool(index.loc[index["partition"].str.contains(partition["name"], regex=False), "reserved_data_exposed"].any())
            partitions.append({
                "Partition": displayed_name, "Start": partition.get("start"), "End": partition.get("end"),
                "Configured output": partition.get("output_file"),
                "Exposure status": "EXPOSED / BURNED" if displayed_name == "OOS_BURNED" or exposed else "NOT EXPOSED BY INDEXED EXPERIMENTS",
            })
        st.dataframe(pd.DataFrame(partitions), width="stretch", hide_index=True)
        if dataset.get("research_notes"):
            with st.expander("Dataset research notes"):
                for note in dataset["research_notes"]:
                    st.write(f"- {note}")


def _artifact_inventory(index: pd.DataFrame, root: Path) -> pd.DataFrame:
    rows = []
    for experiment_id in index["experiment_id"]:
        for artifact in list_artifacts(experiment_id, root):
            rows.append({"experiment_id": experiment_id, **artifact})
    return pd.DataFrame(rows)


def _ledger_display(index: pd.DataFrame) -> pd.DataFrame:
    return index[[
        "experiment_id", "gate", "title", "partition", "configurations",
        "status", "decision", "confirmatory", "reserved_data_exposed",
        "run_timestamp", "artifact_count",
    ]].rename(columns={
        "experiment_id": "Experiment ID", "gate": "Gate", "title": "Title",
        "partition": "Partition", "configurations": "Configurations / runs",
        "status": "Status", "decision": "Decision", "confirmatory": "Confirmatory",
        "reserved_data_exposed": "Reserved data exposed", "run_timestamp": "Run date",
        "artifact_count": "Artifacts",
    })


def _version_record(manifest: dict[str, Any], version: str) -> dict[str, Any]:
    for record in manifest.get("strategy_versions", []):
        if record.get("strategy_version") == version:
            return record
    return {"strategy_version": version, "title": version}


def _partition_label(value: str | list[str]) -> str:
    return " + ".join(value) if isinstance(value, list) else str(value)


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "Missing"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"


def _format_value(value: Any) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
