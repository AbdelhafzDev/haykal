from __future__ import annotations

from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.contracts.action import ActionTarget, Risk, SemanticAction
from haykal.contracts.common import SettlePolicy
from haykal.contracts.expectation import Expectation
from haykal.contracts.selector import ResourceMatch, Selector
from haykal.device import DeviceHealth, DeviceSnapshot
from haykal.device.single_shot import DispatchOutcome
from haykal.runtime import RuntimeSession
from haykal.traces import TraceStore


def _hierarchy(label: str, resource_id: str) -> str:
    return f'''<hierarchy rotation="0"><node index="0" text="{label}" resource-id="{resource_id}"
      class="android.widget.Button" package="dev.haykal" content-desc="{label}"
      checkable="false" checked="false" clickable="true" enabled="true"
      focusable="true" focused="false" scrollable="false" selected="false"
      bounds="[10,20][210,120]" visible-to-user="true" /></hierarchy>'''


class Backend:
    def __init__(self) -> None:
        self.opened = False
        self.taps = 0

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False

    async def health(self) -> DeviceHealth:
        return DeviceHealth(self.opened, "fixture")

    async def snapshot(self) -> DeviceSnapshot:
        return DeviceSnapshot(400, 800, 2, 0, "dev.haykal", ".Main", False)

    async def hierarchy(self) -> str:
        return (
            _hierarchy("تم", "dev.haykal:id/done")
            if self.taps
            else _hierarchy("التالي", "dev.haykal:id/next")
        )

    async def screenshot(self) -> bytes:
        return b"fixture-png"

    async def tap(self, x: int, y: int) -> None:
        assert (x, y) == (110, 70)
        self.taps += 1

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None: ...

    async def type_text(self, text: str, *, replace: bool) -> None: ...

    async def press(self, key: str) -> None: ...

    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome:
        return DispatchOutcome(action_id, "dispatched", None, False)


@pytest.mark.asyncio
async def test_shared_runtime_observe_resolve_act_verify_trace(tmp_path: Path) -> None:
    backend = Backend()
    runtime = RuntimeSession(
        session_id="session",
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        trace_store=TraceStore(tmp_path / "trace.sqlite3"),
    )
    await runtime.open()
    scene = await runtime.observe()
    action = SemanticAction(
        action_id="tap-next",
        kind="tap",
        target=ActionTarget(
            scene_revision=scene.revision,
            selector=Selector(resource_id=ResourceMatch(equals="dev.haykal:id/next")),
        ),
        expect=Expectation(
            visible=Selector(resource_id=ResourceMatch(equals="dev.haykal:id/done")),
            timeout_ms=1_000,
            settle=SettlePolicy(stable_samples=2, interval_ms=1),
        ),
        risk=Risk(category="navigation", gate="none"),
    )
    resolution = await runtime.resolve(action)
    assert resolution["accepted"] is True
    result = await runtime.act(action, run_id="run-1")
    assert result.status == "verified"
    assert result.post_scene == runtime.current_scene().scene_id
    assert [event["event_type"] for event in runtime.trace(result.trace_id)] == [
        "action.prepared",
        "target.resolved",
        "action.dispatched",
        "observation.created",
        "verification.completed",
        "transition.committed",
    ]
    await runtime.close()
    assert backend.opened is False
