"""MCP tools delegate to the same RuntimeSession used by HTTP and Python."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server import MCPServer

from haykal.contracts import (
    ApprovalChallenge,
    DecisionResponse,
    Expectation,
    ExtractionRequest,
    RunRequest,
    SemanticAction,
)
from haykal.runtime import RuntimeSession
from haykal.workflows import SkillEngine, public_run

SessionLookup = Callable[[str], RuntimeSession]


def create_mcp_server(
    session_lookup: SessionLookup,
    *,
    skill_engine: SkillEngine | None = None,
    approval_principal: str | None = None,
) -> MCPServer:
    server = MCPServer("Haykal", instructions="Deterministic Android UI primitives.")

    @server.tool()
    async def observe(session_id: str, require_vision: bool = False) -> dict[str, object]:
        """Capture an evidence-backed semantic UI scene."""

        session = session_lookup(session_id)
        scene = (
            await session.observe(require_vision=True)
            if require_vision
            else await session.observe()
        )
        return scene.model_dump(mode="json")

    @server.tool()
    async def resolve(session_id: str, action: dict[str, object]) -> dict[str, object]:
        """Dry-run a semantic action target and return ranked diagnostics."""

        return await session_lookup(session_id).resolve(SemanticAction.model_validate(action))

    @server.tool()
    async def extract(session_id: str, request: dict[str, object]) -> dict[str, object]:
        """Extract typed, evidence-linked records from a retained scene."""

        result = await session_lookup(session_id).extract(ExtractionRequest.model_validate(request))
        return result.model_dump(mode="json")

    @server.tool()
    async def act(
        session_id: str,
        action: dict[str, object],
        run_id: str | None = None,
    ) -> dict[str, object]:
        """Resolve, dispatch once, settle, verify, and trace one semantic action."""

        result = await session_lookup(session_id).act(
            SemanticAction.model_validate(action),
            run_id=run_id,
        )
        return result.model_dump(mode="json")

    @server.tool()
    async def verify(session_id: str, expectation: dict[str, object]) -> dict[str, object]:
        """Evaluate a composed expectation against a settled fresh scene."""

        result = await session_lookup(session_id).verify(Expectation.model_validate(expectation))
        return result.model_dump(mode="json")

    @server.tool()
    def get_trace(session_id: str, trace_id: str) -> list[dict[str, object]]:
        """Return the ordered, redacted trace for an action."""

        return session_lookup(session_id).trace(trace_id)

    if skill_engine is not None:

        @server.tool()
        async def run_skill(request: dict[str, object]) -> dict[str, object]:
            """Start a signed immutable skill and run until completion or a safe pause."""

            result = await skill_engine.start(RunRequest.model_validate(request))
            return public_run(result).model_dump(mode="json")

        @server.tool()
        async def decide(run_id: str, decision: dict[str, object]) -> dict[str, object]:
            """Provide one response explicitly allowed by a paused run."""

            result = await skill_engine.decide(run_id, DecisionResponse.model_validate(decision))
            return public_run(result).model_dump(mode="json")

        @server.tool()
        def get_run(run_id: str) -> dict[str, object]:
            """Return the durable current state of a skill run."""

            return public_run(skill_engine.get(run_id)).model_dump(mode="json")

        @server.tool()
        def get_events(run_id: str) -> list[dict[str, object]]:
            """Return ordered evidence events for a skill run."""

            trace_id = skill_engine.get(run_id).trace_id
            return session_lookup(skill_engine.get(run_id).session_id).trace(trace_id)

        if approval_principal is not None:

            @server.tool()
            async def approve(run_id: str, challenge: dict[str, object]) -> dict[str, object]:
                """Approve and resume one gate from a separately authorized MCP server."""

                token = skill_engine.approve(
                    run_id,
                    principal=approval_principal,
                    scopes={"approve"},
                    presented=ApprovalChallenge.model_validate(challenge),
                )
                result = await skill_engine.submit_approval(run_id, token)
                return public_run(result).model_dump(mode="json")

    return server
