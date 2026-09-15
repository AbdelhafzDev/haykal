# Comparative benchmark harness

`tasks.yaml` is the machine-check inventory for the twenty declared reference
tasks. A v2 run manifest embeds those tasks and combines them with the shape shown
in `systems.example.yaml`. Each adapter receives one task as JSON on stdin, but
its `success` and `unsafe_actions` values are diagnostic claims only. A separately
pinned oracle resets Matjar, captures pre/post state, and owns published scoring.

Every executable, adapter, model, prompt, APK, device image, task suite, and
configuration requires a full SHA-256 pin, verified before the output directory
is created. Production reports use 30 clean starts per task with deterministic
randomized system order. Raw oracle evidence is sealed by a digested manifest;
`haykal benchmark-rebuild` verifies it and recreates derived summaries without
calling an adapter.

Run `scripts/p95-3-local-evidence.sh EMPTY_DIRECTORY` for the deliberately lying
local-adapter proof. It is controller validation, not an Agent Device result.

Maestro MCP and ARTEMIS are omitted until M0 records an exact, reproducible
configuration. This is a published omission, not a zero score.
