# Phase 3 implementation status

Phase 3 implementation finished locally on 2026-09-13. Haykal now has one
deterministic observe-resolve-act-settle-verify loop used by its embedded runtime,
HTTP API, Python SDK, MCP server, and authoring tools. A real UIAutomator2 action
passed on the API 37 Pixel VM. Phase 3 is implementation-complete, but formal
release acceptance remains blocked by the declared reliability, latency,
authoring, comparative benchmark, and M0 evidence gates.

## Implemented

- Ranked semantic target resolution with source diagnostics, actionable-parent
  promotion, confidence and margin abstention, record anchors, and stale-target
  re-resolution through stable IDs or semantic fingerprints.
- Action validation and receipts for tap, swipe, Unicode input, key press, and
  bounded waits. Receipts carry backend, method, parameter digest, dispatch
  status, repeat status, and input strategy without tracing plaintext input.
- Approval-required rejection for sensitive and irreversible risk categories.
  Approved irreversible execution is routed only through the durable M0
  single-shot boundary; unknown outcomes never enter verification or retry.
- Recursive three-valued expectations for boolean composition, visibility, text,
  state, parsed number/money/rating/duration values, foreground package, scene
  change, and scene stability.
- Bounded polling and semantic settling. The fingerprint excludes frame-local
  IDs, volatile provenance, and Android System UI so repeated stable captures do
  not churn on implementation metadata.
- Durable ordered SQLite traces and a shared serialized `RuntimeSession` with
  bounded scene retention.
- Authenticated HTTP primitives, durable principal-bound idempotency claims,
  replayed cached responses, conflict detection, trace retrieval, and resumable
  SSE sequence IDs.
- Typed Python HTTP client and an official MCP Python SDK v2 adapter exposing
  `observe`, `resolve`, `extract`, `act`, `verify`, and `get_trace`.
- `haykal scene`, `resolve --dry-run`, `extract --dry-run`, `lint`, and `replay`,
  plus loopback HTTP serving and configured-device MCP stdio serving.
- A pinned JSON-over-stdio comparative harness with mandatory Haykal and Agent
  Device systems, separate tracks, per-run CSV, exact pins, median/p95, unsafe
  rates, and Wilson 95% intervals. The twenty machine-check task definitions are
  checked in under `benchmarks/`.
- Reproducible host and API 35 emulator CI definitions plus a Phase 3 live-action
  gate.

## Latest local evidence

- Host: 447 Python tests pass with 80.45% coverage; all 13 schema drift checks,
  Ruff formatting/lint, strict mypy over 76 source files, locked dependency sync,
  CLI import/startup, HTTP, Python SDK, and MCP in-memory checks pass.
- Live VM: Android API 37, ARM64 Pixel emulator, Matjar cold start,
  UIAutomator2 3.x.
- Resolver: the Compose text child was promoted to its tappable parent with score
  0.994; only one candidate was accepted.
- Dispatch: exactly one tap at `(346, 600)` returned an accepted UIAutomator2
  receipt with `dispatch_status=dispatched` and a SHA-256 parameter digest.
- Verification: two stable post-action scenes contained the Android View `حفظ`
  control and the action returned `verified`.
- Trace: six ordered events link action preparation, target evidence, receipt,
  post-scene, expectation evidence, and committed transition.
- The complete repeatable reference gate (both app builds, installs, fault
  controls, device smokes, then the Matjar action) passed. Its verified action
  took 1.629 seconds, including 1.478 seconds of verification. An earlier cold
  UIAutomator2 run took 21.694 seconds before helper warm-up, so neither result is
  presented as a p95 latency pass.

Generated live evidence is under `reports/m3/` and ignored because it may contain
screen-derived data.

## Exit criteria

| Criterion | Status | Evidence or blocker |
| --- | --- | --- |
| Ambiguity returned below configured margin | passed | duplicate-target unit and no-dispatch assertion |
| Every action links pre/target/receipt/post/verification | passed locally | unit integration and six-event live trace |
| Unknown outcome differs from safe failure | passed | single-shot uncertain-outcome and post-dispatch-failure tests |
| Unicode strategy and restoration | provisional | helper-IME receipt/redaction plus Phase 1 durable restoration; full M0 field matrix pending |
| Primitive reliability >=99% over 1,000 actions | pending | harness and single live proof exist; qualification run not performed |
| Accessibility-only observe p95 <=1,000 ms | pending distribution | warm verified action was 1.629 s, but a cold helper run was 21.694 s; the required p95 sample and M0 screenshot-path decision are unresolved |
| One-day offers authoring exercise | pending external participant | lint/replay tools pass; timed non-author exercise not performed |
| Comparative harness runs validated systems on both tracks | partially blocked | harness and 20 tasks exist; Agent Device exact pin/adapter process and compiled skills are not yet available |
| Hosted API 35 gate | configured, awaiting remote | `.github/workflows/phase3.yml`; repository has no GitHub remote |

Phase 4 can proceed locally because the primitive loop and its contracts are
integrated. A release tag must remain blocked. In particular, one successful live
tap cannot substitute for 1,000-action reliability, a 30-start authoring/skill
qualification, or the labelled M0 perception and input evidence.
