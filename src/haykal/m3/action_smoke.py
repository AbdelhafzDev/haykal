"""Live semantic action, settle, verification, and trace smoke."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from haykal.contracts.action import ActionTarget, Risk, SemanticAction
from haykal.contracts.common import SettlePolicy
from haykal.contracts.expectation import Expectation
from haykal.contracts.selector import Selector, TextMatch
from haykal.runtime import build_runtime


async def run_action_smoke(
    *,
    serial: str,
    state_directory: Path | None = None,
) -> dict[str, object]:
    root = state_directory or Path(tempfile.mkdtemp(prefix="haykal-m3-"))
    session = build_runtime(
        serial=serial,
        session_id=f"m3_{uuid.uuid4().hex}",
        state_directory=root,
        heartbeat_s=5,
    )
    await session.open()
    try:
        pre = await session.observe()
        action = SemanticAction(
            action_id=f"act_{uuid.uuid4().hex}",
            kind="tap",
            target=ActionTarget(
                scene_revision=pre.revision,
                selector=Selector(text=TextMatch(contains="Android View baseline")),
            ),
            expect=Expectation(
                text_contains="حفظ",
                # Two coherent UIAutomator2 hierarchy+screenshot captures can take
                # more than five seconds on the ARM64 API 37 reference VM.
                timeout_ms=30_000,
                settle=SettlePolicy(stable_samples=2, interval_ms=100),
            ),
            risk=Risk(category="navigation", gate="none"),
        )
        resolution = await session.resolve(action)
        result = await session.act(action, run_id="m3-live-smoke")
        trace = session.trace(result.trace_id)
        return {
            "schema_version": "1.0",
            "status": "passed" if result.status == "verified" else "failed",
            "pre_scene": pre.scene_id,
            "post_scene": result.post_scene,
            "resolution": resolution,
            "action": result.model_dump(mode="json"),
            "trace": trace,
        }
    finally:
        await session.close()
