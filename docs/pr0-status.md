# PR.0 status: production contract freeze

Decision: **passed; proceed to PR.1 OmniParser fallback**

Baseline release: `0.0.3`

Accepted runtime commit: `883937b9969802694a27a39261b850c075aa5467`

PR.0 freezes one deliberately narrow production shape: a single-tenant private
service on Ubuntu 24.04 x86_64 controlling one persistent API 35 Android VM with
UIAutomator2. API 34 remains compatibility coverage.

The machine-readable contract is
[`config/production-acceptance.json`](../config/production-acceptance.json). It
pins the accepted release identity, hosted run, reference and compatibility VM
fingerprints, deployment resources, retention, timeouts, recovery bounds, and
resource-growth limits. Release and score decisions are derived from evidence
gates; callers cannot set a production-ready boolean.

The baseline intentionally fails closed with five production blockers:

- OmniParser fallback is not pinned or evaluated.
- The eight-hour release-wheel soak has not run.
- Two authorized regional apps have not been validated.
- The reference deployment drill has not run.
- The final security review must follow those changes.

The non-core author and external competitor benchmark remain separate evidence
gates for the 95/100 claim.

Validation:

```text
uv run python scripts/production-verify.py \
  config/production-acceptance.json --allow-pending
```

Without `--allow-pending`, the verifier returns a non-zero status until every
production gate carries an evidence digest and URI. A code change after this
freeze creates a new release candidate and must pass hosted P95.4 again before
the soak or regional acceptance can count.
