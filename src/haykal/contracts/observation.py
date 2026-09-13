"""Raw observation contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import ArtifactPointer, ContractModel, NonNegativeInt, SchemaVersion


class Display(ContractModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    density: float = Field(gt=0)
    rotation: int = Field(ge=0, le=3)


class ForegroundApp(ContractModel):
    package: str = Field(min_length=1)
    activity: str | None = None


class KeyboardState(ContractModel):
    visible: bool


class CaptureEvidence(ArtifactPointer):
    captured_at: datetime
    backend: str = Field(min_length=1)


class RawObservation(ContractModel):
    schema_version: SchemaVersion = "1.0"
    observation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    revision: NonNegativeInt
    display: Display
    foreground: ForegroundApp
    keyboard: KeyboardState
    hierarchy: CaptureEvidence
    screenshot: CaptureEvidence
    capture_skew_ms: NonNegativeInt
    warnings: list[str] = Field(default_factory=list)
