"""Persistence of derived timeframes as Parquet + JSON manifest (M4).

Derived bars are a **cache**, never authoritative data.  The canonical source
is the validated 1-minute partition file declared in the dataset partition
config.  Each Parquet file has a sibling manifest recording its provenance,
and a persisted file is only ever returned when the manifest proves it still
matches:

- the Parquet file's own SHA-256;
- the current ``TIMEFRAME_BUILDER_VERSION``;
- the effective session model (timezone, bounds, calendar overrides);
- the source partition file's SHA-256 (unless explicitly skipped).

Anything else raises ``StaleDerivedTimeframeError``; there is no silent
rebuild on read.  Layout::

    data/derived/timeframes/<dataset_id>/<partition>/
        <dataset_id>__<partition>__<tf>__tfb-v<N>.parquet
        <dataset_id>__<partition>__<tf>__tfb-v<N>.manifest.json

Only DEVELOPMENT-role partitions are processed unless
``allow_reserved_partition=True`` is passed explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
import hashlib
import json
import os
import platform
import subprocess

import pandas as pd

from src.data.instruments import load_instrument
from src.data.sessions import SessionSpec, load_session_spec
from src.data.timeframes import (
    OUTPUT_COLUMNS,
    TIMEFRAME_BUILDER_VERSION,
    TimeframeSpec,
    build_timeframe,
    get_timeframe,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_CONFIG = PROJECT_ROOT / "config" / "datasets" / "mnq_1m_actual_contract_v1.partitions.json"
DEFAULT_DERIVED_ROOT = PROJECT_ROOT / "data" / "derived" / "timeframes"
MANIFEST_SCHEMA_VERSION = "1.0"
DEVELOPMENT_ROLE = "DEVELOPMENT"
SOURCE_COLUMNS = ["timestamp_et", "session_date", "contract", "open", "high", "low", "close", "volume"]
CONVENTIONS = {
    "source_bar_labels": "bar_end",
    "index": "timestamp_et equals bar_end",
    "available_at": "bar_end (nominal, clipped to the session), also for incomplete bars",
    "anchor": "regular session open; buckets clipped to actual session bounds",
    "incomplete_bar_policy": "emitted with expected_bars/observed_bars and is_complete=False",
    "empty_bucket_policy": "no row; bars are never synthesized",
    "mixed_contract_policy": "error",
}


class TimeframeStoreError(ValueError):
    """Base error for derived-timeframe persistence."""


class DerivedTimeframeNotFoundError(TimeframeStoreError, LookupError):
    """No persisted derived timeframe exists for the request."""


class StaleDerivedTimeframeError(TimeframeStoreError):
    """A persisted derived timeframe no longer matches its provenance."""


@dataclass(frozen=True)
class DerivedTimeframe:
    """Location and manifest of one persisted derived timeframe."""

    data_path: Path
    manifest_path: Path
    manifest: Mapping[str, Any]
    written: bool


def derived_paths(
    dataset_id: str,
    partition: str,
    timeframe: TimeframeSpec | str,
    output_root: str | Path = DEFAULT_DERIVED_ROOT,
) -> tuple[Path, Path]:
    """Return the (parquet, manifest) paths for a derived timeframe."""
    spec = get_timeframe(timeframe)
    for label, value in (("dataset_id", dataset_id), ("partition", partition), ("timeframe", spec.timeframe_id)):
        if not value or any(character in value for character in '/\\:*?"<>|') or value in (".", ".."):
            raise TimeframeStoreError(f"Invalid {label} for a file name: {value!r}")
    stem = f"{dataset_id}__{partition}__{spec.timeframe_id}__tfb-v{TIMEFRAME_BUILDER_VERSION}"
    folder = Path(output_root) / dataset_id / partition
    return folder / f"{stem}.parquet", folder / f"{stem}.manifest.json"


def materialize_timeframe(
    timeframe: TimeframeSpec | str,
    *,
    partition: str,
    dataset_config: str | Path = DEFAULT_DATASET_CONFIG,
    session_spec: SessionSpec | None = None,
    output_root: str | Path = DEFAULT_DERIVED_ROOT,
    project_root: str | Path = PROJECT_ROOT,
    allow_reserved_partition: bool = False,
    rebuild: bool = False,
) -> DerivedTimeframe:
    """Build a derived timeframe from a partition file and persist it.

    An existing file whose manifest is still valid is returned unchanged
    (``written=False``) unless ``rebuild=True``.  A stale file is replaced.
    """
    spec = get_timeframe(timeframe)
    session = session_spec if session_spec is not None else load_session_spec()
    dataset, entry = _partition_entry(dataset_config, partition, allow_reserved_partition)
    root = Path(project_root)
    source_path = _resolve(entry["output_file"], root)
    if not source_path.is_file():
        raise TimeframeStoreError(f"Partition source file not found: {source_path}")
    data_path, manifest_path = derived_paths(dataset["dataset_id"], partition, spec, output_root)

    source_sha = _sha256(source_path)
    if not rebuild and manifest_path.is_file() and data_path.is_file():
        try:
            manifest = _validated_manifest(data_path, manifest_path, session, source_sha)
            return DerivedTimeframe(data_path, manifest_path, manifest, written=False)
        except StaleDerivedTimeframeError:
            pass

    bars = _load_source(source_path, dataset, entry, session)
    derived = build_timeframe(bars, spec, session)
    instrument = load_instrument(dataset["instrument_id"])

    data_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(data_path, lambda handle: derived.to_parquet(handle, engine="pyarrow", index=True))
    git_sha, git_dirty = _git_provenance(root)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_type": "derived_timeframe",
        "authoritative": False,
        "dataset_id": dataset["dataset_id"],
        "partition": {
            "name": partition,
            "role": entry.get("partition_role"),
            "evidence_status": entry.get("evidence_status"),
            "start": entry["start"],
            "end": entry["end"],
        },
        "instrument": {
            "instrument_id": instrument.instrument_id,
            "contracts": sorted(str(value) for value in bars["contract"].unique()),
        },
        "source": {
            "path": _display_path(source_path, root),
            "sha256": source_sha,
            "row_count": int(len(bars)),
            "first_bar_end": bars.index.min().isoformat(),
            "last_bar_end": bars.index.max().isoformat(),
            "timestamp_semantics": dataset.get("timestamp_semantics"),
        },
        "timeframe": {"timeframe_id": spec.timeframe_id, "minutes": spec.minutes},
        "session": {
            "session_id": session.session_id,
            "timezone": session.timezone,
            "fingerprint_sha256": session_fingerprint(session),
            "calendar_coverage": (
                [day.isoformat() for day in session.calendar_coverage]
                if session.calendar_coverage else None
            ),
            "override_count": len(session.overrides),
        },
        "conventions": CONVENTIONS,
        "generation": {
            "builder_version": TIMEFRAME_BUILDER_VERSION,
            "git_sha": git_sha,
            "git_dirty": git_dirty,
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "pyarrow": _pyarrow_version(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "output": {
            "path": data_path.name,
            "sha256": _sha256(data_path),
            "row_count": int(len(derived)),
            "columns": list(OUTPUT_COLUMNS),
            "incomplete_count": int((~derived["is_complete"]).sum()),
            "session_truncated_count": int(derived["is_session_truncated"].sum()),
            "first_bar_end": derived.index.min().isoformat(),
            "last_bar_end": derived.index.max().isoformat(),
        },
    }
    _atomic_write(
        manifest_path,
        lambda handle: handle.write((json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")),
    )
    return DerivedTimeframe(data_path, manifest_path, manifest, written=True)


def load_timeframe(
    timeframe: TimeframeSpec | str,
    *,
    partition: str,
    dataset_config: str | Path = DEFAULT_DATASET_CONFIG,
    session_spec: SessionSpec | None = None,
    output_root: str | Path = DEFAULT_DERIVED_ROOT,
    project_root: str | Path = PROJECT_ROOT,
    allow_reserved_partition: bool = False,
    verify_source: bool = True,
) -> pd.DataFrame:
    """Return a persisted derived timeframe after validating its manifest.

    Raises ``DerivedTimeframeNotFoundError`` when nothing is persisted and
    ``StaleDerivedTimeframeError`` when provenance no longer matches.  With
    ``verify_source=False`` the source partition is not re-hashed.
    """
    spec = get_timeframe(timeframe)
    session = session_spec if session_spec is not None else load_session_spec()
    dataset, entry = _partition_entry(dataset_config, partition, allow_reserved_partition)
    data_path, manifest_path = derived_paths(dataset["dataset_id"], partition, spec, output_root)
    if not manifest_path.is_file() or not data_path.is_file():
        raise DerivedTimeframeNotFoundError(
            f"No persisted {spec.timeframe_id} for {dataset['dataset_id']}/{partition} at {data_path}"
        )
    source_sha = None
    if verify_source:
        source_path = _resolve(entry["output_file"], Path(project_root))
        if not source_path.is_file():
            raise StaleDerivedTimeframeError(f"Source partition file missing: {source_path}")
        source_sha = _sha256(source_path)
    _validated_manifest(data_path, manifest_path, session, source_sha)
    frame = pd.read_parquet(data_path, engine="pyarrow")
    if list(frame.columns) != OUTPUT_COLUMNS or frame.index.name != "timestamp_et":
        raise StaleDerivedTimeframeError(f"Unexpected schema in {data_path}")
    return frame


def session_fingerprint(spec: SessionSpec) -> str:
    """SHA-256 of the effective session model, including calendar overrides."""
    payload = {
        "session_id": spec.session_id,
        "timezone": spec.timezone,
        "open": [spec.open_time.isoformat(), spec.open_day_offset],
        "close": spec.close_time.isoformat(),
        "break": [spec.break_start.isoformat(), spec.break_end.isoformat()],
        "trading_weekdays": sorted(spec.trading_weekdays),
        "coverage": [day.isoformat() for day in spec.calendar_coverage] if spec.calendar_coverage else None,
        "overrides": [
            {
                "trading_date": override.trading_date.isoformat(),
                "kind": override.kind,
                "open": override.open_time.isoformat() if override.open_time else None,
                "open_day_offset": override.open_day_offset,
                "close": override.close_time.isoformat() if override.close_time else None,
            }
            for _, override in sorted(spec.overrides.items())
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _validated_manifest(
    data_path: Path,
    manifest_path: Path,
    session: SessionSpec,
    source_sha: str | None,
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StaleDerivedTimeframeError(f"Unreadable manifest {manifest_path}: {error}") from error
    checks = [
        (manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION, "manifest schema version"),
        (manifest.get("generation", {}).get("builder_version") == TIMEFRAME_BUILDER_VERSION, "builder version"),
        (manifest.get("session", {}).get("fingerprint_sha256") == session_fingerprint(session), "session model"),
        (manifest.get("output", {}).get("sha256") == _sha256(data_path), "output file hash"),
    ]
    if source_sha is not None:
        checks.append((manifest.get("source", {}).get("sha256") == source_sha, "source file hash"))
    failed = [name for ok, name in checks if not ok]
    if failed:
        raise StaleDerivedTimeframeError(f"{data_path.name} is stale: {', '.join(failed)} mismatch")
    return manifest


def _partition_entry(
    dataset_config: str | Path,
    partition: str,
    allow_reserved_partition: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(dataset_config)
    try:
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TimeframeStoreError(f"Cannot read dataset config {path}: {error}") from error
    for key in ("dataset_id", "instrument_id", "partitions"):
        if key not in dataset:
            raise TimeframeStoreError(f"Dataset config {path} missing {key!r}")
    matches = [item for item in dataset["partitions"] if item.get("name") == partition]
    if len(matches) != 1:
        raise TimeframeStoreError(f"Partition {partition!r} not uniquely defined in {path}")
    entry = matches[0]
    for key in ("start", "end", "output_file"):
        if key not in entry:
            raise TimeframeStoreError(f"Partition {partition!r} missing {key!r}")
    if entry.get("partition_role") != DEVELOPMENT_ROLE and not allow_reserved_partition:
        raise TimeframeStoreError(
            f"Partition {partition!r} has role {entry.get('partition_role')!r}; "
            "pass allow_reserved_partition=True only with explicit authorization"
        )
    return dataset, entry


def _load_source(
    path: Path,
    dataset: Mapping[str, Any],
    entry: Mapping[str, Any],
    session: SessionSpec,
) -> pd.DataFrame:
    if dataset.get("timezone") not in (None, session.timezone):
        raise TimeframeStoreError(
            f"Dataset timezone {dataset.get('timezone')!r} differs from session timezone {session.timezone!r}"
        )
    header = set(pd.read_csv(path, nrows=0).columns)
    missing = [column for column in SOURCE_COLUMNS if column not in header]
    if missing:
        raise TimeframeStoreError(f"Source {path} missing columns: {missing}")
    frame = pd.read_csv(path, usecols=SOURCE_COLUMNS)
    frame["timestamp_et"] = pd.to_datetime(frame["timestamp_et"], utc=True).dt.tz_convert(session.timezone)
    dates = pd.to_datetime(frame["session_date"]).dt.date
    start, end = pd.Timestamp(entry["start"]).date(), pd.Timestamp(entry["end"]).date()
    if dates.min() < start or dates.max() > end:
        raise TimeframeStoreError(
            f"Source {path} has session dates {dates.min()}..{dates.max()} outside partition {start}..{end}"
        )
    return frame.set_index("timestamp_et")


def _resolve(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, write) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("wb", dir=path.parent, delete=False, prefix=f".{path.name}.", suffix=".tmp") as handle:
            temporary_path = Path(handle.name)
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _git_provenance(root: Path) -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=5, check=False)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True,
                                text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, None
    if sha.returncode != 0 or status.returncode != 0:
        return None, None
    return sha.stdout.strip() or None, bool(status.stdout.strip())


def _pyarrow_version() -> str | None:
    try:
        import pyarrow
    except ImportError:
        return None
    return pyarrow.__version__
