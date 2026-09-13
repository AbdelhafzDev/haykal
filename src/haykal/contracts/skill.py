"""Guarded skill contract and cross-reference validation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, SchemaVersion
from .expectation import Expectation
from .extraction import ExtractionRequest
from .selector import Selector, semantic_references, validate_element_dictionary


class SkillMetadata(ContractModel):
    name: str = Field(pattern=r"^[a-z0-9_.-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    package: str = Field(min_length=1)
    app_versions: str = Field(min_length=1)
    locales: list[str] = Field(min_length=1)
    content_digest: str | None = None
    publisher: str | None = None
    signature: str | None = None


class SkillInput(ContractModel):
    type: Literal[
        "string",
        "integer",
        "number",
        "boolean",
        "enum",
        "money",
        "secret_ref",
        "saved_ref",
        "object",
    ]
    required: bool = True
    default: object | None = None
    min: float | None = None
    max: float | None = None
    min_length: int | None = Field(default=None, ge=0)
    values: list[str] | None = None
    currency: str | None = None
    namespace: str | None = None
    fields: dict[str, SkillInput] | None = None


SkillInput.model_rebuild()


class ExtractionStep(ExtractionRequest):
    as_: str = Field(alias="as", pattern=r"^[a-z][a-z0-9_]*$")


EscalationReason = Literal[
    "unexpected_state",
    "unrecognized_screen",
    "selection_margin",
    "selection_empty",
    "option_unavailable",
    "checkout_mismatch",
    "location_unavailable",
    "security_challenge",
    "ambiguous_target",
    "extraction_ambiguous_field",
    "material_choice_required",
]


class Escalation(ContractModel):
    reason: EscalationReason
    allowed_actions: list[Literal["tap", "swipe", "press_key", "input_text", "wait", "cancel"]]


class SelectionPredicate(ContractModel):
    field: str = Field(min_length=1)
    op: Literal["==", "!=", "<", "<=", ">", ">=", "in", "contains"]
    value: object


class SelectionOrder(ContractModel):
    field: str = Field(min_length=1)
    direction: Literal["asc", "desc"]


class SelectionMargin(ContractModel):
    field: str = Field(min_length=1)
    min_gap: float = Field(ge=0)


class SelectionPolicy(ContractModel):
    from_: str = Field(alias="from", pattern=r"^[a-z][a-z0-9_]*$")
    where: list[SelectionPredicate] = Field(default_factory=list)
    order_by: list[SelectionOrder] = Field(min_length=1)
    margin: SelectionMargin | None = None
    as_: str = Field(alias="as", pattern=r"^[a-z][a-z0-9_]*$")


class FieldReconcile(ContractModel):
    field: str = Field(min_length=1)
    op: Literal["==", "!=", "<", "<=", ">", ">=", "in", "contains"]
    value: object
    tolerance: float | None = Field(default=None, ge=0)


class SumReconcile(ContractModel):
    check: Literal["sum_matches"]
    parts: list[str] = Field(min_length=1)
    signs: list[Literal["+", "-"]] = Field(min_length=1)
    total: str = Field(min_length=1)
    tolerance: float = Field(default=0.01, ge=0)

    @model_validator(mode="after")
    def matching_signs(self) -> SumReconcile:
        if len(self.parts) != len(self.signs):
            raise ValueError("sum_matches requires one sign per part")
        return self


ReconcileCheck = FieldReconcile | SumReconcile


class Transition(ContractModel):
    next: str | None = None
    terminal: str | None = None
    escalate: Escalation | None = None

    @model_validator(mode="after")
    def exactly_one_destination(self) -> Transition:
        if sum(value is not None for value in (self.next, self.terminal, self.escalate)) != 1:
            raise ValueError("transition requires exactly one destination")
        return self


class Branch(Transition):
    when: Expectation | None = None
    otherwise: bool | None = None

    @model_validator(mode="after")
    def exactly_one_guard(self) -> Branch:
        if (self.when is None) == (self.otherwise is None):
            raise ValueError("branch requires exactly one of when or otherwise")
        if self.otherwise is False:
            raise ValueError("otherwise may only be true")
        return self


class Gate(ContractModel):
    category: Literal[
        "purchase",
        "transfer",
        "submission",
        "deletion",
        "permission",
        "credential",
        "communication",
        "unknown",
    ]
    material: dict[str, object]
    require: list[dict[str, object]] = Field(default_factory=list)


class SkillRecordAnchor(ContractModel):
    record_anchor: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class SkillAction(ContractModel):
    kind: Literal["tap", "swipe", "input_text", "press_key", "wait"]
    target: Selector | SkillRecordAnchor | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    distance_ratio: float | None = Field(default=None, gt=0, le=1)
    within: Selector | None = None
    text: str | None = None
    mode: Literal["replace", "append"] | None = None
    key: Literal["back", "home", "enter", "search"] | None = None
    wait_ms: int | None = Field(default=None, gt=0, le=60_000)

    @model_validator(mode="after")
    def kind_fields(self) -> SkillAction:
        if self.kind in {"tap", "input_text"} and self.target is None:
            raise ValueError(f"{self.kind} requires target")
        if self.kind == "input_text" and (self.text is None or self.mode is None):
            raise ValueError("input_text requires text and mode")
        if self.kind == "swipe" and (self.direction is None or self.distance_ratio is None):
            raise ValueError("swipe requires direction and distance_ratio")
        if self.kind == "press_key" and self.key is None:
            raise ValueError("press_key requires key")
        if self.kind == "wait" and self.wait_ms is None:
            raise ValueError("wait requires wait_ms")
        return self


class SkillState(ContractModel):
    expect: Expectation | None = None
    extract: ExtractionStep | None = None
    select: SelectionPolicy | None = None
    reconcile: list[ReconcileCheck] | None = None
    on_reconcile_failure: Transition | None = None
    gate: Gate | None = None
    action: SkillAction | None = None
    retry: Literal["none"] | dict[str, object] | None = None
    verify: Expectation | None = None
    on_action_uncertain: Transition | None = None
    on_verify_timeout: Transition | None = None
    on_verify_failure: Transition | None = None
    branches: list[Branch] | None = None
    next: str | None = None
    terminal: str | None = None
    escalate: Escalation | None = None

    @model_validator(mode="after")
    def state_invariants(self) -> SkillState:
        endings = (self.branches, self.next, self.terminal, self.escalate)
        if sum(value is not None for value in endings) != 1:
            raise ValueError("state requires exactly one normal destination")
        if self.gate is not None and self.action is None:
            raise ValueError("gate and governed action must be in the same state")
        if self.gate is not None and (self.retry != "none" or self.on_action_uncertain is None):
            raise ValueError("gated action requires retry=none and on_action_uncertain")
        return self


class Skill(ContractModel):
    schema_version: SchemaVersion = "1.0"
    kind: Literal["skill"] = "skill"
    metadata: SkillMetadata
    inputs: dict[str, SkillInput] = Field(default_factory=dict)
    elements: dict[str, Selector]
    start: str
    states: dict[str, SkillState] = Field(min_length=1)

    @model_validator(mode="after")
    def cross_references(self) -> Skill:
        if self.start not in self.states:
            raise ValueError(f"start state {self.start!r} is undefined")
        validate_element_dictionary(self.elements)
        state_names = self.states.keys()
        for state_name, state in self.states.items():
            destinations = [state.next]
            destinations.extend(branch.next for branch in state.branches or [])
            for transition in (
                state.on_reconcile_failure,
                state.on_action_uncertain,
                state.on_verify_timeout,
                state.on_verify_failure,
            ):
                if transition:
                    destinations.append(transition.next)
            unknown = {
                name for name in destinations if name is not None and name not in state_names
            }
            if unknown:
                raise ValueError(
                    f"state {state_name!r} references unknown states: {', '.join(sorted(unknown))}"
                )
            selectors = _state_selectors(state)
            referenced = set().union(*(semantic_references(selector) for selector in selectors))
            missing = referenced - self.elements.keys()
            if missing:
                raise ValueError(
                    f"state {state_name!r} uses undefined semantic names: "
                    f"{', '.join(sorted(missing))}"
                )
            if state.select is not None:
                extraction_names = {
                    candidate.extract.as_
                    for candidate in self.states.values()
                    if candidate.extract is not None
                }
                if state.select.from_ not in extraction_names:
                    raise ValueError(
                        f"state {state_name!r} selects undefined extraction {state.select.from_!r}"
                    )
        return self


def _state_selectors(state: SkillState) -> list[Selector]:
    selectors: list[Selector] = []
    if state.action and isinstance(state.action.target, Selector):
        selectors.append(state.action.target)
    if state.action and state.action.within:
        selectors.append(state.action.within)
    if state.extract:
        if state.extract.group.root:
            selectors.append(state.extract.group.root)
        if state.extract.group.record:
            selectors.append(state.extract.group.record)
        selectors.extend(field.selector for field in state.extract.fields.values())
        if state.extract.scroll:
            selectors.append(state.extract.scroll.within)
    return selectors
