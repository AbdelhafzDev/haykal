# ADR 0007: Release hardening boundary

- Status: accepted
- Date: 2026-09-13

## Decision

Phase 5 adds operational diagnostics, conservative public/export redaction,
bounded retention, verified backup/restore, static trace reports, supply-chain
evidence, and reproducible hardening harnesses. It does not add the recorder.

The public health endpoint exposes only readiness, version, and aggregate check
counts. Detailed diagnostics require the caller token. Public trace responses and
SSE are redacted even when raw local trace storage is retained. Screenshots are
omitted from exports unless a policy explicitly enables images and declares
pixel-region redaction.

Backups use SQLite's online backup operation and a per-file digest manifest.
Restore targets must be empty and archive entries cannot be links, devices,
absolute paths, traversal paths, or files absent from the manifest.

The short load/soak/chaos run in the normal gate validates the harness only. It
cannot satisfy the eight-hour release gate. The comparative report cannot be
published until exact runnable Haykal and Agent Device adapters are supplied.

## Consequences

- Operations are diagnosable without granting database access.
- Private data is not returned merely because a trace row incorrectly claimed
  that redaction had already happened.
- Retention is preview-first; destructive application is explicit.
- The release status distinguishes implemented mechanisms from elapsed-time,
  external-system, and human-participant evidence.
