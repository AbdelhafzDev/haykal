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

- Distinct unauthenticated `/livez`, `/healthz`, and device-aware `/readyz`, plus
  authenticated `/v1/diagnostics` and the `haykal diagnostics` command.
- Default-redacted HTTP, SSE, MCP/runtime trace reads and a database-independent
  static HTML/JSON trace exporter.
- Recursive key/literal/email/phone/card redaction, private-by-default images,
  and explicit image pixel-region redaction.
- Preview-first trace/artifact retention with separate bounded ages.
- Online SQLite backup, content/skill inclusion, digest manifest, atomic archive
  publication, safe extraction, integrity verification, and empty-target restore.
- CycloneDX 1.6 SBOM and Markdown dependency-license generation from the locked
  installed environment.
- Externally supervised process/SQLite/artifact/lease/settings/disk fault matrix,
  live UIAutomator2/ADB/IME recovery checks, and a bounded soak with real injected
  faults, latency/resource time series, growth limits, and honest 30-minute and
  eight-hour eligibility fields.
- Clean-wheel installation check and Android API 34/35 reference acceptance jobs.
- Expanded comparative report layout with per-run logs, preserved configs/tasks,
  methodology, track-safe summaries, and immutable output destination.
- Versioned Matjar skills plus Python step-caller, HTTP skill/approval, and MCP
  configuration examples.
- Operations, recovery, threat-model, limitations, and Phase 5 runbooks.
- Recorder polish explicitly deferred because the core release gates are not all
  green.

## Latest local evidence

- Host gate after P95.3: 520 tests passed with 84.56% coverage; Ruff, strict mypy
  over 100 source files, 21 schemas, package build, clean wheel installation,
  secret scan, dependency audit, and Actionlint passed. All seven P95 regressions
  are permanent passing tests with no remaining xfail locks.
- A clean API 37 device run passed all 12 process/storage/device fault rows and
  the connected/absent readiness transition. Both prior Matjar lifecycle
  scenarios, static trace export, backup, and restore also passed on API 37.
- The 30-minute storage profile completed 2,747,317 operations with 74,250
  injected and detected faults, zero unexpected/integrity failures, 6.48 ms p95,
  84.4 MB peak RSS, and non-positive stabilized state/RSS slopes. Its P95.2
  eligibility flag is true; the separate eight-hour P95.5 flag remains false.

## Release-gate status

| Criterion | Status | Evidence or blocker |
| --- | --- | --- |
| Repository/host provenance | partial, blocking | local phase commits and clean-tree evidence exist; hosted CI is absent because no remote is configured |
| Host release and clean-wheel gate | partial, blocking | host tests and isolated installation pass, but the installed wheel has not run the Android E2E lifecycle |
| Clean API 34/35 reference VMs | configured, not observed | API 37 local VM passed; hosted matrix has not run because this repository has no remote/commit |
| Static trace usable without DB | passed locally | exporter tests and API 37 live trace export |
| Redaction and retention | privacy defect fixed locally; later evidence remains | P95.1 aborts the whole image export for absent, mismatched, malformed, or out-of-bounds coverage; retention reachability is still outside this phase |
| Backup and recovery | passed locally | tests plus API 37 live-state backup/restore/diagnostics |
| Effective risk/approval floor | passed locally | P95.1 reclassifies resolved targets for Python, HTTP, MCP, recovery, and skills; bound permits and single-shot dispatch are permanent regressions and passed on API 37 Matjar |
| Device readiness | passed locally | missing/unauthorized targets, helper death, expired lease, pending recovery, and disk pressure fail readiness; live connected/absent API 37 transitions passed |
| Fault injection and bounded growth | passed for P95.2 locally | 12-row host/device matrix passed and the 30-minute real-fault soak stayed within declared resource/growth limits |
| Eight-hour device soak | not run, blocking | requires 28,800 uninterrupted seconds on the release VM |
| Critical/high threat findings | P95.1 findings closed locally | downgrade and image-export defects are closed by adversarial, property, corpus, and live Matjar evidence; later phase blockers keep the overall release no-go |
| Comparative benchmark | controller passed locally; external comparison blocked | P95.3 scores independent pre/post oracle state, enforces full SHA-256 pins, seals raw evidence, and defeats a lying local adapter over 30 runs; no real pinned Agent Device run is claimed until P95.5 |
| Authorized regional compatibility | blocked externally | no app build/account/OTP/test authorization supplied |
| Non-core author exercise | blocked externally | requires a human participant outside the core implementation |

The code is ready for Phase 5 evidence collection, but the stable MVP is not yet
release-certified. A short smoke run, illustrative Jahez document, or synthetic
competitor result must not be used to turn a blocked row green.
