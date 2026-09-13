# Phase 4 runbook

## Host verification

```bash
cd /Users/abdelhafz/dev/haykal
uv sync --all-extras --locked
uv run python -m haykal.contracts.schema --output schemas/v1
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src/haykal
```

Lint the two Matjar skills independently:

```bash
uv run haykal lint skills/dev.haykal.refapps.matjar/offers.yaml
uv run haykal lint skills/dev.haykal.refapps.matjar/prepare-order.yaml
```

## Publisher setup

Generate an Ed25519 key document and keep it outside the repository:

```bash
uv run haykal skill-keygen --publisher acme.mobile > publisher-key.json
```

Create a deployment trust file containing only public keys:

```json
{
  "publishers": {
    "acme.mobile": "BASE64_ED25519_PUBLIC_KEY"
  }
}
```

Sign and publish a version. Publishing the same bytes is idempotent; publishing
different content under the same name and version fails.

```bash
uv run haykal skill-sign \
  skills/dev.haykal.refapps.matjar/offers.yaml \
  --publisher acme.mobile \
  --private-key publisher-key.json \
  --output signed-offers.yaml

uv run haykal --state-dir .haykal skill-publish signed-offers.yaml \
  --trust-policy trust-policy.json
```

## Serve skills

Use distinct high-entropy caller, approver, and token-signing secrets. The
approval secret must contain at least 32 bytes.

```bash
export HAYKAL_API_TOKEN='caller-secret'
export HAYKAL_APPROVER_TOKEN='different-approver-secret'
export HAYKAL_APPROVAL_SECRET='at-least-32-random-bytes-change-me'
export HAYKAL_TRUST_POLICY="$PWD/trust-policy.json"
uv run haykal --state-dir .haykal serve --host 127.0.0.1 --port 8421
```

Create a device session, then start a signed skill with the caller credential:

```http
POST /v1/runs
Authorization: Bearer <caller>
Idempotency-Key: <unique>

{
  "session_id": "ses_...",
  "skill": "matjar.prepare_pizza_order",
  "version": "1.0.0",
  "inputs": {"maximum_total": {"amount": 60, "currency": "SAR"}}
}
```

When the run returns `approval_required`, the separate approver reads
`GET /v1/runs/{run_id}/approval`, reviews `material`, and posts that exact object:

```http
POST /v1/runs/{run_id}/approvals
Authorization: Bearer <approver>
Idempotency-Key: <unique>

{"gate_id":"gate_...","challenge":{...exact GET response...}}
```

Haykal re-observes and re-extracts before dispatch. A changed total, merchant,
masked address/payment hint, or target returns `approval_stale` and requires a
new review. Exact HTTP retries replay the cached response; a token cannot be used
for a second dispatch.

For MCP skill tools, pass the same trust policy and approval secret to `haykal
mcp`. Omit `--approval-principal` on the caller server. Register a separately
controlled MCP server with `--approval-principal <identity>` only when that
transport itself is the approval authority.

## Live Matjar acceptance

Start the documented Android emulator, then run:

```bash
ANDROID_SDK_ROOT=/path/to/android-sdk \
ANDROID_SERIAL=emulator-5554 \
./scripts/phase4-reference-check.sh
```

The gate builds and installs Matjar, verifies ten scrolling offer records, proves
the preparation run stops before submit, then enables `submit_timeout`, approves
the extracted purchase, asserts one wire-level submit, and reconciles the result
through Orders as `completed_reconciled`.

Generated screen-derived evidence is placed under `reports/m4/` and is ignored.
Do not use the illustrative Jahez lifecycle as a released compatibility skill;
it requires explicit authorization, a supported app version, and credentials.
