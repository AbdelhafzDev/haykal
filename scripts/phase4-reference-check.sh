#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"

serial="${ANDROID_SERIAL:-emulator-5554}"
adb="$ANDROID_SDK_ROOT/platform-tools/adb"
report_dir="$project_dir/reports/m4"

if [[ "${HAYKAL_REFAPPS_PREBUILT:-0}" != "1" ]]; then
  ANDROID_HOME="$ANDROID_SDK_ROOT" \
    "$project_dir/refapps/matjar/gradlew" --no-daemon \
    -p "$project_dir/refapps/matjar" test assembleDebug
fi
test -s "$project_dir/refapps/matjar/app/build/outputs/apk/debug/app-debug.apk"
"$adb" -s "$serial" install -r \
  "$project_dir/refapps/matjar/app/build/outputs/apk/debug/app-debug.apk" >/dev/null

run_skill() {
  local name="$1"
  local inputs="$2"
  local output="$3"
  local fault="$4"
  local approval="$5"
  "$adb" -s "$serial" shell am broadcast \
    -a dev.haykal.refapp.RESET -p dev.haykal.refapps.matjar >/dev/null
  if [[ -n "$fault" ]]; then
    "$adb" -s "$serial" shell am broadcast \
      -a dev.haykal.refapp.SET_FAULT -p dev.haykal.refapps.matjar \
      --es name "$fault" --ez enabled true >/dev/null
  fi
  "$adb" -s "$serial" shell am force-stop dev.haykal.refapps.matjar
  "$adb" -s "$serial" shell am start -W \
    -n dev.haykal.refapps.matjar/.MainActivity >/dev/null
  cd "$project_dir"
  if [[ -n "$approval" ]]; then
    uv run haykal-m4 \
      --serial "$serial" \
      --skill "skills/dev.haykal.refapps.matjar/$name.yaml" \
      --state-dir "$report_dir/state" \
      --inputs "$inputs" \
      --output "$report_dir/$output.json" \
      "$approval" >/dev/null
  else
    uv run haykal-m4 \
      --serial "$serial" \
      --skill "skills/dev.haykal.refapps.matjar/$name.yaml" \
      --state-dir "$report_dir/state" \
      --inputs "$inputs" \
      --output "$report_dir/$output.json" >/dev/null
  fi
}

mkdir -p "$report_dir/state"
run_skill offers '{}' offers '' ''
run_skill prepare-order '{"maximum_total":{"amount":60,"currency":"SAR"}}' \
  prepare-order '' ''
run_skill prepare-order '{"maximum_total":{"amount":60,"currency":"SAR"}}' \
  prepare-order-reconciled submit_timeout --approve-gate

cd "$project_dir"
uv run python - <<'PY'
import json
from pathlib import Path

offers = json.loads(Path("reports/m4/offers.json").read_text())
order = json.loads(Path("reports/m4/prepare-order.json").read_text())
reconciled = json.loads(Path("reports/m4/prepare-order-reconciled.json").read_text())
assert offers["status"] == "completed", offers
assert len(offers["outputs"]["offers"]) == 10
assert offers["events"][-1]["event_type"] == "run.completed"
assert order["status"] == "approval_required"
assert order["state"] == "review"
assert order["pending"]["material"]["total"]["currency"] == "SAR"
assert order["pending"]["material"]["address"]["masked"].startswith("••••")
assert order["pending"]["material"]["payment"]["masked"].startswith("••••")
assert not any(
    event["event_type"] == "action.dispatched"
    and event["payload"].get("action_id", "").endswith(":review")
    for event in order["events"]
)
review_dispatches = [
    event
    for event in reconciled["events"]
    if event["event_type"] == "action.dispatched"
    and event["payload"].get("action_id", "").endswith(":review")
]
assert reconciled["status"] == "completed_reconciled"
assert len(review_dispatches) == 1
assert review_dispatches[0]["payload"]["receipt"]["repeated_request"] is False
print(
    "Phase 4 live skills passed: 10 offers, approval stop, and one-shot "
    "submit reconciled through Orders"
)
PY
