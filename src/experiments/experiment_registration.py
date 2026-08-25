"""Prospective experiment registration for Research Infrastructure V1.0.

Future experiment runners write one canonical record under their project and
use this module to refresh the existing reviewed ``experiment_index.json``.
The dashboard remains a read-only consumer of that index.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
import json
import mimetypes
import os
import platform
import re
import subprocess

from src.experiments.experiment_index import (
    SCHEMA_VERSION,
    VALID_DECISIONS,
    VALID_STATUSES,
    load_research_lifecycle,
    repository_root,
    resolve_artifact_path,
    validate_experiment_record,
)


REGISTRATION_API_VERSION = "1.0"
RECORD_FOLDER = "records"
MUTABLE_FIELDS = {
    "status",
    "notes",
    "summary_metrics",
    "decision",
    "runtime_metadata",
    "known_limitations",
    "warnings",
    "future_hypotheses",
}
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def create_experiment(
    *,
    experiment_id: str,
    project_id: str,
    strategy_id: str,
    strategy_version: str | None,
    research_stage: str,
    title: str,
    experiment_type: str,
    partition: str | list[str],
    confirmatory: bool,
    reserved_data_exposed: bool,
    gate: str | None = None,
    hypothesis: str | None = None,
    description: str | None = None,
    parent_experiment_ids: list[str] | None = None,
    source_gates: list[str] | None = None,
    configuration_path: str | Path | None = None,
    configuration_parameters: Mapping[str, Any] | None = None,
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    data_hash: str | None = None,
    instrument_id: str | None = None,
    universe_id: str | None = None,
    asset_class: str | None = None,
    timeframe: str | None = None,
    git_sha: str | None = None,
    status: str = "running",
    notes: str | None = None,
    project_root: str | Path | None = None,
) -> "ExperimentRun":
    """Create and index a new prospective experiment record.

    Research permissions are deliberately explicit inputs.  This function
    records partition exposure but never opens a dataset or decides whether a
    partition is allowed.
    """
    root = repository_root(project_root)
    _validate_identifier(experiment_id, "experiment_id")
    _validate_identifier(project_id, "project_id")
    _require_project_manifest(root, project_id)
    if experiment_id in _known_experiment_ids(root):
        raise ValueError(f"Experiment ID already exists: {experiment_id}")
    if status not in {"planned", "running"}:
        raise ValueError("New experiments must start as planned or running")
    if not isinstance(confirmatory, bool) or not isinstance(reserved_data_exposed, bool):
        raise ValueError("confirmatory and reserved_data_exposed must be explicit booleans")

    parents = list(parent_experiment_ids or [])
    unknown_parents = sorted(set(parents) - _known_experiment_ids(root))
    if unknown_parents:
        raise ValueError(f"Unknown parent experiment(s): {', '.join(unknown_parents)}")

    config_path = _normalise_reference_path(configuration_path, root)
    captured_sha, dirty = _git_provenance(root)
    started_at = _utc_now()
    record_path = _record_path(root, project_id, experiment_id)
    if record_path.exists():
        raise ValueError(f"Experiment record already exists: {experiment_id}")
    record = {
        "experiment_id": experiment_id,
        "project_id": project_id,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "research_stage": research_stage,
        "title": title,
        "gate": gate,
        "experiment_type": experiment_type,
        "hypothesis": hypothesis,
        "description": description,
        "scope": {
            "instrument_id": instrument_id,
            "universe_id": universe_id,
            "asset_class": asset_class,
            "timeframe": timeframe,
            "partition": deepcopy(partition),
        },
        "lineage": {
            "parent_experiment_ids": parents,
            "source_gates": list(source_gates or []),
        },
        "reproducibility": {
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "data_hash": data_hash,
            "config_path": config_path,
            "git_sha": git_sha or captured_sha,
            "working_tree_dirty": dirty,
            "run_timestamp": started_at,
        },
        "data_references": [],
        "configuration": {
            "path": config_path,
            "parameters": deepcopy(dict(configuration_parameters or {})),
        },
        "status": status,
        "decision": "none",
        "confirmatory": confirmatory,
        "reserved_data_exposed": reserved_data_exposed,
        "summary_metrics": {},
        "artifacts": [],
        "notes": notes,
        "known_limitations": [],
        "started_at": started_at,
        "updated_at": started_at,
        "completed_at": None,
        "failed_at": None,
        "failure": None,
        "runtime_metadata": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "registration": {
            "api_version": REGISTRATION_API_VERSION,
            "record_path": record_path.relative_to(root).as_posix(),
        },
    }
    _validate_record(record, root)
    _atomic_write_json(record_path, record)
    refresh_experiment_index(project_id, root)
    return ExperimentRun(experiment_id=experiment_id, project_root=root)


def register_artifact(
    experiment_id: str,
    *,
    artifact_id: str,
    artifact_type: str,
    title: str,
    path: str | Path,
    description: str | None = None,
    mime_type: str | None = None,
    category: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    required: bool = True,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Idempotently register one canonical artifact path without copying it."""
    root = repository_root(project_root)
    record, record_path = _load_registered_record(experiment_id, root)
    _assert_open(record)
    _validate_identifier(artifact_id, "artifact_id")
    if not isinstance(artifact_type, str) or not artifact_type.strip():
        raise ValueError("artifact_type must be a non-empty string")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("artifact title must be a non-empty string")
    resolved = resolve_artifact_path(path, root)
    relative = resolved.relative_to(root).as_posix()
    artifact = {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "title": title,
        "path": relative,
        "description": description,
        "mime_type": mime_type or mimetypes.guess_type(resolved.name)[0],
        "category": category,
        "metadata": deepcopy(dict(metadata or {})),
        "required": required,
    }
    existing = {item["artifact_id"]: item for item in record["artifacts"]}
    if artifact_id in existing and existing[artifact_id]["path"] != relative:
        raise ValueError(
            f"Artifact ID {artifact_id} is already bound to {existing[artifact_id]['path']}"
        )
    existing[artifact_id] = artifact
    record["artifacts"] = sorted(existing.values(), key=lambda item: item["artifact_id"])
    _persist_registered_record(record, record_path, root)
    return deepcopy(artifact)


def update_experiment(
    experiment_id: str,
    updates: Mapping[str, Any],
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Update declared mutable metadata while protecting identity/provenance."""
    root = repository_root(project_root)
    record, record_path = _load_registered_record(experiment_id, root)
    _assert_open(record)
    unsupported = sorted(set(updates) - MUTABLE_FIELDS)
    if unsupported:
        raise ValueError(
            "Immutable or unsupported experiment field(s): " + ", ".join(unsupported)
        )
    updated = deepcopy(record)
    for name, value in updates.items():
        if name == "status":
            if value == "complete":
                raise ValueError("Use finalize_experiment() to mark an experiment complete")
            if value == "failed":
                raise ValueError("Use fail_experiment() to record a failed experiment")
            if value not in VALID_STATUSES:
                raise ValueError(f"Unsupported experiment status: {value}")
        elif name == "decision" and value not in VALID_DECISIONS:
            raise ValueError(f"Unsupported experiment decision: {value}")
        elif name in {"summary_metrics", "runtime_metadata"}:
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} must be an object")
            updated[name] = {**updated.get(name, {}), **deepcopy(dict(value))}
            continue
        elif name in {"known_limitations", "warnings", "future_hypotheses"}:
            if not isinstance(value, list):
                raise ValueError(f"{name} must be a list")
        updated[name] = deepcopy(value)
    _persist_registered_record(updated, record_path, root)
    return deepcopy(updated)


def finalize_experiment(
    experiment_id: str,
    *,
    summary_metrics: Mapping[str, Any] | None = None,
    decision: str | None = None,
    notes: str | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate artifacts, persist completion, and refresh the dashboard index."""
    root = repository_root(project_root)
    record, record_path = _load_registered_record(experiment_id, root)
    if record["status"] == "complete":
        return deepcopy(record)
    if record["status"] == "failed":
        raise ValueError("A failed experiment cannot be finalized as complete")
    missing = []
    for artifact in record["artifacts"]:
        resolved = resolve_artifact_path(artifact["path"], root)
        if artifact.get("required", True) and not resolved.is_file():
            missing.append(artifact["path"])
    if missing:
        raise FileNotFoundError("Required experiment artifact(s) missing: " + ", ".join(missing))

    completed = deepcopy(record)
    if summary_metrics is not None:
        if not isinstance(summary_metrics, Mapping):
            raise ValueError("summary_metrics must be an object")
        completed["summary_metrics"] = {
            **completed.get("summary_metrics", {}),
            **deepcopy(dict(summary_metrics)),
        }
    if decision is not None:
        if decision not in VALID_DECISIONS:
            raise ValueError(f"Unsupported experiment decision: {decision}")
        completed["decision"] = decision
    if notes is not None:
        completed["notes"] = notes
    completed_at = _utc_now()
    final_git_sha, final_dirty = _git_provenance(root)
    completed["reproducibility"] = {
        **completed["reproducibility"],
        "final_git_sha": final_git_sha,
        "final_working_tree_dirty": final_dirty,
    }
    completed.update({
        "status": "complete",
        "completed_at": completed_at,
        "updated_at": completed_at,
        "failure": None,
        "failed_at": None,
    })
    _persist_registered_record(completed, record_path, root, touch_updated_at=False)
    return deepcopy(completed)


def fail_experiment(
    experiment_id: str,
    error: BaseException | str,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Persist a FAILED record while leaving the original exception to callers."""
    root = repository_root(project_root)
    record, record_path = _load_registered_record(experiment_id, root)
    if record["status"] == "complete":
        raise ValueError("A completed experiment cannot be marked failed")
    failed = deepcopy(record)
    failed_at = _utc_now()
    failed.update({
        "status": "failed",
        "failed_at": failed_at,
        "updated_at": failed_at,
        "failure": {
            "type": type(error).__name__ if isinstance(error, BaseException) else "ExperimentFailure",
            "message": str(error),
        },
    })
    _persist_registered_record(failed, record_path, root, touch_updated_at=False)
    return deepcopy(failed)


def refresh_experiment_index(
    project_id: str,
    project_root: str | Path | None = None,
) -> Path:
    """Deterministically upsert prospective records into the one project index."""
    root = repository_root(project_root)
    _validate_identifier(project_id, "project_id")
    _require_project_manifest(root, project_id)
    project_dir = root / "experiments" / "projects" / project_id
    index_path = project_dir / "experiment_index.json"
    if index_path.exists():
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if str(payload.get("schema_version")) != SCHEMA_VERSION:
            raise ValueError(f"Unsupported experiment index version in {index_path}")
        if payload.get("project_id") != project_id:
            raise ValueError("Experiment index project_id does not match its directory")
    else:
        payload = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "records": []}

    valid_stages = {
        stage["stage_id"]: stage["ordinal"]
        for stage in load_research_lifecycle(root)["stages"]
    }
    merged: dict[str, dict[str, Any]] = {}
    for record in payload.get("records", []):
        validated = validate_experiment_record(deepcopy(record), valid_stages=set(valid_stages))
        if validated["project_id"] != project_id:
            raise ValueError("Experiment index contains a record for another project")
        if validated["experiment_id"] in merged:
            raise ValueError(f"Duplicate experiment ID: {validated['experiment_id']}")
        merged[validated["experiment_id"]] = validated

    prospective_ids: set[str] = set()
    for path in sorted((project_dir / RECORD_FOLDER).glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        validated = validate_experiment_record(record, valid_stages=set(valid_stages))
        if validated["project_id"] != project_id:
            raise ValueError(f"Registered record project mismatch: {path}")
        experiment_id = validated["experiment_id"]
        if experiment_id in prospective_ids:
            raise ValueError(f"Duplicate prospective experiment ID: {experiment_id}")
        prospective_ids.add(experiment_id)
        merged[experiment_id] = validated

    all_known = _known_experiment_ids(root) | set(merged)
    for record in merged.values():
        unknown = sorted(set(record["lineage"]["parent_experiment_ids"]) - all_known)
        if unknown:
            raise ValueError(
                f"Unknown parent experiment(s) for {record['experiment_id']}: {', '.join(unknown)}"
            )
    records = sorted(
        merged.values(),
        key=lambda record: (
            valid_stages[record["research_stage"]],
            record["reproducibility"].get("run_timestamp") or "",
            str(record.get("gate") or ""),
            record["experiment_id"],
        ),
    )
    refreshed = {"schema_version": SCHEMA_VERSION, "project_id": project_id, "records": records}
    serialized = json.dumps(refreshed, indent=2, ensure_ascii=False) + "\n"
    current = index_path.read_text(encoding="utf-8") if index_path.exists() else None
    if current != serialized:
        _atomic_write_text(index_path, serialized)
    return index_path


@dataclass(frozen=True)
class ExperimentRun:
    """Small convenience wrapper with optional context-manager finalization."""

    experiment_id: str
    project_root: Path

    @property
    def record(self) -> dict[str, Any]:
        record, _ = _load_registered_record(self.experiment_id, self.project_root)
        return deepcopy(record)

    def register_artifact(self, **kwargs: Any) -> dict[str, Any]:
        return register_artifact(self.experiment_id, project_root=self.project_root, **kwargs)

    def update(self, **updates: Any) -> dict[str, Any]:
        return update_experiment(self.experiment_id, updates, project_root=self.project_root)

    def finalize(self, **kwargs: Any) -> dict[str, Any]:
        return finalize_experiment(self.experiment_id, project_root=self.project_root, **kwargs)

    def __enter__(self) -> "ExperimentRun":
        if self.record["status"] == "planned":
            update_experiment(
                self.experiment_id, {"status": "running"}, project_root=self.project_root
            )
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: Any) -> bool:
        del exc_type, traceback
        if exc is not None:
            fail_experiment(self.experiment_id, exc, project_root=self.project_root)
            return False
        if self.record["status"] not in {"complete", "failed"}:
            finalize_experiment(self.experiment_id, project_root=self.project_root)
        return False


def _validate_record(record: dict[str, Any], root: Path) -> None:
    schema_path = root / "experiments" / "schema" / "experiment_record.schema.json"
    if not schema_path.is_file():
        raise FileNotFoundError(f"Experiment record schema is missing: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    missing = sorted(set(schema.get("required", [])) - set(record))
    if missing:
        raise ValueError("Experiment record missing schema fields: " + ", ".join(missing))
    stages = {stage["stage_id"] for stage in load_research_lifecycle(root)["stages"]}
    validate_experiment_record(record, valid_stages=stages)


def _persist_registered_record(
    record: dict[str, Any],
    record_path: Path,
    root: Path,
    *,
    touch_updated_at: bool = True,
) -> None:
    if touch_updated_at:
        record["updated_at"] = _utc_now()
    _validate_record(record, root)
    _atomic_write_json(record_path, record)
    refresh_experiment_index(record["project_id"], root)


def _load_registered_record(experiment_id: str, root: Path) -> tuple[dict[str, Any], Path]:
    _validate_identifier(experiment_id, "experiment_id")
    matches = list((root / "experiments" / "projects").glob(f"*/{RECORD_FOLDER}/{experiment_id}.json"))
    if not matches:
        raise KeyError(f"Experiment is not managed by automatic registration: {experiment_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate registered experiment records: {experiment_id}")
    path = matches[0]
    record = json.loads(path.read_text(encoding="utf-8"))
    _validate_record(record, root)
    return record, path


def _record_path(root: Path, project_id: str, experiment_id: str) -> Path:
    return root / "experiments" / "projects" / project_id / RECORD_FOLDER / f"{experiment_id}.json"


def _require_project_manifest(root: Path, project_id: str) -> None:
    path = root / "experiments" / "projects" / project_id / "project.json"
    if not path.is_file():
        raise FileNotFoundError(f"Project manifest is required before experiment registration: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("project_id") != project_id:
        raise ValueError("Project manifest project_id does not match its directory")


def _known_experiment_ids(root: Path) -> set[str]:
    projects_by_id: dict[str, set[str]] = {}
    for path in sorted((root / "experiments" / "projects").glob("*/experiment_index.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        project_id = path.parent.name
        for record in payload.get("records", []):
            experiment_id = record.get("experiment_id")
            if isinstance(experiment_id, str):
                projects_by_id.setdefault(experiment_id, set()).add(project_id)
    for path in sorted((root / "experiments" / "projects").glob(f"*/{RECORD_FOLDER}/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        experiment_id = record.get("experiment_id")
        if isinstance(experiment_id, str):
            projects_by_id.setdefault(experiment_id, set()).add(path.parents[1].name)
    duplicates = sorted(
        experiment_id for experiment_id, projects in projects_by_id.items() if len(projects) > 1
    )
    if duplicates:
        raise ValueError(f"Duplicate experiment IDs across projects: {', '.join(duplicates)}")
    return set(projects_by_id)


def _assert_open(record: Mapping[str, Any]) -> None:
    if record["status"] in {"complete", "failed"}:
        raise ValueError(f"Experiment is immutable after {record['status']}: {record['experiment_id']}")


def _validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must use letters, numbers, dots, underscores, or hyphens")


def _normalise_reference_path(value: str | Path | None, root: Path) -> str | None:
    if value is None:
        return None
    return resolve_artifact_path(value, root).relative_to(root).as_posix()


def _git_provenance(root: Path) -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=5, check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True,
            text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if sha.returncode != 0 or status.returncode != 0:
        return None, None
    return sha.stdout.strip() or None, bool(status.stdout.strip())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False,
            prefix=f".{path.name}.", suffix=".tmp",
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
