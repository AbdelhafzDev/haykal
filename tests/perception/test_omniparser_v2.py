from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from haykal.perception import (
    OmniParserCacheError,
    OmniParserModelManifest,
    OmniParserV2Runner,
    build_omniparser_v2_adapter,
    model_manifest_digest,
    prepare_model_cache,
    verify_model_cache,
)
from haykal.perception.omniparser_v2 import PinnedModelFile

REVISION = "1" * 40


def _sha(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _manifest() -> tuple[OmniParserModelManifest, dict[str, bytes]]:
    payloads = {
        "detector/model.pt": b"detector",
        "captioner/model.safetensors": b"captioner",
        "processor/config.json": b"processor",
    }
    files = tuple(
        PinnedModelFile(
            group=group,
            repository="microsoft/fixture",
            revision=REVISION,
            remote_path=path,
            local_path=path,
            sha256=_sha(data),
            size=len(data),
            license="MIT",
        )
        for group, (path, data) in zip(
            ("detector", "captioner", "processor"), payloads.items(), strict=True
        )
    )
    return (
        OmniParserModelManifest(
            schema_version="1.0",
            name="microsoft/OmniParser-v2.0",
            upstream_revision=REVISION,
            source_repository="https://github.com/microsoft/OmniParser",
            source_commit="2" * 40,
            files=files,
        ),
        payloads,
    )


def test_prepare_cache_uses_pinned_urls_and_verifies_every_byte(tmp_path: Path) -> None:
    manifest, payloads = _manifest()
    urls: list[str] = []

    def download(url: str, output: Path, expected_size: int) -> None:
        urls.append(url)
        remote_path = url.rsplit(f"/resolve/{REVISION}/", 1)[1]
        data = payloads[remote_path]
        assert len(data) == expected_size
        output.write_bytes(data)

    files = prepare_model_cache(tmp_path, manifest, downloader=download)
    assert files == verify_model_cache(tmp_path, manifest)
    assert len(files) == 3
    assert all(f"/resolve/{REVISION}/" in url for url in urls)
    assert model_manifest_digest(manifest).startswith("sha256:")

    files[0].write_bytes(b"tampered")
    with pytest.raises(OmniParserCacheError, match="mismatch"):
        verify_model_cache(tmp_path, manifest)


def test_cache_rejects_symlinked_parent(tmp_path: Path) -> None:
    manifest, payloads = _manifest()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "detector").symlink_to(outside, target_is_directory=True)
    for path, data in payloads.items():
        if not path.startswith("detector/"):
            output = tmp_path / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
    with pytest.raises(OmniParserCacheError, match="symlink"):
        verify_model_cache(tmp_path, manifest)


class _Engine:
    def infer(self, screenshot: bytes) -> Sequence[Mapping[str, object]]:
        assert screenshot == b"png"
        return [
            {
                "id": "offer",
                "bounds": [10, 20, 110, 80],
                "role": "button",
                "label": "عرض بيتزا",
                "confidence": 0.98,
            }
        ]


@pytest.mark.asyncio
async def test_runner_is_lazy_and_adapter_preserves_pinned_identity(tmp_path: Path) -> None:
    manifest, payloads = _manifest()
    for path, data in payloads.items():
        output = tmp_path / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    constructions = 0

    def factory(root: Path, supplied: OmniParserModelManifest, device: str) -> _Engine:
        nonlocal constructions
        constructions += 1
        assert root == tmp_path
        assert supplied == manifest
        assert device == "cpu"
        return _Engine()

    runner = OmniParserV2Runner(
        cache_root=tmp_path,
        manifest=manifest,
        device="cpu",
        engine_factory=factory,
    )
    assert constructions == 0
    assert runner(b"png")[0]["label"] == "عرض بيتزا"
    assert runner(b"png")[0]["label"] == "عرض بيتزا"
    assert constructions == 1

    adapter = build_omniparser_v2_adapter(
        cache_root=tmp_path,
        manifest_path=manifest_path,
        device="cpu",
        engine_factory=factory,
    )
    candidates = await adapter.detect(b"png", width=200, height=100)
    assert candidates[0].label == "عرض بيتزا"
    assert candidates[0].source == "vision"
    assert adapter.identity.model_digest == model_manifest_digest(manifest)
