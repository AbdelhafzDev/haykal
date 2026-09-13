# ADR 0002: v1 contract and device foundation

- Status: accepted for implementation
- Date: 2026-09-13

## Decision

Canonical contracts are strict Pydantic models and generated JSON Schemas. Unknown
fields fail validation. Public `schema_version` is `1.0`; compatible proxying is a
future service behavior, not permission for the kernel to accept unknown syntax.

Device calls are asynchronous at the Haykal boundary, serialized per backend, and
bounded by deadlines. Reversible operations may receive one visible recovery
attempt. Irreversible calls require an audited `AtMostOnceDispatcher` and otherwise
fail closed.

Exclusive device ownership uses SQLite leases with expiring tokens and monotonically
increasing fencing generations. Temporary device-state baselines are journaled by
generation; a new owner restores state abandoned by an expired owner before using
the device. Artifacts use atomic SHA-256 content addressing.

## Consequences

- Contract drift fails tests until schemas and fixtures are intentionally updated.
- The synchronous UIAutomator2 library cannot block the application event loop.
- Timed-out worker threads may finish in the background, so a timeout is never an
  authorization to dispatch an irreversible action through the ordinary path.
- Normal shutdown restores the active baseline and marks it complete.
- A crashed process leaves a pending journal entry, which the next fenced lease
  restores before recording its own baseline.
