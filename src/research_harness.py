"""Lightweight SQLite + CSV experiment ledger for VectorBT research."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


COLUMNS = (
    "run_id", "timestamp_utc", "strategy_name", "strategy_version",
    "hypothesis", "dataset", "timeframe", "session", "parameters_json",
    "costs_slippage_json", "results_summary_json", "notes", "code_version",
    "code_hash", "artifact_paths_json", "config_path",
)

REQUIRED_CONFIG_FIELDS = (
    "strategy_name", "strategy_version", "hypothesis", "dataset", "timeframe",
    "session", "parameters", "costs_slippage",
)


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return (cleaned or "RUN")[:24].upper()


class ExperimentLedger:
    """Create, update, and inspect reproducible backtest records."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.experiments_dir = self.project_root / "experiments"
        self.runs_dir = self.experiments_dir / "runs"
        self.db_path = self.experiments_dir / "experiment_ledger.sqlite"
        self.csv_path = self.experiments_dir / "ledger.csv"
        self.schema_path = self.experiments_dir / "schema.sql"

    def initialize(self) -> None:
        """Create folders, database schema, and the CSV ledger if needed."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Missing schema file: {self.schema_path}")
        with self._connection() as connection:
            connection.executescript(self.schema_path.read_text(encoding="utf-8"))
        self.sync_csv()

    def create_run(self, config: str | Path | Mapping[str, Any]) -> tuple[str, Path]:
        """Register a new run, snapshot its config, and return its ID and folder."""
        self.initialize()
        config_data, source_path = self._load_config(config)
        missing = [key for key in REQUIRED_CONFIG_FIELDS if key not in config_data]
        if missing:
            raise ValueError(f"Config is missing required fields: {', '.join(missing)}")

        timestamp = datetime.now(timezone.utc)
        run_id = (
            f"{_slug(str(config_data['strategy_name']))}_"
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"
        )
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=False, exist_ok=False)

        snapshot_path = run_dir / "config.json"
        snapshot = dict(config_data)
        snapshot["run_id"] = run_id
        snapshot["timestamp_utc"] = timestamp.isoformat()
        snapshot_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        artifacts = dict(config_data.get("artifact_paths", {}))
        artifacts.setdefault("run_directory", self._store_path(run_dir))
        artifacts.setdefault("config", self._store_path(snapshot_path))
        row = {
            "run_id": run_id,
            "timestamp_utc": timestamp.isoformat(),
            "strategy_name": str(config_data["strategy_name"]),
            "strategy_version": str(config_data["strategy_version"]),
            "hypothesis": str(config_data["hypothesis"]),
            "dataset": str(config_data["dataset"]),
            "timeframe": str(config_data["timeframe"]),
            "session": _compact_json(config_data["session"]),
            "parameters_json": _compact_json(config_data["parameters"]),
            "costs_slippage_json": _compact_json(config_data["costs_slippage"]),
            "results_summary_json": _compact_json(config_data.get("results_summary", {})),
            "notes": str(config_data.get("notes", "")),
            "code_version": str(config_data.get("code_version") or self._git_version()),
            "code_hash": str(config_data.get("code_hash") or self._code_hash()),
            "artifact_paths_json": _compact_json(artifacts),
            "config_path": self._store_path(source_path or snapshot_path),
        }

        placeholders = ", ".join("?" for _ in COLUMNS)
        with self._connection() as connection:
            connection.execute(
                f"INSERT INTO experiments ({', '.join(COLUMNS)}) VALUES ({placeholders})",
                [row[column] for column in COLUMNS],
            )
        self.sync_csv()
        return run_id, run_dir

    def update_run(
        self,
        run_id: str,
        *,
        results_summary: Mapping[str, Any] | None = None,
        notes: str | None = None,
        artifact_paths: Mapping[str, str | Path] | None = None,
    ) -> dict[str, str]:
        """Update results, notes, or artifacts for an existing run."""
        self.initialize()
        current = self.get_run(run_id)
        artifacts = json.loads(current["artifact_paths_json"])
        for key, value in (artifact_paths or {}).items():
            artifacts[str(key)] = self._store_path(Path(value))

        results_json = _compact_json(
            results_summary
            if results_summary is not None
            else json.loads(current["results_summary_json"])
        )
        updated_notes = current["notes"] if notes is None else str(notes)
        artifacts_json = _compact_json(artifacts)
        with self._connection() as connection:
            connection.execute(
                """UPDATE experiments
                   SET results_summary_json = ?, notes = ?, artifact_paths_json = ?
                   WHERE run_id = ?""",
                (results_json, updated_notes, artifacts_json, run_id),
            )
        self.sync_csv()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, str]:
        """Return one run as a dictionary."""
        if not self.db_path.exists():
            raise FileNotFoundError("Ledger is not initialized. Run the init command first.")
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM experiments WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return dict(row)

    def sync_csv(self) -> None:
        """Rebuild the human-readable CSV mirror from SQLite."""
        rows: list[dict[str, str]] = []
        if self.db_path.exists():
            with self._connection() as connection:
                connection.row_factory = sqlite3.Row
                rows = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM experiments ORDER BY timestamp_utc, run_id"
                    ).fetchall()
                ]
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def _load_config(
        self, config: str | Path | Mapping[str, Any]
    ) -> tuple[dict[str, Any], Path | None]:
        if isinstance(config, Mapping):
            return dict(config), None
        path = Path(config)
        if not path.is_absolute():
            path = self.project_root / path
        return json.loads(path.read_text(encoding="utf-8")), path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _store_path(self, path: Path) -> str:
        if not path.is_absolute():
            path = self.project_root / path
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.project_root).as_posix()
        except ValueError:
            return str(resolved)

    def _git_version(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.project_root, check=True,
                capture_output=True, text=True, timeout=3,
            )
            return result.stdout.strip() or "unversioned"
        except (FileNotFoundError, subprocess.SubprocessError):
            return "unversioned"

    def _code_hash(self) -> str:
        digest = hashlib.sha256()
        file_count = 0
        for folder_name in ("src", "strategies"):
            folder = self.project_root / folder_name
            if not folder.exists():
                continue
            for path in sorted(folder.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                digest.update(path.relative_to(self.project_root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
                file_count += 1
        return digest.hexdigest() if file_count else "no-python-files"


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_json_argument(value: str) -> Mapping[str, Any]:
    candidate = Path(value)
    data = (
        json.loads(candidate.read_text(encoding="utf-8"))
        if candidate.exists()
        else json.loads(value)
    )
    if not isinstance(data, dict):
        raise ValueError("Results JSON must be an object.")
    return data


def _parse_artifacts(values: Sequence[str]) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Artifact must use key=path format: {value}")
        key, path = value.split("=", 1)
        if not key.strip() or not path.strip():
            raise ValueError(f"Artifact must use key=path format: {value}")
        artifacts[key.strip()] = path.strip()
    return artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=_default_root())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize the SQLite and CSV ledgers")
    create = commands.add_parser("create", help="Create and register a new run")
    create.add_argument("--config", required=True)
    update = commands.add_parser("update", help="Update results and artifacts")
    update.add_argument("--run-id", required=True)
    update.add_argument("--results-json", help="Inline JSON object or JSON file path")
    update.add_argument("--notes")
    update.add_argument("--artifact", action="append", default=[], help="key=path")
    show = commands.add_parser("show", help="Print one ledger record as JSON")
    show.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ledger = ExperimentLedger(args.project_root)
    try:
        if args.command == "init":
            ledger.initialize()
            print(f"Initialized ledger: {ledger.db_path}")
        elif args.command == "create":
            run_id, run_dir = ledger.create_run(args.config)
            print(f"run_id={run_id}")
            print(f"run_dir={run_dir}")
        elif args.command == "update":
            results = _parse_json_argument(args.results_json) if args.results_json else None
            record = ledger.update_run(
                args.run_id, results_summary=results, notes=args.notes,
                artifact_paths=_parse_artifacts(args.artifact),
            )
            print(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True))
        elif args.command == "show":
            print(json.dumps(ledger.get_run(args.run_id), indent=2, ensure_ascii=False))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
