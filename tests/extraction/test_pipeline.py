from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.contracts.common import Bounds
from haykal.contracts.extraction import ExtractionField, ExtractionGroup, ExtractionRequest
from haykal.contracts.observation import (
    CaptureEvidence,
    Display,
    ForegroundApp,
    KeyboardState,
    RawObservation,
)
from haykal.contracts.selector import Selector, TextMatch
from haykal.extraction import ExtractionEngine, ExtractionPipeline
from haykal.perception import AdapterIdentity, PerceptionCandidate, StaticPerceptionAdapter
from haykal.scene import SceneBuilder

DIGEST = "sha256:" + "c" * 64


def _observation(store: ArtifactStore, hierarchy: bytes, screenshot: bytes) -> RawObservation:
    now = datetime.now(UTC)
    return RawObservation(
        observation_id="obs_extract",
        session_id="session",
        revision=1,
        display=Display(width=400, height=800, density=2.0, rotation=0),
        foreground=ForegroundApp(package="dev.haykal"),
        keyboard=KeyboardState(visible=False),
        hierarchy=CaptureEvidence(
            artifact=store.put(hierarchy).digest,
            captured_at=now,
            backend="fixture",
        ),
        screenshot=CaptureEvidence(
            artifact=store.put(screenshot).digest,
            media_type="image/png",
            captured_at=now,
            backend="fixture",
        ),
        capture_skew_ms=0,
    )


@pytest.mark.asyncio
async def test_pipeline_enriches_only_when_required_source_is_missing(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    hierarchy = b"<hierarchy/>"
    screenshot = b"recorded-image"
    observation = _observation(store, hierarchy, screenshot)
    initial = await SceneBuilder(store).build(
        observation,
        hierarchy_xml=hierarchy,
        screenshot_png=screenshot,
    )
    ocr = StaticPerceptionAdapter(
        "ocr",
        AdapterIdentity(name="fixture-ocr", version="1", model_digest=DIGEST),
        [
            PerceptionCandidate(
                source="ocr",
                source_id="ocr:fixture#offer",
                bounds=Bounds(left=10, top=10, right=300, bottom=80),
                role="text",
                text="عرض اليوم",
                property_confidence={"text": 0.95, "bounds": 0.95},
            )
        ],
    )
    request = ExtractionRequest(
        scene_id=initial.scene.scene_id,
        require_sources=["ocr"],
        group=ExtractionGroup(by="single"),
        fields={
            "offer": ExtractionField(
                selector=Selector(text=TextMatch(equals="عرض اليوم")),
                type="text",
                required=True,
            )
        },
    )
    pipeline = ExtractionPipeline(SceneBuilder(store, ocr=ocr), ExtractionEngine())

    enriched = await pipeline.extract(
        request,
        observation=observation,
        hierarchy_xml=hierarchy,
        screenshot_png=screenshot,
        input_scene=initial.scene,
    )

    assert enriched.enrichment is not None
    assert enriched.scene.revision == initial.scene.revision + 1
    assert enriched.scene.quality.fallbacks_used == ["ocr"]
    assert enriched.extraction.input_scene_id == initial.scene.scene_id
    assert enriched.extraction.effective_scene_id == enriched.scene.scene_id
    assert enriched.extraction.records[0].fields["offer"] == {
        "raw": "عرض اليوم",
        "normalized": "عرض اليوم",
    }
    assert enriched.extraction.records[0].evidence["offer"] is not None

    direct = await pipeline.extract(
        request.model_copy(update={"scene_id": enriched.scene.scene_id}),
        observation=observation,
        hierarchy_xml=hierarchy,
        screenshot_png=screenshot,
        input_scene=enriched.scene,
    )
    assert direct.enrichment is None
    assert direct.scene is enriched.scene
