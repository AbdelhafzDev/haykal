"""Live observe-to-scene smoke evidence."""

from __future__ import annotations

from pathlib import Path

from haykal.artifacts import ArtifactStore
from haykal.device import Uiautomator2Backend
from haykal.scene import ElementIdentityTracker, ObservationService, SceneBuilder


async def run_scene_smoke(
    *,
    serial: str,
    artifact_root: Path,
    session_id: str = "m2-smoke",
    timeout_s: float = 15.0,
) -> dict[str, object]:
    backend = Uiautomator2Backend.from_serial(serial, operation_timeout_s=timeout_s)
    store = ArtifactStore(artifact_root)
    await backend.open()
    try:
        observer = ObservationService(
            backend,
            store,
            session_id=session_id,
        )
        builder = SceneBuilder(
            store,
            tracker=ElementIdentityTracker(),
        )
        first_capture = await observer.capture()
        first = await builder.build(
            first_capture.observation,
            hierarchy_xml=first_capture.hierarchy_xml,
            screenshot_png=first_capture.screenshot_png,
        )
        capture = await observer.capture()
        result = await builder.build(
            capture.observation,
            hierarchy_xml=capture.hierarchy_xml,
            screenshot_png=capture.screenshot_png,
        )
        if result.tracking is None:
            raise RuntimeError("scene smoke requires identity tracking")
        return {
            "schema_version": "1.0",
            "status": "passed",
            "observation": capture.observation.model_dump(mode="json"),
            "scene": result.scene.model_dump(mode="json"),
            "quality_detail": {
                "actionable_count": result.accessibility_quality.actionable_count,
                "labelled_actionable_ratio": (
                    result.accessibility_quality.labelled_actionable_ratio
                ),
                "query_coverage": result.accessibility_quality.query_coverage,
            },
            "identity_detail": {
                "first_scene_id": first.scene.scene_id,
                "matched": len(result.tracking.matches),
                "new": len(result.tracking.new_ids),
                "ambiguous": len(result.tracking.ambiguous_temporary_ids),
                "expired": len(result.tracking.expired_ids),
            },
            "evidence_artifacts": result.evidence_artifacts,
            "warnings": result.warnings,
        }
    finally:
        await backend.close()
