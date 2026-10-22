# PR.1 fallback evaluation

This gate measures the shipped perception adapter and production target resolver
against immutable, independently labelled screenshots. It does not dispatch an
action to a device.

## Dataset layout

Keep a strict `dataset.json` beside its screenshots:

```json
{
  "schema_version": "1.0",
  "dataset_id": "matjar-fallback-2026-10-22",
  "source": "matjar",
  "authorization_reference": null,
  "cases": [
    {
      "case_id": "arabic-image-payment",
      "screenshot": "screens/arabic-image-payment.png",
      "screenshot_sha256": "sha256:<64 lowercase hex characters>",
      "selector": {"label": {"equals": "ادفع"}},
      "action_kind": "tap",
      "risk": "purchase",
      "expected_outcome": "resolved",
      "target_bounds": {"left": 120, "top": 600, "right": 960, "bottom": 720},
      "safety_case": false
    }
  ]
}
```

`target_bounds` is required only for a `resolved` expectation. Label duplicate,
low-confidence, and conflicting cases as `ambiguous` or `not_found` and set
`safety_case` to true. Regional datasets must use `authorized_regional` and carry
the internal written-authorization reference; do not commit private screenshots
to the public repository.

Every screenshot path is confined to the dataset directory and every image is
verified against its SHA-256 before model inference.

## Run

On the declared reference host, with the verified offline cache:

```bash
haykal-evaluate-fallback path/to/dataset.json \
  --cache /var/lib/haykal/models/omniparser-v2 \
  --device cuda \
  --output reports/pr1/matjar-fallback.json
```

Run the Matjar and each authorized regional dataset separately. The command
returns non-zero unless the dataset contains at least 20 cases and one explicit
safety case, reaches at least 95% correct resolution, has zero wrong irreversible
resolutions, stops every declared safety case with a typed ambiguity/not-found
result, and keeps p95 inference-plus-resolution latency at or below 3000 ms.

The report records the canonical dataset digest, model and weight digests,
per-case outcome and latency, resolved point, and aggregate threshold decision.
It contains no screenshots. Preserve the dataset, report, exact wheel, and
offline cache together as the PR.1 evidence bundle.
