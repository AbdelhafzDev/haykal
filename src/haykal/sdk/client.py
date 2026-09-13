"""Dependency-light synchronous HTTP client with typed results."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import TypeVar, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import BaseModel

from haykal.contracts import (
    ActionResult,
    ApprovalChallenge,
    DecisionResponse,
    Expectation,
    ExpectationResult,
    ExtractionRequest,
    ExtractionResult,
    RunRequest,
    RunSnapshot,
    SemanticAction,
    SemanticScene,
    TraceEnvelope,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class HaykalHTTPError(RuntimeError):
    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(f"Haykal HTTP {status}: {body.decode(errors='replace')}")
        self.status = status
        self.body = body


class HaykalClient:
    def __init__(self, base_url: str, token: str, *, timeout_s: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_s

    def create_session(self, device_serial: str, *, idempotency_key: str | None = None) -> str:
        payload = self._post(
            "/v1/sessions",
            {"device_serial": device_serial},
            idempotency_key=idempotency_key,
        )
        return str(payload["session_id"])

    def observe(self, session_id: str, *, idempotency_key: str | None = None) -> SemanticScene:
        return self._model(
            SemanticScene,
            self._post(
                f"/v1/sessions/{session_id}/observe",
                {},
                idempotency_key=idempotency_key,
            ),
        )

    def extract(
        self,
        session_id: str,
        request: ExtractionRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ExtractionResult:
        return self._model(
            ExtractionResult,
            self._post(
                f"/v1/sessions/{session_id}/extract",
                request.model_dump(mode="json", by_alias=True),
                idempotency_key=idempotency_key,
            ),
        )

    def act(
        self,
        session_id: str,
        action: SemanticAction,
        *,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ActionResult:
        headers = {"X-Haykal-Run-ID": run_id} if run_id else None
        return self._model(
            ActionResult,
            self._post(
                f"/v1/sessions/{session_id}/actions",
                action.model_dump(mode="json", by_alias=True),
                idempotency_key=idempotency_key,
                headers=headers,
            ),
        )

    def verify(
        self,
        session_id: str,
        expectation: Expectation,
        *,
        idempotency_key: str | None = None,
    ) -> ExpectationResult:
        return self._model(
            ExpectationResult,
            self._post(
                f"/v1/sessions/{session_id}/verify",
                expectation.model_dump(mode="json", by_alias=True),
                idempotency_key=idempotency_key,
            ),
        )

    def trace(self, trace_id: str) -> list[TraceEnvelope]:
        return [TraceEnvelope.model_validate(item) for item in self._get(f"/v1/traces/{trace_id}")]

    def run_skill(
        self,
        request: RunRequest,
        *,
        idempotency_key: str | None = None,
    ) -> RunSnapshot:
        return self._model(
            RunSnapshot,
            self._post(
                "/v1/runs",
                request.model_dump(mode="json"),
                idempotency_key=idempotency_key,
            ),
        )

    def get_run(self, run_id: str) -> RunSnapshot:
        return self._model(RunSnapshot, self._get_object(f"/v1/runs/{run_id}"))

    def decide(
        self,
        run_id: str,
        decision: DecisionResponse,
        *,
        idempotency_key: str | None = None,
    ) -> RunSnapshot:
        return self._model(
            RunSnapshot,
            self._post(
                f"/v1/runs/{run_id}/decisions",
                decision.model_dump(mode="json", exclude_none=True),
                idempotency_key=idempotency_key,
            ),
        )

    def resume_run(self, run_id: str, *, idempotency_key: str | None = None) -> RunSnapshot:
        return self._model(
            RunSnapshot,
            self._post(f"/v1/runs/{run_id}/resume", {}, idempotency_key=idempotency_key),
        )

    def approval_challenge(self, run_id: str) -> ApprovalChallenge:
        return self._model(
            ApprovalChallenge,
            self._get_object(f"/v1/runs/{run_id}/approval"),
        )

    def approve_run(
        self,
        run_id: str,
        challenge: ApprovalChallenge,
        *,
        idempotency_key: str | None = None,
    ) -> RunSnapshot:
        return self._model(
            RunSnapshot,
            self._post(
                f"/v1/runs/{run_id}/approvals",
                {
                    "gate_id": challenge.gate_id,
                    "challenge": challenge.model_dump(mode="json"),
                },
                idempotency_key=idempotency_key,
            ),
        )

    def events(self, run_id: str, *, after_sequence: int = 0) -> Iterator[TraceEnvelope]:
        request = Request(
            f"{self._base_url}/v1/runs/{run_id}/events",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "text/event-stream",
                "Last-Event-ID": str(after_sequence),
            },
        )
        try:
            response = urlopen(request, timeout=self._timeout)
        except HTTPError as exc:
            raise HaykalHTTPError(exc.code, exc.read()) from exc
        with response:
            for raw_line in response:
                line = raw_line.decode().strip()
                if line.startswith("data: "):
                    yield TraceEnvelope.model_validate_json(line.removeprefix("data: "))

    def close_session(self, session_id: str, *, idempotency_key: str | None = None) -> None:
        self._request(
            "DELETE",
            f"/v1/sessions/{session_id}",
            b"{}",
            idempotency_key=idempotency_key or uuid.uuid4().hex,
        )

    def _post(
        self,
        path: str,
        payload: object,
        *,
        idempotency_key: str | None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        encoded = self._request(
            "POST",
            path,
            body,
            idempotency_key=idempotency_key or uuid.uuid4().hex,
            headers=headers,
        )
        decoded = json.loads(encoded)
        if not isinstance(decoded, dict):
            raise ValueError("Haykal response must be a JSON object")
        return cast(dict[str, object], decoded)

    def _get(self, path: str) -> list[object]:
        decoded = json.loads(self._request("GET", path, None))
        if not isinstance(decoded, list):
            raise ValueError("Haykal response must be a JSON array")
        return cast(list[object], decoded)

    def _get_object(self, path: str) -> dict[str, object]:
        decoded = json.loads(self._request("GET", path, None))
        if not isinstance(decoded, dict):
            raise ValueError("Haykal response must be a JSON object")
        return cast(dict[str, object], decoded)

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        *,
        idempotency_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        request_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            request_headers["Idempotency-Key"] = idempotency_key
        request_headers.update(headers or {})
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            method=method,
            headers=request_headers,
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return cast(bytes, response.read())
        except HTTPError as exc:
            raise HaykalHTTPError(exc.code, exc.read()) from exc

    @staticmethod
    def _model(model: type[ModelT], payload: object) -> ModelT:
        return model.model_validate(payload)
