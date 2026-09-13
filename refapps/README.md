# Reference applications

The reference suite has two installable targets:

- `matjar`: one deterministic application containing Android View, Compose,
  embedded WebView, and fake checkout surfaces.
- `flutter-sparse`: a small Flutter application whose semantics can be disabled
  to force OCR/vision fallback.

[`manifest.json`](manifest.json) is the machine-readable test contract. Faults
are controlled through broadcasts and all state is synthetic. Neither app may
contact a payment system or contain live credentials.

Both apps have been built, installed, reset, fault-checked, launched, and observed
on the API 37 reference VM. Flutter is pinned to 3.47.4; its macOS ARM64 archive
checksum is recorded in `toolchains/flutter-sdk.json`.

From the repository root, reproduce the individual gates with
`scripts/matjar-check.sh` and `scripts/flutter-sparse-check.sh`, or run both with
`scripts/reference-apps-check.sh`. The GitHub Actions gate runs the same scripts
on an API 35 x86_64 emulator.
