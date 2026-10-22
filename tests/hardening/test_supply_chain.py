from __future__ import annotations

import json
from pathlib import Path

from haykal.hardening import build_license_report, build_sbom


def test_sbom_is_cyclonedx_and_license_report_is_reproducible_shape(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_bytes(b"locked")
    sbom = build_sbom(tmp_path)

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert sbom["components"]
    report = build_license_report(sbom)
    assert "# Dependency license report" in report
    assert "haykal-runtime" in report


def test_sbom_includes_pinned_model_files_without_installing_ml_extra(tmp_path: Path) -> None:
    model_root = tmp_path / "config" / "models"
    model_root.mkdir(parents=True)
    (model_root / "fixture.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "group": "detector",
                        "repository": "microsoft/OmniParser-v2.0",
                        "revision": "1" * 40,
                        "local_path": "icon_detect_v3/model.pt",
                        "sha256": "sha256:" + "a" * 64,
                        "license": "MIT",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sbom = build_sbom(tmp_path)
    model = next(item for item in sbom["components"] if item["type"] == "machine-learning-model")
    assert model["hashes"] == [{"alg": "SHA-256", "content": "a" * 64}]
    assert model["licenses"] == [{"license": {"name": "MIT"}}]
