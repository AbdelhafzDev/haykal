"""Runtime-owned effective-risk assessment and approval binding."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import ClassVar, Literal

from haykal.contracts.action import ResolvedTarget, Risk, RiskCategory, SemanticAction
from haykal.contracts.scene import SemanticElement, SemanticScene


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return " ".join(unicodedata.normalize("NFKC", value).split())
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def canonical_digest(value: object, *, normalize_text: bool = False) -> str:
    effective = _normalize(value) if normalize_text else value
    encoded = json.dumps(
        effective,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def action_intent_digest(action: SemanticAction) -> str:
    return canonical_digest(action.model_dump(mode="json", exclude={"action_id"}))


def resolved_target_fingerprint(scene: SemanticScene, target: ResolvedTarget | None) -> str:
    element = _resolved_element(scene, target)
    material: object = element.fingerprint.model_dump(mode="json") if element else target
    return canonical_digest(material)


def _resolved_element(
    scene: SemanticScene, target: ResolvedTarget | None
) -> SemanticElement | None:
    if target is None or target.element_id.startswith("coordinate:"):
        return None
    return next((item for item in scene.elements if item.id == target.element_id), None)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    declared: Risk
    inferred: RiskCategory
    effective: Risk
    policy_decision: Literal["allow", "approval_required"]

    def as_dict(self) -> dict[str, object]:
        return {
            "declared": self.declared.model_dump(mode="json"),
            "inferred": self.inferred,
            "effective": self.effective.model_dump(mode="json"),
            "policy_decision": self.policy_decision,
        }


@dataclass(frozen=True, slots=True)
class ValidatedApproval:
    """Internal capability produced only after a bound approval token is consumed."""

    gate_id: str
    action_intent_digest: str
    target_fingerprint: str
    effective_risk: RiskCategory


class RiskClassifier:
    """Compute a conservative risk floor that untrusted declarations cannot lower."""

    _ORDER: ClassVar[dict[str, int]] = {
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
    _PURCHASE: ClassVar[tuple[str, ...]] = (
        "place_order",
        "place order",
        "buy",
        "purchase",
        "pay",
        "إتمام الطلب",
        "اتمام الطلب",
        "تأكيد الطلب",
        "ادفع",
    )
    _TRANSFER: ClassVar[tuple[str, ...]] = (
        "transfer",
        "send_money",
        "send money",
        "تحويل",
        "إرسال المال",
        "ارسال المال",
    )
    _DELETION: ClassVar[tuple[str, ...]] = (
        "delete",
        "remove_account",
        "remove account",
        "حذف",
    )
    _CREDENTIAL: ClassVar[tuple[str, ...]] = (
        "password",
        "passcode",
        "otp",
        "pin",
        "كلمة المرور",
        "رمز التحقق",
        "الرقم السري",
    )
    _PERMISSION: ClassVar[tuple[str, ...]] = (
        "allow permission",
        "grant permission",
        "السماح",
        "إذن",
        "اذن",
    )
    _COMMUNICATION: ClassVar[tuple[str, ...]] = (
        "send message",
        "publish",
        "post comment",
        "إرسال الرسالة",
        "ارسال الرسالة",
        "نشر",
    )
    _SUBMISSION: ClassVar[tuple[str, ...]] = (
        "submit",
        "confirm",
        "save changes",
        "إرسال",
        "ارسال",
        "تأكيد",
        "حفظ التغييرات",
    )

    def assess(
        self,
        action: SemanticAction,
        scene: SemanticScene,
        target: ResolvedTarget | None,
        declared: RiskCategory | None = None,
    ) -> RiskAssessment:
        element = _resolved_element(scene, target)
        target_context = " ".join(
            value
            for value in (
                element.label if element else None,
                element.text if element else None,
                element.resource_id if element else None,
            )
            if value
        )
        inferred = self.infer(action, target_context=target_context)
        candidates = [inferred, action.risk.category]
        if declared is not None:
            candidates.append(declared)
        effective_category = max(candidates, key=self._ORDER.__getitem__)
        gate_required = effective_category != "navigation" or action.risk.gate == "required"
        effective = Risk(
            category=effective_category,
            gate="required" if gate_required else "none",
        )
        return RiskAssessment(
            declared=action.risk,
            inferred=inferred,
            effective=effective,
            policy_decision="approval_required" if gate_required else "allow",
        )

    def classify(
        self,
        action: SemanticAction,
        declared: RiskCategory | None = None,
        *,
        target_context: str = "",
    ) -> RiskCategory:
        inferred = self.infer(action, target_context=target_context)
        candidates = [inferred, action.risk.category]
        if declared is not None:
            candidates.append(declared)
        return max(candidates, key=self._ORDER.__getitem__)

    def infer(self, action: SemanticAction, *, target_context: str = "") -> RiskCategory:
        semantic = ""
        if action.target and action.target.selector:
            semantic = action.target.selector.semantic_name or ""
        name = f"{semantic} {target_context}".casefold()
        if action.target is not None and action.target.coordinates is not None:
            return "unknown"
        candidates: list[RiskCategory] = ["navigation"]
        if action.kind == "input_text" and any(term in name for term in self._CREDENTIAL):
            candidates.append("credential")
        if any(term in name for term in self._PERMISSION):
            candidates.append("permission")
        if any(term in name for term in self._COMMUNICATION):
            candidates.append("communication")
        if any(term in name for term in self._SUBMISSION):
            candidates.append("submission")
        if any(term in name for term in self._PURCHASE):
            candidates.append("purchase")
        if any(term in name for term in self._TRANSFER):
            candidates.append("transfer")
        if any(term in name for term in self._DELETION):
            candidates.append("deletion")
        return max(candidates, key=self._ORDER.__getitem__)


def validate_approval(
    approval: ValidatedApproval | None,
    action: SemanticAction,
    scene: SemanticScene,
    target: ResolvedTarget | None,
    assessment: RiskAssessment,
) -> bool:
    if approval is None:
        return False
    return (
        approval.action_intent_digest == action_intent_digest(action)
        and approval.target_fingerprint == resolved_target_fingerprint(scene, target)
        and approval.effective_risk == assessment.effective.category
    )
