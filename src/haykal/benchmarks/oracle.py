"""Independent state-oracle boundary for benchmark scoring."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .provenance import PinnedFile, Sha256, canonical_sha256, contains_sensitive_key


class StateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: str
    equals: object | None = None
    gte: float | None = None
    lte: float | None = None

    @model_validator(mode="after")
    def one_comparison(self) -> StateCheck:
        comparisons = sum(value is not None for value in (self.equals, self.gte, self.lte))
        if comparisons != 1:
            raise ValueError("state check requires exactly one of equals, gte, or lte")
        return self

    def evaluate(self, state: dict[str, object]) -> bool:
        actual: object = state
        for segment in self.state.split("."):
            if not isinstance(actual, dict) or segment not in actual:
                return False
            actual = actual[segment]
        if self.equals is not None:
            return actual == self.equals
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        if self.gte is not None:
            return actual >= self.gte
        assert self.lte is not None
        return actual <= self.lte


class OracleSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: dict[str, object] = Field(default_factory=dict)
    unsafe_actions: int = Field(default=0, ge=0)
    event_log: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class BenchmarkOracle(Protocol):
    async def reset(self, task: dict[str, object], run: int) -> None: ...

    async def snapshot(self, task: dict[str, object], run: int) -> OracleSnapshot: ...


class OracleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command: list[str] = Field(min_length=1)
    executable: PinnedFile
    adapter: PinnedFile
    configuration_sha256: Sha256
    options: dict[str, object] = Field(default_factory=dict)
    secret_env: tuple[str, ...] = ()

    @model_validator(mode="after")
    def safe_configuration(self) -> OracleConfig:
        if contains_sensitive_key(self.options):
            raise ValueError("oracle options must reference secrets through secret_env")
        if len(set(self.secret_env)) != len(self.secret_env):
            raise ValueError("oracle secret_env names must be unique")
        return self

    def verify(self) -> None:
        executable = self.executable.verify()
        adapter = self.adapter.verify()
        if executable != Path(self.command[0]).expanduser().resolve():
            raise ValueError("oracle executable pin does not match command[0]")
        command_paths = {str(Path(item).expanduser().resolve()) for item in self.command}
        if str(adapter) not in command_paths:
            raise ValueError("oracle adapter pin is not present in its command")
        expected = canonical_sha256({"options": self.options, "secret_env": self.secret_env})
        if expected != self.configuration_sha256:
            raise ValueError("oracle configuration digest mismatch")


def child_environment(secret_env: tuple[str, ...], command: list[str]) -> dict[str, str]:
    environment = {
        key: value
        for key in ("HOME", "LANG", "PATH", "TMPDIR", "SYSTEMROOT", "WINDIR")
        if (value := os.environ.get(key)) is not None
    }
    for name in secret_env:
        if name not in os.environ:
            raise ValueError(f"required secret environment variable is missing: {name}")
        value = os.environ[name]
        if value and any(value in argument for argument in command):
            raise ValueError("secret value must not appear in a benchmark command")
        environment[name] = value
    return environment


class CommandOracle:
    """Separate JSON-over-stdio process used only for reset and state reads."""

    def __init__(self, config: OracleConfig, *, timeout_s: float = 30.0) -> None:
        self.config = config
        self.timeout_s = timeout_s

    async def reset(self, task: dict[str, object], run: int) -> None:
        payload = await self._call("reset", task, run)
        if payload.get("reset") is not True:
            raise RuntimeError("independent oracle did not confirm reset")

    async def snapshot(self, task: dict[str, object], run: int) -> OracleSnapshot:
        return OracleSnapshot.model_validate(await self._call("snapshot", task, run))

    async def _call(self, operation: str, task: dict[str, object], run: int) -> dict[str, object]:
        environment = child_environment(self.config.secret_env, self.config.command)
        process = await asyncio.create_subprocess_exec(
            *self.config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        request = json.dumps(
            {
                "operation": operation,
                "task": task,
                "run": run,
                "options": self.config.options,
            },
            ensure_ascii=False,
        ).encode()
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request), timeout=self.timeout_s
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("independent oracle timed out") from None
        secret_values = [
            os.environ[name].encode() for name in self.config.secret_env if os.environ[name]
        ]
        if any(secret in stdout or secret in stderr for secret in secret_values):
            raise RuntimeError("independent oracle leaked a secret")
        if process.returncode != 0:
            raise RuntimeError("independent oracle failed")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("independent oracle returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("independent oracle returned a non-object")
        return payload
