from __future__ import annotations

import json

from haykal.contracts import Expectation, ExtractionRequest, SemanticAction
from haykal.sdk import HaykalClient


class Client(HaykalClient):
    def __init__(self) -> None:
        super().__init__("http://localhost", "secret")
        self.requests: list[tuple[str, str]] = []

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        *,
        idempotency_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        self.requests.append((method, path))
        if path == "/v1/sessions":
            value: object = {"session_id": "session"}
        elif path.endswith("/observe"):
            value = {
                "scene_id": "scene",
                "session_id": "session",
                "revision": 1,
                "digest": "sha256:" + "1" * 64,
                "quality": {"score": 1, "accessibility_coverage": 1},
                "elements": [],
            }
        elif path.endswith("/extract"):
            value = {
                "extraction_id": "extraction",
                "input_scene_id": "scene",
                "effective_scene_id": "scene",
                "scenes": ["scene"],
                "request_satisfied": True,
                "source_exhausted": True,
                "truncated": False,
                "stop_reason": "end_of_list",
                "records": [],
            }
        elif path.endswith("/actions"):
            value = {
                "action_id": "wait",
                "status": "verified",
                "attempts": 1,
                "started_at": "2026-09-13T00:00:00Z",
                "completed_at": "2026-09-13T00:00:01Z",
                "pre_scene": "scene",
                "post_scene": "scene",
                "trace_id": "trace",
            }
        elif path.endswith("/verify"):
            value = {"status": "passed", "scene_ids": ["scene"], "evidence": [], "elapsed_ms": 1}
        elif path.startswith("/v1/traces/"):
            value = [
                {
                    "run_id": "run",
                    "sequence": 1,
                    "event_type": "observation.created",
                    "occurred_at": "2026-09-13T00:00:00Z",
                    "payload": {},
                    "trace_id": "trace",
                    "artifacts": [],
                    "redaction": {"policy": "default", "applied": True},
                }
            ]
        else:
            value = {"closed": True}
        return json.dumps(value).encode()


def test_typed_sdk_methods() -> None:
    client = Client()
    assert client.create_session("emu") == "session"
    assert client.observe("session").scene_id == "scene"
    extraction = ExtractionRequest.model_validate(
        {
            "group": {"by": "single"},
            "fields": {"title": {"selector": {"text": {"contains": "x"}}, "type": "text"}},
        }
    )
    assert client.extract("session", extraction).extraction_id == "extraction"
    action = SemanticAction.model_validate(
        {
            "action_id": "wait",
            "kind": "wait",
            "wait_ms": 1,
            "risk": {"category": "navigation", "gate": "none"},
        }
    )
    assert client.act("session", action, run_id="run").status == "verified"
    assert client.verify("session", Expectation(scene_stable=True)).status == "passed"
    assert client.trace("trace")[0].sequence == 1
    client.close_session("session")
    assert len(client.requests) == 7
