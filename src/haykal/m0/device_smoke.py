"""Repeatable live-device smoke evidence for M0/M1."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from haykal.artifacts import ArtifactStore
from haykal.device.backend import Uiautomator2Backend


async def run_device_smoke(
    *, serial: str, artifact_root: Path, timeout_s: float = 15.0
) -> dict[str, object]:
    backend = Uiautomator2Backend.from_serial(serial, operation_timeout_s=timeout_s)
    store = ArtifactStore(artifact_root)
    timings: dict[str, float] = {}
    started = time.perf_counter()
    await backend.open()
    timings["open_ms"] = (time.perf_counter() - started) * 1000
    try:
        health = await backend.health()
        hierarchy_started = time.perf_counter()
        hierarchy = await backend.hierarchy()
        timings["hierarchy_ms"] = (time.perf_counter() - hierarchy_started) * 1000
        screenshot_started = time.perf_counter()
        screenshot = await backend.screenshot()
        timings["screenshot_ms"] = (time.perf_counter() - screenshot_started) * 1000
        hierarchy_artifact = store.put(hierarchy.encode())
        screenshot_artifact = store.put(screenshot)
        action_started = time.perf_counter()
        await backend.press("home")
        timings["press_home_ms"] = (time.perf_counter() - action_started) * 1000
        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "serial": serial,
            "status": "passed" if health.healthy else "failed",
            "health": {"healthy": health.healthy, "detail": health.detail},
            "timings_ms": {name: round(value, 3) for name, value in timings.items()},
            "hierarchy": {
                "bytes": len(hierarchy.encode()),
                "artifact": hierarchy_artifact.digest,
            },
            "screenshot": {
                "bytes": len(screenshot),
                "artifact": screenshot_artifact.digest,
            },
        }
    finally:
        await backend.close()
