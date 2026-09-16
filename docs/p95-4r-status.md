# P95.4R status: focused release-gate remediation

Decision: **local release acceptance passed; hosted release provenance pending**

Release target: `0.0.3`

Defensible implementation score after P95.4R: **90/100 locally**. A hosted
fresh-checkout run of the same release would raise the release evidence to the
forecast **91/100**. It does not by itself earn the remaining external-evidence
points required for 95.

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
| Commit | `98beea89218ced122ecc6cf4f00487bbb51de2cc` |
| Source tree | `66503e5689aa8f89aa574657f7095cc62e26222c` |
| Wheel SHA-256 | `e89d7fc0875befcbfc7ebdf3337e64b303afb02b7b05005a6f9dedc3ab9ebdb2` |
| APK SHA-256 | `438d09b82db6d4c738a3a875b5bdd595c0ee7d500e8e439e5321848e75b4166a` |
| Build manifest SHA-256 | `7c8aa9bd819c25c8b7153784da8228f9d9564fd41ae507e8872bc6d9635f078a` |
| Previous release | `0.0.2` |
| Previous wheel SHA-256 | `a9228d13f07bbc925659d141e91d31ac32859bf6fb2d186c10607ebbde326cb7` |

## Clean-device acceptance

The exact bundle above passed wheel-only acceptance after wipe-data boots on both
supported Android versions:

| VM | Result | Acceptance manifest SHA-256 | Evidence index SHA-256 |
| --- | --- | --- | --- |
| API 34, Android 14 | Passed | `f7ffd6d0112bdd2e8fef1d264abbe37df287a816f5a421adb061ddff5a097d2e` | `a03b4fe707090ce473daabfd38ea8bddf352e873b8c8521c72ee15c07c1e72ed` |
| API 35, Android 15 | Passed | `a7e684e9125ba845bed3ec83bb09663117ee8ecda27081913c66f89a06ae363d` | `3acd8192cb06b037267b6959bca6991bb5d587c708c5230822765cad35ef2b8a` |

The same-release attestation passed with SHA-256
`adbd60104e6a55d1ea0f2c0c45c97e45f229a7683949a61b9018c4b63f4cffca`.
Each device passed Arabic input and offers, primitive action, approval stop,
stale approval rejection, submit-timeout reconciliation, HTTP, MCP, trace export,
retention preview, backup/restore, device-aware readiness, and upgrade/schema
compatibility.

The acceptance run exposed and fixed four release-boundary defects before the
final pass: an incomplete upgrade fixture, a development-only transport-smoke
dependency, uninitialized HTTP readiness artifacts, and focus loss while enabling
the Unicode input method. The final Arabic typing path enables the IME without an
empty text injection and gives cold-device verification its own bounded budget.

Generated evidence is retained locally under `reports/p95-4r/` and deliberately
ignored by Git because the bundle and device artifacts total about 48 MB. The
small status record carries their cryptographic identities; the release verifier
validates the complete local evidence indexes.

## Remaining gate

The prior `0.0.2` API 34/35 evidence remains historical and does not count for
this release candidate. Local P95.4R is complete. The overall release decision
remains **no-go** only for hosted provenance: `git remote -v` is empty, so a
fresh-checkout hosted CI run and downloadable hosted artifacts cannot yet be
produced. After a remote is configured, run the same release workflow in hosted
CI and retain its run URL and artifacts before changing the release decision.
