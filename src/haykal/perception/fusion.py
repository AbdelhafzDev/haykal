"""Deterministic multi-source candidate fusion with per-property evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from haykal.contracts.common import Bounds
from haykal.contracts.scene import (
    ElementFingerprint,
    ElementState,
    PropertyEvidence,
    SemanticElement,
)
from haykal.text.normalization import normalize
from haykal.text.similarity import similarity

from .model import PerceptionCandidate, area, intersection_over_union

_SOURCE_PRIORITY = {"accessibility": 3, "vision": 2, "ocr": 1}


@dataclass(slots=True)
class _Group:
    candidates: list[PerceptionCandidate] = field(default_factory=list)


def _containment_ratio(left: Bounds, right: Bounds) -> float:
    intersection_width = max(0, min(left.right, right.right) - max(left.left, right.left))
    intersection_height = max(0, min(left.bottom, right.bottom) - max(left.top, right.top))
    denominator = min(area(left), area(right))
    return intersection_width * intersection_height / denominator if denominator else 0.0


def _texts(candidate: PerceptionCandidate) -> tuple[str, ...]:
    return tuple(value for value in (candidate.label, candidate.text) if value)


def _roles_compatible(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if "unknown" in {left, right}:
        return 0.75
    if "text" in {left, right}:
        return 0.70
    if {left, right} <= {"button", "checkbox", "radio", "switch", "tab"}:
        return 0.65
    return 0.1


def candidate_match_score(left: PerceptionCandidate, right: PerceptionCandidate) -> float:
    if left.resource_id and left.resource_id == right.resource_id:
        return 1.0
    overlap = max(
        intersection_over_union(left.bounds, right.bounds),
        0.8 * _containment_ratio(left.bounds, right.bounds),
    )
    if overlap < 0.2:
        return 0.0
    left_text = _texts(left)
    right_text = _texts(right)
    text_score = (
        max(similarity(a, b) for a in left_text for b in right_text)
        if left_text and right_text
        else 0.5
    )
    role_score = _roles_compatible(left.role, right.role)
    return round(0.55 * overlap + 0.30 * text_score + 0.15 * role_score, 6)


def _group_score(candidate: PerceptionCandidate, group: _Group) -> float:
    return max(candidate_match_score(candidate, existing) for existing in group.candidates)


def _best_candidate(
    candidates: Iterable[PerceptionCandidate], property_name: str
) -> PerceptionCandidate:
    return max(
        candidates,
        key=lambda item: (
            item.confidence_for(property_name),
            _SOURCE_PRIORITY[item.source],
            -item.order,
            item.source_id,
        ),
    )


def _evidence(candidates: Iterable[PerceptionCandidate], property_name: str) -> PropertyEvidence:
    items = list(candidates)
    combined = 1.0
    for item in items:
        combined *= 1.0 - item.confidence_for(property_name)
    return PropertyEvidence(
        confidence=round(1.0 - combined, 6),
        sources=sorted(
            {
                source
                for item in items
                for source in item.property_sources.get(property_name, (item.source_id,))
            }
        ),
    )


def _element_id(group: _Group, index: int) -> str:
    signature = "|".join(sorted(item.source_id for item in group.candidates))
    digest = hashlib.sha256(f"{index}|{signature}".encode()).hexdigest()[:20]
    return f"el_tmp_{digest}"


def fuse_candidates(
    candidates: Iterable[PerceptionCandidate], *, match_threshold: float = 0.56
) -> list[SemanticElement]:
    """Fuse candidates without merging distinct detections from one source."""

    ordered = sorted(
        candidates,
        key=lambda item: (
            -_SOURCE_PRIORITY[item.source],
            item.order,
            item.bounds.top,
            item.bounds.left,
            item.source_id,
        ),
    )
    groups: list[_Group] = []
    for candidate in ordered:
        scored = [
            (index, _group_score(candidate, group))
            for index, group in enumerate(groups)
            if all(item.source != candidate.source for item in group.candidates)
        ]
        best = max(scored, key=lambda item: (item[1], -item[0]), default=None)
        if best is not None and best[1] >= match_threshold:
            groups[best[0]].candidates.append(candidate)
        else:
            groups.append(_Group([candidate]))

    temporary_ids = [_element_id(group, index) for index, group in enumerate(groups)]
    source_to_element = {
        candidate.source_id: temporary_ids[index]
        for index, group in enumerate(groups)
        for candidate in group.candidates
    }
    elements: list[SemanticElement] = []
    for index, group in enumerate(groups):
        items = group.candidates
        role_items = [item for item in items if item.role != "unknown"] or items
        role_candidate = _best_candidate(role_items, "role")
        label_items = [item for item in items if item.label]
        if not label_items and role_candidate.role in {
            "button",
            "checkbox",
            "radio",
            "switch",
            "tab",
        }:
            label_items = [item for item in items if item.text]
        text_items = [item for item in items if item.text]
        resource_items = [item for item in items if item.resource_id]
        bounds_candidate = _best_candidate(items, "bounds")
        state_items = [item for item in items if item.source == "accessibility"] or items
        state_candidate = _best_candidate(state_items, "state")
        label_candidate = _best_candidate(label_items, "label") if label_items else None
        text_candidate = _best_candidate(text_items, "text") if text_items else None
        resource_candidate = (
            _best_candidate(resource_items, "resource_id") if resource_items else None
        )
        parent_source = next(
            (
                item.parent_source_id
                for item in items
                if item.source == "accessibility" and item.parent_source_id
            ),
            None,
        )
        ancestry = max((item.ancestry for item in items), key=len, default=())
        properties = {
            "role": _evidence(
                [item for item in role_items if item.role == role_candidate.role], "role"
            ),
            "bounds": _evidence(items, "bounds"),
            "state": _evidence(state_items, "state"),
        }
        action_items = [item for item in items if item.actions]
        if action_items:
            properties["actions"] = _evidence(action_items, "actions")
        if label_candidate is not None:
            chosen = label_candidate.label or label_candidate.text
            label_support = [
                item
                for item in items
                if chosen and any(similarity(chosen, value) >= 0.9 for value in _texts(item))
            ]
            properties["label"] = _evidence(label_support, "label")
        else:
            chosen = None
        if text_candidate is not None:
            text_support = [
                item
                for item in text_items
                if item.text and similarity(text_candidate.text or "", item.text) >= 0.9
            ]
            properties["text"] = _evidence(text_support, "text")
        if resource_candidate is not None:
            properties["resource_id"] = _evidence(resource_items, "resource_id")
        parent_items = [item for item in items if item.parent_source_id]
        if parent_items:
            properties["parent"] = _evidence(parent_items, "parent")
        actions = sorted({action for item in items for action in item.actions})
        elements.append(
            SemanticElement(
                id=temporary_ids[index],
                role=role_candidate.role,
                label=chosen,
                label_normalized=normalize(chosen) if chosen else None,
                text=text_candidate.text if text_candidate else None,
                text_normalized=(
                    normalize(text_candidate.text)
                    if text_candidate and text_candidate.text
                    else None
                ),
                resource_id=resource_candidate.resource_id if resource_candidate else None,
                bounds=bounds_candidate.bounds,
                state=ElementState.model_validate(state_candidate.state.model_dump()),
                actions=actions,
                parent=source_to_element.get(parent_source) if parent_source else None,
                properties=properties,
                fingerprint=ElementFingerprint(
                    resource_id=resource_candidate.resource_id if resource_candidate else None,
                    ancestry=[normalize(value) for value in ancestry if value],
                    text_key=normalize(
                        chosen or (text_candidate.text if text_candidate else None) or ""
                    )
                    or None,
                ),
            )
        )
    return sorted(elements, key=lambda item: (item.bounds.top, item.bounds.left, item.id))


def semantic_digest(elements: list[SemanticElement], *, revision: int) -> str:
    payload = {
        "revision": revision,
        "elements": [element.model_dump(mode="json") for element in elements],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def semantic_content_digest(elements: list[SemanticElement]) -> str:
    """Digest user-app content, excluding frame-local IDs and volatile provenance."""

    content = [
        {
            "role": element.role,
            "label": element.label_normalized,
            "text": element.text_normalized,
            "resource_id": element.resource_id,
            "bounds": element.bounds.model_dump(mode="json"),
            "state": element.state.model_dump(mode="json"),
            "actions": element.actions,
        }
        for element in elements
        if not (element.resource_id or "").startswith("com.android.systemui:")
    ]
    content.sort(
        key=lambda item: (
            str(item["resource_id"]),
            str(item["role"]),
            str(item["label"]),
            str(item["text"]),
            json.dumps(item["bounds"], sort_keys=True),
        )
    )
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
