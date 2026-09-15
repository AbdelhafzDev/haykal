"""Independently scored, cryptographically pinned benchmark orchestration."""

from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .oracle import (
    BenchmarkOracle,
    CommandOracle,
    OracleConfig,
    OracleSnapshot,
    StateCheck,
    child_environment,
)
from .provenance import (
    PinnedFile,
    Sha256,
    canonical_sha256,
    contains_sensitive_key,
    sha256_bytes,
    sha256_file,
)


class BenchmarkTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int = Field(gt=0)
    app: str
    task: str
    stresses: list[str]
    success_check: StateCheck
    safety_checks: list[StateCheck] = Field(default_factory=list)
    event_limits: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_event_limits(self) -> BenchmarkTask:
        if any(not name or limit < 0 for name, limit in self.event_limits.items()):
            raise ValueError("event limits require non-empty names and non-negative limits")
        return self


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Literal["haykal", "agent-device", "maestro-mcp", "artemis"]
    track: Literal["step-caller", "compiled-skill"]
    version: Sha256
    command: list[str] = Field(min_length=1)
    executable: PinnedFile
    adapter: PinnedFile
    model: PinnedFile
    prompt: PinnedFile
    configuration_sha256: Sha256
    options: dict[str, object] = Field(default_factory=dict)
    secret_env: tuple[str, ...] = ()

    @model_validator(mode="after")
    def safe_configuration(self) -> SystemConfig:
        if contains_sensitive_key(self.options):
            raise ValueError("benchmark options must reference secrets through secret_env")
        if len(set(self.secret_env)) != len(self.secret_env):
            raise ValueError("secret_env names must be unique")
        if self.version != self.adapter.sha256:
            raise ValueError("system version must equal the executed adapter digest")
        return self

    def configuration_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "track": self.track,
            "options": self.options,
            "secret_env": self.secret_env,
        }

    def verify(self) -> None:
        executable = self.executable.verify()
        adapter = self.adapter.verify()
        self.model.verify()
        self.prompt.verify()
        if executable != Path(self.command[0]).expanduser().resolve():
            raise ValueError(f"{self.name} executable pin does not match command[0]")
        command_paths = {str(Path(item).expanduser().resolve()) for item in self.command}
        if str(adapter) not in command_paths:
            raise ValueError(f"{self.name} adapter pin is not present in its command")
        if canonical_sha256(self.configuration_payload()) != self.configuration_sha256:
            raise ValueError(f"{self.name} configuration digest mismatch")


class BenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["2.0"] = "2.0"
    runs: int = Field(default=30, gt=0)
    random_seed: int = 95
    task_suite_sha256: Sha256
    reference_apk: PinnedFile
    device_image: PinnedFile
    oracle: OracleConfig
    tasks: list[BenchmarkTask] = Field(min_length=1)
    systems: list[SystemConfig] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_contract(self) -> BenchmarkManifest:
        names = {system.name for system in self.systems}
        missing = {"haykal", "agent-device"} - names
        if missing:
            raise ValueError(f"required systems missing: {', '.join(sorted(missing))}")
        if len({(system.name, system.track) for system in self.systems}) != len(self.systems):
            raise ValueError("system and track pairs must be unique")
        if len({task.id for task in self.tasks}) != len(self.tasks):
            raise ValueError("benchmark task ids must be unique")
        expected = canonical_sha256([task.model_dump(mode="json") for task in self.tasks])
        if expected != self.task_suite_sha256:
            raise ValueError("task suite digest mismatch")
        return self

    def verify(self) -> None:
        self.reference_apk.verify()
        self.device_image.verify()
        self.oracle.verify()
        for system in self.systems:
            system.verify()


@dataclass(frozen=True, slots=True)
class AdapterOutcome:
    claimed_success: bool
    claimed_unsafe_actions: int
    output: dict[str, object]
    model_calls: int
    input_tokens: int
    output_tokens: int
    model_screens: int
    steps: int
    failure_category: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    system: str
    track: str
    task_id: int
    run: int
    success: bool
    unsafe_actions: int
    adapter_claimed_success: bool
    adapter_claimed_unsafe_actions: int
    wall_seconds: float
    model_calls: int
    input_tokens: int
    output_tokens: int
    model_screens: int
    steps: int
    failure_category: str | None
    oracle_before_sha256: str
    oracle_after_sha256: str


@dataclass(frozen=True, slots=True)
class RunEvidence:
    sequence: int
    result: BenchmarkResult
    oracle_before: dict[str, object]
    oracle_after: dict[str, object]
    adapter_output: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class BenchmarkAdapter(Protocol):
    async def run(self, task: BenchmarkTask, run: int) -> AdapterOutcome: ...


class CommandAdapter:
    """Untrusted adapter whose success and safety fields are diagnostic claims only."""

    def __init__(self, config: SystemConfig, *, timeout_s: float = 300.0) -> None:
        self.config = config
        self.timeout_s = timeout_s

    async def run(self, task: BenchmarkTask, run: int) -> AdapterOutcome:
        environment = child_environment(self.config.secret_env, self.config.command)
        process = await asyncio.create_subprocess_exec(
            *self.config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        request = json.dumps(
            {"task": task.model_dump(mode="json"), "run": run, "options": self.config.options},
            ensure_ascii=False,
        ).encode()
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request), timeout=self.timeout_s
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return self._failure("timeout")
        secret_values = [
            os.environ[name].encode() for name in self.config.secret_env if os.environ[name]
        ]
        if any(secret in stdout or secret in stderr for secret in secret_values):
            return self._failure("secret_leak")
        if process.returncode != 0:
            return self._failure("crash")
        try:
            payload = json.loads(stdout)
            if not isinstance(payload, dict):
                raise TypeError
            output = payload.get("output", {})
            if not isinstance(output, dict):
                raise TypeError
            failure_category = payload.get("failure_category")
            if failure_category is not None and not isinstance(failure_category, str):
                raise TypeError
            return AdapterOutcome(
                bool(payload.get("success", False)),
                max(0, int(payload.get("unsafe_actions", 0))),
                output,
                max(0, int(payload.get("model_calls", 0))),
                max(0, int(payload.get("input_tokens", 0))),
                max(0, int(payload.get("output_tokens", 0))),
                max(0, int(payload.get("model_screens", 0))),
                max(0, int(payload.get("steps", 0))),
                failure_category,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return self._failure("invalid_result")

    @staticmethod
    def _failure(category: str) -> AdapterOutcome:
        return AdapterOutcome(False, 0, {}, 0, 0, 0, 0, 0, category)


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


def _score(
    task: BenchmarkTask, before: OracleSnapshot, after: OracleSnapshot, outcome: AdapterOutcome
) -> tuple[bool, int]:
    before_state = {**before.state, "output": {}}
    state = {**after.state, "output": outcome.output}
    success = (
        outcome.failure_category is None
        and not task.success_check.evaluate(before_state)
        and task.success_check.evaluate(state)
    )
    unsafe_delta = max(0, after.unsafe_actions - before.unsafe_actions)
    unsafe_checks = sum(not check.evaluate(state) for check in task.safety_checks)
    if after.event_log[: len(before.event_log)] == before.event_log:
        new_events = after.event_log[len(before.event_log) :]
    else:
        new_events = after.event_log
    unsafe_events = sum(
        max(0, new_events.count(event) - limit) for event, limit in task.event_limits.items()
    )
    return success, unsafe_delta + unsafe_checks + unsafe_events


async def run_benchmark(
    manifest: BenchmarkManifest,
    output: str | Path,
    *,
    oracle: BenchmarkOracle | None = None,
) -> list[BenchmarkResult]:
    destination = Path(output)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("benchmark destination must be empty")
    manifest.verify()
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_inputs(destination, manifest)
    active_oracle = oracle or CommandOracle(manifest.oracle)
    adapter_types = {"haykal": HaykalAdapter, "agent-device": AgentDeviceAdapter}
    adapters = {
        (config.name, config.track): adapter_types.get(config.name, CommandAdapter)(config)
        for config in manifest.systems
    }
    rng = random.Random(manifest.random_seed)
    raw_directory = destination / "raw"
    raw_directory.mkdir()
    evidence: list[RunEvidence] = []
    sequence = 0
    for task in manifest.tasks:
        for run in range(1, manifest.runs + 1):
            systems = list(manifest.systems)
            rng.shuffle(systems)
            for system in systems:
                sequence += 1
                started = time.monotonic()
                before = OracleSnapshot()
                after = OracleSnapshot()
                outcome = CommandAdapter._failure("oracle_failure")
                try:
                    task_payload = task.model_dump(mode="json")
                    await active_oracle.reset(task_payload, run)
                    before = await active_oracle.snapshot(task_payload, run)
                    outcome = await adapters[(system.name, system.track)].run(task, run)
                    after = await active_oracle.snapshot(task_payload, run)
                    success, unsafe = _score(task, before, after, outcome)
                    category = outcome.failure_category
                    if category is None and unsafe:
                        category = "unsafe_oracle"
                    elif category is None and not success:
                        category = "oracle_mismatch"
                except Exception:
                    success, unsafe, category = False, 0, "oracle_failure"
                result = BenchmarkResult(
                    system.name,
                    system.track,
                    task.id,
                    run,
                    success,
                    unsafe,
                    outcome.claimed_success,
                    outcome.claimed_unsafe_actions,
                    round(time.monotonic() - started, 6),
                    outcome.model_calls,
                    outcome.input_tokens,
                    outcome.output_tokens,
                    outcome.model_screens,
                    outcome.steps,
                    category,
                    before.digest,
                    after.digest,
                )
                item = RunEvidence(
                    sequence,
                    result,
                    before.model_dump(mode="json"),
                    after.model_dump(mode="json"),
                    outcome.output,
                )
                evidence.append(item)
                (raw_directory / f"{sequence:08d}.json").write_text(
                    json.dumps(item.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
    _seal_evidence(destination)
    results = [item.result for item in evidence]
    _write_derived(destination, manifest, results)
    return results


def load_manifest(path: str | Path) -> BenchmarkManifest:
    return BenchmarkManifest.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def _write_inputs(destination: Path, manifest: BenchmarkManifest) -> None:
    (destination / "benchmark-manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (destination / "tasks.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": manifest.schema_version,
                "tasks": [task.model_dump(mode="json") for task in manifest.tasks],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config_directory = destination / "config"
    config_directory.mkdir()
    for system in manifest.systems:
        (config_directory / f"{system.name}--{system.track}.json").write_text(
            system.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )


def _seal_evidence(destination: Path) -> None:
    paths = [
        destination / "benchmark-manifest.json",
        destination / "tasks.yaml",
        *sorted((destination / "config").glob("*.json")),
        *sorted((destination / "raw").glob("*.json")),
    ]
    entries = {str(path.relative_to(destination)): sha256_file(path) for path in paths}
    manifest = {
        "schema_version": "1.0",
        "files": entries,
        "raw_runs": len(list((destination / "raw").glob("*.json"))),
    }
    evidence = destination / "evidence-manifest.json"
    evidence.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (destination / "evidence-manifest.sha256").write_text(
        f"{sha256_file(evidence)}  evidence-manifest.json\n", encoding="ascii"
    )
    for path in paths:
        path.chmod(0o400)
    (destination / "raw").chmod(0o500)
    (destination / "config").chmod(0o500)
    evidence.chmod(0o400)
    (destination / "evidence-manifest.sha256").chmod(0o400)


def verify_evidence(source: str | Path) -> dict[str, object]:
    root = Path(source)
    evidence = root / "evidence-manifest.json"
    sidecar = (root / "evidence-manifest.sha256").read_text(encoding="ascii").split()[0]
    if sha256_file(evidence) != sidecar:
        raise ValueError("evidence manifest digest mismatch")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError("evidence manifest has no file map")
    actual_paths = {
        "benchmark-manifest.json",
        "tasks.yaml",
        *(str(path.relative_to(root)) for path in (root / "config").glob("*.json")),
        *(str(path.relative_to(root)) for path in (root / "raw").glob("*.json")),
    }
    if actual_paths != set(files):
        raise ValueError("sealed evidence file set mismatch")
    if payload.get("raw_runs") != len(list((root / "raw").glob("*.json"))):
        raise ValueError("sealed evidence run count mismatch")
    for relative, expected in files.items():
        path = (root / str(relative)).resolve()
        if root.resolve() not in path.parents:
            raise ValueError("evidence path escapes report root")
        if sha256_file(path) != expected:
            raise ValueError(f"evidence digest mismatch: {relative}")
    return {str(key): value for key, value in payload.items()}


def rebuild_summary(source: str | Path, output: str | Path) -> str:
    root = Path(source)
    verify_evidence(root)
    destination = Path(output)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("rebuild destination must be empty")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = BenchmarkManifest.model_validate_json(
        (root / "benchmark-manifest.json").read_text(encoding="utf-8")
    )
    results = [
        BenchmarkResult(**json.loads(path.read_text(encoding="utf-8"))["result"])
        for path in sorted((root / "raw").glob("*.json"))
    ]
    _write_derived(destination, manifest, results)
    return sha256_file(destination / "derived-manifest.json")


def _write_derived(
    destination: Path, manifest: BenchmarkManifest, results: list[BenchmarkResult]
) -> None:
    if not results:
        raise ValueError("benchmark produced no results")
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
        json.dumps(summaries, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    methodology = (
        "# Benchmark methodology\n\n"
        f"Runs per task and system: **{manifest.runs}**. Release eligible: "
        f"**{'yes' if manifest.runs >= 30 else 'no'}**.\n\n"
        "The controller resets the app and records independent pre/post state "
        "around every adapter run. Adapter success and safety fields are retained "
        "only as claims; published scores are computed from oracle state and safety "
        "checks. System order is deterministically randomized.\n"
    )
    (destination / "methodology.md").write_text(methodology, encoding="utf-8")
    lines = [
        "# Benchmark summary",
        "",
        "| System | Track | Runs | Success | Unsafe | Median s | p95 s |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summaries:
        lines.append(
            f"| {item['system']} | {item['track']} | {item['runs']} | "
            f"{item['success_rate']:.3f} | {item['unsafe_rate']:.3f} | "
            f"{item['median_seconds']:.3f} | {item['p95_seconds']:.3f} |"
        )
    (destination / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    derived = {
        name: sha256_file(destination / name)
        for name in ("results.csv", "summary.json", "summary.md", "methodology.md")
    }
    (destination / "derived-manifest.json").write_text(
        json.dumps(derived, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def report_digest(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())
