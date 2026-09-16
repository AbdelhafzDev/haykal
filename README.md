# Haykal

> Working codename. `Haykal` (`هيكل`) means structure. The name has not received
> trademark or domain clearance and must not be treated as the final brand.

Haykal is an Android mobile skill runtime. It converts accessibility data,
screenshots, OCR, and vision detections into a versioned semantic scene; extracts
typed records with evidence; resolves semantic actions against that scene;
executes them through a device backend; and returns verification evidence and a
durable trace.

The stable MVP is intentionally narrow:

- Android emulators and controlled Android VMs only.
- Python `uiautomator2` as the sole shipped action and hierarchy backend.
- Accessibility-first perception with OCR and swappable vision fallback.
- Four primitives: `observe`, `extract`, `act`, `verify`.
- A canonical scene, selector, action, extraction, expectation, result, and trace
  contract, with a versioned Arabic-aware normalizer and money parser.
- Deterministic, parameterized skills with declarative selection policies.
- Pause/resume escalation and approval gates whose material summary comes from
  extraction, never from prose.
- At-most-once dispatch for irreversible actions, mandatory reconciliation when
  their outcome is uncertain, and an effectively-once result only when evidence
  proves whether the external effect occurred.
- A focused reference application suite and two-track published benchmark.
- Authoring tools validated by a one-day reference-skill exercise.
- Local/private deployment; no managed device cloud.

The product is the semantic runtime above the device backend. UIAutomator2,
OmniParser-compatible models, MCP, and imported Maestro flows are adapters, not
the public identity of the system.

Start with the [MVP plan](docs/plan/README.md). The written plan currently scores
[95/100](docs/plan/09-readiness-scorecard.md); the remaining five points require
Milestone 0 evidence and cannot be earned by documentation alone.
The post-Phase-5 implementation review started stable-MVP readiness at 70/100.
The P95.4 review reduced the defensible implementation score to **85/100** after
finding release-boundary defects in record relocation, stale rebinding, build
provenance, and acceptance assertions. Focused P95.4R remediation targets release
`0.0.3`; its implementation is complete but its new clean API 34/35 evidence and
hosted fresh-checkout run are still pending. The release decision remains no-go.
Follow the phased
[Path to 95](docs/plan/10-path-to-95.md), the
[P95.1 safety/privacy record](docs/p95-1-status.md), the
[P95.2 reliability/readiness record](docs/p95-2-status.md), and the
[P95.3 benchmark record](docs/p95-3-status.md). P95.4 shipped-wheel acceptance is
implemented but does not earn its forecast score until the clean API 34/35
matrix passes; see the [P95.4 status](docs/p95-4-status.md) and
[P95.4R remediation status](docs/p95-4r-status.md), plus the
[runbook](docs/p95-4-runbook.md). This implementation score is
separate from the written-plan score.

Implementation has started. See the [Milestone 0 runbook](docs/m0-runbook.md).
The Phase 1 contract/device/reference-app implementation is locally accepted; see
the [Phase 1 status](docs/phase1-status.md). The Phase 2 scene, fusion, identity,
selector, and extraction implementation is locally integrated; see the
[Phase 2 status](docs/phase2-status.md) for evidence and the labelled/model gates
that remain before release acceptance.
The Phase 3 deterministic action loop, transports, authoring tools, and benchmark
harness are locally integrated; see [Phase 3 status](docs/phase3-status.md) for the
live trace and the reliability, latency, authoring, and comparative gates that
remain blocking.
Use the [Phase 3 runbook](docs/phase3-runbook.md) for CLI, HTTP/SSE, Python/MCP,
live-device, and comparative-harness commands.
The Phase 4 signed skill engine, journal, bounded escalation, content-bound
approval, and Matjar reconciliation path are locally integrated; see the
[Phase 4 status](docs/phase4-status.md) and [Phase 4 runbook](docs/phase4-runbook.md).
Phase 5 operational hardening is implemented for local evidence collection; see
the [Phase 5 status](docs/phase5-status.md), [Phase 5 runbook](docs/phase5-runbook.md),
[operations guide](docs/operations.md), [threat model](docs/threat-model.md), and
[known limitations](docs/known-limitations.md). Elapsed-time, external competitor,
regional-app, and non-core-author gates remain evidence blockers rather than
being replaced with synthetic results.
