# Phase 1 implementation status

Phase 1 implementation finished on 2026-09-13. The contract, host runtime, and
both reference applications are implemented and locally accepted on the API 37
Pixel VM through the real UIAutomator2 backend. A SHA-pinned GitHub Actions gate
repeats the host checks and both install/fault/smoke paths on an API 35 emulator.

## Implemented

- Thirteen strict Pydantic v1 contract models with unknown-field rejection.
- Thirteen deterministic, checked-in JSON Schemas under `schemas/v1/`.
- Compatibility fixtures and round-trip/schema drift tests.
- Bounded selector vocabulary, semantic reference validation, and cycle detection.
- Skill state/reference invariants including same-state gates and uncertain routes.
- Async `DeviceBackend` protocol and serialized UIAutomator2 adapter with deadlines,
  one bounded reversible recovery, IME restoration, and fail-closed irreversible
  dispatch.
- SQLite device leases with heartbeat, fencing generation, stale takeover, and
  stale-owner rejection.
- Durable device-state journal that restores an abandoned IME baseline under the
  next fencing generation before device use.
- Atomic SHA-256 content-addressed artifact storage with integrity verification.
- Machine-readable two-app reference-suite and fault-control contract.
- Installable Matjar APK combining View, Compose, embedded WebView, deterministic
  checkout/order reconciliation, and all declared fault toggles.
- Installable Flutter 3.47.4 app with semantics-on, semantics-off, and image-only
  Arabic surfaces plus all three declared fault toggles.
- Live UIAutomator2 evidence with Arabic accessibility text, hierarchy and
  screenshot artifacts, plus reversible action timing.
- Reproducible host and emulator CI gates with every external action pinned to an
  immutable commit SHA.

Latest local acceptance: 380 Python tests passed with 88.66% coverage; Ruff and
mypy passed; two Flutter widget tests passed; the combined reference-app script
completed against `emulator-5554`; and the CI workflow passed actionlint 1.7.12.
The Flutter app also rebuilt successfully from a clean source-only copy without
ignored/generated wrapper files.

## Exit criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| Process restart cannot strand a lease | passed in integration tests | fencing generation and stale takeover tests |
| Backend timeouts are bounded | passed in integration tests | blocking fake call returns typed timeout |
| Input method restored after normal/abnormal exit | passed in integration tests | durable baseline journal and newer-lease recovery test |
| Contract fixtures round-trip | passed | v1 fixture bundle and schema drift test |
| Matjar builds, installs, resets, and exposes faults | passed locally | Gradle build, 13 broadcast faults, cold launch and live smoke report |
| Flutter sparse app builds, installs, resets, and exposes faults | passed locally | pinned Flutter build, 3 broadcast faults, Arabic hierarchy and live smoke report |
| Reference suite runs in hosted CI | configured, awaiting first remote run | `.github/workflows/phase2.yml`; repository has no remote yet |

Phase 1 is **implementation-complete and locally accepted**. The only operational
acceptance item that cannot be completed in this local repository is the first
green hosted-CI run; it requires pushing the repository to a GitHub remote. Phase 2
may proceed locally, but a release tag must remain blocked until that run is green.
