# Phase 5 implementation status

Phase 5 hardening mechanisms are implemented locally. Release evidence that
requires elapsed time, a clean hosted Android matrix, external competitors,
regional-app authorization, or a non-core author is not claimed until that run
exists.

## Post-review correction

The 2026-09-13 release review scored the implemented stable MVP at **70/100** and
kept the release decision at **no-go**. It found two release-critical defects:
caller-controlled risk can bypass the independent approval floor, and an image
whose artifact has no matching redaction region can be exported unchanged. It
also found that the current soak, benchmark, readiness, and wheel-install checks
do not yet prove their stated release properties.

Remediation is split into P95.0 through P95.5 in
[`plan/10-path-to-95.md`](plan/10-path-to-95.md). The review overrides older
"passed locally" wording where the relevant assertion was narrower than the
release criterion.

## Implemented

- Minimal unauthenticated `/healthz`, authenticated `/v1/diagnostics`, and the
  `haykal diagnostics` command.
- Default-redacted HTTP, SSE, MCP/runtime trace reads and a database-independent
  static HTML/JSON trace exporter.
- Recursive key/literal/email/phone/card redaction, private-by-default images,
  and explicit image pixel-region redaction.
- Preview-first trace/artifact retention with separate bounded ages.
- Online SQLite backup, content/skill inclusion, digest manifest, atomic archive
  publication, safe extraction, integrity verification, and empty-target restore.
- CycloneDX 1.6 SBOM and Markdown dependency-license generation from the locked
  installed environment.
- Bounded concurrent storage load/soak/chaos harness with latency, failures,
  integrity, memory, state-size, and honest eight-hour eligibility fields.
- Clean-wheel installation check and Android API 34/35 reference acceptance jobs.
- Expanded comparative report layout with per-run logs, preserved configs/tasks,
  methodology, track-safe summaries, and immutable output destination.
- Versioned Matjar skills plus Python step-caller, HTTP skill/approval, and MCP
  configuration examples.
- Operations, recovery, threat-model, limitations, and Phase 5 runbooks.
- Recorder polish explicitly deferred because the core release gates are not all
  green.

## Latest local evidence

- Host gate: 483 tests passed with 85.28% coverage; Ruff, strict mypy over 95
  source files, 21 schema generation, package build, and Actionlint passed.
- A newly created Python 3.13 virtual environment installed the built wheel and
  executed the diagnostics command successfully.
- Android API 37: both Matjar lifecycle scenarios passed; a redacted static trace
  was exported, live state was backed up and restored, and restored diagnostics
  passed.
- Bounded storage smoke: 2,688 successful operations, 166 injected interruptions,
  zero unexpected failures, and zero artifact-integrity failures. Its one-second
  duration makes it ineligible for the eight-hour gate.

## Release-gate status

| Criterion | Status | Evidence or blocker |
| --- | --- | --- |
| Repository/host provenance | blocking | repository tree is not yet committed; hosted CI and reviewable commit provenance are absent |
| Host release and clean-wheel gate | partial, blocking | host tests and isolated installation pass, but the installed wheel has not run the Android E2E lifecycle |
| Clean API 34/35 reference VMs | configured, not observed | API 37 local VM passed; hosted matrix has not run because this repository has no remote/commit |
| Static trace usable without DB | passed locally | exporter tests and API 37 live trace export |
| Redaction and retention | failed, blocking | artifact-specific image regions can leave another exported image completely unredacted; retention lacks reachability |
| Backup and recovery | passed locally | tests plus API 37 live-state backup/restore/diagnostics |
| Effective risk/approval floor | failed, blocking | primitive callers control risk; skill actions are not reclassified from resolved target context |
| Device readiness | failed, blocking | health checks storage only and can return ready without a usable authorized device |
| Load/chaos harness | partial, blocking | the smoke exercises storage concurrency, but interruption counters do not inject process, database, backend, ADB, lease, or device failures |
| Eight-hour device soak | not run, blocking | requires 28,800 uninterrupted seconds on the release VM |
| Critical/high threat findings | failed, blocking | effective-risk and image-export findings must close in P95.1 before release evidence continues |
| Comparative benchmark | failed design plus external blocker | results are adapter-reported rather than independently read from Matjar; no pinned runnable Agent Device adapter is supplied |
| Authorized regional compatibility | blocked externally | no app build/account/OTP/test authorization supplied |
| Non-core author exercise | blocked externally | requires a human participant outside the core implementation |

The code is ready for Phase 5 evidence collection, but the stable MVP is not yet
release-certified. A short smoke run, illustrative Jahez document, or synthetic
competitor result must not be used to turn a blocked row green.
