"""Machine-readable host and dependency checks for Milestone 0."""

from __future__ import annotations

import importlib.metadata
import inspect
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    detail: str


def _find_android_tool(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    roots = [
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        str(Path.home() / "Library" / "Android" / "sdk"),
    ]
    folders = {
        "adb": "platform-tools",
        "emulator": "emulator",
        "sdkmanager": "cmdline-tools/latest/bin",
    }
    for root in (Path(value) for value in roots if value):
        candidate = root / folders.get(name, "") / name
        if candidate.is_file():
            return str(candidate)
    return None


def _command(name: str, *, required: bool = True) -> Check:
    if name in {"adb", "emulator", "sdkmanager"}:
        path = _find_android_tool(name)
    else:
        path = shutil.which(name)
    if path:
        return Check(name, "passed", path)
    return Check(name, "blocked" if required else "skipped", "not found on PATH")


def _adb_devices() -> Check:
    adb = _find_android_tool("adb")
    if adb is None:
        return Check("android_device", "blocked", "adb is not installed")
    result = subprocess.run(
        [adb, "devices", "-l"],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    devices = [
        line
        for line in result.stdout.splitlines()[1:]
        if len(line.split()) >= 2 and line.split()[1] == "device"
    ]
    if not devices:
        return Check("android_device", "blocked", "no authorized device or VM attached")
    return Check("android_device", "passed", ", ".join(devices))


def _uiautomator2_retry_audit() -> Check:
    try:
        from uiautomator2 import core  # type: ignore[import-untyped]
    except ImportError:
        return Check("uiautomator2_retry_audit", "blocked", "uiautomator2 is not installed")
    source = inspect.getsource(core.BasicUiautomatorServer.jsonrpc_call)
    indicators = ("stop_uiautomator", "start_uiautomator", "_jsonrpc_call")
    if all(indicator in source for indicator in indicators) and source.count("_jsonrpc_call") >= 2:
        return Check(
            "uiautomator2_retry_audit",
            "risk_confirmed",
            "jsonrpc_call restarts UiAutomator and invokes _jsonrpc_call again; "
            "irreversible actions must bypass this wrapper",
        )
    return Check(
        "uiautomator2_retry_audit",
        "review_required",
        "known retry signature not found; inspect the pinned dependency before dispatch work",
    )


def build_report() -> dict[str, object]:
    checks = [
        Check("python", "passed", sys.version.split()[0]),
        _command("java"),
        _command("adb"),
        _command("emulator"),
        _command("sdkmanager"),
        _command("docker", required=False),
        _adb_devices(),
        Check("uiautomator2", "passed", importlib.metadata.version("uiautomator2")),
        _uiautomator2_retry_audit(),
    ]
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": "M0",
        "checks": [asdict(check) for check in checks],
        "summary": {
            status: sum(check.status == status for check in checks)
            for status in ("passed", "blocked", "skipped", "risk_confirmed", "review_required")
        },
    }
