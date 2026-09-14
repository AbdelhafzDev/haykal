"""Conservative trace redaction and bounded retention."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime, timedelta

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, model_validator

from haykal.artifacts import ArtifactStore
from haykal.contracts import TraceEnvelope
from haykal.traces import TraceStore


class ImageRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact: str = "*"
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    right: int = Field(gt=0)
    bottom: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> ImageRegion:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("image redaction region must have positive area")
        return self


class ImageRedactionError(ValueError):
    """An image cannot be exported under the configured fail-closed policy."""


class RedactionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "default"
    replacement: str = "<redacted>"
    sensitive_keys: set[str] = Field(
        default_factory=lambda: {
            "address",
            "authorization",
            "card",
            "email",
            "nonce",
            "otp",
            "password",
            "payment",
            "phone",
            "private_key",
            "secret",
            "token",
        }
    )
    literal_secrets: list[str] = Field(default_factory=list)
    include_images: bool = False
    image_regions: list[ImageRegion] = Field(default_factory=list)

    @model_validator(mode="after")
    def images_require_regions(self) -> RedactionPolicy:
        if self.include_images and not self.image_regions:
            raise ValueError("image export requires at least one redaction region")
        return self


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trace_days: int = Field(default=7, ge=1)
    artifact_days: int = Field(default=7, ge=1)


class Redactor:
    _email = re.compile(r"(?<![\w.])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.])")
    _phone = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){8,15}(?!\d)")
    _card = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

    def __init__(self, policy: RedactionPolicy) -> None:
        self.policy = policy
        self._keys = {key.casefold() for key in policy.sensitive_keys}

    def redact(self, value: object, *, key: str | None = None) -> object:
        if key is not None and self._sensitive_key(key):
            return self.policy.replacement
        if isinstance(value, dict):
            return {
                str(item_key): self.redact(item, key=str(item_key))
                for item_key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            return self._redact_text(value)
        return value

    def redact_image(self, data: bytes, *, artifact: str) -> bytes:
        regions = [
            region for region in self.policy.image_regions if region.artifact in {"*", artifact}
        ]
        if not regions:
            raise ImageRedactionError(f"artifact {artifact} has no matching redaction region")
        with Image.open(io.BytesIO(data)) as image:
            output = image.convert("RGB")
            width, height = output.size
            if any(
                region.left >= width
                or region.top >= height
                or region.right > width
                or region.bottom > height
                for region in regions
            ):
                raise ImageRedactionError(
                    f"artifact {artifact} has a redaction region outside image bounds"
                )
            draw = ImageDraw.Draw(output)
            for region in regions:
                draw.rectangle(
                    (region.left, region.top, region.right, region.bottom),
                    fill=(0, 0, 0),
                )
            rendered = io.BytesIO()
            output.save(rendered, format="PNG", optimize=True)
            return rendered.getvalue()

    def redact_event(self, event: TraceEnvelope) -> dict[str, object]:
        payload = event.model_dump(mode="json")
        payload["payload"] = self.redact(payload.get("payload", {}))
        if not self.policy.include_images:
            payload["artifacts"] = []
        payload["redaction"] = {"policy": self.policy.name, "applied": True}
        return payload

    def _sensitive_key(self, key: str) -> bool:
        separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
        folded = re.sub(r"[^\w]+", "_", separated.casefold())
        return any(part in self._keys for part in folded.split("_"))

    def _redact_text(self, value: str) -> str:
        redacted = value
        for secret in sorted(self.policy.literal_secrets, key=len, reverse=True):
            if secret:
                redacted = redacted.replace(secret, self.policy.replacement)
        redacted = self._email.sub(self.policy.replacement, redacted)
        redacted = self._phone.sub(self.policy.replacement, redacted)
        return self._card.sub(self.policy.replacement, redacted)


class RetentionService:
    def __init__(self, traces: TraceStore, artifacts: ArtifactStore) -> None:
        self.traces = traces
        self.artifacts = artifacts

    def apply(
        self,
        policy: RetentionPolicy,
        *,
        now: datetime | None = None,
        dry_run: bool = True,
    ) -> dict[str, object]:
        current = now or datetime.now(UTC)
        trace_cutoff = current - timedelta(days=policy.trace_days)
        artifact_cutoff = current - timedelta(days=policy.artifact_days)
        return {
            "dry_run": dry_run,
            "trace_cutoff": trace_cutoff.isoformat(),
            "artifact_cutoff": artifact_cutoff.isoformat(),
            "trace_events": self.traces.prune_before(trace_cutoff, dry_run=dry_run),
            "artifacts": self.artifacts.prune_before(artifact_cutoff, dry_run=dry_run),
        }
