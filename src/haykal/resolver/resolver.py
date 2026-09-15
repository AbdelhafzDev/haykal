"""Ranked semantic target resolution with stale-scene recovery."""

from __future__ import annotations

from dataclasses import dataclass

from haykal.contracts.action import ActionTarget, ResolutionPolicy, ResolvedTarget
from haykal.contracts.extraction import RecordAnchor
from haykal.contracts.scene import SemanticElement, SemanticScene
from haykal.contracts.selector import Selector
from haykal.scene import identity_score
from haykal.selectors import SceneIndex, SelectorEvaluator


class TargetResolutionError(ValueError):
    """Base class for fail-closed target resolution."""


class TargetNotFound(TargetResolutionError):
    """No compatible target matched."""


class AmbiguousTarget(TargetResolutionError):
    def __init__(self, message: str, *, alternatives: list[dict[str, object]]) -> None:
        super().__init__(message)
        self.alternatives = alternatives


class StaleTarget(TargetResolutionError):
    """A target from an older scene cannot be re-established safely."""


@dataclass(frozen=True, slots=True)
class RankedTarget:
    element: SemanticElement
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    target: ResolvedTarget
    ranked: tuple[RankedTarget, ...]


_ACTION_CAPABILITY = {"tap": "tap", "input_text": "input_text"}


class TargetResolver:
    def __init__(self, *, element_dictionary: dict[str, Selector] | None = None) -> None:
        self._dictionary = element_dictionary or {}

    def resolve(
        self,
        target: ActionTarget,
        scene: SemanticScene,
        *,
        action_kind: str,
        policy: ResolutionPolicy,
        source_scene: SemanticScene | None = None,
        record_anchors: dict[str, RecordAnchor] | None = None,
    ) -> ResolutionDecision:
        if target.coordinates is not None:
            x, y = target.coordinates
            if x < 0 or y < 0:
                raise TargetNotFound("coordinate target must be non-negative")
            return ResolutionDecision(
                ResolvedTarget(
                    element_id=f"coordinate:{x}:{y}",
                    point=(x, y),
                    score=1.0,
                    scene_revision=scene.revision,
                ),
                (),
            )
        if target.selector is not None:
            return self.resolve_selector(
                target.selector,
                scene,
                action_kind=action_kind,
                policy=policy,
            )
        if target.record_anchor is not None:
            anchor = (record_anchors or {}).get(target.record_anchor)
            if anchor is None:
                raise TargetNotFound(f"record anchor {target.record_anchor!r} is unavailable")
            return self._resolve_element_id(
                anchor.element_id,
                anchor.scene_revision,
                scene,
                action_kind=action_kind,
                policy=policy,
                source_scene=source_scene,
            )
        assert target.element_id is not None and target.scene_revision is not None
        return self._resolve_element_id(
            target.element_id,
            target.scene_revision,
            scene,
            action_kind=action_kind,
            policy=policy,
            source_scene=source_scene,
        )

    def resolve_selector(
        self,
        selector: Selector,
        scene: SemanticScene,
        *,
        action_kind: str,
        policy: ResolutionPolicy,
    ) -> ResolutionDecision:
        evaluator = SelectorEvaluator(scene, element_dictionary=self._dictionary)
        ranked_by_id: dict[str, RankedTarget] = {}
        for match in evaluator.resolve(selector):
            candidate = self._actionable(match.element, evaluator.index, action_kind)
            if candidate is None:
                continue
            evidence = self._evidence_confidence(candidate, selector)
            score = round(0.70 * match.text_score + 0.30 * evidence, 6)
            reasons = ["selector_match", f"evidence={evidence:.3f}"]
            if candidate.id != match.element.id:
                reasons.append(f"actionable_ancestor_of={match.element.id}")
            current = ranked_by_id.get(candidate.id)
            ranked = RankedTarget(candidate, score, tuple(reasons))
            if current is None or ranked.score > current.score:
                ranked_by_id[candidate.id] = ranked
        expansion: dict[str, object] | None = None
        if selector.semantic_name is not None:
            expanded = self._dictionary.get(selector.semantic_name)
            expansion = {
                "name": selector.semantic_name,
                "selector": expanded.model_dump(mode="json") if expanded else None,
            }
        return self._accept(
            list(ranked_by_id.values()),
            scene,
            policy,
            dictionary_expansion=expansion,
        )

    def _resolve_element_id(
        self,
        element_id: str,
        source_revision: int,
        scene: SemanticScene,
        *,
        action_kind: str,
        policy: ResolutionPolicy,
        source_scene: SemanticScene | None,
    ) -> ResolutionDecision:
        index = SceneIndex(scene)
        current = index.by_id.get(element_id)
        if current is not None and self._supports(current, action_kind):
            stale = source_revision != scene.revision
            return ResolutionDecision(
                self._resolved(current, 1.0 if not stale else 0.99, scene, stale_rebound=stale),
                (RankedTarget(current, 1.0 if not stale else 0.99, ("stable_id",)),),
            )
        if source_revision == scene.revision:
            raise TargetNotFound(f"element {element_id!r} is absent from current scene")
        if source_scene is None or source_scene.revision != source_revision:
            raise StaleTarget("source scene required to re-resolve stale element")
        previous = SceneIndex(source_scene).by_id.get(element_id)
        if previous is None:
            raise StaleTarget(f"element {element_id!r} is absent from source scene")
        exact_resource = [
            element
            for element in scene.elements
            if previous.resource_id is not None
            and element.resource_id == previous.resource_id
            and self._supports(element, action_kind)
        ]
        if len(exact_resource) == 1:
            matched = exact_resource[0]
            return ResolutionDecision(
                self._resolved(matched, 0.99, scene, stale_rebound=True),
                (RankedTarget(matched, 0.99, ("unique_resource_id",)),),
            )
        ranked = [
            RankedTarget(element, identity_score(previous, element), ("semantic_fingerprint",))
            for element in scene.elements
            if self._supports(element, action_kind)
        ]
        return self._accept(ranked, scene, policy, stale_rebound=True)

    def _accept(
        self,
        ranked: list[RankedTarget],
        scene: SemanticScene,
        policy: ResolutionPolicy,
        *,
        dictionary_expansion: dict[str, object] | None = None,
        stale_rebound: bool = False,
    ) -> ResolutionDecision:
        ordered = sorted(
            ranked,
            key=lambda item: (
                -item.score,
                item.element.bounds.top,
                item.element.bounds.left,
                item.element.id,
            ),
        )
        alternatives = [self._alternative(item) for item in ordered[:5]]
        if not ordered or ordered[0].score < policy.minimum_score:
            raise TargetNotFound(f"no target reached minimum score {policy.minimum_score:.3f}")
        margin = ordered[0].score - (ordered[1].score if len(ordered) > 1 else 0.0)
        if len(ordered) > 1 and margin < policy.ambiguity_margin:
            raise AmbiguousTarget(
                f"top target margin {margin:.3f} is below {policy.ambiguity_margin:.3f}",
                alternatives=alternatives,
            )
        return ResolutionDecision(
            self._resolved(
                ordered[0].element,
                ordered[0].score,
                scene,
                stale_rebound=stale_rebound,
                alternatives=alternatives[1:],
                dictionary_expansion=dictionary_expansion,
            ),
            tuple(ordered),
        )

    def _actionable(
        self, element: SemanticElement, index: SceneIndex, action_kind: str
    ) -> SemanticElement | None:
        if self._supports(element, action_kind):
            return element
        return next(
            (
                ancestor
                for ancestor in index.ancestors(element)
                if self._supports(ancestor, action_kind)
            ),
            None,
        )

    def _supports(self, element: SemanticElement, action_kind: str) -> bool:
        capability = _ACTION_CAPABILITY.get(action_kind)
        return capability is None or capability in element.actions

    def _evidence_confidence(self, element: SemanticElement, selector: Selector) -> float:
        names = ["bounds", "role"]
        if selector.label is not None:
            names.append("label")
        if selector.text is not None:
            names.append("text")
        if selector.resource_id is not None:
            names.append("resource_id")
        values = [
            element.properties[name].confidence for name in names if name in element.properties
        ]
        return sum(values) / len(values) if values else 0.0

    def _resolved(
        self,
        element: SemanticElement,
        score: float,
        scene: SemanticScene,
        *,
        stale_rebound: bool,
        alternatives: list[dict[str, object]] | None = None,
        dictionary_expansion: dict[str, object] | None = None,
    ) -> ResolvedTarget:
        return ResolvedTarget(
            element_id=element.id,
            point=(
                (element.bounds.left + element.bounds.right) // 2,
                (element.bounds.top + element.bounds.bottom) // 2,
            ),
            score=score,
            scene_revision=scene.revision,
            stale_rebound=stale_rebound,
            alternatives=alternatives or [],
            dictionary_expansion=dictionary_expansion,
        )

    def _alternative(self, target: RankedTarget) -> dict[str, object]:
        return {
            "element_id": target.element.id,
            "score": target.score,
            "role": target.element.role,
            "label": target.element.label,
            "text": target.element.text,
            "bounds": target.element.bounds.model_dump(mode="json"),
            "reasons": list(target.reasons),
        }
