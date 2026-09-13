# ADR 0005: deterministic action loop and northbound boundaries

- Status: accepted for implementation
- Date: 2026-09-13

## Decision

Every caller uses one serialized `RuntimeSession`. It owns observation history,
adjacent-frame identity, extraction, resolution, action dispatch, verification,
and trace access. HTTP, the Python client, MCP, and authoring tools are adapters;
none may call UIAutomator2 directly.

The resolver ranks compatible actionable targets, records per-candidate reasons,
and abstains below either the minimum score or ambiguity margin. A stale element
ID is accepted only when its stable ID survives or its source-scene semantic
fingerprint can be re-established above the same thresholds.

Reversible operations permit the backend's one bounded recovery. Irreversible
operations use the M0 single-shot dispatcher and never enter that recovery path.
An uncertain irreversible dispatch returns `outcome_unknown`. The HTTP layer has
a separate durable idempotency ledger: it claims a principal/key/digest before
execution, returns a completed cached response on exact replay, rejects changed
content, and refuses to execute a claim left incomplete by a crashed process.

Verification polls coherent semantic frames within a declared bound. Settling
uses visible application content, state, bounds, and actions while excluding
frame-local element IDs, evidence addresses, and Android System UI nodes. This
prevents identity allocation or the status-bar clock from making a static app
screen appear unstable.

The MCP adapter uses the official Python SDK v2 and exposes structured primitive
tools over the same session. HTTP/JSON remains canonical; its durable trace
sequence is also the SSE event ID. MCP task/skill calls are deferred to M4 rather
than embedding another reasoning loop in M3.

## Consequences

- A dry-run selector and a dispatched selector execute the same resolver code.
- Plaintext input is not written to action traces; receipts record a strategy and
  parameter digest.
- A process crash after an HTTP claim cannot transparently repeat the request.
- Local MCP clients get structured objects without depending on the HTTP server.
- ARM64 UIAutomator2 coherent captures are currently much slower than the
  provisional latency gate; screenshot-path selection remains a blocking M0 item.
