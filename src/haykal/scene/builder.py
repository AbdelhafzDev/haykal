"""Observation-to-scene orchestration with explicit fallback degradation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, replace

from haykal.artifacts.store import ArtifactStore
from haykal.contracts.observation import RawObservation
from haykal.contracts.scene import SceneQuality, SemanticScene
from haykal.perception.adapters import PerceptionAdapter
from haykal.perception.fusion import fuse_candidates, semantic_digest
from haykal.perception.hierarchy import parse_hierarchy
from haykal.perception.model import PerceptionCandidate, SourceKind
from haykal.perception.quality import QualityPolicy, QualityReport, assess_accessibility

from .tracker import ElementIdentityTracker, TrackingResult

DEFAULT_QUALITY_POLICY = QualityPolicy()


class ObservationIntegrityError(ValueError):
    """Supplied bytes do not match the observation artifact addresses."""


class ObservationIncoherent(ValueError):
    """Hierarchy and screenshot are too far apart for safe fusion."""


@dataclass(frozen=True, slots=True)
class SceneBuildResult:
    scene: SemanticScene
    accessibility_quality: QualityReport
    evidence_artifacts: tuple[str, ...]
    warnings: tuple[str, ...]
    tracking: TrackingResult | None = None


class SceneBuilder:
    def __init__(
        self,
        artifact_store: ArtifactStore,
        *,
        ocr: PerceptionAdapter | None = None,
        vision: PerceptionAdapter | None = None,
        quality_policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
        fallback_timeout_s: float = 30.0,
        tracker: ElementIdentityTracker | None = None,
        max_fallback_skew_ms: int = 500,
    ) -> None:
        if ocr is not None and ocr.source != "ocr":
            raise ValueError("ocr adapter must declare source=ocr")
        if vision is not None and vision.source != "vision":
            raise ValueError("vision adapter must declare source=vision")
        self._artifacts = artifact_store
        self._adapters = {adapter.source: adapter for adapter in (ocr, vision) if adapter}
        self._quality_policy = quality_policy
        self._fallback_timeout_s = fallback_timeout_s
        self._tracker = tracker
        self._max_fallback_skew_ms = max_fallback_skew_ms

    def has_adapter(self, source: SourceKind) -> bool:
        return source in self._adapters

    async def build(
        self,
        observation: RawObservation,
        *,
        hierarchy_xml: bytes,
        screenshot_png: bytes,
        target_queries: tuple[str, ...] = (),
        require_sources: tuple[SourceKind, ...] = ("accessibility",),
        scene_revision: int | None = None,
    ) -> SceneBuildResult:
        self._verify_raw(observation, hierarchy_xml, screenshot_png)
        accessibility = parse_hierarchy(hierarchy_xml)
        report = assess_accessibility(
            accessibility,
            target_queries=target_queries,
            require_sources=require_sources,
            policy=self._quality_policy,
        )
        candidates = list(accessibility)
        evidence_artifacts: list[str] = []
        warnings = [*observation.warnings, *report.warnings]
        available_fallbacks = tuple(
            source for source in report.required_fallbacks if source in self._adapters
        )
        if available_fallbacks and observation.capture_skew_ms > self._max_fallback_skew_ms:
            raise ObservationIncoherent(
                f"capture skew {observation.capture_skew_ms} ms exceeds "
                f"fallback limit {self._max_fallback_skew_ms} ms"
            )
        used: list[SourceKind] = []
        for source in report.required_fallbacks:
            adapter = self._adapters.get(source)
            if adapter is None:
                warnings.append(f"{source}_unavailable")
                continue
            try:
                detected = await asyncio.wait_for(
                    adapter.detect(
                        screenshot_png,
                        width=observation.display.width,
                        height=observation.display.height,
                    ),
                    timeout=self._fallback_timeout_s,
                )
            except TimeoutError:
                warnings.append(f"{source}_timeout")
                continue
            except Exception as exc:
                warnings.append(f"{source}_failed:{type(exc).__name__}")
                continue
            stored, addressed = self._store_adapter_output(adapter, detected)
            evidence_artifacts.append(stored)
            candidates.extend(addressed)
            used.append(source)
        elements = fuse_candidates(candidates)
        revision = observation.revision if scene_revision is None else scene_revision
        if revision < observation.revision:
            raise ValueError("scene revision cannot precede its observation revision")
        digest = semantic_digest(elements, revision=revision)
        scene = SemanticScene(
            scene_id=f"scn_{digest.removeprefix('sha256:')[:20]}",
            observation_id=observation.observation_id,
            session_id=observation.session_id,
            revision=revision,
            digest=digest,
            quality=SceneQuality(
                score=min(1.0, round(report.score + 0.08 * len(used), 6)),
                accessibility_coverage=report.accessibility_coverage,
                fallbacks_used=[source for source in used if source != "accessibility"],
            ),
            elements=elements,
        )
        tracking = self._tracker.track(scene) if self._tracker is not None else None
        if tracking is not None:
            scene = tracking.scene
        return SceneBuildResult(
            scene=scene,
            accessibility_quality=report,
            evidence_artifacts=tuple(evidence_artifacts),
            warnings=tuple(dict.fromkeys(warnings)),
            tracking=tracking,
        )

    def _verify_raw(
        self, observation: RawObservation, hierarchy_xml: bytes, screenshot_png: bytes
    ) -> None:
        if (
            observation.hierarchy.captured_at is not None
            and observation.screenshot.captured_at is not None
        ):
            measured = round(
                abs(
                    (
                        observation.screenshot.captured_at - observation.hierarchy.captured_at
                    ).total_seconds()
                    * 1000
                )
            )
            if abs(measured - observation.capture_skew_ms) > 2:
                raise ObservationIntegrityError(
                    "capture_skew_ms does not match evidence timestamps"
                )
        pairs = (
            (hierarchy_xml, observation.hierarchy.artifact, "hierarchy"),
            (screenshot_png, observation.screenshot.artifact, "screenshot"),
        )
        for data, expected, label in pairs:
            actual = self._artifacts.put(data)
            if actual.digest != expected:
                raise ObservationIntegrityError(
                    f"{label} digest mismatch: expected {expected}, got {actual.digest}"
                )

    def _store_adapter_output(
        self,
        adapter: PerceptionAdapter,
        candidates: list[PerceptionCandidate],
    ) -> tuple[str, list[PerceptionCandidate]]:
        payload = {
            "identity": asdict(adapter.identity),
            "source": adapter.source,
            "candidates": [
                {
                    "source_id": candidate.source_id,
                    "bounds": candidate.bounds.model_dump(mode="json"),
                    "role": candidate.role,
                    "label": candidate.label,
                    "text": candidate.text,
                    "resource_id": candidate.resource_id,
                    "state": candidate.state.model_dump(mode="json"),
                    "actions": candidate.actions,
                    "parent_source_id": candidate.parent_source_id,
                    "ancestry": candidate.ancestry,
                    "property_confidence": candidate.property_confidence,
                    "property_sources": candidate.property_sources,
                    "order": candidate.order,
                }
                for candidate in candidates
            ],
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        stored = self._artifacts.put(encoded)
        source_addresses = {
            candidate.source_id: f"{candidate.source}:{stored.digest}#{index}"
            for index, candidate in enumerate(candidates)
        }
        addressed = [
            replace(
                candidate,
                source_id=source_addresses[candidate.source_id],
                parent_source_id=(
                    source_addresses.get(candidate.parent_source_id, candidate.parent_source_id)
                    if candidate.parent_source_id is not None
                    else None
                ),
                property_sources={
                    name: tuple(source_addresses.get(source, source) for source in sources)
                    for name, sources in candidate.property_sources.items()
                },
            )
            for candidate in candidates
        ]
        return stored.digest, addressed
