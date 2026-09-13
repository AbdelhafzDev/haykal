#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"

flutter_bin="${FLUTTER_BIN:-$project_dir/.tools/flutter/bin/flutter}"
adb="$ANDROID_SDK_ROOT/platform-tools/adb"
serial="${ANDROID_SERIAL:-emulator-5554}"
app_dir="$project_dir/refapps/flutter-sparse"
package="dev.haykal.refapps.flutter_sparse"
faults=(arabic_indic_digits slow_settle duplicate_labels)

cd "$app_dir"
"$flutter_bin" pub get
"$flutter_bin" analyze
"$flutter_bin" test
ANDROID_HOME="$ANDROID_SDK_ROOT" "$flutter_bin" build apk --debug
"$adb" -s "$serial" install -r build/app/outputs/flutter-apk/app-debug.apk
"$adb" -s "$serial" shell am start -W -n "$package/.MainActivity" >/dev/null
"$adb" -s "$serial" shell am broadcast \
  -a dev.haykal.refapp.RESET -p "$package"
for fault in "${faults[@]}"; do
  "$adb" -s "$serial" shell am broadcast \
    -a dev.haykal.refapp.SET_FAULT \
    -p "$package" \
    --es name "$fault" \
    --ez enabled true >/dev/null
done
fault_count=$("$adb" -s "$serial" shell run-as "$package" \
  cat shared_prefs/flutter_sparse.xml | rg -c 'name="fault\.')
if [[ "$fault_count" -ne "${#faults[@]}" ]]; then
  echo "Expected ${#faults[@]} Flutter fault switches, found $fault_count" >&2
  exit 1
fi
"$adb" -s "$serial" shell am broadcast \
  -a dev.haykal.refapp.RESET -p "$package"
"$adb" -s "$serial" shell am force-stop "$package"
"$adb" -s "$serial" shell am start -W -n "$package/.MainActivity"

cd "$project_dir"
uv run haykal-m0 device-smoke \
  --serial "$serial" \
  --artifact-root reports/m0/artifacts \
  --output reports/m0/flutter-sparse-smoke.json

hierarchy_digest=$(jq -r '.hierarchy.artifact | sub("^sha256:"; "")' \
  reports/m0/flutter-sparse-smoke.json)
hierarchy_path="reports/m0/artifacts/sha256/${hierarchy_digest:0:2}/${hierarchy_digest:2}"
rg -q 'مختبر Flutter الدلالي' "$hierarchy_path"
rg -q 'عرض بيتزا مارغريتا' "$hierarchy_path"
