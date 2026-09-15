"""One serialized device session and its evidence-backed scene history."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Literal

from haykal.artifacts import ArtifactStore
from haykal.contracts import (
    ActionResult,
    Expectation,
    ExpectationResult,
    ExtractionRequest,
    ExtractionResult,
    SemanticAction,
    SemanticScene,
)
from haykal.contracts.action import ResolutionPolicy
from haykal.contracts.extraction import ExtractedRecord, RecordAnchor
from haykal.contracts.selector import Selector
from haykal.device import DeviceBackend
from haykal.execution import ActionRunner
from haykal.execution.risk import ValidatedApproval
from haykal.extraction import ExtractionEngine, ExtractionPipeline
from haykal.perception import PerceptionAdapter, semantic_content_digest
from haykal.resolver import TargetResolver
from haykal.scene import ElementIdentityTracker, ObservationService, SceneBuilder
from haykal.scene.observer import ObservationCapture
from haykal.traces import TraceStore
from haykal.verification import ExpectationEvaluator, SceneFrame, VerificationService


class SceneNotFound(LookupError):
    """A requested scene is not retained by this session."""


class SessionClosed(RuntimeError):
    """An operation was attempted outside the session lifecycle."""


@dataclass(frozen=True, slots=True)
class _SceneRecord:
    scene: SemanticScene
    capture: ObservationCapture


class RuntimeSession:
    """Canonical primitive service; transports contain no device logic."""

    def __init__(
        self,
        *,
        session_id: str,
        backend: DeviceBackend,
        artifact_store: ArtifactStore,
        trace_store: TraceStore,
        ocr: PerceptionAdapter | None = None,
        vision: PerceptionAdapter | None = None,
        element_dictionary: dict[str, Selector] | None = None,
        retained_scenes: int = 100,
    ) -> None:
        if retained_scenes < 2:
            raise ValueError("retained_scenes must be at least two")
        self.session_id = session_id
        self._backend = backend
        self._artifact_store = artifact_store
        self._trace_store = trace_store
        self._observer = ObservationService(backend, artifact_store, session_id=session_id)
        self._builder = SceneBuilder(
            artifact_store,
            ocr=ocr,
            vision=vision,
            tracker=ElementIdentityTracker(),
        )
        dictionary = element_dictionary or {}
        self._dictionary = dict(dictionary)
        self._resolver = TargetResolver(element_dictionary=dictionary)
        self._extractor = ExtractionPipeline(
            self._builder,
            ExtractionEngine(
                artifact_store=artifact_store,
                element_dictionary=dictionary,
            ),
        )
        self._verifier = VerificationService(
            self,
            evaluator=ExpectationEvaluator(element_dictionary=dictionary),
        )
        self._runner = ActionRunner(backend, self._resolver, self._verifier, trace_store)
        self._records: dict[str, _SceneRecord] = {}
        self._revision_index: dict[int, str] = {}
        self._retained_scenes = retained_scenes
        self._current_scene_id: str | None = None
        self._lock = asyncio.Lock()
        self._opened = False

    async def configure_elements(self, element_dictionary: dict[str, Selector]) -> None:
        """Install the exact immutable skill dictionary before a run slice."""

        async with self._lock:
            self._dictionary = dict(element_dictionary)
            self._resolver = TargetResolver(element_dictionary=self._dictionary)
            self._extractor = ExtractionPipeline(
                self._builder,
                ExtractionEngine(
                    artifact_store=self._artifact_store,
                    element_dictionary=self._dictionary,
                ),
            )
            self._verifier = VerificationService(
                self,
                evaluator=ExpectationEvaluator(element_dictionary=self._dictionary),
            )
            self._runner = ActionRunner(
                self._backend,
                self._resolver,
                self._verifier,
                self._trace_store,
            )

    async def open(self) -> None:
        if self._opened:
            return
        await self._backend.open()
        self._opened = True

    async def close(self) -> None:
        if not self._opened:
            return
        try:
            await self._backend.close()
        finally:
            self._opened = False

    async def capture(self) -> SceneFrame:
        """Implement SceneFrameSource for bounded verification polling."""

        self._require_open()
        capture = await self._observer.capture()
        built = await self._builder.build(
            capture.observation,
            hierarchy_xml=capture.hierarchy_xml,
            screenshot_png=capture.screenshot_png,
        )
        self._remember(_SceneRecord(built.scene, capture))
        return SceneFrame(
            scene=built.scene,
            foreground_package=capture.observation.foreground.package,
            screenshot_png=capture.screenshot_png,
        )

    async def observe(self) -> SemanticScene:
        async with self._lock:
            return (await self.capture()).scene

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        async with self._lock:
            if request.scroll is not None:
                return await self._extract_scrolling(request)
            return await self._extract_once(request)

    async def _extract_once(self, request: ExtractionRequest) -> ExtractionResult:
        record = self._record(request.scene_id)
        result = await self._extractor.extract(
            request,
            observation=record.capture.observation,
            hierarchy_xml=record.capture.hierarchy_xml,
            screenshot_png=record.capture.screenshot_png,
            input_scene=record.scene,
        )
        if result.scene.scene_id != record.scene.scene_id:
            self._remember(_SceneRecord(result.scene, record.capture))
        return result.extraction

    async def _extract_scrolling(self, request: ExtractionRequest) -> ExtractionResult:
        assert request.scroll is not None
        input_scene = self._record(request.scene_id).scene
        records: list[ExtractedRecord] = []
        dropped: list[dict[str, object]] = []
        seen: set[str] = set()
        scenes: list[str] = []
        source_exhausted = False
        container_id: str | None = None
        started = time.monotonic()
        stop_reason: Literal[
            "end_of_list",
            "max_records",
            "max_pages",
            "max_ms",
            "no_new_records",
            "scene_unstable",
        ] = "max_pages"
        for page in range(request.scroll.max_pages):
            if (
                request.limits.max_ms is not None
                and (time.monotonic() - started) * 1000 >= request.limits.max_ms
            ):
                stop_reason = "max_ms"
                break
            current = self._record().scene
            one_page = request.model_copy(update={"scene_id": current.scene_id, "scroll": None})
            result = await self._extract_once(one_page)
            scenes.extend(result.scenes)
            dropped.extend(result.dropped_records)
            new_count = 0
            for item in result.records:
                signature = self._record_signature(request, item.fields)
                if signature in seen:
                    continue
                seen.add(signature)
                if item.anchor is not None:
                    checkpoint = item.anchor.scroll_checkpoint
                    item = item.model_copy(
                        update={
                            "anchor": item.anchor.model_copy(
                                update={
                                    "scroll_checkpoint": (
                                        checkpoint.model_copy(
                                            update={"page": page, "container": container_id}
                                        )
                                        if checkpoint is not None
                                        else None
                                    )
                                }
                            )
                        }
                    )
                records.append(item)
                new_count += 1
                if request.limits.max_records and len(records) >= request.limits.max_records:
                    stop_reason = "max_records"
                    break
            if stop_reason == "max_records":
                break
            if page > 0 and new_count == 0:
                stop_reason = "no_new_records"
                break
            if page + 1 >= request.scroll.max_pages:
                break
            decision = self._resolver.resolve_selector(
                request.scroll.within,
                self._record().scene,
                action_kind="swipe",
                policy=self._runner_policy(),
            )
            target = next(
                item.element
                for item in decision.ranked
                if item.element.id == decision.target.element_id
            )
            container_id = target.id
            x = (target.bounds.left + target.bounds.right) // 2
            height = target.bounds.bottom - target.bounds.top
            await self._backend.swipe(
                x,
                target.bounds.top + round(height * 0.8),
                x,
                target.bounds.top + round(height * 0.2),
                300,
            )
            settled = await self._capture_settled(
                stable_samples=request.scroll.settle.stable_samples,
                interval_ms=request.scroll.settle.interval_ms,
            )
            if not settled:
                stop_reason = "scene_unstable"
                break
        effective = self._record().scene
        payload = {
            "request": request.model_dump(mode="json"),
            "scenes": scenes,
            "records": [item.model_dump(mode="json") for item in records],
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ExtractionResult(
            extraction_id=f"ext_{digest[:20]}",
            input_scene_id=input_scene.scene_id,
            effective_scene_id=effective.scene_id,
            scenes=scenes or [input_scene.scene_id],
            request_satisfied=bool(records) and not dropped,
            source_exhausted=source_exhausted,
            truncated=stop_reason != "end_of_list",
            stop_reason=stop_reason,
            records=records,
            dropped_records=dropped,
        )

    async def _capture_settled(self, *, stable_samples: int, interval_ms: int) -> bool:
        previous: str | None = None
        stable = 0
        for _ in range(max(4, stable_samples * 4)):
            frame = await self.capture()
            digest = semantic_content_digest(frame.scene.elements)
            stable = stable + 1 if digest == previous else 1
            if stable >= stable_samples:
                return True
            previous = digest
            await asyncio.sleep(interval_ms / 1000)
        return False

    @staticmethod
    def _record_signature(request: ExtractionRequest, fields: dict[str, object | None]) -> str:
        names = request.dedupe_by or sorted(fields)
        payload = {name: fields.get(name) for name in names}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _runner_policy() -> ResolutionPolicy:
        return ResolutionPolicy()

    async def resolve(
        self,
        action: SemanticAction,
        *,
        record_anchors: dict[str, RecordAnchor] | None = None,
    ) -> dict[str, object]:
        async with self._lock:
            pre_scene = self._record().scene
            if action.target is None:
                assessment = self._runner.assess(action, pre_scene, None)
                return {
                    "accepted": True,
                    "target": None,
                    "ranked": [],
                    "risk": assessment.as_dict(),
                }
            source = self._source_scene(action, record_anchors)
            decision = self._resolver.resolve(
                action.target,
                pre_scene,
                action_kind=action.kind,
                policy=action.resolution,
                source_scene=source,
                record_anchors=record_anchors,
            )
            assessment = self._runner.assess(action, pre_scene, decision.target)
            return {
                "accepted": True,
                "target": decision.target.model_dump(mode="json"),
                "risk": assessment.as_dict(),
                "ranked": [
                    {
                        "element_id": item.element.id,
                        "score": item.score,
                        "reasons": list(item.reasons),
                        "bounds": item.element.bounds.model_dump(mode="json"),
                    }
                    for item in decision.ranked
                ],
            }

    async def act(
        self,
        action: SemanticAction,
        *,
        run_id: str | None = None,
        trace_id: str | None = None,
        approval: ValidatedApproval | None = None,
        record_anchors: dict[str, RecordAnchor] | None = None,
    ) -> ActionResult:
        async with self._lock:
            pre_scene = self._record().scene
            return await self._runner.execute(
                action,
                pre_scene,
                run_id=run_id,
                trace_id=trace_id,
                source_scene=self._source_scene(action, record_anchors),
                approval=approval,
                record_anchors=record_anchors,
            )

    async def verify(self, expectation: Expectation) -> ExpectationResult:
        async with self._lock:
            pre_scene = self._record().scene
            return (await self._verifier.verify(expectation, pre_scene=pre_scene)).result

    def trace(self, trace_id: str) -> list[dict[str, object]]:
        from haykal.hardening.privacy import RedactionPolicy, Redactor

        redactor = Redactor(RedactionPolicy())
        return [redactor.redact_event(event) for event in self._trace_store.read(trace_id)]

    def current_scene(self) -> SemanticScene:
        return self._record().scene

    def _source_scene(
        self,
        action: SemanticAction,
        record_anchors: dict[str, RecordAnchor] | None = None,
    ) -> SemanticScene | None:
        revision = action.target.scene_revision if action.target is not None else None
        if (
            revision is None
            and action.target is not None
            and action.target.record_anchor is not None
        ):
            anchor = (record_anchors or {}).get(action.target.record_anchor)
            revision = anchor.scene_revision if anchor is not None else None
        if revision is None:
            return None
        scene_id = self._revision_index.get(revision)
        return self._records[scene_id].scene if scene_id is not None else None

    def _record(self, scene_id: str | None = None) -> _SceneRecord:
        effective = scene_id or self._current_scene_id
        if effective is None or effective not in self._records:
            raise SceneNotFound("observe first or provide a retained scene_id")
        return self._records[effective]

    def _remember(self, record: _SceneRecord) -> None:
        self._records[record.scene.scene_id] = record
        self._revision_index[record.scene.revision] = record.scene.scene_id
        self._current_scene_id = record.scene.scene_id
        while len(self._records) > self._retained_scenes:
            oldest_id = next(iter(self._records))
            oldest = self._records.pop(oldest_id)
            if self._revision_index.get(oldest.scene.revision) == oldest_id:
                del self._revision_index[oldest.scene.revision]

    def _require_open(self) -> None:
        if not self._opened:
            raise SessionClosed(f"session {self.session_id!r} is closed")
