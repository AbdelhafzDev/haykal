# Phase 3 runbook

## Install and verify

```bash
cd /Users/abdelhafz/dev/haykal
uv sync --all-extras --locked
./scripts/phase3-check.sh
```

Set an Android serial explicitly. Haykal acquires a fenced SQLite lease, restores
an abandoned input-method baseline before use, heartbeats while the session is
open, and restores the current baseline on close.

## Authoring tools

```bash
uv run haykal scene --device emulator-5554
uv run haykal scene --device emulator-5554 --json > scene.json

uv run haykal resolve --dry-run \
  --scene scene.json \
  --selector '{"role":"button","label":{"contains":"أضف"}}'

uv run haykal extract --dry-run \
  --scene scene.json \
  --request extract/offers.yaml

uv run haykal lint skills/matjar/offers.yaml
uv run haykal replay skills/matjar/offers.yaml \
  --fixtures skills/matjar/fixtures/1.0.0
```

`resolve` exits 2 when it abstains or finds ambiguity. `extract` exits 2 when the
declared request is not satisfied. `lint` and `replay` are device-free and are
intended for CI.

## HTTP and SSE

Serve loopback only for the local MVP:

```bash
export HAYKAL_API_TOKEN='replace-with-a-random-secret'
uv run haykal --state-dir .haykal serve --host 127.0.0.1 --port 8421
```

Create a session:

```bash
curl -sS http://127.0.0.1:8421/v1/sessions \
  -H "Authorization: Bearer $HAYKAL_API_TOKEN" \
  -H 'Idempotency-Key: session-create-001' \
  -H 'Content-Type: application/json' \
  -d '{"device_serial":"emulator-5554"}'
```

Every mutating request needs a unique `Idempotency-Key`. Exact replay returns the
stored response with `Idempotency-Replayed: true`. Changed content returns
`idempotency_conflict`. An incomplete claim after a crash returns
`outcome_unknown` and is never re-executed automatically.

Pass `X-Haykal-Run-ID` on an action, then consume durable events with:

```bash
curl -N http://127.0.0.1:8421/v1/runs/RUN_ID/events \
  -H "Authorization: Bearer $HAYKAL_API_TOKEN" \
  -H 'Last-Event-ID: 0'
```

## MCP v2

The stdio server owns one configured device session:

```bash
uv run haykal --state-dir .haykal mcp \
  --device emulator-5554 \
  --session-id android
```

Configure that command in the MCP host and pass `session_id: android` to tools.
Available tools are `observe`, `resolve`, `extract`, `act`, `verify`, and
`get_trace`. Risky actions are fail-closed in Phase 3; Phase 4 adds the separate
approval principal and bound approval tokens.

## Live reference gate

```bash
ANDROID_SDK_ROOT=/path/to/android-sdk \
FLUTTER_BIN=/path/to/flutter/bin/flutter \
ANDROID_SERIAL=emulator-5554 \
./scripts/phase3-reference-check.sh
```

This builds, installs, resets, and probes both reference apps, then resolves and
taps the stable `search_button` accessibility resource, waits for two stable scenes,
verifies `اعرض النتائج`, and
checks the six-event trace.

## Comparative harness

Create a v2 run manifest containing the twenty entries in
`benchmarks/tasks.yaml`, an independently pinned oracle, and configurations shaped
like `benchmarks/systems.example.yaml`, then run:

```bash
uv run haykal benchmark --manifest benchmark-run.yaml --out report/
uv run haykal benchmark-rebuild --report report/ --out rebuilt/
```

Every executable, adapter, model, prompt, APK, device image, task suite, and
configuration must have a verified SHA-256 pin. Each command adapter reads one
JSON task from stdin, but its success and safety fields are claims only. The
controller resets through the separate oracle, records pre/post state, scores the
declared checks, seals raw evidence read-only, and derives the report. Never merge
the step-caller and compiled-skill tracks.
