#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
temporary="$(mktemp)"
trap 'rm -f -- "$temporary"' EXIT

cd "$project_dir"
uv run --extra dev detect-secrets scan --no-verify >"$temporary"

uv run python - "$temporary" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
results = report.get("results", {})
allowlisted_public_checksums = {
    ("toolchains/flutter-sdk.json", 6, "Hex High Entropy String"),
}
findings = [
    (filename, finding["line_number"], finding["type"])
    for filename, items in results.items()
    for finding in items
    if (filename, finding["line_number"], finding["type"])
    not in allowlisted_public_checksums
]
if findings:
    for filename, line, finding_type in findings:
        print(f"{filename}:{line}: {finding_type}", file=sys.stderr)
    raise SystemExit(f"secret scan failed with {len(findings)} potential finding(s)")
print("Secret scan passed: zero unallowlisted findings")
PY
