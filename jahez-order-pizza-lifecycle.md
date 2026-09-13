# Lifecycle example: “Order me a pizza from Jahez”

This is an illustrative lifecycle, not a claim about Jahez's current private UI,
selectors, policies, or payment behavior. Production use requires an authorized
account, a supported app version, and permission to automate the workflow. The
identical skill, with a different element dictionary, runs against the Matjar
reference app and is the second reference skill in Milestone 4.

Unlike “show me pizza offers,” this request can create a financial and physical
commitment. Haykal may prepare and verify the basket deterministically, but it must
not submit the order without approval bound to the exact merchant, items, total,
delivery address, and current checkout scene.

Release tests run on Matjar or stop at the approval gate on Jahez. They never place
real orders.

Every selector, extraction field, parser, policy, and event below uses only the
vocabulary defined in [docs/plan/03-contracts.md](docs/plan/03-contracts.md).

## 1. The request is incomplete and the skill says so

> Order me a pizza from Jahez.

does not carry enough authority to choose safely. The task caller must supply
preferences or accept that Haykal pauses at each material choice. The skill's
declared inputs make this explicit:

```yaml
inputs:
  pizza:
    type: object
    fields:
      style:         {type: enum, values: [pepperoni, margherita, vegetable, chicken]}
      size:          {type: enum, values: [small, medium, large]}
      quantity:      {type: integer, min: 1, max: 5, default: 1}
      substitutions: {type: enum, values: [allow, disallow], default: disallow}
  minimum_rating:            {type: number, min: 0, max: 5, default: 4.2}
  maximum_delivery_minutes:  {type: integer, min: 10, max: 120, default: 60}
  maximum_total:             {type: money, currency: SAR}
  address:                   {type: saved_ref, namespace: addresses}
  payment:                   {type: saved_ref, namespace: payment_methods}
  approval_authority:        {type: enum, values: [human, policy], default: human}
```

Illustrative task request:

```json
{
  "skill": "jahez.order_pizza",
  "version": "1.0.0",
  "inputs": {
    "pizza": {"style": "pepperoni", "size": "large", "quantity": 1, "substitutions": "disallow"},
    "minimum_rating": 4.2,
    "maximum_delivery_minutes": 60,
    "maximum_total": {"amount": 90.0, "currency": "SAR"},
    "address": {"namespace": "addresses", "reference": "home"},
    "payment": {"namespace": "payment_methods", "reference": "default"},
    "approval_authority": "human"
  }
}
```

Missing `maximum_total` or `address` is `invalid_skill_input`. Haykal never
invents a budget, address, payment method, or substitution policy.

## 2. Element dictionary (excerpt)

```yaml
elements:
  search_box:       {role: textbox, label: {any_contains: ["بحث", "Search"]}}
  results_list:     {role: list, resource_id: {ends_with: "id/search_results"}}
  result_card:      {role: list_item, within: {semantic_name: results_list}}
  size_large:       {role: radio, label: {any_contains: ["كبير", "Large"]}}
  add_to_basket:    {role: button, label: {any_contains: ["أضف إلى السلة", "Add to basket"]}}
  basket_button:    {role: button, label: {any_contains: ["السلة", "Basket"]}}
  basket_badge:     {role: text, within: {semantic_name: basket_button}}
  checkout_button:  {role: button, label: {any_contains: ["إتمام الطلب", "Checkout"]}}
  total_label:      {role: text, text: {any_contains: ["الإجمالي", "Total"]}}
  address_label:    {role: text, text: {any_contains: ["عنوان التوصيل", "Delivery address"]}}
  payment_label:    {role: text, text: {any_contains: ["طريقة الدفع", "Payment method"]}}
  place_order:      {role: button, label: {any_contains: ["تأكيد الطلب", "Place order"]}}
  confirmation:     {role: text, text: {any_contains: ["تم تأكيد طلبك", "Order confirmed"]}}
  order_reference:  {role: text, text: {regex: "^(رقم الطلب|Order)\\s*[#:]?\\s*[A-Z0-9٠-٩-]{4,}$"}}
  orders_tab:       {role: tab, label: {any_contains: ["طلباتي", "Orders"]}}
  order_row:        {role: list_item, within: {role: list, resource_id: {ends_with: "id/orders"}}}
  otp_screen:       {role: text, text: {any_contains: ["رمز التحقق", "Verification code"]}}
  decline_message:  {role: text, text: {any_contains: ["تم رفض", "declined"]}}
```

`place_order` and `checkout_button` are distinct entries with distinct labels. A
generic “Continue” button matches neither, so it can never be resolved as the
submit action.

## 3. Lifecycle overview

```text
request
  |
validate inputs, dictionary, vocabulary, skill version
  |
create durable run + acquire device lease
  |
verify login, location, app version, saved payment availability
  |
search -> extract candidates -> select (declared policy)
  |                                  |
  |                        margin too small / null fields
  |                                  |
  |                          needs_decision -> resume
  |
open product -> select size -> add to basket -> verify badge
  |
open basket -> checkout -> extract checkout record -> reconcile
  |
approval_required with material summary from extraction
  |
human rejects ---------------------------------> cancelled safely
  |
human approves
  |
re-observe + re-extract + compare material fields
  |
changed --------------------> approval_stale -> new approval_required
  |
dispatch place_order at most once
  |
verify confirmation -------> extract order_reference -> completed
  |
uncertain -----------------> reconcile via orders_tab
                                |               |
                         one match         no unique match
                                |               |
                      completed_reconciled  outcome_unknown
```

## 4. Admission and safety classification

Before acquiring a device, Haykal:

1. Authenticates the caller and checks permission to run purchase-capable skills.
2. Loads the exact immutable skill version, verifies its content digest and
   publisher signature, and lints it.
3. Validates every input against its declared type.
4. Resolves `saved_ref` inputs inside the deployment; values never enter the trace.
5. Classifies actions: navigation and add-to-basket are reversible; `place_order`
   is irreversible and gated under `purchase`.
6. Confirms the deployment policy requires `human` approval and that the caller
   has not asked for less than policy allows.
7. Creates the durable run and transition journal.

## 5. Prerequisites

After the lease is held, the runtime verifies backend health, supported app
version, signed-in authorized account, resolvable address reference, and a masked
saved payment method. It then runs one observation and checks `not_visible:
otp_screen`. OTP, CAPTCHA, and identity checks are escalation states; the runtime
never reads an OTP from another application or dismisses a security challenge.

## 6. Search, extract, select

```yaml
results:
  extract:
    as: candidates
    group: {by: ancestry, record: {semantic_name: result_card}}
    fields:
      restaurant: {selector: {role: text, position: first}, type: text, required: true}
      item:       {selector: {role: text, text: {any_contains: ["بيبروني", "Pepperoni"]}}, type: text, required: true}
      rating:     {selector: {role: text, text: {regex: "^[0-9٠-٩۰-۹]\\.[0-9٠-٩۰-۹]$"}}, type: rating, scale: 5, required: true}
      price:      {selector: {role: text, text: {any_contains: ["ر.س", "SAR"]}, position: first}, type: money, required: true}
      eta:        {selector: {role: text, text: {any_contains: ["دقيقة", "min"]}}, type: duration, required: true}
      available:  {selector: {role: text, text: {any_contains: ["مغلق", "Closed"]}}, type: boolean, true_tokens: [], false_tokens: ["مغلق", "Closed"], default_when_absent: true}
    scroll: {within: {semantic_name: results_list}, max_pages: 3}
    dedupe_by: [restaurant, item]
  select:
    from: candidates
    where:
      - {field: available.value, op: "==", value: true}
      - {field: rating.value, op: ">=", value: "${minimum_rating}"}
      - {field: eta.max_minutes, op: "<=", value: "${maximum_delivery_minutes}"}
      - {field: price.currency, op: "==", value: "SAR"}
      - {field: price.amount, op: "<=", value: "${maximum_total.amount}"}
    order_by:
      - {field: rating.value, direction: desc}
      - {field: price.amount, direction: asc}
      - {field: restaurant.normalized, direction: asc}
    margin: {field: rating.value, min_gap: 0.1}
    as: chosen
  action: {kind: tap, target: {record_anchor: chosen}}
  verify: {visible: {semantic_name: add_to_basket}}
  next: product
```

`available` is the one boolean with `default_when_absent: true`; the contract
permits a default only for booleans whose absence is itself the signal, and the
trace records that the default was applied.

Illustrative extracted candidate:

```json
{
  "record_id": "rec:sha256:...",
  "fields": {
    "restaurant": {"raw": "بيتزا مايسترو", "normalized": "بيتزا مايسترو"},
    "item":       {"raw": "بيتزا بيبروني كبيرة", "normalized": "بيتزا بيبروني كبيره"},
    "rating":     {"value": 4.6, "scale": 5, "raw": "٤.٦"},
    "price":      {"amount": 54.0, "currency": "SAR", "raw": "٥٤ ر.س", "digits": "arabic-indic"},
    "eta":        {"min_minutes": 35, "max_minutes": 45, "raw": "٣٥-٤٥ دقيقة"},
    "available":  {"value": true, "raw": null, "defaulted": true}
  },
  "evidence": {"restaurant": {"scene_id": "scn_01J...", "element_ids": ["el_c4_name"], "sources": ["accessibility"]}, "...": "..."},
  "anchor": {"element_id": "el_c4", "scene_revision": 5, "fingerprint": "sha256:...", "scroll_checkpoint": {"page": 2, "visible_signature": "sha256:..."}}
}
```

Before opening `chosen`, Haykal runs `reveal`: it restores the bounded scroll
checkpoint and re-resolves the fingerprint. If the selected card cannot be
relocated unambiguously, the state returns `record_not_relocatable`; it never taps
the card currently occupying the old coordinates.

If the top two candidates are within 0.1 rating of each other after sorting, the
run pauses. This decision is not the purchase approval; it only chooses a
reversible preparation path.

```json
{
  "event_type": "run.needs_decision",
  "payload": {
    "reason": "selection_margin",
    "run_state": "results",
    "question": "Two candidates are equally rated. Choose one to prepare.",
    "choices": [
      {"record_id": "rec:a", "restaurant": "بيتزا مايسترو", "item": "بيتزا بيبروني كبيرة", "price": {"amount": 54.0, "currency": "SAR"}, "eta": {"min_minutes": 35, "max_minutes": 45}},
      {"record_id": "rec:b", "restaurant": "بيتزا هت", "item": "بيبروني لارج", "price": {"amount": 49.0, "currency": "SAR"}, "eta": {"min_minutes": 25, "max_minutes": 35}}
    ],
    "allowed_responses": ["select_record", "cancel"],
    "expires_at": "2026-09-13T10:15:00Z"
  }
}
```

Response: `{"select_record": "rec:b"}`. The runtime re-observes, re-anchors
`rec:b` by fingerprint if the list moved, taps, and continues.

## 7. Product configuration

```yaml
product:
  expect: {visible: {semantic_name: add_to_basket}}
  branches:
    - when: {visible: {semantic_name: size_large}}
      action: {kind: tap, target: {semantic_name: size_large}}
      verify: {state_equals: {target: {semantic_name: size_large}, state: selected, value: true}}
      next: add
    - otherwise:
        escalate: {reason: option_unavailable, allowed_actions: [cancel]}

add:
  action: {kind: tap, target: {semantic_name: add_to_basket}}
  verify:
    value_equals: {target: {semantic_name: basket_badge}, type: number, value: "${pizza.quantity}"}
  next: basket
```

Only options authorized by the inputs are selected. A greyed-out size is
`state_equals enabled false` and triggers `option_unavailable`; it is never
replaced by another size because `substitutions` is `disallow`.

## 8. Checkout extraction and reconciliation

```yaml
review:
  expect: {visible: {semantic_name: place_order}}
  extract:
    as: checkout
    group: {by: single}
    fields:
      merchant:     {selector: {role: text, position: first}, type: text, required: true}
      item_name:    {selector: {role: text, text: {any_contains: ["بيبروني", "Pepperoni"]}}, type: text, required: true}
      item_qty:     {selector: {role: text, text: {regex: "^[0-9٠-٩]+\\s*[x×]"}}, type: number, required: true}
      subtotal:     {selector: {role: text, near: {selector: {text: {any_contains: ["المجموع الفرعي", "Subtotal"]}}, direction: right, max_px: 700}}, type: money}
      discount:     {selector: {role: text, near: {selector: {text: {any_contains: ["خصم", "Discount"]}}, direction: right, max_px: 700}}, type: money}
      delivery_fee: {selector: {role: text, near: {selector: {text: {any_contains: ["رسوم التوصيل", "Delivery fee"]}}, direction: right, max_px: 700}}, type: money}
      service_fee:  {selector: {role: text, near: {selector: {text: {any_contains: ["رسوم الخدمة", "Service fee"]}}, direction: right, max_px: 700}}, type: money}
      tax:          {selector: {role: text, near: {selector: {text: {any_contains: ["ضريبة", "VAT"]}}, direction: right, max_px: 700}}, type: money}
      total:        {selector: {role: text, near: {selector: {semantic_name: total_label}, direction: right, max_px: 700}}, type: money, required: true}
      address:      {selector: {role: text, near: {selector: {semantic_name: address_label}, direction: below, max_px: 140}}, type: text, required: true, privacy: masked}
      payment:      {selector: {role: text, near: {selector: {semantic_name: payment_label}, direction: below, max_px: 140}}, type: text, required: true, privacy: masked}
      eta:          {selector: {role: text, text: {any_contains: ["دقيقة", "min"]}}, type: duration}
  reconcile:
    - {field: checkout.merchant.normalized, op: "==", value: "${chosen.restaurant.normalized}"}
    - {field: checkout.item_qty.value, op: "==", value: "${pizza.quantity}"}
    - {field: checkout.total.currency, op: "==", value: "SAR"}
    - {field: checkout.total.amount, op: "<=", value: "${maximum_total.amount}"}
    - {field: checkout.address.normalized, op: "contains", value: "${address.display_hint}"}
    - {field: checkout.payment.normalized, op: "contains", value: "${payment.display_hint}"}
    - {check: sum_matches, parts: [subtotal, discount, delivery_fee, service_fee, tax], signs: [+, -, +, +, +], total: total, tolerance: 0.05}
  on_reconcile_failure:
    escalate: {reason: checkout_mismatch, allowed_actions: [cancel]}
  gate:
    category: purchase
    material:
      merchant: checkout.merchant
      items: [checkout.item_name, checkout.item_qty]
      total: checkout.total
      address: checkout.address
      payment: checkout.payment
      eta: checkout.eta
  action: {kind: tap, target: {semantic_name: place_order}}
  retry: none
  verify:
    timeout_ms: 20000
    any:
      - visible: {semantic_name: confirmation}
      - visible: {semantic_name: decline_message}
  on_action_uncertain: {next: reconcile}
  on_verify_timeout: {next: reconcile}
  on_verify_failure: {escalate: {reason: unexpected_state, allowed_actions: [cancel]}}
  branches:
    - when: {visible: {semantic_name: confirmation}}
      next: confirmed
    - when: {visible: {semantic_name: decline_message}}
      terminal: failed_declined
```

`display_hint` is the only thing a `saved_ref` exposes: a masked form such as
`Home •••• 182` or `•••• 4242` that the deployment stores next to the reference.
The extraction pipeline masks these fields before persistence or event emission.
Any ephemeral full value visible on screen is used only for the in-transaction
comparison and discarded, so the full address and card never enter the skill,
events, or trace.

`sum_matches` is a built-in reconcile check. If the visible parts do not add up to
the visible total within tolerance, the runtime does not trust the total and
escalates. Any `null` in a field the reconcile rules reference fails reconciliation;
nothing is assumed zero.

Illustrative reconciled checkout record:

```json
{
  "merchant":     {"raw": "بيتزا هت", "normalized": "بيتزا هت"},
  "item_name":    {"raw": "بيبروني لارج", "normalized": "بيبروني لارج"},
  "item_qty":     {"value": 1, "raw": "١ ×", "digits": "arabic-indic"},
  "subtotal":     {"amount": 49.0, "currency": "SAR"},
  "discount":     {"amount": 8.0, "currency": "SAR"},
  "delivery_fee": {"amount": 5.0, "currency": "SAR"},
  "service_fee":  {"amount": 2.0, "currency": "SAR"},
  "tax":          {"amount": 7.2, "currency": "SAR"},
  "total":        {"amount": 55.2, "currency": "SAR", "raw": "٥٥٫٢٠ ر.س", "digits": "arabic-indic"},
  "address":      {"raw": "المنزل •••• 182", "normalized": "المنزل •••• 182"},
  "payment":      {"raw": "بطاقة محفوظة •••• 4242", "normalized": "بطاقه محفوظه •••• 4242"},
  "eta":          {"min_minutes": 25, "max_minutes": 35}
}
```

## 9. Approval gate

```json
{
  "event_type": "run.approval_required",
  "payload": {
    "gate_id": "gate_01J...",
    "category": "purchase",
    "expires_at": "2026-09-13T10:20:00Z",
    "proposed_action": {"kind": "tap", "target": {"semantic_name": "place_order"}},
    "material": {
      "merchant": "بيتزا هت",
      "items": ["1 × بيبروني لارج"],
      "total": {"amount": 55.2, "currency": "SAR"},
      "address": "المنزل •••• 182",
      "payment": "بطاقة محفوظة •••• 4242",
      "eta": {"min_minutes": 25, "max_minutes": 35}
    },
    "material_source": {"extraction_id": "ext_01J...", "scene_id": "scn_01M..."},
    "skill_digest": "sha256:...",
    "action_intent_digest": "sha256:...",
    "target_fingerprint": "sha256:...",
    "material_digest": "sha256:...",
    "evidence_scene_digest": "sha256:...",
    "nonce": "nonce_01J..."
  }
}
```

The material summary is the extraction result, not prose. The run releases no
purchase action while paused. The task-calling agent cannot approve its own
purchase: approval arrives through a separately authenticated human or policy
principal. Its credential is never available to the agent/control process.

```json
{
  "gate_id": "gate_01J...",
  "decision": "approve",
  "material_digest": "sha256:...",
  "action_intent_digest": "sha256:...",
  "target_fingerprint": "sha256:...",
  "nonce": "nonce_01J...",
  "approval_token": "opaque-single-use-token"
}
```

The HTTP request also carries a unique `Idempotency-Key`; repeating the same
request returns the original approval response, while changing its content under
the same key is rejected.

## 10. Pre-submit revalidation

Immediately after approval and before tapping, the runtime captures a fresh scene,
runs the `review` extraction again, and compares every material field to the
approved values. A different total, merchant, item, quantity, address hint,
payment hint, or a `place_order` target fingerprint that changes makes the
approval `approval_stale`. Haykal emits a new `run.approval_required` with the new
material summary; it never stretches the old approval. An unrelated full-scene
change does not invalidate the gate by itself.

## 11. Submit with at-most-once dispatch

The gated action is in the same `review` state as its approval material. The
journal records `action_prepared`, performs one wire-level dispatch, then records
`action_dispatched`. `retry: none` is enforced by deployment policy and the
irreversible backend path bypasses UIAutomator2's transparent retry. Lint rejects
a purchase action without `on_action_uncertain` and `on_verify_timeout` routes to
reconciliation. Haykal claims an effectively-once result only after confirmation
or reconciliation proves what happened.

## 12. Confirmation

```yaml
confirmed:
  extract:
    as: order
    group: {by: single}
    fields:
      reference: {selector: {semantic_name: order_reference}, type: text}
      total:     {selector: {role: text, near: {selector: {semantic_name: total_label}, direction: right, max_px: 700}}, type: money}
      eta:       {selector: {role: text, text: {any_contains: ["دقيقة", "min"]}}, type: duration}
  reconcile:
    - {field: order.total.amount, op: "==", value: "${checkout.total.amount}", tolerance: 0.01}
  terminal: completed
```

Result:

```json
{
  "run_id": "run_01J...",
  "status": "completed",
  "skill": "jahez.order_pizza@1.0.0",
  "order": {
    "merchant": "بيتزا هت",
    "items": ["1 × بيبروني لارج"],
    "total": {"amount": 55.2, "currency": "SAR"},
    "reference": "masked:••••7312",
    "eta": {"min_minutes": 25, "max_minutes": 35}
  },
  "approval": {"gate_id": "gate_01J...", "approved_by": "human:user_01J..."},
  "stats": {"steps": 14, "model_calls": 0, "decisions": 1, "gates": 1, "duration_s": 38.2},
  "trace_id": "trc_01J..."
}
```

## 13. Unknown-outcome reconciliation

If the tap was dispatched and neither confirmation nor decline verified within the
timeout, or the backend died after `action_dispatched`, the runtime must not tap
again.

```yaml
reconcile:
  actions_allowed: [tap, swipe, press_key]      # reversible only, enforced
  steps:
    - action: {kind: press_key, key: back}
    - action: {kind: tap, target: {semantic_name: orders_tab}}
      verify: {visible: {semantic_name: order_row}}
    - extract:
        as: recent_orders
        group: {by: ancestry, record: {semantic_name: order_row}}
        fields:
          merchant: {selector: {role: text, position: first}, type: text, required: true}
          total:    {selector: {role: text, text: {any_contains: ["ر.س", "SAR"]}}, type: money, required: true}
          placed:   {selector: {role: text, text: {any_contains: ["دقيقة", "الآن", "min", "now"]}}, type: duration}
        limits: {max_records: 5}
    - match:
        from: recent_orders
        where:
          - {field: merchant.normalized, op: "==", value: "${checkout.merchant.normalized}"}
          - {field: total.amount, op: "==", value: "${checkout.total.amount}", tolerance: 0.01}
          - {field: placed.max_minutes, op: "<=", value: 10}
        expect_count: 1
        on_one: {terminal: completed_reconciled}
        on_zero_or_many: {terminal: outcome_unknown}
```

`completed_reconciled` carries the matched order record and its evidence.
`outcome_unknown` is returned for human review with the last scene attached. The
runtime never reports `failed` merely because confirmation was not observed; the
purchase may exist.

## 14. Escalations during the run

| Situation | Reason code | Allowed responses |
| --- | --- | --- |
| Requested size greyed out | `option_unavailable` | cancel |
| Minimum order above budget | `checkout_mismatch` | cancel |
| Restaurant closed mid-run | `selection_empty` | cancel |
| Address outside service area | `checkout_mismatch` | cancel |
| OTP, CAPTCHA, identity, recovery | `security_challenge` | cancel |
| Payment declined | terminal `failed_declined` | none |
| Fee pushes total above budget | `checkout_mismatch` | cancel |
| Unknown modal over checkout | `unrecognized_screen` | tap, press_key, cancel |
| Submit action ambiguous | `ambiguous_target` | cancel |
| Confirmation indistinguishable from error | reconcile path | none |
| Two equal candidates | `selection_margin` | select_record, cancel |

Each escalation exposes only bounded choices and a redacted scene. A successful
recovery becomes a candidate skill patch, never an automatic production update.

## 15. Cleanup and retained evidence

1. Persist the terminal event and reconciliation status.
2. Consume or invalidate the approval token.
3. Restore temporary input-method and device settings.
4. Preserve the app state when human review may be required; otherwise follow the
   deployment's neutral-state policy.
5. Release the device lease.
6. Apply trace retention and redaction policy.

The trace retains masked order details, approval identity, scene/action digests,
extraction evidence, target-resolution evidence, action timing, and verification.
It never stores raw card data, full addresses, or OTP values.

## Acceptance scenarios

Each maps to a Matjar fault switch and is part of the Milestone 4 gate.

| Scenario | Switch |
| --- | --- |
| Happy path to the gate, approve, confirm, no model call | none |
| User rejects; no submit occurs | none, reject at gate |
| Approval expires and cannot be reused | none, wait |
| Price changes after approval; new gate emitted | `price_change` |
| Basket gains an unexpected item; reconcile fails | harness adds item |
| Requested size unavailable; bounded decision | `option_unavailable` |
| Payment declined; no resubmission | `payment_decline` |
| Backend dies before final tap; resume, no duplicate | harness kill before submit |
| Backend dies after final tap; reconciliation finds the order | `submit_created_no_confirm` |
| Submit hangs; reconciliation finds the order | `submit_timeout` + created |
| Submit hangs; nothing created; `outcome_unknown` | `submit_timeout` + not created |
| Duplicate approval and duplicate action requests; one order | harness replays |
| Two equal candidates; select_record resumes | seeded data |
| Visible parts do not sum to total; escalates | harness mis-renders tax |
| OTP screen before checkout; security_challenge | `otp_challenge` |
| Arabic-Indic digits throughout; totals parse and reconcile | `arabic_indic_digits` |
| Trace export masks address, account, payment, and order reference | export test |
