# P95.4 shipped-wheel acceptance runbook

P95.4 tests the distributable artifact. The build step may use the checkout;
the acceptance runtime may not import or execute Haykal from it.

## Build once

From a clean, committed checkout with full Git history:

```sh
ANDROID_SDK_ROOT=/opt/android-sdk \
  ./scripts/p95-4-build-bundle.sh /empty/release-bundle
```

The command builds the current wheel once, locates and builds the most recent
earlier package version for the upgrade fixture, assembles Matjar, and records
all digests in `build-manifest.json` and `SHA256SUMS`. Set
`HAYKAL_PREVIOUS_REF` only when automatic version-history discovery is not the
intended upgrade baseline.

The promoted wheel must never be rebuilt in an API-specific job. Copy or
download the entire bundle without changing it.

## Run one clean VM

Boot a clean Google APIs VM, then run:

```sh
ANDROID_SDK_ROOT=/opt/android-sdk \
ANDROID_SERIAL=emulator-5554 \
P95_API_LEVEL=34 \
  ./scripts/p95-4-wheel-acceptance.sh \
  /immutable/release-bundle /empty/evidence-api-34
```

Repeat from a separate clean snapshot with `P95_API_LEVEL=35`. The script:

- verifies every bundle digest before installation;
- installs the previous wheel, creates durable state, then upgrades to the
  promoted wheel;
- clears `PYTHONPATH`, disables user site packages, changes to a temporary
  directory, and proves `haykal.__file__` is inside the clean venv;
- runs a real primitive action plus HTTP and MCP observations;
- exercises Arabic input, both Matjar skills, the purchase stop, stale approval,
  and submit-timeout reconciliation;
- exports a static trace, previews retention, backs up and restores state; and
- proves connected, absent, and recovered device-readiness states.

No acceptance command uses `uv run`. Installation logs, package inventory,
device properties, app packages, logcat, reports, and hashes are retained.

## Verify the matrix

```sh
python3 scripts/p95-4-verify-matrix.py \
  /evidence-api-34 /evidence-api-35 \
  --output /empty/same-wheel-attestation.json
```

The command rejects missing API levels, a failed run, or different wheel
digests. `.github/workflows/p95-4.yml` implements this build-once, two-VM, final
attestation topology in hosted CI.

Evidence directories are immutable inputs to review. Never edit a failed run;
retain it and start with a new empty directory.
