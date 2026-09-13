"""Static skill checks that go beyond contract shape validation."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass

from pydantic import ValidationError

from haykal.contracts import Selector, Skill
from haykal.contracts.selector import semantic_references

_INPUT = re.compile(r"\$\{(?:inputs?\.)?([a-zA-Z_][a-zA-Z0-9_]*)[^}]*}")


@dataclass(frozen=True, slots=True)
class LintIssue:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def lint_skill(payload: object) -> tuple[Skill | None, list[LintIssue]]:
    try:
        skill = Skill.model_validate(payload)
    except ValidationError as exc:
        return None, [
            LintIssue(
                "invalid_contract",
                ".".join(str(item) for item in error["loc"]),
                str(error["msg"]),
            )
            for error in exc.errors()
        ]

    issues: list[LintIssue] = []
    referenced_elements: set[str] = set()
    reachable = _reachable(skill)
    for name in sorted(set(skill.states) - reachable):
        issues.append(LintIssue("unreachable_state", f"states.{name}", "state is unreachable"))

    for state_name, state in skill.states.items():
        selectors: list[Selector] = []
        if state.expect is not None:
            selectors.extend(_expectation_selectors(state.expect.model_dump(by_alias=True)))
        if state.verify is not None:
            selectors.extend(_expectation_selectors(state.verify.model_dump(by_alias=True)))
        if state.extract is not None:
            if state.extract.group.root is not None:
                selectors.append(state.extract.group.root)
            if state.extract.group.record is not None:
                selectors.append(state.extract.group.record)
            selectors.extend(field.selector for field in state.extract.fields.values())
            if state.extract.scroll is not None:
                selectors.append(state.extract.scroll.within)
        if state.action is not None and isinstance(state.action.target, Selector):
            selectors.append(state.action.target)
        for selector in selectors:
            referenced_elements.update(semantic_references(selector))
            fields = selector.model_dump(exclude_none=True)
            if set(fields) <= {"semantic_name", "normalize", "prefer_sources"}:
                continue
            discriminators = {"resource_id", "label", "text", "semantic_name", "within"}
            if not (set(fields) & discriminators):
                issues.append(
                    LintIssue(
                        "under_specified_selector",
                        f"states.{state_name}",
                        "selector needs resource_id, label, text, semantic_name, or within",
                    )
                )
        if state.action is not None:
            if state.expect is None:
                issues.append(
                    LintIssue(
                        "missing_precondition",
                        f"states.{state_name}.expect",
                        "acting state requires an expectation",
                    )
                )
            if state.verify is None:
                issues.append(
                    LintIssue(
                        "missing_verification",
                        f"states.{state_name}.verify",
                        "acting state requires a verification",
                    )
                )

    for name in sorted(set(skill.elements) - referenced_elements):
        issues.append(LintIssue("unused_element", f"elements.{name}", "element is never used"))

    encoded = json.dumps(skill.model_dump(mode="json", by_alias=True), ensure_ascii=False)
    referenced_inputs = set(_INPUT.findall(encoded))
    produced = {
        state.extract.as_ for state in skill.states.values() if state.extract is not None
    } | {state.select.as_ for state in skill.states.values() if state.select is not None}
    for name in sorted(referenced_inputs - set(skill.inputs) - produced):
        issues.append(LintIssue("undefined_input", name, "input is referenced but not declared"))
    for name in sorted(set(skill.inputs) - referenced_inputs):
        issues.append(LintIssue("unused_input", f"inputs.{name}", "input is never referenced"))
    return skill, issues


def _reachable(skill: Skill) -> set[str]:
    found: set[str] = set()
    pending = [skill.start]
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        state = skill.states[name]
        destinations = [state.next]
        destinations.extend(branch.next for branch in state.branches or [])
        for transition in (
            state.on_action_uncertain,
            state.on_verify_timeout,
            state.on_verify_failure,
            state.on_reconcile_failure,
        ):
            if transition is not None:
                destinations.append(transition.next)
        pending.extend(item for item in destinations if item is not None)
    return found


def _expectation_selectors(value: object) -> list[Selector]:
    # Contract validation already proved these dictionaries are selectors. Re-validate
    # only the selector-shaped branches so the linter remains independent of internals.
    found: list[Selector] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"visible", "not_visible", "target"} and isinstance(child, dict):
                with suppress(ValidationError):
                    found.append(Selector.model_validate(child))
            else:
                found.extend(_expectation_selectors(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_expectation_selectors(child))
    return found
