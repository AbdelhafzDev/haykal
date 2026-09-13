"""Bounded selector vocabulary and semantic dictionary validation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import Confidence, ContractModel, NonNegativeInt

Role = Literal[
    "button",
    "textbox",
    "text",
    "image",
    "checkbox",
    "radio",
    "switch",
    "list",
    "list_item",
    "tab",
    "dialog",
    "container",
    "webview",
    "unknown",
]


class TextMatch(ContractModel):
    equals: str | None = None
    contains: str | None = None
    any_contains: list[str] | None = None
    similar: str | None = None
    threshold: Confidence | None = None
    regex: str | None = None
    normalization: Literal["arabic-search@1", "arabic-material@1"] = "arabic-search@1"

    @model_validator(mode="after")
    def exactly_one_operator(self) -> TextMatch:
        operators = (self.equals, self.contains, self.any_contains, self.similar, self.regex)
        if sum(value is not None for value in operators) != 1:
            raise ValueError("text match requires exactly one operator")
        if self.threshold is not None and self.similar is None:
            raise ValueError("threshold is valid only with similar")
        if self.any_contains is not None and not self.any_contains:
            raise ValueError("any_contains must not be empty")
        return self


class ResourceMatch(ContractModel):
    equals: str | None = None
    ends_with: str | None = None
    regex: str | None = None

    @model_validator(mode="after")
    def exactly_one_operator(self) -> ResourceMatch:
        if sum(value is not None for value in (self.equals, self.ends_with, self.regex)) != 1:
            raise ValueError("resource match requires exactly one operator")
        return self


class Near(ContractModel):
    selector: Selector
    direction: Literal["left", "right", "above", "below", "overlap"]
    max_px: int = Field(gt=0)


class Selector(ContractModel):
    element_id: str | None = None
    scene_revision: NonNegativeInt | None = None
    semantic_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    role: Role | list[Role] | None = None
    resource_id: ResourceMatch | None = None
    within: Selector | None = None
    near: Near | None = None
    label: TextMatch | None = None
    text: TextMatch | None = None
    focused: bool | None = None
    enabled: bool | None = None
    checked: bool | None = None
    selected: bool | None = None
    scrollable: bool | None = None
    position: Literal["first", "last", "index"] | None = None
    index: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> Selector:
        if (self.element_id is None) != (self.scene_revision is None):
            raise ValueError("element_id and scene_revision must appear together")
        if self.position == "index" and self.index is None:
            raise ValueError("position index requires index")
        if self.index is not None and self.position != "index":
            raise ValueError("index requires position=index")
        identity = (
            self.element_id,
            self.semantic_name,
            self.resource_id,
            self.label,
            self.text,
            self.position,
        )
        if not any(value is not None for value in identity):
            raise ValueError("selector is under-specified")
        return self


Selector.model_rebuild()


def semantic_references(selector: Selector) -> set[str]:
    references: set[str] = set()
    if selector.semantic_name:
        references.add(selector.semantic_name)
    if selector.within:
        references.update(semantic_references(selector.within))
    if selector.near:
        references.update(semantic_references(selector.near.selector))
    return references


def validate_element_dictionary(elements: dict[str, Selector]) -> None:
    """Reject unknown semantic references and cycles."""

    referenced = set().union(*(semantic_references(value) for value in elements.values()))
    unknown = referenced - elements.keys()
    if unknown:
        raise ValueError(f"undefined semantic names: {', '.join(sorted(unknown))}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"element dictionary cycle at {name}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in semantic_references(elements[name]):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for element_name in elements:
        visit(element_name)
