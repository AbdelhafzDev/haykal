#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"

matjar_dir="$project_dir/refapps/matjar"
adb="$ANDROID_SDK_ROOT/platform-tools/adb"
serial="${ANDROID_SERIAL:-emulator-5554}"
faults=(
  promo_modal price_change payment_decline submit_timeout
  submit_created_no_confirm option_unavailable minimum_order
  address_out_of_area otp_challenge sparse_cards arabic_indic_digits
  slow_settle duplicate_labels
)

cd "$matjar_dir"
if [[ "${HAYKAL_REFAPPS_PREBUILT:-0}" != "1" ]]; then
  ./gradlew --no-daemon :app:assembleDebug
fi
test -s app/build/outputs/apk/debug/app-debug.apk
"$adb" -s "$serial" install -r app/build/outputs/apk/debug/app-debug.apk
"$adb" -s "$serial" shell am start -W \
  -n dev.haykal.refapps.matjar/.MainActivity >/dev/null
"$adb" -s "$serial" shell am broadcast \
  -a dev.haykal.refapp.RESET -p dev.haykal.refapps.matjar
for fault in "${faults[@]}"; do
  "$adb" -s "$serial" shell am broadcast \
    -a dev.haykal.refapp.SET_FAULT \
    -p dev.haykal.refapps.matjar \
    --es name "$fault" \
    --ez enabled true >/dev/null
done
fault_count=$("$adb" -s "$serial" shell run-as dev.haykal.refapps.matjar \
  cat shared_prefs/matjar.xml | rg -c 'name="fault\.')
if [[ "$fault_count" -ne "${#faults[@]}" ]]; then
  echo "Expected ${#faults[@]} Matjar fault switches, found $fault_count" >&2
  exit 1
fi
"$adb" -s "$serial" shell am broadcast \
  -a dev.haykal.refapp.RESET -p dev.haykal.refapps.matjar
"$adb" -s "$serial" shell am force-stop dev.haykal.refapps.matjar
"$adb" -s "$serial" shell am start -W \
  -n dev.haykal.refapps.matjar/.MainActivity
cd "$project_dir"
uv run haykal-m0 device-smoke \
  --serial "$serial" \
  --artifact-root reports/m0/artifacts \
  --output reports/m0/matjar-smoke.json
