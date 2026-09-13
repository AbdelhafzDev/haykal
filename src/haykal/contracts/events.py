"""Runtime event, trace, and run-result envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ContractModel, NonNegativeInt, SchemaVersion

EventType = Literal[
    "run.started",
    "device.lease_acquired",
    "observation.created",
    "extraction.completed",
    "target.resolved",
    "action.prepared",
    "action.dispatched",
    "verification.completed",
    "transition.committed",
    "run.needs_decision",
    "run.approval_required",
    "run.approval_stale",
    "run.resumed",
    "run.suspended",
    "run.completed",
    "run.completed_reconciled",
    "run.outcome_unknown",
    "run.failed",
    "run.cancelled",
    "device.lease_released",
]


class RedactionRecord(ContractModel):
    policy: str
    applied: bool


class RuntimeEvent(ContractModel):
    schema_version: SchemaVersion = "1.0"
    run_id: str
    sequence: NonNegativeInt
    event_type: EventType
    occurred_at: datetime
    payload: dict[str, object] = Field(default_factory=dict)


class TraceEnvelope(RuntimeEvent):
    trace_id: str
    artifacts: list[str] = Field(default_factory=list)
    redaction: RedactionRecord


class RunStats(ContractModel):
    steps: NonNegativeInt
    model_calls: NonNegativeInt = 0
    decisions: NonNegativeInt
    gates: NonNegativeInt
    duration_s: float = Field(ge=0)


class RunResult(ContractModel):
    schema_version: SchemaVersion = "1.0"
    run_id: str
    status: Literal[
        "completed", "completed_reconciled", "prepared", "failed", "cancelled", "outcome_unknown"
    ]
    skill: str
    inputs_echo: dict[str, object] = Field(default_factory=dict)
    outputs: dict[str, object] = Field(default_factory=dict)
    extractions: list[dict[str, object]] = Field(default_factory=list)
    approval: dict[str, object] | None = None
    stats: RunStats
    trace_id: str
