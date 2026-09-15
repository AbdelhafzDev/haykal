#!/usr/bin/env python3
"""Exercise the installed HTTP and MCP adapters against one real Android device."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mcp import Client
from starlette.testclient import TestClient

import haykal
from haykal.artifacts import ArtifactStore
from haykal.hardening import AndroidDeviceDiagnostics, Diagnostics
from haykal.runtime import build_runtime
from haykal.traces import TraceStore
from haykal.transports.http import IdempotencyStore, SessionRegistry, create_app
from haykal.transports.mcp import create_mcp_server


async def _mcp_smoke(serial: str, state: Path) -> dict[str, object]:
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    runtime = build_runtime(serial=serial, session_id="wheel-mcp", state_directory=state)
    await runtime.open()
    try:
        server = create_mcp_server(
            lambda session_id: runtime if session_id == "wheel-mcp" else None
        )
        async with Client(server) as client:
            result = await client.call_tool("observe", {"session_id": "wheel-mcp"})
        scene = result.structured_content
        if not isinstance(scene, dict) or not scene.get("scene_id"):
            raise RuntimeError("MCP observe returned no structured scene")
        return {
            "transport": "mcp-v2-in-process",
            "scene_id": scene["scene_id"],
            "elements": len(scene.get("elements", [])),
        }
    finally:
        await runtime.close()


def _http_smoke(serial: str, adb: str, state: Path) -> dict[str, object]:
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    ArtifactStore(state / "artifacts").put(b"p95-4-readiness-probe")

    async def factory(session_id: str, target: str):
        return build_runtime(serial=target, session_id=session_id, state_directory=state)

    database = state / "runtime.sqlite3"
    app = create_app(
        sessions=SessionRegistry(factory),
        idempotency=IdempotencyStore(database),
        traces=TraceStore(database),
        bearer_token="p95-4-wheel-caller",
        diagnostics=Diagnostics(
            state,
            minimum_free_bytes=1,
            device_probe=AndroidDeviceDiagnostics(serial, database, adb_path=adb),
        ),
    )
    headers = {"Authorization": "Bearer p95-4-wheel-caller"}
    with TestClient(app) as client:
        readiness = client.get("/readyz")
        created = client.post(
            "/v1/sessions",
            json={"device_serial": serial},
            headers={**headers, "Idempotency-Key": "wheel-create"},
        )
        if readiness.status_code != 200 or created.status_code != 201:
            raise RuntimeError(
                f"HTTP readiness/session failed: {readiness.status_code}/{created.status_code}"
            )
        session_id = created.json()["session_id"]
        observed = client.post(
            f"/v1/sessions/{session_id}/observe",
            json={},
            headers={**headers, "Idempotency-Key": "wheel-observe"},
        )
        if observed.status_code != 200 or not observed.json().get("scene_id"):
            raise RuntimeError(f"HTTP observe failed: {observed.status_code}")
        replay = client.post(
            f"/v1/sessions/{session_id}/observe",
            json={},
            headers={**headers, "Idempotency-Key": "wheel-observe"},
        )
        if replay.headers.get("idempotency-replayed") != "true":
            raise RuntimeError("HTTP idempotency replay was not reported")
        return {
            "transport": "http",
            "readiness": readiness.json()["status"],
            "session_id": session_id,
            "scene_id": observed.json()["scene_id"],
            "idempotency_replayed": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    ArtifactStore(args.state_dir / "artifacts")
    payload = {
        "schema_version": "1.0",
        "distribution_import": str(Path(haykal.__file__).resolve()),
        "http": _http_smoke(args.serial, args.adb, args.state_dir / "http"),
        "mcp": asyncio.run(_mcp_smoke(args.serial, args.state_dir / "mcp")),
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
