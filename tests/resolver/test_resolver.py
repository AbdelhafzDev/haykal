from __future__ import annotations

import pytest

from haykal.contracts.action import ActionTarget, ResolutionPolicy
from haykal.contracts.common import Bounds
from haykal.contracts.scene import (
    ElementFingerprint,
    ElementState,
    PropertyEvidence,
    SceneQuality,
    SemanticElement,
    SemanticScene,
)
from haykal.contracts.selector import Selector, TextMatch
from haykal.resolver import AmbiguousTarget, TargetNotFound, TargetResolver


def _element(
    element_id: str,
    *,
    role: str = "button",
    label: str | None = None,
    text: str | None = None,
    parent: str | None = None,
    top: int = 0,
    actions: list[str] | None = None,
    resource_id: str | None = None,
) -> SemanticElement:
    source = f"accessibility:{element_id}"
    properties = {
        "role": PropertyEvidence(confidence=0.98, sources=[source]),
        "bounds": PropertyEvidence(confidence=0.99, sources=[source]),
        "state": PropertyEvidence(confidence=0.98, sources=[source]),
    }
    if label:
        properties["label"] = PropertyEvidence(confidence=0.96, sources=[source])
    if text:
        properties["text"] = PropertyEvidence(confidence=0.96, sources=[source])
    if resource_id:
        properties["resource_id"] = PropertyEvidence(confidence=1, sources=[source])
    return SemanticElement.model_validate(
        {
            "id": element_id,
            "role": role,
            "label": label,
            "label_normalized": label,
            "text": text,
            "text_normalized": text,
            "resource_id": resource_id,
            "bounds": Bounds(left=0, top=top, right=300, bottom=top + 100),
            "state": ElementState(
                enabled=True,
                visible=True,
                focused=False,
                scrollable=False,
            ),
            "actions": actions if actions is not None else ["tap"],
            "parent": parent,
            "properties": properties,
            "fingerprint": ElementFingerprint(
                resource_id=resource_id,
                ancestry=["root"],
                text_key=label or text,
            ),
        }
    )


def _scene(revision: int, elements: list[SemanticElement]) -> SemanticScene:
    return SemanticScene(
        scene_id=f"scene-{revision}",
        session_id="session",
        revision=revision,
        digest="sha256:" + f"{revision:064x}",
        quality=SceneQuality(score=1, accessibility_coverage=1),
        elements=elements,
    )


def test_selector_promotes_text_child_to_actionable_ancestor() -> None:
    scene = _scene(
        1,
        [
            _element("button", label=None, actions=["tap"]),
            _element(
                "text",
                role="text",
                text="اطلب الآن",
                parent="button",
                actions=[],
            ),
        ],
    )

    decision = TargetResolver().resolve(
        ActionTarget(selector=Selector(text=TextMatch(equals="اطلب الآن"))),
        scene,
        action_kind="tap",
        policy=ResolutionPolicy(),
    )

    assert decision.target.element_id == "button"
    assert decision.target.point == (150, 50)
    assert "actionable_ancestor_of=text" in decision.ranked[0].reasons


def test_duplicate_targets_abstain_with_ranked_alternatives() -> None:
    scene = _scene(
        1,
        [
            _element("one", label="إضافة", top=0),
            _element("two", label="إضافة", top=200),
        ],
    )

    with pytest.raises(AmbiguousTarget) as caught:
        TargetResolver().resolve(
            ActionTarget(selector=Selector(label=TextMatch(equals="إضافة"))),
            scene,
            action_kind="tap",
            policy=ResolutionPolicy(),
        )

    assert [item["element_id"] for item in caught.value.alternatives] == ["one", "two"]


def test_stale_stable_id_rebinds_but_incompatible_element_fails() -> None:
    resolver = TargetResolver()
    current = _scene(2, [_element("stable", label="التالي")])

    decision = resolver.resolve(
        ActionTarget(element_id="stable", scene_revision=1),
        current,
        action_kind="tap",
        policy=ResolutionPolicy(),
    )
    assert decision.target.stale_rebound is True

    with pytest.raises(TargetNotFound):
        resolver.resolve(
            ActionTarget(element_id="stable", scene_revision=2),
            _scene(2, [_element("stable", label="التالي", actions=[])]),
            action_kind="tap",
            policy=ResolutionPolicy(),
        )


def test_stale_anchor_prefers_one_exact_resource_across_large_scroll_shift() -> None:
    source = _scene(1, [_element("old", top=100, resource_id="result_9")])
    current = _scene(
        2,
        [
            _element("new", top=800, resource_id="result_9"),
            _element("other", top=200, resource_id="result_10"),
        ],
    )

    decision = TargetResolver().resolve(
        ActionTarget(element_id="old", scene_revision=1),
        current,
        action_kind="tap",
        policy=ResolutionPolicy(),
        source_scene=source,
    )

    assert decision.target.element_id == "new"
    assert decision.target.stale_rebound is True
    assert decision.ranked[0].reasons == ("unique_resource_id",)
