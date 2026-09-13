"""Generate checked-in JSON Schemas for every canonical contract."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from . import (
    ActionResult,
    ApprovalChallenge,
    ApprovalGrant,
    ApprovalGrantRequest,
    CandidatePatch,
    DecisionResponse,
    Expectation,
    ExpectationResult,
    ExtractionRequest,
    ExtractionResult,
    RawObservation,
    RunRequest,
    RunResult,
    RunSnapshot,
    RuntimeEvent,
    SelectionResult,
    Selector,
    SemanticAction,
    SemanticScene,
    Skill,
    TraceEnvelope,
)

MODELS: dict[str, type[BaseModel]] = {
    "action": SemanticAction,
    "action-result": ActionResult,
    "approval-challenge": ApprovalChallenge,
    "approval-grant": ApprovalGrant,
    "approval-grant-request": ApprovalGrantRequest,
    "candidate-patch": CandidatePatch,
    "decision-response": DecisionResponse,
    "expectation": Expectation,
    "expectation-result": ExpectationResult,
    "extraction-request": ExtractionRequest,
    "extraction-result": ExtractionResult,
    "observation": RawObservation,
    "run-result": RunResult,
    "run-request": RunRequest,
    "run-snapshot": RunSnapshot,
    "runtime-event": RuntimeEvent,
    "scene": SemanticScene,
    "selection-result": SelectionResult,
    "selector": Selector,
    "skill": Skill,
    "trace": TraceEnvelope,
}


def render_schemas() -> dict[str, str]:
    return {
        f"{name}.schema.json": json.dumps(
            model.model_json_schema(mode="validation"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
        for name, model in MODELS.items()
    }


def write_schemas(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    rendered = render_schemas()
    for existing in destination.glob("*.schema.json"):
        if existing.name not in rendered:
            existing.unlink()
    for name, content in rendered.items():
        (destination / name).write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="haykal-schema")
    parser.add_argument("--output", type=Path, default=Path("schemas/v1"))
    args = parser.parse_args(argv)
    write_schemas(args.output)
    print(f"wrote {len(MODELS)} schemas to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
