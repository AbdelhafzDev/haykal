#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$project_dir"

uv sync --extra dev --locked
uv run haykal-schema --output schemas/v1
uv run ruff format --check src tests examples
uv run ruff check .
uv run mypy
uv run pytest --cov=haykal --cov-report=term-missing
uv run haykal lint skills/dev.haykal.refapps.matjar/offers.yaml >/dev/null
uv run haykal lint skills/dev.haykal.refapps.matjar/prepare-order.yaml >/dev/null
uv build

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
chmod 700 "$temporary"
uv run haykal --state-dir "$temporary/state" hardening-run \
  --duration-s 0.25 --workers 2 --chaos-every 7 \
  --output "$temporary/hardening.json" --output-state "$temporary/state" >/dev/null
uv run haykal fault-matrix --output-state "$temporary/fault-state" \
  --output "$temporary/fault-matrix.json" >/dev/null
uv run haykal --state-dir "$temporary/state" diagnostics --storage-only \
  >"$temporary/diagnostics.json"
uv run haykal sbom --project-root "$project_dir" \
  --output "$temporary/sbom.cdx.json" --licenses "$temporary/licenses.md" >/dev/null
uv run python - "$temporary" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
hardening = json.loads((root / "hardening.json").read_text())
diagnostics = json.loads((root / "diagnostics.json").read_text())
sbom = json.loads((root / "sbom.cdx.json").read_text())
faults = json.loads((root / "fault-matrix.json").read_text())
assert hardening["operations"] > 0
assert hardening["unexpected_failures"] == 0
assert diagnostics["status"] == "ready"
assert faults["passed"] is True and len(faults["observations"]) == 9
assert sbom["bomFormat"] == "CycloneDX" and sbom["specVersion"] == "1.6"
PY

uv venv "$temporary/venv" --python 3.13 >/dev/null
wheel="$(find dist -maxdepth 1 -name '*.whl' -print | sort | tail -n 1)"
uv pip install --python "$temporary/venv/bin/python" "$wheel" >/dev/null
"$temporary/venv/bin/haykal" --state-dir "$temporary/clean-state" diagnostics \
  --storage-only >/dev/null
"$temporary/venv/bin/haykal-evaluate-fallback" --help >/dev/null
