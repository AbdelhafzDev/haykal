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
from haykal.contracts.selector import Near, ResourceMatch, Selector, TextMatch
from haykal.selectors import SelectorEvaluationError, SelectorEvaluator


def _element(
    element_id: str,
    *,
    role: str,
    label: str,
    bounds: Bounds,
    parent: str | None = None,
    resource_id: str | None = None,
) -> SemanticElement:
    source = f"accessibility:{element_id}"
    return SemanticElement.model_validate(
        {
            "id": element_id,
            "role": role,
            "label": label,
            "label_normalized": label,
            "resource_id": resource_id,
            "bounds": bounds,
            "state": ElementState(
                enabled=True,
                visible=True,
                focused=False,
                scrollable=role == "list",
            ),
            "actions": ["scroll"] if role == "list" else ["tap"],
            "parent": parent,
            "properties": {"label": PropertyEvidence(confidence=1, sources=[source])},
            "fingerprint": ElementFingerprint(text_key=label),
        }
    )


def _scene() -> SemanticScene:
    return SemanticScene(
        scene_id="scene",
        session_id="session",
        revision=4,
        digest="sha256:" + "0" * 64,
        quality=SceneQuality(score=1, accessibility_coverage=1),
        elements=[
            _element(
                "list",
                role="list",
                label="النتائج",
                bounds=Bounds(left=0, top=0, right=600, bottom=900),
                resource_id="app:id/results",
            ),
            _element(
                "title",
                role="text",
                label="بيتزا مارغريتا",
                bounds=Bounds(left=300, top=100, right=580, bottom=180),
                parent="list",
            ),
            _element(
                "price",
                role="text",
                label="٣٩٫٩٥ ر.س",  # noqa: RUF001
                bounds=Bounds(left=300, top=200, right=580, bottom=280),
                parent="list",
            ),
        ],
    )


def test_semantic_expansion_within_and_arabic_matching() -> None:
    scene = _scene()
    evaluator = SelectorEvaluator(
        scene,
        element_dictionary={
            "results": Selector(role="list", resource_id=ResourceMatch(ends_with="id/results"))
        },
    )
    selector = Selector(
        role="text",
        label=TextMatch(similar="بيتزا مارغريته", threshold=0.85),
        within=Selector(semantic_name="results"),
    )

    matches = evaluator.resolve(selector)
    assert [match.element.id for match in matches] == ["title"]


def test_near_position_and_scene_revision_are_enforced() -> None:
    evaluator = SelectorEvaluator(_scene())
    near_title = Selector(
        role="text",
        position="first",
        near=Near(
            selector=Selector(label=TextMatch(contains="بيتزا")),
            direction="below",
            max_px=150,
        ),
    )
    assert [match.element.id for match in evaluator.resolve(near_title)] == ["price"]
    assert evaluator.resolve(Selector(element_id="price", scene_revision=3)) == []
    assert evaluator.resolve(Selector(element_id="price", scene_revision=4))[0].element.id == (
        "price"
    )


def test_unsafe_regex_is_rejected() -> None:
    evaluator = SelectorEvaluator(_scene())
    with pytest.raises(SelectorEvaluationError, match="length budget"):
        evaluator.resolve(Selector(label=TextMatch(regex="x" * 257)))
