"""Loopback-first Starlette API over the canonical runtime session."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from haykal.authoring import lint_skill
from haykal.contracts import (
    ApprovalGrantRequest,
    DecisionResponse,
    Expectation,
    ExtractionRequest,
    RunRequest,
    SemanticAction,
)
from haykal.hardening import Diagnostics, RedactionPolicy, Redactor
from haykal.runtime import RuntimeSession
from haykal.traces import TraceStore
from haykal.workflows import ApprovalError, InvalidDecision, SkillEngine, public_run

from .idempotency import (
    CachedResponse,
    IdempotencyConflict,
    IdempotencyInProgress,
    IdempotencyStore,
)

SessionFactory = Callable[[str, str], Awaitable[RuntimeSession]]


class SessionRegistry:
    def __init__(self, factory: SessionFactory) -> None:
        self._factory = factory
        self._sessions: dict[str, RuntimeSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, device_serial: str) -> RuntimeSession:
        session_id = f"ses_{uuid.uuid4().hex}"
        session = await self._factory(session_id, device_serial)
        await session.open()
        async with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> RuntimeSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise LookupError(f"session {session_id!r} was not found") from exc

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            raise LookupError(f"session {session_id!r} was not found")
        await session.close()

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)


def _error(code: str, detail: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "detail": detail, "retryable": False}},
        status_code=status,
    )


def create_app(
    *,
    sessions: SessionRegistry,
    idempotency: IdempotencyStore,
    traces: TraceStore,
    bearer_token: str,
    skill_engine: SkillEngine | None = None,
    approver_token: str | None = None,
    diagnostics: Diagnostics | None = None,
    redaction_policy: RedactionPolicy | None = None,
) -> Starlette:
    """Create an authenticated API; deploy it on loopback unless TLS is terminated."""

    if not bearer_token:
        raise ValueError("bearer_token must not be empty")
    if approver_token is not None and hmac.compare_digest(approver_token, bearer_token):
        raise ValueError("caller and approver credentials must be different")
    redactor = Redactor(redaction_policy or RedactionPolicy())

    def authorized(request: Request, expected_token: str = bearer_token) -> bool:
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {expected_token}"
        return hmac.compare_digest(supplied, expected)

    async def mutate(
        request: Request,
        operation: Callable[[bytes], Awaitable[tuple[int, object]]],
        *,
        expected_token: str = bearer_token,
    ) -> Response:
        if not authorized(request, expected_token):
            return _error("unauthorized", "valid bearer token required", 401)
        principal = hashlib.sha256(expected_token.encode()).hexdigest()
        key = request.headers.get("idempotency-key")
        if not key:
            return _error("idempotency_key_required", "Idempotency-Key is required", 400)
        body = await request.body()
        digest = idempotency.digest(method=request.method, path=request.url.path, body=body)
        try:
            cached = idempotency.claim(principal, key, digest)
        except IdempotencyConflict as exc:
            return _error("idempotency_conflict", str(exc), 409)
        except IdempotencyInProgress as exc:
            return _error("outcome_unknown", str(exc), 409)
        if cached is not None:
            return Response(
                cached.body,
                status_code=cached.status_code,
                media_type=cached.media_type,
                headers={"Idempotency-Replayed": "true"},
            )
        try:
            status, value = await operation(body)
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        except (
            ApprovalError,
            InvalidDecision,
            ValidationError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            status = 422
            encoded = json.dumps(
                {
                    "error": {
                        "code": "invalid_request",
                        "detail": str(exc),
                        "retryable": False,
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        except LookupError as exc:
            status = 404
            encoded = json.dumps(
                {"error": {"code": "not_found", "detail": str(exc), "retryable": False}},
                separators=(",", ":"),
            ).encode()
        except Exception as exc:
            status = 500
            encoded = json.dumps(
                {
                    "error": {
                        "code": "internal_error",
                        "detail": type(exc).__name__,
                        "retryable": False,
                    }
                },
                separators=(",", ":"),
            ).encode()
        response = CachedResponse(status, "application/json", encoded)
        idempotency.complete(principal, key, digest, response)
        return Response(encoded, status_code=status, media_type="application/json")

    def session_for(request: Request) -> RuntimeSession:
        return sessions.get(request.path_params["session_id"])

    async def live(_request: Request) -> Response:
        return JSONResponse({"status": "live"})

    async def health(_request: Request) -> Response:
        if diagnostics is None:
            return JSONResponse({"status": "degraded", "version": "unknown", "checks": {}})
        report = await asyncio.to_thread(diagnostics.run)
        status = 503 if report.status == "unhealthy" else 200
        return JSONResponse(report.as_dict(public=True), status_code=status)

    async def ready(_request: Request) -> Response:
        if diagnostics is None:
            return JSONResponse(
                {"status": "unhealthy", "version": "unknown", "checks": {}},
                status_code=503,
            )
        report = await asyncio.to_thread(diagnostics.run)
        status = 200 if report.status == "ready" else 503
        return JSONResponse(report.as_dict(public=True), status_code=status)

    async def detailed_diagnostics(request: Request) -> Response:
        if not authorized(request):
            return _error("unauthorized", "valid bearer token required", 401)
        if diagnostics is None:
            return _error("not_found", "diagnostics are not configured", 404)
        report = await asyncio.to_thread(diagnostics.run)
        status = 503 if report.status == "unhealthy" else 200
        return JSONResponse(report.as_dict(), status_code=status)

    async def create_session(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            payload = json.loads(body or b"{}")
            serial = payload.get("device_serial")
            if not isinstance(serial, str) or not serial:
                raise ValueError("device_serial is required")
            session = await sessions.create(serial)
            return 201, {"session_id": session.session_id, "device_serial": serial}

        return await mutate(request, operation)

    async def observe(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            payload = json.loads(body or b"{}")
            require_vision = payload.get("require_vision", False)
            if not isinstance(require_vision, bool) or set(payload) - {"require_vision"}:
                raise ValueError("observe accepts only a boolean require_vision field")
            session = session_for(request)
            scene = (
                await session.observe(require_vision=True)
                if require_vision
                else await session.observe()
            )
            return 200, scene.model_dump(mode="json")

        return await mutate(request, operation)

    async def extract(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            result = await session_for(request).extract(ExtractionRequest.model_validate_json(body))
            return 200, result.model_dump(mode="json")

        return await mutate(request, operation)

    async def act(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            result = await session_for(request).act(
                SemanticAction.model_validate_json(body),
                run_id=request.headers.get("x-haykal-run-id"),
            )
            return 200, result.model_dump(mode="json")

        return await mutate(request, operation)

    async def verify(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            result = await session_for(request).verify(Expectation.model_validate_json(body))
            return 200, result.model_dump(mode="json")

        return await mutate(request, operation)

    async def delete_session(request: Request) -> Response:
        async def operation(_body: bytes) -> tuple[int, object]:
            await sessions.remove(request.path_params["session_id"])
            return 200, {"closed": True}

        return await mutate(request, operation)

    async def get_trace(request: Request) -> Response:
        if not authorized(request):
            return _error("unauthorized", "valid bearer token required", 401)
        events = traces.read(request.path_params["trace_id"])
        if not events:
            return _error("not_found", "trace was not found", 404)
        return JSONResponse([redactor.redact_event(event) for event in events])

    async def events(request: Request) -> Response:
        if not authorized(request):
            return _error("unauthorized", "valid bearer token required", 401)
        run_id = request.path_params["run_id"]
        raw_cursor = request.headers.get("last-event-id", "0")
        try:
            cursor = max(0, int(raw_cursor))
        except ValueError:
            return _error("invalid_event_cursor", "Last-Event-ID must be an integer", 400)
        once = request.query_params.get("once") == "true"

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor
            idle = 0
            while True:
                emitted = traces.read_run(run_id, after_sequence=cursor)
                if emitted:
                    idle = 0
                    for event in emitted:
                        cursor = event.sequence
                        data = json.dumps(
                            redactor.redact_event(event),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            default=str,
                        )
                        yield f"id: {cursor}\nevent: {event.event_type}\ndata: {data}\n\n"
                    if once:
                        return
                else:
                    if once:
                        return
                    idle += 1
                    if idle >= 60:
                        yield ": keep-alive\n\n"
                        idle = 0
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def create_run(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            if skill_engine is None:
                raise LookupError("skill runtime is not configured")
            snapshot = await skill_engine.start(RunRequest.model_validate_json(body))
            return 201, public_run(snapshot).model_dump(mode="json")

        return await mutate(request, operation)

    async def get_run(request: Request) -> Response:
        if not authorized(request):
            return _error("unauthorized", "valid bearer token required", 401)
        if skill_engine is None:
            return _error("not_found", "skill runtime is not configured", 404)
        try:
            return JSONResponse(
                public_run(skill_engine.get(request.path_params["run_id"])).model_dump(mode="json")
            )
        except LookupError as exc:
            return _error("not_found", str(exc), 404)

    async def decide_run(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            if skill_engine is None:
                raise LookupError("skill runtime is not configured")
            snapshot = await skill_engine.decide(
                request.path_params["run_id"], DecisionResponse.model_validate_json(body)
            )
            return 200, public_run(snapshot).model_dump(mode="json")

        return await mutate(request, operation)

    async def resume_run(request: Request) -> Response:
        async def operation(_body: bytes) -> tuple[int, object]:
            if skill_engine is None:
                raise LookupError("skill runtime is not configured")
            snapshot = await skill_engine.resume(request.path_params["run_id"])
            return 200, public_run(snapshot).model_dump(mode="json")

        return await mutate(request, operation)

    async def approve_run(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            if skill_engine is None:
                raise LookupError("skill runtime is not configured")
            run_id = request.path_params["run_id"]
            confirmation = ApprovalGrantRequest.model_validate_json(body)
            token = skill_engine.approve(
                run_id,
                principal="http-approver",
                scopes={"approve"},
                presented=confirmation.challenge,
            )
            snapshot = await skill_engine.submit_approval(run_id, token)
            return 200, public_run(snapshot).model_dump(mode="json")

        if approver_token is None:
            return _error("not_found", "approval authority is not configured", 404)
        return await mutate(request, operation, expected_token=approver_token)

    async def get_approval(request: Request) -> Response:
        if approver_token is None or not authorized(request, approver_token):
            return _error("unauthorized", "valid approver token required", 401)
        if skill_engine is None:
            return _error("not_found", "skill runtime is not configured", 404)
        try:
            snapshot = skill_engine.get(request.path_params["run_id"])
        except LookupError as exc:
            return _error("not_found", str(exc), 404)
        if snapshot.status != "approval_required" or snapshot.pending is None:
            return _error("approval_not_required", "run is not waiting for approval", 409)
        return JSONResponse(
            {
                name: snapshot.pending[name]
                for name in (
                    "schema_version",
                    "gate_id",
                    "run_id",
                    "skill_digest",
                    "action_intent_digest",
                    "target_fingerprint",
                    "material",
                    "material_digest",
                    "evidence_scene_digest",
                    "expires_at",
                    "nonce",
                )
            }
        )

    async def validate_skill(request: Request) -> Response:
        async def operation(body: bytes) -> tuple[int, object]:
            skill, issues = lint_skill(json.loads(body))
            return 200, {
                "valid": skill is not None and not issues,
                "issues": [issue.as_dict() for issue in issues],
            }

        return await mutate(request, operation)

    routes = [
        Route("/livez", live, methods=["GET"]),
        Route("/healthz", health, methods=["GET"]),
        Route("/readyz", ready, methods=["GET"]),
        Route("/v1/diagnostics", detailed_diagnostics, methods=["GET"]),
        Route("/v1/sessions", create_session, methods=["POST"]),
        Route("/v1/sessions/{session_id:str}/observe", observe, methods=["POST"]),
        Route("/v1/sessions/{session_id:str}/extract", extract, methods=["POST"]),
        Route("/v1/sessions/{session_id:str}/actions", act, methods=["POST"]),
        Route("/v1/sessions/{session_id:str}/verify", verify, methods=["POST"]),
        Route("/v1/sessions/{session_id:str}", delete_session, methods=["DELETE"]),
        Route("/v1/skills/validate", validate_skill, methods=["POST"]),
        Route("/v1/runs", create_run, methods=["POST"]),
        Route("/v1/runs/{run_id:str}", get_run, methods=["GET"]),
        Route("/v1/runs/{run_id:str}/decisions", decide_run, methods=["POST"]),
        Route("/v1/runs/{run_id:str}/resume", resume_run, methods=["POST"]),
        Route("/v1/runs/{run_id:str}/approval", get_approval, methods=["GET"]),
        Route("/v1/runs/{run_id:str}/approvals", approve_run, methods=["POST"]),
        Route("/v1/runs/{run_id:str}/events", events, methods=["GET"]),
        Route("/v1/traces/{trace_id:str}", get_trace, methods=["GET"]),
    ]

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await sessions.close_all()

    return Starlette(routes=routes, lifespan=lifespan)
