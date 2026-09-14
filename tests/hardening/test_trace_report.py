from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from haykal.artifacts import ArtifactStore
from haykal.hardening import ImageRegion, RedactionPolicy, TraceReportExporter
from haykal.traces import TraceStore


def _png() -> bytes:
    image = Image.new("RGB", (12, 12), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_static_trace_export_redacts_payload_and_images(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "runtime.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifact = artifacts.put(_png())
    traces.append(
        trace_id="trace-1",
        run_id="run-1",
        event_type="observation.created",
        payload={"address": "private", "note": "user@example.com"},
        artifacts=[artifact.digest],
    )
    destination = tmp_path / "report"

    result = TraceReportExporter(traces, artifacts).export(
        "trace-1",
        destination,
        RedactionPolicy(
            include_images=True,
            image_regions=[ImageRegion(left=0, top=0, right=6, bottom=6)],
        ),
    )

    assert result.events == 1
    assert result.artifacts_exported == 1
    document = json.loads((destination / "trace.json").read_text(encoding="utf-8"))
    assert document["events"][0]["payload"] == {
        "address": "<redacted>",
        "note": "<redacted>",
    }
    assert "private" not in (destination / "index.html").read_text(encoding="utf-8")
    exported = next((destination / "artifacts").glob("*.png"))
    with Image.open(exported) as image:
        assert image.getpixel((2, 2)) == (0, 0, 0)


def test_default_export_omits_sensitive_images(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "runtime.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifact = artifacts.put(_png())
    traces.append(
        trace_id="trace-1",
        run_id="run-1",
        event_type="observation.created",
        artifacts=[artifact.digest],
    )
    result = TraceReportExporter(traces, artifacts).export(
        "trace-1", tmp_path / "report", RedactionPolicy()
    )
    assert result.artifacts_exported == 0
    assert result.artifacts_omitted == 1
    assert not (tmp_path / "report" / "artifacts").exists()


def test_malformed_image_aborts_the_entire_export(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "runtime.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    valid = artifacts.put(_png())
    invalid = artifacts.put(b"not-an-image")
    traces.append(
        trace_id="trace-1",
        run_id="run-1",
        event_type="observation.created",
        artifacts=[valid.digest, invalid.digest],
    )
    destination = tmp_path / "report"

    with pytest.raises(ValueError, match="cannot be safely exported"):
        TraceReportExporter(traces, artifacts).export(
            "trace-1",
            destination,
            RedactionPolicy(
                include_images=True,
                image_regions=[ImageRegion(left=0, top=0, right=6, bottom=6)],
            ),
        )

    assert not destination.exists()
