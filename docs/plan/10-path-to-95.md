# Path to 95 execution program

This program converts the post-Phase-5 review into release work. It scores the
implemented stable MVP, not the quality of the written plan. The starting score
is **70/100** and the release decision is **no-go** until every safety-critical
gate in P95.1 is green.

## Operating rules

- Work is sequential unless a phase explicitly says otherwise.
- Every defect starts with a regression test that fails for the reviewed reason.
- A phase is complete only when its code, tests, evidence report, and status
  documentation agree.
- Unit tests cannot satisfy a gate that requires a device, elapsed time, an
  external system, or a non-core participant.
- Caller, skill, screen, adapter output, archive, and restored state remain
  untrusted at their respective boundaries.
- Safety gates are binary. A downgraded-risk dispatch, unredacted export, repeated
  irreversible action, or self-scored benchmark blocks release.
- Build once and promote the same wheel digest through clean-machine acceptance.
- Each completed phase receives a dedicated commit. Release evidence records the
  commit, wheel, VM image, reference-app, model, and configuration digests.

## Sequence and score trajectory

| Phase | Outcome | Items covered | Expected score after evidence | Active effort |
| --- | --- | --- | ---: | ---: |
| P95.0 | Reproducible baseline and red tests | 7, prerequisites for all | 72 | 0.5–1 day |
| P95.1 | Trusted safety and privacy boundary | 1, 2 | 80 | 2–4 days |
| P95.2 | Real reliability and device readiness | 3, 6 | 85 | 4–7 days |
| P95.3 | Independently scored, pinned benchmark | 4 | 88 | 3–5 days |
| P95.4 | Wheel-only clean Android acceptance | 5, remainder of 7 | 91 | 2–4 days |
| P95.5 | External and elapsed-time proof | 8 | 95 | 3–5 active days plus access and soak time |

Scores are forecasts, not automatic awards. A phase that misses an exit criterion
does not advance the score.

## P95.0: baseline, provenance, and regression locks

**Goal:** make every later change reviewable and turn the review findings into
executable failing specifications.

Work:

1. Inventory generated, host-derived, secret-bearing, and source files; confirm
   `.gitignore` keeps device and trace evidence out of source control.
2. Run a local secret scan and remove or rotate any discovered credential before
   the baseline commit.
3. Commit the current tree as a clearly named pre-hardening baseline. It is not a
   release tag and must retain the no-go status.
4. Add hosted CI for formatting, lint, strict typing, schemas, tests with coverage,
   build, clean wheel installation, dependency audit, and workflow lint.
5. Add failing regression tests for:
   - HTTP and MCP callers declaring a coordinate or payment target as navigation;
   - a harmless selector name resolving to a payment-labelled element;
   - an image export whose only redaction region belongs to another artifact;
   - readiness with no authorized device;
   - benchmark output that claims success while the Matjar oracle disagrees.

Evidence:

- Baseline commit SHA and clean `git status`.
- Hosted CI URL/run identifier for the baseline gates.
- A review report listing each red test and the defect it locks.

Exit criteria:

- Every project file is tracked or deliberately ignored.
- No credential is present in tracked history or generated evidence.
- Each critical/high review finding has a regression test that fails before its
  implementation fix.
- CI runs from a fresh checkout rather than the developer's environment.

During P95.0 these regression tests are committed as strict expected failures,
with issue/phase reasons. An unexpected pass fails CI; the owning remediation
phase removes the marker and keeps the test as a normal permanent regression.

## P95.1: effective risk and fail-closed privacy

**Goal:** establish one runtime-controlled policy boundary for every caller and
prevent any artifact export when redaction coverage is incomplete.

### Effective risk

1. Move effective risk computation to the runtime action boundary used by Python,
   HTTP, MCP, recovery decisions, and skills.
2. Resolve the target first, then classify using action kind, coordinates, caller
   declaration, selector semantics, and resolved element label/text/resource ID.
3. Compute `effective_risk = max(caller_declared, skill_declared, inferred)` using
   the deployment policy. A caller can raise risk but cannot lower it.
4. Treat coordinates and unclassifiable actions as `unknown`.
5. Require a runtime-created challenge for every non-navigation effective risk.
   A boolean `approved` flag is not public authority.
6. Apply the no-transparent-retry/single-shot path to every effective irreversible
   or unknown action.
7. Record declared, inferred, effective, and policy-decision values in the trace
   without including secrets.

### Image and trace privacy

1. When images are enabled, require either a wildcard redaction region or at least
   one region matching every exported artifact.
2. Reject the entire export when any image lacks coverage; never silently export
   an unchanged image.
3. Validate region bounds against the decoded image and reject invalid or empty
   coverage.
4. Add mixed-artifact, malformed-image, wildcard, out-of-bounds, and no-match
   tests. Include Arabic names and addresses under generic evidence keys in the
   text-redaction corpus.
5. Mark stored raw trace envelopes as raw; apply `redaction.applied=true` only to
   the actual public/exported representation.

Evidence:

- Security regression report covering all transports and skill execution.
- Property/fuzz tests showing risk cannot decrease across the boundary.
- Trace-export corpus report showing zero unredacted secrets or uncovered images.
- Updated threat model with the reviewed critical/high rows closed by evidence.

Exit criteria:

- The reviewed downgrade payload is rejected or converted into an approval
  challenge before dispatch.
- A resolved payment label overrides a harmless caller/skill semantic name.
- An approved irreversible/unknown action reaches only the single-shot backend.
- An artifact with no matching image rule makes export fail closed.
- No critical or high safety/privacy finding remains marked resolved solely by a
  unit-test count.

## P95.2: fault injection, bounded growth, and readiness

**Goal:** prove recovery from real failures and make readiness mean that Haykal can
actually accept work on its leased device.

### Reliability harness

Replace skipped iterations with independently controlled fault scenarios:

| Fault | Injection point | Required observation |
| --- | --- | --- |
| Runtime process kill | prepared, dispatched, pre-commit, post-commit | restart reconciles without duplicate dispatch |
| SQLite interruption | journal and trace transactions | database remains valid or fails explicitly |
| Artifact corruption/truncation | after put, before get/export | digest read detects corruption |
| UIAutomator2 agent death | observe and reversible action | bounded restart and lease retained or safely released |
| ADB disconnect/reconnect | observe, action, settle | typed unavailable/unknown outcome; no unsafe retry |
| Lease expiry/process death | active session | next owner recovers without concurrent control |
| Settings/IME interruption | during Arabic input | cleanup restores the prior device state |
| Disk-full/low-space | trace and artifact write | fail before unsafe dispatch or report outcome honestly |

Use a supervisor outside the tested process to inject faults and verify the
result. Read artifacts through `ArtifactStore.get`, not filename existence. Track
RSS, file count, artifact bytes, SQLite bytes, open descriptors, operation
latency, and recovery time as time series. Define explicit absolute limits and
growth-slope limits before running the gate.

### Health model

- `/livez`: process/event-loop liveness only.
- `/healthz`: minimal aggregate service health for compatibility.
- `/readyz`: state access, database integrity, disk threshold, ADB availability,
  authorized target, lease state, UIAutomator2/helper health, and pending recovery.
- Return 503 for degraded or unhealthy readiness. Never report ready when device
  diagnostics are absent.
- Keep detailed serials, paths, and recovery data behind authenticated
  diagnostics.

Evidence:

- Fault-matrix report with injection timestamps and independent observations.
- Thirty-minute development soak with bounded-growth graphs.
- Readiness transition tests covering disconnect, reconnect, agent death, lease
  loss, disk pressure, and recovery.

Exit criteria:

- Every fault row has a deterministic automated test and saved report.
- No injected fault creates duplicate irreversible dispatch.
- Artifact corruption is detected by content verification.
- No deadlock, leaked lease, unrecovered setting, or positive unbounded-growth
  slope remains after the stabilization window.
- The service returns not-ready whenever its configured device cannot accept work.

## P95.3: independent benchmark and cryptographic pinning

**Goal:** ensure no compared system, including Haykal, can award itself success or
hide an unsafe action.

Work:

1. Add a benchmark controller that resets Matjar, records the pre-state, runs the
   adapter, and reads the post-state through a separate oracle channel.
2. Evaluate each task's `success_check` centrally from Matjar state. Treat adapter
   `success` and `unsafe_actions` as diagnostic claims only.
3. Count sensitive/unsafe external effects independently from Matjar counters and
   the device event log.
4. Require SHA-256 or immutable repository/container identifiers for adapter code,
   model, prompt, reference APK, VM image, and configuration.
5. Verify that the executable being launched matches the recorded digest.
6. Pass secrets through environment/file descriptors or a secret provider; redact
   them from copied configs, command lines, logs, and reports.
7. Run all systems from identical clean snapshots with randomized system order and
   at least 30 runs per task. Preserve failures and timeouts as results.

Evidence:

- Oracle unit and adversarial adapter tests, including a lying adapter.
- Signed/digested benchmark manifest and immutable raw result directory.
- Reproduction script that rebuilds the summary exclusively from raw oracle data.

Exit criteria:

- A lying adapter cannot change success or safety scores.
- Missing or mismatched digests prevent the run.
- Secret canaries do not appear in any published artifact.
- Recomputing from raw results produces the same summary digest.

P95.3 may implement and validate Haykal plus a deliberately adversarial local
adapter. The real Agent Device comparison remains P95.5 external evidence.

## P95.4: build-once wheel-only clean Android matrix

**Goal:** prove that the distributable artifact—not the source checkout—runs the
complete product lifecycle on supported clean VMs.

Work:

1. Build one wheel, record its digest, and prevent later matrix jobs from
   rebuilding it.
2. Create clean, reproducibly identified API 34 and API 35 VM snapshots.
3. Start each acceptance job outside the repository or with the source tree
   unavailable on `PYTHONPATH`.
4. Install only the promoted wheel and declared runtime dependencies.
5. Install Matjar and execute both lifecycle skills, primitive HTTP/MCP smoke,
   approval, stale approval, submit-timeout reconciliation, Arabic input,
   static trace export, retention preview, backup, restore, and device-aware
   readiness transitions.
6. Upgrade from the previous package version and verify state/schema migration.
7. Save reports, logs, package lists, device properties, APK digest, VM identity,
   and the exact wheel digest.

Evidence:

- Green API 34 and API 35 hosted CI runs from a clean checkout.
- Wheel-only command provenance demonstrating no `uv run` against source.
- Acceptance manifest tying both runs to the same wheel digest.

Exit criteria:

- Both API levels pass the entire acceptance suite with the exact same wheel.
- No source checkout is imported or executed by the acceptance runtime.
- Upgrade, backup, restore, and readiness recovery pass from clean snapshots.
- Repository status is clean and the release candidate commit is immutable.

## P95.5: release evidence and external validation

**Goal:** earn the final four points with elapsed-time and independent evidence
that cannot be manufactured locally.

Work and gates:

1. Run the real eight-hour device soak on the release wheel and clean reference
   VM with the P95.2 fault schedule. Zero duplicate irreversible dispatches,
   deadlocks, leaked leases, unrecovered settings, integrity failures, or breached
   resource-growth limits are allowed.
2. Pin and run Agent Device using the P95.3 controller. Add Maestro MCP or ARTEMIS
   only when an exact reproducible configuration exists; document honest omissions
   and losses.
3. Run two authorized regional-app workflows using dedicated test accounts and
   written scope. Never place a real purchase or handle production payment data.
4. Have a non-core engineer complete the bounded Matjar authoring exercise. Record
   elapsed time, questions, tool defects, resulting skill digest, and 30 clean
   replay results.
5. Close the OCR/vision commercial-license and Arabic-labelled accuracy decision
   with model/weight digests.

Evidence:

- Eight-hour signed soak/fault report.
- Published comparative report and raw oracle results.
- Redacted regional compatibility reports with authorization references.
- Non-core authoring report and replay artifacts.
- OCR/vision selection ADR and license inventory.

Exit criteria:

- Every Phase 5 release row is green or explicitly unsupported before any unsafe
  action; no unresolved critical/high issue is waived.
- All external evidence references the P95.4 wheel and release-candidate commit.
- A fresh reviewer can reproduce the benchmark summary and verify evidence
  digests without access to the development machine.
- The implementation scorecard reaches at least 95/100 without counting prose,
  mocks, short smokes, or illustrative Jahez documents as release evidence.

## Phase status template

Each P95 phase status document must contain:

```text
Decision: blocked | in_progress | passed
Commit: <sha>
Wheel: sha256:<digest> | not_applicable
Environment: <host/VM image/API>
Commands: <exact commands or workflow URL>
Tests: <counts and named gates>
Evidence: <paths and digests>
Open findings: <severity, owner, next action>
Score after evidence: <n>/100
```

The final release score is recalculated after P95.5. Forecast values in this
document never replace measured evidence.
