"""Externally supervised fault injection for release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from haykal.artifacts import ArtifactIntegrityError, ArtifactStore
from haykal.device import DeviceLeaseStore, DeviceStateJournal
from haykal.device.single_shot import AtMostOnceDispatcher
from haykal.traces import TraceStore


@dataclass(frozen=True, slots=True)
class FaultObservation:
    fault: str
    injected_at: str
    observed_at: str
    passed: bool
    observation: str
    recovery_ms: float


@dataclass(frozen=True, slots=True)
class FaultMatrixReport:
    schema_version: str
    started_at: str
    completed_at: str
    supervisor_pid: int
    observations: tuple[FaultObservation, ...]

    @property
    def passed(self) -> bool:
        return bool(self.observations) and all(item.passed for item in self.observations)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


class _EffectTransport:
    def __init__(self, effects: Path) -> None:
        self.effects = effects

    def call_once(self, method: str, params: dict[str, object]) -> dict[str, object]:
        del method, params
        with self.effects.open("ab") as stream:
            stream.write(b"effect\n")
            stream.flush()
            os.fsync(stream.fileno())
        return {"accepted": True}


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _request_digest(method: str, params: dict[str, object]) -> str:
    encoded = json.dumps(
        {"method": method, "params": params},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_marker(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _block() -> None:
    while True:
        time.sleep(60)


def _dispatch_worker(root: Path, checkpoint: str, marker: Path) -> None:
    database = root / f"dispatch-{checkpoint}.sqlite3"
    effects = root / f"effects-{checkpoint}.log"
    method = "tap"
    params: dict[str, object] = {"x": 10, "y": 20}
    dispatcher = AtMostOnceDispatcher(database, _EffectTransport(effects))
    if checkpoint == "prepared":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "INSERT INTO irreversible_dispatch VALUES (?, ?, 'prepared', NULL)",
                ("purchase", _request_digest(method, params)),
            )
            connection.commit()
        _write_marker(marker, checkpoint)
        _block()

    class CheckpointTransport(_EffectTransport):
        def call_once(self, method: str, params: dict[str, object]) -> dict[str, object]:
            if checkpoint == "dispatched":
                _write_marker(marker, checkpoint)
                _block()
            receipt = super().call_once(method, params)
            if checkpoint == "pre_commit":
                _write_marker(marker, checkpoint)
                _block()
            return receipt

    dispatcher = AtMostOnceDispatcher(database, CheckpointTransport(effects))
    dispatcher.dispatch(action_id="purchase", method=method, params=params)
    _write_marker(marker, checkpoint)
    _block()


def _sqlite_worker(root: Path, marker: Path) -> None:
    database = root / "interrupted.sqlite3"
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS durable(value TEXT)")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO durable VALUES ('must_rollback')")
        _write_marker(marker, "transaction-open")
        _block()


def _lease_worker(root: Path, marker: Path, *, setting: bool) -> None:
    database = root / ("setting.sqlite3" if setting else "lease.sqlite3")
    lease = DeviceLeaseStore(database).acquire("vm-1", "crashed-worker", ttl_s=0.2)
    if setting:
        DeviceStateJournal(database).record_baseline(lease, "default_input_method", "original/.Ime")
    _write_marker(marker, json.dumps({"generation": lease.generation}))
    _block()


def _disk_worker(root: Path, marker: Path) -> None:
    def file_limit(_signum: int, _frame: object) -> None:
        raise OSError("injected file-size limit")

    signal.signal(signal.SIGXFSZ, file_limit)
    original = resource.getrlimit(resource.RLIMIT_FSIZE)
    injected_at = _stamp()
    artifact_blocked = False
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (4096, original[1]))
        ArtifactStore(root / "disk-artifacts").put(b"x" * (1024 * 1024))
    except Exception:
        artifact_blocked = True
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, original)
        ArtifactStore(root / "disk-artifacts")

    trace_blocked = False
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (4096, original[1]))
        TraceStore(root / "disk-trace.sqlite3").append(
            trace_id="disk",
            run_id="disk",
            event_type="observation.created",
            payload={"data": "x" * 64_000},
        )
    except Exception:
        trace_blocked = True
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, original)
    _write_marker(
        marker,
        json.dumps(
            {
                "artifact_blocked": artifact_blocked,
                "trace_blocked": trace_blocked,
                "injected_at": injected_at,
            }
        ),
    )


def _worker(args: argparse.Namespace) -> int:
    root = Path(args.root)
    marker = Path(args.marker)
    scenario = str(args.worker)
    if scenario.startswith("dispatch:"):
        _dispatch_worker(root, scenario.partition(":")[2], marker)
    elif scenario == "sqlite":
        _sqlite_worker(root, marker)
    elif scenario == "lease":
        _lease_worker(root, marker, setting=False)
    elif scenario == "setting":
        _lease_worker(root, marker, setting=True)
    elif scenario == "disk":
        _disk_worker(root, marker)
    else:
        raise ValueError(f"unknown worker scenario {scenario!r}")
    return 0


def _supervise(root: Path, scenario: str, *, kill: bool = True) -> tuple[str, str, float]:
    marker = root / f"marker-{scenario.replace(':', '-')}.txt"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "haykal.hardening.faults",
            "--worker",
            scenario,
            "--root",
            str(root),
            "--marker",
            str(marker),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not marker.exists():
        process.kill()
        process.wait(timeout=5)
        raise TimeoutError(f"fault worker {scenario!r} did not reach its checkpoint")
    injected_at = _stamp()
    injected = time.monotonic()
    if kill and process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    return (
        marker.read_text(encoding="utf-8"),
        injected_at,
        (time.monotonic() - injected) * 1000,
    )


def _dispatch_fault(root: Path, checkpoint: str) -> FaultObservation:
    _, injected_at, recovery_ms = _supervise(root, f"dispatch:{checkpoint}")
    database = root / f"dispatch-{checkpoint}.sqlite3"
    effects = root / f"effects-{checkpoint}.log"
    outcome = AtMostOnceDispatcher(database, _EffectTransport(effects)).dispatch(
        action_id="purchase", method="tap", params={"x": 10, "y": 20}
    )
    count = effects.read_text(encoding="utf-8").count("effect") if effects.exists() else 0
    passed = count <= 1 and outcome.repeated_request
    return FaultObservation(
        f"runtime_kill_{checkpoint}",
        injected_at,
        _stamp(),
        passed,
        f"effects={count}; reconciled={outcome.status}",
        round(recovery_ms, 3),
    )


def _sqlite_fault(root: Path) -> FaultObservation:
    _, injected_at, recovery_ms = _supervise(root, "sqlite")
    database = root / "interrupted.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        check = connection.execute("PRAGMA quick_check").fetchone()[0]
        rows = int(connection.execute("SELECT COUNT(*) FROM durable").fetchone()[0])
    return FaultObservation(
        "sqlite_interruption",
        injected_at,
        _stamp(),
        check == "ok" and rows == 0,
        f"quick_check={check}; uncommitted_rows={rows}",
        round(recovery_ms, 3),
    )


def _artifact_fault(root: Path) -> FaultObservation:
    injected_at = _stamp()
    started = time.monotonic()
    store = ArtifactStore(root / "corrupt-artifacts")
    artifact = store.put(b"integrity-evidence")
    artifact.path.write_bytes(b"corrupt")
    detected = False
    try:
        store.get(artifact.digest)
    except ArtifactIntegrityError:
        detected = True
    return FaultObservation(
        "artifact_corruption",
        injected_at,
        _stamp(),
        detected,
        "ArtifactStore.get rejected modified content" if detected else "corruption missed",
        round((time.monotonic() - started) * 1000, 3),
    )


def _lease_fault(root: Path, *, setting: bool) -> FaultObservation:
    name = "setting" if setting else "lease"
    _, injected_at, recovery_ms = _supervise(root, name)
    database = root / ("setting.sqlite3" if setting else "lease.sqlite3")
    time.sleep(0.25)
    leases = DeviceLeaseStore(database)
    replacement = leases.acquire("vm-1", "replacement", ttl_s=5)
    recovered = 0
    if setting:
        recovered = DeviceStateJournal(database).recover_prior(replacement, lambda _item: None)
    generation = replacement.generation
    leases.release(replacement)
    return FaultObservation(
        "ime_interruption" if setting else "lease_owner_death",
        injected_at,
        _stamp(),
        generation == 2 and (not setting or recovered == 1),
        f"replacement_generation={generation}; recovered_settings={recovered}; released=true",
        round(recovery_ms + 250, 3),
    )


def _disk_fault(root: Path) -> FaultObservation:
    marker, _supervisor_at, recovery_ms = _supervise(root, "disk", kill=False)
    result = json.loads(marker)
    injected_at = str(result["injected_at"])
    accepted = any(
        path
        for path in (root / "disk-artifacts").glob("sha256/*/*")
        if not path.name.startswith(".")
    )
    database = root / "disk-trace.sqlite3"
    trace_rows = 0
    quick_check = "ok"
    if database.exists():
        with closing(sqlite3.connect(database)) as connection:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trace_event'"
            ).fetchone()
            if table is not None:
                trace_rows = int(
                    connection.execute("SELECT COUNT(*) FROM trace_event").fetchone()[0]
                )
    passed = (
        bool(result["artifact_blocked"])
        and bool(result["trace_blocked"])
        and not accepted
        and quick_check == "ok"
        and trace_rows == 0
    )
    return FaultObservation(
        "disk_full",
        injected_at,
        _stamp(),
        passed,
        f"artifact_published={accepted}; trace_rows={trace_rows}; quick_check={quick_check}",
        round(recovery_ms, 3),
    )


def _run(command: list[str], *, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _device_faults(serial: str, adb_path: str) -> list[FaultObservation]:
    from uiautomator2 import connect  # type: ignore[import-untyped]

    results: list[FaultObservation] = []
    injected_at = _stamp()
    started = time.monotonic()
    for package in ("com.github.uiautomator", "com.github.uiautomator.test"):
        _run([adb_path, "-s", serial, "shell", "am", "force-stop", package])
    try:
        client = connect(serial)
        client.reset_uiautomator()
        healthy = bool(client.info)
    except Exception:
        healthy = False
    results.append(
        FaultObservation(
            "uiautomator2_agent_death",
            injected_at,
            _stamp(),
            healthy,
            "helper restarted and responded" if healthy else "helper did not recover",
            round((time.monotonic() - started) * 1000, 3),
        )
    )

    injected_at = _stamp()
    started = time.monotonic()
    reconnect = _run([adb_path, "-s", serial, "reconnect"])
    wait = _run([adb_path, "-s", serial, "wait-for-device"], timeout=30)
    state = _run([adb_path, "-s", serial, "get-state"])
    connected = (
        reconnect.returncode == 0 and wait.returncode == 0 and state.stdout.strip() == "device"
    )
    results.append(
        FaultObservation(
            "adb_disconnect_reconnect",
            injected_at,
            _stamp(),
            connected,
            f"state={state.stdout.strip() or 'unavailable'}",
            round((time.monotonic() - started) * 1000, 3),
        )
    )

    injected_at = _stamp()
    started = time.monotonic()
    original = _run(
        [adb_path, "-s", serial, "shell", "settings", "get", "secure", "default_input_method"]
    ).stdout.strip()
    ime_enabled = False
    try:
        connect(serial).set_fastinput_ime(True)
        ime_enabled = True
    except Exception:
        pass
    listed = _run([adb_path, "-s", serial, "shell", "ime", "list", "-s"]).stdout.splitlines()
    helper = next((item.strip() for item in listed if "uiautomator" in item.casefold()), None)
    restored = False
    try:
        if helper and not ime_enabled:
            _run([adb_path, "-s", serial, "shell", "ime", "set", helper])
    finally:
        if original:
            _run([adb_path, "-s", serial, "shell", "ime", "set", original])
            current = _run(
                [
                    adb_path,
                    "-s",
                    serial,
                    "shell",
                    "settings",
                    "get",
                    "secure",
                    "default_input_method",
                ]
            ).stdout.strip()
            restored = current == original
    results.append(
        FaultObservation(
            "device_ime_restore",
            injected_at,
            _stamp(),
            bool(helper) and restored,
            "prior IME restored" if restored else "IME restoration failed",
            round((time.monotonic() - started) * 1000, 3),
        )
    )
    return results


def run_fault_matrix(
    state_directory: str | Path,
    *,
    serial: str | None = None,
    adb_path: str | None = None,
) -> FaultMatrixReport:
    if bool(serial) != bool(adb_path):
        raise ValueError("serial and adb_path must be provided together")
    root = Path(state_directory)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("fault-matrix state directory must be empty")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    started_at = _stamp()
    observations = [
        *(
            _dispatch_fault(root, checkpoint)
            for checkpoint in (
                "prepared",
                "dispatched",
                "pre_commit",
                "post_commit",
            )
        ),
        _sqlite_fault(root),
        _artifact_fault(root),
        _lease_fault(root, setting=False),
        _lease_fault(root, setting=True),
        _disk_fault(root),
    ]
    if serial and adb_path:
        observations.extend(_device_faults(serial, adb_path))
    return FaultMatrixReport(
        "1.0",
        started_at,
        _stamp(),
        os.getpid(),
        tuple(observations),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--root", required=True)
    parser.add_argument("--marker")
    parser.add_argument("--serial")
    parser.add_argument("--adb-path")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.worker:
        if not args.marker:
            parser.error("--marker is required for a worker")
        return _worker(args)
    report = run_fault_matrix(args.root, serial=args.serial, adb_path=args.adb_path)
    encoded = json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
