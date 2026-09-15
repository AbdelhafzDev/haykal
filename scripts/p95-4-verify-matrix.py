#!/usr/bin/env python3
"""Verify that API 34 and 35 evidence passed against one identical wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifests = []
    for directory in args.evidence:
        path = directory / "acceptance-manifest.json"
        payload = json.loads(path.read_text())
        payload["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifests.append(payload)
    by_api = {int(item["device"]["api_level"]): item for item in manifests}
    if set(by_api) != {34, 35}:
        raise SystemExit(f"expected API 34 and 35 evidence, got {sorted(by_api)}")
    digests = {item["release"]["wheel_sha256"] for item in manifests}
    if len(digests) != 1 or not all(item["status"] == "passed" for item in manifests):
        raise SystemExit("matrix did not pass with one identical wheel")
    result = {
        "schema_version": "1.0",
        "status": "passed",
        "api_levels": [34, 35],
        "wheel_sha256": next(iter(digests)),
        "runs": [
            {
                "api_level": api,
                "manifest_sha256": by_api[api]["manifest_sha256"],
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
