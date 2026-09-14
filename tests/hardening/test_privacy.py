from __future__ import annotations

import io
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from haykal.artifacts import ArtifactStore
from haykal.contracts import TraceEnvelope
from haykal.hardening import (
    ImageRedactionError,
    ImageRegion,
    RedactionPolicy,
    Redactor,
    RetentionPolicy,
    RetentionService,
)
from haykal.traces import TraceStore


def test_recursive_text_and_image_region_redaction() -> None:
    policy = RedactionPolicy(
        literal_secrets=["OTP-SECRET"],
        include_images=True,
        image_regions=[ImageRegion(left=0, top=0, right=5, bottom=5)],
    )
    redactor = Redactor(policy)
    value = redactor.redact(
        {
            "address": "Riyadh",
            "message": "mail me@example.com or +966 55 123 4567 OTP-SECRET",
        }
    )
    assert value == {
        "address": "<redacted>",
        "message": "mail <redacted> or <redacted><redacted>",
    }

    image = Image.new("RGB", (10, 10), "white")
    source = io.BytesIO()
    image.save(source, format="PNG")
    rendered = redactor.redact_image(source.getvalue(), artifact="sha256:any")
    with Image.open(io.BytesIO(rendered)) as redacted:
        assert redacted.getpixel((2, 2)) == (0, 0, 0)
        assert redacted.getpixel((8, 8)) == (255, 255, 255)


def test_trace_event_redaction_corrects_the_public_policy_record() -> None:
    event = TraceEnvelope.model_validate(
        {
            "run_id": "run",
            "sequence": 1,
            "event_type": "run.started",
            "occurred_at": "2026-09-13T00:00:00Z",
            "payload": {"token": "do-not-export"},
            "trace_id": "trace",
            "redaction": {"policy": "raw", "applied": False},
        }
    )
    rendered = Redactor(RedactionPolicy(name="public")).redact_event(event)
    assert rendered["payload"] == {"token": "<redacted>"}
    assert rendered["redaction"] == {"policy": "public", "applied": True}
    assert rendered["artifacts"] == []

    with pytest.raises(ValidationError, match="redaction region"):
        RedactionPolicy(include_images=True)


def test_image_redaction_fails_without_matching_or_in_bounds_region() -> None:
    image = Image.new("RGB", (10, 10), "white")
    source = io.BytesIO()
    image.save(source, format="PNG")
    data = source.getvalue()

    unmatched = Redactor(
        RedactionPolicy(
            include_images=True,
            image_regions=[ImageRegion(artifact="sha256:other", left=0, top=0, right=5, bottom=5)],
        )
    )
    with pytest.raises(ImageRedactionError, match="no matching"):
        unmatched.redact_image(data, artifact="sha256:target")

    out_of_bounds = Redactor(
        RedactionPolicy(
            include_images=True,
            image_regions=[ImageRegion(left=0, top=0, right=11, bottom=10)],
        )
    )
    with pytest.raises(ImageRedactionError, match="outside image bounds"):
        out_of_bounds.redact_image(data, artifact="sha256:target")


def test_literal_arabic_identity_is_redacted_under_generic_keys() -> None:
    name = "عبد الحفيظ محمد"
    address = "شارع الملك فهد، الرياض"
    redactor = Redactor(RedactionPolicy(literal_secrets=[name, address]))

    rendered = redactor.redact({"actual": f"التوصيل إلى {name} في {address}", "candidate": name})

    encoded = str(rendered)
    assert name not in encoded
    assert address not in encoded
    assert encoded.count("<redacted>") == 3


def test_retention_is_preview_first_and_then_deletes(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "runtime.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    traces.append(
        trace_id="trace",
        run_id="run",
        event_type="run.started",
    )
    artifact = artifacts.put(b"old")
    old = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(artifact.path, (old, old))
    service = RetentionService(traces, artifacts)
    policy = RetentionPolicy(trace_days=7, artifact_days=7)
    future = datetime.now(UTC) + timedelta(days=8)

    preview = service.apply(policy, now=future)
    assert preview["dry_run"] is True
    assert preview["trace_events"] == 1
    assert preview["artifacts"] == 1
    assert traces.read("trace")
    assert artifact.path.exists()

    applied = service.apply(policy, now=future, dry_run=False)
    assert applied["trace_events"] == 1
    assert applied["artifacts"] == 1
    assert traces.read("trace") == []
    assert not artifact.path.exists()
