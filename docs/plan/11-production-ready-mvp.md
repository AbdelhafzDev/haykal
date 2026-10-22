# Production-ready MVP plan

Status: **ready to execute**

Starting point: Haykal `0.0.3` has passed hosted wheel-only acceptance on clean
Android API 34 and 35 VMs. The accepted runtime commit is
`883937b9969802694a27a39261b850c075aa5467`, and its wheel SHA-256 is
`b01ce357d5c5be1142b8aca427b63843f4d08ad8ee5d4de21dd29e00d169c200`.
The implementation score is 91/100. This plan earns production confidence
without expanding the product into a device cloud or general QA platform.

## Production definition

The production MVP is a **single-tenant, private Haykal service controlling one
persistent Android VM**. It supports Android 14 and 15, Python UIAutomator2,
accessibility-first perception, local OmniParser V2 fallback, Python/HTTP/MCP
callers, deterministic skills, approval gates, redacted traces, backup, restore,
and upgrade.

The first release is production-ready when:

1. The exact release wheel survives an eight-hour device-and-fault soak.
2. OmniParser fallback is licensed, pinned, measured, and fails closed.
3. Two authorized regional-app workflows pass repeated acceptance runs without
   a real purchase or production payment data.
4. A clean host can be installed, monitored, backed up, restored, upgraded, and
   rolled back from the runbook.
5. No unresolved critical or high-severity safety, privacy, or integrity finding
   remains.

Competitor results and broader platform features do not substitute for these
gates.

## Phase PR.0: freeze the release contract

**Target:** half a day.

Work:

- Keep `0.0.3` and its P95.4 artifacts immutable as the baseline.
- Create one production acceptance manifest containing the release commit,
  source tree, wheel, Matjar APK, VM image, Android SDK, Python, model, skill, and
  configuration digests.
- Define one supported reference host and one supported persistent API 35 VM.
- Define operational limits before testing: disk floor, trace/artifact retention,
  request timeout, lease duration, maximum recovery time, and resource-growth
  limits.
- Keep API 34 as compatibility coverage; use API 35 as the production reference.

Exit:

- One manifest identifies every executable input.
- Every later report points to that manifest.
- Any code change after the freeze creates a new release candidate and repeats
  hosted P95.4 acceptance.

## Phase PR.1: ship OmniParser as the fallback

**Target:** three to five engineering days.

Use Microsoft OmniParser V2 with:

- `icon_detect_v3`, the MIT-licensed YOLOv9-E detector;
- `icon_caption`, the MIT-licensed Florence-2 captioner; and
- the existing OCR adapter for visible text.

Do not ship the older YOLOv8-based `icon_detect` weights because they are
AGPL-3.0. Pin the exact upstream revisions and SHA-256 hashes, retain the MIT
notices, and include the weights in the dependency/license inventory.

Implementation:

- Add OmniParser through the existing vision-adapter interface. Do not change
  the scene, action, selector, result, or trace contracts.
- Load the models once in the runtime process. Do not introduce a separate
  service, queue, or network call for the MVP.
- Invoke fallback only when the accessibility scene declares insufficient
  coverage, the caller explicitly requests visual observation, or target
  resolution has no accessibility candidate.
- Normalize detector boxes and captions into ordinary evidence-bearing scene
  elements. Preserve the screenshot digest, model digests, confidence, and
  coordinate transform in the trace.
- Fuse accessibility, OCR, and vision evidence. Accessibility remains preferred
  when sources agree. Conflicts and low-confidence-only matches return a typed
  ambiguity or escalation; they never silently choose an action.
- Keep effective-risk classification and approval after target resolution, so a
  vision-originated target cannot lower risk or bypass a gate.
- Package OmniParser as an optional production extra and support a pre-populated
  offline model cache. Production startup must not download code or weights.

Acceptance dataset:

- Matjar screens covering known elements, missing semantics, scrolling, dialogs,
  keyboards, stale totals, and image-only controls.
- Authorized Arabic/RTL screens from the two pilot apps.
- Mixed Arabic/English labels, Eastern and Western Arabic numerals, duplicate
  icons, disabled elements, and small touch targets.

Release thresholds on the declared reference host:

- At least 95% correct target resolution on fallback-required labelled cases.
- Zero wrong irreversible or unknown-risk dispatches.
- Every low-confidence or conflicting case stops safely.
- P95 fallback observation latency no greater than three seconds.
- No raw screenshot or model input leaves the private deployment.

Exit:

- Model and weight digests are in the release manifest and SBOM.
- The labelled evaluation report is reproducible from saved inputs.
- OmniParser can be disabled without changing any public contract.

## Phase PR.2: prove runtime reliability

**Target:** one engineering day plus an uninterrupted eight-hour run.

Work:

- Build one new release wheel only if PR.1 changes product code. Promote that
  exact wheel through hosted P95.4 on API 34 and 35 before the soak.
- Run the accepted wheel for 28,800 uninterrupted seconds on a clean reference
  VM using the existing P95.2 fault schedule.
- Exercise process kill, SQLite interruption, artifact corruption, UIAutomator2
  death, ADB disconnect, lease expiry, IME interruption, and disk pressure.
- Record latency, recovery time, RSS, file count, artifact bytes, SQLite bytes,
  open descriptors, leases, settings, and dispatch receipts as time series.
- Recompute the report from raw evidence and publish its digest.

Exit:

- Zero duplicate irreversible dispatches, deadlocks, leaked leases, integrity
  failures, or unrecovered device settings.
- All uncertain outcomes remain explicit and are reconciled without transparent
  retry.
- All resource and recovery limits declared in PR.0 pass.
- A failure creates a defect and a new release candidate; a shortened rerun does
  not count.

## Phase PR.3: validate the regional product wedge

**Target:** two to four active days, dependent on authorization and accounts.

Use two apps for which the team has written authorization, dedicated test
accounts, stable OTP access, and non-production addresses. Never enter real card
data or place a real purchase.

Required workflows per app:

1. **Show pizza offers:** search, extract structured offers, preserve evidence,
   and return results without mutation.
2. **Prepare a pizza order:** select an item and options, reach the final
   purchase gate, summarize the material terms, and stop before purchase.

Run each workflow at least 30 times across Arabic and English UI where available.
Include a cold start, warm persistent session, keyboard interruption, popup,
scroll relocation, changed price, stale approval, accessibility gap, and vision
fallback.

Exit:

- At least 95% task success for supported paths.
- 100% stop rate at the declared payment/irreversible gate.
- Zero real orders, payment entry, or unredacted private evidence.
- Every failure has a typed reason and a redacted trace; unsupported screens fail
  safely instead of guessing.

## Phase PR.4: make one deployment operable

**Target:** two to three engineering days.

Build one reference deployment, not several:

- Ubuntu 24.04 LTS host, pinned Python environment, pinned Android SDK, one
  persistent API 35 VM, and a `systemd` Haykal service.
- Bind Haykal to loopback behind the customer's authenticated TLS reverse proxy.
- Store caller, approver, and signing credentials separately in the deployment's
  secret store or root-readable environment files.
- Put state and raw evidence on an encrypted volume. Encrypt backup archives with
  the deployment's KMS or backup tooling.
- Monitor `/livez`, `/readyz`, disk space, lease age, pending reconciliation,
  process restarts, device connectivity, and backup freshness.
- Provide one install command sequence, one upgrade sequence, one rollback
  sequence, and one recovery drill. Test them on a clean host.
- Set a seven-day default trace/artifact retention for the pilot, configurable by
  the operator, with images disabled in public exports by default.

Do not add Kubernetes, multi-tenancy, enterprise SSO, a web dashboard, or a
managed device scheduler for the MVP.

Exit:

- A fresh operator can install the pinned release from the runbook.
- Restart, backup, restore, upgrade, rollback, expired credential, full disk, and
  disconnected-device drills behave as documented.
- The service is never ready when its authorized device cannot accept work.
- Remote traffic is authenticated and encrypted before reaching Haykal.

## Phase PR.5: final acceptance and launch

**Target:** one to two active days.

- Have one non-core engineer install the release and author or modify one Matjar
  skill using only the public documentation. Fix blocking documentation or tool
  defects and replay the resulting skill 30 times.
- Run one pinned external competitor through the independent Matjar oracle. This
  validates the benchmark and positioning; it cannot override a failed product
  gate.
- Review the threat model, known limitations, SBOM, licenses, regional reports,
  soak report, deployment drills, and all open findings.
- Publish a final release-evidence index that hashes every report and identifies
  the exact wheel, models, VM, configuration, and skills.

Launch decision:

- **Production pilot:** all safety, reliability, perception, regional, and
  deployment gates above pass. One design partner and one controlled VM are
  supported.
- **No-go:** any critical/high finding, failed eight-hour soak, unlicensed model,
  wrong irreversible action, missing authorization, or unreproducible evidence.
- **95/100:** add the non-core author and external benchmark evidence required by
  P95.5; do not award points for plans or synthetic results.

## Sequence

```text
PR.0 freeze
   ↓
PR.1 OmniParser fallback
   ↓
hosted P95.4 rerun for the new wheel
   ↓
PR.2 eight-hour soak
   ↓
PR.3 two authorized regional apps
   ↓
PR.4 one reference deployment
   ↓
PR.5 independent acceptance → production pilot
```

PR.3 account preparation and PR.4 clean-host preparation may happen while the
PR.2 soak is running, but their evidence is evaluated only against the same
accepted release.

## Explicitly not now

- iOS.
- Physical-device farms or a managed VM cloud.
- Multiple executors, including Maestro or Appium execution.
- Kubernetes, multi-region failover, or horizontal scaling.
- Multi-tenancy, enterprise SSO, billing, or an admin dashboard.
- A custom accessibility-service APK.
- Automatic skill patch promotion or self-learning.
- Additional agent protocols beyond the working Python, HTTP, and MCP surfaces.
- General-purpose QA recording and test-management features.

These become roadmap items only after a design partner proves a repeated need.

## Estimated remaining effort

The internal work is approximately **8–13 active engineering days**, plus the
eight-hour soak and time needed to obtain regional-app authorization and a
non-core participant. The calendar is driven by external access, not by adding
more architecture.
