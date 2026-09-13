from __future__ import annotations

import pytest

from haykal.contracts.common import Bounds
from haykal.contracts.scene import (
    ElementFingerprint,
    ElementState,
    PropertyEvidence,
    SceneQuality,
    SemanticElement,
    SemanticScene,
)
from haykal.scene.tracker import ElementIdentityTracker, SceneRevisionError


def _element(
    temporary_id: str,
    *,
    resource_id: str | None,
    text: str,
    top: int,
    evidence_source: str | None = None,
) -> SemanticElement:
    source = evidence_source or f"accessibility:{temporary_id}"
    return SemanticElement(
        id=temporary_id,
        role="button",
        label=text,
        label_normalized=text,
        resource_id=resource_id,
        bounds=Bounds(left=0, top=top, right=300, bottom=top + 100),
        state=ElementState(
            enabled=True,
            visible=True,
            focused=False,
            scrollable=False,
        ),
        actions=["tap"],
        properties={
            "role": PropertyEvidence(confidence=1, sources=[source]),
            "label": PropertyEvidence(confidence=1, sources=[source]),
            "bounds": PropertyEvidence(confidence=1, sources=[source]),
        },
        fingerprint=ElementFingerprint(
            resource_id=resource_id,
            ancestry=["results"],
            text_key=text,
        ),
    )


def _scene(revision: int, elements: list[SemanticElement]) -> SemanticScene:
    return SemanticScene(
        scene_id=f"temporary_{revision}",
        session_id="session",
        revision=revision,
        digest="sha256:" + "0" * 64,
        quality=SceneQuality(score=1, accessibility_coverage=1),
        elements=elements,
    )


def test_resource_identity_survives_movement_and_reordering() -> None:
    tracker = ElementIdentityTracker()
    first = tracker.track(
        _scene(
            1,
            [
                _element("a", resource_id="id/pizza", text="بيتزا", top=100),
                _element("b", resource_id="id/burger", text="برجر", top=300),
            ],
        )
    )
    second = tracker.track(
        _scene(
            2,
            [
                _element("c", resource_id="id/burger", text="برجر", top=100),
                _element("d", resource_id="id/pizza", text="بيتزا", top=300),
            ],
        )
    )

    first_ids = {item.resource_id: item.id for item in first.scene.elements}
    second_ids = {item.resource_id: item.id for item in second.scene.elements}
    assert first_ids == second_ids
    assert len(second.matches) == 2
    assert second.expired_ids == ()


def test_ambiguous_identity_abstains_and_allocates_new_id() -> None:
    tracker = ElementIdentityTracker()
    tracker.track(
        _scene(
            1,
            [
                _element("a", resource_id=None, text="عرض", top=100),
                _element("b", resource_id=None, text="عرض", top=100),
            ],
        )
    )
    result = tracker.track(_scene(2, [_element("current", resource_id=None, text="عرض", top=100)]))

    assert result.matches == ()
    assert result.ambiguous_temporary_ids == ("current",)
    assert result.scene.elements[0].id in result.new_ids


def test_revision_must_increase_within_session() -> None:
    tracker = ElementIdentityTracker()
    tracker.track(_scene(2, []))
    with pytest.raises(SceneRevisionError):
        tracker.track(_scene(2, []))


def test_anonymous_structural_node_uses_raw_continuity_with_geometry() -> None:
    tracker = ElementIdentityTracker()
    first = tracker.track(
        _scene(
            1,
            [
                _element(
                    "temporary-a",
                    resource_id=None,
                    text="",
                    top=100,
                    evidence_source="accessibility:node_17",
                )
            ],
        )
    )
    second = tracker.track(
        _scene(
            2,
            [
                _element(
                    "temporary-b",
                    resource_id=None,
                    text="",
                    top=100,
                    evidence_source="accessibility:node_17",
                )
            ],
        )
    )

    assert second.scene.elements[0].id == first.scene.elements[0].id
    assert len(second.matches) == 1
