# ADR 0001: Milestone 0 baseline

- Status: in validation
- Date: 2026-09-13

## Context

The implementation begins on macOS with Python 3.13, `uv`, Java, and Docker
available. Android platform-tools and an attached Android VM are not currently on
`PATH`, so device-dependent evidence cannot yet be collected.

The pinned Python UIAutomator2 client must be treated as unsafe for irreversible
actions until its transparent restart/retry path is bypassed and verified at the
wire/device boundary.

Update: the SDK was later discovered at the standard macOS Android SDK location,
outside `PATH`. The existing API 37 Pixel VM now passes the live device smoke. The
original observation is retained here because it motivated portable tool discovery.

## Initial decisions

- Python package target: Python 3.11 or newer; exact dependencies are recorded in
  `uv.lock`.
- M0 checks emit structured JSON and distinguish `passed`, `blocked`,
  `risk_confirmed`, and `review_required`.
- The normalizer has separate search and material profiles from its first commit.
- The irreversible-action spike uses a durable SQLite ledger and a transport that
  promises one low-level call. A timeout becomes `outcome_unknown`; the action ID
  is never dispatched again.
- Live-device success is not claimed until ADB and a reproducible VM are present.

## Evidence required to accept this ADR

1. `reports/m0/doctor.json` from the reference host and VM.
2. A captured wire/device test showing one input event under injected timeout and
   UIAutomator2 service restart.
3. Screenshot and Unicode input matrices on the selected Android API levels.
4. OCR/vision benchmark and license inventory.
5. Three design-partner interview records.
