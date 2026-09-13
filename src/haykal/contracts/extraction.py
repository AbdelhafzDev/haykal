"""Typed extraction request and evidence contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, PositiveInt, SchemaVersion, SettlePolicy
from .selector import Selector


def _accessibility_source() -> list[Literal["accessibility", "ocr", "vision"]]:
    return ["accessibility"]


class ExtractionGroup(ContractModel):
    by: Literal["single", "ancestry", "repeat", "rows"]
    root: Selector | None = None
    record: Selector | None = None
    band_px: PositiveInt | None = None

    @model_validator(mode="after")
    def grouping_fields(self) -> ExtractionGroup:
        if self.by == "ancestry" and self.record is None:
            raise ValueError("ancestry grouping requires record selector")
        if self.by == "rows" and self.band_px is None:
            raise ValueError("rows grouping requires band_px")
        return self


class ExtractionField(ContractModel):
    selector: Selector
    type: Literal["text", "number", "money", "rating", "duration", "boolean", "image_crop"]
    required: bool = False
    scale: Literal[5, 10] | None = None
    true_tokens: list[str] | None = None
    false_tokens: list[str] | None = None
    default_when_absent: bool | None = None
    privacy: Literal["public", "masked", "secret"] = "public"

    @model_validator(mode="after")
    def type_options(self) -> ExtractionField:
        if self.scale is not None and self.type != "rating":
            raise ValueError("scale is valid only for rating")
        boolean_options = (self.true_tokens, self.false_tokens, self.default_when_absent)
        if any(value is not None for value in boolean_options) and self.type != "boolean":
            raise ValueError("boolean options are valid only for boolean")
        return self


class ScrollExtraction(ContractModel):
    within: Selector
    max_pages: PositiveInt
    settle: SettlePolicy = Field(default_factory=SettlePolicy)


class ExtractionLimits(ContractModel):
    max_records: PositiveInt | None = None
    max_ms: PositiveInt | None = None


class ExtractionRequest(ContractModel):
    schema_version: SchemaVersion = "1.0"
    scene_id: str | None = None
    require_sources: list[Literal["accessibility", "ocr", "vision"]] = Field(
        default_factory=_accessibility_source
    )
    group: ExtractionGroup
    fields: dict[str, ExtractionField] = Field(min_length=1)
    scroll: ScrollExtraction | None = None
    dedupe_by: list[str] = Field(default_factory=list)
    limits: ExtractionLimits = Field(default_factory=ExtractionLimits)

    @model_validator(mode="after")
    def valid_field_references(self) -> ExtractionRequest:
        unknown = set(self.dedupe_by) - self.fields.keys()
        if unknown:
            raise ValueError(f"dedupe_by references unknown fields: {', '.join(sorted(unknown))}")
        return self


class FieldEvidence(ContractModel):
    scene_id: str
    element_ids: list[str] = Field(min_length=1)
    sources: list[str] = Field(min_length=1)


class ScrollCheckpoint(ContractModel):
    container: str | None = None
    page: int = Field(ge=0)
    visible_signature: str


class RecordAnchor(ContractModel):
    element_id: str
    scene_revision: int = Field(ge=0)
    fingerprint: str
    scroll_checkpoint: ScrollCheckpoint | None = None


class ExtractedRecord(ContractModel):
    record_id: str
    fields: dict[str, object | None]
    evidence: dict[str, FieldEvidence | None]
    anchor: RecordAnchor | None = None
    ambiguities: list[dict[str, object]] = Field(default_factory=list)


class ExtractionResult(ContractModel):
    schema_version: SchemaVersion = "1.0"
    extraction_id: str
    input_scene_id: str
    effective_scene_id: str
    scenes: list[str] = Field(min_length=1)
    request_satisfied: bool
    source_exhausted: bool
    truncated: bool
    stop_reason: Literal[
        "end_of_list", "max_records", "max_pages", "max_ms", "no_new_records", "scene_unstable"
    ]
    records: list[ExtractedRecord]
    dropped_records: list[dict[str, object]] = Field(default_factory=list)
