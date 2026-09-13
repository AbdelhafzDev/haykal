from __future__ import annotations

import pytest

from haykal.contracts.common import SettlePolicy
from haykal.contracts.expectation import Expectation
from haykal.verification import SceneFrame, VerificationService

from .test_evaluator import _scene


class Frames:
    def __init__(self, frames: list[SceneFrame]) -> None:
        self.frames = frames
        self.calls = 0

    async def capture(self) -> SceneFrame:
        index = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        return self.frames[index]


@pytest.mark.asyncio
async def test_verify_waits_for_two_equal_semantic_samples() -> None:
    changed_one = SceneFrame(_scene(2, label="تم"), "dev.haykal", b"png-1")
    changed_two = SceneFrame(_scene(3, label="تم"), "dev.haykal", b"png-2")
    frames = Frames([changed_one, changed_two])
    service = VerificationService(frames)

    outcome = await service.verify(
        Expectation(
            visible={"label": {"equals": "تم"}},
            timeout_ms=100,
            settle=SettlePolicy(stable_samples=2, interval_ms=1),
        ),
        pre_scene=_scene(1),
    )

    assert outcome.result.status == "passed"
    assert outcome.frame.scene.scene_id == "scene-3"
    assert frames.calls == 2


@pytest.mark.asyncio
async def test_verify_returns_failed_after_bounded_timeout() -> None:
    frames = Frames([SceneFrame(_scene(2), "dev.haykal", b"png")])
    outcome = await VerificationService(frames).verify(
        Expectation(
            visible={"label": {"equals": "لن يظهر"}},
            timeout_ms=2,
            settle=SettlePolicy(stable_samples=1, interval_ms=1),
        )
    )

    assert outcome.result.status == "failed"
    assert frames.calls >= 2
