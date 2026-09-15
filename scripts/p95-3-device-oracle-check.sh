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

cd "$project_dir"
mkdir -p "$output"
ANDROID_HOME="$ANDROID_SDK_ROOT" \
  ./refapps/matjar/gradlew -p refapps/matjar assembleDebug >/dev/null
apk="refapps/matjar/app/build/outputs/apk/debug/app-debug.apk"
"$adb" -s "$serial" install -r "$apk" >/dev/null
"$adb" -s "$serial" shell getprop >"$output/device.properties"
shasum -a 256 "$apk" >"$output/apk.sha256"

uv run python - "$serial" "$adb" "$output/oracle-transition.json" <<'PY'
import json
import sys
import time
from pathlib import Path

import uiautomator2 as u2

from haykal.benchmarks.matjar_oracle import MatjarAdbOracle

serial, adb, output = sys.argv[1:]
oracle = MatjarAdbOracle(serial, adb)
oracle.reset()
before = oracle.snapshot()
device = u2.connect(serial)
device(resourceId="search_button").click()
time.sleep(0.2)
after = oracle.snapshot()
assert before["state"]["screen"] == "home"
assert after["state"]["screen"] == "search"
for resource in (
    "show_results",
    "result_1",
    "add_to_basket",
    "checkout_button",
    "place_order",
):
    device(resourceId=resource).click()
    time.sleep(0.2)
after_order = oracle.snapshot()
assert after_order["state"]["screen"] == "confirmation"
assert after_order["state"]["submit_count"] == 1
assert after_order["state"]["order_created"] is True
assert after_order["event_log"] == ["submit_order"]
Path(output).write_text(
    json.dumps(
        {"before": before, "after_navigation": after, "after_order": after_order},
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("P95.3 independent Matjar ADB oracle transition passed")
PY
