"""Audited single-dispatch observe-resolve-act-verify runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from haykal.contracts.action import (
    ActionResult,
    DeviceReceipt,
    ResolvedTarget,
    SemanticAction,
    VerificationSummary,
)
from haykal.contracts.events import EventType
from haykal.contracts.extraction import RecordAnchor
from haykal.contracts.scene import SemanticScene
from haykal.device import DeviceBackend
from haykal.perception import semantic_content_digest
from haykal.resolver import AmbiguousTarget, TargetResolutionError, TargetResolver
from haykal.traces import TraceStore
from haykal.verification import VerificationService


class ApprovalRequired(PermissionError):
    """A sensitive or irreversible action has no validated approval yet."""


_APPROVAL_CATEGORIES = {
    "purchase",
    "transfer",
    "submission",
    "deletion",
    "permission",
    "credential",
    "communication",
    "unknown",
}
_IRREVERSIBLE_CATEGORIES = {
    "purchase",
    "transfer",
    "submission",
    "deletion",
    "communication",
}
ActionStatus = Literal[
    "verified",
    "executed_unverified",
    "rejected",
    "ambiguous",
    "failed",
    "outcome_unknown",
]
DispatchStatus = Literal["dispatched", "outcome_unknown"]


def _digest(method: str, params: dict[str, object]) -> str:
    encoded = json.dumps(
        {"method": method, "params": params},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ActionRunner:
    def __init__(
        self,
        backend: DeviceBackend,
        resolver: TargetResolver,
        verifier: VerificationService,
        traces: TraceStore,
    ) -> None:
        self._backend = backend
        self._resolver = resolver
        self._verifier = verifier
        self._traces = traces

    async def execute(
        self,
        action: SemanticAction,
        pre_scene: SemanticScene,
        *,
        run_id: str | None = None,
        trace_id: str | None = None,
        source_scene: SemanticScene | None = None,
        record_anchors: dict[str, RecordAnchor] | None = None,
        approved: bool = False,
    ) -> ActionResult:
        run_id = run_id or f"run_{uuid.uuid4().hex}"
        trace_id = trace_id or self._traces.new_trace_id()
        started = datetime.now(UTC)
        self._traces.append(
            trace_id=trace_id,
            run_id=run_id,
            event_type="action.prepared",
            payload={
                "action_id": action.action_id,
                "kind": action.kind,
                "risk": action.risk.model_dump(mode="json"),
                "has_expectation": action.expect is not None,
            },
        )
        resolved: ResolvedTarget | None = None
        receipt: DeviceReceipt | None = None
        try:
            if action.risk.category in _APPROVAL_CATEGORIES and not approved:
                raise ApprovalRequired(f"{action.risk.category} action requires validated approval")
            if action.target is not None:
                decision = self._resolver.resolve(
                    action.target,
                    pre_scene,
                    action_kind=action.kind,
                    policy=action.resolution,
                    source_scene=source_scene,
                    record_anchors=record_anchors,
                )
                resolved = decision.target
                self._traces.append(
                    trace_id=trace_id,
                    run_id=run_id,
                    event_type="target.resolved",
                    payload=resolved.model_dump(mode="json"),
                )
            receipt, dispatch_status = await self._dispatch(
                action,
                pre_scene,
                resolved_point=resolved.point if resolved is not None else None,
                approved=approved,
            )
            self._traces.append(
                trace_id=trace_id,
                run_id=run_id,
                event_type="action.dispatched",
                payload={
                    "action_id": action.action_id,
                    "receipt": receipt.model_dump(mode="json"),
                },
            )
            if dispatch_status == "outcome_unknown":
                self._traces.append(
                    trace_id=trace_id,
                    run_id=run_id,
                    event_type="run.outcome_unknown",
                    payload={"action_id": action.action_id},
                )
                return self._result(
                    action,
                    started,
                    pre_scene,
                    trace_id,
                    "outcome_unknown",
                    resolved=resolved,
                    receipt=receipt,
                )
            verification = await (
                self._verifier.verify(action.expect, pre_scene=pre_scene)
                if action.expect is not None
                else self._verifier.settle(pre_scene=pre_scene)
            )
            post_scene = verification.frame.scene
            self._traces.append(
                trace_id=trace_id,
                run_id=run_id,
                event_type="observation.created",
                payload={"scene_id": post_scene.scene_id, "revision": post_scene.revision},
            )
            if action.expect is None:
                changed = semantic_content_digest(pre_scene.elements) != semantic_content_digest(
                    post_scene.elements
                )
                verification_status: Literal["passed", "failed", "inconclusive"] = (
                    "passed" if changed else "inconclusive"
                )
                verification_evidence = [
                    {"predicate": "default_scene_changed", "actual": changed},
                    *verification.result.evidence,
                ]
            else:
                verification_status = verification.result.status
                verification_evidence = verification.result.evidence
            summary = VerificationSummary(
                status=verification_status,
                evidence=verification_evidence,
            )
            self._traces.append(
                trace_id=trace_id,
                run_id=run_id,
                event_type="verification.completed",
                payload={
                    "action_id": action.action_id,
                    "result": verification.result.model_dump(mode="json"),
                    "effective_status": verification_status,
                },
            )
            status: ActionStatus = (
                "verified"
                if verification_status == "passed"
                else "executed_unverified"
                if verification_status == "inconclusive"
                else "failed"
            )
            if status == "verified":
                self._traces.append(
                    trace_id=trace_id,
                    run_id=run_id,
                    event_type="transition.committed",
                    payload={"action_id": action.action_id, "post_scene": post_scene.scene_id},
                )
            return self._result(
                action,
                started,
                pre_scene,
                trace_id,
                status,
                post_scene=post_scene,
                resolved=resolved,
                receipt=receipt,
                verification=summary,
            )
        except AmbiguousTarget as exc:
            self._record_failure(trace_id, run_id, action.action_id, "ambiguous", str(exc))
            return self._result(
                action,
                started,
                pre_scene,
                trace_id,
                "ambiguous",
                resolved=resolved,
            )
        except (ApprovalRequired, TargetResolutionError) as exc:
            self._record_failure(trace_id, run_id, action.action_id, "rejected", str(exc))
            return self._result(
                action,
                started,
                pre_scene,
                trace_id,
                "rejected",
                resolved=resolved,
            )
        except Exception as exc:
            failure_status: ActionStatus = (
                "outcome_unknown" if action.risk.category in _IRREVERSIBLE_CATEGORIES else "failed"
            )
            self._record_failure(
                trace_id,
                run_id,
                action.action_id,
                failure_status,
                type(exc).__name__,
            )
            return self._result(
                action,
                started,
                pre_scene,
                trace_id,
                failure_status,
                resolved=resolved,
                receipt=receipt,
            )

    async def _dispatch(
        self,
        action: SemanticAction,
        scene: SemanticScene,
        *,
        resolved_point: tuple[int, int] | None,
        approved: bool,
    ) -> tuple[DeviceReceipt, DispatchStatus]:
        method, params, input_strategy = self._command(action, scene, resolved_point=resolved_point)
        request_digest = _digest(method, params)
        irreversible = action.risk.category in _IRREVERSIBLE_CATEGORIES
        if irreversible:
            if not approved:
                raise ApprovalRequired("irreversible dispatch requires approval")
            outcome = await self._backend.dispatch_once(
                action_id=action.action_id,
                method=method,
                params=params,
            )
            receipt = DeviceReceipt(
                backend="uiautomator2-single-shot",
                accepted=outcome.status == "dispatched",
                input_strategy=input_strategy,
                method=method,
                parameters_digest=request_digest,
                dispatch_status=(
                    "dispatched" if outcome.status == "dispatched" else "outcome_unknown"
                ),
                repeated_request=outcome.repeated_request,
            )
            return receipt, receipt.dispatch_status or "outcome_unknown"

        if method == "tap":
            await self._backend.tap(self._int_param(params, "x"), self._int_param(params, "y"))
        elif method == "input_text":
            assert resolved_point is not None and action.text is not None
            await self._backend.tap(*resolved_point)
            await self._backend.type_text(action.text, replace=action.mode == "replace")
        elif method == "swipe":
            await self._backend.swipe(
                self._int_param(params, "x1"),
                self._int_param(params, "y1"),
                self._int_param(params, "x2"),
                self._int_param(params, "y2"),
                self._int_param(params, "duration_ms"),
            )
        elif method == "press":
            await self._backend.press(str(params["key"]))
        else:
            await asyncio.sleep(self._int_param(params, "wait_ms") / 1000)
        return (
            DeviceReceipt(
                backend="uiautomator2",
                accepted=True,
                input_strategy=input_strategy,
                method=method,
                parameters_digest=request_digest,
                dispatch_status="dispatched",
            ),
            "dispatched",
        )

    def _command(
        self,
        action: SemanticAction,
        scene: SemanticScene,
        *,
        resolved_point: tuple[int, int] | None,
    ) -> tuple[str, dict[str, object], Literal["helper_ime"] | None]:
        if action.kind == "tap":
            assert resolved_point is not None
            return "tap", {"x": resolved_point[0], "y": resolved_point[1]}, None
        if action.kind == "input_text":
            assert resolved_point is not None and action.text is not None
            return (
                "input_text",
                {
                    "x": resolved_point[0],
                    "y": resolved_point[1],
                    "text": action.text,
                    "replace": action.mode == "replace",
                },
                "helper_ime",
            )
        if action.kind == "swipe":
            bounds = self._swipe_bounds(action, scene)
            ratio = action.distance_ratio or 0.5
            direction = action.direction or "up"
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            center_x = bounds[0] + width // 2
            center_y = bounds[1] + height // 2
            dx = round(width * ratio / 2)
            dy = round(height * ratio / 2)
            points = {
                "up": (center_x, center_y + dy, center_x, center_y - dy),
                "down": (center_x, center_y - dy, center_x, center_y + dy),
                "left": (center_x + dx, center_y, center_x - dx, center_y),
                "right": (center_x - dx, center_y, center_x + dx, center_y),
            }
            x1, y1, x2, y2 = points[direction]
            return (
                "swipe",
                {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration_ms": 300},
                None,
            )
        if action.kind == "press_key":
            assert action.key is not None
            return "press", {"key": action.key}, None
        assert action.wait_ms is not None
        return "wait", {"wait_ms": action.wait_ms}, None

    def _swipe_bounds(
        self, action: SemanticAction, scene: SemanticScene
    ) -> tuple[int, int, int, int]:
        if action.within is not None:
            decision = self._resolver.resolve_selector(
                action.within,
                scene,
                action_kind="swipe",
                policy=action.resolution,
            )
            element = next(
                item.element
                for item in decision.ranked
                if item.element.id == decision.target.element_id
            )
            return (
                element.bounds.left,
                element.bounds.top,
                element.bounds.right,
                element.bounds.bottom,
            )
        if not scene.elements:
            raise TargetResolutionError("cannot infer swipe viewport from empty scene")
        return (
            min(item.bounds.left for item in scene.elements),
            min(item.bounds.top for item in scene.elements),
            max(item.bounds.right for item in scene.elements),
            max(item.bounds.bottom for item in scene.elements),
        )

    def _record_failure(
        self,
        trace_id: str,
        run_id: str,
        action_id: str,
        status: str,
        detail: str,
    ) -> None:
        event_type: EventType = (
            "run.outcome_unknown" if status == "outcome_unknown" else "run.failed"
        )
        self._traces.append(
            trace_id=trace_id,
            run_id=run_id,
            event_type=event_type,
            payload={"action_id": action_id, "status": status, "detail": detail},
        )

    def _int_param(self, params: dict[str, object], name: str) -> int:
        value = params.get(name)
        if not isinstance(value, int):
            raise ValueError(f"dispatch parameter {name!r} must be an integer")
        return value

    def _result(
        self,
        action: SemanticAction,
        started: datetime,
        pre_scene: SemanticScene,
        trace_id: str,
        status: ActionStatus,
        *,
        post_scene: SemanticScene | None = None,
        resolved: ResolvedTarget | None = None,
        receipt: DeviceReceipt | None = None,
        verification: VerificationSummary | None = None,
    ) -> ActionResult:
        return ActionResult(
            action_id=action.action_id,
            status=status,
            attempts=1 if receipt is not None else 0,
            started_at=started,
            completed_at=datetime.now(UTC),
            pre_scene=pre_scene.scene_id,
            post_scene=post_scene.scene_id if post_scene else None,
            resolved_target=resolved,
            device_receipt=receipt,
            verification=verification,
            trace_id=trace_id,
        )
