# ADR 0003: deterministic reference apps and CI toolchains

- Status: accepted for implementation
- Date: 2026-09-13

## Decision

The Phase 1 reference suite contains two offline, synthetic Android packages:

- Matjar combines Android View, Jetpack Compose, embedded WebView, and a fake
  checkout/order ledger.
- Flutter Sparse isolates semantics-on, semantics-off, and image-painted Arabic
  surfaces under Flutter 3.47.4.

Both apps expose an allowlisted broadcast fault contract and a reset action. A
fresh install is launched once before broadcasts because Android marks new
packages stopped and will otherwise suppress receiver delivery. Resets and fault
writes use synchronous preference commits so CI observes a deterministic state.

Flutter 3.47.4 is pinned in `pubspec.yaml` and `toolchains/flutter-sdk.json`; the
official macOS ARM64 archive checksum is committed. GitHub Actions dependencies
are pinned to immutable commit SHAs. The hosted reference gate uses API 35 x86_64,
while the local acceptance run uses the available API 37 ARM64 Pixel VM.

## Consequences

- Production applications, accounts, credentials, networks, and payment systems
  are never required by the correctness suite.
- Fault persistence and observable behavior are both tested before later scene
  and resolver benchmarks consume these apps.
- A local pass does not prove the hosted runner path. The first remote green run
  remains an operational release gate once a GitHub remote exists.
