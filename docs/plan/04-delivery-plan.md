# Delivery plan

The schedule is milestone-based. Dates are assigned only after Milestone 0
completes and the first design-partner workflow is identified.

## Effort summary

| Milestone | One engineer | Two engineers (calendar) |
| --- | ---: | ---: |
| M0 Validate assumptions and dispatch safety | 2–3 wk | 1.5–2 wk |
| M1 Contracts, device, focused reference apps | 4 wk | 2–2.5 wk |
| M2 Scene, fusion, identity, extraction | 5–6 wk | 3–3.5 wk |
| M3 Resolver, actions, verification, core authoring | 4–5 wk | 2–2.5 wk |
| M4 Skills, escalation, gates, reconciliation | 5 wk | 3–3.5 wk |
| M5 Hardening and release evidence | 4–5 wk | 2.5–3 wk |
| **Stable core total** | **24–28 engineer-wk** | **14–17 calendar wk** |
| M6 Maestro importer (only on partner demand) | 1 wk | 1 wk |

The estimate includes contingency for perception variance and safety rework. A
launch package with recorder polish plus validated Maestro and ARTEMIS adapters is
28–32 engineer-weeks. Scope is cut by combining View, Compose, and WebView cases
inside Matjar and keeping a single Flutter fallback app; reliability is not cut.

## Milestone 0: validate critical assumptions

**Goal:** remove dependency, device, and customer uncertainties before committing
public contracts.

Deliverables:

- Reproducible Android VM image and bootstrap script (API levels chosen from
  partner targets, minimum two).
- UIAutomator2 lifecycle spike covering connect, hierarchy, action, screenshot,
  process death, reconnect, and cleanup.
- Wire-level UIAutomator2 retry audit. Prototype the irreversible dispatch path
  that bypasses or disables transparent JSON-RPC retries and prove one injected
  timeout cannot produce a second input event.
- Screenshot comparison between UIAutomator2 and lossless ADB screencap on
  Arabic screens: latency, pixel difference, OCR accuracy.
- Arabic input matrix covering native View, Compose, WebView, Flutter, multiline,
  mixed Arabic/English/numbers, emoji, and secure fields.
- OCR comparison on 200 labelled Arabic/English screenshots across at least two
  local OCR engines.
- OmniParser-compatible adapter spike on hierarchy-sparse screens, including
  license review of detector and caption weights.
- `arabic-search@1`, `arabic-material@1`, and `money@1` reference implementations with 300 labelled
  strings including Arabic-Indic digits, currency tokens, and duration ranges.
- Dependency license inventory with model and weight checksums.
- Three design-partner interviews answering: primitives vs skills, who owns
  logged-in devices, which actions need approval, must perception be offline.
- Baseline latency and failure measurements, not marketing targets.

Exit criteria:

- A default screenshot path and OCR backend are selected from measurements.
- Unsupported text-field categories are documented.
- UIAutomator2 recovery and input-method restoration work on the reference VM.
- The irreversible path has a documented at-most-once dispatch boundary and an
  automated replay-prevention test at the device/wire layer.
- Normalizer and money parser pass 100% of the labelled set or the failing cases
  are documented as out of scope.
- No unresolved license prevents private commercial distribution.
- Partner interview findings are recorded as ADRs and the first reference
  workflow is chosen.

## Milestone 1: contracts, device foundation, reference apps

**Goal:** establish versioned public boundaries, reliable device ownership, and
the applications every later gate runs against.

Deliverables:

- Repository/package scaffold, static checks, tests, and build metadata.
- Pydantic models plus committed JSON Schemas for observation, scene, selector,
  action, extraction request/result, expectation, result, skill, event, and trace.
- Selector vocabulary validator and element-dictionary resolver with cycle
  detection.
- Compatibility fixtures and golden serialization tests.
- Async `DeviceBackend` protocol.
- UIAutomator2 backend with serialized operation queue and deadlines.
- Exclusive device lease, heartbeat, health check, bounded restart, and cleanup.
- Content-addressed raw artifact storage.
- Focused reference suite v1 from
  [07-reference-apps-and-benchmarks.md](07-reference-apps-and-benchmarks.md):
  Matjar contains View, Compose, embedded WebView, and fault-injected checkout
  screens; `flutter-sparse` covers semantics-on/off fallback.

Exit criteria:

- A process restart does not leave an unrecoverable device lease.
- Backend timeouts never block the application event loop indefinitely.
- Input method and temporary device settings are restored after normal and abnormal
  session termination.
- Contract fixtures round-trip across supported minor versions.
- Every reference app installs from CI and exposes its declared fault switches.

## Milestone 2: scene, fusion, identity, extraction

**Goal:** produce useful, evidence-backed semantic scenes and typed records.

Deliverables:

- Raw hierarchy parser and canonical accessibility-node normalization.
- Screenshot/OCR/vision adapters and fallback policy.
- Fusion with per-property provenance and ranking confidence.
- Scene quality metrics and deterministic digest.
- Adjacent-frame identity tracker with session-scoped stable IDs.
- Extraction engine: single, ancestry, repeat, and rows grouping; on-demand scene
  enrichment; field binding; parsers; dedupe; scroll budgets; relocatable record
  anchors; ambiguity reporting; image crops.
- Labelled fusion, tracking, and extraction fixtures including RTL, Compose,
  WebView, Flutter, dialogs, scrolling, keyboard transitions, and checkout rows.

Exit criteria:

- Every synthesized property identifies its evidence source.
- Raw evidence is immutable and can reconstruct the scene deterministically.
- Tracking and extraction meet the gates in `05-quality-security.md`.
- Missing perception sources degrade explicitly rather than returning fabricated
  certainty.
- No extracted field value exists without an element in evidence.

## Milestone 3: resolver, actions, verification, and core authoring

**Goal:** complete a deterministic observe-resolve-act-verify loop that a skill
author can use and a benchmark can measure.

Deliverables:

- Semantic selector evaluator and ranked candidate diagnostics.
- Stale-target re-resolution and ambiguity thresholds.
- Action validation, dispatch receipts, explicit retry policy, idempotency keys,
  and the no-transparent-retry irreversible path proven in M0.
- Unicode text strategies with input-method restoration and strategy recorded in
  receipts.
- Expectation evaluator with boolean composition, `state_equals`, `value_equals`.
- Scene settling based on bounded polling and fingerprints.
- Primitive HTTP endpoints, SSE stream, Python client, and MCP adapter.
- Core authoring tools: `haykal scene`, `haykal resolve --dry-run`,
  `haykal extract --dry-run`, `haykal lint`, and `haykal replay` as specified in
  [08-skill-authoring.md](08-skill-authoring.md).
- Two-track benchmark harness with required Haykal and Agent Device adapters.
  Maestro MCP and ARTEMIS adapters are included only if M0 records pinned runnable
  configurations; otherwise their omission and reason are published.

Exit criteria:

- Resolver returns ambiguity instead of selecting below the configured margin.
- Every action links pre-scene, target evidence, backend receipt, post-scene, and
  verification.
- Unknown outcomes are distinguishable from safe failures.
- Primitive reliability and latency gates pass.
- An engineer who did not build Haykal authors the offers skill against Matjar in
  one working day using only the tools and `08`.
- The benchmark harness runs every validated pinned system on both applicable
  tracks and produces the report format in `07`.

## Milestone 4: durable skills, escalation, gates, reconciliation

**Goal:** run known workflows without a model and safely delegate unknown states.

Deliverables:

- Skill schema, validator, signed content-addressed registry, publisher trust
  policy, and immutable version loading.
- Guarded state-machine interpreter with extract and select steps.
- Declarative selection policy evaluator with documented tie-break.
- SQLite run journal and crash-safe resume.
- Structured escalation events and bounded decision responses, including
  candidate selection.
- Suspended state and resume after decision expiry.
- Candidate-patch records without automatic promotion.
- Risk classification and approval-gate service.
- Material summary produced by declared extraction and bound to the approval.
- One-time approval validation bound to skill, action intent, target fingerprint,
  and conservative material digest, using a separate approval principal.
- Pre-submit re-observe and re-extract; stale approval on material change.
- Reconciliation path through the Orders screen for `outcome_unknown`.
- Two reference skills on Matjar: read-only offers and prepare-order-to-gate.
- Two compatibility skills on an authorized regional app, run and reported
  separately.

Exit criteria:

- Happy-path skill execution uses no model call.
- An unknown screen pauses without losing the device/run state.
- Restart/resume does not repeat a committed action.
- Stale or reused approval tokens are rejected.
- Fault injection cannot produce a second wire-level gated-action dispatch.
- Every acceptance scenario in both lifecycle examples passes on Matjar.

## Milestone 5: hardening and release evidence

**Goal:** make the MVP installable, diagnosable, and supportable.

Deliverables:

- Diagnostics command and health endpoint.
- Recorder-to-draft polish is included only if core release gates are already
  green; otherwise it moves to the launch package without blocking the MVP.
- Static trace report sufficient for debugging without database access.
- Redaction and retention configuration including image-region redaction.
- Clean-machine installation, upgrade, backup, and recovery documentation.
- Load, soak, chaos, and security test runs with saved reports.
- SBOM and license report.
- Final comparative benchmark run and published report.
- Versioned sample skills and integration examples.
- Known-limitations document.

Exit criteria:

- A clean reference VM passes installation and end-to-end acceptance tests.
- Eight-hour soak and failure-injection gates pass.
- Threat-model findings rated critical or high are resolved or explicitly block
  release.
- Benchmark report reproduces within stated variance from the shipped harness.

## Milestone 6: Maestro importer (conditional)

Scheduled only when a design partner has Maestro assets they need to keep.

- Strict importer for `tapOn`, `inputText`, `back`, `swipe`, `assertVisible`,
  `assertNotVisible`, `waitUntil`, `launchApp`.
- Source maps from imported actions to YAML file and line.
- Unsupported commands fail import with actionable errors.

## Repository sequence

```text
1. text/ parsers + labelled fixtures                 (M0)
2. contracts + selectors + fixtures                  (M1)
3. device backend + leases                           (M1)
4. refapps/                                          (M1, parallel)
5. artifacts + traces                                (M1)
6. perception + scenes + extraction                  (M2)
7. resolver + verification                           (M3)
8. HTTP/SSE + SDK + MCP                              (M3)
9. authoring tools + benchmark harness               (M3)
10. skill engine + journal + selection policies      (M4)
11. escalation + approvals + reconciliation          (M4)
12. hardening, benchmark report, release evidence    (M5)
```

## MVP completion artifacts

- Package and locked dependency manifest with hashes.
- Generated JSON Schemas.
- Reference VM setup instructions.
- Reference application suite with fault-switch documentation.
- Component and workflow benchmark dataset manifests and results.
- Comparative benchmark report with methodology and raw data.
- Threat model and dependency/license report.
- Trace examples with redacted artifacts.
- At least one primitive-caller integration.
- Two deterministic Arabic/RTL skills on Matjar and two compatibility runs on an
  authorized regional app.
- Authoring guide with the one-day exercise and its timing record.
- Known-limitations document.
