from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from haykal.contracts.action import ActionTarget, Risk, RiskCategory, SemanticAction
from haykal.contracts.selector import Selector
from haykal.execution import RiskClassifier

RISK_ORDER: dict[RiskCategory, int] = {
    "navigation": 0,
    "credential": 1,
    "permission": 2,
    "communication": 3,
    "submission": 4,
    "purchase": 5,
    "transfer": 6,
    "deletion": 7,
    "unknown": 8,
}
RISK_CATEGORIES = list(RISK_ORDER)


def _action(category: RiskCategory, *, semantic_name: str = "continue") -> SemanticAction:
    return SemanticAction(
        action_id="risk-property",
        kind="tap",
        target=ActionTarget(selector=Selector(semantic_name=semantic_name)),
        risk=Risk(category=category, gate="none"),
    )


@given(
    action_risk=st.sampled_from(RISK_CATEGORIES),
    caller_floor=st.sampled_from(RISK_CATEGORIES),
)
def test_effective_risk_is_monotonic(action_risk: RiskCategory, caller_floor: RiskCategory) -> None:
    effective = RiskClassifier().classify(_action(action_risk), declared=caller_floor)

    assert RISK_ORDER[effective] >= RISK_ORDER[action_risk]
    assert RISK_ORDER[effective] >= RISK_ORDER[caller_floor]


def test_highest_detected_semantic_risk_wins() -> None:
    action = _action("navigation")

    assert (
        RiskClassifier().classify(action, target_context="confirm transfer and delete account")
        == "deletion"
    )


def test_opening_checkout_review_is_not_the_purchase_commit() -> None:
    action = _action("navigation", semantic_name="checkout_button")

    assert (
        RiskClassifier().classify(action, target_context="متابعة إلى الدفع checkout_button")
        == "navigation"
    )


def test_raw_coordinates_are_always_unknown() -> None:
    action = _action("navigation").model_copy(
        update={
            "target": ActionTarget(
                coordinates=(20, 30),
                scene_revision=1,
                description="harmless according to caller",
            )
        }
    )

    assert RiskClassifier().classify(action) == "unknown"
