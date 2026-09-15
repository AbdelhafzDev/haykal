"""Bounded reliability soak with real storage faults and resource evidence."""

from __future__ import annotations

import asyncio
import hashlib
import math
import resource
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections import deque
from contextlib import closing, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from haykal.artifacts import ArtifactIntegrityError, ArtifactStore
from haykal.traces import TraceStore


@dataclass(frozen=True, slots=True)
class ResourceSample:
    elapsed_s: float
    rss_bytes: int
    file_count: int
    artifact_bytes: int
    sqlite_bytes: int
    state_bytes: int
    open_descriptors: int


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
    detected_faults: int
    artifact_integrity_failures: int
    p50_ms: float
    p95_ms: float
    peak_traced_memory_bytes: int
    peak_rss_bytes: int
    state_bytes: int
    peak_file_count: int
    peak_open_descriptors: int
    state_growth_bytes_per_s: float
    rss_growth_bytes_per_s: float
    limits: dict[str, float | int]
    limits_passed: bool
    samples: tuple[ResourceSample, ...]
    thirty_minute_gate_eligible: bool
    eight_hour_gate_eligible: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage if sys.platform == "darwin" else usage * 1024)


def _open_descriptors() -> int:
    for directory in (Path("/proc/self/fd"), Path("/dev/fd")):
        try:
            return sum(1 for _ in directory.iterdir())
        except OSError:
            continue
    return 0


def _bytes(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        with suppress(OSError):
            total += path.stat().st_size
    return total


def _sample(root: Path, started: float) -> ResourceSample:
    files = [path for path in root.rglob("*") if path.is_file()]
    artifact_files = [path for path in files if "artifacts" in path.parts]
    sqlite_files = [
        path for path in files if path.name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm"))
    ]
    return ResourceSample(
        elapsed_s=round(time.monotonic() - started, 6),
        rss_bytes=_rss_bytes(),
        file_count=len(files),
        artifact_bytes=_bytes(artifact_files),
        sqlite_bytes=_bytes(sqlite_files),
        state_bytes=_bytes(files),
        open_descriptors=_open_descriptors(),
    )


def _slope(samples: list[ResourceSample], field: str) -> float:
    stable = samples[len(samples) // 2 :]
    if len(stable) < 2:
        return 0.0
    xs = [sample.elapsed_s for sample in stable]
    ys = [float(getattr(sample, field)) for sample in stable]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator


def _sqlite_interruption(database: Path, iteration: int) -> bool:
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS interrupted(value INTEGER)")
        before = int(connection.execute("SELECT COUNT(*) FROM interrupted").fetchone()[0])
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO interrupted VALUES (?)", (iteration,))
        connection.rollback()
        check = connection.execute("PRAGMA quick_check").fetchone()[0]
        after = int(connection.execute("SELECT COUNT(*) FROM interrupted").fetchone()[0])
    return check == "ok" and before == after


def _artifact_interruption(store: ArtifactStore, payload: bytes) -> bool:
    artifact = store.put(payload)
    artifact.path.write_bytes(b"injected-corruption")
    detected = False
    try:
        store.get(artifact.digest)
    except ArtifactIntegrityError:
        detected = True
    with suppress(OSError):
        artifact.path.unlink()
    return detected


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
    fault_root = root / "fault-injection"
    fault_root.mkdir(mode=0o700, exist_ok=True)
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    deadline = started + duration_s
    latencies: deque[float] = deque(maxlen=10_000)
    samples: list[ResourceSample] = []
    counters = {
        "operations": 0,
        "failures": 0,
        "interruptions": 0,
        "detected": 0,
        "integrity": 0,
    }
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
                if iteration % chaos_every == 0:
                    fault_ok = await asyncio.to_thread(
                        _sqlite_interruption,
                        fault_root / f"worker-{worker_id}.sqlite3",
                        iteration,
                    )
                    if iteration % (chaos_every * 2) == 0:
                        fault_ok = fault_ok and await asyncio.to_thread(
                            _artifact_interruption,
                            artifacts,
                            f"fault-{worker_id}-{iteration}".encode(),
                        )
                    async with lock:
                        counters["interruptions"] += 1
                        counters["detected"] += int(fault_ok)
                        counters["failures"] += int(not fault_ok)
                stored = await asyncio.to_thread(artifacts.put, payload)
                event = await asyncio.to_thread(
                    traces.append,
                    trace_id=f"soak-{worker_id}",
                    run_id=f"soak-{worker_id}",
                    event_type="observation.created",
                    payload={"iteration": iteration, "artifact": stored.digest},
                    artifacts=[stored.digest],
                )
                raw = await asyncio.to_thread(artifacts.get, digest)
                if event.sequence <= 0 or raw != payload:
                    async with lock:
                        counters["integrity"] += 1
                async with lock:
                    counters["operations"] += 1
                    latencies.append((time.monotonic() - tick) * 1000)
            except Exception:
                async with lock:
                    counters["failures"] += 1

    async def monitor() -> None:
        interval = min(5.0, max(0.02, duration_s / 20))
        while time.monotonic() < deadline:
            samples.append(await asyncio.to_thread(_sample, root, started))
            await asyncio.sleep(interval)
        samples.append(await asyncio.to_thread(_sample, root, started))

    async def retain() -> None:
        while time.monotonic() < deadline:
            await asyncio.sleep(min(5.0, max(0.02, duration_s / 10)))
            cutoff = datetime.now(UTC) - timedelta(seconds=10)
            await asyncio.to_thread(traces.prune_before, cutoff, dry_run=False)

    state_bytes = 0
    try:
        await asyncio.gather(
            *(worker(index) for index in range(workers)),
            monitor(),
            retain(),
        )
        _current, peak = tracemalloc.get_traced_memory()
        final_sample = await asyncio.to_thread(_sample, root, started)
        if not samples or samples[-1] != final_sample:
            samples.append(final_sample)
        state_bytes = final_sample.state_bytes
    finally:
        tracemalloc.stop()
        if state_directory is None:
            temporary.cleanup()
    sorted_latencies = sorted(latencies)
    p50 = statistics.median(sorted_latencies) if sorted_latencies else 0.0
    p95 = (
        sorted_latencies[max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)]
        if sorted_latencies
        else 0.0
    )
    elapsed = time.monotonic() - started
    state_slope = _slope(samples, "state_bytes")
    rss_slope = _slope(samples, "rss_bytes")
    limits: dict[str, float | int] = {
        "max_rss_bytes": 512 * 1024 * 1024,
        "max_state_bytes": 1024 * 1024 * 1024,
        "max_open_descriptors": 256,
        "max_p95_ms": 1000.0,
        "max_state_growth_bytes_per_s": 256 * 1024,
        "max_rss_growth_bytes_per_s": 64 * 1024,
    }
    peak_rss = max((sample.rss_bytes for sample in samples), default=0)
    peak_files = max((sample.file_count for sample in samples), default=0)
    peak_fds = max((sample.open_descriptors for sample in samples), default=0)
    passed = counters["failures"] == 0 and counters["integrity"] == 0
    limits_passed = (
        peak_rss <= limits["max_rss_bytes"]
        and state_bytes <= limits["max_state_bytes"]
        and peak_fds <= limits["max_open_descriptors"]
        and p95 <= limits["max_p95_ms"]
        and state_slope <= limits["max_state_growth_bytes_per_s"]
        and rss_slope <= limits["max_rss_growth_bytes_per_s"]
    )
    return ReliabilityReport(
        schema_version="2.0",
        profile="storage-real-fault-soak",
        started_at=started_at,
        requested_duration_s=duration_s,
        elapsed_s=round(elapsed, 6),
        workers=workers,
        operations=counters["operations"],
        unexpected_failures=counters["failures"],
        injected_interruptions=counters["interruptions"],
        detected_faults=counters["detected"],
        artifact_integrity_failures=counters["integrity"],
        p50_ms=round(p50, 6),
        p95_ms=round(p95, 6),
        peak_traced_memory_bytes=peak,
        peak_rss_bytes=peak_rss,
        state_bytes=state_bytes,
        peak_file_count=peak_files,
        peak_open_descriptors=peak_fds,
        state_growth_bytes_per_s=round(state_slope, 6),
        rss_growth_bytes_per_s=round(rss_slope, 6),
        limits=limits,
        limits_passed=limits_passed,
        samples=tuple(samples),
        thirty_minute_gate_eligible=(
            duration_s >= 1800 and elapsed >= 1800 and passed and limits_passed
        ),
        eight_hour_gate_eligible=(
            duration_s >= 28_800 and elapsed >= 28_800 and passed and limits_passed
        ),
    )


def report_digest(report: ReliabilityReport) -> str:
    import json

    encoded = json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
