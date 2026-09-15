from __future__ import annotations

import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

from haykal.artifacts import ArtifactStore
from haykal.device import DeviceLeaseStore, DeviceStateJournal
from haykal.hardening import (
    AndroidDeviceDiagnostics,
    DiagnosticCheck,
    Diagnostics,
)


class MutableDeviceProbe:
    def __init__(self) -> None:
        self.authorized = True
        self.helper = True
        self.lease = True
        self.recovery = True

    def run(self) -> tuple[DiagnosticCheck, ...]:
        return (
            DiagnosticCheck("adb", "passed", "server responded"),
            DiagnosticCheck(
                "authorized_target",
                "passed" if self.authorized else "failed",
                "fixture",
            ),
            DiagnosticCheck("device_lease", "passed" if self.lease else "failed", "fixture"),
            DiagnosticCheck(
                "uiautomator2_helper",
                "passed" if self.helper else "failed",
                "fixture",
            ),
            DiagnosticCheck(
                "pending_recovery",
                "passed" if self.recovery else "failed",
                "fixture",
            ),
        )


def _initialized_state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    with closing(sqlite3.connect(state / "runtime.sqlite3")) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.commit()
    ArtifactStore(state / "artifacts").put(b"evidence")
    return state


def test_diagnostics_checks_private_state_database_and_artifacts(tmp_path: Path) -> None:
    state = _initialized_state(tmp_path)

    report = Diagnostics(state, minimum_free_bytes=1, require_device=False).run()

    assert report.status == "ready"
    assert report.as_dict(public=True)["checks"] == {
        "passed": 4,
        "warning": 0,
        "failed": 0,
    }
    assert "generated_at" not in report.as_dict(public=True)


def test_diagnostics_reports_uninitialized_state_without_creating_it(tmp_path: Path) -> None:
    state = tmp_path / "missing"
    report = Diagnostics(state, minimum_free_bytes=1, require_device=False).run()

    assert report.status == "degraded"
    assert not state.exists()


def test_readiness_requires_device_and_tracks_failure_transitions(tmp_path: Path) -> None:
    state = _initialized_state(tmp_path)
    assert Diagnostics(state, minimum_free_bytes=1).run().status == "unhealthy"
    probe = MutableDeviceProbe()
    diagnostics = Diagnostics(state, minimum_free_bytes=1, device_probe=probe)
    assert diagnostics.run().status == "ready"

    for attribute in ("authorized", "helper", "lease", "recovery"):
        setattr(probe, attribute, False)
        assert diagnostics.run().status == "unhealthy"
        setattr(probe, attribute, True)
        assert diagnostics.run().status == "ready"

    assert (
        Diagnostics(
            state,
            minimum_free_bytes=2**63,
            device_probe=probe,
        )
        .run()
        .status
        == "unhealthy"
    )


def test_android_probe_reads_adb_lease_helper_and_pending_recovery(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    leases = DeviceLeaseStore(database)
    journal = DeviceStateJournal(database)
    lease = leases.acquire("emulator-5554", "worker", ttl_s=10, now=100)

    def adb(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            "List of devices attached\nemulator-5554\tdevice\n",
            "",
        )

    probe = AndroidDeviceDiagnostics(
        "emulator-5554",
        database,
        adb_path="/fixture/adb",
        adb_runner=adb,
        helper_probe=lambda _serial: {"displayRotation": 0},
        now=lambda: 105,
    )
    assert all(check.status == "passed" for check in probe.run())

    journal.record_baseline(lease, "default_input_method", "original/.Ime")
    checks = {check.name: check for check in probe.run()}
    assert checks["pending_recovery"].status == "failed"
