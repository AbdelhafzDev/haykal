# Phase 2 reports

Generated reports and artifacts are ignored. Capture two live deterministic
scenes after launching either reference app:

```bash
uv run haykal-m2 scene-smoke --serial emulator-5554 \
  --artifact-root reports/m2/artifacts \
  --output reports/m2/scene-smoke.json
```

The command reports quality for the second scene and adjacent-frame identity
matches. To build/install both reference apps and assert the live Phase 2 gate:

```bash
ANDROID_SDK_ROOT=/path/to/android-sdk \
ANDROID_SERIAL=emulator-5554 \
FLUTTER_BIN=/path/to/flutter/bin/flutter \
./scripts/phase2-reference-check.sh
```
