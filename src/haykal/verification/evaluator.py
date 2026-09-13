"""Pure recursive evaluation of bounded expectations against a semantic scene."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from haykal.contracts.expectation import Expectation, ExpectationResult, TextPredicate
from haykal.contracts.scene import SemanticElement, SemanticScene
from haykal.contracts.selector import Selector
from haykal.perception import semantic_content_digest
from haykal.selectors import SelectorEvaluator
from haykal.selectors.evaluator import SelectorMatch
from haykal.text import normalize, parse_duration, parse_money, parse_number

Evaluation = Literal["passed", "failed", "inconclusive"]


@dataclass(frozen=True, slots=True)
class _Evaluation:
    status: Evaluation
    evidence: tuple[dict[str, object], ...]


class ExpectationEvaluator:
    def __init__(self, *, element_dictionary: dict[str, Selector] | None = None) -> None:
        self._dictionary = element_dictionary or {}

    def evaluate(
        self,
        expectation: Expectation,
        scene: SemanticScene,
        *,
        pre_scene: SemanticScene | None = None,
        foreground_package: str | None = None,
        scene_stable: bool | None = None,
        elapsed_ms: int = 0,
    ) -> ExpectationResult:
        started = time.monotonic()
        evaluated = self._evaluate(
            expectation,
            scene,
            pre_scene=pre_scene,
            foreground_package=foreground_package,
            scene_stable=scene_stable,
        )
        measured = round((time.monotonic() - started) * 1000)
        return ExpectationResult(
            status=evaluated.status,
            scene_ids=[scene.scene_id],
            evidence=list(evaluated.evidence),
            elapsed_ms=elapsed_ms + measured,
        )

    def _evaluate(
        self,
        expectation: Expectation,
        scene: SemanticScene,
        *,
        pre_scene: SemanticScene | None,
        foreground_package: str | None,
        scene_stable: bool | None,
    ) -> _Evaluation:
        if expectation.all_ is not None:
            return self._combine(
                "all",
                [
                    self._evaluate(
                        child,
                        scene,
                        pre_scene=pre_scene,
                        foreground_package=foreground_package,
                        scene_stable=scene_stable,
                    )
                    for child in expectation.all_
                ],
            )
        if expectation.any_ is not None:
            return self._combine(
                "any",
                [
                    self._evaluate(
                        child,
                        scene,
                        pre_scene=pre_scene,
                        foreground_package=foreground_package,
                        scene_stable=scene_stable,
                    )
                    for child in expectation.any_
                ],
            )
        if expectation.not_ is not None:
            child = self._evaluate(
                expectation.not_,
                scene,
                pre_scene=pre_scene,
                foreground_package=foreground_package,
                scene_stable=scene_stable,
            )
            status: Evaluation = (
                "inconclusive"
                if child.status == "inconclusive"
                else "failed"
                if child.status == "passed"
                else "passed"
            )
            return _Evaluation(status, child.evidence)

        evaluator = SelectorEvaluator(scene, element_dictionary=self._dictionary)
        if expectation.visible is not None:
            matches = evaluator.resolve(expectation.visible)
            return self._match_result("visible", matches, bool(matches))
        if expectation.not_visible is not None:
            matches = evaluator.resolve(expectation.not_visible)
            return self._match_result("not_visible", matches, not matches)
        if expectation.text_equals is not None:
            return self._text("text_equals", expectation.text_equals, evaluator, contains=False)
        if expectation.text_contains is not None:
            return self._text("text_contains", expectation.text_contains, evaluator, contains=True)
        if expectation.state_equals is not None:
            state_predicate = expectation.state_equals
            matches = evaluator.resolve(state_predicate.target)
            selected = [
                match
                for match in matches
                if getattr(match.element.state, state_predicate.state) == state_predicate.value
            ]
            return self._match_result("state_equals", selected, bool(selected))
        if expectation.value_equals is not None:
            value_predicate = expectation.value_equals
            matches = evaluator.resolve(value_predicate.target)
            selected = [
                match
                for match in matches
                if self._value_matches(match.element, value_predicate.type, value_predicate.value)
            ]
            return self._match_result("value_equals", selected, bool(selected))
        if expectation.foreground_package is not None:
            if foreground_package is None:
                return _Evaluation("inconclusive", ())
            passed = foreground_package == expectation.foreground_package
            return _Evaluation(
                "passed" if passed else "failed",
                (
                    {
                        "predicate": "foreground_package",
                        "expected": expectation.foreground_package,
                        "actual": foreground_package,
                    },
                ),
            )
        if expectation.scene_changed is not None:
            if pre_scene is None:
                return _Evaluation("inconclusive", ())
            changed = semantic_content_digest(pre_scene.elements) != semantic_content_digest(
                scene.elements
            )
            return _Evaluation(
                "passed" if changed == expectation.scene_changed else "failed",
                ({"predicate": "scene_changed", "actual": changed},),
            )
        assert expectation.scene_stable is not None
        if scene_stable is None:
            return _Evaluation("inconclusive", ())
        return _Evaluation(
            "passed" if scene_stable == expectation.scene_stable else "failed",
            ({"predicate": "scene_stable", "actual": scene_stable},),
        )

    def _combine(self, operator: str, children: list[_Evaluation]) -> _Evaluation:
        evidence = tuple(item for child in children for item in child.evidence)
        statuses = [child.status for child in children]
        if operator == "all":
            status: Evaluation = (
                "failed"
                if "failed" in statuses
                else "passed"
                if all(item == "passed" for item in statuses)
                else "inconclusive"
            )
        else:
            status = (
                "passed"
                if "passed" in statuses
                else "failed"
                if all(item == "failed" for item in statuses)
                else "inconclusive"
            )
        return _Evaluation(status, evidence)

    def _text(
        self,
        name: str,
        predicate: TextPredicate | str,
        evaluator: SelectorEvaluator,
        *,
        contains: bool,
    ) -> _Evaluation:
        target = predicate.target if isinstance(predicate, TextPredicate) else None
        expected = predicate.value if isinstance(predicate, TextPredicate) else predicate
        elements = (
            [match.element for match in evaluator.resolve(target)]
            if target is not None
            else evaluator.index.scene.elements
        )
        normalized_expected = normalize(expected)
        matched = [
            element
            for element in elements
            if any(
                (
                    normalized_expected in normalize(value)
                    if contains
                    else normalize(value) == normalized_expected
                )
                for value in (element.label, element.text)
                if value
            )
        ]
        evidence = tuple(self._element_evidence(name, element) for element in matched)
        return _Evaluation("passed" if matched else "failed", evidence)

    def _value_matches(self, element: SemanticElement, kind: str, expected: object) -> bool:
        raw = element.text or element.label
        if raw is None:
            return False
        try:
            if kind in {"number", "rating"}:
                actual: object = parse_number(raw).value
                wanted = expected.get("value") if isinstance(expected, dict) else expected
                return actual == Decimal(str(wanted))
            if kind == "money":
                actual_money = parse_money(raw)
                if not isinstance(expected, dict):
                    return actual_money.amount == Decimal(str(expected))
                return actual_money.amount == Decimal(str(expected.get("amount"))) and (
                    "currency" not in expected or actual_money.currency == expected.get("currency")
                )
            actual_duration = parse_duration(raw)
            if not isinstance(expected, dict):
                return False
            return actual_duration.min_minutes == expected.get(
                "min_minutes"
            ) and actual_duration.max_minutes == expected.get("max_minutes")
        except (ValueError, TypeError):
            return False

    def _match_result(self, name: str, matches: list[SelectorMatch], passed: bool) -> _Evaluation:
        evidence = tuple(self._element_evidence(name, match.element) for match in matches)
        return _Evaluation("passed" if passed else "failed", evidence)

    def _element_evidence(self, predicate: str, element: SemanticElement) -> dict[str, object]:
        return {
            "predicate": predicate,
            "element_id": element.id,
            "sources": sorted(
                {source for evidence in element.properties.values() for source in evidence.sources}
            ),
        }
