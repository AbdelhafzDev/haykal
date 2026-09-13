"""Bounded storage load/soak/chaos evidence harness."""

from __future__ import annotations

import asyncio
import hashlib
import math
import statistics
import tempfile
import time
import tracemalloc
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from haykal.artifacts import ArtifactStore
from haykal.traces import TraceStore


@dataclass(frozen=True, slots=True)
class ReliabilityReport:
    schema_version: str
    profile: str
    started_at: str
    requested_duration_s: float
    elapsed_s: float
    workers: int
    operations: int
    unexpected_failures: int
    injected_interruptions: int
    artifact_integrity_failures: int
    p50_ms: float
    p95_ms: float
    peak_traced_memory_bytes: int
    state_bytes: int
    eight_hour_gate_eligible: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


async def run_storage_reliability(
    *,
    duration_s: float,
    workers: int = 4,
    chaos_every: int = 37,
    state_directory: str | Path | None = None,
) -> ReliabilityReport:
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if chaos_every <= 0:
        raise ValueError("chaos_every must be positive")
    temporary = tempfile.TemporaryDirectory(prefix="haykal-reliability-")
    root = Path(state_directory) if state_directory is not None else Path(temporary.name)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifacts = ArtifactStore(root / "artifacts")
    traces = TraceStore(root / "runtime.sqlite3")
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    deadline = started + duration_s
    latencies: deque[float] = deque(maxlen=10_000)
    counters = {"operations": 0, "failures": 0, "interruptions": 0, "integrity": 0}
    lock = asyncio.Lock()
    tracemalloc.start()

    async def worker(worker_id: int) -> None:
        iteration = 0
        payload = f"haykal-soak-worker-{worker_id}".encode()
        digest = ArtifactStore.digest(payload)
        while time.monotonic() < deadline:
            iteration += 1
            tick = time.monotonic()
            try:
                stored = await asyncio.to_thread(artifacts.put, payload)
                if iteration % chaos_every == 0:
                    async with lock:
                        counters["interruptions"] += 1
                    continue
                event = await asyncio.to_thread(
                    traces.append,
                    trace_id=f"soak-{worker_id}",
                    run_id=f"soak-{worker_id}",
                    event_type="observation.created",
                    payload={"iteration": iteration, "artifact": stored.digest},
                    artifacts=[stored.digest],
                )
                if event.sequence <= 0 or not artifacts.contains(digest):
                    async with lock:
                        counters["integrity"] += 1
                async with lock:
                    counters["operations"] += 1
                    latencies.append((time.monotonic() - tick) * 1000)
            except Exception:
                async with lock:
                    counters["failures"] += 1

    state_bytes = 0
    try:
        await asyncio.gather(*(worker(index) for index in range(workers)))
        _current, peak = tracemalloc.get_traced_memory()
        state_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    finally:
        tracemalloc.stop()
        if state_directory is None:
            temporary.cleanup()
    samples = sorted(latencies)
    p50 = statistics.median(samples) if samples else 0.0
    p95 = samples[max(0, math.ceil(len(samples) * 0.95) - 1)] if samples else 0.0
    elapsed = time.monotonic() - started
    passed = counters["failures"] == 0 and counters["integrity"] == 0
    return ReliabilityReport(
        schema_version="1.0",
        profile="storage-load-soak-chaos",
        started_at=started_at,
        requested_duration_s=duration_s,
        elapsed_s=round(elapsed, 6),
        workers=workers,
        operations=counters["operations"],
        unexpected_failures=counters["failures"],
        injected_interruptions=counters["interruptions"],
        artifact_integrity_failures=counters["integrity"],
        p50_ms=round(p50, 6),
        p95_ms=round(p95, 6),
        peak_traced_memory_bytes=peak,
        state_bytes=state_bytes,
        eight_hour_gate_eligible=duration_s >= 28_800 and elapsed >= 28_800 and passed,
    )


def report_digest(report: ReliabilityReport) -> str:
    import json

    encoded = json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
