from __future__ import annotations

import io
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from mcp import Client
from PIL import Image
from starlette.testclient import TestClient

from haykal.artifacts import ArtifactStore
from haykal.benchmarks import BenchmarkManifest, run_benchmark
from haykal.contracts import RunRequest, Skill
from haykal.device import DeviceHealth, DeviceSnapshot
from haykal.device.single_shot import DispatchOutcome
from haykal.hardening import Diagnostics, ImageRegion, RedactionPolicy, TraceReportExporter
from haykal.runtime import RuntimeSession
from haykal.traces import TraceStore
from haykal.transports.http import IdempotencyStore, SessionRegistry, create_app
from haykal.transports.mcp import create_mcp_server
from tests.workflows.test_engine import Backend as SkillBackend
from tests.workflows.test_engine import _system as skill_system

READINESS_LOCK = pytest.mark.xfail(
    strict=True,
    reason="P95.2: diagnostics do not yet include device readiness",
)
BENCHMARK_LOCK = pytest.mark.xfail(
    strict=True,
    reason="P95.3: benchmark success is not yet computed by an independent oracle",
)
PIN_LOCK = pytest.mark.xfail(
    strict=True,
    reason="P95.3: benchmark version pins are not yet cryptographically validated",
)


def _hierarchy(label: str, resource: str) -> str:
    return f'''<hierarchy rotation="0"><node index="0" text="{label}"
      resource-id="dev.haykal.matjar:id/{resource}" class="android.widget.Button"
      package="dev.haykal.matjar" content-desc="{label}" checkable="false"
      checked="false" clickable="true" enabled="true" focusable="true"
      focused="false" scrollable="false" selected="false"
      bounds="[10,20][210,120]" visible-to-user="true" /></hierarchy>'''


class PaymentBackend:
    def __init__(self) -> None:
        self.opened = False
        self.taps = 0
        self.dispatches = 0

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False

    async def health(self) -> DeviceHealth:
        return DeviceHealth(self.opened, "fixture")

    async def snapshot(self) -> DeviceSnapshot:
        return DeviceSnapshot(400, 800, 2, 0, "dev.haykal.matjar", ".Main", False)

    async def hierarchy(self) -> str:
        return _hierarchy("ادفع", "place_order")

    async def screenshot(self) -> bytes:
        return b"fixture-png"

    async def tap(self, x: int, y: int) -> None:
        self.taps += 1

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None: ...

    async def type_text(self, text: str, *, replace: bool) -> None: ...

    async def press(self, key: str) -> None: ...

    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome:
        self.dispatches += 1
        return DispatchOutcome(action_id, "dispatched", {"wire_calls": 1}, False)


def _runtime(tmp_path: Path, backend: PaymentBackend, *, name: str) -> RuntimeSession:
    return RuntimeSession(
        session_id=name,
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / f"{name}-artifacts"),
        trace_store=TraceStore(tmp_path / f"{name}.sqlite3"),
    )


def _downgraded_coordinate(revision: int) -> dict[str, object]:
    return {
        "action_id": "caller-downgrade",
        "kind": "tap",
        "target": {
            "scene_revision": revision,
            "coordinates": [110, 70],
            "description": "Place order",
        },
        "risk": {"category": "navigation", "gate": "none"},
    }


def test_http_coordinate_risk_downgrade_cannot_dispatch(tmp_path: Path) -> None:
    backends: list[PaymentBackend] = []

    async def factory(session_id: str, _serial: str) -> RuntimeSession:
        backend = PaymentBackend()
        backends.append(backend)
        return _runtime(tmp_path, backend, name=session_id)

    database = tmp_path / "http.sqlite3"
    app = create_app(
        sessions=SessionRegistry(factory),
        idempotency=IdempotencyStore(database),
        traces=TraceStore(database),
        bearer_token="test-caller-token",
    )
    auth = {"Authorization": "Bearer test-caller-token"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/sessions",
            json={"device_serial": "emulator-test"},
            headers={**auth, "Idempotency-Key": "create"},
        ).json()
        prefix = f"/v1/sessions/{created['session_id']}"
        scene = client.post(
            f"{prefix}/observe",
            json={},
            headers={**auth, "Idempotency-Key": "observe"},
        ).json()
        response = client.post(
            f"{prefix}/actions",
            json=_downgraded_coordinate(scene["revision"]),
            headers={**auth, "Idempotency-Key": "act"},
        )

    assert response.status_code != 200 or response.json().get("status") != "verified"
    assert backends[0].taps == 0
    assert backends[0].dispatches == 0


@pytest.mark.asyncio
async def test_mcp_resolved_payment_label_overrides_caller_navigation(tmp_path: Path) -> None:
    backend = PaymentBackend()
    runtime = _runtime(tmp_path, backend, name="mcp")
    await runtime.open()
    scene = await runtime.observe()
    action = {
        "action_id": "mcp-downgrade",
        "kind": "tap",
        "target": {
            "scene_revision": scene.revision,
            "selector": {"resource_id": {"equals": "dev.haykal.matjar:id/place_order"}},
        },
        "risk": {"category": "navigation", "gate": "none"},
    }
    server = create_mcp_server(lambda _session_id: runtime)
    async with Client(server) as client:
        result = await client.call_tool("act", {"session_id": "mcp", "action": action})
    await runtime.close()

    assert result.structured_content["status"] != "verified"
    assert backend.taps == 0
    assert backend.dispatches == 0


def _downgraded_skill() -> Skill:
    return Skill.model_validate(
        {
            "metadata": {
                "name": "matjar.downgraded",
                "version": "1.0.0",
                "package": "dev.haykal.matjar",
                "app_versions": ">=1,<2",
                "locales": ["ar-SA"],
            },
            "elements": {
                "continue_button": {"resource_id": {"ends_with": "id/place_order"}},
                "done": {"resource_id": {"ends_with": "id/confirmation"}},
            },
            "start": "continue",
            "states": {
                "continue": {
                    "expect": {"visible": {"semantic_name": "continue_button"}},
                    "action": {"kind": "tap", "target": {"semantic_name": "continue_button"}},
                    "verify": {"visible": {"semantic_name": "done"}},
                    "next": "finish",
                },
                "finish": {
                    "expect": {"visible": {"semantic_name": "done"}},
                    "terminal": "completed",
                },
            },
        }
    )


@pytest.mark.asyncio
async def test_signed_skill_is_reclassified_from_resolved_payment_target(tmp_path: Path) -> None:
    backend = SkillBackend(mode="approval")
    engine, _runtime_session, signed = await skill_system(tmp_path, _downgraded_skill(), backend)
    result = await engine.start(
        RunRequest(session_id="session-1", skill=signed.metadata.name, version="1.0.0")
    )

    assert result.status == "failed"
    assert result.pending == {"reason": "approval_policy_missing"}
    assert backend.taps == 0
    assert backend.dispatches == 0


def _png(color: tuple[int, int, int]) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(stream, format="PNG")
    return stream.getvalue()


def test_trace_export_rejects_artifact_without_matching_image_region(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "trace.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    covered = artifacts.put(_png((255, 255, 255)))
    uncovered = artifacts.put(_png((255, 0, 0)))
    traces.append(
        trace_id="trace",
        run_id="run",
        event_type="observation.created",
        artifacts=[covered.digest, uncovered.digest],
    )
    policy = RedactionPolicy(
        include_images=True,
        image_regions=[ImageRegion(artifact=covered.digest, left=0, top=0, right=6, bottom=6)],
    )

    with pytest.raises(ValueError, match="matching redaction region"):
        TraceReportExporter(traces, artifacts).export("trace", tmp_path / "report", policy)
    assert not (tmp_path / "report").exists()


@READINESS_LOCK
def test_storage_health_is_not_device_readiness(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    with closing(sqlite3.connect(state / "runtime.sqlite3")) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.commit()
    ArtifactStore(state / "artifacts").put(b"evidence")

    report = Diagnostics(state, minimum_free_bytes=1).run()

    assert report.status != "ready"


@BENCHMARK_LOCK
@pytest.mark.asyncio
async def test_adapter_success_cannot_override_independent_oracle(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "import json,sys; json.load(sys.stdin); "
        "print(json.dumps({'success': True, 'unsafe_actions': 0}))",
    ]
    manifest = BenchmarkManifest.model_validate(
        {
            "runs": 1,
            "tasks": [
                {
                    "id": 1,
                    "app": "matjar",
                    "task": "open offers",
                    "stresses": ["adversarial_adapter"],
                    "success_check": {"state": "offers", "equals": True},
                }
            ],
            "systems": [
                {
                    "name": name,
                    "track": "step-caller",
                    "version": f"sha256:{index:064x}",
                    "command": command,
                }
                for index, name in enumerate(("haykal", "agent-device"), start=1)
            ],
        }
    )
    oracle_state = {"offers": False}

    results = await run_benchmark(manifest, tmp_path / "report")
    expected = oracle_state["offers"] is True

    assert all(result.success is expected for result in results)


@PIN_LOCK
def test_benchmark_rejects_non_cryptographic_version_pin() -> None:
    with pytest.raises(ValueError, match="cryptographic"):
        BenchmarkManifest.model_validate(
            {
                "runs": 1,
                "tasks": [
                    {
                        "id": 1,
                        "app": "matjar",
                        "task": "open offers",
                        "stresses": ["pinning"],
                        "success_check": {"state": "offers", "equals": True},
                    }
                ],
                "systems": [
                    {
                        "name": "haykal",
                        "track": "step-caller",
                        "version": "not-a-real-pin",
                        "command": ["haykal-adapter"],
                    },
                    {
                        "name": "agent-device",
                        "track": "step-caller",
                        "version": "also-not-a-pin",
                        "command": ["agent-device-adapter"],
                    },
                ],
            }
        )
