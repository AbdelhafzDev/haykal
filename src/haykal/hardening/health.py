"""Redacted operational diagnostics for local deployments."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

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


class DeviceDiagnosticProbe(Protocol):
    def run(self) -> tuple[DiagnosticCheck, ...]: ...


AdbRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
HelperProbe = Callable[[str], object]


class AndroidDeviceDiagnostics:
    """Read-only readiness checks for one configured Android target."""

    def __init__(
        self,
        serial: str,
        database: str | Path,
        *,
        adb_path: str | None = None,
        adb_runner: AdbRunner | None = None,
        helper_probe: HelperProbe | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.serial = serial
        self.database = Path(database)
        self.adb_path = adb_path or shutil.which("adb")
        self._adb_runner = adb_runner or self._run_adb
        self._helper_probe = helper_probe or self._probe_helper
        self._now = now

    def run(self) -> tuple[DiagnosticCheck, ...]:
        adb, authorized = self._adb()
        checks = [adb, authorized, self._lease(), self._pending_recovery()]
        if authorized.status == "passed":
            checks.append(self._helper())
        else:
            checks.append(DiagnosticCheck("uiautomator2_helper", "failed", "target is unavailable"))
        return tuple(checks)

    def _adb(self) -> tuple[DiagnosticCheck, DiagnosticCheck]:
        if not self.adb_path:
            failed = DiagnosticCheck("adb", "failed", "adb executable is unavailable")
            return failed, DiagnosticCheck(
                "authorized_target", "failed", "configured target cannot be inspected"
            )
        try:
            result = self._adb_runner([self.adb_path, "devices"])
        except (OSError, subprocess.SubprocessError) as exc:
            failed = DiagnosticCheck("adb", "failed", type(exc).__name__)
            return failed, DiagnosticCheck(
                "authorized_target", "failed", "configured target cannot be inspected"
            )
        if result.returncode != 0:
            failed = DiagnosticCheck("adb", "failed", "adb devices failed")
            return failed, DiagnosticCheck(
                "authorized_target", "failed", "configured target cannot be inspected"
            )
        states = {}
        for line in result.stdout.splitlines()[1:]:
            columns = line.split()
            if len(columns) >= 2:
                states[columns[0]] = columns[1]
        state = states.get(self.serial)
        authorized = state == "device"
        detail = "authorized and connected" if authorized else f"state={state or 'absent'}"
        return (
            DiagnosticCheck("adb", "passed", "server responded"),
            DiagnosticCheck("authorized_target", "passed" if authorized else "failed", detail),
        )

    def _lease(self) -> DiagnosticCheck:
        if not self.database.exists():
            return DiagnosticCheck("device_lease", "passed", "available")
        try:
            uri = f"file:{self.database.resolve().as_posix()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_lease'"
                ).fetchone()
                if table is None:
                    return DiagnosticCheck("device_lease", "passed", "available")
                row = connection.execute(
                    "SELECT generation, expires_at FROM device_lease WHERE device_id = ?",
                    (self.serial,),
                ).fetchone()
        except sqlite3.Error as exc:
            return DiagnosticCheck("device_lease", "failed", type(exc).__name__)
        if row is None:
            return DiagnosticCheck("device_lease", "passed", "available")
        generation, expires_at = int(row[0]), float(row[1])
        if expires_at <= self._now():
            return DiagnosticCheck("device_lease", "failed", "lease expired")
        return DiagnosticCheck("device_lease", "passed", f"active generation {generation}")

    def _pending_recovery(self) -> DiagnosticCheck:
        if not self.database.exists():
            return DiagnosticCheck("pending_recovery", "passed", "none")
        try:
            uri = f"file:{self.database.resolve().as_posix()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_state_journal'"
                ).fetchone()
                if table is None:
                    return DiagnosticCheck("pending_recovery", "passed", "none")
                count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM device_state_journal "
                        "WHERE device_id = ? AND restored_at IS NULL",
                        (self.serial,),
                    ).fetchone()[0]
                )
        except sqlite3.Error as exc:
            return DiagnosticCheck("pending_recovery", "failed", type(exc).__name__)
        return DiagnosticCheck(
            "pending_recovery",
            "passed" if count == 0 else "failed",
            "none" if count == 0 else f"{count} setting(s) pending",
        )

    def _helper(self) -> DiagnosticCheck:
        try:
            info = self._helper_probe(self.serial)
        except Exception as exc:
            return DiagnosticCheck("uiautomator2_helper", "failed", type(exc).__name__)
        return DiagnosticCheck(
            "uiautomator2_helper",
            "passed" if bool(info) else "failed",
            "responsive" if bool(info) else "empty response",
        )

    @staticmethod
    def _run_adb(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

    @staticmethod
    def _probe_helper(serial: str) -> object:
        from uiautomator2 import connect  # type: ignore[import-untyped]

        return connect(serial).info


class Diagnostics:
    """Inspect state without opening a device session or exposing credentials."""

    def __init__(
        self,
        state_directory: str | Path,
        *,
        minimum_free_bytes: int = 256 * 1024 * 1024,
        artifact_sample: int = 100,
        device_probe: DeviceDiagnosticProbe | None = None,
        require_device: bool = True,
    ) -> None:
        self.root = Path(state_directory)
        self.minimum_free_bytes = minimum_free_bytes
        self.artifact_sample = artifact_sample
        self.device_probe = device_probe
        self.require_device = require_device

    def run(self) -> DiagnosticReport:
        checks = [self._state_directory(), self._disk(), self._database(), self._artifacts()]
        if self.device_probe is not None:
            try:
                checks.extend(self.device_probe.run())
            except Exception as exc:
                checks.append(DiagnosticCheck("device", "failed", type(exc).__name__))
        elif self.require_device:
            checks.append(DiagnosticCheck("device", "failed", "no configured device probe"))
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
