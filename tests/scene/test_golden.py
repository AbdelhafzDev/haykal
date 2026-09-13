from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.contracts.observation import (
    CaptureEvidence,
    Display,
    ForegroundApp,
    KeyboardState,
    RawObservation,
)
from haykal.scene import SceneBuilder

ROOT = Path(__file__).parents[2]


@pytest.mark.asyncio
async def test_basic_rtl_hierarchy_matches_committed_golden_scene(tmp_path: Path) -> None:
    hierarchy = (ROOT / "fixtures/perception/basic-rtl.xml").read_bytes()
    screenshot = b"fixture-image"
    store = ArtifactStore(tmp_path / "artifacts")
    now = datetime.now(UTC)
    observation = RawObservation(
        observation_id="obs_golden",
        session_id="ses_golden",
        revision=7,
        display=Display(width=1080, height=2400, density=2.75, rotation=0),
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
    result = await SceneBuilder(store).build(
        observation,
        hierarchy_xml=hierarchy,
        screenshot_png=screenshot,
    )
    projection = {
        "digest": result.scene.digest,
        "quality": result.scene.quality.model_dump(mode="json"),
        "elements": [
            [
                element.id,
                element.role,
                element.label,
                element.text,
                element.resource_id,
                element.parent,
            ]
            for element in result.scene.elements
        ],
    }
    expected = json.loads(
        (ROOT / "fixtures/scene/basic-rtl.expected.json").read_text(encoding="utf-8")
    )

    assert result.warnings == ()
    assert projection == expected
