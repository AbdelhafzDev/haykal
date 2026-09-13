# Phase 5 evidence

Generated JSON, static trace exports, archives, and soak logs are ignored because
they may contain host or screen-derived data. Recreate host evidence with
`./scripts/phase5-check.sh`, live reference evidence with
`./scripts/phase5-reference-check.sh`, and the full device soak with
`./scripts/phase5-device-soak.sh`.

Only a run lasting at least 28,800 seconds is eligible for the eight-hour gate.
A short smoke run proves the harness works but is not release evidence.

Committed evidence documents:

- `sbom.cdx.json`: CycloneDX 1.6 runtime dependency closure.
- `license-report.md`: declared licenses from installed package metadata.
- `security-report.md`: targeted security regression result.
- `comparative-benchmark-status.md`: explicit external blocker, with no synthetic
  scores.
