# Phase 5 runbook

## Host release gate

```bash
./scripts/phase5-check.sh
```

This verifies the lock, schemas, formatting, lint, strict typing, complete test
suite and coverage, both signed reference skill sources, package build, bounded
load/chaos smoke, diagnostics, CycloneDX shape, license report generation, and a
clean virtual-environment wheel installation.

## Diagnostics and health

```bash
haykal --state-dir /var/lib/haykal diagnostics
curl http://127.0.0.1:8421/healthz
curl -H "Authorization: Bearer $HAYKAL_API_TOKEN" \
  http://127.0.0.1:8421/v1/diagnostics
```

`/healthz` deliberately omits paths, timestamps, device identifiers, and failure
details. The authenticated endpoint returns database, state permission, disk, and
artifact-integrity details.

## Static trace report and retention

```bash
haykal --state-dir STATE trace-export TRACE_ID \
  --policy config/redaction.example.yaml --output REPORT_DIRECTORY
haykal --state-dir STATE retention --trace-days 7 --artifact-days 7
haykal --state-dir STATE retention --trace-days 7 --artifact-days 7 --apply
```

The report contains `index.html`, `trace.json`, and `manifest.json`; no SQLite
database is needed to inspect it. Images are private-by-default. Always preview
retention before applying it, and keep artifact retention at least as long as
trace retention.

## Supply chain

```bash
haykal sbom --project-root . --output reports/m5/sbom.cdx.json \
  --licenses reports/m5/license-report.md
```

This is offline evidence from the installed locked environment. Package metadata
is not legal advice. OCR and vision model code/weight licenses remain separate and
blocking until models are selected.

## Reference VM and recovery drill

With a clean emulator attached:

```bash
ANDROID_SDK_ROOT="$ANDROID_HOME" ANDROID_SERIAL=emulator-5554 \
  ./scripts/phase5-reference-check.sh
```

It reruns both Phase 4 lifecycles, exports a private static trace, snapshots live
SQLite state, restores it into an empty directory, and runs diagnostics.
The hosted workflow runs this on Android API 34 and 35.

## Load, chaos, and soak

A bounded component run:

```bash
haykal hardening-run --duration-s 60 --workers 4 --chaos-every 37 \
  --output reports/m5/storage-hardening.json
```

The release device soak is intentionally separate:

```bash
HAYKAL_SOAK_DURATION_S=28800 ./scripts/phase5-device-soak.sh
```

Reducing the duration is useful for debugging but makes
`eight_hour_gate_eligible` false. An interrupted/failed cycle exits immediately;
it is not converted into a passing partial report.

## Comparative benchmark

Create a manifest from `benchmarks/systems.example.yaml`, embed the twenty tasks,
replace placeholders with exact digests and executable adapter paths, then run:

```bash
haykal benchmark --manifest /absolute/pinned-systems-and-tasks.yaml \
  --out /empty/release-benchmark-directory
```

The destination must be empty. The harness emits raw per-run results,
configuration, task inventory, methodology, JSON/Markdown summaries, and keeps
step-caller and compiled-skill tracks separate. Fewer than 30 runs is explicitly
not release eligible.

See [operations.md](operations.md), [threat-model.md](threat-model.md), and
[known-limitations.md](known-limitations.md) before deployment.
