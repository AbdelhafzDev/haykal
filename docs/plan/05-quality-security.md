# Quality, safety, and security

## Quality strategy

Reliability is the product claim. Every reported result must include the device,
application version, locale, model versions, dataset version, number of attempts,
and confidence interval where applicable.

### Test layers

1. **Contract tests:** schema compatibility, serialization, selector validation,
   dictionary cycle detection, and error stability.
2. **Text tests:** both Arabic normalization profiles and every parser against the labelled string
   set; property tests that normalization is idempotent.
3. **Unit tests:** parsing, fusion, tracking, resolution, extraction grouping and
   binding, expectations, selection policies, skill transitions, and approval
   validation.
4. **Golden-scene tests:** raw hierarchy/screenshots produce deterministic
   semantic scenes, digests, and extraction results.
5. **Backend integration tests:** real emulator actions, process recovery, Unicode
   input, rotation, keyboard, and app switching.
6. **Skill tests:** replay against recorded scenes followed by real-device runs on
   reference apps.
7. **Fault injection:** device disconnect, backend death, process restart, empty
   hierarchy, stale scene, duplicate request, artifact write failure, timeout,
   and every Matjar fault switch.
8. **Soak tests:** repeated runs and long-lived idle/active sessions.
9. **Comparative benchmark:** the twenty-task suite across every pinned system
   validated in M0, with Haykal and Agent Device required.
10. **Authoring test:** the one-day exercise performed by someone outside the
    core team, timed and recorded.

## Reference test matrix

- Android API levels selected from partner targets, minimum two.
- Reference apps: Matjar (View, Compose, WebView, checkout) and `flutter-sparse`.
- Arabic (`ar-SA`), English (`en-US`), and mixed-direction content.
- Portrait and one rotation transition.
- Keyboard open/closed transitions.
- Accessibility-rich and intentionally hierarchy-sparse screens.
- Arabic-Indic and Latin digit rendering for every price and rating.

Third-party production apps supplement this matrix as compatibility evidence and
are reported separately.

## Release gates

Targets are provisional until Milestone 0 records baselines. Changing a target
requires a written decision with benchmark evidence.

| Area | MVP release gate |
| --- | --- |
| Primitive execution | ≥99% successful verified reversible actions over 1,000 actions on the reference matrix |
| Reference skills | ≥95% complete runs over 30 clean starts per declared app/version/locale |
| Target resolution | ≥98% precision among accepted targets **and** ≥95% acceptance coverage on resolvable labelled cases; report abstention and false-accept rates |
| Identity tracking | ID precision and recall ≥95%, and IDF1 ≥95%, across the labelled transition set |
| Extraction field presence | Precision and recall ≥98% on the labelled field-presence set |
| Extraction field values | ≥98% exact value accuracy among correctly present fields; parsing and presence errors reported separately |
| Extraction records | ≥99% correct record boundaries (no merged or split cards) on the labelled set |
| Money and number parsing | 100% on the labelled string set, both digit systems, all listed currency tokens |
| Normalization | 100% on the labelled equivalence set; idempotent under property testing |
| Selection policy | 100% agreement with a hand-computed result on the policy fixture set |
| Arabic input | ≥99% exact round-trip on supported non-secure fields; unsupported classes return explicit errors |
| Accessibility-only observe | p95 ≤1,000 ms on reference hardware |
| Extraction, one page | p95 ≤400 ms beyond observe on reference hardware |
| OCR fallback observe | p95 reported and bounded by configured timeout; target set after M0 |
| Vision fallback observe | p95 reported per model/hardware profile; target set after M0 |
| Backend recovery | Detect and either recover or pause safely within 15 s |
| Crash consistency | Zero repeated committed actions across the failure-injection suite |
| Irreversible dispatch | Zero second wire-level dispatches after timeout, connection loss, UIAutomator2 restart, API replay, or process restart |
| Approval safety | Zero accepted expired, reused, wrong-material, wrong-target, wrong-action, wrong-skill, or wrong-run approval tokens |
| Reconciliation | 100% of injected post-submit failures end in `completed_reconciled` or `outcome_unknown`, never `failed` or a second submit |
| Soak | Eight hours without unrecovered deadlock, lease loss, or unbounded memory/artifact growth |
| Authoring | Offers skill authored on Matjar by a non-author in ≤1 working day |
| Comparative benchmark | Report reproduced from the shipped harness within stated variance and published with the release |

Latency measurements report capture, perception, extraction, resolution,
dispatch, verification, and total time separately.

## Benchmark datasets

### Component suite

- Labelled screenshots and hierarchies.
- Expected OCR text and direction.
- Expected normalization and parser outputs for 300 strings.
- Expected source fusion groups.
- Expected element identities across frame sequences.
- Expected resolver candidates and ambiguity outcomes.
- Expected extraction records and per-field values for 100 labelled cards and 20
  labelled checkout screens, in both digit systems.

### Workflow suite

- Reference apps for each UI technology and the Matjar checkout flow.
- Versioned initial device snapshots.
- Skills and expected terminal outcomes, including every fault switch.
- Regional third-party app runs recorded separately and never mixed with
  reproducible results.

### Comparative suite

Defined in [07-reference-apps-and-benchmarks.md](07-reference-apps-and-benchmarks.md).

Benchmark data must not contain live credentials, payment details, OTPs, personal
addresses, or unredacted customer screenshots.

## Action safety

Actions are classified as:

- **Reversible:** navigation, scrolling, opening a screen, adding to a basket.
- **Sensitive:** typing personal information, granting permissions, sending a
  message.
- **Irreversible:** purchase, transfer, submission, deletion, account change.
- **Unknown:** insufficient policy context; treated as gated.

Retry policy depends on classification. A network timeout after an irreversible
tap produces `outcome_unknown`; it does not automatically tap again. The suite
instruments the wire/device boundary and proves that UIAutomator2 or transport
recovery cannot transparently replay the command.

## Extraction safety

- No field value without an element in evidence.
- No currency assumed when the token is missing.
- No value copied across records or interpolated from layout.
- Ambiguous fields are reported, not resolved by position unless the selector
  says so.
- Material summaries for approvals are produced only by declared extractions,
  never by free text from a model.

## Approval security

- Approval tokens are signed or stored as opaque server-side capabilities.
- Tokens carry expiry, nonce, approver, run, skill digest, action-intent digest,
  target fingerprint, and conservative material digest. Scene digest is retained
  as evidence, not used as the sole validity boundary.
- The service re-observes and re-extracts immediately before execution.
- Material changes invalidate approval.
- A consumed nonce cannot be reused.
- Rejection and expiration are durable events.
- Default policy requires human approval for irreversible consumer actions.

## Authentication and authorization

- HTTP binds to loopback by default.
- Remote deployment requires TLS termination and bearer-token authentication.
- Agent/control tokens are scoped to primitive control or skill execution and can
  never carry approval authority. Human or policy approval uses a separate
  authenticated principal and credential. Trace read, authoring, and
  administration are separate scopes.
- SSE streams require the same token as the run they observe.
- MCP stdio inherits local operating-system access but still uses runtime policy.
- Session and run identifiers are unguessable.
- Every mutating HTTP request requires a durable idempotency key bound to the
  authenticated principal and canonical request digest.
- Administrative diagnostics redact secrets.

Enterprise SSO and multi-tenant authorization are post-MVP.

## Secrets and privacy

- Skills reference secrets and saved references; they never embed them.
- Secrets are resolved at execution time from environment/file providers with
  restrictive filesystem permissions.
- Secret values are marked before logging so trace redaction does not depend only
  on pattern matching.
- Screenshots and image crops are sensitive by default.
- Artifact retention is configurable and defaults to a bounded period.
- Export applies text, field, and image-region redaction and records the policy.
- Raw unredacted traces never leave the deployment automatically.
- Card data storage and entry are not supported.

## Dependency and model supply chain

- Lock Python dependencies and record hashes.
- Generate an SBOM for each release.
- Pin OCR and vision model versions and weight checksums.
- Record code, model, and dataset licenses separately.
- Keep the vision adapter replaceable.
- Do not download executable code or model weights implicitly at runtime in a
  production deployment.
- Verify release artifacts in the clean-VM acceptance test.

## Threat model priorities

- Unauthorized device control.
- Malicious or compromised skill definitions.
- Prompt or UI text attempting to manipulate an external caller.
- Trace and screenshot disclosure.
- Approval replay or substitution.
- Duplicate irreversible actions after timeout/restart.
- Extraction manipulated by on-screen text to misreport a total.
- ADB exposure outside the trusted host.
- Model or dependency supply-chain compromise.
- Candidate-patch poisoning.
- Validly structured but malicious or downgraded-risk skill packages.
- Cross-session artifact or device leakage.

Candidate patches and screen text are always untrusted data, never executable
instructions.

Published skill packages are content-addressed and signed by a trusted publisher.
Runtime policy independently classifies actions, so skill metadata cannot weaken
approval or retry requirements.
