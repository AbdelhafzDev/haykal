from __future__ import annotations

from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.contracts import DecisionResponse, RunRequest, Skill
from haykal.device import DeviceHealth, DeviceSnapshot
from haykal.device.single_shot import DispatchOutcome
from haykal.runtime import RuntimeSession
from haykal.skills import PublisherKeyPair, SkillRegistry, TrustPolicy, sign_skill
from haykal.traces import TraceStore
from haykal.workflows import ApprovalService, RunJournal, SkillEngine


class Backend:
    def __init__(self, *, mode: str = "simple") -> None:
        self.opened = False
        self.mode = mode
        self.done = False
        self.taps = 0
        self.dispatches = 0
        self.total = "55.20 SAR"

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False

    async def health(self) -> DeviceHealth:
        return DeviceHealth(True, "fixture")

    async def snapshot(self) -> DeviceSnapshot:
        return DeviceSnapshot(400, 800, 2, 0, "dev.haykal.matjar", ".Main", False)

    async def hierarchy(self) -> str:
        if self.mode == "approval":
            return self._approval_xml()
        label, resource = ("تم", "done") if self.done else ("التالي", "next")
        return self._xml_node(label, resource, clickable=True)

    async def screenshot(self) -> bytes:
        return b"fixture-png"

    async def tap(self, x: int, y: int) -> None:
        self.taps += 1
        self.done = True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None: ...

    async def type_text(self, text: str, *, replace: bool) -> None: ...

    async def press(self, key: str) -> None: ...

    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome:
        self.dispatches += 1
        self.done = True
        return DispatchOutcome(action_id, "dispatched", {"wire_calls": 1}, False)

    def _approval_xml(self) -> str:
        if self.done:
            return self._xml_node("تم الطلب", "confirmation", clickable=False)
        total = self._xml_node(self.total, "total", clickable=False, nested=True)
        order = self._xml_node("إتمام الطلب", "place_order", clickable=True, nested=True)
        return f'<hierarchy rotation="0">{total}{order}</hierarchy>'

    @staticmethod
    def _xml_node(label: str, resource: str, *, clickable: bool, nested: bool = False) -> str:
        node = f'''<node index="0" text="{label}" resource-id="dev.haykal.matjar:id/{resource}"
          class="android.widget.Button" package="dev.haykal.matjar" content-desc="{label}"
          checkable="false" checked="false" clickable="{str(clickable).lower()}" enabled="true"
          focusable="true" focused="false" scrollable="false" selected="false"
          bounds="[10,20][210,120]" visible-to-user="true" />'''
        return node if nested else f'<hierarchy rotation="0">{node}</hierarchy>'


def _simple_skill() -> Skill:
    return Skill.model_validate(
        {
            "metadata": {
                "name": "matjar.simple",
                "version": "1.0.0",
                "package": "dev.haykal.matjar",
                "app_versions": ">=1,<2",
                "locales": ["ar-SA"],
            },
            "elements": {
                "next": {"resource_id": {"ends_with": "id/next"}},
                "done": {"resource_id": {"ends_with": "id/done"}},
            },
            "start": "tap",
            "states": {
                "tap": {
                    "expect": {"visible": {"semantic_name": "next"}},
                    "action": {"kind": "tap", "target": {"semantic_name": "next"}},
                    "verify": {"visible": {"semantic_name": "done"}},
                    "next": "finish",
                },
                "finish": {
                    "expect": {"visible": {"semantic_name": "done"}},
                    "terminal": "completed",
                },
            },
        }
    )


def _approval_skill() -> Skill:
    return Skill.model_validate(
        {
            "metadata": {
                "name": "matjar.order",
                "version": "1.0.0",
                "package": "dev.haykal.matjar",
                "app_versions": ">=1,<2",
                "locales": ["ar-SA"],
            },
            "elements": {
                "total": {"resource_id": {"ends_with": "id/total"}},
                "place_order": {"resource_id": {"ends_with": "id/place_order"}},
                "confirmation": {"resource_id": {"ends_with": "id/confirmation"}},
            },
            "start": "review",
            "states": {
                "review": {
                    "expect": {"visible": {"semantic_name": "place_order"}},
                    "extract": {
                        "as": "checkout",
                        "group": {"by": "single"},
                        "fields": {
                            "total": {
                                "selector": {"semantic_name": "total"},
                                "type": "money",
                                "required": True,
                            }
                        },
                    },
                    "reconcile": [
                        {"field": "checkout.total.currency", "op": "==", "value": "SAR"},
                        {"field": "checkout.total.amount", "op": "<=", "value": 60},
                    ],
                    "gate": {
                        "category": "purchase",
                        "material": {"merchant": "Matjar Pizza", "total": "checkout.total"},
                    },
                    "action": {"kind": "tap", "target": {"semantic_name": "place_order"}},
                    "retry": "none",
                    "verify": {"visible": {"semantic_name": "confirmation"}},
                    "on_action_uncertain": {"next": "reconcile_order"},
                    "next": "finish",
                },
                "finish": {
                    "expect": {"visible": {"semantic_name": "confirmation"}},
                    "terminal": "completed",
                },
                "reconcile_order": {"terminal": "outcome_unknown"},
            },
        }
    )


async def _system(tmp_path: Path, skill: Skill, backend: Backend, *, decision_ttl_s: int = 900):
    database = tmp_path / "runtime.sqlite3"
    keys = PublisherKeyPair.generate()
    registry = SkillRegistry(
        database,
        tmp_path / "skills",
        trust_policy=TrustPolicy({"tests": keys.public_key}),
    )
    signed = sign_skill(skill, publisher="tests", private_key=keys.private_key)
    registry.publish(signed.model_dump(mode="json", by_alias=True))
    traces = TraceStore(database)
    runtime = RuntimeSession(
        session_id="session-1",
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        trace_store=traces,
        element_dictionary=skill.elements,
    )
    await runtime.open()
    engine = SkillEngine(
        registry=registry,
        journal=RunJournal(database),
        approvals=ApprovalService(database, signing_secret=b"s" * 32),
        traces=traces,
        sessions=lambda _session_id: runtime,
        decision_ttl_s=decision_ttl_s,
    )
    return engine, runtime, signed


@pytest.mark.asyncio
async def test_model_free_happy_path_runs_to_completion(tmp_path: Path) -> None:
    backend = Backend()
    engine, runtime, signed = await _system(tmp_path, _simple_skill(), backend)
    result = await engine.start(
        RunRequest(session_id="session-1", skill=signed.metadata.name, version="1.0.0")
    )
    assert result.status == "completed"
    assert result.outputs["terminal"] == "completed"
    assert result.steps == 2
    assert backend.taps == 1
    events = runtime.trace(result.trace_id)
    assert events[0]["event_type"] == "run.started"
    assert events[-1]["event_type"] == "run.completed"


@pytest.mark.asyncio
async def test_purchase_requires_bound_approval_and_dispatches_once(tmp_path: Path) -> None:
    backend = Backend(mode="approval")
    engine, _runtime, signed = await _system(tmp_path, _approval_skill(), backend)
    paused = await engine.start(
        RunRequest(session_id="session-1", skill=signed.metadata.name, version="1.0.0")
    )
    assert paused.status == "approval_required"
    assert paused.pending is not None
    assert paused.pending["material"] == {
        "merchant": "Matjar Pizza",
        "total": {"amount": 55.2, "currency": "SAR", "raw": "55.20 SAR", "digits": "latin"},
    }
    assert backend.dispatches == 0
    token = engine.approve(paused.run_id, principal="approver", scopes={"approve"})
    completed = await engine.submit_approval(paused.run_id, token)
    assert completed.status == "completed"
    assert backend.dispatches == 1
    with pytest.raises(Exception, match="not waiting for approval"):
        await engine.submit_approval(paused.run_id, token)
    assert backend.dispatches == 1


@pytest.mark.asyncio
async def test_material_change_makes_approval_stale_without_dispatch(tmp_path: Path) -> None:
    backend = Backend(mode="approval")
    engine, _runtime, signed = await _system(tmp_path, _approval_skill(), backend)
    paused = await engine.start(
        RunRequest(session_id="session-1", skill=signed.metadata.name, version="1.0.0")
    )
    token = engine.approve(paused.run_id, principal="approver", scopes={"approve"})
    backend.total = "59.00 SAR"
    stale = await engine.submit_approval(paused.run_id, token)
    assert stale.status == "approval_required"
    assert stale.pending is not None and stale.pending["reason"] == "approval_stale"
    assert backend.dispatches == 0


@pytest.mark.asyncio
async def test_unknown_screen_is_durable_and_expiry_suspends_until_resume(tmp_path: Path) -> None:
    backend = Backend()
    backend.done = True
    engine, _runtime, signed = await _system(tmp_path, _simple_skill(), backend, decision_ttl_s=0)
    paused = await engine.start(
        RunRequest(session_id="session-1", skill=signed.metadata.name, version="1.0.0")
    )
    assert paused.status == "needs_decision"
    assert paused.state == "tap"
    suspended = engine.get(paused.run_id)
    assert suspended.status == "suspended"
    assert suspended.pending is not None
    resumed = await engine.resume(paused.run_id)
    assert resumed.status == "needs_decision"
    assert resumed.state == "tap"


@pytest.mark.asyncio
async def test_repeated_recovery_decision_does_not_dispatch_twice(tmp_path: Path) -> None:
    backend = Backend()
    backend.done = True
    engine, _runtime, signed = await _system(tmp_path, _simple_skill(), backend)
    paused = await engine.start(
        RunRequest(session_id="session-1", skill=signed.metadata.name, version="1.0.0")
    )
    decision = DecisionResponse.model_validate(
        {
            "action": {
                "action_id": "recovery-1",
                "kind": "tap",
                "target": {"selector": {"semantic_name": "done"}},
                "risk": {"category": "navigation", "gate": "none"},
            },
            "expect": {"visible": {"semantic_name": "done"}},
        }
    )

    paused_again = await engine.decide(paused.run_id, decision)
    assert paused_again.status == "needs_decision"
    assert backend.taps == 1

    repeated = await engine.decide(paused.run_id, decision)
    assert repeated.status == "needs_decision"
    assert backend.taps == 1
