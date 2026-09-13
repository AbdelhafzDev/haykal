# Risks and validation questions

## Highest risks

### Effort underestimation

Risk: the first draft estimated 8–10 weeks. It omitted reference applications,
extraction, authoring tooling, the comparative benchmark, and reconciliation.

MVP response:

- Stable-core estimate revised to 24–28 engineer-weeks, or 14–17 calendar weeks
  for two; the broader launch package is 28–32 engineer-weeks.
- Every milestone lists deliverables that must exist before its gate runs.
- Re-estimate at the end of M0 and M2 and record the delta.

### UIAutomator2 operational behavior

Risk: hierarchy capture can be slow or empty, the on-device process can die, and
UiAutomation ownership can conflict with other automation tools. The client may
also transparently retry a JSON-RPC operation after restarting its service, which
is unacceptable for an irreversible tap.

MVP response:

- Exclusive device lease.
- Per-operation timeout and serialized queue.
- Empty-hierarchy detection and bounded retry.
- One safe backend restart followed by a structured pause.
- A separate irreversible dispatch path that bypasses/disables transparent
  retries, with wire-level replay-prevention tests.
- Recovery and soak tests on every supported Android API level.

### Unicode and Arabic input

Risk: custom IME, clipboard paste, accessibility `setText`, secure fields, WebView,
Compose, and Flutter behave differently. The helper IME can also change or hide the
user keyboard.

MVP response:

- Benchmark strategies per field type in M0.
- Record selected strategy in action receipts.
- Save and restore the prior input method.
- Verify entered value when readable.
- Mark secure or unsupported fields explicitly rather than claiming success.

### Screenshot/OCR quality

Risk: compressed screenshots lose small Arabic features, while lossless captures
may cost latency. OCR accuracy varies by font, diacritics, mixed direction, and
rendering technology.

MVP response:

- Choose screenshot and OCR backends from a labelled benchmark.
- Store raw text alongside normalized matching text.
- Invoke OCR only when useful and vision only when needed.
- Report source-specific latency and accuracy.

### Extraction correctness

Risk: record boundaries merge or split cards; a price is bound to the wrong card;
Arabic-Indic digits or an unusual currency token parse wrongly; a checkout total is
misread before an approval.

MVP response:

- Four grouping strategies (`single`, `ancestry`, `repeat`, `rows`) with labelled
  fixtures for each.
- On-demand perception enrichment creates a new immutable scene revision.
- Scrolled record anchors carry checkpoints and must be revealed and re-resolved.
- Per-field ambiguity reporting instead of first-match.
- Parsers isolated in `text/` with a 300-string labelled set and a 100% gate.
- Material summaries for approvals come only from declared extractions.
- Reconciliation compares extracted totals with the approved values before submit.
- Threat model includes on-screen text crafted to misreport a total.

### Confidence without calibration

Risk: a number labelled confidence may look statistically meaningful when it is
only a heuristic ranking.

MVP response:

- Call it a ranking confidence in the contract and documentation.
- Define acceptance thresholds from labelled data.
- Preserve alternative candidates and ambiguity margins.
- Add probability calibration only after sufficient production evidence exists.

### Reference apps built by the same team

Risk: apps designed by Haykal's authors may unintentionally favour Haykal's
perception, inflating gate results.

MVP response:

- Reference apps use standard framework widgets and official sample layouts
  wherever possible, with hierarchy-sparse screens deliberately included.
- Compatibility runs on authorized regional apps are reported alongside every
  release, separately labelled.
- The comparative benchmark runs competitors on the same apps; a large gap in
  Haykal's favour on reference apps but not on regional apps is flagged as a
  suite bias finding.

### Third-party app instability

Risk: regional consumer apps change frequently, detect emulators, require OTP,
bind accounts to devices, or prohibit automated access.

MVP response:

- Base release gates on reference apps.
- Pin skill support to declared app-version ranges.
- Use authorized accounts and environments.
- Treat third-party production flows as compatibility evidence, not reproducible
  release fixtures.
- Pause clearly when integrity checks or policy restrictions block automation.

### Skill maintenance cost

Risk: app-specific skills become a services business unless authoring, testing,
and update promotion are disciplined.

MVP response:

- Ship core authoring tools in the MVP and gate the bounded Matjar exercise at one
  day; measure other skills rather than promising the same duration.
- Keep the first skill set very small.
- Require explicit states, element dictionaries, and expectations.
- Generate candidate patches but never auto-promote them.
- Measure maintenance time and breakage rate as product metrics.

### Comparative benchmark fairness

Risk: competitors configured poorly make Haykal look better than it is, and the
report loses credibility on first inspection.

MVP response:

- The parity track uses the same pinned model and neutral task prompt; a separate
  appendix may show vendor-recommended configurations.
- Pin exact commits, packages, models, prompts, device snapshots, and options.
- Keep step-caller parity separate from compiled-skill economics, which includes
  authoring and maintenance cost.
- Configuration files for every system are published with the report.
- Tasks, apps, and raw per-run logs are published.
- A row where Haykal loses is reported as a loss.

### Managed-device scope expansion

Risk: authentication and persistent device identity make a device platform appear
necessary before the runtime has product-market evidence.

MVP response:

- Operate one or a few manually provisioned persistent VMs/devices.
- Define a device-provider boundary but do not implement cloud scheduling.
- Integrate an existing provider or customer-owned devices before building a fleet.

## Decisions required during Milestone 0

1. Which Android API levels and VM image are supported at launch?
2. Does UIAutomator2 screenshot quality meet Arabic OCR requirements, or is
   lossless ADB screencap the default?
3. Which local OCR implementation wins the Arabic/English benchmark under the
   target CPU/GPU envelope?
4. Which OmniParser-compatible implementation and weights are commercially safe,
   reproducible, and fast enough?
5. Which UI technologies and text-field categories can be supported honestly?
6. What retention period and redaction policy apply by default?
7. What is the first authorized reference workflow and application version?
8. Do the three interviewed partners want primitives, skills, or both, and who
   maintains their logged-in devices?
9. Which currency tokens and duration formats appear in the partner apps beyond
   the MVP list?
10. Can each optional benchmark competitor be pinned and run reproducibly under
    the parity harness? If not, document its exclusion rather than inventing a
    “latest” configuration.

Answers are recorded as architecture decision records with benchmark or customer
evidence.

## Product questions to validate with design partners

- Do callers primarily want primitives, deterministic skills, or both?
- Will they provide and maintain logged-in devices, or expect device provisioning?
- Which actions require human approval under their policy?
- Must all perception run without network access?
- What trace evidence is necessary for audit and support?
- Who owns skill maintenance when an application changes?
- Is Arabic/RTL accuracy a purchasing requirement or only a useful differentiator?
- Which existing Maestro assets, if any, must import for adoption to be credible?
- Which extracted data do they need returned as structured records?

## Metrics that determine whether to continue

After two design-partner workflows, review:

- Successful deterministic-run rate.
- Escalations per run and percentage converted into approved patches.
- Model calls and cost avoided compared with the comparative benchmark baselines.
- Median and p95 observation-to-verified-action latency.
- Extraction field accuracy on partner screens.
- Skill breakage and maintenance hours per app release.
- Incorrect resolutions that escaped verification.
- Device provisioning and session-recovery burden.
- Customer willingness to pay for runtime versus a managed outcome.

If maintenance dominates or customers only buy complete outcomes, repositioning
toward a managed automation service may be more rational than expanding the
protocol surface.

## Post-MVP options, not commitments

- Own AccessibilityService backend with event-driven observation.
- Additional Android action backend for restricted devices.
- Maestro importer (M6) when a partner needs it.
- A2A task adapter and AG-UI event adapter.
- Managed persistent-device integration or platform.
- iOS observer and executor.
- Skill authoring UI on top of the CLI tools.
- Automated patch evaluation and promotion workflow.
- Calibrated confidence models trained from accepted and rejected resolutions.
- Learned extraction templates per app from accepted records.
