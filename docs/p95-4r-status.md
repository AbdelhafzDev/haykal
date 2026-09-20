# P95.4R status: focused release-gate remediation

Decision: **passed in hosted CI; proceed to P95.5**

Release target: `0.0.3`

Defensible implementation score after hosted P95.4R acceptance: **91/100**. This
does not by itself earn the remaining external-evidence points required for 95.

P95.4R closes the release-review findings without expanding product scope:

- `resolve` is read-only again. Record relocation is an explicit reversible
  `reveal` operation whose swipes, observations, and verification are written to
  the run trace before target resolution.
- Record anchors are bound to the semantic fingerprint captured during
  extraction. A unique resource ID is insufficient when label, ancestry, or
  other fingerprint material changes.
- Release bundles are built exclusively from the committed Git tree. The builder
  rejects tracked and untracked worktree changes before creating an archive and
  records the source-tree object in the build manifest.
- HTTP acceptance launches the installed `haykal serve` entrypoint over a real
  loopback socket. MCP acceptance launches the installed `haykal mcp` entrypoint
  over stdio.
- Upgrade acceptance seeds and verifies artifacts, traces, run snapshots, action
  checkpoints, approval storage, signed skills, SQLite integrity, and required
  tables across the previous-to-current wheel upgrade.
- Approval acceptance asserts zero irreversible review dispatches before approval
  and after stale approval. Timeout reconciliation requires exactly one review
  dispatch with a non-repeated receipt.
- Matrix attestation verifies every evidence digest and requires an identical
  release object across API 34 and 35, including commit, source tree, wheel, APK,
  previous wheel, and build-manifest digest.

## Release identity

One clean commit produced one immutable release bundle:

| Field | Value |
| --- | --- |
| Version | `0.0.3` |
| Commit | `883937b9969802694a27a39261b850c075aa5467` |
| Source tree | `2ced8d6fb3460b84b2b381f46bb65f320b376d57` |
| Wheel SHA-256 | `b01ce357d5c5be1142b8aca427b63843f4d08ad8ee5d4de21dd29e00d169c200` |
| APK SHA-256 | `e046bda3be2b5ff7905553ce495fdea1c110084ba2f0179dba8dbae84c29a82e` |
| Build manifest SHA-256 | `818610a1903cdd921da58573115fff701e7e24717d38116dd03efac07af3d84d` |
| Previous release | `0.0.2` |
| Previous wheel SHA-256 | `0841206d6b84fefb4c3e65ff3accd830f13d873a3863aff58fc2a03fb2179cad` |

## Clean-device acceptance

The exact bundle above passed wheel-only acceptance after wipe-data boots on both
supported Android versions:

| VM | Result | Acceptance manifest SHA-256 | Evidence index SHA-256 |
| --- | --- | --- | --- |
| API 34, Android 14 | Passed | `a3135fec5c7a17dfd71373228d31acc79ce210d892e788456b72708ac54987c4` | `1f06ca88a4054d4fcb4d5833cb4bf4fb6021027e21e2fe8b97af65b13d1830ca` |
| API 35, Android 15 | Passed | `4958be83b4875e691c50017ecd123d716d0fe1420e450bfe77839024154eccb9` | `ebf77fdedc0456fa68b5c96a1c8bfb9594f468e6c0efce2d5dc0186e83d3e754` |

The same-release attestation passed with SHA-256
`75ce9e7a0ff3bf04fc52b8122b6bcb4ce9661da0eb495d2aeb5ff27244c44d13`.
Each device passed Arabic input and offers, primitive action, approval stop,
stale approval rejection, submit-timeout reconciliation, HTTP, MCP, trace export,
retention preview, backup/restore, device-aware readiness, and upgrade/schema
compatibility.

The local and hosted acceptance runs exposed and fixed release-boundary defects
before the final pass: an incomplete upgrade fixture, a development-only
transport-smoke dependency, uninitialized HTTP readiness artifacts, cold
navigation verification budgets, Android 15 focus loss while enabling the
Unicode input method, an incorrectly shared command timeout for cold Unicode
input, cold Compose scene readiness, and a fallback-skew check that rejected
accessibility-only observations even when no OCR or vision adapter was present.

Hosted run: [GitHub Actions run 35501344891](https://github.com/AbdelhafzDev/haykal/actions/runs/35501344891),
completed successfully in 13m17s from a fresh checkout. It published four
downloadable artifacts with 14-day retention:

| Artifact | GitHub artifact ID | Archive SHA-256 |
| --- | ---: | --- |
| `p95-4-release-bundle` | `10602661162` | `009e041377e1e82c6dccb362bf87a6ba7d218b520ac5661f92ed71580c4bef14` |
| `p95-4-api-34` | `10602577828` | `801d975a3370c07c39ee5c2e1abc523a814271284995565b3603ace1795b2c65` |
| `p95-4-api-35` | `10602556830` | `53f474ea42b02631793645bd42867700f4d54129e6df8ee387d89b4192e9dacc` |
| `p95-4-same-wheel-attestation` | `10601889155` | `20d077b388e6221a09f972b0c2221db20caae72123ab418096ff7dd735170f94` |

The downloaded release `SHA256SUMS` and both device `evidence-sha256.txt`
indexes were independently rechecked after the hosted run; every entry passed.
The attestation binds the two VM fingerprints to the same commit, source tree,
wheel, APK, previous wheel, and build manifest.

## Remaining gate

P95.4 is complete. P95.5 is the remaining path to a defensible 95/100: a real
eight-hour release-wheel soak, an external competitor run through the independent
oracle, authorized regional-app validation, a non-core author exercise, and the
OCR/vision licensing and Arabic-accuracy decision. These external and elapsed-time
gates remain no-go until their evidence exists.
