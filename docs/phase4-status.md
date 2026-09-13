# Phase 4 implementation status

Phase 4 core implementation finished locally on 2026-09-13. Haykal now runs
signed deterministic skills, persists every run/action checkpoint, pauses on
unknown states, binds approval to re-extracted material and a freshly resolved
target, dispatches approved irreversible taps through a no-recovery single-shot
path, and reconciles an uncertain confirmation through Matjar Orders.

## Implemented

- Typed selection, reconciliation, escalation, decision, approval, run snapshot,
  and candidate-patch contracts, with 21 generated JSON Schemas.
- Ed25519 publisher keys, canonical skill digests, trust policy enforcement,
  immutable `(name, version)` indexing, and content-addressed object storage.
- Deterministic selection with null exclusion, declared filters/order, stable
  record-ID tie-break, and margin/empty escalation.
- Guarded model-free state interpreter with input validation, extract/select,
  reconciliation, bounded transitions, step budget, durable pause/resume, and no
  automatic candidate-patch promotion.
- SQLite run journal with full synchronization, optimistic revisions, durable
  action preparation/commit, conservative interrupted-action recovery, and
  at-most-once journaling for agent-supplied recovery actions.
- Risk-classification floor and approval challenges bound to skill, action
  intent, target fingerprint, normalized material, evidence, expiry, and nonce.
- Separate approver authority, exact-challenge presentation, opaque HMAC token,
  atomic single consumption, expiry, stale-material, stale-target, and replay
  rejection.
- Pre-submit re-observation, re-extraction, and re-resolution.
- UIAutomator2-only execution, including a durable raw-client single-shot path
  that bypasses normal recovery for an irreversible tap.
- Multi-page scrolling extraction with semantic settle, deduplication, limits,
  stop reasons, and page checkpoints.
- HTTP, Python SDK, and MCP run/decision/status/event surfaces. HTTP approval uses
  a separate token and explicit challenge review; MCP approval is absent unless
  the server is created with a separate approval principal.
- Two lint-clean Matjar skills: `matjar.list_pizza_offers` and
  `matjar.prepare_pizza_order`.

## Latest local evidence

- Host suite: 468 tests pass with 84.40% coverage. Ruff and strict mypy pass over 88 source
  files, the lockfile is current, and Matjar assembles successfully.
- Live API 37 ARM64 emulator: the offers skill returned ten deduplicated Arabic
  records across scrolling and completed with no model call.
- Live preparation lifecycle: selected the 4.9-rated candidate under 60 SAR,
  reached checkout, extracted 55.20 SAR plus masked address/payment hints, emitted
  `approval_required`, and did not dispatch the governed action.
- Live approval lifecycle: a separate approval principal authorized the same
  extracted material; exactly one `uiautomator2-single-shot` submit was recorded.
- With Matjar `submit_timeout`, the confirmation remained unknown, the workflow
  opened Orders, extracted the order, and finished `completed_reconciled`. The
  single submit receipt reported `repeated_request: false`.

Generated live evidence is under `reports/m4/` and ignored because it contains
screen-derived data.

## Exit criteria

| Criterion | Status | Evidence or blocker |
| --- | --- | --- |
| Happy skill uses no model calls | passed locally | Matjar offers live run; interpreter has no model dependency |
| Unknown screen pauses without state loss | passed locally | durable journal and expiry/suspend/resume test |
| Restart never repeats committed/prepared action | passed locally | journal recovery and single-shot replay tests |
| Stale, expired, reused approval rejected | passed locally | approval service and interpreter integration tests |
| Fault cannot duplicate gated dispatch | passed locally | raw-client single-shot test and live timeout run with one submit |
| Both lifecycle scenarios pass on Matjar | passed locally | repeatable `phase4-reference-check.sh` |
| Two authorized regional compatibility runs | blocked externally | no Jahez authorization, declared app build, account, OTP policy, or test credentials were supplied |

The Phase 4 core may proceed to hardening. A product release remains blocked by
the regional compatibility runs and the earlier M0/M3 reliability, latency,
competitor, and non-core-author evidence gates. Illustrative Jahez documents are
not counted as compatibility evidence.
