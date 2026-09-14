# P95.1 status: trusted safety and privacy boundary

Decision: **complete locally; overall release remains no-go**

P95.1 closes the two release-critical implementation defects found in the Phase
5 review. It does not claim hosted CI, clean API 34/35 wheel-only acceptance,
real fault injection, an independently scored competitor benchmark, or external
validation.

## Effective-risk boundary

- `RiskClassifier` now runs inside `ActionRunner`, after target resolution, for
  Python, HTTP, MCP, recovery decisions, and deterministic skills.
- The classifier combines caller/skill declarations with action kind,
  coordinates, selector semantics, and the resolved element label, text, and
  resource ID. Risk is monotonic: external declarations can raise the floor and
  cannot lower it.
- Coordinates are `unknown`. Every non-navigation or explicitly gated action
  requires an internal `ValidatedApproval` bound to the effective action intent,
  resolved target fingerprint, and effective category.
- HTTP and MCP expose no approval boolean. Only successful consumption of the
  signed, single-use skill challenge creates the internal permit.
- Purchase, transfer, submission, deletion, communication, and unknown actions
  reach only the durable single-shot backend. The trace records declared,
  inferred, effective, and policy-decision fields before dispatch.

The live Matjar run also found and fixed a conservative false positive: opening
the checkout review screen (`checkout_button`, “متابعة إلى الدفع”) is navigation,
while the actual `place_order` / “إتمام الطلب” control is a purchase. The final
live trace classified the latter as purchase, stopped without an approval, and
used `uiautomator2-single-shot` after approval.

## Fail-closed trace export

- Images remain omitted by default.
- When enabled, every exported artifact must match an exact or wildcard pixel
  region. Missing or mismatched rules abort the entire export.
- Regions are checked against the decoded image dimensions. Malformed images and
  out-of-bounds regions abort before the destination is published.
- Stored envelopes say `policy: raw, applied: false`; only an actually redacted
  public/read/export representation says `applied: true`.
- The corpus includes multiple artifacts, wildcard and exact rules, malformed
  PNG data, invalid bounds, email/phone/card patterns, and Arabic names and
  addresses under generic evidence keys.

Pixel-region selection is an operator policy. The runtime proves that configured
coverage is applied to every included image; it cannot prove that a manually
chosen rectangle covers every visually sensitive pixel.

## Evidence

| Gate | Result |
| --- | --- |
| HTTP coordinate downgrade | rejected; zero normal or single-shot dispatches |
| MCP resolved Arabic payment with navigation declaration | rejected; zero dispatches |
| Signed skill resolved to payment without a gate | failed before dispatch |
| Risk monotonicity | Hypothesis property passes across every category pair |
| Stale/mismatched approval | rejected when material, target, or effective risk changes |
| Approved coordinates/unknown | exactly one `dispatch_once` call |
| Image without a matching rule | entire export rejected |
| Malformed/out-of-bounds image | entire export rejected and destination unpublished |
| Raw/public trace flags | raw false; redacted public/export true |
| Full host gate | 499 passed, 3 expected P95.2/P95.3 locks, at least 85% coverage |
| Build/install | sdist, wheel, and isolated wheel install passed |
| API 37 Matjar | 10-offer lifecycle passed; order stopped at approval; approved submit dispatched once and reconciled through Orders |

Local artifact identities for the final API 37 run:

- wheel SHA-256: `bdd8376850de029e716c7ba0012f811553d0d4c67070f5957f23b642a3213112`
- Matjar debug APK SHA-256: `22296d98d427ff5e1903319bea4e181c74848c58cd4ccedad732e34ce332132d`
- implementation commit: `IMPLEMENTATION_COMMIT`

Commands used:

```sh
./scripts/phase5-check.sh
ANDROID_SDK_ROOT=/Users/abdelhafz/Library/Android/sdk \
  ANDROID_SERIAL=emulator-5554 ./scripts/phase4-reference-check.sh
./scripts/p95-secret-scan.sh
uv run pip-audit --progress-spinner off
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
```

The P95.0 hosted fresh-checkout evidence is still unavailable because this
repository has no configured remote. Therefore the honest overall score is
**78/100 official**, or **80/100 conditional** on the required hosted baseline
run. P95.2 is next: real fault injection and device-aware readiness.
