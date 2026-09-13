from __future__ import annotations

import pytest
from mcp import Client

from haykal.contracts.scene import SceneQuality, SemanticScene
from haykal.transports.mcp import create_mcp_server


class Session:
    async def observe(self) -> SemanticScene:
        return SemanticScene(
            scene_id="scene",
            session_id="session",
            revision=1,
            digest="sha256:" + "1" * 64,
            quality=SceneQuality(score=1, accessibility_coverage=1),
            elements=[],
        )

    def trace(self, _trace_id: str) -> list[dict[str, object]]:
        return []


@pytest.mark.asyncio
async def test_mcp_v2_tool_returns_structured_scene() -> None:
    session = Session()
    server = create_mcp_server(lambda _session_id: session)  # type: ignore[arg-type]
    async with Client(server) as client:
        result = await client.call_tool("observe", {"session_id": "session"})
    assert result.structured_content["scene_id"] == "scene"
