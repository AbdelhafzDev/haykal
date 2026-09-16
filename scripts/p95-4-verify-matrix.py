#!/usr/bin/env python3
"""Verify that API 34 and 35 evidence passed against one identical wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_evidence(directory: Path) -> str:
    checksum_path = directory / "evidence-sha256.txt"
    if not checksum_path.is_file():
        raise SystemExit(f"missing evidence checksum manifest: {checksum_path}")
    covered: set[str] = set()
    for line in checksum_path.read_text().splitlines():
        expected, separator, relative = line.partition("  ")
        candidate = Path(relative)
        if not separator or candidate.is_absolute() or ".." in candidate.parts:
            raise SystemExit(f"malformed evidence checksum line: {line!r}")
        path = directory / candidate
        if not path.is_file() or _digest(path) != expected:
            raise SystemExit(f"evidence digest mismatch: {candidate}")
        covered.add(candidate.as_posix())
    if "acceptance-manifest.json" not in covered:
        raise SystemExit("evidence checksum manifest does not cover acceptance-manifest.json")
    return _digest(checksum_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifests = []
    for directory in args.evidence:
        path = directory / "acceptance-manifest.json"
        payload = json.loads(path.read_text())
        payload["manifest_sha256"] = _digest(path)
        payload["evidence_sha256"] = _verify_evidence(directory)
        manifests.append(payload)
    by_api = {int(item["device"]["api_level"]): item for item in manifests}
    if len(manifests) != 2 or set(by_api) != {34, 35}:
        raise SystemExit(f"expected API 34 and 35 evidence, got {sorted(by_api)}")
    releases = [item["release"] for item in manifests]
    if releases[0] != releases[1]:
        raise SystemExit("matrix evidence does not reference one identical release bundle")
    if not all(
        item["status"] == "passed"
        and all(value == "passed" for value in item.get("checks", {}).values())
        for item in manifests
    ):
        raise SystemExit("matrix did not pass every acceptance check")
    wheel_digest = str(releases[0]["wheel_sha256"])
    result = {
        "schema_version": "1.0",
        "status": "passed",
        "api_levels": [34, 35],
        "release": releases[0],
        "wheel_sha256": wheel_digest,
        "runs": [
            {
                "api_level": api,
                "manifest_sha256": by_api[api]["manifest_sha256"],
                "evidence_sha256": by_api[api]["evidence_sha256"],
                "vm_identity": by_api[api]["device"]["vm_identity"],
            }
            for api in (34, 35)
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
