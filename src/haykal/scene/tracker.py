"""Session-scoped adjacent-frame element identity tracking."""

from __future__ import annotations

from dataclasses import dataclass

from haykal.contracts.scene import SemanticElement, SemanticScene
from haykal.perception.fusion import semantic_digest
from haykal.perception.model import intersection_over_union
from haykal.text.similarity import similarity


class SceneRevisionError(ValueError):
    """Scene revisions within a session must increase monotonically."""


@dataclass(frozen=True, slots=True)
class IdentityMatch:
    current_temporary_id: str
    previous_id: str
    score: float


@dataclass(frozen=True, slots=True)
class TrackingResult:
    scene: SemanticScene
    matches: tuple[IdentityMatch, ...]
    new_ids: tuple[str, ...]
    ambiguous_temporary_ids: tuple[str, ...]
    expired_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrackingPolicy:
    minimum_score: float = 0.52
    ambiguity_margin: float = 0.08


DEFAULT_TRACKING_POLICY = TrackingPolicy()


def _jaccard(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def _evidence_sources(element: SemanticElement) -> set[str]:
    return {
        source
        for name, evidence in element.properties.items()
        if name in {"bounds", "role", "state"}
        for source in evidence.sources
    }


def identity_score(previous: SemanticElement, current: SemanticElement) -> float:
    resource_score = (
        1.0
        if previous.resource_id
        and current.resource_id
        and previous.resource_id == current.resource_id
        else 0.0
    )
    role_score = 1.0 if previous.role == current.role else 0.0
    previous_text = previous.fingerprint.text_key or ""
    current_text = current.fingerprint.text_key or ""
    text_score = similarity(previous_text, current_text) if previous_text or current_text else 0.5
    ancestry_score = _jaccard(previous.fingerprint.ancestry, current.fingerprint.ancestry)
    geometry_score = intersection_over_union(previous.bounds, current.bounds)
    source_score = float(bool(_evidence_sources(previous) & _evidence_sources(current)))
    return round(
        0.25 * resource_score
        + 0.20 * source_score
        + 0.10 * role_score
        + 0.30 * text_score
        + 0.10 * ancestry_score
        + 0.05 * geometry_score,
        6,
    )


class ElementIdentityTracker:
    def __init__(self, policy: TrackingPolicy = DEFAULT_TRACKING_POLICY) -> None:
        self._policy = policy
        self._previous: SemanticScene | None = None
        self._session_id: str | None = None
        self._counter = 0

    def track(self, scene: SemanticScene) -> TrackingResult:
        previous = self._previous
        if self._session_id != scene.session_id:
            self._session_id = scene.session_id
            self._counter = 0
            previous = None
        elif previous is not None and scene.revision <= previous.revision:
            raise SceneRevisionError(
                f"scene revision {scene.revision} does not follow {previous.revision}"
            )

        id_map: dict[str, str] = {}
        matches: list[IdentityMatch] = []
        ambiguous: list[str] = []
        used_previous: set[str] = set()
        proposals: list[tuple[float, SemanticElement, SemanticElement]] = []
        if previous is not None:
            for current in scene.elements:
                ranked = sorted(
                    ((identity_score(old, current), old) for old in previous.elements),
                    key=lambda item: (-item[0], item[1].id),
                )
                if not ranked or ranked[0][0] < self._policy.minimum_score:
                    continue
                runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
                if ranked[0][0] - runner_up < self._policy.ambiguity_margin:
                    ambiguous.append(current.id)
                    continue
                proposals.append((ranked[0][0], current, ranked[0][1]))

        for score, current, old in sorted(
            proposals, key=lambda item: (-item[0], item[1].id, item[2].id)
        ):
            if old.id in used_previous:
                ambiguous.append(current.id)
                continue
            id_map[current.id] = old.id
            used_previous.add(old.id)
            matches.append(IdentityMatch(current.id, old.id, score))

        new_ids: list[str] = []
        for element in scene.elements:
            if element.id not in id_map:
                self._counter += 1
                stable_id = f"el_{self._counter:08x}"
                id_map[element.id] = stable_id
                new_ids.append(stable_id)

        tracked_elements = [
            element.model_copy(
                update={
                    "id": id_map[element.id],
                    "parent": id_map.get(element.parent) if element.parent else None,
                }
            )
            for element in scene.elements
        ]
        digest = semantic_digest(tracked_elements, revision=scene.revision)
        tracked = scene.model_copy(
            update={
                "scene_id": f"scn_{digest.removeprefix('sha256:')[:20]}",
                "digest": digest,
                "elements": tracked_elements,
            }
        )
        previous_ids = {element.id for element in previous.elements} if previous else set()
        expired = tuple(sorted(previous_ids - used_previous))
        self._previous = tracked
        return TrackingResult(
            scene=tracked,
            matches=tuple(matches),
            new_ids=tuple(new_ids),
            ambiguous_temporary_ids=tuple(sorted(set(ambiguous))),
            expired_ids=expired,
        )
