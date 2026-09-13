"""Deterministic selector evaluation shared by extraction and later resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from haykal.contracts.scene import SemanticElement, SemanticScene
from haykal.contracts.selector import ResourceMatch, Selector, TextMatch
from haykal.text.normalization import normalize
from haykal.text.similarity import similarity

MAX_REGEX_LENGTH = 256


class SelectorEvaluationError(ValueError):
    """A selector cannot be evaluated safely against this scene."""


@dataclass(frozen=True, slots=True)
class SelectorMatch:
    element: SemanticElement
    text_score: float


class SceneIndex:
    def __init__(self, scene: SemanticScene) -> None:
        self.scene = scene
        self.by_id = {element.id: element for element in scene.elements}
        self.children: dict[str | None, list[SemanticElement]] = {}
        for element in scene.elements:
            self.children.setdefault(element.parent, []).append(element)

    def ancestors(self, element: SemanticElement) -> list[SemanticElement]:
        result: list[SemanticElement] = []
        parent_id = element.parent
        visited: set[str] = set()
        while parent_id is not None and parent_id not in visited:
            visited.add(parent_id)
            parent = self.by_id.get(parent_id)
            if parent is None:
                break
            result.append(parent)
            parent_id = parent.parent
        return result

    def descendants(self, root: SemanticElement, *, include_root: bool = True) -> set[str]:
        result = {root.id} if include_root else set()
        pending = list(self.children.get(root.id, []))
        while pending:
            current = pending.pop()
            if current.id in result:
                continue
            result.add(current.id)
            pending.extend(self.children.get(current.id, []))
        return result


class SelectorEvaluator:
    def __init__(
        self,
        scene: SemanticScene,
        *,
        element_dictionary: dict[str, Selector] | None = None,
    ) -> None:
        self.index = SceneIndex(scene)
        self._dictionary = element_dictionary or {}

    def resolve(
        self, selector: Selector, *, scope_ids: set[str] | None = None
    ) -> list[SelectorMatch]:
        matches = [
            SelectorMatch(element, score)
            for element in self.index.scene.elements
            if (scope_ids is None or element.id in scope_ids)
            and (score := self._match(element, selector)) is not None
        ]
        matches.sort(
            key=lambda item: (
                item.element.bounds.top,
                item.element.bounds.left,
                item.element.id,
            )
        )
        if selector.position == "first":
            return matches[:1]
        if selector.position == "last":
            return matches[-1:]
        if selector.position == "index":
            index = selector.index or 0
            return matches[index : index + 1]
        return matches

    def _match(self, element: SemanticElement, selector: Selector) -> float | None:
        score = 1.0
        if selector.semantic_name is not None:
            expanded = self._dictionary.get(selector.semantic_name)
            if expanded is None:
                raise SelectorEvaluationError(f"undefined semantic name {selector.semantic_name!r}")
            expanded_score = self._match(element, expanded)
            if expanded_score is None:
                return None
            score = min(score, expanded_score)
        if selector.element_id is not None and (
            element.id != selector.element_id
            or selector.scene_revision != self.index.scene.revision
        ):
            return None
        if selector.role is not None:
            roles = selector.role if isinstance(selector.role, list) else [selector.role]
            if element.role not in roles:
                return None
        if selector.resource_id is not None and not self._resource_matches(
            element.resource_id, selector.resource_id
        ):
            return None
        if selector.label is not None:
            label_score = self._text_matches(element.label, selector.label)
            if label_score is None:
                return None
            score = min(score, label_score)
        if selector.text is not None:
            text_score = self._text_matches(element.text, selector.text)
            if text_score is None:
                return None
            score = min(score, text_score)
        for name in ("focused", "enabled", "checked", "selected", "scrollable"):
            expected = getattr(selector, name)
            if expected is not None and getattr(element.state, name) != expected:
                return None
        if selector.within is not None:
            ancestor_ids = {match.element.id for match in self.resolve(selector.within)}
            if not any(item.id in ancestor_ids for item in self.index.ancestors(element)):
                return None
        if selector.near is not None:
            anchors = [match.element for match in self.resolve(selector.near.selector)]
            if not any(
                self._near(element, anchor, selector.near.direction, selector.near.max_px)
                for anchor in anchors
                if anchor.id != element.id
            ):
                return None
        return score

    def _resource_matches(self, value: str | None, matcher: ResourceMatch) -> bool:
        if value is None:
            return False
        if matcher.equals is not None:
            return value == matcher.equals
        if matcher.ends_with is not None:
            return value.endswith(matcher.ends_with)
        if matcher.regex is not None:
            return self._regex(matcher.regex, value)
        return False

    def _text_matches(self, value: str | None, matcher: TextMatch) -> float | None:
        if value is None:
            return None
        normalized = normalize(value, matcher.normalization)
        if matcher.equals is not None:
            return 1.0 if normalized == normalize(matcher.equals, matcher.normalization) else None
        if matcher.contains is not None:
            query = normalize(matcher.contains, matcher.normalization)
            return 1.0 if query in normalized else None
        if matcher.any_contains is not None:
            queries = [normalize(item, matcher.normalization) for item in matcher.any_contains]
            return 1.0 if any(query in normalized for query in queries) else None
        if matcher.similar is not None:
            score = similarity(value, matcher.similar, matcher.normalization)
            return score if score >= (matcher.threshold or 0.9) else None
        if matcher.regex is not None:
            return 1.0 if self._regex(matcher.regex, value) else None
        return None

    def _regex(self, pattern: str, value: str) -> bool:
        if len(pattern) > MAX_REGEX_LENGTH:
            raise SelectorEvaluationError("selector regex exceeds length budget")
        try:
            return re.search(pattern, value) is not None
        except re.error as exc:
            raise SelectorEvaluationError(f"invalid selector regex: {exc}") from exc

    @staticmethod
    def _near(
        element: SemanticElement,
        anchor: SemanticElement,
        direction: str,
        max_px: int,
    ) -> bool:
        element_x = (element.bounds.left + element.bounds.right) / 2
        element_y = (element.bounds.top + element.bounds.bottom) / 2
        anchor_x = (anchor.bounds.left + anchor.bounds.right) / 2
        anchor_y = (anchor.bounds.top + anchor.bounds.bottom) / 2
        horizontal = abs(element_x - anchor_x)
        vertical = abs(element_y - anchor_y)
        if direction == "left":
            return element_x < anchor_x and horizontal <= max_px
        if direction == "right":
            return element_x > anchor_x and horizontal <= max_px
        if direction == "above":
            return element_y < anchor_y and vertical <= max_px
        if direction == "below":
            return element_y > anchor_y and vertical <= max_px
        return not (
            element.bounds.right < anchor.bounds.left
            or element.bounds.left > anchor.bounds.right
            or element.bounds.bottom < anchor.bounds.top
            or element.bounds.top > anchor.bounds.bottom
        )
