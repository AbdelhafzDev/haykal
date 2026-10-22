"""Fail-closed production acceptance manifest and evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GitObject = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
PositiveInt = Annotated[int, Field(gt=0)]


class GateStatus(StrEnum):
    """State of an evidence-backed release gate."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ProductionGateName(StrEnum):
    """Gates required for the single-tenant production pilot."""

    HOSTED_P95_4 = "hosted_p95_4"
    OMNIPARSER_FALLBACK = "omniparser_fallback"
    EIGHT_HOUR_SOAK = "eight_hour_soak"
    REGIONAL_APPS = "regional_apps"
    DEPLOYMENT_DRILL = "deployment_drill"
    SECURITY_REVIEW = "security_review"


class ScoreGateName(StrEnum):
    """Independent evidence required for the separate 95/100 claim."""

    NON_CORE_AUTHOR = "non_core_author"
    EXTERNAL_BENCHMARK = "external_benchmark"


class EvidenceGate(BaseModel):
    """A gate whose pass state must carry immutable evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: GateStatus
    summary: Annotated[str, Field(min_length=1)]
    evidence_sha256: Sha256 | None = None
    evidence_uri: Annotated[str, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def require_evidence_for_pass(self) -> EvidenceGate:
        if self.status is GateStatus.PASSED:
            if self.evidence_sha256 is None or self.evidence_uri is None:
                raise ValueError("a passed gate requires evidence_sha256 and evidence_uri")
        elif self.evidence_sha256 is not None or self.evidence_uri is not None:
            raise ValueError("pending or failed gates cannot claim acceptance evidence")
        return self


class ReleaseIdentity(BaseModel):
    """Immutable P95.4 release identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    commit: GitObject
    source_tree: GitObject
    wheel_sha256: Sha256
    apk_sha256: Sha256
    build_manifest_sha256: Sha256
    hosted_run_uri: Annotated[str, Field(pattern=r"^https://github\.com/.+/actions/runs/[0-9]+$")]


class HostContract(BaseModel):
    """One intentionally narrow production reference host."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operating_system: Literal["Ubuntu 24.04 LTS"]
    architecture: Literal["x86_64"]
    python: Annotated[str, Field(pattern=r"^3\.(11|12|13)(\.[0-9]+)?$")]
    minimum_vcpus: PositiveInt
    minimum_memory_bytes: PositiveInt
    minimum_encrypted_disk_bytes: PositiveInt


class AndroidImage(BaseModel):
    """Pinned reference or compatibility Android image."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["reference", "compatibility"]
    api_level: Literal[34, 35]
    target: Literal["google_apis"]
    architecture: Literal["x86_64"]
    profile: Literal["pixel_6"]
    fingerprint: Annotated[str, Field(min_length=1)]


class DeploymentContract(BaseModel):
    """Supported production deployment shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenancy: Literal["single_tenant"]
    device_count: Literal[1]
    executor: Literal["uiautomator2"]
    host: HostContract
    android_images: tuple[AndroidImage, ...]

    @model_validator(mode="after")
    def require_one_reference_and_compatibility_image(self) -> DeploymentContract:
        roles = [image.role for image in self.android_images]
        levels = {image.api_level for image in self.android_images}
        if roles.count("reference") != 1 or levels != {34, 35}:
            raise ValueError("deployment requires one reference image and API 34/35 coverage")
        reference = next(image for image in self.android_images if image.role == "reference")
        if reference.api_level != 35:
            raise ValueError("API 35 must be the production reference image")
        return self


class OperationalLimits(BaseModel):
    """Predeclared limits used by soak and deployment acceptance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_free_disk_bytes: PositiveInt
    trace_retention_days: PositiveInt
    artifact_retention_days: PositiveInt
    request_timeout_seconds: PositiveInt
    lease_duration_seconds: PositiveInt
    maximum_recovery_seconds: PositiveInt
    maximum_core_rss_bytes: PositiveInt
    maximum_model_rss_bytes: PositiveInt
    maximum_state_bytes: PositiveInt
    maximum_open_descriptors: PositiveInt
    maximum_core_p95_milliseconds: PositiveInt
    maximum_fallback_p95_milliseconds: PositiveInt
    maximum_state_growth_bytes_per_second: Annotated[int, Field(ge=0)]
    maximum_rss_growth_bytes_per_second: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def keep_artifacts_for_the_trace_lifetime(self) -> OperationalLimits:
        if self.artifact_retention_days < self.trace_retention_days:
            raise ValueError("artifact retention cannot be shorter than trace retention")
        if self.maximum_recovery_seconds >= self.lease_duration_seconds:
            raise ValueError("recovery must finish before the active lease expires")
        return self


class ModelArtifact(BaseModel):
    """One locally cached perception artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(min_length=1)]
    role: Literal["detector", "captioner"]
    upstream_revision: GitObject
    sha256: Sha256
    license: Literal["MIT"]


class PerceptionContract(BaseModel):
    """Production perception boundary without runtime downloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: Literal["accessibility"]
    fallback: Literal["none", "omniparser_v2"]
    model_artifacts: tuple[ModelArtifact, ...] = ()
    offline_cache_required: Literal[True]
    network_download_allowed: Literal[False]

    @model_validator(mode="after")
    def require_complete_omniparser_pair(self) -> PerceptionContract:
        roles = {artifact.role for artifact in self.model_artifacts}
        if self.fallback == "none" and self.model_artifacts:
            raise ValueError("model artifacts are not allowed when fallback is disabled")
        if self.fallback == "omniparser_v2" and roles != {"detector", "captioner"}:
            raise ValueError("OmniParser V2 requires one detector and one captioner role")
        if len(roles) != len(self.model_artifacts):
            raise ValueError("perception model roles must be unique")
        return self


class ProductionAcceptanceManifest(BaseModel):
    """Complete contract evaluated before production pilot release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    manifest_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")]
    created_at: datetime
    release: ReleaseIdentity
    deployment: DeploymentContract
    operational_limits: OperationalLimits
    perception: PerceptionContract
    production_gates: dict[ProductionGateName, EvidenceGate]
    score_gates: dict[ScoreGateName, EvidenceGate]

    @model_validator(mode="after")
    def require_complete_gate_sets(self) -> ProductionAcceptanceManifest:
        if set(self.production_gates) != set(ProductionGateName):
            raise ValueError("manifest must declare every production gate exactly once")
        if set(self.score_gates) != set(ScoreGateName):
            raise ValueError("manifest must declare every score gate exactly once")
        fallback_gate = self.production_gates[ProductionGateName.OMNIPARSER_FALLBACK]
        if (
            fallback_gate.status is GateStatus.PASSED
            and self.perception.fallback != "omniparser_v2"
        ):
            raise ValueError("passed OmniParser gate requires the pinned OmniParser V2 fallback")
        return self


class ProductionEvaluation(BaseModel):
    """Derived decision; callers cannot write their own release result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    manifest_sha256: Sha256
    production_eligible: bool
    score_95_evidence_complete: bool
    blocking_gates: tuple[str, ...]
    pending_score_gates: tuple[str, ...]


def production_manifest_digest(manifest: ProductionAcceptanceManifest) -> str:
    """Hash the normalized manifest rather than its presentation formatting."""

    payload = manifest.model_dump(mode="json")
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def evaluate_production_manifest(manifest: ProductionAcceptanceManifest) -> ProductionEvaluation:
    """Derive pilot and score decisions solely from evidence-backed gates."""

    blocking = tuple(
        gate.value
        for gate in ProductionGateName
        if manifest.production_gates[gate].status is not GateStatus.PASSED
    )
    pending_score = tuple(
        gate.value
        for gate in ScoreGateName
        if manifest.score_gates[gate].status is not GateStatus.PASSED
    )
    return ProductionEvaluation(
        manifest_id=manifest.manifest_id,
        manifest_sha256=production_manifest_digest(manifest),
        production_eligible=not blocking,
        score_95_evidence_complete=not blocking and not pending_score,
        blocking_gates=blocking,
        pending_score_gates=pending_score,
    )


def load_production_manifest(path: str | Path) -> ProductionAcceptanceManifest:
    """Load and strictly validate a production manifest."""

    source = Path(path)
    return ProductionAcceptanceManifest.model_validate_json(source.read_text(encoding="utf-8"))
