# P95.4 status: test the shipped product

Decision: **in progress — implementation complete; API 34/35 and hosted evidence pending**

Commit: pending implementation commit

Wheel: pending clean-checkout build

Environment: local host verification complete; clean Android API 34/35 matrix pending

Commands:

```text
./scripts/p95-4-build-bundle.sh /empty/release-bundle
./scripts/p95-4-wheel-acceptance.sh /release-bundle /empty/evidence
python3 scripts/p95-4-verify-matrix.py /api-34 /api-35 --output /empty/attestation.json
```

Tests: 523 passed; Ruff passed; strict mypy passed. The hosted workflow builds
one bundle, fans the unchanged artifact out to clean API 34 and 35 VMs, and
creates a same-wheel attestation.

Evidence: pending clean release-candidate runs. Generated evidence belongs under
ignored `reports/p95-4/`, not in Git.

Open findings:

- high — repository has no configured remote, so hosted CI cannot yet provide a
  run URL or fresh-checkout attestation;
- high — clean API 34 and API 35 acceptance manifests are not yet attached;
- medium — local API 37 can validate the harness but cannot satisfy the matrix
  exit criterion.

Score after evidence: **86/100 official, 88/100 conditional** until both required
API levels pass with one clean, immutable wheel. A local or API 37 smoke does not
award the forecast P95.4 points.

## Implemented acceptance boundary

Release version `0.0.2` is the upgrade target; the builder locates the last
different package version (`0.0.1`) from Git history. Acceptance first creates
state with that earlier wheel and only then force-upgrades to the one promoted
wheel.

The runner starts outside the source checkout with an empty `PYTHONPATH`, a
disabled user site, and a new venv. It fails unless the imported `haykal` module
is inside that venv and unless the build manifest says the wheel came from a
clean worktree.

Matjar's stale-approval case is device-backed: the runtime pauses at the purchase
gate, grants a one-time token, changes the checkout price through the reference
app's fault channel, restarts the activity at its persisted checkout screen, and
submits the now-stale token. The gate must pause again with
`reason=approval_stale`; no purchase dispatch may occur.
