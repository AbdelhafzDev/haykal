# M0 reports

Generated machine reports are intentionally ignored by Git. Reproduce the local
host report with:

```bash
uv run haykal-m0 doctor --output reports/m0/doctor.json
uv run haykal-m0 inventory --project-root . --output reports/m0/dependencies.json
uv run haykal-m0 device-smoke --serial emulator-5554 \
  --output reports/m0/device-smoke.json
ANDROID_SDK_ROOT=/path/to/android-sdk ./scripts/matjar-check.sh
ANDROID_SDK_ROOT=/path/to/android-sdk \
  FLUTTER_BIN=/path/to/flutter/bin/flutter ./scripts/flutter-sparse-check.sh
```

Reports used for an ADR or release decision must be copied into a dated evidence
bundle together with the dependency lock digest, VM image digest, command line,
and operator notes. A `blocked` check is a truthful result, not a pass.
