# ADR 0006: durable skills and content-bound approval

- Status: accepted for implementation
- Date: 2026-09-13

## Decision

Published skills are immutable content-addressed objects. A publisher signs the
canonical skill digest with Ed25519, and a deployment loads the object only when
the configured trust policy recognizes the publisher and verifies the digest and
signature. Reusing a name and semantic version for different bytes is rejected.

The skill interpreter is a deterministic guarded state machine. Its evaluation
order is `expect`, `extract`, `select`, `reconcile`, `gate`, `action`, `verify`,
then transition. Selection excludes null referenced values, applies declared
filters and ordering, and uses `record_id` as the final stable tie-break. A
declared insufficient margin pauses with the exact candidate set rather than
choosing silently.

Each run and action checkpoint is committed to a synchronous WAL SQLite journal.
An action ID is deterministic for the run and state. A committed action advances
without dispatch on recovery. A checkpoint found only in `prepared` is changed
to `outcome_unknown`; it is never dispatched again. A recovery decision may be
saved as a candidate patch, but no runtime path can promote that patch into a
published skill.

Approval is a separate authority. The approver first reads the exact challenge,
including extracted material, skill digest, action-intent digest, target
fingerprint, and expiry. The confirmation must present that same challenge. The
runtime then re-observes, re-extracts, and re-resolves immediately before token
consumption. A changed material or target binding makes the approval stale.
Tokens are opaque, signed, stored by hash, and atomically single-use.

Approved irreversible taps pass through a durable UIAutomator2 single-shot
transport. It invokes the raw client exactly once and deliberately bypasses the
normal backend recovery retry. A crash after preparation is therefore reported
as unknown and reconciled; it cannot trigger a second tap. Reversible operations
continue to use the normal bounded recovery path.

## Consequences

- Known workflows complete without a model call; unknown states pause with a
  bounded response vocabulary.
- A full scene change does not stale an approval when the target and material are
  unchanged, but any bound target or material change does.
- Approval safety can sacrifice automatic progress after a crash; reconciliation
  is required to recover truth.
- The same skill/run service is available over Python, HTTP, and MCP. MCP approval
  is registered only on a separately authorized server identity.
- A regional-app compatibility result cannot be claimed until an authorized
  account, declared app version, and release-safe test environment are provided.
