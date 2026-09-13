#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"

serial="${ANDROID_SERIAL:-emulator-5554}"
adb="$ANDROID_SDK_ROOT/platform-tools/adb"

"$project_dir/scripts/reference-apps-check.sh"
"$adb" -s "$serial" shell am force-stop dev.haykal.refapps.matjar
"$adb" -s "$serial" shell am start -W \
  -n dev.haykal.refapps.matjar/.MainActivity >/dev/null

cd "$project_dir"
uv run haykal-m3 action-smoke \
  --serial "$serial" \
  --state-dir reports/m3/state \
  --output reports/m3/action-smoke.json >/dev/null

uv run python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/m3/action-smoke.json").read_text())
assert report["status"] == "passed"
assert report["action"]["status"] == "verified"
assert report["action"]["device_receipt"]["dispatch_status"] == "dispatched"
assert report["action"]["pre_scene"] == report["pre_scene"]
assert report["action"]["post_scene"] == report["post_scene"]
events = [event["event_type"] for event in report["trace"]]
assert events == [
    "action.prepared",
    "target.resolved",
    "action.dispatched",
    "observation.created",
    "verification.completed",
    "transition.committed",
]
print("Phase 3 live action passed: resolved, dispatched, verified, and traced")
PY
