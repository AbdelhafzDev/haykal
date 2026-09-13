from __future__ import annotations

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
