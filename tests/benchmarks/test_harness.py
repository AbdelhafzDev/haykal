from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from haykal.benchmarks import BenchmarkManifest, BenchmarkTask, run_benchmark, wilson

ROOT = Path(__file__).parents[2]


def _manifest(version: str = "sha256:abc") -> dict[str, object]:
    task = {
        "id": 1,
        "app": "matjar",
        "task": "open offers",
        "stresses": ["baseline"],
        "success_check": {"state": "offers", "equals": True},
    }
    return {
        "runs": 30,
        "tasks": [task],
        "systems": [
            {
                "name": "haykal",
                "track": "step-caller",
                "version": version,
                "command": ["haykal-adapter"],
            },
            {
                "name": "agent-device",
                "track": "step-caller",
                "version": "git:abc123",
                "command": ["agent-device-adapter"],
            },
        ],
    }


def test_manifest_requires_pins_and_both_required_systems() -> None:
    assert len(BenchmarkManifest.model_validate(_manifest()).systems) == 2
    with pytest.raises(ValidationError):
        BenchmarkManifest.model_validate(_manifest("latest"))


def test_wilson_interval_is_bounded() -> None:
    low, high = wilson(29, 30)
    assert 0 < low < 29 / 30 < high <= 1


def test_declared_twenty_task_inventory_is_machine_valid() -> None:
    payload = yaml.safe_load((ROOT / "benchmarks/tasks.yaml").read_text())
    tasks = [BenchmarkTask.model_validate(item) for item in payload["tasks"]]
    assert [task.id for task in tasks] == list(range(1, 21))
    assert all(task.success_check for task in tasks)


@pytest.mark.asyncio
async def test_command_adapters_write_reproducible_report(tmp_path: Path) -> None:
    manifest_payload = _manifest()
    manifest_payload["runs"] = 1
    command = [
        sys.executable,
        "-c",
        "import json,sys; json.load(sys.stdin); print(json.dumps({'success': True, 'steps': 2}))",
    ]
    for system in manifest_payload["systems"]:  # type: ignore[union-attr]
        system["command"] = command
    manifest = BenchmarkManifest.model_validate(manifest_payload)
    results = await run_benchmark(manifest, tmp_path / "report")
    assert len(results) == 2
    assert all(result.success for result in results)
    summary = json.loads((tmp_path / "report/summary.json").read_text())
    assert [item["track"] for item in summary] == ["step-caller", "step-caller"]
    assert (tmp_path / "report/results.csv").is_file()
    assert (tmp_path / "report/methodology.md").is_file()
    assert (tmp_path / "report/summary.md").is_file()
    assert (tmp_path / "report/tasks.yaml").is_file()
    assert (tmp_path / "report/logs/haykal--step-caller/task-01/run-001.json").is_file()
    with pytest.raises(FileExistsError):
        await run_benchmark(manifest, tmp_path / "report")
