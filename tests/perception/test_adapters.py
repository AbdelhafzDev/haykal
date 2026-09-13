from __future__ import annotations

import time

import pytest

from haykal.perception.adapters import AdapterIdentity, NormalizedJsonAdapter

DIGEST = "sha256:" + "a" * 64


def test_adapter_identity_requires_content_digests() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        AdapterIdentity(name="ocr", version="1", model_digest="latest")


@pytest.mark.asyncio
async def test_json_adapter_rejects_unknown_and_out_of_bounds_output() -> None:
    identity = AdapterIdentity(name="fixture", version="1", model_digest=DIGEST)
    unknown = NormalizedJsonAdapter(
        source="ocr",
        identity=identity,
        runner=lambda _image: [{"bounds": [0, 0, 10, 10], "surprise": True}],
    )
    with pytest.raises(ValueError, match="unknown adapter fields"):
        await unknown.detect(b"png", width=100, height=100)

    outside = NormalizedJsonAdapter(
        source="ocr",
        identity=identity,
        runner=lambda _image: [{"bounds": [0, 0, 101, 10], "text": "بيتزا"}],
    )
    with pytest.raises(ValueError, match="exceed display"):
        await outside.detect(b"png", width=100, height=100)


@pytest.mark.asyncio
async def test_json_adapter_deadline_is_bounded() -> None:
    def slow(_image: bytes) -> list[dict[str, object]]:
        time.sleep(0.1)
        return []

    adapter = NormalizedJsonAdapter(
        source="ocr",
        identity=AdapterIdentity(name="slow", version="1", model_digest=DIGEST),
        runner=slow,
        timeout_s=0.01,
    )
    with pytest.raises(TimeoutError):
        await adapter.detect(b"png", width=100, height=100)
