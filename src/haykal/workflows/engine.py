"""Guarded, journaled skill interpreter with bounded human/agent delegation."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from haykal.contracts import (
    ApprovalChallenge,
    DecisionResponse,
    Expectation,
    RunRequest,
    RunSnapshot,
    SemanticAction,
    Skill,
)
from haykal.contracts.action import ActionTarget, ResolvedTarget, Risk
from haykal.contracts.extraction import ExtractedRecord, ExtractionResult, RecordAnchor
from haykal.contracts.skill import (
    Branch,
    FieldReconcile,
    SkillInput,
    SkillState,
    SumReconcile,
    Transition,
)
from haykal.execution.risk import (
    RiskClassifier,
    ValidatedApproval,
    canonical_digest,
    resolved_target_fingerprint,
)
from haykal.runtime import RuntimeSession
from haykal.skills import SkillRegistry
from haykal.traces import TraceStore
from haykal.verification import ExpectationEvaluator

from .approval import ApprovalError, ApprovalService, ApprovalStale
from .journal import RunJournal
from .selection import SelectionEvaluator
from .values import ValueNotFound, get_path, public_input_echo, resolve_value

SessionLookup = Callable[[str], RuntimeSession]


class InvalidDecision(ValueError):
    pass


class InvalidSkillInput(ValueError):
    pass


class SkillEngine:
    """Executes known states without a model and pauses at explicit boundaries."""

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        journal: RunJournal,
        approvals: ApprovalService,
        traces: TraceStore,
        sessions: SessionLookup,
        decision_ttl_s: int = 900,
        approval_ttl_s: int = 300,
        max_steps: int = 100,
    ) -> None:
        self._registry = registry
        self._journal = journal
        self._approvals = approvals
        self._traces = traces
        self._sessions = sessions
        self._selection = SelectionEvaluator()
        self._risks = RiskClassifier()
        self._decision_ttl_s = decision_ttl_s
        self._approval_ttl_s = approval_ttl_s
        self._max_steps = max_steps

    async def start(self, request: RunRequest) -> RunSnapshot:
        skill = self._registry.load(request.skill, request.version)
        inputs = self._validate_inputs(skill, request.inputs)
        now = datetime.now(UTC)
        snapshot = RunSnapshot(
            run_id=f"run_{uuid.uuid4().hex}",
            trace_id=self._traces.new_trace_id(),
            session_id=request.session_id,
            skill=f"{request.skill}@{request.version}",
            skill_digest=skill.metadata.content_digest or canonical_digest(skill.model_dump()),
            state=skill.start,
            status="running",
            inputs_echo=public_input_echo(inputs),
            outputs={"_inputs": inputs, "_extractions": {}, "_selected": {}},
            created_at=now,
            updated_at=now,
        )
        self._journal.create(snapshot)
        self._event(snapshot, "run.started", {"skill": snapshot.skill})
        await self._sessions(snapshot.session_id).observe()
        return await self._drive(snapshot, skill)

    def get(self, run_id: str) -> RunSnapshot:
        snapshot = self._journal.get(run_id)
        if snapshot.status == "needs_decision" and self._pending_expired(snapshot):
            snapshot = self._replace(snapshot, status="suspended")
            self._event(snapshot, "run.suspended", {"reason": "decision_expired"})
        return snapshot

    async def recover(self, run_id: str) -> RunSnapshot:
        """Continue a run left running by a prior process without replaying actions."""

        snapshot = self._journal.get(run_id)
        if snapshot.status != "running":
            return self.get(run_id)
        name, version = snapshot.skill.rsplit("@", 1)
        await self._sessions(snapshot.session_id).observe()
        return await self._drive(snapshot, self._registry.load(name, version))

    async def resume(self, run_id: str) -> RunSnapshot:
        snapshot = self.get(run_id)
        if snapshot.status != "suspended":
            raise InvalidDecision("only a suspended run can be resumed without a response")
        pending = dict(snapshot.pending or {})
        pending["expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=self._decision_ttl_s)
        ).isoformat()
        snapshot = self._replace(snapshot, status="needs_decision", pending=pending)
        self._event(snapshot, "run.resumed", {"state": snapshot.state})
        return snapshot

    async def decide(self, run_id: str, response: DecisionResponse) -> RunSnapshot:
        snapshot = self.get(run_id)
        if snapshot.status == "suspended":
            raise InvalidDecision("resume the suspended run before deciding")
        if snapshot.status != "needs_decision" or snapshot.pending is None:
            raise InvalidDecision("run is not waiting for a decision")
        pending = snapshot.pending
        allowed_raw = pending.get("allowed_responses", [])
        allowed = allowed_raw if isinstance(allowed_raw, list) else []
        kind = self._decision_kind(response)
        if kind not in allowed:
            raise InvalidDecision(f"response {kind!r} is not allowed")
        if response.cancel:
            snapshot = self._replace(
                snapshot,
                status="cancelled",
                pending=None,
                decisions=snapshot.decisions + 1,
            )
            self._event(snapshot, "run.cancelled", {"state": snapshot.state})
            return snapshot
        outputs = dict(snapshot.outputs)
        if response.select_record is not None:
            choices_raw = pending.get("choices", [])
            choices = choices_raw if isinstance(choices_raw, list) else []
            valid = {
                item.get("record_id")
                for item in choices
                if isinstance(item, dict) and isinstance(item.get("record_id"), str)
            }
            if response.select_record not in valid:
                raise InvalidDecision("selected record is not one of the offered candidates")
            forced = dict(self._mapping(outputs.get("_forced_selection")))
            forced[snapshot.state] = response.select_record
            outputs["_forced_selection"] = forced
        elif response.select_transition is not None:
            transitions_raw = pending.get("transitions", [])
            transitions = transitions_raw if isinstance(transitions_raw, list) else []
            if response.select_transition not in transitions:
                raise InvalidDecision("selected transition is not allowed")
            snapshot = snapshot.model_copy(update={"state": response.select_transition})
        elif response.action is not None:
            actions_raw = pending.get("allowed_actions", [])
            allowed_actions = actions_raw if isinstance(actions_raw, list) else []
            if response.action.kind not in allowed_actions:
                raise InvalidDecision("recovery action kind is not allowed")
            if response.expect is None:
                raise InvalidDecision("recovery action requires an explicit expectation")
            runtime = self._sessions(snapshot.session_id)
            resolution = await runtime.resolve(response.action)
            effective_risk = self._effective_risk(resolution)
            if effective_risk.category != "navigation" or effective_risk.gate != "none":
                raise InvalidDecision("decision actions must be reversible navigation")
            recovery_action = response.action.model_copy(
                update={"expect": response.expect, "risk": effective_risk}
            )
            claim = self._journal.claim_action(
                snapshot.run_id,
                recovery_action.action_id,
                canonical_digest(recovery_action.model_dump(mode="json")),
            )
            if claim.should_dispatch:
                result = await runtime.act(
                    recovery_action,
                    run_id=snapshot.run_id,
                    trace_id=snapshot.trace_id,
                )
                status = "committed" if result.status == "verified" else "outcome_unknown"
                self._journal.finish_action(
                    snapshot.run_id,
                    recovery_action.action_id,
                    status=status,
                    result=result.model_dump(mode="json"),
                )
                if result.status != "verified":
                    raise InvalidDecision(f"recovery action did not verify: {result.status}")
                self._journal.record_patch(
                    run_id=snapshot.run_id,
                    skill_digest=snapshot.skill_digest,
                    state=snapshot.state,
                    reason=str(pending.get("reason", "unrecognized_screen")),
                    decision=response,
                    scene_digest=self._sessions(snapshot.session_id).current_scene().digest,
                )
            elif claim.status != "committed":
                raise InvalidDecision("recovery action has an unknown prior outcome")
        snapshot = self._replace(
            snapshot,
            status="running",
            pending=None,
            outputs=outputs,
            decisions=snapshot.decisions + 1,
        )
        self._event(snapshot, "run.resumed", {"state": snapshot.state, "decision": kind})
        name, version = snapshot.skill.rsplit("@", 1)
        return await self._drive(snapshot, self._registry.load(name, version))

    def approve(
        self,
        run_id: str,
        *,
        principal: str,
        scopes: set[str],
        presented: ApprovalChallenge | None = None,
    ) -> str:
        snapshot = self.get(run_id)
        if snapshot.status != "approval_required" or snapshot.pending is None:
            raise ApprovalError("run is not waiting for approval")
        challenge = self._challenge(snapshot)
        if presented is not None and presented != challenge:
            raise ApprovalStale("presented approval challenge is not current")
        return self._approvals.grant(
            challenge,
            principal=principal,
            scopes=scopes,
        ).token

    async def submit_approval(self, run_id: str, token: str) -> RunSnapshot:
        snapshot = self.get(run_id)
        if snapshot.status != "approval_required":
            raise ApprovalError("run is not waiting for approval")
        name, version = snapshot.skill.rsplit("@", 1)
        skill = self._registry.load(name, version)
        return await self._drive(
            self._replace(snapshot, status="running"),
            skill,
            approval_token=token,
        )

    async def _drive(
        self,
        snapshot: RunSnapshot,
        skill: Skill,
        *,
        approval_token: str | None = None,
    ) -> RunSnapshot:
        runtime = self._sessions(snapshot.session_id)
        await runtime.configure_elements(skill.elements)
        evaluator = ExpectationEvaluator(element_dictionary=skill.elements)
        while snapshot.status == "running":
            if snapshot.steps >= self._max_steps:
                return self._fail(snapshot, "step_budget_exhausted")
            state = skill.states[snapshot.state]
            checkpoint = self._journal.action_status(
                snapshot.run_id, f"{snapshot.run_id}:{snapshot.state}"
            )
            if checkpoint == "committed":
                snapshot = self._transition(snapshot, state, evaluator, runtime)
                continue
            if checkpoint in {"prepared", "outcome_unknown"}:
                if checkpoint == "prepared":
                    interrupted = self._action(snapshot, state)
                    if interrupted is not None:
                        self._journal.claim_action(
                            snapshot.run_id,
                            interrupted.action_id,
                            canonical_digest(interrupted.model_dump(mode="json")),
                        )
                snapshot = self._uncertain(snapshot, state, f"{snapshot.run_id}:{snapshot.state}")
                if snapshot.status == "running":
                    continue
                return snapshot
            scene = runtime.current_scene()
            context = self._context(snapshot)
            if state.expect is not None:
                expected = self._expectation(state.expect, context)
                assert expected is not None
                expectation_result = evaluator.evaluate(expected, scene)
                if expectation_result.status != "passed":
                    return self._pause(
                        snapshot,
                        reason="unexpected_state",
                        allowed_actions=["tap", "press_key", "cancel"],
                    )
            snapshot, context = await self._extract_select_reconcile(snapshot, state, runtime)
            if snapshot.status != "running":
                return snapshot
            action = self._action(snapshot, state)
            anchors = self._anchors(snapshot)
            if action is not None:
                validated_approval: ValidatedApproval | None = None
                try:
                    await runtime.reveal(
                        action,
                        run_id=snapshot.run_id,
                        trace_id=snapshot.trace_id,
                        record_anchors=anchors,
                    )
                    resolution = await runtime.resolve(action, record_anchors=anchors)
                except ValueError:
                    return self._pause(
                        snapshot,
                        reason="ambiguous_target",
                        allowed_actions=["tap", "press_key", "cancel"],
                    )
                effective_risk = self._effective_risk(resolution)
                action = action.model_copy(update={"risk": effective_risk})
                if effective_risk.gate == "required" and state.gate is None:
                    return self._fail(snapshot, "approval_policy_missing")
                if state.gate is not None:
                    challenge = self._make_challenge(snapshot, state, action, resolution)
                    if approval_token is None:
                        pending = challenge.model_dump(mode="json")
                        pending["reason"] = "approval_required"
                        pending["allowed_responses"] = ["approve", "cancel"]
                        snapshot = self._replace(
                            snapshot,
                            status="approval_required",
                            pending=pending,
                            gates=snapshot.gates + 1,
                        )
                        self._event(snapshot, "run.approval_required", pending)
                        return snapshot
                    bound = self._challenge(snapshot)
                    challenge = challenge.model_copy(
                        update={
                            "gate_id": bound.gate_id,
                            "nonce": bound.nonce,
                            "expires_at": bound.expires_at,
                        }
                    )
                    try:
                        self._approvals.consume(approval_token, challenge)
                    except ApprovalStale:
                        fresh = self._make_challenge(snapshot, state, action, resolution)
                        pending = fresh.model_dump(mode="json")
                        pending["reason"] = "approval_stale"
                        pending["allowed_responses"] = ["approve", "cancel"]
                        snapshot = self._replace(
                            snapshot, status="approval_required", pending=pending
                        )
                        self._event(snapshot, "run.approval_stale", pending)
                        return snapshot
                    validated_approval = ValidatedApproval(
                        gate_id=challenge.gate_id,
                        action_intent_digest=challenge.action_intent_digest,
                        target_fingerprint=challenge.target_fingerprint,
                        effective_risk=action.risk.category,
                    )
                    approval_token = None
                claim = self._journal.claim_action(
                    snapshot.run_id,
                    action.action_id,
                    canonical_digest(action.model_dump(mode="json")),
                )
                if not claim.should_dispatch:
                    if claim.status == "committed":
                        snapshot = self._transition(snapshot, state, evaluator, runtime)
                        continue
                    snapshot = self._uncertain(snapshot, state, action.action_id)
                    if snapshot.status == "running":
                        continue
                    return snapshot
                action_result = await runtime.act(
                    action,
                    run_id=snapshot.run_id,
                    trace_id=snapshot.trace_id,
                    approval=validated_approval,
                    record_anchors=anchors,
                )
                if action_result.status == "verified":
                    self._journal.finish_action(
                        snapshot.run_id,
                        action.action_id,
                        status="committed",
                        result=action_result.model_dump(mode="json"),
                    )
                else:
                    self._journal.finish_action(
                        snapshot.run_id,
                        action.action_id,
                        status="outcome_unknown",
                        result=action_result.model_dump(mode="json"),
                    )
                    if (
                        action_result.status in {"ambiguous", "rejected"}
                        and action_result.attempts == 0
                    ):
                        return self._pause(
                            snapshot,
                            reason="ambiguous_target",
                            allowed_actions=["tap", "press_key", "cancel"],
                        )
                    snapshot = self._uncertain(snapshot, state, action.action_id)
                    if snapshot.status == "running":
                        continue
                    return snapshot
            snapshot = self._transition(snapshot, state, evaluator, runtime)
        return snapshot

    async def _extract_select_reconcile(
        self,
        snapshot: RunSnapshot,
        state: SkillState,
        runtime: RuntimeSession,
    ) -> tuple[RunSnapshot, dict[str, object]]:
        outputs = dict(snapshot.outputs)
        extractions = dict(self._mapping(outputs.get("_extractions")))
        selected = dict(self._mapping(outputs.get("_selected")))
        if state.extract is not None:
            scene = await runtime.observe()
            request = state.extract.model_copy(update={"scene_id": scene.scene_id})
            result = await runtime.extract(request)
            extractions[state.extract.as_] = result.model_dump(mode="json")
            outputs["_extractions"] = extractions
            outputs[state.extract.as_] = (
                result.records[0].fields
                if state.extract.group.by == "single" and len(result.records) == 1
                else [record.fields for record in result.records]
            )
            snapshot = self._replace(snapshot, outputs=outputs)
            self._event(
                snapshot,
                "extraction.completed",
                {"alias": state.extract.as_, "records": len(result.records)},
            )
        context = self._context(snapshot)
        if state.select is not None:
            raw = extractions.get(state.select.from_)
            if not isinstance(raw, dict):
                return self._fail(snapshot, "selection_source_missing"), context
            extraction = ExtractionResult.model_validate(raw)
            outcome = self._selection.evaluate(state.select, extraction.records, context)
            forced = self._mapping(outputs.get("_forced_selection")).get(snapshot.state)
            if forced is not None:
                outcome = outcome.model_copy(
                    update={
                        "status": "selected",
                        "selected": next(
                            (item for item in extraction.records if item.record_id == forced), None
                        ),
                    }
                )
            if outcome.status == "empty" or (
                outcome.selected is None and outcome.status == "selected"
            ):
                return (
                    self._pause(
                        snapshot,
                        reason="selection_empty",
                        allowed_actions=["cancel"],
                    ),
                    context,
                )
            if outcome.status == "margin":
                choices = [item.model_dump(mode="json") for item in outcome.candidates]
                return (
                    self._pause(
                        snapshot,
                        reason="selection_margin",
                        allowed_actions=["cancel"],
                        extra={
                            "choices": choices,
                            "allowed_responses": ["select_record", "cancel"],
                        },
                    ),
                    context,
                )
            assert outcome.selected is not None
            selected[state.select.as_] = outcome.selected.model_dump(mode="json")
            outputs["_selected"] = selected
            outputs[state.select.as_] = outcome.selected.fields
            snapshot = self._replace(snapshot, outputs=outputs)
            context = self._context(snapshot)
        if state.reconcile is not None and not self._reconcile(state, context):
            transition = state.on_reconcile_failure
            if transition is not None:
                return self._apply_transition(snapshot, transition), context
            return (
                self._pause(snapshot, reason="checkout_mismatch", allowed_actions=["cancel"]),
                context,
            )
        return snapshot, context

    def _transition(
        self,
        snapshot: RunSnapshot,
        state: SkillState,
        evaluator: ExpectationEvaluator,
        runtime: RuntimeSession,
    ) -> RunSnapshot:
        if state.next is not None:
            return self._advance(snapshot, state.next)
        if state.terminal is not None:
            status = self._terminal_status(state.terminal)
            snapshot = self._replace(
                snapshot,
                status=status,
                outputs={**snapshot.outputs, "terminal": state.terminal},
                steps=snapshot.steps + 1,
            )
            event = (
                "run.completed_reconciled" if status == "completed_reconciled" else "run.completed"
            )
            self._event(snapshot, event, {"terminal": state.terminal})
            return snapshot
        if state.escalate is not None:
            return self._pause(
                snapshot,
                reason=state.escalate.reason,
                allowed_actions=list(state.escalate.allowed_actions),
            )
        assert state.branches is not None
        for branch in state.branches:
            if branch.otherwise or (
                branch.when is not None
                and evaluator.evaluate(branch.when, runtime.current_scene()).status == "passed"
            ):
                return self._apply_branch(snapshot, branch)
        return self._pause(
            snapshot,
            reason="unexpected_state",
            allowed_actions=["tap", "press_key", "cancel"],
        )

    def _action(self, snapshot: RunSnapshot, state: SkillState) -> SemanticAction | None:
        spec = state.action
        if spec is None:
            return None
        context = self._context(snapshot)
        target: ActionTarget | None = None
        if spec.target is not None:
            if hasattr(spec.target, "record_anchor"):
                target = ActionTarget(record_anchor=spec.target.record_anchor)
            else:
                target = ActionTarget(selector=spec.target)
        text = resolve_value(spec.text, context) if spec.text is not None else None
        if text is not None and not isinstance(text, str):
            raise InvalidSkillInput("input_text interpolation must resolve to a string")
        expectation = self._expectation(state.verify, context) if state.verify is not None else None
        provisional = SemanticAction(
            action_id=f"{snapshot.run_id}:{snapshot.state}",
            kind=spec.kind,
            target=target,
            direction=spec.direction,
            distance_ratio=spec.distance_ratio,
            within=spec.within,
            text=text,
            mode=spec.mode,
            key=spec.key,
            wait_ms=spec.wait_ms,
            expect=expectation,
            risk=Risk(category="navigation", gate="none"),
        )
        declared = state.gate.category if state.gate else None
        category = self._risks.classify(provisional, declared)
        risk = (
            Risk(category=category, gate="required")
            if category != "navigation"
            else Risk(category=category, gate="none")
        )
        return provisional.model_copy(update={"risk": risk})

    def _make_challenge(
        self,
        snapshot: RunSnapshot,
        state: SkillState,
        action: SemanticAction,
        resolution: dict[str, object],
    ) -> ApprovalChallenge:
        assert state.gate is not None
        material = self._resolve_material(state.gate.material, self._context(snapshot))
        if not isinstance(material, dict):
            raise ValueError("gate material must resolve to an object")
        target = resolution.get("target")
        if not isinstance(target, dict) or not isinstance(target.get("element_id"), str):
            raise ValueError("gated action must resolve an element")
        scene = self._sessions(snapshot.session_id).current_scene()
        resolved = ResolvedTarget.model_validate(target)
        fingerprint = resolved_target_fingerprint(scene, resolved)
        return self._approvals.challenge(
            run_id=snapshot.run_id,
            skill_digest=snapshot.skill_digest,
            action=action,
            target_fingerprint=fingerprint,
            material=material,
            evidence_scene_digest=scene.digest,
            ttl_s=self._approval_ttl_s,
        )

    @staticmethod
    def _effective_risk(resolution: dict[str, object]) -> Risk:
        assessment = resolution.get("risk")
        if not isinstance(assessment, dict):
            raise ValueError("runtime resolution omitted effective risk assessment")
        effective = assessment.get("effective")
        return Risk.model_validate(effective)

    def _challenge(self, snapshot: RunSnapshot) -> ApprovalChallenge:
        pending = snapshot.pending or {}
        return ApprovalChallenge.model_validate(
            {name: pending[name] for name in ApprovalChallenge.model_fields if name in pending}
        )

    def _anchors(self, snapshot: RunSnapshot) -> dict[str, RecordAnchor]:
        anchors: dict[str, RecordAnchor] = {}
        for alias, raw in self._mapping(snapshot.outputs.get("_selected")).items():
            if isinstance(raw, dict):
                record = ExtractedRecord.model_validate(raw)
                if record.anchor is not None:
                    anchors[alias] = record.anchor
        return anchors

    def _reconcile(self, state: SkillState, context: dict[str, object]) -> bool:
        for check in state.reconcile or []:
            try:
                if isinstance(check, FieldReconcile):
                    left = get_path(context, check.field)
                    right = resolve_value(check.value, context)
                    if not self._compare(left, check.op, right, check.tolerance):
                        return False
                elif isinstance(check, SumReconcile):
                    values = [Decimal(str(get_path(context, part))) for part in check.parts]
                    total = Decimal(str(get_path(context, check.total)))
                    actual = sum(
                        (value if sign == "+" else -value)
                        for value, sign in zip(values, check.signs, strict=True)
                    )
                    if abs(actual - total) > Decimal(str(check.tolerance)):
                        return False
            except (ValueNotFound, TypeError, InvalidOperation):
                return False
        return True

    @staticmethod
    def _compare(left: object, op: str, right: object, tolerance: float | None) -> bool:
        if left is None or right is None:
            return False
        if tolerance is not None and op == "==":
            try:
                return abs(Decimal(str(left)) - Decimal(str(right))) <= Decimal(str(tolerance))
            except InvalidOperation:
                return False
        if op == "contains":
            return str(right) in str(left)
        if op == "in":
            return left in right if isinstance(right, (list, tuple, set, dict, str)) else False
        if op in {"==", "!="}:
            return (left == right) == (op == "==")
        try:
            left_number, right_number = Decimal(str(left)), Decimal(str(right))
            return {
                "<": left_number < right_number,
                "<=": left_number <= right_number,
                ">": left_number > right_number,
                ">=": left_number >= right_number,
            }[op]
        except InvalidOperation:
            left_text, right_text = str(left), str(right)
            return {
                "<": left_text < right_text,
                "<=": left_text <= right_text,
                ">": left_text > right_text,
                ">=": left_text >= right_text,
            }[op]

    def _pause(
        self,
        snapshot: RunSnapshot,
        *,
        reason: str,
        allowed_actions: list[str],
        extra: dict[str, object] | None = None,
    ) -> RunSnapshot:
        pending: dict[str, object] = {
            "reason": reason,
            "run_state": snapshot.state,
            "allowed_actions": allowed_actions,
            "allowed_responses": ["action", "cancel"]
            if allowed_actions != ["cancel"]
            else ["cancel"],
            "expires_at": (datetime.now(UTC) + timedelta(seconds=self._decision_ttl_s)).isoformat(),
        }
        pending.update(extra or {})
        snapshot = self._replace(snapshot, status="needs_decision", pending=pending)
        self._event(snapshot, "run.needs_decision", pending)
        return snapshot

    def _uncertain(self, snapshot: RunSnapshot, state: SkillState, action_id: str) -> RunSnapshot:
        if state.on_action_uncertain is not None:
            snapshot = self._apply_transition(snapshot, state.on_action_uncertain)
            self._event(snapshot, "run.outcome_unknown", {"action_id": action_id})
            return snapshot
        snapshot = self._replace(snapshot, status="outcome_unknown")
        self._event(snapshot, "run.outcome_unknown", {"action_id": action_id})
        return snapshot

    def _apply_branch(self, snapshot: RunSnapshot, branch: Branch) -> RunSnapshot:
        return self._apply_transition(snapshot, branch)

    def _apply_transition(self, snapshot: RunSnapshot, transition: Transition) -> RunSnapshot:
        if transition.next is not None:
            return self._advance(snapshot, transition.next)
        if transition.terminal is not None:
            status = self._terminal_status(transition.terminal)
            completed = self._replace(
                snapshot,
                status=status,
                outputs={**snapshot.outputs, "terminal": transition.terminal},
                steps=snapshot.steps + 1,
            )
            event = (
                "run.completed_reconciled" if status == "completed_reconciled" else "run.completed"
            )
            self._event(completed, event, {"terminal": transition.terminal})
            return completed
        assert transition.escalate is not None
        return self._pause(
            snapshot,
            reason=transition.escalate.reason,
            allowed_actions=list(transition.escalate.allowed_actions),
        )

    def _advance(self, snapshot: RunSnapshot, state: str) -> RunSnapshot:
        updated = self._replace(snapshot, state=state, steps=snapshot.steps + 1, pending=None)
        self._event(updated, "transition.committed", {"state": state})
        return updated

    def _fail(self, snapshot: RunSnapshot, reason: str) -> RunSnapshot:
        snapshot = self._replace(snapshot, status="failed", pending={"reason": reason})
        self._event(snapshot, "run.failed", {"reason": reason})
        return snapshot

    def _replace(self, snapshot: RunSnapshot, **updates: object) -> RunSnapshot:
        updates["updated_at"] = datetime.now(UTC)
        changed = snapshot.model_copy(update=updates)
        self._journal.update(changed)
        return changed

    def _event(self, snapshot: RunSnapshot, event_type: str, payload: dict[str, object]) -> None:
        self._traces.append(
            trace_id=snapshot.trace_id,
            run_id=snapshot.run_id,
            event_type=event_type,  # type: ignore[arg-type]
            payload=payload,
        )

    def _context(self, snapshot: RunSnapshot) -> dict[str, object]:
        outputs = snapshot.outputs
        inputs = dict(self._mapping(outputs.get("_inputs")))
        context = {**inputs, "inputs": inputs}
        for key, value in outputs.items():
            if not key.startswith("_"):
                context[key] = value
        return context

    def _resolve_material(self, value: object, context: dict[str, object]) -> object:
        if isinstance(value, str):
            try:
                return get_path(context, value)
            except ValueNotFound:
                return resolve_value(value, context)
        if isinstance(value, list):
            return [self._resolve_material(item, context) for item in value]
        if isinstance(value, dict):
            return {key: self._resolve_material(item, context) for key, item in value.items()}
        return value

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _expectation(expectation: object, context: dict[str, object]) -> Expectation | None:
        if expectation is None:
            return None
        assert isinstance(expectation, Expectation)
        payload = resolve_value(expectation.model_dump(mode="json", by_alias=True), context)
        return Expectation.model_validate(payload)

    @staticmethod
    def _terminal_status(label: str) -> str:
        if label == "prepared":
            return "prepared"
        if label == "completed_reconciled":
            return "completed_reconciled"
        if label == "outcome_unknown":
            return "outcome_unknown"
        if label.startswith("failed"):
            return "failed"
        return "completed"

    @staticmethod
    def _decision_kind(response: DecisionResponse) -> str:
        if response.select_record is not None:
            return "select_record"
        if response.select_transition is not None:
            return "select_transition"
        if response.action is not None:
            return "action"
        return "cancel"

    @staticmethod
    def _pending_expired(snapshot: RunSnapshot) -> bool:
        value = (snapshot.pending or {}).get("expires_at")
        if not isinstance(value, str):
            return False
        return datetime.now(UTC) >= datetime.fromisoformat(value)

    def _validate_inputs(self, skill: Skill, supplied: dict[str, object]) -> dict[str, object]:
        unknown = set(supplied) - set(skill.inputs)
        if unknown:
            raise InvalidSkillInput(f"unknown inputs: {', '.join(sorted(unknown))}")
        values: dict[str, object] = {}
        for name, specification in skill.inputs.items():
            if name not in supplied:
                if specification.default is not None:
                    values[name] = specification.default
                    continue
                if specification.required:
                    raise InvalidSkillInput(f"required input {name!r} is missing")
                continue
            value = supplied[name]
            self._validate_input(name, specification, value)
            values[name] = value
        return values

    def _validate_input(self, name: str, spec: SkillInput, value: object) -> None:
        valid = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "enum": isinstance(value, str) and (spec.values is None or value in spec.values),
            "money": isinstance(value, dict) and "amount" in value and "currency" in value,
            "secret_ref": isinstance(value, dict) and value.get("namespace") == spec.namespace,
            "saved_ref": isinstance(value, dict) and value.get("namespace") == spec.namespace,
            "object": isinstance(value, dict),
        }[spec.type]
        if not valid:
            raise InvalidSkillInput(f"input {name!r} does not match {spec.type}")
        if isinstance(value, str) and spec.min_length is not None and len(value) < spec.min_length:
            raise InvalidSkillInput(f"input {name!r} is too short")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if spec.min is not None and value < spec.min:
                raise InvalidSkillInput(f"input {name!r} is below minimum")
            if spec.max is not None and value > spec.max:
                raise InvalidSkillInput(f"input {name!r} is above maximum")
