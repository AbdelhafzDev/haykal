#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to the Android SDK directory}"
flutter_bin="${FLUTTER_BIN:-$project_dir/.tools/flutter/bin/flutter}"

ANDROID_HOME="$ANDROID_SDK_ROOT" \
  "$project_dir/refapps/matjar/gradlew" --no-daemon \
  -p "$project_dir/refapps/matjar" test assembleDebug

cd "$project_dir/refapps/flutter-sparse"
"$flutter_bin" pub get
"$flutter_bin" analyze
"$flutter_bin" test
ANDROID_HOME="$ANDROID_SDK_ROOT" "$flutter_bin" build apk --debug

echo "Reference APKs built before emulator startup"
