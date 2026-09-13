"""Deterministic device-free skill replay against state-named scene fixtures."""

from __future__ import annotations

from pathlib import Path

from haykal.contracts import SemanticScene, Skill
from haykal.contracts.action import ActionTarget, ResolutionPolicy
from haykal.extraction import ExtractionEngine
from haykal.resolver import TargetResolutionError, TargetResolver
from haykal.verification import ExpectationEvaluator


def replay_skill(skill: Skill, fixtures: str | Path) -> dict[str, object]:
    root = Path(fixtures)
    resolver = TargetResolver(element_dictionary=skill.elements)
    extractor = ExtractionEngine(element_dictionary=skill.elements)
    evaluator = ExpectationEvaluator(element_dictionary=skill.elements)
    states: list[dict[str, object]] = []
    passed = True
    for state_name, state in skill.states.items():
        path = root / f"{state_name}.json"
        if not path.is_file():
            states.append({"state": state_name, "status": "missing_fixture"})
            passed = False
            continue
        scene = SemanticScene.model_validate_json(path.read_text(encoding="utf-8"))
        result: dict[str, object] = {"state": state_name, "scene_id": scene.scene_id}
        state_passed = True
        if state.expect is not None:
            expectation = evaluator.evaluate(
                state.expect,
                scene,
                foreground_package=skill.metadata.package,
                scene_stable=True,
            )
            result["expect"] = expectation.status
            state_passed = state_passed and expectation.status == "passed"
        if state.extract is not None:
            request = state.extract.model_copy(update={"scene_id": scene.scene_id})
            extraction = extractor.extract_scene(request, scene)
            result["records"] = len(extraction.records)
            state_passed = state_passed and extraction.request_satisfied
        if state.action is not None and hasattr(state.action.target, "model_dump"):
            selector = state.action.target
            try:
                decision = resolver.resolve(
                    ActionTarget(selector=selector),  # type: ignore[arg-type]
                    scene,
                    action_kind=state.action.kind,
                    policy=ResolutionPolicy(),
                )
                result["target"] = decision.target.model_dump(mode="json")
            except TargetResolutionError as exc:
                result["resolution_error"] = str(exc)
                state_passed = False
        if state.verify is not None:
            result["verify_declared"] = True
        result["status"] = "passed" if state_passed else "failed"
        passed = passed and state_passed
        states.append(result)
    return {"passed": passed, "states": states}
