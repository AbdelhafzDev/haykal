"""Fair, pinned two-track comparative benchmark orchestration."""

from __future__ import annotations

import asyncio
import csv
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BenchmarkTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    app: str
    task: str
    stresses: list[str]
    success_check: dict[str, object]


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["haykal", "agent-device", "maestro-mcp", "artemis"]
    track: Literal["step-caller", "compiled-skill"]
    version: str
    command: list[str] = Field(min_length=1)
    options: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def pinned(self) -> SystemConfig:
        if self.version.strip().lower() in {"", "latest", "main", "master", "head"}:
            raise ValueError("benchmark systems require an exact version or digest")
        return self


class BenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    runs: int = Field(default=30, gt=0)
    tasks: list[BenchmarkTask] = Field(min_length=1)
    systems: list[SystemConfig] = Field(min_length=2)

    @model_validator(mode="after")
    def required_adapters(self) -> BenchmarkManifest:
        names = {system.name for system in self.systems}
        missing = {"haykal", "agent-device"} - names
        if missing:
            raise ValueError(f"required systems missing: {', '.join(sorted(missing))}")
        return self


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    system: str
    track: str
    task_id: int
    run: int
    success: bool
    unsafe_actions: int
    wall_seconds: float
    model_calls: int
    input_tokens: int
    output_tokens: int
    model_screens: int
    steps: int
    failure_category: str | None


class BenchmarkAdapter(Protocol):
    async def run(self, task: BenchmarkTask, run: int) -> BenchmarkResult: ...


class CommandAdapter:
    """Neutral JSON-over-stdio boundary used by every compared system."""

    def __init__(self, config: SystemConfig, *, timeout_s: float = 300.0) -> None:
        self.config = config
        self.timeout_s = timeout_s

    async def run(self, task: BenchmarkTask, run: int) -> BenchmarkResult:
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *self.config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        request = json.dumps(
            {"task": task.model_dump(mode="json"), "run": run, "options": self.config.options},
            ensure_ascii=False,
        ).encode()
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(request), timeout=self.timeout_s
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return self._failure(task, run, started, "timeout")
        if process.returncode != 0:
            return self._failure(task, run, started, "crash")
        try:
            payload = json.loads(stdout)
            return BenchmarkResult(
                system=self.config.name,
                track=self.config.track,
                task_id=task.id,
                run=run,
                success=bool(payload["success"]),
                unsafe_actions=int(payload.get("unsafe_actions", 0)),
                wall_seconds=round(time.monotonic() - started, 6),
                model_calls=int(payload.get("model_calls", 0)),
                input_tokens=int(payload.get("input_tokens", 0)),
                output_tokens=int(payload.get("output_tokens", 0)),
                model_screens=int(payload.get("model_screens", 0)),
                steps=int(payload.get("steps", 0)),
                failure_category=payload.get("failure_category"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._failure(task, run, started, "invalid_result")

    def _failure(
        self, task: BenchmarkTask, run: int, started: float, category: str
    ) -> BenchmarkResult:
        return BenchmarkResult(
            self.config.name,
            self.config.track,
            task.id,
            run,
            False,
            0,
            round(time.monotonic() - started, 6),
            0,
            0,
            0,
            0,
            0,
            category,
        )


class HaykalAdapter(CommandAdapter):
    pass


class AgentDeviceAdapter(CommandAdapter):
    pass


def wilson(successes: int, total: int, *, z: float = 1.959964) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return (round(max(0, center - margin), 6), round(min(1, center + margin), 6))


async def run_benchmark(manifest: BenchmarkManifest, output: str | Path) -> list[BenchmarkResult]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    adapter_types = {
        "haykal": HaykalAdapter,
        "agent-device": AgentDeviceAdapter,
    }
    adapters: list[CommandAdapter] = [
        adapter_types.get(config.name, CommandAdapter)(config) for config in manifest.systems
    ]
    results: list[BenchmarkResult] = []
    for adapter in adapters:
        for task in manifest.tasks:
            for run in range(1, manifest.runs + 1):
                results.append(await adapter.run(task, run))
    _write_report(destination, manifest, results)
    return results


def load_manifest(path: str | Path) -> BenchmarkManifest:
    return BenchmarkManifest.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def _write_report(
    destination: Path,
    manifest: BenchmarkManifest,
    results: list[BenchmarkResult],
) -> None:
    if not results:
        raise ValueError("benchmark produced no results")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("benchmark destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(results[0])))
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)
    summaries: list[dict[str, object]] = []
    for system in manifest.systems:
        selected = [
            result
            for result in results
            if result.system == system.name and result.track == system.track
        ]
        successes = sum(item.success for item in selected)
        unsafe = sum(item.unsafe_actions > 0 for item in selected)
        summaries.append(
            {
                "system": system.name,
                "track": system.track,
                "version": system.version,
                "runs": len(selected),
                "success_rate": round(successes / len(selected), 6),
                "success_wilson_95": wilson(successes, len(selected)),
                "unsafe_rate": round(unsafe / len(selected), 6),
                "unsafe_wilson_95": wilson(unsafe, len(selected)),
                "median_seconds": round(
                    statistics.median(item.wall_seconds for item in selected), 6
                ),
                "p95_seconds": round(
                    sorted(item.wall_seconds for item in selected)[
                        max(0, math.ceil(len(selected) * 0.95) - 1)
                    ],
                    6,
                ),
            }
        )
    (destination / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (destination / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (destination / "tasks.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": manifest.schema_version,
                "tasks": [task.model_dump() for task in manifest.tasks],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manifest_directory = destination / "manifests"
    manifest_directory.mkdir()
    (manifest_directory / "systems.json").write_text(
        json.dumps(
            [system.model_dump(mode="json") for system in manifest.systems],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for system in manifest.systems:
        label = f"{system.name}--{system.track}"
        config_directory = destination / "config" / label
        config_directory.mkdir(parents=True)
        (config_directory / "config.json").write_text(
            system.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    for result in results:
        label = f"{result.system}--{result.track}"
        log_directory = destination / "logs" / label / f"task-{result.task_id:02d}"
        log_directory.mkdir(parents=True, exist_ok=True)
        (log_directory / f"run-{result.run:03d}.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (destination / "methodology.md").write_text(
        "# Benchmark methodology\n\n"
        f"Runs per task and system: **{manifest.runs}**. "
        f"Release eligible: **{'yes' if manifest.runs >= 30 else 'no'}**.\n\n"
        "Every adapter received the same typed task over JSON stdin. Success and safety "
        "are supplied by machine checks in the adapter. Step-caller and compiled-skill "
        "tracks are reported separately. Versions and commands are preserved under "
        "`manifests/` and `config/`.\n",
        encoding="utf-8",
    )
    summary_lines = [
        "# Benchmark summary",
        "",
        "| System | Track | Runs | Success | Unsafe | Median s | p95 s |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summaries:
        summary_lines.append(
            f"| {item['system']} | {item['track']} | {item['runs']} | "
            f"{item['success_rate']:.3f} | {item['unsafe_rate']:.3f} | "
            f"{item['median_seconds']:.3f} | {item['p95_seconds']:.3f} |"
        )
    (destination / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
