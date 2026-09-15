from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from haykal.benchmarks import (
    BenchmarkManifest,
    BenchmarkTask,
    OracleSnapshot,
    canonical_sha256,
    rebuild_summary,
    run_benchmark,
    sha256_file,
    verify_evidence,
    wilson,
)

ROOT = Path(__file__).parents[2]


class SequenceOracle:
    def __init__(
        self,
        after: dict[str, object],
        *,
        before: dict[str, object] | None = None,
        unsafe_actions: int = 0,
        before_events: tuple[str, ...] = (),
        after_events: tuple[str, ...] = (),
    ) -> None:
        self.before = before or {"offers": False, "submit_count": 0}
        self.after = after
        self.unsafe_actions = unsafe_actions
        self.before_events = before_events
        self.after_events = after_events
        self.snapshots = 0
        self.resets = 0

    async def reset(self, task: dict[str, object], run: int) -> None:
        del task, run
        self.snapshots = 0
        self.resets += 1

    async def snapshot(self, task: dict[str, object], run: int) -> OracleSnapshot:
        del task, run
        self.snapshots += 1
        if self.snapshots == 1:
            return OracleSnapshot(state=self.before, event_log=self.before_events)
        return OracleSnapshot(
            state=self.after,
            unsafe_actions=self.unsafe_actions,
            event_log=self.after_events,
        )


def _file(path: Path, content: str) -> dict[str, str]:
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "sha256": sha256_file(path)}


def _manifest(tmp_path: Path, *, version: str | None = None) -> dict[str, object]:
    adapter = _file(
        tmp_path / "adapter.py",
        "import json,sys\njson.load(sys.stdin)\n"
        "print(json.dumps({'success': True, 'unsafe_actions': 0, 'steps': 2}))\n",
    )
    oracle_adapter = _file(
        tmp_path / "oracle.py",
        "import json,sys\nr=json.load(sys.stdin)\n"
        "print(json.dumps({'reset': True} if r['operation']=='reset' else "
        "{'state': {'offers': False}, 'unsafe_actions': 0, 'event_log': []}))\n",
    )
    executable = {"path": sys.executable, "sha256": sha256_file(sys.executable)}
    model = _file(tmp_path / "model.bin", "model fixture")
    prompt = _file(tmp_path / "prompt.txt", "neutral task prompt")
    apk = _file(tmp_path / "matjar.apk", "apk fixture")
    image = _file(tmp_path / "device.img", "device fixture")
    task = {
        "id": 1,
        "app": "matjar",
        "task": "open offers",
        "stresses": ["baseline"],
        "success_check": {"state": "offers", "equals": True},
    }
    task_model = BenchmarkTask.model_validate(task)
    systems = []
    for name in ("haykal", "agent-device"):
        options: dict[str, object] = {}
        configuration = {
            "name": name,
            "track": "step-caller",
            "options": options,
            "secret_env": [],
        }
        systems.append(
            {
                "name": name,
                "track": "step-caller",
                "version": version or adapter["sha256"],
                "command": [sys.executable, adapter["path"]],
                "executable": executable,
                "adapter": adapter,
                "model": model,
                "prompt": prompt,
                "configuration_sha256": canonical_sha256(configuration),
                "options": options,
            }
        )
    return {
        "schema_version": "2.0",
        "runs": 1,
        "random_seed": 95,
        "task_suite_sha256": canonical_sha256([task_model.model_dump(mode="json")]),
        "reference_apk": apk,
        "device_image": image,
        "oracle": {
            "command": [sys.executable, oracle_adapter["path"]],
            "executable": executable,
            "adapter": oracle_adapter,
            "configuration_sha256": canonical_sha256({"options": {}, "secret_env": []}),
        },
        "tasks": [task],
        "systems": systems,
    }


def test_manifest_requires_cryptographic_pins_and_both_systems(tmp_path: Path) -> None:
    assert len(BenchmarkManifest.model_validate(_manifest(tmp_path)).systems) == 2
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        BenchmarkManifest.model_validate(_manifest(tmp_path, version="git:abc123"))


def test_manifest_rejects_inline_system_or_oracle_secrets(tmp_path: Path) -> None:
    system_payload = _manifest(tmp_path)
    system_payload["systems"][0]["options"] = {"api_token": "must-not-be-here"}  # type: ignore[index]
    with pytest.raises(ValidationError, match="secret_env"):
        BenchmarkManifest.model_validate(system_payload)

    oracle_payload = _manifest(tmp_path)
    oracle_payload["oracle"]["options"] = {"password": "must-not-be-here"}  # type: ignore[index]
    with pytest.raises(ValidationError, match="secret_env"):
        BenchmarkManifest.model_validate(oracle_payload)


def test_wilson_interval_is_bounded() -> None:
    low, high = wilson(29, 30)
    assert 0 < low < 29 / 30 < high <= 1


def test_declared_twenty_task_inventory_is_machine_valid() -> None:
    payload = yaml.safe_load((ROOT / "benchmarks/tasks.yaml").read_text())
    tasks = [BenchmarkTask.model_validate(item) for item in payload["tasks"]]
    assert [task.id for task in tasks] == list(range(1, 21))
    assert all(task.success_check for task in tasks)
    assert {task.id for task in tasks if task.safety_checks} == {18, 20}
    assert {task.id for task in tasks if task.event_limits} == {18, 20}


@pytest.mark.asyncio
async def test_controller_scores_oracle_and_rebuilds_only_from_sealed_raw(
    tmp_path: Path,
) -> None:
    manifest = BenchmarkManifest.model_validate(_manifest(tmp_path))
    report = tmp_path / "report"
    results = await run_benchmark(manifest, report, oracle=SequenceOracle({"offers": True}))

    assert len(results) == 2
    assert all(result.success for result in results)
    assert all(result.adapter_claimed_success for result in results)
    assert verify_evidence(report)["raw_runs"] == 2
    rebuilt = tmp_path / "rebuilt"
    rebuild_summary(report, rebuilt)
    assert (report / "derived-manifest.json").read_bytes() == (
        rebuilt / "derived-manifest.json"
    ).read_bytes()
    assert (report / "summary.json").read_bytes() == (rebuilt / "summary.json").read_bytes()
    with pytest.raises(FileExistsError):
        await run_benchmark(manifest, report, oracle=SequenceOracle({"offers": True}))


@pytest.mark.asyncio
async def test_lying_adapter_cannot_override_oracle_or_safety(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["tasks"][0]["safety_checks"] = [{"state": "submit_count", "lte": 0}]  # type: ignore[index]
    task = BenchmarkTask.model_validate(payload["tasks"][0])  # type: ignore[index]
    payload["task_suite_sha256"] = canonical_sha256([task.model_dump(mode="json")])
    manifest = BenchmarkManifest.model_validate(payload)

    results = await run_benchmark(
        manifest,
        tmp_path / "report",
        oracle=SequenceOracle({"offers": False, "submit_count": 2}),
    )

    assert all(result.adapter_claimed_success for result in results)
    assert all(not result.success for result in results)
    assert all(result.unsafe_actions == 1 for result in results)
    assert all(result.failure_category == "unsafe_oracle" for result in results)


@pytest.mark.asyncio
async def test_adapter_cannot_hide_duplicate_external_event(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["tasks"][0]["event_limits"] = {"submit_order": 1}  # type: ignore[index]
    task = BenchmarkTask.model_validate(payload["tasks"][0])  # type: ignore[index]
    payload["task_suite_sha256"] = canonical_sha256([task.model_dump(mode="json")])
    manifest = BenchmarkManifest.model_validate(payload)

    results = await run_benchmark(
        manifest,
        tmp_path / "report",
        oracle=SequenceOracle(
            {"offers": True},
            after_events=("submit_order", "submit_order"),
        ),
    )

    assert all(result.adapter_claimed_unsafe_actions == 0 for result in results)
    assert all(result.unsafe_actions == 1 for result in results)
    assert all(result.failure_category == "unsafe_oracle" for result in results)


@pytest.mark.asyncio
async def test_command_oracle_is_a_separate_fail_closed_process(tmp_path: Path) -> None:
    manifest = BenchmarkManifest.model_validate(_manifest(tmp_path))

    results = await run_benchmark(manifest, tmp_path / "report")

    assert all(result.adapter_claimed_success for result in results)
    assert all(not result.success for result in results)
    assert all(result.failure_category == "oracle_mismatch" for result in results)


@pytest.mark.asyncio
async def test_preexisting_success_state_cannot_credit_a_noop_adapter(tmp_path: Path) -> None:
    manifest = BenchmarkManifest.model_validate(_manifest(tmp_path))

    results = await run_benchmark(
        manifest,
        tmp_path / "report",
        oracle=SequenceOracle({"offers": True}, before={"offers": True}),
    )

    assert all(not result.success for result in results)
    assert all(result.failure_category == "oracle_mismatch" for result in results)


@pytest.mark.asyncio
async def test_secret_canary_is_not_published(tmp_path: Path, monkeypatch) -> None:
    payload = _manifest(tmp_path)
    systems = payload["systems"]  # type: ignore[assignment]
    adapter_path = Path(systems[0]["adapter"]["path"])
    adapter_path.write_text(
        "import json,os,sys\njson.load(sys.stdin)\nprint(os.environ['BENCHMARK_CANARY'])\n",
        encoding="utf-8",
    )
    adapter_digest = sha256_file(adapter_path)
    monkeypatch.setenv("BENCHMARK_CANARY", "canary-must-never-be-published")
    for system in systems:
        system["version"] = adapter_digest
        system["adapter"]["sha256"] = adapter_digest
        system["secret_env"] = ["BENCHMARK_CANARY"]
        system["configuration_sha256"] = canonical_sha256(
            {
                "name": system["name"],
                "track": system["track"],
                "options": system["options"],
                "secret_env": ["BENCHMARK_CANARY"],
            }
        )
    manifest = BenchmarkManifest.model_validate(payload)

    results = await run_benchmark(
        manifest,
        tmp_path / "report",
        oracle=SequenceOracle({"offers": True}),
    )

    assert all(not result.success for result in results)
    assert all(result.failure_category == "secret_leak" for result in results)
    published = b"".join(
        path.read_bytes() for path in (tmp_path / "report").rglob("*") if path.is_file()
    )
    assert b"canary-must-never-be-published" not in published


@pytest.mark.asyncio
async def test_pin_mismatch_prevents_execution_and_evidence_creation(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    manifest = BenchmarkManifest.model_validate(payload)
    Path(payload["systems"][0]["adapter"]["path"]).write_text("tampered")  # type: ignore[index]

    with pytest.raises(ValueError, match="pin mismatch"):
        await run_benchmark(manifest, tmp_path / "report")
    assert not (tmp_path / "report").exists()


@pytest.mark.asyncio
async def test_tampered_raw_evidence_cannot_be_rebuilt(tmp_path: Path) -> None:
    manifest = BenchmarkManifest.model_validate(_manifest(tmp_path))
    report = tmp_path / "report"
    await run_benchmark(manifest, report, oracle=SequenceOracle({"offers": True}))
    raw = next((report / "raw").glob("*.json"))
    raw.chmod(0o600)
    raw.write_text("{}")

    with pytest.raises(ValueError, match="evidence digest mismatch"):
        rebuild_summary(report, tmp_path / "rebuilt")


@pytest.mark.asyncio
async def test_unsealed_extra_raw_run_is_rejected(tmp_path: Path) -> None:
    manifest = BenchmarkManifest.model_validate(_manifest(tmp_path))
    report = tmp_path / "report"
    await run_benchmark(manifest, report, oracle=SequenceOracle({"offers": True}))
    (report / "raw").chmod(0o700)
    (report / "raw/99999999.json").write_text("{}")

    with pytest.raises(ValueError, match="file set mismatch"):
        rebuild_summary(report, tmp_path / "rebuilt")
