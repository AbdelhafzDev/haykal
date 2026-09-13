"""Durable skill-run, escalation, and approval contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .action import SemanticAction
from .common import ContractModel, NonNegativeInt, SchemaVersion
from .expectation import Expectation
from .extraction import ExtractedRecord

RunStatus = Literal[
    "running",
    "needs_decision",
    "approval_required",
    "suspended",
    "completed",
    "completed_reconciled",
    "prepared",
    "failed",
    "cancelled",
    "outcome_unknown",
]


class RunRequest(ContractModel):
    schema_version: SchemaVersion = "1.0"
    session_id: str = Field(min_length=1)
    skill: str = Field(pattern=r"^[a-z0-9_.-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    inputs: dict[str, object] = Field(default_factory=dict)


class RunSnapshot(ContractModel):
    schema_version: SchemaVersion = "1.0"
    run_id: str
    trace_id: str
    session_id: str
    skill: str
    skill_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    state: str
    status: RunStatus
    inputs_echo: dict[str, object] = Field(default_factory=dict)
    outputs: dict[str, object] = Field(default_factory=dict)
    pending: dict[str, object] | None = None
    steps: NonNegativeInt = 0
    decisions: NonNegativeInt = 0
    gates: NonNegativeInt = 0
    created_at: datetime
    updated_at: datetime


class DecisionResponse(ContractModel):
    select_record: str | None = None
    select_transition: str | None = None
    action: SemanticAction | None = None
    expect: Expectation | None = None
    cancel: bool | None = None

    @model_validator(mode="after")
    def exactly_one_response(self) -> DecisionResponse:
        forms = (
            self.select_record is not None,
            self.select_transition is not None,
            self.action is not None,
            self.cancel is True,
        )
        if sum(forms) != 1:
            raise ValueError("decision requires exactly one response")
        if self.expect is not None and self.action is None:
            raise ValueError("expect is only valid with action")
        return self


class ApprovalChallenge(ContractModel):
    schema_version: SchemaVersion = "1.0"
    gate_id: str
    run_id: str
    skill_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    action_intent_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    target_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    material: dict[str, object]
    material_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_scene_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expires_at: datetime
    nonce: str


class ApprovalGrantRequest(ContractModel):
    gate_id: str
    challenge: ApprovalChallenge

    @model_validator(mode="after")
    def matching_gate(self) -> ApprovalGrantRequest:
        if self.gate_id != self.challenge.gate_id:
            raise ValueError("gate_id does not match challenge")
        return self


class ApprovalGrant(ContractModel):
    gate_id: str
    token: str
    expires_at: datetime


class CandidatePatch(ContractModel):
    schema_version: SchemaVersion = "1.0"
    patch_id: str
    run_id: str
    skill_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    state: str
    reason: str
    decision: DecisionResponse
    scene_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime
    promoted: Literal[False] = False


class SelectionResult(ContractModel):
    status: Literal["selected", "empty", "margin"]
    selected: ExtractedRecord | None = None
    candidates: list[ExtractedRecord] = Field(default_factory=list)
    excluded_null: NonNegativeInt = 0
