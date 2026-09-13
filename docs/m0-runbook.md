# Milestone 0 runbook

## Current checkpoint

The repository contains the executable M0 foundation:

- Locked Python environment and static/test tooling.
- Versioned Arabic search/material normalizers.
- Number, money, and duration parsers.
- A labelled normalization matrix with 315 distinct raw strings plus parser cases.
- A durable at-most-once dispatch spike and restart/timeout tests.
- A host/dependency doctor that audits the pinned UIAutomator2 retry behavior.
- A dependency inventory containing exact installed versions, declared license
  metadata, and the `uv.lock` SHA-256 digest.

| M0 workstream | Current state | Evidence |
| --- | --- | --- |
| Python environment and dependency pinning | passing | `uv.lock`, dependency inventory |
| Arabic normalization and core parsers | passing | 380-test suite; 315 normalization strings plus parser fixtures |
| UIAutomator2 source retry audit | risk confirmed | `doctor.json`; pinned version 3.7.0 transparently retries |
| At-most-once dispatch spike | software proof passing | timeout/restart tests; live wire/device proof pending |
| Android VM and ADB lifecycle | started | API 37 Pixel VM discovered; live backend smoke passed |
| Screenshot and Arabic input matrices | started | hierarchy/screenshot baseline captured; full matrix remains |
| OCR/vision selection and license review | pending | requires labelled screenshot corpus |
| Design-partner validation | pending | requires founder interviews |

## Run the software-only checks

```bash
uv sync --all-extras
uv lock
./scripts/m0-check.sh
```

The script writes `reports/m0/doctor.json`. It succeeds even when hardware checks
are `blocked`; downstream evidence gates inspect the JSON status rather than the
shell exit code.

## Unblock live-device validation

Install Android platform-tools, provision the reference VM, enable developer/ADB
access, and verify exactly one authorized device:

```bash
adb devices
uv run haykal-m0 doctor --output reports/m0/doctor.json
```

Do not run Maestro, Appium, or Espresso against the same device during a Haykal
lease. Use only synthetic accounts and Matjar fixtures; never use real payment or
personal data in M0 evidence.

## Remaining M0 experiments

1. UIAutomator2 connect/hierarchy/action/screenshot/process-death/reconnect matrix.
2. Wire-level no-replay test for the irreversible dispatch transport.
3. UIAutomator2 versus lossless ADB screenshot benchmark on Arabic screens.
4. Arabic input matrix for View, Compose, WebView, Flutter, multiline, emoji, and
   secure-field rejection.
5. Two-engine OCR benchmark on 200 labelled screenshots.
6. OmniParser-compatible sparse-screen adapter and license review.
7. Dependency/model SBOM with checksums.
8. Three design-partner interviews and first authorized workflow ADR.
