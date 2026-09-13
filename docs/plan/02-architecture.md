# Architecture

## System view

```text
                     Northbound adapters
          MCP            HTTP + SSE          Python SDK
           |               |                   |
           +---------------+-------------------+
                           |
                    Application service
       sessions | runs | approvals | traces | authoring
                           |
       +-------------------+--------------------+
       |                   |                    |
  Primitive API       Skill engine         Event stream
 observe/extract    guarded state machine   pause/resume
   act/verify       + selection policies
       +-------------------+--------------------+
                           |
                    Runtime kernel
   observe -> scene -> [extract | resolve -> act] -> verify
      |        |          |          |        |        |
      |     tracker    records     policy  receipt  evidence
      |                                                |
 Perception pipeline                              Trace store
 a11y -> OCR -> vision -> fusion              SQLite + artifacts
      |
               Device backend
    UIAutomator2 hierarchy/actions + selected screenshot path
                           |
                 Android emulator / VM
```

## Package boundaries

```text
haykal/
  contracts/       Versioned Pydantic models and JSON Schemas
  text/            search/material normalization, digit and money parsing
  device/          DeviceBackend protocol and UIAutomator2 implementation
  perception/      Raw normalization, OCR, vision, fusion, quality policy
  scene/           Scene construction, identity tracking, digests
  selectors/       Selector vocabulary, validation, element dictionary
  resolver/        Ranking, ambiguity handling, stale-target re-resolution
  extraction/      Grouping, field binding, value parsing, dedupe, budgets
  execution/       Action validation, dispatch, receipts, retry policy
  verification/    Expectation evaluation and settle polling
  skills/          Validation, registry, interpreter, selection policy, journal
  safety/          Risk classification, gates, approval validation
  traces/          Event writer, artifact storage, redaction, export
  service/         Session/run/approval application services
  transports/http/ HTTP API and SSE event stream
  transports/mcp/  MCP adapter
  sdk/             Python client
  authoring/       Scene inspector, extract/selector dry-run, lint, replay
  benchmarks/      Component suite, workflow suite, comparative harness
  cli/             Administration, diagnostics, and authoring entry points
refapps/           Reference applications (see 07)
importers/maestro/ Post-MVP unless a design partner requires it
```

Dependencies point inward. Transports and concrete backends depend on contracts
and application services; the runtime kernel never imports MCP, FastAPI,
UIAutomator2, OmniParser, or Maestro types. `text/` has no dependencies on any
other Haykal package so it can be tested and benchmarked alone.

## Device backend

The backend interface is asynchronous even though the current Python
`uiautomator2` library is synchronous. Blocking calls execute through a bounded
worker pool with one serialized operation queue per device.

Required backend capabilities:

- Open and close a session.
- Report device identity, geometry, rotation, foreground app, and health.
- Capture raw hierarchy and screenshot evidence.
- Tap, swipe, press a key, and input Unicode text.
- Expose a distinct `dispatch_once` path for irreversible actions; it must issue
  at most one device input event for one action ID and must not inherit transparent
  client-library retries.
- Apply an operation timeout and return a typed failure.
- Restart its on-device process once under the recovery policy.
- Restore temporary input method and device settings during cleanup.

The adapter must disable, bypass, or surface dependency retries. Each permissible
reversible attempt appears in the action receipt and trace. A backend that cannot
prove this property is ineligible for irreversible actions.

## Observation coherence

UIAutomator2 does not provide a truly atomic hierarchy-plus-screenshot snapshot.
`observe()` therefore returns:

- Hierarchy capture time.
- Screenshot capture time.
- Capture order and skew.
- Scene-change fingerprints before and after capture when coherence is uncertain.

If skew or motion exceeds policy, the runtime retries the observation within a
bounded budget. It never claims atomicity that the device cannot provide.

## Perception fallback policy

```text
capture raw evidence
       |
normalize accessibility tree
       |
measure scene quality
       +-- sufficient ----------> construct scene
       |
       +-- missing text ---------> run OCR
       |
       +-- sparse/ambiguous -----> run vision adapter
                                      |
                             fuse all candidates
```

Scene quality considers actionable-node count, labelled-node ratio, target query
coverage, conflicting bounds, and caller policy. Vision is not invoked merely
because it is available.

## Fusion and confidence

Each candidate retains raw source identity. Fusion groups likely matches using:

- Intersection-over-union and containment.
- Normalized text similarity using `arabic-search@1`; material equality uses
  conservative `arabic-material@1`.
- Role compatibility.
- Parent/child and neighborhood context.
- Resource IDs and accessibility metadata when present.

Confidence is stored per property, not only per element. Initial scores are
rule-based and must be calibrated against labelled benchmark data. A score is not
marketed as a probability until calibration measurements support that claim.

## Cross-frame identity

The tracker assigns opaque logical IDs by matching adjacent scenes using stable
resource IDs, role/text signatures, ancestry, geometry, and local neighborhood.
Every scene has a monotonically increasing revision.

An action containing an element ID also contains the scene revision from which it
was selected. Before dispatch, the resolver:

1. Accepts the target when the revision is current.
2. Otherwise re-resolves its semantic fingerprint against the latest scene.
3. Returns `stale_target` or `ambiguous_target` if confidence is insufficient.

Stable IDs are session-scoped in the MVP. They are not promised across app
restarts or independent runs.

## Selector resolution

```text
selector (validated vocabulary)
       |
semantic_name? -> element dictionary -> expanded selector
       |
candidate filter: role, resource_id, state flags, within, near
       |
text scoring: label/text vs normalized query
       |
rank -> top score >= minimum_score and margin >= ambiguity_margin
       |
   accept | ambiguous_target (with ranked alternatives)
```

The dictionary expansion is recorded in the trace so a failure can be read as
"semantic name X expanded to selector Y and matched candidates Z".

## Extraction pipeline

```text
scene or observation
  |
ensure requested evidence -> optional OCR/vision enrichment -> new scene revision
  |
group: single | ancestry | repeat | rows
  |            (declared in the extract request)
records (each = set of elements)
  |
bind fields: selector scoped to the record
  |
parse values: text | number | money | rating | duration | boolean
  |            (text/ parsers, digit system recorded)
attach evidence: scene_id, element_ids, sources per field
  |
dedupe by declared signature across scrolls
  |
budget check: max_records | max_scrolls | max_ms | end_of_list
  |
records + satisfaction/exhaustion/truncation flags + reason
```

Grouping rules:

- `single`: one record scoped to the declared root, or the whole scene when no
  root is declared; used for checkout summaries and forms.
- `ancestry`: elements sharing the nearest ancestor that matches the record
  selector.
- `repeat`: siblings whose subtree shape repeats at least twice under a container.
- `rows`: elements whose vertical centres fall within a declared band, for
  hierarchy-sparse and OCR-only screens.

A field that resolves to more than one element inside a record is an extraction
ambiguity, reported per field, not silently reduced to the first match. Every
record anchor carries a semantic fingerprint and scroll checkpoint. `reveal`
returns to that checkpoint, searches a bounded neighbourhood, and re-resolves the
fingerprint before any anchored action; failure is `record_not_relocatable`.

## Skill execution lifecycle

```text
created -> validating -> acquiring_device -> running
                                         |      |
                                         |      +-> needs_decision
                                         |      +-> approval_required
                                         |      +-> retry_wait
                                         |      +-> suspended (decision expired)
                                         |
                                         +-> completed
                                         +-> completed_reconciled
                                         +-> outcome_unknown
                                         +-> failed
                                         +-> cancelled
```

Before an action, the engine journals `action_prepared`. After a successful device
receipt it journals `action_dispatched`, captures a new scene, evaluates the
expectation, and journals `transition_committed`. Recovery uses this journal to
avoid assuming that an interrupted action did not occur.

Potentially irreversible actions are never automatically replayed after an
uncertain outcome. The run pauses for reconciliation.

## Selection policies

A skill state may declare a `select` block that turns extracted records into one
choice without a model:

```text
records -> filter (declared predicates on parsed fields)
        -> reject if a required field is null
        -> sort (ordered keys, direction, documented tie-break)
        -> take first
        -> if margin between first and second < declared margin -> needs_decision
```

Policies are data, evaluated by the runtime. They cannot call code.

## Escalation

An escalation contains the current redacted scene, known skill state, expected
states, failure reason, allowed primitive actions, extracted candidates when a
choice is required, and a deadline. The caller may:

- Select one candidate.
- Select one candidate transition.
- Provide one bounded semantic action and expectation.
- Cancel the run.

Free-form code and shell commands are not accepted as escalation responses.

The response is executed through the same resolver, safety policy, verifier, and
trace path as a skill action. An expired escalation moves the run to `suspended`.
A dedicated device may remain parked; otherwise a configured hold TTL persists an
app/scene/scroll checkpoint and releases the lease. Resume reacquires a device,
restores the checkpoint when possible, and always starts with a fresh observation.

## Approval gates

Approval is authorized by a human or policy principal whose credential is
separate from the agent/control credential. It is bound to:

- Run and gate IDs.
- Skill name and version.
- Exact action intent digest and target semantic fingerprint.
- Material summary produced by a declared extraction (merchant, items, amount,
  currency, destination, recipient).
- Conservative material digest using raw or `arabic-material@1` values.
- Approver identity, authority, expiry, and single-use nonce.

The runtime re-observes, re-extracts, and re-resolves immediately before execution.
A material or target change invalidates the approval and emits a new gate. A full
scene digest is retained as evidence but unrelated UI changes do not invalidate
approval. Tokens are single-use.

## Irreversible dispatch boundary

The device backend exposes `dispatch_once(action, idempotency_key)` for gated
actions. This path bypasses or disables library-level transparent retries. Haykal
journals `action_prepared` durably before one wire-level dispatch and
`action_dispatched` immediately after a receipt. A timeout or connection loss
after dispatch becomes `outcome_unknown` and enters reconciliation; it never
causes a second tap. This is an at-most-once dispatch guarantee. Haykal reports an
effectively-once external result only when confirmation or reconciliation proves
the effect.

## Event stream

Server-Sent Events over the HTTP API. Each durable event carries the run sequence
number as its SSE `id`. Delivery is at least once: clients reconnect with
`Last-Event-ID` and deduplicate by `(run_id, sequence)`. Retention gaps return an
explicit `event_cursor_expired` response. The MCP adapter reads the same sequence.

## Authoring tools

The `authoring/` package is a consumer of the public contracts, not a privileged
path into the kernel. It uses the same observe, extract, and resolve code the
runtime uses, so a selector that passes dry-run behaves identically in a run.

## Persistence

SQLite WAL stores sessions, runs, skill versions, transition journals, approvals,
extraction results, and trace indexes. Screenshots, raw hierarchies, and exported
traces live in a content-addressed artifact directory.

Database updates and artifact writes use a prepare/commit pattern so a trace never
references a partially written artifact. Retention and redaction policies are
configured per deployment.
