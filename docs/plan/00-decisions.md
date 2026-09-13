# MVP decisions

These decisions are fixed for the MVP unless a validation milestone disproves an
underlying assumption. Every change to this file requires an architecture
decision record in `docs/adr/` with benchmark or customer evidence.

## Product boundary

Haykal is a mobile semantic runtime, not an autonomous general-purpose agent. It
serves two caller types through the same kernel:

- **Step callers** provide one semantic action, extraction, or expectation at a
  time.
- **Task callers** invoke deterministic, parameterized skills.

Unknown states are returned to the caller as structured escalation events. Haykal
does not embed a required LLM loop.

## Four primitives, not three

The kernel exposes exactly four read/write primitives:

| Primitive | Effect on device | Output |
| --- | --- | --- |
| `observe` | none | semantic scene |
| `extract` | none | typed records with evidence |
| `act` | one semantic action | action result |
| `verify` | none | expectation result |

Extraction is a first-class primitive because every task caller needs structured
data from lists, cards, and checkout screens, and because reconciliation before an
approval gate is impossible without it. Extraction never infers a value that is not
present in the scene.

## Platform and deployment

- Android only.
- Controlled emulator or Android VM with ADB access.
- One Haykal worker owns one device lease at a time.
- Single-host, private deployment.
- Linux is the reference server environment; macOS is supported for development.
- Durable run state uses SQLite in WAL mode for the MVP.
- Screenshot and trace files use a configured local artifact directory.

High availability, distributed scheduling, multi-region operation, physical-device
farms, and managed cloud devices are outside the MVP.

## Device backend

- Python `uiautomator2` is the only shipped action and hierarchy backend.
- The backend runs behind an asynchronous `DeviceBackend` interface.
- Device operations have deadlines, typed errors, health checks, and bounded
  automatic recovery.
- The runtime restores device settings it changes, including the input method.
- Screenshot capture is benchmark-driven. It may use an ADB screencap path when
  that produces materially better OCR/vision input than the UIAutomator2 image.
- A per-device lease prevents concurrent UIAutomator2, Maestro, Appium, or Espresso
  ownership.

There is no `AdbExecutor` or `MaestroExecutor` in the MVP.

## Perception

- Accessibility hierarchy is always attempted first.
- OCR supplements missing or conflicting text.
- A swappable vision adapter is invoked only when policy or scene quality requires
  it.
- The first vision adapter may target OmniParser-compatible output, but no model
  type or weight format appears in the canonical contract.
- Model versions, checksums, licenses, latency, and hardware requirements are
  recorded in the build manifest.
- The OCR implementation is selected during the validation milestone using an
  Arabic/English benchmark rather than preference.
- Text normalization uses versioned `arabic-search@1` and conservative
  `arabic-material@1` profiles. Both raw and normalized forms are stored.
- Numeric and monetary values are parsed by a versioned parser that accepts
  Arabic-Indic, Extended Arabic-Indic, and Latin digits and records the digit
  system it saw.
- Text matching has two profiles. `arabic-search@1` may apply aggressive folds
  for candidate retrieval; `arabic-material@1` is conservative and is mandatory
  for equality checks involving approvals, addresses, merchants, recipients, and
  payment hints. Raw text is always retained.
- `extract` may request missing OCR/vision evidence. Enrichment creates a new,
  immutable scene revision and returns both the input and effective scene IDs.

## Selector vocabulary

- Selectors use only the fields enumerated in `03-contracts.md`. Unknown selector
  fields fail validation.
- Skills declare an **element dictionary** that binds semantic names to selectors.
  A semantic name used in a skill state that is absent from the dictionary fails
  skill validation.
- No selector may reference a raw coordinate without a target description and the
  scene revision it was derived from.

## Interfaces

- HTTP/JSON is the canonical service interface.
- The event stream is Server-Sent Events with `Last-Event-ID` resume.
- The Python SDK is a typed client for the HTTP contract and an optional embedded
  client for local development.
- MCP is a thin adapter over the same application service.
- A2A and AG-UI are post-MVP transports. They do not define mobile action syntax.

## Reference applications and benchmarks

- Haykal ships a focused **reference application suite**: Matjar covers Android
  View, Compose, and embedded WebView screens in one deterministic application;
  a small Flutter app covers hierarchy-sparse fallback. Release gates run against
  these apps, never only against third-party apps.
- A **two-track comparative benchmark** is a release artifact. The step-caller
  track compares equivalent agent-driven tools; the compiled-skill track reports
  replay economics plus authoring and maintenance cost. Agent Device is required
  for MVP; Maestro MCP and ARTEMIS adapters are added when a pinned, runnable
  configuration is validated during M0.
- Third-party regional apps are compatibility evidence, recorded and reported
  separately from reproducible results.

## Skills and learning

- Skills are versioned guarded state machines, not linear macros.
- Skills contain semantic actions, extractions, and explicit expectations.
- Skills declare selection policies declaratively. Free-form code is not accepted
  in a skill.
- Runtime recovery may be saved as a candidate patch.
- Candidate patches never update a skill automatically. Promotion requires replay,
  regression evaluation, and maintainer approval.
- Skill authoring tooling (scene inspection, extraction/selector dry-run, skill
  lint, and fixture replay) ships in the MVP. Recording to draft is a release
  candidate, not a core-release blocker. The measured goal is one day for the
  bounded Matjar offers exercise, not for arbitrary production applications.
- Maestro support is a strict importer for a documented subset. It is scheduled
  after the first design partner asks for it.

## Safety

- Skills declare risk gates before irreversible or sensitive actions.
- Purchase, transfer, deletion, permission, credential, and communication actions
  can be gated independently.
- An agent cannot self-approve a gate by default. Approval comes from a human or a
  separately configured policy authority.
- Approval is single-use, expires, and is bound to the run, skill revision, exact
  action intent, target fingerprint, conservative material digest, approver,
  expiry, and nonce. A full scene digest is evidence but is not the authority,
  because unrelated dynamic content may change.
- The agent/control credential cannot hold approval authority. Human or policy
  approval uses a separately authenticated principal and credential.
- Irreversible actions provide **at-most-once dispatch**, never automatic retry.
  A dispatch with an uncertain effect enters reconciliation. “Effectively once”
  may be reported only when independent evidence proves the external outcome.
- Payment-card entry and storage are outside the MVP.

## Effort and staffing

- The stable core MVP is estimated at **24–28 engineer-weeks**, or **14–17
  calendar weeks for two senior engineers** working perception and runtime in
  parallel. A launch package with recorder polish and all optional competitor
  adapters is **28–32 engineer-weeks**. Earlier estimates omitted the hardening
  required around irreversible dispatch, identity recovery, security, and
  statistically useful release evidence.
- Dates are assigned only after Milestone 0 completes.

## Explicit non-goals

- A general autonomous phone agent.
- iOS.
- A managed device platform.
- Automatic skill generation from arbitrary natural language.
- Automatic promotion of learned recoveries.
- Full Maestro language compatibility.
- Training a proprietary vision model.
- Guaranteed automation of applications that block emulators or automation.
- Completing real purchases in release tests.
- Inferring values that are not visible in the scene.
