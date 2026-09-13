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
uv run haykal-m2 scene-smoke \
  --serial "$serial" \
  --artifact-root reports/m2/artifacts \
  --output reports/m2/matjar-scene.json >/dev/null

uv run python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("reports/m2/matjar-scene.json").read_text())
scene = report["scene"]
identity = report["identity_detail"]
quality = report["quality_detail"]

assert report["status"] == "passed"
assert report["observation"]["foreground"]["package"] == "dev.haykal.refapps.matjar"
assert report["warnings"] == []
assert quality["actionable_count"] >= 2
assert quality["labelled_actionable_ratio"] == 1.0
assert identity["matched"] == len(scene["elements"])
assert identity["new"] == 0
assert identity["ambiguous"] == 0
assert identity["expired"] == 0
print(
    "Phase 2 live scene passed: "
    f"{len(scene['elements'])} elements, "
    f"{identity['matched']} stable IDs, "
    f"quality={scene['quality']['score']:.6f}"
)
PY
