from __future__ import annotations

from pathlib import Path

import pytest

from haykal.contracts.action import ActionTarget, Risk, SemanticAction
from haykal.contracts.common import Bounds, SettlePolicy
from haykal.contracts.expectation import Expectation
from haykal.contracts.scene import (
    ElementFingerprint,
    ElementState,
    PropertyEvidence,
    SceneQuality,
    SemanticElement,
    SemanticScene,
)
from haykal.contracts.selector import Selector, TextMatch
from haykal.device import DeviceHealth, DeviceSnapshot
from haykal.device.single_shot import DispatchOutcome
from haykal.execution import ActionRunner
from haykal.resolver import TargetResolver
from haykal.traces import TraceStore
from haykal.verification import SceneFrame, VerificationService


class FakeBackend:
    def __init__(self, *, dispatch_status: str = "dispatched") -> None:
        self.calls: list[tuple[str, object]] = []
        self.dispatch_status = dispatch_status

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def health(self) -> DeviceHealth:
        return DeviceHealth(True, "fixture")

    async def snapshot(self) -> DeviceSnapshot:
        return DeviceSnapshot(400, 800, 2, 0, "dev.haykal", ".Main", False)

    async def hierarchy(self) -> str:
        return "<hierarchy/>"

    async def screenshot(self) -> bytes:
        return b"png"

    async def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", (x, y)))

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self.calls.append(("swipe", (x1, y1, x2, y2, duration_ms)))

    async def type_text(self, text: str, *, replace: bool) -> None:
        self.calls.append(("type_text", (text, replace)))

    async def press(self, key: str) -> None:
        self.calls.append(("press", key))

    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome:
        self.calls.append(("dispatch_once", (action_id, method, params)))
        return DispatchOutcome(action_id, self.dispatch_status, None, False)


class Frames:
    def __init__(self, frames: list[SceneFrame]) -> None:
        self.frames = frames
        self.calls = 0

    async def capture(self) -> SceneFrame:
        index = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        return self.frames[index]


class FailingFrames:
    async def capture(self) -> SceneFrame:
        raise TimeoutError("capture failed")


def _element(element_id: str, label: str, *, top: int = 0) -> SemanticElement:
    source = f"accessibility:{element_id}"
    return SemanticElement(
        id=element_id,
        role="button",
        label=label,
        label_normalized=label,
        bounds=Bounds(left=0, top=top, right=200, bottom=top + 100),
        state=ElementState(
            enabled=True,
            visible=True,
            focused=False,
            scrollable=False,
        ),
        actions=["tap", "input_text"],
        properties={
            "role": PropertyEvidence(confidence=0.98, sources=[source]),
            "label": PropertyEvidence(confidence=0.98, sources=[source]),
            "bounds": PropertyEvidence(confidence=0.99, sources=[source]),
            "state": PropertyEvidence(confidence=0.98, sources=[source]),
        },
        fingerprint=ElementFingerprint(text_key=label),
    )


def _scene(
    revision: int,
    label: str = "التالي",
    *,
    elements: list[SemanticElement] | None = None,
) -> SemanticScene:
    return SemanticScene(
        scene_id=f"scene-{revision}",
        session_id="session",
        revision=revision,
        digest="sha256:" + f"{revision:064x}",
        quality=SceneQuality(score=1, accessibility_coverage=1),
        elements=elements if elements is not None else [_element("button", label)],
    )


def _runner(
    tmp_path: Path,
    backend: FakeBackend,
    frames: Frames,
) -> tuple[ActionRunner, TraceStore]:
    traces = TraceStore(tmp_path / "trace.sqlite3")
    return (
        ActionRunner(
            backend,
            TargetResolver(),
            VerificationService(frames),
            traces,
        ),
        traces,
    )


@pytest.mark.asyncio
async def test_verified_tap_links_complete_trace(tmp_path: Path) -> None:
    backend = FakeBackend()
    frames = Frames(
        [
            SceneFrame(_scene(2, "تم"), "dev.haykal", b"png-1"),
            SceneFrame(_scene(3, "تم"), "dev.haykal", b"png-2"),
        ]
    )
    runner, traces = _runner(tmp_path, backend, frames)
    action = SemanticAction(
        action_id="tap-next",
        kind="tap",
        target=ActionTarget(selector=Selector(label=TextMatch(equals="التالي"))),
        expect=Expectation(
            visible=Selector(label=TextMatch(equals="تم")),
            settle=SettlePolicy(stable_samples=2, interval_ms=1),
            timeout_ms=100,
        ),
        risk=Risk(category="navigation", gate="none"),
    )

    result = await runner.execute(
        action,
        _scene(1),
        run_id="run",
        trace_id="trace",
    )

    assert result.status == "verified"
    assert backend.calls == [("tap", (100, 50))]
    assert result.resolved_target is not None
    assert result.post_scene == "scene-3"
    assert [event.event_type for event in traces.read("trace")] == [
        "action.prepared",
        "target.resolved",
        "action.dispatched",
        "observation.created",
        "verification.completed",
        "transition.committed",
    ]


@pytest.mark.asyncio
async def test_duplicate_target_abstains_before_dispatch(tmp_path: Path) -> None:
    backend = FakeBackend()
    runner, _ = _runner(
        tmp_path,
        backend,
        Frames([SceneFrame(_scene(2), "dev.haykal", b"png")]),
    )
    scene = _scene(
        1,
        elements=[_element("one", "إضافة"), _element("two", "إضافة", top=200)],
    )
    action = SemanticAction(
        action_id="ambiguous",
        kind="tap",
        target=ActionTarget(selector=Selector(label=TextMatch(equals="إضافة"))),
        risk=Risk(category="navigation", gate="none"),
    )

    result = await runner.execute(action, scene)

    assert result.status == "ambiguous"
    assert backend.calls == []


@pytest.mark.asyncio
async def test_sensitive_action_requires_approval(tmp_path: Path) -> None:
    backend = FakeBackend()
    runner, _ = _runner(
        tmp_path,
        backend,
        Frames([SceneFrame(_scene(2), "dev.haykal", b"png")]),
    )
    action = SemanticAction(
        action_id="purchase",
        kind="tap",
        target=ActionTarget(selector=Selector(label=TextMatch(equals="التالي"))),
        risk=Risk(category="purchase", gate="required"),
    )

    result = await runner.execute(action, _scene(1))

    assert result.status == "rejected"
    assert backend.calls == []


@pytest.mark.asyncio
async def test_irreversible_unknown_never_enters_verification(tmp_path: Path) -> None:
    backend = FakeBackend(dispatch_status="outcome_unknown")
    frames = Frames([SceneFrame(_scene(2), "dev.haykal", b"png")])
    runner, traces = _runner(tmp_path, backend, frames)
    action = SemanticAction(
        action_id="submit-once",
        kind="tap",
        target=ActionTarget(selector=Selector(label=TextMatch(equals="التالي"))),
        risk=Risk(category="submission", gate="required"),
    )

    result = await runner.execute(
        action,
        _scene(1),
        approved=True,
        run_id="run",
        trace_id="trace",
    )

    assert result.status == "outcome_unknown"
    assert frames.calls == 0
    assert len(backend.calls) == 1
    assert [event.event_type for event in traces.read("trace")][-1] == "run.outcome_unknown"


@pytest.mark.asyncio
async def test_arabic_input_uses_helper_ime_without_text_in_trace(tmp_path: Path) -> None:
    backend = FakeBackend()
    frames = Frames(
        [
            SceneFrame(_scene(2, "بحث"), "dev.haykal", b"png-1"),
            SceneFrame(_scene(3, "بحث"), "dev.haykal", b"png-2"),
        ]
    )
    runner, traces = _runner(tmp_path, backend, frames)
    action = SemanticAction(
        action_id="type-arabic",
        kind="input_text",
        target=ActionTarget(selector=Selector(label=TextMatch(equals="التالي"))),
        text="بيتزا",
        mode="replace",
        risk=Risk(category="navigation", gate="none"),
    )

    result = await runner.execute(
        action,
        _scene(1),
        run_id="run",
        trace_id="trace",
    )

    assert result.device_receipt is not None
    assert result.device_receipt.input_strategy == "helper_ime"
    assert backend.calls == [
        ("tap", (100, 50)),
        ("type_text", ("بيتزا", True)),
    ]
    encoded_trace = "".join(event.model_dump_json() for event in traces.read("trace"))
    assert "بيتزا" not in encoded_trace


@pytest.mark.asyncio
async def test_post_dispatch_failure_preserves_receipt(tmp_path: Path) -> None:
    backend = FakeBackend()
    traces = TraceStore(tmp_path / "trace.sqlite3")
    runner = ActionRunner(
        backend,
        TargetResolver(),
        VerificationService(FailingFrames()),
        traces,
    )
    action = SemanticAction(
        action_id="tap-then-observe-fails",
        kind="tap",
        target=ActionTarget(selector=Selector(label=TextMatch(equals="التالي"))),
        risk=Risk(category="navigation", gate="none"),
    )
    result = await runner.execute(action, _scene(1))
    assert result.status == "failed"
    assert result.device_receipt is not None
    assert result.device_receipt.dispatch_status == "dispatched"
