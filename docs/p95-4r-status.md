# P95.4R status: focused release-gate remediation

Decision: **implementation complete; clean-device release evidence pending**

Release target: `0.0.3`

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

The prior `0.0.2` API 34/35 evidence remains historical and does not count for
this release candidate. P95.4R is complete only after one clean commit produces a
new immutable bundle and that exact bundle passes API 34 and API 35 acceptance.
Hosted CI remains a release requirement; the repository still needs a configured
remote before hosted evidence can be produced.

