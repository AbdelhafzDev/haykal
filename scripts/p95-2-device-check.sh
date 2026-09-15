#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"
serial="${ANDROID_SERIAL:-emulator-5554}"
output="${1:?Pass an empty evidence output directory}"
adb="$ANDROID_SDK_ROOT/platform-tools/adb"

if [[ -e "$output" ]]; then
  echo "evidence output already exists: $output" >&2
  exit 2
fi
mkdir -p "$output"

cd "$project_dir"
uv run haykal fault-matrix \
  --output-state "$output/fault-state" \
  --output "$output/fault-matrix.json" \
  --device "$serial" --adb-path "$adb" >/dev/null

uv run haykal --state-dir "$output/readiness-cli" hardening-run \
  --duration-s 0.1 --workers 1 --chaos-every 7 \
  --output-state "$output/readiness-state" >/dev/null
uv run haykal --state-dir "$output/readiness-state" diagnostics \
  --device "$serial" --adb-path "$adb" >"$output/readiness-connected.json"

set +e
uv run haykal --state-dir "$output/readiness-state" diagnostics \
  --device "${serial}-absent" --adb-path "$adb" >"$output/readiness-absent.json"
absent_status=$?
set -e

uv run python - "$output" "$absent_status" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
faults = json.loads((root / "fault-matrix.json").read_text())
connected = json.loads((root / "readiness-connected.json").read_text())
absent = json.loads((root / "readiness-absent.json").read_text())
assert faults["passed"] is True and len(faults["observations"]) == 12
assert connected["status"] == "ready"
assert absent["status"] == "unhealthy" and int(sys.argv[2]) == 2
print("P95.2 device faults and readiness transitions passed")
PY
