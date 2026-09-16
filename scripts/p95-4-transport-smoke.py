#!/usr/bin/env python3
"""Exercise the installed HTTP and MCP adapters against one real Android device."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
from mcp import Client, StdioServerParameters

import haykal
from haykal.artifacts import ArtifactStore


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


async def _mcp_smoke(serial: str, state: Path, haykal_bin: Path) -> dict[str, object]:
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    parameters = StdioServerParameters(
        command=str(haykal_bin),
        args=[
            "--state-dir",
            str(state),
            "mcp",
            "--device",
            serial,
            "--session-id",
            "wheel-mcp",
        ],
        env=_clean_environment(),
    )
    async with Client(parameters, read_timeout_seconds=60) as client:
        result = await client.call_tool("observe", {"session_id": "wheel-mcp"})
    scene = result.structured_content
    if not isinstance(scene, dict) or not scene.get("scene_id"):
        raise RuntimeError("MCP observe returned no structured scene")
    return {
        "transport": "mcp-v2-stdio",
        "scene_id": scene["scene_id"],
        "elements": len(scene.get("elements", [])),
    }


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _http_smoke(serial: str, adb: str, state: Path, haykal_bin: Path) -> dict[str, object]:
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    command = [
        str(haykal_bin),
        "--state-dir",
        str(state),
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--token",
        "p95-4-wheel-caller",
        "--device-serial",
        serial,
        "--adb-path",
        adb,
    ]
    headers = {"Authorization": "Bearer p95-4-wheel-caller"}
    with (state / "server.stdout.log").open("wb") as stdout, (
        state / "server.stderr.log"
    ).open("wb") as stderr:
        process = subprocess.Popen(
            command,
            env=_clean_environment(),
            stdout=stdout,
            stderr=stderr,
        )
        try:
            with httpx.Client(base_url=base_url, timeout=30) as client:
                deadline = time.monotonic() + 60
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"HTTP server exited with {process.returncode}")
                    try:
                        readiness = client.get("/readyz")
                        if readiness.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError("HTTP server did not become ready")
                    time.sleep(0.25)
                created = client.post(
                    "/v1/sessions",
                    json={"device_serial": serial},
                    headers={**headers, "Idempotency-Key": "wheel-create"},
                )
                if created.status_code != 201:
                    raise RuntimeError(
                        f"HTTP session creation failed: {created.status_code}"
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
                    "transport": "http-socket",
                    "readiness": readiness.json()["status"],
                    "session_id": session_id,
                    "scene_id": observed.json()["scene_id"],
                    "idempotency_replayed": True,
                }
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--haykal-bin", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    ArtifactStore(args.state_dir / "artifacts")
    payload = {
        "schema_version": "1.0",
        "distribution_import": str(Path(haykal.__file__).resolve()),
        "http": _http_smoke(
            args.serial,
            args.adb,
            args.state_dir / "http",
            args.haykal_bin.resolve(),
        ),
        "mcp": asyncio.run(
            _mcp_smoke(args.serial, args.state_dir / "mcp", args.haykal_bin.resolve())
        ),
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
