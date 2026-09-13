"""Semantic action and action-result contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .common import Confidence, ContractModel, NonNegativeInt, SchemaVersion
from .expectation import Expectation
from .selector import Selector


class ActionTarget(ContractModel):
    scene_revision: NonNegativeInt | None = None
    element_id: str | None = None
    selector: Selector | None = None
    record_anchor: str | None = None
    description: str | None = None
    coordinates: tuple[int, int] | None = None

    @model_validator(mode="after")
    def one_target_form(self) -> ActionTarget:
        forms = (
            self.element_id is not None,
            self.selector is not None,
            self.record_anchor is not None,
            self.coordinates is not None,
        )
        if sum(forms) != 1:
            raise ValueError("action target requires exactly one target form")
        if self.element_id is not None and self.scene_revision is None:
            raise ValueError("element target requires scene_revision")
        if self.coordinates is not None and (self.scene_revision is None or not self.description):
            raise ValueError("coordinate target requires scene_revision and description")
        return self


class ResolutionPolicy(ContractModel):
    minimum_score: Confidence = 0.80
    ambiguity_margin: Confidence = 0.10


class Risk(ContractModel):
    category: Literal[
        "navigation",
        "purchase",
        "transfer",
        "submission",
        "deletion",
        "permission",
        "credential",
        "communication",
        "unknown",
    ]
    gate: Literal["required", "policy", "none"] = "policy"


class SemanticAction(ContractModel):
    schema_version: SchemaVersion = "1.0"
    action_id: str = Field(min_length=1)
    kind: Literal["tap", "swipe", "input_text", "press_key", "wait"]
    target: ActionTarget | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    distance_ratio: float | None = Field(default=None, gt=0, le=1)
    within: Selector | None = None
    text: str | None = None
    mode: Literal["replace", "append"] | None = None
    key: Literal["back", "home", "enter", "search"] | None = None
    wait_ms: int | None = Field(default=None, gt=0, le=60_000)
    expect: Expectation | None = None
    resolution: ResolutionPolicy = Field(default_factory=ResolutionPolicy)
    risk: Risk

    @model_validator(mode="after")
    def kind_fields(self) -> SemanticAction:
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


class ResolvedTarget(ContractModel):
    element_id: str
    point: tuple[int, int]
    score: Confidence
    scene_revision: NonNegativeInt | None = None
    stale_rebound: bool = False
    dictionary_expansion: dict[str, object] | None = None
    alternatives: list[dict[str, object]] = Field(default_factory=list)


class DeviceReceipt(ContractModel):
    backend: str
    accepted: bool
    input_strategy: Literal["accessibility_set_text", "helper_ime", "clipboard_paste"] | None = None
    method: str | None = None
    parameters_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    dispatch_status: Literal["dispatched", "outcome_unknown"] | None = None
    repeated_request: bool = False


class VerificationSummary(ContractModel):
    status: Literal["passed", "failed", "inconclusive"]
    evidence: list[dict[str, object]] = Field(default_factory=list)


class ActionResult(ContractModel):
    schema_version: SchemaVersion = "1.0"
    action_id: str
    status: Literal[
        "verified", "executed_unverified", "rejected", "ambiguous", "failed", "outcome_unknown"
    ]
    attempts: NonNegativeInt
    started_at: datetime
    completed_at: datetime
    pre_scene: str
    post_scene: str | None = None
    resolved_target: ResolvedTarget | None = None
    device_receipt: DeviceReceipt | None = None
    verification: VerificationSummary | None = None
    trace_id: str
