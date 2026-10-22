from __future__ import annotations

from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.contracts.action import ActionTarget, Risk, SemanticAction
from haykal.contracts.common import Bounds, SettlePolicy
from haykal.contracts.expectation import Expectation
from haykal.contracts.scene import ElementState
from haykal.contracts.selector import ResourceMatch, Selector, TextMatch
from haykal.device import DeviceHealth, DeviceSnapshot
from haykal.device.single_shot import DispatchOutcome
from haykal.perception import AdapterIdentity, PerceptionCandidate, StaticPerceptionAdapter
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
        "risk.assessed",
        "action.dispatched",
        "observation.created",
        "verification.completed",
        "transition.committed",
    ]
    await runtime.close()
    assert backend.opened is False


@pytest.mark.asyncio
async def test_observe_can_explicitly_require_vision_without_changing_scene_contract(
    tmp_path: Path,
) -> None:
    backend = Backend()
    vision = StaticPerceptionAdapter(
        "vision",
        AdapterIdentity(
            name="fixture-vision",
            version="1",
            model_digest="sha256:" + "a" * 64,
        ),
        [
            PerceptionCandidate(
                source="vision",
                source_id="vision:offer",
                bounds=Bounds(left=220, top=20, right=390, bottom=120),
                role="button",
                label="عرض بيتزا",
                state=ElementState(
                    enabled=True,
                    visible=True,
                    focused=False,
                    scrollable=False,
                ),
                actions=("tap",),
            )
        ],
    )
    runtime = RuntimeSession(
        session_id="session",
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        trace_store=TraceStore(tmp_path / "trace.sqlite3"),
        vision=vision,
    )
    await runtime.open()
    scene = await runtime.observe(require_vision=True)
    await runtime.close()

    assert scene.quality.fallbacks_used == ["vision"]
    assert any(element.label == "عرض بيتزا" for element in scene.elements)


@pytest.mark.asyncio
async def test_missing_accessibility_target_triggers_vision_before_risk_assessment(
    tmp_path: Path,
) -> None:
    class RichBackend(Backend):
        async def hierarchy(self) -> str:
            return """<hierarchy rotation="0">
              <node index="0" text="التالي" resource-id="dev.haykal:id/next"
                class="android.widget.Button" package="dev.haykal" content-desc="التالي"
                clickable="true" enabled="true" scrollable="false" bounds="[10,20][210,120]" />
              <node index="1" text="رجوع" resource-id="dev.haykal:id/back"
                class="android.widget.Button" package="dev.haykal" content-desc="رجوع"
                clickable="true" enabled="true" scrollable="false" bounds="[10,140][210,240]" />
            </hierarchy>"""

    vision = StaticPerceptionAdapter(
        "vision",
        AdapterIdentity(
            name="fixture-vision",
            version="1",
            model_digest="sha256:" + "a" * 64,
        ),
        [
            PerceptionCandidate(
                source="vision",
                source_id="vision:offer",
                bounds=Bounds(left=220, top=20, right=390, bottom=120),
                role="button",
                label="ادفع",
                state=ElementState(
                    enabled=True,
                    visible=True,
                    focused=False,
                    scrollable=False,
                ),
                actions=("tap",),
            )
        ],
    )
    runtime = RuntimeSession(
        session_id="session",
        backend=RichBackend(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        trace_store=TraceStore(tmp_path / "trace.sqlite3"),
        vision=vision,
    )
    await runtime.open()
    initial = await runtime.observe()
    assert initial.quality.fallbacks_used == []
    decision = await runtime.resolve(
        SemanticAction(
            action_id="resolve-offer",
            kind="tap",
            target=ActionTarget(selector=Selector(label=TextMatch(equals="ادفع"))),
            risk=Risk(category="navigation", gate="none"),
        )
    )
    await runtime.close()

    assert decision["accepted"] is True
    assert runtime.current_scene().quality.fallbacks_used == ["vision"]
    assert decision["risk"]["effective"]["category"] == "purchase"
    assert decision["risk"]["policy_decision"] == "approval_required"
