from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.contracts.common import Bounds
from haykal.contracts.observation import (
    CaptureEvidence,
    Display,
    ForegroundApp,
    KeyboardState,
    RawObservation,
)
from haykal.perception.adapters import AdapterIdentity, StaticPerceptionAdapter
from haykal.perception.model import PerceptionCandidate
from haykal.scene.builder import ObservationIntegrityError, SceneBuilder

ROOT = Path(__file__).parents[2]
DIGEST = "sha256:" + "b" * 64


def _observation(
    store: ArtifactStore,
    hierarchy: bytes,
    screenshot: bytes,
    *,
    skew_ms: int = 0,
) -> RawObservation:
    now = datetime.now(UTC)
    return RawObservation(
        observation_id="obs_1",
        session_id="ses_1",
        revision=1,
        display=Display(width=1080, height=2400, density=2.75, rotation=0),
        foreground=ForegroundApp(package="dev.haykal", activity=".MainActivity"),
        keyboard=KeyboardState(visible=False),
        hierarchy=CaptureEvidence(
            artifact=store.put(hierarchy).digest,
            captured_at=now,
            backend="uiautomator2",
        ),
        screenshot=CaptureEvidence(
            artifact=store.put(screenshot).digest,
            media_type="image/png",
            captured_at=now + timedelta(milliseconds=skew_ms),
            backend="uiautomator2",
        ),
        capture_skew_ms=skew_ms,
    )


@pytest.mark.asyncio
async def test_scene_is_deterministic_and_fallback_output_is_immutable(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    hierarchy = b"<hierarchy rotation='0'/>"
    screenshot = b"recorded-png"
    observation = _observation(store, hierarchy, screenshot)
    ocr = StaticPerceptionAdapter(
        "ocr",
        AdapterIdentity(name="fixture-ocr", version="1", model_digest=DIGEST),
        [
            PerceptionCandidate(
                source="ocr",
                source_id="ocr:raw#0",
                bounds=Bounds(left=10, top=10, right=300, bottom=80),
                role="text",
                text="بيتزا ٣٩ ر.س",
                property_confidence={"text": 0.9, "bounds": 0.9},
                property_sources={"text": ("ocr:raw#0",)},
            )
        ],
    )
    builder = SceneBuilder(store, ocr=ocr)

    first = await builder.build(
        observation,
        hierarchy_xml=hierarchy,
        screenshot_png=screenshot,
    )
    second = await builder.build(
        observation,
        hierarchy_xml=hierarchy,
        screenshot_png=screenshot,
    )

    assert first.scene == second.scene
    assert first.scene.quality.fallbacks_used == ["ocr"]
    assert first.evidence_artifacts == second.evidence_artifacts
    assert store.contains(first.evidence_artifacts[0])
    assert (
        first.scene.elements[0]
        .properties["text"]
        .sources[0]
        .startswith(f"ocr:{first.evidence_artifacts[0]}#")
    )
    assert "vision_unavailable" in first.warnings


@pytest.mark.asyncio
async def test_scene_rejects_bytes_that_do_not_match_observation(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    hierarchy = (ROOT / "fixtures/perception/basic-rtl.xml").read_bytes()
    observation = _observation(store, hierarchy, b"png")

    with pytest.raises(ObservationIntegrityError, match="hierarchy digest mismatch"):
        await SceneBuilder(store).build(
            observation,
            hierarchy_xml=b"<hierarchy/>",
            screenshot_png=b"png",
        )


@pytest.mark.asyncio
async def test_fallback_rejects_incoherent_capture(tmp_path: Path) -> None:
    from haykal.scene import ObservationIncoherent

    store = ArtifactStore(tmp_path / "artifacts")
    hierarchy = b"<hierarchy/>"
    observation = _observation(store, hierarchy, b"png", skew_ms=501)

    ocr = StaticPerceptionAdapter(
        "ocr",
        AdapterIdentity(name="fixture-ocr", version="1", model_digest=DIGEST),
        [],
    )

    with pytest.raises(ObservationIncoherent, match="capture skew"):
        await SceneBuilder(store, ocr=ocr).build(
            observation,
            hierarchy_xml=hierarchy,
            screenshot_png=b"png",
        )


@pytest.mark.asyncio
async def test_incoherent_screenshot_is_not_fused_without_an_adapter(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    hierarchy = b"<hierarchy/>"
    observation = _observation(store, hierarchy, b"png", skew_ms=501)

    result = await SceneBuilder(store).build(
        observation,
        hierarchy_xml=hierarchy,
        screenshot_png=b"png",
    )

    assert result.scene.quality.fallbacks_used == []
    assert "ocr_unavailable" in result.warnings
    assert "vision_unavailable" in result.warnings
