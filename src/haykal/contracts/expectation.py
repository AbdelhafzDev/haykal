"""Recursive, bounded expectation contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, PositiveInt, SchemaVersion, SettlePolicy
from .selector import Selector


class TextPredicate(ContractModel):
    target: Selector | None = None
    value: str


class StatePredicate(ContractModel):
    target: Selector
    state: Literal["enabled", "focused", "checked", "selected", "scrollable"]
    value: bool


class ValuePredicate(ContractModel):
    target: Selector
    type: Literal["number", "money", "rating", "duration"]
    value: object


class Expectation(ContractModel):
    schema_version: SchemaVersion = "1.0"
    timeout_ms: PositiveInt | None = None
    settle: SettlePolicy | None = None
    all_: list[Expectation] | None = Field(default=None, alias="all", min_length=1)
    any_: list[Expectation] | None = Field(default=None, alias="any", min_length=1)
    not_: Expectation | None = Field(default=None, alias="not")
    visible: Selector | None = None
    not_visible: Selector | None = None
    text_equals: TextPredicate | str | None = None
    text_contains: TextPredicate | str | None = None
    state_equals: StatePredicate | None = None
    value_equals: ValuePredicate | None = None
    foreground_package: str | None = None
    scene_changed: bool | None = None
    scene_stable: bool | None = None

    @model_validator(mode="after")
    def exactly_one_predicate(self) -> Expectation:
        predicates = (
            self.all_,
            self.any_,
            self.not_,
            self.visible,
            self.not_visible,
            self.text_equals,
            self.text_contains,
            self.state_equals,
            self.value_equals,
            self.foreground_package,
            self.scene_changed,
            self.scene_stable,
        )
        if sum(value is not None for value in predicates) != 1:
            raise ValueError("expectation requires exactly one predicate")
        return self


Expectation.model_rebuild()


class ExpectationResult(ContractModel):
    schema_version: SchemaVersion = "1.0"
    status: Literal["passed", "failed", "inconclusive"]
    scene_ids: list[str] = Field(min_length=1)
    evidence: list[dict[str, object]] = Field(default_factory=list)
    elapsed_ms: int = Field(ge=0)
