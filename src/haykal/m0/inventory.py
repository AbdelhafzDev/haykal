"""Dependency inventory for Milestone 0 evidence bundles."""

from __future__ import annotations

import hashlib
import importlib.metadata
import sys
from datetime import UTC, datetime
from pathlib import Path


def _metadata_value(metadata: importlib.metadata.PackageMetadata, key: str) -> str | None:
    if key not in metadata:
        return None
    return metadata[key] or None


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def build_inventory(project_root: Path) -> dict[str, object]:
    packages: list[dict[str, object]] = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        license_expression = _metadata_value(metadata, "License-Expression") or _metadata_value(
            metadata, "License"
        )
        packages.append(
            {
                "name": _metadata_value(metadata, "Name") or distribution.name,
                "version": distribution.version,
                "license": license_expression or "UNKNOWN",
                "homepage": _metadata_value(metadata, "Project-URL")
                or _metadata_value(metadata, "Home-page"),
            }
        )
    packages.sort(key=lambda item: str(item["name"]).casefold())
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "uv_lock": {
            "path": "uv.lock",
            "digest": _sha256(project_root / "uv.lock"),
        },
        "packages": packages,
        "unknown_license_count": sum(package["license"] == "UNKNOWN" for package in packages),
        "models": [],
        "notes": [
            "Package metadata is an audit input, not legal advice.",
            "OCR and vision models are added only after M0 selection with separate "
            "code/weight licenses.",
        ],
    }
