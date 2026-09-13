from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from haykal.contracts import (
    ActionResult,
    ExpectationResult,
    ExtractionResult,
    RunSnapshot,
    SemanticScene,
)
from haykal.hardening import Diagnostics
from haykal.traces import TraceStore
from haykal.transports.http import IdempotencyStore, SessionRegistry, create_app


class Session:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.opened = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False

    async def observe(self) -> SemanticScene:
        return SemanticScene(
            scene_id="scene",
            session_id=self.session_id,
            revision=1,
            digest="sha256:" + "1" * 64,
            quality={"score": 1, "accessibility_coverage": 1},
            elements=[],
        )

    async def extract(self, request: object) -> ExtractionResult:
        return ExtractionResult(
            extraction_id="extraction",
            input_scene_id="scene",
            effective_scene_id="scene",
            scenes=["scene"],
            request_satisfied=True,
            source_exhausted=True,
            truncated=False,
            stop_reason="end_of_list",
            records=[],
        )

    async def act(self, action: object, *, run_id: str | None = None) -> ActionResult:
        return ActionResult(
            action_id="wait",
            status="verified",
            attempts=1,
            started_at="2026-09-13T00:00:00Z",
            completed_at="2026-09-13T00:00:01Z",
            pre_scene="scene",
            post_scene="scene",
            trace_id="trace",
        )

    async def verify(self, expectation: object) -> ExpectationResult:
        return ExpectationResult(status="passed", scene_ids=["scene"], elapsed_ms=1)


class WorkflowEngine:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.snapshot = RunSnapshot(
            run_id="run-skill",
            trace_id="trace-skill",
            session_id="session",
            skill="matjar.list_pizza_offers@1.0.0",
            skill_digest="sha256:" + "a" * 64,
            state="collect",
            status="approval_required",
            pending={
                "schema_version": "1.0",
                "gate_id": "gate-1",
                "run_id": "run-skill",
                "skill_digest": "sha256:" + "a" * 64,
                "action_intent_digest": "sha256:" + "b" * 64,
                "target_fingerprint": "sha256:" + "c" * 64,
                "material": {"total": {"amount": 55.2, "currency": "SAR"}},
                "material_digest": "sha256:" + "d" * 64,
                "evidence_scene_digest": "sha256:" + "e" * 64,
                "expires_at": now.isoformat(),
                "nonce": "nonce-1",
            },
            created_at=now,
            updated_at=now,
        )
        self.approvals = 0

    async def start(self, request: object) -> RunSnapshot:
        return self.snapshot

    def get(self, run_id: str) -> RunSnapshot:
        if run_id != self.snapshot.run_id:
            raise LookupError(run_id)
        return self.snapshot

    async def decide(self, run_id: str, decision: object) -> RunSnapshot:
        return self.snapshot.model_copy(update={"status": "cancelled"})

    async def resume(self, run_id: str) -> RunSnapshot:
        return self.snapshot

    def approve(
        self,
        run_id: str,
        *,
        principal: str,
        scopes: set[str],
        presented: object,
    ) -> str:
        self.approvals += 1
        return "one-time-token"

    async def submit_approval(self, run_id: str, token: str) -> RunSnapshot:
        return self.snapshot.model_copy(update={"status": "completed", "pending": None})


def test_authentication_and_durable_idempotency_replay(tmp_path: Path) -> None:
    created: list[Session] = []

    async def factory(session_id: str, _serial: str) -> Session:
        session = Session(session_id)
        created.append(session)
        return session

    database = tmp_path / "runtime.sqlite3"
    registry = SessionRegistry(factory)  # type: ignore[arg-type]
    app = create_app(
        sessions=registry,
        idempotency=IdempotencyStore(database),
        traces=TraceStore(database),
        bearer_token="secret",
    )
    with TestClient(app) as client:
        assert client.post("/v1/sessions", json={"device_serial": "emu"}).status_code == 401
        headers = {"Authorization": "Bearer secret", "Idempotency-Key": "create-1"}
        first = client.post("/v1/sessions", json={"device_serial": "emu"}, headers=headers)
        second = client.post("/v1/sessions", json={"device_serial": "emu"}, headers=headers)
        conflict = client.post("/v1/sessions", json={"device_serial": "other"}, headers=headers)
        assert first.status_code == 201
        assert second.json() == first.json()
        assert second.headers["idempotency-replayed"] == "true"
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        assert len(created) == 1
    assert created[0].opened is False


def test_health_is_minimal_and_diagnostics_require_authentication(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)

    async def factory(session_id: str, _serial: str) -> Session:
        return Session(session_id)

    app = create_app(
        sessions=SessionRegistry(factory),  # type: ignore[arg-type]
        idempotency=IdempotencyStore(state / "runtime.sqlite3"),
        traces=TraceStore(state / "runtime.sqlite3"),
        bearer_token="secret",
        diagnostics=Diagnostics(state, minimum_free_bytes=1),
    )
    with TestClient(app) as client:
        public = client.get("/healthz")
        assert public.status_code == 200
        assert "generated_at" not in public.json()
        assert client.get("/v1/diagnostics").status_code == 401
        detailed = client.get("/v1/diagnostics", headers={"Authorization": "Bearer secret"})
        assert detailed.status_code == 200
        assert detailed.json()["checks"]


def test_approval_authority_cannot_reuse_the_caller_credential(tmp_path: Path) -> None:
    async def factory(session_id: str, _serial: str) -> Session:
        return Session(session_id)

    database = tmp_path / "runtime.sqlite3"
    with pytest.raises(ValueError, match="credentials must be different"):
        create_app(
            sessions=SessionRegistry(factory),  # type: ignore[arg-type]
            idempotency=IdempotencyStore(database),
            traces=TraceStore(database),
            bearer_token="same",
            approver_token="same",
        )


def test_primitive_routes_trace_and_sse(tmp_path: Path) -> None:
    async def factory(session_id: str, _serial: str) -> Session:
        return Session(session_id)

    database = tmp_path / "runtime.sqlite3"
    traces = TraceStore(database)
    trace = traces.append(
        trace_id="trace-1",
        run_id="run-1",
        event_type="observation.created",
        payload={"scene_id": "scene", "token": "never-return-this"},
    )
    app = create_app(
        sessions=SessionRegistry(factory),  # type: ignore[arg-type]
        idempotency=IdempotencyStore(database),
        traces=traces,
        bearer_token="secret",
    )
    auth = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/sessions",
            json={"device_serial": "emu"},
            headers={**auth, "Idempotency-Key": "1"},
        ).json()
        prefix = f"/v1/sessions/{created['session_id']}"
        observed = client.post(
            f"{prefix}/observe", json={}, headers={**auth, "Idempotency-Key": "2"}
        )
        assert observed.json()["scene_id"] == "scene"
        extracted = client.post(
            f"{prefix}/extract",
            json={
                "group": {"by": "single"},
                "fields": {"title": {"selector": {"text": {"contains": "x"}}, "type": "text"}},
            },
            headers={**auth, "Idempotency-Key": "3"},
        )
        assert extracted.json()["request_satisfied"] is True
        acted = client.post(
            f"{prefix}/actions",
            json={
                "action_id": "wait",
                "kind": "wait",
                "wait_ms": 1,
                "risk": {"category": "navigation", "gate": "none"},
            },
            headers={**auth, "Idempotency-Key": "4"},
        )
        assert acted.json()["status"] == "verified"
        verified = client.post(
            f"{prefix}/verify",
            json={"scene_stable": True},
            headers={**auth, "Idempotency-Key": "5"},
        )
        assert verified.json()["status"] == "passed"
        trace_payload = client.get("/v1/traces/trace-1", headers=auth).json()[0]
        assert trace_payload["sequence"] == trace.sequence
        assert trace_payload["payload"]["token"] == "<redacted>"
        stream = client.get("/v1/runs/run-1/events?once=true", headers=auth)
        assert "event: observation.created" in stream.text
        closed = client.request("DELETE", prefix, json={}, headers={**auth, "Idempotency-Key": "6"})
        assert closed.json() == {"closed": True}


def test_skill_routes_and_separate_approver_authority(tmp_path: Path) -> None:
    async def factory(session_id: str, _serial: str) -> Session:
        return Session(session_id)

    database = tmp_path / "runtime.sqlite3"
    engine = WorkflowEngine()
    app = create_app(
        sessions=SessionRegistry(factory),  # type: ignore[arg-type]
        idempotency=IdempotencyStore(database),
        traces=TraceStore(database),
        bearer_token="caller",
        skill_engine=engine,  # type: ignore[arg-type]
        approver_token="approver",
    )
    caller = {"Authorization": "Bearer caller", "Idempotency-Key": "run-1"}
    with TestClient(app) as client:
        created = client.post(
            "/v1/runs",
            json={
                "session_id": "session",
                "skill": "matjar.list_pizza_offers",
                "version": "1.0.0",
            },
            headers=caller,
        )
        assert created.status_code == 201
        assert created.json()["run_id"] == "run-skill"
        assert (
            client.get("/v1/runs/run-skill", headers={"Authorization": "Bearer caller"}).status_code
            == 200
        )
        denied = client.post(
            "/v1/runs/run-skill/approvals",
            json={},
            headers={"Authorization": "Bearer caller", "Idempotency-Key": "approve-1"},
        )
        assert denied.status_code == 401
        approver_auth = {"Authorization": "Bearer approver"}
        challenge = client.get(
            "/v1/runs/run-skill/approval",
            headers=approver_auth,
        ).json()
        approved = client.post(
            "/v1/runs/run-skill/approvals",
            json={"gate_id": challenge["gate_id"], "challenge": challenge},
            headers={**approver_auth, "Idempotency-Key": "approve-1"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"
        assert engine.approvals == 1
