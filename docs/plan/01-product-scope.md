# Product scope

## Problem

Mobile agents currently choose between low-level automation tools and complete
model-driven agents. Low-level tools expose coordinates or raw accessibility trees
without stable semantic identity or evidence. Complete agents repeatedly spend
model time rediscovering known paths and make verification and safety policy hard
to control.

Haykal provides a deterministic middle layer:

```text
caller intent
    -> semantic scene
    -> deterministic resolution or extraction
    -> device action
    -> declared verification
    -> evidence and trace
```

Known paths compile into reusable skills. Unknown states are escalated to an
external agent or human without surrendering execution, safety, or trace control.

## Initial users

### Agent developers

They need reliable phone primitives without adopting another agent's reasoning
loop. They call Haykal through MCP, HTTP, or the Python SDK. Their integration is
four primitives and a versioned event stream; callers subscribe only to the event
types they need.

### Teams operating regional Android workflows

They need repeatable Arabic/RTL workflows, local deployment, explicit approvals,
and traces that can be audited without sending screenshots to a third-party cloud.

### Skill authors

They write and harden supported flows, investigate escalations, and promote
candidate patches after regression evaluation. They work with the authoring
tools described in [08-skill-authoring.md](08-skill-authoring.md), not with raw
hierarchies.

## Stable MVP use cases

1. Observe a screen and receive a normalized scene with accessibility, OCR, and
   vision provenance.
2. Extract typed records (cards, rows, totals, badges) from the current scene
   with per-field evidence and no inferred values.
3. Resolve and execute a semantic tap, swipe, key press, or text-entry action.
4. Verify visible/non-visible elements, text, attributes, foreground application,
   and bounded scene transitions.
5. Run a versioned skill with typed parameters and a declarative selection policy.
6. Pause a skill when the current state is ambiguous or unknown.
7. Resume it after an external caller supplies one bounded decision.
8. Stop at a risk gate, present reconciled material details, and accept or reject
   an authorized approval.
9. Inspect or export a redacted trace containing observations, extractions,
   decisions, actions, verification results, timing, and artifacts.
10. Author the bounded Matjar offers skill in one working day using the scene
    inspector, extraction/selector dry-run, fixtures, replay, and lint.
11. Reproduce the comparative benchmark against Maestro MCP, ARTEMIS, and Agent
    Device from a documented harness.

## Functional requirements

### Runtime sessions

- Create, inspect, cancel, and close a device session.
- Hold an exclusive device lease with heartbeat and stale-lease recovery.
- Detect device disconnects and UIAutomator2 process failure.
- Recover the backend once when safe; otherwise pause the run with a typed reason.
- Preserve run state across a Haykal process restart.
- Bound suspended device leases with a deployment-configured hold TTL. At expiry,
  persist a resumable checkpoint and release the device unless it is dedicated.

### Observation and scene construction

- Capture hierarchy and screenshot with independent timestamps and measured skew.
- Record display size, density, rotation, foreground package, keyboard state, and
  capture backend.
- Normalize accessibility nodes without mutating the raw evidence.
- Add OCR and vision candidates according to fallback policy.
- Permit an extraction to request missing perception sources. Enrichment produces
  a new immutable scene revision and records why each additional source ran.
- Fuse candidates with per-property source and confidence.
- Assign frame-local IDs and track logical elements across adjacent frames.
- Produce a deterministic scene digest.

### Extraction

- Group scene elements into records using a declared grouping rule (ancestry,
  repeated structure, or spatial rows).
- Bind declared fields to elements inside each record by selector.
- Parse values into typed forms: text, number, money, rating, duration, boolean.
- Accept Arabic-Indic, Extended Arabic-Indic, and Latin digits; record which was
  seen.
- Return `null` for a field whose evidence is absent. Never infer, interpolate, or
  copy from a neighbouring record.
- Carry evidence for every non-null field: scene ID, element IDs, and sources.
- Support bounded scrolling with stable-fingerprint settling and deduplication by
  declared signature.
- Return a relocatable record anchor containing a semantic fingerprint and scroll
  checkpoint; reveal and re-resolve it before an action if it is off screen.
- Report `request_satisfied`, `source_exhausted`, and `truncated` independently;
  always include a stop reason.

### Resolution and execution

- Resolve by element ID plus scene revision, semantic name, role, label, text,
  resource ID, state flags, containment, proximity, or constrained combinations
  from the documented vocabulary.
- Return `ambiguous_target` rather than guessing below the confidence margin.
- Re-observe and re-resolve stale targets before acting.
- Validate coordinates against current display geometry.
- Return an action receipt even when execution fails.
- Make action retries explicit and safe; do not blindly retry potentially
  irreversible actions.

### Verification

- Support `all`, `any`, and `not` composition.
- Evaluate predicates against newly captured scenes.
- Poll until success or a bounded timeout using scene fingerprints for settling.
- Return the evidence used for every predicate.
- Require explicit postconditions in skills. Primitive callers may omit them.

### Skills

- Load immutable, version-addressed skill definitions.
- Validate input types, constraints, element dictionary, and selector vocabulary
  before acquiring a device.
- Select a transition only when its guard is unambiguous.
- Evaluate declarative selection policies with a documented stable sort.
- Persist the current state and transition journal before and after each action.
- Pause on escalation or approval; resume idempotently.
- Never mutate the active skill definition during a run.
- Load only immutable, content-addressed skill packages signed by a trusted
  publisher. Deployment policy independently classifies action risk and never
  trusts a skill's self-declared category as authority.

### Authoring

- Dump the current scene as a readable table and as JSON.
- Dry-run a selector against a live or recorded scene and show ranked candidates
  with scores and the ambiguity margin.
- Capture a manual walk-through as versioned scene fixtures. Recorder-generated
  draft skills are launch-package scope, not a core release dependency.
- Lint a skill: unknown selector fields, undefined semantic names, unreachable
  states, missing expectations, ungated irreversible actions, unparsable inputs.
- Replay a skill against recorded scenes without a device.

### Traces

- Assign a run ID, trace ID, observation revision, and action ID.
- Store structured events separately from large artifacts.
- Link every action to pre-action scene, resolved target, post-action scene, and
  expectation result.
- Link every extraction to the scenes and elements it read.
- Redact configured text fields and screenshots before external export.
- Export a portable JSON Lines trace plus referenced artifacts.

## Release definition

The MVP is releasable when:

- The canonical contracts are versioned and have compatibility tests.
- A supported skill can survive process restart, device reconnect, escalation,
  and approval without repeating a Haykal dispatch; uncertain irreversible
  effects enter reconciliation and are never automatically dispatched again.
- Arabic and mixed-direction text tests pass on the declared device/app matrix.
- Extraction and money-parsing gates pass on the labelled component suite.
- Failure injection demonstrates no duplicate gated action.
- Reliability, latency, and soak-test gates in
  [05-quality-security.md](05-quality-security.md) pass.
- The comparative benchmark report in
  [07-reference-apps-and-benchmarks.md](07-reference-apps-and-benchmarks.md) is
  reproduced from the shipped harness and published with the release.
- A new skill author completes the authoring exercise in
  [08-skill-authoring.md](08-skill-authoring.md) within one working day.
- Installation, upgrade, recovery, backup, and trace-redaction procedures are
  documented and exercised from a clean VM.
