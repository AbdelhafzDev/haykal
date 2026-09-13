"""On-demand scene enrichment followed by deterministic extraction."""

from __future__ import annotations

from dataclasses import dataclass

from haykal.contracts.extraction import ExtractionRequest, ExtractionResult
from haykal.contracts.observation import RawObservation
from haykal.contracts.scene import SemanticScene
from haykal.scene import SceneBuilder, SceneBuildResult

from .engine import ExtractionContextMismatch, ExtractionEngine, MissingRequiredSource


@dataclass(frozen=True, slots=True)
class ExtractionPipelineResult:
    scene: SemanticScene
    extraction: ExtractionResult
    enrichment: SceneBuildResult | None


class ExtractionPipeline:
    def __init__(self, builder: SceneBuilder, engine: ExtractionEngine) -> None:
        self._builder = builder
        self._engine = engine

    async def extract(
        self,
        request: ExtractionRequest,
        *,
        observation: RawObservation,
        hierarchy_xml: bytes,
        screenshot_png: bytes,
        input_scene: SemanticScene | None = None,
    ) -> ExtractionPipelineResult:
        if input_scene is None and request.scene_id is not None:
            raise ExtractionContextMismatch(
                "a request naming scene_id requires the matching input_scene"
            )
        if input_scene is not None:
            if request.scene_id is not None and request.scene_id != input_scene.scene_id:
                raise ExtractionContextMismatch(
                    f"request scene {request.scene_id!r} does not match {input_scene.scene_id!r}"
                )
            if input_scene.observation_id not in {None, observation.observation_id}:
                raise ExtractionContextMismatch(
                    "input scene and raw observation do not share an observation"
                )
            direct_request = request.model_copy(update={"scene_id": input_scene.scene_id})
            try:
                extraction = self._engine.extract_scene(
                    direct_request,
                    input_scene,
                    screenshot_png=screenshot_png,
                )
            except MissingRequiredSource:
                pass
            else:
                return ExtractionPipelineResult(input_scene, extraction, None)

        revision = input_scene.revision + 1 if input_scene is not None else None
        enrichment = await self._builder.build(
            observation,
            hierarchy_xml=hierarchy_xml,
            screenshot_png=screenshot_png,
            require_sources=tuple(request.require_sources),
            scene_revision=revision,
        )
        effective_request = request.model_copy(update={"scene_id": enrichment.scene.scene_id})
        extraction = self._engine.extract_scene(
            effective_request,
            enrichment.scene,
            screenshot_png=screenshot_png,
        )
        if input_scene is not None:
            extraction = extraction.model_copy(update={"input_scene_id": input_scene.scene_id})
        return ExtractionPipelineResult(enrichment.scene, extraction, enrichment)
