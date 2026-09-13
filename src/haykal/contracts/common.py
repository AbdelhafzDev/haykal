"""Shared strict types for the v1 public contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SchemaVersion = Literal["1.0"]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class ContractModel(BaseModel):
    """Base for canonical objects: strict fields and JSON-friendly output."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Bounds(ContractModel):
    left: int
    top: int
    right: int
    bottom: int


class ArtifactPointer(ContractModel):
    artifact: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: str | None = None
    captured_at: datetime | None = None
    backend: str | None = None


class SettlePolicy(ContractModel):
    stable_samples: PositiveInt = 2
    interval_ms: PositiveInt = 250
