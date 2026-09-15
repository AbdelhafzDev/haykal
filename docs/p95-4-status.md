# P95.4 status: test the shipped product

Decision: **complete locally; hosted fresh-checkout evidence remains no-go**

Commit: `3bcdfdec9a33c084947be65f8ce306fcc942ec17`

Wheel: `sha256:4f55eec86ff084ca8497f73fb11b4e142487a7cc69ceeb10212f0ded4ed3db58`

Environment: macOS arm64 host; wipe-data Google APIs arm64 VMs:

- API 34: `google/sdk_gphone64_arm64/emu64a:14/UE1A.230829.050/12077443:userdebug/dev-keys`
- API 35: `google/sdk_gphone64_arm64/emu64a:15/AE3A.240806.043/12960925:userdebug/dev-keys`

Commands:

```text
./scripts/p95-4-build-bundle.sh /empty/release-bundle
./scripts/p95-4-wheel-acceptance.sh /release-bundle /empty/evidence
python3 scripts/p95-4-verify-matrix.py /api-34 /api-35 --output /empty/attestation.json
```

Tests: 524 passed with 84.67% coverage; Ruff passed; strict mypy over 100
source files passed; 21 schemas regenerated; sdist/wheel build and clean wheel
install passed. Both local clean VMs passed every shipped-wheel acceptance check.
The hosted workflow builds one bundle, fans the unchanged artifact out to clean
API 34 and 35 VMs, and creates a same-wheel attestation.

Evidence: generated evidence is under ignored `reports/p95-4/`, not in Git.

- same-wheel attestation: `sha256:6270396013d0275c329f8b1726c8405b137f52df892ed21b34c59bcb91982b38`
- build manifest: `sha256:61e1b82e7c47c6d82ac861b76f15e5ae8e0fe4a95c692b253bcce2918793e2b9`
- API 34 acceptance manifest: `sha256:ea0f104927c99cadbf327a2442d50f45539db2a6372e3f5a173015e50f9b2e77`
- API 35 acceptance manifest: `sha256:350b947000256ca1b11bbf8470840547dd70a0721da3c08f428fa4aceaa33c07`
- Matjar APK: `sha256:6f79e3fba002875a8eaf804e682d960e8a98fbedae41292b8246c17abaca91ff`
- previous 0.0.1 wheel: `sha256:9132be7e50de198c2128eb657425317b206757b4ff7a4abc9481ce088b61de15`

Open findings:

- high — repository has no configured remote, so hosted CI cannot yet provide a
  run URL or fresh-checkout attestation;
- medium — the evidence is local rather than a downloadable hosted artifact;
  publish it through the configured workflow after adding a remote.

Score after evidence: **89/100 official, 91/100 conditional** on the unchanged
workflow passing from a hosted fresh checkout. The local API 34/35 matrix earns
the P95.4 product evidence; the missing hosted provenance is not silently counted.

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
app's fault channel, and waits for the changed total on the same checkout screen
before submitting the now-stale token. The gate must pause again with
`reason=approval_stale`; no purchase dispatch may occur.

## Failures found by the matrix

P95.4 found and fixed product-level defects before the green runs:

- `record_anchor.scene_revision` was not used to retrieve its source scene;
- off-screen selected records did not restore their bounded scroll checkpoint;
- a unique exact resource ID could lose to geometry drift after scrolling; and
- Matjar could not expose a material price change while checkout stayed open.

The final runtime scans backward for the bounded checkpoint, requires the target
resource to become visible, and accepts an exact resource match only when it is
unique and actionable. Duplicate IDs still fail closed through ranked ambiguity.
