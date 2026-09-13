"""Semantic scene contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import Bounds, Confidence, ContractModel, NonNegativeInt, SchemaVersion
from .selector import Role


class ElementState(ContractModel):
    enabled: bool
    visible: bool
    focused: bool
    checked: bool | None = None
    selected: bool | None = None
    scrollable: bool


class PropertyEvidence(ContractModel):
    confidence: Confidence
    sources: list[str] = Field(min_length=1)


class ElementFingerprint(ContractModel):
    resource_id: str | None = None
    ancestry: list[str] = Field(default_factory=list)
    text_key: str | None = None


class SemanticElement(ContractModel):
    id: str = Field(min_length=1)
    role: Role
    label: str | None = None
    label_normalized: str | None = None
    text: str | None = None
    text_normalized: str | None = None
    resource_id: str | None = None
    bounds: Bounds
    state: ElementState
    actions: list[Literal["tap", "input_text", "scroll", "check", "select"]]
    parent: str | None = None
    properties: dict[str, PropertyEvidence]
    fingerprint: ElementFingerprint


class SceneQuality(ContractModel):
    score: Confidence
    accessibility_coverage: Confidence
    fallbacks_used: list[Literal["ocr", "vision"]] = Field(default_factory=list)


class SemanticScene(ContractModel):
    schema_version: SchemaVersion = "1.0"
    scene_id: str = Field(min_length=1)
    observation_id: str | None = None
    session_id: str = Field(min_length=1)
    revision: NonNegativeInt
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    quality: SceneQuality
    elements: list[SemanticElement]
