"""Offline SBOM and dependency-license evidence from the locked environment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
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
    components.extend(_model_components(root))
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


def _model_components(root: Path) -> list[dict[str, object]]:
    """Include pinned model/cache inputs even when the optional ML extra is absent."""

    components: list[dict[str, object]] = []
    for manifest_path in sorted((root / "config" / "models").glob("*.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(files, list):
            continue
        for item in files:
            if not isinstance(item, dict):
                continue
            required = ("repository", "revision", "local_path", "sha256", "license")
            if not all(isinstance(item.get(key), str) and item[key] for key in required):
                continue
            raw_digest = str(item["sha256"])
            algorithm, separator, content = raw_digest.partition(":")
            if (
                separator != ":"
                or algorithm != "sha256"
                or not re.fullmatch(r"[0-9a-f]{64}", content)
            ):
                continue
            repository = str(item["repository"])
            revision = str(item["revision"])
            local_path = str(item["local_path"])
            components.append(
                {
                    "type": "machine-learning-model",
                    "bom-ref": (
                        f"pkg:huggingface/{quote(repository)}@{quote(revision)}#{quote(local_path)}"
                    ),
                    "name": f"{repository}/{local_path}",
                    "version": revision,
                    "licenses": [{"license": {"name": str(item["license"])}}],
                    "hashes": [{"alg": "SHA-256", "content": content}],
                    "properties": [
                        {
                            "name": "haykal:model-manifest",
                            "value": manifest_path.relative_to(root).as_posix(),
                        },
                        {"name": "haykal:model-role", "value": str(item.get("group", "unknown"))},
                    ],
                }
            )
    return components


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
