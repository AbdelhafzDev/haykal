"""Internal normalized perception candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from haykal.contracts.common import Bounds
from haykal.contracts.scene import ElementState
from haykal.contracts.selector import Role

SourceKind = Literal["accessibility", "ocr", "vision"]
ActionKind = Literal["tap", "input_text", "scroll", "check", "select"]


@dataclass(frozen=True, slots=True)
class PerceptionCandidate:
    source: SourceKind
    source_id: str
    bounds: Bounds
    role: Role = "unknown"
    label: str | None = None
    text: str | None = None
    resource_id: str | None = None
    state: ElementState = field(
        default_factory=lambda: ElementState(
            enabled=True,
            visible=True,
            focused=False,
            checked=None,
            selected=None,
            scrollable=False,
        )
    )
    actions: tuple[ActionKind, ...] = ()
    parent_source_id: str | None = None
    ancestry: tuple[str, ...] = ()
    property_confidence: dict[str, float] = field(default_factory=dict)
    property_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    order: int = 0

    def confidence_for(self, property_name: str) -> float:
        default = 0.96 if self.source == "accessibility" else 0.75
        return self.property_confidence.get(property_name, default)


def area(bounds: Bounds) -> int:
    return max(0, bounds.right - bounds.left) * max(0, bounds.bottom - bounds.top)


def intersection_over_union(left: Bounds, right: Bounds) -> float:
    intersection_width = max(0, min(left.right, right.right) - max(left.left, right.left))
    intersection_height = max(0, min(left.bottom, right.bottom) - max(left.top, right.top))
    intersection = intersection_width * intersection_height
    union = area(left) + area(right) - intersection
    return intersection / union if union else 0.0


def contains(outer: Bounds, inner: Bounds) -> bool:
    return (
        outer.left <= inner.left
        and outer.top <= inner.top
        and outer.right >= inner.right
        and outer.bottom >= inner.bottom
    )
