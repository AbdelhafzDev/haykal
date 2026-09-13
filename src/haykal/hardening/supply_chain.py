"""Offline SBOM and dependency-license evidence from the locked environment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _metadata(distribution: importlib.metadata.Distribution, key: str) -> str | None:
    metadata = cast(Mapping[str, str], distribution.metadata)
    value = metadata.get(key)
    return value.strip() if value and value.strip() else None


def _license(distribution: importlib.metadata.Distribution) -> str:
    expression = _metadata(distribution, "License-Expression") or _metadata(distribution, "License")
    if expression:
        return expression
    classifiers = distribution.metadata.get_all("Classifier") or []
    matches = [item.rsplit(" :: ", 1)[-1] for item in classifiers if "License ::" in item]
    return " OR ".join(matches) if matches else "UNKNOWN"


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def build_sbom(project_root: str | Path) -> dict[str, object]:
    root = Path(project_root)
    distributions = list(importlib.metadata.distributions())
    by_name = {
        _normalized(_metadata(distribution, "Name") or distribution.name): distribution
        for distribution in distributions
    }
    included: set[str] = set()
    pending = ["haykal-runtime"]
    while pending:
        normalized = _normalized(pending.pop())
        if normalized in included or normalized not in by_name:
            continue
        included.add(normalized)
        for requirement in by_name[normalized].requires or []:
            if "extra ==" in requirement:
                continue
            match = re.match(r"[A-Za-z0-9_.-]+", requirement)
            if match is not None:
                pending.append(match.group(0))
    components: list[dict[str, object]] = []
    for normalized in included:
        distribution = by_name[normalized]
        name = _metadata(distribution, "Name") or distribution.name
        version = distribution.version
        license_name = _license(distribution)
        components.append(
            {
                "type": "library",
                "bom-ref": f"pkg:pypi/{quote(_normalized(name))}@{quote(version)}",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{quote(_normalized(name))}@{quote(version)}",
                "licenses": [{"license": {"name": license_name}}],
            }
        )
    components.sort(key=lambda item: (str(item["name"]).casefold(), str(item["version"])))
    lock_digest = _digest(root / "uv.lock")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "type": "application",
                "name": "haykal-runtime",
                "version": _installed_version(),
            },
            "properties": [{"name": "haykal:uv-lock:sha256", "value": lock_digest or "missing"}],
        },
        "components": components,
    }


def _installed_version() -> str:
    try:
        return importlib.metadata.version("haykal-runtime")
    except importlib.metadata.PackageNotFoundError:
        return "development"


def build_license_report(sbom: dict[str, object]) -> str:
    components = sbom.get("components", [])
    lines = [
        "# Dependency license report",
        "",
        "Generated from installed package metadata. This is an audit input, not legal advice.",
        "",
        "| Package | Version | Declared license |",
        "| --- | --- | --- |",
    ]
    unknown = 0
    if isinstance(components, list):
        for component in components:
            if not isinstance(component, dict):
                continue
            licenses = component.get("licenses")
            license_name = "UNKNOWN"
            if isinstance(licenses, list) and licenses and isinstance(licenses[0], dict):
                license_value = licenses[0].get("license")
                if isinstance(license_value, dict):
                    license_name = str(license_value.get("name", "UNKNOWN"))
            unknown += license_name == "UNKNOWN"
            escaped_license = license_name.replace("|", "\\|")
            lines.append(
                f"| {component.get('name', '')} | {component.get('version', '')} | "
                f"{escaped_license} |"
            )
    lines.extend(["", f"Unknown license declarations: **{unknown}**.", ""])
    return "\n".join(lines)
