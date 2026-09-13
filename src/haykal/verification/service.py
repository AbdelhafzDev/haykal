"""Bounded semantic settling and expectation verification."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

from haykal.contracts.common import SettlePolicy
from haykal.contracts.expectation import Expectation, ExpectationResult
from haykal.contracts.scene import SemanticScene
from haykal.perception import semantic_content_digest
from haykal.scene import ObservationService, SceneBuilder

from .evaluator import ExpectationEvaluator


@dataclass(frozen=True, slots=True)
class SceneFrame:
    scene: SemanticScene
    foreground_package: str
    screenshot_png: bytes


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    result: ExpectationResult
    frame: SceneFrame


class SceneFrameSource(Protocol):
    async def capture(self) -> SceneFrame: ...


class ObservationFrameSource:
    def __init__(self, observer: ObservationService, builder: SceneBuilder) -> None:
        self._observer = observer
        self._builder = builder

    async def capture(self) -> SceneFrame:
        capture = await self._observer.capture()
        built = await self._builder.build(
            capture.observation,
            hierarchy_xml=capture.hierarchy_xml,
            screenshot_png=capture.screenshot_png,
        )
        return SceneFrame(
            built.scene,
            capture.observation.foreground.package,
            capture.screenshot_png,
        )


class VerificationService:
    def __init__(
        self,
        source: SceneFrameSource,
        *,
        evaluator: ExpectationEvaluator | None = None,
    ) -> None:
        self._source = source
        self._evaluator = evaluator or ExpectationEvaluator()

    async def verify(
        self,
        expectation: Expectation,
        *,
        pre_scene: SemanticScene | None = None,
    ) -> VerificationOutcome:
        return await self._sample(
            expectation,
            pre_scene=pre_scene,
            settle=expectation.settle or SettlePolicy(),
            timeout_ms=expectation.timeout_ms or 5_000,
        )

    async def settle(
        self,
        *,
        pre_scene: SemanticScene | None = None,
        settle: SettlePolicy | None = None,
        timeout_ms: int = 5_000,
    ) -> VerificationOutcome:
        return await self._sample(
            None,
            pre_scene=pre_scene,
            settle=settle or SettlePolicy(),
            timeout_ms=timeout_ms,
        )

    async def _sample(
        self,
        expectation: Expectation | None,
        *,
        pre_scene: SemanticScene | None,
        settle: SettlePolicy,
        timeout_ms: int,
    ) -> VerificationOutcome:
        started = time.monotonic()
        stable_samples = 0
        prior_digest: str | None = None
        latest: SceneFrame | None = None
        latest_result: ExpectationResult | None = None
        while True:
            latest = await self._source.capture()
            digest = semantic_content_digest(latest.scene.elements)
            stable_samples = stable_samples + 1 if digest == prior_digest else 1
            prior_digest = digest
            stable = stable_samples >= settle.stable_samples
            elapsed_ms = round((time.monotonic() - started) * 1000)
            if expectation is None:
                latest_result = ExpectationResult(
                    status="passed" if stable else "failed",
                    scene_ids=[latest.scene.scene_id],
                    evidence=[{"predicate": "scene_stable", "actual": stable}],
                    elapsed_ms=elapsed_ms,
                )
            else:
                latest_result = self._evaluator.evaluate(
                    expectation,
                    latest.scene,
                    pre_scene=pre_scene,
                    foreground_package=latest.foreground_package,
                    scene_stable=stable,
                    elapsed_ms=elapsed_ms,
                )
            if stable and latest_result.status == "passed":
                return VerificationOutcome(latest_result, latest)
            if elapsed_ms >= timeout_ms:
                timed_out = latest_result.model_copy(
                    update={
                        "status": (
                            "inconclusive" if latest_result.status == "inconclusive" else "failed"
                        ),
                        "elapsed_ms": elapsed_ms,
                    }
                )
                return VerificationOutcome(timed_out, latest)
            await asyncio.sleep(settle.interval_ms / 1000)
