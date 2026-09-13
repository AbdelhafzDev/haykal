"""Redacted operational diagnostics for local deployments."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

CheckStatus = Literal["passed", "warning", "failed"]


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    generated_at: str
    version: str
    status: Literal["ready", "degraded", "unhealthy"]
    checks: tuple[DiagnosticCheck, ...]

    def as_dict(self, *, public: bool = False) -> dict[str, object]:
        if public:
            return {
                "status": self.status,
                "version": self.version,
                "checks": {
                    status: sum(check.status == status for check in self.checks)
                    for status in ("passed", "warning", "failed")
                },
            }
        return {
            "schema_version": "1.0",
            "generated_at": self.generated_at,
            "version": self.version,
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
        }


class Diagnostics:
    """Inspect state without opening a device session or exposing credentials."""

    def __init__(
        self,
        state_directory: str | Path,
        *,
        minimum_free_bytes: int = 256 * 1024 * 1024,
        artifact_sample: int = 100,
    ) -> None:
        self.root = Path(state_directory)
        self.minimum_free_bytes = minimum_free_bytes
        self.artifact_sample = artifact_sample

    def run(self) -> DiagnosticReport:
        checks = [self._state_directory(), self._disk(), self._database(), self._artifacts()]
        if any(check.status == "failed" for check in checks):
            return DiagnosticReport(
                datetime.now(UTC).isoformat(), self._version(), "unhealthy", tuple(checks)
            )
        if any(check.status == "warning" for check in checks):
            return DiagnosticReport(
                datetime.now(UTC).isoformat(), self._version(), "degraded", tuple(checks)
            )
        return DiagnosticReport(
            datetime.now(UTC).isoformat(), self._version(), "ready", tuple(checks)
        )

    @staticmethod
    def _version() -> str:
        try:
            return importlib.metadata.version("haykal-runtime")
        except importlib.metadata.PackageNotFoundError:
            return "development"

    def _state_directory(self) -> DiagnosticCheck:
        if not self.root.exists():
            return DiagnosticCheck("state_directory", "warning", "not initialized")
        if not self.root.is_dir():
            return DiagnosticCheck("state_directory", "failed", "path is not a directory")
        if not os.access(self.root, os.R_OK | os.W_OK | os.X_OK):
            return DiagnosticCheck("state_directory", "failed", "directory is not accessible")
        mode = self.root.stat().st_mode & 0o777
        if mode & 0o077:
            return DiagnosticCheck(
                "state_directory_permissions",
                "warning",
                f"mode {mode:04o}; use 0700 for private deployments",
            )
        return DiagnosticCheck("state_directory", "passed", f"mode {mode:04o}")

    def _disk(self) -> DiagnosticCheck:
        probe = self.root if self.root.exists() else self.root.parent
        try:
            free = shutil.disk_usage(probe).free
        except OSError as exc:
            return DiagnosticCheck("disk_space", "failed", type(exc).__name__)
        status: CheckStatus = "passed" if free >= self.minimum_free_bytes else "failed"
        return DiagnosticCheck("disk_space", status, f"{free} bytes free")

    def _database(self) -> DiagnosticCheck:
        database = self.root / "runtime.sqlite3"
        if not database.exists():
            return DiagnosticCheck("database", "warning", "not initialized")
        try:
            uri = f"file:{database.resolve().as_posix()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
                if result is None or result[0] != "ok":
                    return DiagnosticCheck("database", "failed", "quick_check failed")
                tables = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                )
        except (OSError, sqlite3.Error) as exc:
            return DiagnosticCheck("database", "failed", type(exc).__name__)
        return DiagnosticCheck("database", "passed", f"quick_check=ok; tables={tables}")

    def _artifacts(self) -> DiagnosticCheck:
        root = self.root / "artifacts" / "sha256"
        if not root.exists():
            return DiagnosticCheck("artifacts", "warning", "not initialized")
        files = sorted(path for path in root.glob("*/*") if path.is_file())
        failures = 0
        import hashlib

        for path in files[: self.artifact_sample]:
            expected = f"{path.parent.name}{path.name}"
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            failures += actual != expected
        if failures:
            return DiagnosticCheck("artifacts", "failed", f"{failures} integrity failures")
        sampled = min(len(files), self.artifact_sample)
        return DiagnosticCheck("artifacts", "passed", f"verified {sampled}/{len(files)}")
