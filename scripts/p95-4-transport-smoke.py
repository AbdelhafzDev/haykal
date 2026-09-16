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
import urllib.error
import urllib.request
from pathlib import Path

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


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], dict[str, object]]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = json.loads(response.read())
        return int(response.status), dict(response.headers.items()), body


def _http_smoke(serial: str, adb: str, state: Path, haykal_bin: Path) -> dict[str, object]:
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    ArtifactStore(state / "artifacts").put(b"p95-4-readiness-probe")
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
            deadline = time.monotonic() + 60
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"HTTP server exited with {process.returncode}")
                try:
                    ready_status, _, readiness = _request(base_url, "GET", "/readyz")
                    if ready_status == 200:
                        break
                except urllib.error.URLError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("HTTP server did not become ready")
                time.sleep(0.25)
            created_status, _, created = _request(
                base_url,
                "POST",
                "/v1/sessions",
                headers={**headers, "Idempotency-Key": "wheel-create"},
                payload={"device_serial": serial},
            )
            if created_status != 201:
                raise RuntimeError(f"HTTP session creation failed: {created_status}")
            session_id = created["session_id"]
            observed_status, _, observed = _request(
                base_url,
                "POST",
                f"/v1/sessions/{session_id}/observe",
                headers={**headers, "Idempotency-Key": "wheel-observe"},
                payload={},
            )
            if observed_status != 200 or not observed.get("scene_id"):
                raise RuntimeError(f"HTTP observe failed: {observed_status}")
            _, replay_headers, _ = _request(
                base_url,
                "POST",
                f"/v1/sessions/{session_id}/observe",
                headers={**headers, "Idempotency-Key": "wheel-observe"},
                payload={},
            )
            replayed = next(
                (
                    value
                    for key, value in replay_headers.items()
                    if key.casefold() == "idempotency-replayed"
                ),
                None,
            )
            if replayed != "true":
                raise RuntimeError("HTTP idempotency replay was not reported")
            return {
                "transport": "http-socket",
                "readiness": readiness["status"],
                "session_id": session_id,
                "scene_id": observed["scene_id"],
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
