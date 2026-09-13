"""Secure normalization of Android UIAutomator hierarchy XML."""

from __future__ import annotations

import re
import xml.etree.ElementTree as StandardElementTree
from dataclasses import dataclass, replace

from defusedxml import ElementTree

from haykal.contracts.common import Bounds
from haykal.contracts.scene import ElementState
from haykal.contracts.selector import Role

from .model import ActionKind, PerceptionCandidate

_BOUNDS = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")


class HierarchyParseError(ValueError):
    """Hierarchy XML is malformed or violates bounded parser rules."""


@dataclass(frozen=True, slots=True)
class HierarchyPolicy:
    max_bytes: int = 8_000_000
    max_nodes: int = 50_000


DEFAULT_HIERARCHY_POLICY = HierarchyPolicy()


def _lift_actionable_labels(
    candidates: list[PerceptionCandidate],
) -> list[PerceptionCandidate]:
    """Attach bounded descendant text to otherwise unlabelled clickable controls."""

    children: dict[str, list[PerceptionCandidate]] = {}
    for candidate in candidates:
        if candidate.parent_source_id is not None:
            children.setdefault(candidate.parent_source_id, []).append(candidate)

    enriched: list[PerceptionCandidate] = []
    for candidate in candidates:
        if not candidate.actions or candidate.label or candidate.text:
            enriched.append(candidate)
            continue
        labels: list[tuple[str, str]] = []
        pending = list(children.get(candidate.source_id, ()))
        visited = 0
        while pending and len(labels) < 4 and visited < 64:
            descendant = pending.pop(0)
            visited += 1
            if descendant.actions:
                continue
            value = descendant.label or descendant.text
            if value and value not in {existing for existing, _ in labels}:
                labels.append((value, descendant.source_id))
            pending.extend(children.get(descendant.source_id, ()))
        if not labels:
            enriched.append(candidate)
            continue
        confidence = dict(candidate.property_confidence)
        confidence["label"] = 0.92
        property_sources = dict(candidate.property_sources)
        property_sources["label"] = tuple(source for _, source in labels)
        enriched.append(
            replace(
                candidate,
                label=" | ".join(value for value, _ in labels),
                property_confidence=confidence,
                property_sources=property_sources,
            )
        )
    return enriched


def _boolean(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.casefold() == "true"


def _bounds(raw: str | None) -> Bounds | None:
    match = _BOUNDS.fullmatch(raw or "")
    if match is None:
        return None
    left, top, right, bottom = (int(value) for value in match.groups())
    if right <= left or bottom <= top:
        return None
    return Bounds(left=left, top=top, right=right, bottom=bottom)


def _role(class_name: str, *, clickable: bool, scrollable: bool, editable: bool) -> Role:
    short = class_name.rsplit(".", 1)[-1].casefold()
    if editable or short in {"edittext", "textfield"}:
        return "textbox"
    if "checkbox" in short:
        return "checkbox"
    if "radiobutton" in short:
        return "radio"
    if "switch" in short or "toggle" in short:
        return "switch"
    if "button" in short or clickable:
        return "button"
    if "webview" in short:
        return "webview"
    if scrollable or any(token in short for token in ("listview", "recyclerview")):
        return "list"
    if "image" in short:
        return "image"
    if "text" in short:
        return "text"
    return "container" if short in {"view", "viewgroup", "framelayout"} else "unknown"


def parse_hierarchy(
    xml: str | bytes,
    *,
    policy: HierarchyPolicy = DEFAULT_HIERARCHY_POLICY,
) -> list[PerceptionCandidate]:
    """Parse a bounded UIAutomator hierarchy without DTD or entity expansion."""

    encoded = xml.encode("utf-8") if isinstance(xml, str) else xml
    if len(encoded) > policy.max_bytes:
        raise HierarchyParseError("hierarchy exceeds byte budget")
    try:
        root = ElementTree.fromstring(encoded)
    except Exception as exc:
        raise HierarchyParseError("invalid hierarchy XML") from exc

    candidates: list[PerceptionCandidate] = []

    def walk(
        node: StandardElementTree.Element,
        parent_id: str | None,
        ancestry: tuple[str, ...],
    ) -> None:
        if len(candidates) >= policy.max_nodes:
            raise HierarchyParseError("hierarchy exceeds node budget")
        attributes = getattr(node, "attrib", {})
        children = list(node)
        if getattr(node, "tag", None) != "node":
            for child in children:
                walk(child, parent_id, ancestry)
            return

        parsed_bounds = _bounds(attributes.get("bounds"))
        source_id = f"accessibility:node_{len(candidates)}"
        clickable = _boolean(attributes.get("clickable"))
        scrollable = _boolean(attributes.get("scrollable"))
        editable = _boolean(attributes.get("editable"))
        class_name = attributes.get("class", "")
        role = _role(
            class_name,
            clickable=clickable,
            scrollable=scrollable,
            editable=editable,
        )
        resource_id = attributes.get("resource-id") or None
        text = attributes.get("text") or None
        label = attributes.get("content-desc") or None
        actions: list[ActionKind] = []
        if clickable:
            actions.append("tap")
        if editable or role == "textbox":
            actions.append("input_text")
        if scrollable:
            actions.append("scroll")
        if role == "checkbox":
            actions.append("check")
        if role in {"radio", "switch", "tab"}:
            actions.append("select")
        ancestry_key = resource_id or label or text or role
        next_ancestry = (*ancestry, ancestry_key)[-8:]
        if parsed_bounds is not None:
            candidates.append(
                PerceptionCandidate(
                    source="accessibility",
                    source_id=source_id,
                    bounds=parsed_bounds,
                    role=role,
                    label=label,
                    text=text,
                    resource_id=resource_id,
                    state=ElementState(
                        enabled=_boolean(attributes.get("enabled"), True),
                        visible=_boolean(attributes.get("visible-to-user"), True),
                        focused=_boolean(attributes.get("focused")),
                        checked=(
                            _boolean(attributes.get("checked"))
                            if attributes.get("checkable") == "true"
                            else None
                        ),
                        selected=(
                            _boolean(attributes.get("selected"))
                            if "selected" in attributes
                            else None
                        ),
                        scrollable=scrollable,
                    ),
                    actions=tuple(dict.fromkeys(actions)),
                    parent_source_id=parent_id,
                    ancestry=ancestry,
                    property_confidence={
                        "role": 0.97,
                        "bounds": 0.99,
                        "label": 0.98,
                        "text": 0.98,
                        "resource_id": 1.0,
                        "state": 0.98,
                        "actions": 0.98,
                        "parent": 0.99,
                    },
                    property_sources=(
                        {
                            "parent": tuple(
                                source for source in (source_id, parent_id) if source is not None
                            )
                        }
                        if parent_id is not None
                        else {}
                    ),
                    order=len(candidates),
                )
            )
            parent_for_children: str | None = source_id
        else:
            parent_for_children = parent_id
        for child in children:
            walk(child, parent_for_children, next_ancestry)

    walk(root, None, ())
    return _lift_actionable_labels(candidates)
