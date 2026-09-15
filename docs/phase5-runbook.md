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
haykal --state-dir /var/lib/haykal diagnostics \
  --device emulator-5554 --adb-path "$ANDROID_SDK_ROOT/platform-tools/adb"
curl http://127.0.0.1:8421/livez
curl http://127.0.0.1:8421/healthz
curl http://127.0.0.1:8421/readyz
curl -H "Authorization: Bearer $HAYKAL_API_TOKEN" \
  http://127.0.0.1:8421/v1/diagnostics
```

`/livez` proves only that the process/event loop responds. `/healthz` is the
minimal compatibility aggregate. `/readyz` returns 200 only when storage, disk,
ADB authorization, the configured target, lease, UIAutomator2 helper, and pending
recovery checks all pass; degraded and unhealthy states return 503. Public
responses omit paths, timestamps, serials, and failure details. The authenticated
endpoint returns the detailed checks. Use `diagnostics --storage-only` only for
offline maintenance; it is not device readiness.

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

## Fault matrix, load, and soak

Run the host process/SQLite/artifact/lease/settings/disk matrix into a new
directory:

```bash
haykal fault-matrix --output-state /empty/p95-2-fault-state \
  --output reports/p95-2/fault-matrix.json
```

With a dedicated emulator, add UIAutomator2 death, target-scoped ADB reconnect,
IME restore, and readiness transitions:

```bash
ANDROID_SDK_ROOT=/opt/android-sdk ANDROID_SERIAL=emulator-5554 \
  ./scripts/p95-2-device-check.sh /empty/p95-2-device-evidence
```

A bounded component run:

```bash
haykal hardening-run --duration-s 60 --workers 4 --chaos-every 37 \
  --output reports/m5/storage-hardening.json
```

The report contains sampled RSS, file/artifact/SQLite bytes, open descriptors,
latencies, recovery counts, growth slopes, and explicit absolute limits. A
30-minute run is the P95.2 development gate. The release device soak remains
separate:

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
