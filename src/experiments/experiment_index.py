"""Reusable, read-only experiment index and artifact discovery.

Reviewed project records are the authoritative dashboard index.  Existing
experiment metadata remains canonical for run-specific detail, and historical
folders can be discovered through record-level glob patterns without moving or
renaming their artifacts.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
import json
import mimetypes
import re

import pandas as pd


SCHEMA_VERSION = "1.0"
VALID_STATUSES = {"planned", "running", "complete", "failed"}
VALID_DECISIONS = {"continue", "freeze", "pass", "revise", "reject", "diagnostic", "none"}
VALID_COMPONENT_TYPES = {"feature", "signal", "state_variable", "strategy"}
REQUIRED_RECORD_FIELDS = {
    "experiment_id", "project_id", "strategy_id", "strategy_version",
    "research_stage", "title", "gate",
    "experiment_type", "hypothesis", "description", "scope", "lineage",
    "reproducibility", "status",
    "decision", "confirmatory", "reserved_data_exposed", "summary_metrics",
    "artifacts",
}
REQUIRED_SCOPE_FIELDS = {"instrument_id", "universe_id", "asset_class", "timeframe", "partition"}
REQUIRED_LINEAGE_FIELDS = {"parent_experiment_ids", "source_gates"}
REQUIRED_REPRO_FIELDS = {"dataset_id", "data_hash", "config_path", "git_sha", "run_timestamp"}
REQUIRED_ARTIFACT_FIELDS = {"artifact_id", "type", "title", "path"}
REQUIRED_CONFIGURATION_FIELDS = {"path", "parameters"}
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv", "tmp", "temp"}


def repository_root(project_root: str | Path | None = None) -> Path:
    return Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]


def validate_experiment_record(
    record: dict[str, Any],
    *,
    valid_stages: set[str] | None = None,
) -> dict[str, Any]:
    """Validate the lightweight V1.0 contract without another dependency."""
    missing = sorted(REQUIRED_RECORD_FIELDS - set(record))
    if missing:
        raise ValueError(f"Experiment record missing fields: {', '.join(missing)}")
    for name in (
        "experiment_id", "project_id", "strategy_id", "research_stage",
        "title", "experiment_type",
    ):
        if not isinstance(record[name], str) or not record[name].strip():
            raise ValueError(f"Experiment field {name} must be a non-empty string")
    if valid_stages is not None and record["research_stage"] not in valid_stages:
        raise ValueError(f"Unsupported research stage: {record['research_stage']}")
    if record["strategy_version"] is not None and not isinstance(record["strategy_version"], str):
        raise ValueError("strategy_version must be a string or null")
    if record["status"] not in VALID_STATUSES:
        raise ValueError(f"Unsupported experiment status: {record['status']}")
    if record["decision"] not in VALID_DECISIONS:
        raise ValueError(f"Unsupported experiment decision: {record['decision']}")
    for name in ("confirmatory", "reserved_data_exposed"):
        if not isinstance(record[name], bool):
            raise ValueError(f"{name} must be boolean")
    _require_mapping_fields(record["scope"], REQUIRED_SCOPE_FIELDS, "scope")
    _require_mapping_fields(record["lineage"], REQUIRED_LINEAGE_FIELDS, "lineage")
    _require_mapping_fields(record["reproducibility"], REQUIRED_REPRO_FIELDS, "reproducibility")
    if "configuration" in record:
        _require_mapping_fields(record["configuration"], REQUIRED_CONFIGURATION_FIELDS, "configuration")
    if not isinstance(record["lineage"]["parent_experiment_ids"], list):
        raise ValueError("parent_experiment_ids must be a list")
    if not isinstance(record["lineage"]["source_gates"], list):
        raise ValueError("source_gates must be a list")
    partition = record["scope"]["partition"]
    if not isinstance(partition, str) and not (
        isinstance(partition, list)
        and partition
        and all(isinstance(value, str) and value.strip() for value in partition)
    ):
        raise ValueError("scope.partition must be a string or non-empty list of strings")
    for name in ("parent_experiment_ids", "source_gates"):
        values = record["lineage"][name]
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError(f"lineage.{name} must contain non-empty strings")
    if not isinstance(record["summary_metrics"], dict):
        raise ValueError("summary_metrics must be an object")
    if "data_references" in record and not isinstance(record["data_references"], list):
        raise ValueError("data_references must be a list")
    if "configuration" in record and not isinstance(record["configuration"]["parameters"], dict):
        raise ValueError("configuration.parameters must be an object")
    if "known_limitations" in record and not isinstance(record["known_limitations"], list):
        raise ValueError("known_limitations must be a list")
    if not isinstance(record["artifacts"], list):
        raise ValueError("artifacts must be a list")
    artifact_ids = set()
    for artifact in record["artifacts"]:
        _require_mapping_fields(artifact, REQUIRED_ARTIFACT_FIELDS, "artifact")
        for name in REQUIRED_ARTIFACT_FIELDS:
            if not isinstance(artifact[name], str) or not artifact[name].strip():
                raise ValueError(f"artifact.{name} must be a non-empty string")
        if "required" in artifact and not isinstance(artifact["required"], bool):
            raise ValueError("artifact.required must be boolean")
        if "metadata" in artifact and not isinstance(artifact["metadata"], dict):
            raise ValueError("artifact.metadata must be an object")
        if artifact["artifact_id"] in artifact_ids:
            raise ValueError(f"Duplicate artifact ID in {record['experiment_id']}: {artifact['artifact_id']}")
        artifact_ids.add(artifact["artifact_id"])
    for name in ("started_at", "updated_at", "completed_at", "failed_at"):
        if name in record and record[name] is not None and not isinstance(record[name], str):
            raise ValueError(f"{name} must be a string or null")
    if "runtime_metadata" in record and not isinstance(record["runtime_metadata"], dict):
        raise ValueError("runtime_metadata must be an object")
    if "failure" in record and record["failure"] is not None and not isinstance(record["failure"], dict):
        raise ValueError("failure must be an object or null")
    return record


def _require_mapping_fields(value: Any, required: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"{label} missing fields: {', '.join(missing)}")


def load_project_manifests(project_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = repository_root(project_root)
    manifests = []
    for path in sorted((root / "experiments" / "projects").glob("*/project.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["_manifest_path"] = path.relative_to(root).as_posix()
        manifests.append(manifest)
    project_ids = [item.get("project_id") for item in manifests]
    if len(project_ids) != len(set(project_ids)):
        raise ValueError("Duplicate project IDs in project manifests")
    return manifests


def load_research_lifecycle(project_root: str | Path | None = None) -> dict[str, Any]:
    root = repository_root(project_root)
    path = root / "experiments" / "schema" / "research_lifecycle_v1.json"
    lifecycle = json.loads(path.read_text(encoding="utf-8"))
    stages = lifecycle.get("stages", [])
    stage_ids = [stage.get("stage_id") for stage in stages]
    ordinals = [stage.get("ordinal") for stage in stages]
    if len(stages) != 12 or len(stage_ids) != len(set(stage_ids)):
        raise ValueError("Research Lifecycle V1.0 must contain 12 unique stages")
    if sorted(ordinals) != list(range(12)):
        raise ValueError("Research Lifecycle V1.0 stage ordinals must be 0 through 11")
    return lifecycle


def load_component_registry(project_root: str | Path | None = None) -> dict[str, Any]:
    root = repository_root(project_root)
    path = root / "config" / "components" / "research_components.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    if str(registry.get("schema_version")) != "1.0":
        raise ValueError("Unsupported research component registry version")
    components = registry.get("components", [])
    ids = [component.get("component_id") for component in components]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate research component IDs")
    known = set(ids)
    for component in components:
        missing = {
            "component_id", "component_type", "name", "version", "status",
            "definition", "dependencies", "timing", "validation",
        } - set(component)
        if missing:
            raise ValueError(f"Research component missing fields: {', '.join(sorted(missing))}")
        if component["component_type"] not in VALID_COMPONENT_TYPES:
            raise ValueError(f"Unsupported research component type: {component['component_type']}")
        unknown = set(component["dependencies"]) - known
        if unknown:
            raise ValueError(f"Unknown component dependencies: {', '.join(sorted(unknown))}")
    return registry


def load_experiment_records(project_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = repository_root(project_root)
    valid_stages = {stage["stage_id"] for stage in load_research_lifecycle(root)["stages"]}
    records: list[dict[str, Any]] = []
    for path in sorted((root / "experiments" / "projects").glob("*/experiment_index.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("schema_version")) != SCHEMA_VERSION:
            raise ValueError(f"Unsupported experiment index version in {path}")
        for source in payload.get("records", []):
            record = validate_experiment_record(deepcopy(source), valid_stages=valid_stages)
            record["_index_path"] = path.relative_to(root).as_posix()
            records.append(record)
    ids = [record["experiment_id"] for record in records]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"Duplicate experiment IDs: {', '.join(duplicates)}")
    known = set(ids)
    for record in records:
        unknown = sorted(set(record["lineage"]["parent_experiment_ids"]) - known)
        if unknown:
            raise ValueError(f"Unknown parent experiment(s) for {record['experiment_id']}: {', '.join(unknown)}")
    return records


def load_experiment_index(
    project_root: str | Path | None = None,
    *,
    project_id: str | None = None,
    strategy_version: str | None = None,
) -> pd.DataFrame:
    """Return a lightweight, filterable table without loading artifact content."""
    records = load_experiment_records(project_root)
    children = _child_map(records)
    stages = {
        stage["stage_id"]: stage
        for stage in load_research_lifecycle(project_root)["stages"]
    }
    rows = []
    for record in records:
        partition = record["scope"]["partition"]
        partition_label = " + ".join(partition) if isinstance(partition, list) else str(partition)
        artifacts = _list_artifacts_for_record(record, repository_root(project_root))
        stage = stages[record["research_stage"]]
        rows.append({
            "experiment_id": record["experiment_id"], "project_id": record["project_id"],
            "strategy_id": record["strategy_id"],
            "strategy_version": record["strategy_version"], "gate": record["gate"],
            "research_stage": record["research_stage"],
            "stage_order": stage["ordinal"], "stage_label": stage["short_label"],
            "title": record["title"], "experiment_type": record["experiment_type"],
            "partition": partition_label, "status": record["status"],
            "decision": record["decision"], "confirmatory": record["confirmatory"],
            "reserved_data_exposed": record["reserved_data_exposed"],
            "run_timestamp": record["reproducibility"]["run_timestamp"],
            "dataset_id": record["reproducibility"]["dataset_id"],
            "configurations": _configuration_count(record["summary_metrics"]),
            "artifact_count": len(artifacts),
            "missing_artifact_count": sum(not artifact["exists"] for artifact in artifacts),
            "parent_experiment_ids": record["lineage"]["parent_experiment_ids"],
            "child_experiment_ids": children.get(record["experiment_id"], []),
            "source_gates": record["lineage"]["source_gates"],
        })
    frame = pd.DataFrame(rows)
    if project_id is not None:
        frame = frame.loc[frame["project_id"].eq(project_id)]
    if strategy_version is not None:
        frame = frame.loc[frame["strategy_version"].eq(strategy_version)]
    return frame.sort_values(
        ["project_id", "strategy_version", "stage_order", "gate"],
        kind="stable", na_position="first",
    ).reset_index(drop=True)


def _configuration_count(metrics: dict[str, Any]) -> int | None:
    for key in ("configurations", "variants", "frozen_candidates"):
        value = metrics.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def get_experiment(
    experiment_id: str,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    records = load_experiment_records(project_root)
    selected = [record for record in records if record["experiment_id"] == experiment_id]
    if not selected:
        raise KeyError(f"Unknown experiment ID: {experiment_id}")
    record = deepcopy(selected[0])
    record["child_experiment_ids"] = _child_map(records).get(experiment_id, [])
    record["resolved_artifacts"] = _list_artifacts_for_record(record, repository_root(project_root))
    return record


def list_artifacts(
    experiment_id: str,
    project_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    return get_experiment(experiment_id, project_root)["resolved_artifacts"]


def _child_map(records: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for record in records:
        for parent in record["lineage"]["parent_experiment_ids"]:
            children.setdefault(parent, []).append(record["experiment_id"])
    return {key: sorted(value) for key, value in children.items()}


def resolve_artifact_path(path: str | Path, project_root: str | Path | None = None) -> Path:
    """Resolve repository-relative and historical absolute paths safely."""
    root = repository_root(project_root)
    raw = Path(str(path).replace("\\", "/"))
    if raw.is_absolute():
        candidate = raw.resolve()
        if _is_within(candidate, root):
            return candidate
        parts = list(raw.parts)
        for marker in ("experiments", "config", "data", "reports"):
            if marker in parts:
                candidate = (root / Path(*parts[parts.index(marker):])).resolve()
                break
        else:
            raise ValueError(f"Artifact path is outside the repository: {path}")
    else:
        candidate = (root / raw).resolve()
    if not _is_within(candidate, root):
        raise ValueError(f"Artifact path escapes the repository: {path}")
    return candidate


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _list_artifacts_for_record(record: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for artifact in record.get("artifacts", []):
        artifacts.append(_materialize_artifact(record["experiment_id"], artifact, root))

    metadata_path = record.get("metadata_path")
    if metadata_path:
        metadata = resolve_artifact_path(metadata_path, root)
        if metadata.exists():
            try:
                payload = json.loads(metadata.read_text(encoding="utf-8"))
                declarations = payload.get("artifacts") or payload.get("outputs") or {}
                if isinstance(declarations, dict):
                    for key, value in declarations.items():
                        if isinstance(value, str):
                            artifacts.append(_artifact_from_path(record["experiment_id"], value, root, title=_humanize(key)))
            except (json.JSONDecodeError, OSError):
                pass

    for pattern in record.get("artifact_patterns", []):
        pattern_path = Path(str(pattern).replace("\\", "/"))
        if pattern_path.is_absolute():
            parent, glob_pattern = pattern_path.parent, pattern_path.name
            matches = parent.glob(glob_pattern) if _is_within(parent.resolve(), root) else []
        else:
            matches = root.glob(pattern_path.as_posix())
        for match in sorted(matches):
            if match.is_file() and not any(part in IGNORED_PARTS for part in match.parts):
                artifacts.append(_artifact_from_path(record["experiment_id"], match, root))

    unique: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        unique.setdefault(artifact["path"].lower(), artifact)
    return sorted(unique.values(), key=lambda item: (item["category"], item["title"], item["path"]))


def _materialize_artifact(experiment_id: str, artifact: dict[str, Any], root: Path) -> dict[str, Any]:
    resolved = resolve_artifact_path(artifact["path"], root)
    relative = resolved.relative_to(root).as_posix()
    output = deepcopy(artifact)
    output.update({
        "path": relative, "resolved_path": str(resolved), "exists": resolved.is_file(),
        "size_bytes": resolved.stat().st_size if resolved.is_file() else None,
        "mime_type": artifact.get("mime_type") or mimetypes.guess_type(resolved.name)[0],
        "category": artifact.get("category") or _artifact_category(artifact["type"]),
        "description": artifact.get("description"),
        "file_uri": resolved.as_uri(),
    })
    return output


def _artifact_from_path(
    experiment_id: str,
    path: str | Path,
    root: Path,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_artifact_path(path, root)
    relative = resolved.relative_to(root).as_posix()
    artifact_type = _artifact_type(resolved)
    return {
        "artifact_id": f"{experiment_id}:{_slug(relative)}",
        "type": artifact_type,
        "title": title or _humanize(resolved.stem),
        "path": relative,
        "resolved_path": str(resolved),
        "description": None,
        "mime_type": mimetypes.guess_type(resolved.name)[0],
        "category": _artifact_category(artifact_type),
        "exists": resolved.is_file(),
        "size_bytes": resolved.stat().st_size if resolved.is_file() else None,
        "file_uri": resolved.as_uri(),
    }


def _artifact_type(path: Path) -> str:
    name = path.name.lower()
    if path.suffix.lower() == ".html":
        return "chart"
    if "signal" in name and ("audit" in name or path.suffix.lower() == ".csv"):
        return "signal_audit"
    if "feature" in name and ("audit" in name or path.suffix.lower() == ".csv"):
        return "feature_audit"
    if "execution" in name and ("audit" in name or path.suffix.lower() == ".csv"):
        return "execution_audit"
    if "candidate" in name and ("audit" in name or path.suffix.lower() == ".csv"):
        return "candidate_audit"
    if "trade" in name and path.suffix.lower() == ".csv":
        return "trade_audit"
    if "freeze" in name or "validation_candidates" in name:
        return "freeze"
    if path.suffix.lower() == ".json" and "config" in name:
        return "config"
    if "metadata" in name or "protocol" in name:
        return "metadata"
    if path.suffix.lower() == ".md":
        return "report"
    if any(token in name for token in ("summary", "sweep", "comparison", "classification")):
        return "summary"
    if path.suffix.lower() in {".csv", ".parquet", ".feather"}:
        return "data"
    if path.suffix.lower() == ".json":
        return "metadata"
    return "other"


def _artifact_category(artifact_type: str) -> str:
    if artifact_type == "chart":
        return "charts"
    if artifact_type in {"config", "metadata", "freeze"}:
        return "governance"
    if artifact_type in {"report", "source", "test"}:
        return "reports"
    return "data"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _humanize(value: str) -> str:
    return re.sub(r"[_-]+", " ", value).strip().title()


def preview_csv(
    path: str | Path,
    project_root: str | Path | None = None,
    *,
    max_rows: int = 100,
    max_columns: int = 50,
) -> pd.DataFrame:
    if max_rows < 1 or max_columns < 1:
        raise ValueError("CSV preview bounds must be positive")
    resolved = resolve_artifact_path(path, project_root)
    if resolved.suffix.lower() != ".csv":
        raise ValueError("CSV preview requires a .csv artifact")
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    frame = pd.read_csv(resolved, nrows=max_rows)
    return frame.iloc[:, :max_columns]


def preview_text(
    path: str | Path,
    project_root: str | Path | None = None,
    *,
    max_characters: int = 200_000,
) -> tuple[str, bool]:
    if max_characters < 1:
        raise ValueError("Text preview bound must be positive")
    resolved = resolve_artifact_path(path, project_root)
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    with resolved.open("r", encoding="utf-8", errors="replace") as source:
        content = source.read(max_characters + 1)
    return content[:max_characters], len(content) > max_characters


def load_dataset_catalog(project_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = repository_root(project_root)
    instruments = {}
    for path in sorted((root / "config" / "instruments").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        instruments[payload.get("instrument_id")] = payload
    datasets = []
    for path in sorted((root / "config" / "datasets").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Normalize the one historical project-specific field at the ingestion
        # boundary so generic dashboard code never depends on an ORB name.
        payload["current_oos_status"] = payload.get(
            "current_oos_status", payload.get("current_orb_v01_oos_status")
        )
        payload["instrument"] = instruments.get(payload.get("instrument_id"), {})
        payload["config_path"] = path.relative_to(root).as_posix()
        datasets.append(payload)
    return datasets
