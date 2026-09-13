from __future__ import annotations

from haykal.contracts.common import Bounds
from haykal.contracts.expectation import (
    Expectation,
    StatePredicate,
    TextPredicate,
    ValuePredicate,
)
from haykal.contracts.scene import (
    ElementFingerprint,
    ElementState,
    PropertyEvidence,
    SceneQuality,
    SemanticElement,
    SemanticScene,
)
from haykal.contracts.selector import Selector, TextMatch
from haykal.verification import ExpectationEvaluator


def _scene(revision: int, *, label: str = "التالي", enabled: bool = True) -> SemanticScene:
    source = "accessibility:node_1"
    element = SemanticElement(
        id="button",
        role="button",
        label=label,
        label_normalized=label,
        bounds=Bounds(left=0, top=0, right=200, bottom=100),
        state=ElementState(
            enabled=enabled,
            visible=True,
            focused=False,
            scrollable=False,
        ),
        actions=["tap"],
        properties={
            "role": PropertyEvidence(confidence=1, sources=[source]),
            "label": PropertyEvidence(confidence=1, sources=[source]),
            "bounds": PropertyEvidence(confidence=1, sources=[source]),
            "state": PropertyEvidence(confidence=1, sources=[source]),
        },
        fingerprint=ElementFingerprint(text_key=label),
    )
    return SemanticScene(
        scene_id=f"scene-{revision}",
        session_id="session",
        revision=revision,
        digest="sha256:" + f"{revision:064x}",
        quality=SceneQuality(score=1, accessibility_coverage=1),
        elements=[element],
    )


def test_recursive_text_state_foreground_and_change_expectations() -> None:
    scene = _scene(2, label="الإجمالي ٣٩ ر.س")
    selector = Selector(label=TextMatch(contains="الإجمالي"))
    expectation = Expectation.model_validate(
        {
            "all": [
                {"visible": selector.model_dump(mode="json")},
                {
                    "text_contains": TextPredicate(target=selector, value="٣٩ ر.س").model_dump(
                        mode="json"
                    )
                },
                {
                    "state_equals": StatePredicate(
                        target=selector, state="enabled", value=True
                    ).model_dump(mode="json")
                },
                {
                    "value_equals": ValuePredicate(
                        target=selector,
                        type="money",
                        value={"amount": 39, "currency": "SAR"},
                    ).model_dump(mode="json")
                },
                {"foreground_package": "dev.haykal"},
                {"scene_changed": True},
            ]
        }
    )

    result = ExpectationEvaluator().evaluate(
        expectation,
        scene,
        pre_scene=_scene(1),
        foreground_package="dev.haykal",
        scene_stable=True,
    )

    assert result.status == "passed"
    assert {item["predicate"] for item in result.evidence} >= {
        "visible",
        "text_contains",
        "state_equals",
        "value_equals",
        "foreground_package",
        "scene_changed",
    }


def test_not_and_any_use_three_valued_logic() -> None:
    missing = Selector(label=TextMatch(equals="غير موجود"))
    expectation = Expectation.model_validate(
        {
            "any": [
                {"foreground_package": "dev.other"},
                {"not": {"visible": missing.model_dump(mode="json")}},
            ]
        }
    )

    result = ExpectationEvaluator().evaluate(
        expectation,
        _scene(1),
        foreground_package=None,
    )

    assert result.status == "passed"


def test_scene_context_is_inconclusive_when_not_supplied() -> None:
    result = ExpectationEvaluator().evaluate(
        Expectation(scene_changed=True),
        _scene(1),
    )
    assert result.status == "inconclusive"
