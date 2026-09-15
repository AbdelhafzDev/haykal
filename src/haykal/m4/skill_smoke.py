"""Run one signed Matjar reference skill through the production runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path

import yaml
from uiautomator2 import connect  # type: ignore[import-untyped]

from haykal.contracts import RunRequest, Skill
from haykal.runtime import build_runtime
from haykal.skills import PublisherKeyPair, SkillRegistry, TrustPolicy, sign_skill
from haykal.traces import TraceStore
from haykal.workflows import ApprovalService, RunJournal, SkillEngine


async def run_smoke(
    *,
    serial: str,
    skill_path: Path,
    state_directory: Path,
    inputs: dict[str, object],
    approve_gate: bool = False,
    stale_gate: bool = False,
) -> dict[str, object]:
    run_root = state_directory / f"run-{uuid.uuid4().hex}"
    run_root.mkdir(parents=True, exist_ok=False)
    database = run_root / "runtime.sqlite3"
    keys = PublisherKeyPair.generate()
    registry = SkillRegistry(
        database,
        run_root / "skill-objects",
        trust_policy=TrustPolicy({"haykal.reference": keys.public_key}),
    )
    payload = yaml.safe_load(skill_path.read_text(encoding="utf-8"))
    skill = Skill.model_validate(payload)
    signed = sign_skill(
        skill,
        publisher="haykal.reference",
        private_key=keys.private_key,
    )
    registry.publish(signed.model_dump(mode="json", by_alias=True))
    traces = TraceStore(database)
    runtime = build_runtime(
        serial=serial,
        session_id=f"m4_{uuid.uuid4().hex}",
        state_directory=run_root,
    )
    await runtime.open()
    try:
        engine = SkillEngine(
            registry=registry,
            journal=RunJournal(database),
            approvals=ApprovalService(database, signing_secret=uuid.uuid4().bytes * 2),
            traces=traces,
            sessions=lambda _session_id: runtime,
        )
        result = await engine.start(
            RunRequest(
                session_id=runtime.session_id,
                skill=signed.metadata.name,
                version=signed.metadata.version,
                inputs=inputs,
            )
        )
        if approve_gate and result.status == "approval_required":
            token = engine.approve(
                result.run_id,
                principal="haykal-reference-approver",
                scopes={"approve"},
            )
            if stale_gate:
                _change_checkout_price(serial)
            result = await engine.submit_approval(result.run_id, token)
        events = traces.read(result.trace_id)
        return {
            "skill": result.skill,
            "skill_digest": result.skill_digest,
            "status": result.status,
            "state": result.state,
            "steps": result.steps,
            "outputs": {
                key: value for key, value in result.outputs.items() if not key.startswith("_")
            },
            "pending": result.pending,
            "events": [event.model_dump(mode="json") for event in events],
        }
    finally:
        await runtime.close()


def _change_checkout_price(serial: str) -> None:
    """Change approval material on the reference app before token submission."""

    adb = os.environ.get("HAYKAL_ADB_PATH") or shutil.which("adb")
    if adb is None:
        raise RuntimeError("adb is required for --stale-gate")
    command = [
        adb,
        "-s",
        serial,
        "shell",
        "am",
        "broadcast",
        "-a",
        "dev.haykal.refapp.SET_FAULT",
        "-p",
        "dev.haykal.refapps.matjar",
        "--es",
        "name",
        "price_change",
        "--ez",
        "enabled",
        "true",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
    device = connect(serial)
    if not device(resourceId="total", text="58.00 SAR").wait(timeout=30):
        raise RuntimeError("changed Matjar checkout did not become observable")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="haykal-m4")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--skill", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--inputs", default="{}")
    parser.add_argument("--approve-gate", action="store_true")
    parser.add_argument(
        "--stale-gate",
        action="store_true",
        help="change Matjar checkout material after granting approval",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = json.loads(args.inputs)
    if not isinstance(inputs, dict):
        raise ValueError("--inputs must be a JSON object")
    result = asyncio.run(
        run_smoke(
            serial=args.serial,
            skill_path=args.skill,
            state_directory=args.state_dir,
            inputs=inputs,
            approve_gate=args.approve_gate,
            stale_gate=args.stale_gate,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
