# Canonical contracts

All public objects carry `schema_version`. JSON Schema is generated from the
Python models and checked into the repository. The runtime rejects unknown major
versions and preserves unknown compatible extension fields when proxying data.

Every field shown below is part of the contract. Fields not shown are not
promised. Where the plan earlier used placeholders such as `semantic_name` or
`attribute: quantity` without definition, this document now defines them or
removes them.

## Text normalization profiles

Raw text is always retained. Candidate discovery defaults to `arabic-search@1`:

1. Unicode NFC.
2. Remove bidi control characters (U+200E, U+200F, U+202A–U+202E, U+2066–U+2069).
3. Remove tashkeel (U+064B–U+0652, U+0670) and tatweel (U+0640).
4. Unify alef variants (أ إ آ ٱ) to ا.
5. Unify ى to ي.
6. Unify ة to ه.
7. Unify ک to ك and ی to ي (Persian forms seen in some fonts).
8. Convert Arabic-Indic (U+0660–U+0669) and Extended Arabic-Indic (U+06F0–U+06F9)
   digits to ASCII digits.
9. Convert Arabic comma (U+060C) and Arabic decimal separator (U+066B) and
   thousands separator (U+066C) to `,` and `.` and `,` respectively.
10. Case-fold Latin letters.
11. Collapse internal whitespace to one space; trim.

Similarity between normalized strings is Levenshtein ratio. `equals` requires
ratio 1.0. `contains` requires the normalized query to be a substring.
`similar` requires ratio at or above a declared threshold, default 0.90.

`arabic-material@1` performs steps 1–5 and 7–11 but does **not** fold `ة` to `ه`.
It is mandatory for approval material, merchant/address/recipient/payment-hint
reconciliation, and other security-sensitive equality. Those comparisons retain
and expose the raw value, conservative normalized value, and parser version.

## Value types and parsers

| Type | Parser input | Output fields |
| --- | --- | --- |
| `text` | raw string | `raw`, `normalized` |
| `number` | digits in any supported system, optional separators and sign | `value`, `raw`, `digits` |
| `money` | number plus currency token | `amount`, `currency`, `raw`, `digits` |
| `rating` | number in [0, 5] or [0, 10] with declared scale | `value`, `scale`, `raw` |
| `duration` | number(s) plus unit token; ranges allowed | `min_minutes`, `max_minutes`, `raw` |
| `boolean` | declared true/false token lists | `value`, `raw` |

`digits` is one of `latin`, `arabic-indic`, `extended-arabic-indic`, `mixed`.

Currency tokens recognized in MVP: `SAR`, `ر.س`, `ريال`, `﷼`, `SR`, `AED`,
`د.إ`, `KWD`, `د.ك`, `BHD`, `QAR`, `OMR`, `EGP`, `ج.م`, `USD`, `$`, `EUR`, `€`.
A money value with no recognizable currency token parses with `currency: null`;
the skill decides whether that is acceptable. The parser never assumes a
currency.

Duration unit tokens recognized in MVP: `دقيقة`, `دقائق`, `د`, `min`, `mins`,
`minute`, `minutes`, `ساعة`, `ساعات`, `hr`, `hrs`, `hour`, `hours`.

Parsers are versioned (`money@1`) and benchmarked in the component suite.

## Raw observation

```json
{
  "schema_version": "1.0",
  "observation_id": "obs_01J...",
  "session_id": "ses_01J...",
  "revision": 42,
  "display": {"width": 1080, "height": 2400, "density": 2.75, "rotation": 0},
  "foreground": {"package": "com.example", "activity": ".MainActivity"},
  "keyboard": {"visible": false},
  "hierarchy": {
    "artifact": "sha256:...",
    "captured_at": "2026-09-13T10:01:02.123Z",
    "backend": "uiautomator2"
  },
  "screenshot": {
    "artifact": "sha256:...",
    "media_type": "image/png",
    "captured_at": "2026-09-13T10:01:02.301Z",
    "backend": "adb-screencap"
  },
  "capture_skew_ms": 178,
  "warnings": []
}
```

## Semantic scene

```json
{
  "schema_version": "1.0",
  "scene_id": "scn_01J...",
  "session_id": "ses_01J...",
  "revision": 42,
  "digest": "sha256:...",
  "quality": {
    "score": 0.84,
    "accessibility_coverage": 0.71,
    "fallbacks_used": ["ocr"]
  },
  "elements": [
    {
      "id": "el_01J...",
      "role": "button",
      "label": "إتمام الطلب",
      "label_normalized": "اتمام الطلب",
      "text": null,
      "resource_id": "com.example:id/submit",
      "bounds": {"left": 780, "top": 2110, "right": 1040, "bottom": 2220},
      "state": {
        "enabled": true, "visible": true, "focused": false,
        "checked": null, "selected": false, "scrollable": false
      },
      "actions": ["tap"],
      "parent": "el_01H...",
      "properties": {
        "role": {"confidence": 0.99, "sources": ["accessibility:node_81"]},
        "label": {
          "confidence": 0.94,
          "sources": ["accessibility:node_81", "ocr:block_12"]
        },
        "bounds": {"confidence": 0.97, "sources": ["accessibility:node_81"]}
      },
      "fingerprint": {
        "resource_id": "com.example:id/submit",
        "ancestry": ["checkout", "footer"],
        "text_key": "اتمام الطلب"
      }
    }
  ]
}
```

Roles in MVP: `button`, `textbox`, `text`, `image`, `checkbox`, `radio`, `switch`,
`list`, `list_item`, `tab`, `dialog`, `container`, `webview`, `unknown`.

Confidence is a normalized ranking score in MVP v1. It is not described as a
statistical probability unless later calibration supports that interpretation.

## Selector vocabulary

A selector is an object using only these fields. Validation rejects any other
field.

```yaml
# identity
element_id: "el_01J..."          # requires scene_revision alongside
scene_revision: 42
semantic_name: search_box        # resolved through the skill's element dictionary

# structural filters
role: textbox                    # one role or a list
resource_id: {equals: "com.example:id/search"}   # equals | ends_with | regex
within: {semantic_name: results_list}            # ancestor must match
near: {selector: {...}, direction: right, max_px: 200}   # spatial neighbour

# text filters (each accepts equals | contains | any_contains | similar | regex,
# plus optional normalization, default arabic-search@1)
label: {any_contains: ["بحث", "مطعم", "طبق"]}
text: {equals: "بيتزا"}

# state filters
focused: true
enabled: true
checked: false
selected: true
scrollable: true

# ordinal within the filtered candidate set, after ranking
position: first                   # first | last | index
index: 2
```

Selection semantics:

- Structural and state filters are hard filters.
- Text filters produce a score in [0, 1]; `equals` and `contains` are hard
  filters that also score 1.0.
- `position` and `index` apply after filtering and are the only way to pick among
  equal candidates without ambiguity.
- A selector without any text, identity, or semantic field and without `position`
  is rejected as under-specified.

### Element dictionary

Skills bind semantic names to selectors once, at the top of the skill:

```yaml
elements:
  search_box:
    role: textbox
    label: {any_contains: ["بحث", "مطعم", "طبق"]}
  results_list:
    role: list
    resource_id: {ends_with: "id/search_results"}
  result_card:
    role: list_item
    within: {semantic_name: results_list}
  basket_badge:
    role: text
    within: {semantic_name: basket_button}
  basket_button:
    role: button
    label: {any_contains: ["السلة", "Basket", "Cart"]}
  place_order_button:
    role: button
    label: {any_contains: ["إتمام الطلب", "تأكيد الطلب", "Place Order"]}
```

A semantic name may reference other semantic names through `within` and `near`.
Cycles fail validation. Dictionary expansion is recorded in the trace.

## Semantic action

```json
{
  "schema_version": "1.0",
  "action_id": "act_01J...",
  "kind": "tap",
  "target": {
    "scene_revision": 42,
    "element_id": "el_01J...",
    "selector": {"semantic_name": "place_order_button"}
  },
  "resolution": {
    "minimum_score": 0.80,
    "ambiguity_margin": 0.10
  },
  "risk": {"category": "purchase", "gate": "required"}
}
```

MVP action kinds:

- `tap`
- `swipe` with `direction`, `distance_ratio`, optional `within` selector
- `input_text` with explicit `replace` or `append` mode
- `press_key` with `back`, `home`, `enter`, `search`
- `wait` with `ms` or an expectation

Coordinates are allowed as a bounded fallback. A coordinate action must carry a
`target.description` and the `scene_revision` it was derived from; it is rejected
if the revision is stale.

## Extraction request

```yaml
schema_version: "1.0"
scene_id: "scn_01J..."                # omit to observe first
require_sources: [accessibility, ocr]   # vision may also be requested
group:
  by: ancestry                      # single | ancestry | repeat | rows
  record: {semantic_name: result_card}
fields:
  restaurant: {selector: {role: text, position: first}, type: text, required: true}
  rating:     {selector: {role: text, text: {regex: "^[0-9٠-٩]\\.[0-9٠-٩]$"}}, type: rating, scale: 5}
  eta:        {selector: {role: text, text: {any_contains: ["دقيقة", "min"]}}, type: duration}
  fee:        {selector: {role: text, text: {any_contains: ["ر.س", "SAR", "توصيل"]}}, type: money}
  thumb:      {selector: {role: image, position: first}, type: image_crop}
scroll:
  within: {semantic_name: results_list}
  max_pages: 3
  settle: {stable_samples: 2, interval_ms: 250}
dedupe_by: [restaurant]
limits: {max_records: 20, max_ms: 15000}
```

If the supplied scene lacks a required source, extraction enriches from the same
device state and creates a new immutable scene revision. The result identifies
both `input_scene_id` and `effective_scene_id`. If capture coherence cannot be
maintained, extraction returns `observation_incoherent`; it never mutates the
original scene. `group.by: single` creates one record under optional `group.root`,
or from the whole scene when the root is omitted.

`image_crop` returns an artifact reference to a crop of the current screenshot
bounded by the element; it is the only field type that produces an artifact.

Field options:

| Option | Applies to | Meaning |
| --- | --- | --- |
| `required: true` | any | record is dropped and reported if the field is `null` |
| `scale` | `rating` | 5 or 10 |
| `true_tokens`, `false_tokens` | `boolean` | token lists matched after normalization |
| `default_when_absent` | `boolean` only | value to use when no element matches; the output carries `defaulted: true`. Permitted only for booleans whose absence is itself the signal, such as a “Closed” badge. No other type may default. |
| `position` | any | choose among several matches inside one record; without it, multiple matches are an ambiguity |
| `privacy` | any | `public` (default), `masked`, or `secret`; masked values are transformed before persistence/export, while secret values expose only equality evidence and a digest |

Privacy transformation happens inside extraction before results or trace events
are persisted. Ephemeral raw values may be used for a declared reconciliation in
the same transaction and are then discarded. Screenshots containing protected
regions are either region-redacted before persistence or retained only in the
restricted raw-artifact store according to deployment policy.

## Extraction result

```json
{
  "schema_version": "1.0",
  "extraction_id": "ext_01J...",
  "input_scene_id": "scn_01J...",
  "effective_scene_id": "scn_01K...",
  "scenes": ["scn_01J...", "scn_01K..."],
  "request_satisfied": true,
  "source_exhausted": true,
  "truncated": false,
  "stop_reason": "end_of_list",
  "records": [
    {
      "record_id": "rec:sha256:...",
      "fields": {
        "restaurant": {"raw": "بيتزا مايسترو", "normalized": "بيتزا مايسترو"},
        "rating": {"value": 4.6, "scale": 5, "raw": "٤.٦"},
        "eta": {"min_minutes": 30, "max_minutes": 40, "raw": "٣٠-٤٠ دقيقة"},
        "fee": {"amount": 9.0, "currency": "SAR", "raw": "٩ ر.س", "digits": "arabic-indic"},
        "thumb": {"artifact": "sha256:..."}
      },
      "evidence": {
        "restaurant": {"scene_id": "scn_01J...", "element_ids": ["el_51a"], "sources": ["accessibility"]},
        "rating": {"scene_id": "scn_01J...", "element_ids": ["el_51b"], "sources": ["ocr"]},
        "eta": {"scene_id": "scn_01J...", "element_ids": ["el_51c"], "sources": ["accessibility"]},
        "fee": {"scene_id": "scn_01J...", "element_ids": ["el_51d"], "sources": ["ocr"]},
        "thumb": {"scene_id": "scn_01J...", "element_ids": ["el_51e"], "sources": ["accessibility"]}
      },
      "anchor": {
        "element_id": "el_51",
        "scene_revision": 42,
        "fingerprint": "sha256:...",
        "scroll_checkpoint": {"container": "el_list", "page": 1, "visible_signature": "sha256:..."}
      },
      "ambiguities": []
    }
  ]
}
```

Rules:

- A field with no matching element is `null` with `evidence: null`.
- A field with more than one matching element inside the record is `null` and
  listed in `ambiguities` with the candidate element IDs.
- A `required: true` field that is `null` drops the record and reports it in
  `dropped_records` with the reason.
- `anchor` is the element to tap to open the record. Before acting, `reveal`
  restores its bounded scroll checkpoint and re-resolves its fingerprint. It
  returns `record_not_relocatable` rather than tapping another record.
- `request_satisfied` means caller limits such as `max_records` were met;
  `source_exhausted` means the runtime proved the list ended; `truncated` means a
  time/page/record budget may have omitted records. These flags are independent.
- Stop reasons: `end_of_list`, `max_records`, `max_pages`, `max_ms`,
  `no_new_records`, `scene_unstable`.

## Expectation

```yaml
schema_version: "1.0"
timeout_ms: 5000
settle:
  stable_samples: 2
  interval_ms: 250
all:
  - visible: {role: dialog}
  - any:
      - text_contains: "تم"
      - text_contains: "نجاح"
  - foreground_package: "com.example"
```

MVP predicates:

- `visible: <selector>`
- `not_visible: <selector>`
- `text_equals: {target: <selector>, value: "..."}` or shorthand string for
  anywhere on screen
- `text_contains` same forms
- `state_equals: {target: <selector>, state: enabled|focused|checked|selected|scrollable, value: bool}`
- `value_equals: {target: <selector>, type: number|money|rating|duration, value: ...}`
  parses the element text with the named parser and compares
- `foreground_package: "..."`
- `scene_changed: true`
- `scene_stable: true`

`attribute_equals` from earlier drafts is replaced by `state_equals` for boolean
state flags and `value_equals` for parsed values. There is no free-form attribute
name.

Each result contains pass/fail/inconclusive status and the scene elements or state
used as evidence.

## Action result

```json
{
  "schema_version": "1.0",
  "action_id": "act_01J...",
  "status": "verified",
  "attempts": 1,
  "started_at": "2026-09-13T10:01:03.000Z",
  "completed_at": "2026-09-13T10:01:03.480Z",
  "pre_scene": "scn_01J...",
  "post_scene": "scn_01K...",
  "resolved_target": {
    "element_id": "el_01J...",
    "point": [910, 2165],
    "score": 0.96,
    "dictionary_expansion": {"semantic_name": "place_order_button", "selector": {}},
    "alternatives": []
  },
  "device_receipt": {"backend": "uiautomator2", "accepted": true, "input_strategy": null},
  "verification": {"status": "passed", "evidence": ["el_01K..."]},
  "trace_id": "trc_01J..."
}
```

Terminal action statuses are `verified`, `executed_unverified`, `rejected`,
`ambiguous`, `failed`, and `outcome_unknown`. `input_strategy` is one of
`accessibility_set_text`, `helper_ime`, `clipboard_paste`, or `null` for
non-text actions.

## Skill

```yaml
schema_version: "1.0"
kind: skill
metadata:
  name: refapp.matjar.prepare_order
  version: 1.0.0
  package: dev.haykal.refapps.matjar
  app_versions: ">=1.0,<2.0"
  locales: [ar-SA, en-US]

inputs:
  item:           {type: string, min_length: 1}
  maximum_total:  {type: money, currency: SAR}
  minimum_rating: {type: number, min: 0, max: 5, default: 4.0}
  address:        {type: saved_ref, namespace: addresses}
  payment:        {type: saved_ref, namespace: payment_methods}

elements:
  search_box:     {role: textbox, label: {any_contains: ["بحث", "Search"]}}
  results_list:   {role: list, resource_id: {ends_with: "id/results"}}
  result_card:    {role: list_item, within: {semantic_name: results_list}}
  add_button:     {role: button, label: {any_contains: ["أضف", "Add"]}}
  basket_button:  {role: button, label: {any_contains: ["السلة", "Basket"]}}
  basket_badge:   {role: text, within: {semantic_name: basket_button}}
  place_order:    {role: button, label: {any_contains: ["إتمام الطلب", "Place Order"]}}

start: home

states:
  home:
    expect: {visible: {semantic_name: search_box}}
    action:
      kind: input_text
      target: {semantic_name: search_box}
      text: "${item}"
      mode: replace
    verify: {visible: {semantic_name: results_list}}
    next: results

  results:
    extract:
      as: candidates
      group: {by: ancestry, record: {semantic_name: result_card}}
      fields:
        name:   {selector: {role: text, position: first}, type: text, required: true}
        rating: {selector: {role: text, text: {regex: "^[0-9٠-٩۰-۹]\\.[0-9٠-٩۰-۹]$"}}, type: rating, scale: 5}
        price:  {selector: {role: text, text: {any_contains: ["ر.س", "SAR"]}}, type: money, required: true}
      scroll: {within: {semantic_name: results_list}, max_pages: 2}
      dedupe_by: [name]
    select:
      from: candidates
      where:
        - {field: rating.value, op: ">=", value: "${minimum_rating}"}
        - {field: price.amount, op: "<=", value: "${maximum_total.amount}"}
        - {field: price.currency, op: "==", value: "SAR"}
      order_by:
        - {field: rating.value, direction: desc}
        - {field: price.amount, direction: asc}
        - {field: name.normalized, direction: asc}      # documented tie-break
      margin: {field: rating.value, min_gap: 0.1}        # else needs_decision
      as: chosen
    action: {kind: tap, target: {record_anchor: chosen}}
    verify: {visible: {semantic_name: add_button}}
    next: product

  product:
    action: {kind: tap, target: {semantic_name: add_button}}
    verify:
      value_equals: {target: {semantic_name: basket_badge}, type: number, value: 1}
    next: basket

  basket:
    action: {kind: tap, target: {semantic_name: basket_button}}
    verify: {visible: {semantic_name: place_order}}
    next: review

  review:
    extract:
      as: checkout
      group: {by: single, root: {role: container, position: last}}
      fields:
        merchant: {selector: {role: text, position: first}, type: text, required: true}
        total:    {selector: {role: text, near: {selector: {text: {any_contains: ["الإجمالي", "Total"]}}, direction: right, max_px: 600}}, type: money, required: true}
        address:  {selector: {role: text, near: {selector: {text: {any_contains: ["العنوان", "Address"]}}, direction: below, max_px: 120}}, type: text}
    reconcile:
      - {field: checkout.total.currency, op: "==", value: "SAR"}
      - {field: checkout.total.amount, op: "<=", value: "${maximum_total.amount}"}
    terminal: prepared
```

Input types: `string`, `integer`, `number`, `boolean`, `enum`, `money`,
`secret_ref`, `saved_ref`. `saved_ref` and `secret_ref` resolve inside the
deployment and never place their values in inputs, events, or traces.

`select.where` operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `contains`.
A record with a `null` in any referenced field is excluded and counted in the
trace. `margin` compares the first and second record after sorting; a gap below
`min_gap` produces `needs_decision` with both candidates.

Skills are immutable once published. Editing creates a new semantic version.
The registry stores a canonical content digest, publisher identity, and signature.
Loading verifies all three against the deployment trust policy. Runtime risk
classification is computed independently; a valid skill cannot lower the policy
category of an action by declaring it reversible.

## Decision responses

A `run.needs_decision` event names its `allowed_responses`. The caller replies
with exactly one of:

```json
{"select_record": "rec:sha256:..."}
{"select_transition": "dismiss_promo"}
{"action": {"kind": "tap", "target": {"element_id": "el_close", "scene_revision": 7}},
 "expect": {"not_visible": {"element_id": "el_close", "scene_revision": 7}}}
{"cancel": true}
```

A response not listed in `allowed_responses` is rejected with `invalid_decision`.
Candidate targets in the event may carry `matches_semantic_name` when an element
matches a dictionary entry the current state did not expect.

### Escalation reason codes

`run.needs_decision` carries one of these `reason` values. Skills may not invent
others; lint rejects an `escalate.reason` outside this list.

- `unexpected_state` — `expect` failed and no branch matched
- `unrecognized_screen` — no known state matches the current scene
- `selection_margin` — top two records within `margin.min_gap`
- `selection_empty` — no record passed `select.where`
- `option_unavailable` — a required option resolved but is disabled
- `checkout_mismatch` — a reconcile check failed
- `location_unavailable` — the app reports the saved location cannot be served
- `security_challenge` — OTP, CAPTCHA, identity, or account-recovery screen
- `ambiguous_target` — the action target did not clear the ambiguity margin
- `extraction_ambiguous_field` — a required field matched several elements
- `material_choice_required` — the skill declares a choice the inputs do not settle


## Skill state grammar

Every state is an object with these optional blocks, evaluated in this order:

```text
expect -> extract -> select -> reconcile -> gate -> action -> verify -> branches | next | terminal
                                                   |          |
                                                   |          +-> on_verify_timeout | on_verify_failure
                                                   +-> on_action_uncertain
```

| Block | Purpose | Notes |
| --- | --- | --- |
| `expect` | precondition on the current scene | expectation object; failure with no matching branch escalates `unexpected_state` |
| `extract` | extraction request with `as: <name>` | result addressable as `<name>` in later blocks |
| `select` | declarative choice over an extraction | see below |
| `reconcile` | list of checks over extracted values and inputs | any failure runs `on_reconcile_failure`, default escalate `checkout_mismatch` |
| `gate` | approval for the action in the same state | `category`, `material` map, optional `require`; a gate without an action is invalid |
| `action` | one semantic action | `target` may be a selector or `{record_anchor: <select alias>}` |
| `retry` | `retry: none` or `retry: {max: n, only_if: reversible}` | lint forces `retry: none` for irreversible categories |
| `verify` | postcondition | expectation object; `timeout_ms` overrides default |
| `on_action_uncertain` | transition after dispatch with unknown effect | required for irreversible actions; normally reconciliation |
| `on_verify_timeout` | transition after expectation timeout | explicit; does not fall through to `branches` |
| `on_verify_failure` | transition after a conclusive mismatch | explicit; default is `expectation_failed` |
| `branches` | ordered `when`/`otherwise` list | each entry has `next`, `terminal`, or `escalate` |
| `next` | unconditional successor | mutually exclusive with `branches` |
| `terminal` | ends the run with a status label | `completed`, `completed_<label>`, `failed_<label>`, `prepared`, `completed_reconciled`, `outcome_unknown` |
| `escalate` | pause with `reason` and `allowed_actions` | `allowed_actions` ⊆ `[tap, swipe, press_key, input_text, wait, cancel]` |

`branches` are evaluated only after a successful verification, or directly after
the last non-action block when the state has no action. Failures never silently
fall through. A state containing `gate` must contain the exact governed `action`;
approval cannot be acquired in one state and consumed by an action in another.
For irreversible actions, lint requires `retry: none`, `on_action_uncertain`, and
a reconciliation-only destination. The device backend must also prove that its
irreversible path performs no transparent transport/library retry.

Reconcile check forms:

```yaml
- {field: <path>, op: <op>, value: <literal or ${input}>, tolerance: 0.01}   # tolerance only for numbers
- {check: sum_matches, parts: [a, b, c], signs: [+, -, +], total: t, tolerance: 0.05}
```

A `null` in any referenced field fails the check. Field paths use dot notation
into parsed values: `checkout.total.amount`, `chosen.restaurant.normalized`.

Reconciliation-only sub-flows (used after `outcome_unknown`) may declare
`actions_allowed` restricted to reversible kinds and a `match` step:

```yaml
- match:
    from: <extraction alias>
    where: [ ...checks... ]
    expect_count: 1
    on_one: {terminal: completed_reconciled}
    on_zero_or_many: {terminal: outcome_unknown}
```

## Approval challenge and token

An approval challenge is immutable and names the exact operation it authorizes:

```json
{
  "gate_id": "gate_01J...",
  "run_id": "run_01J...",
  "skill_digest": "sha256:...",
  "action_intent_digest": "sha256:...",
  "target_fingerprint": "sha256:...",
  "material": {"merchant": "بيتزا هت", "total": {"amount": 58.0, "currency": "SAR"}},
  "material_digest": "sha256:...",
  "evidence_scene_digest": "sha256:...",
  "expires_at": "2026-09-13T10:06:00Z",
  "nonce": "nonce_01J..."
}
```

The material digest uses canonical JSON and conservative text normalization. The
approval endpoint is accessible only to a separate `approve` principal; agent and
skill-execution credentials cannot carry this scope. The returned opaque token is
single-use and repeats every binding above. Immediately before dispatch, Haykal
re-extracts material and re-resolves the target. A changed material or target
fingerprint produces `approval_stale`. A changed full scene alone does not.

### `saved_ref` and `secret_ref`

Inputs of these types resolve inside the deployment. A `saved_ref` exposes one
field to the skill, `display_hint`, a masked string stored beside the reference
such as `المنزل •••• 182`. It exists so reconcile checks can confirm the screen
shows the intended address or card without the skill ever holding the value.
`secret_ref` exposes nothing to the skill; it is consumed only by `input_text`
with `mode: replace` into a field the deployment policy allows.

### Object inputs

```yaml
inputs:
  pizza:
    type: object
    fields:
      style: {type: enum, values: [pepperoni, margherita]}
      size:  {type: enum, values: [small, medium, large]}
```

Object inputs are addressed by path: `${pizza.size}`.

### Run result envelope

```json
{
  "run_id": "run_01J...",
  "status": "completed",
  "skill": "name@version",
  "inputs_echo": {},
  "outputs": {},
  "extractions": [{"extraction_id": "ext_01J...", "as": "offers", "request_satisfied": true, "source_exhausted": false, "truncated": true, "stop_reason": "max_records", "records": 10, "dropped_records": 1}],
  "approval": null,
  "stats": {"steps": 0, "model_calls": 0, "decisions": 0, "gates": 0, "duration_s": 0.0},
  "trace_id": "trc_01J..."
}
```

`inputs_echo` never contains `saved_ref` or `secret_ref` values, only their
reference names. `model_calls` is always 0 for a skill run; decisions answered by
an external model are counted by the caller, not by Haykal.


## Runtime events

- `run.started`
- `device.lease_acquired`
- `observation.created`
- `extraction.completed`
- `action.prepared`
- `target.resolved`
- `risk.assessed`
- `action.dispatched`
- `verification.completed`
- `transition.committed`
- `run.needs_decision`
- `run.approval_required`
- `run.approval_stale`
- `run.resumed`
- `run.suspended`
- `run.completed`
- `run.completed_reconciled`
- `run.outcome_unknown`
- `run.failed`
- `run.cancelled`
- `device.lease_released`

Events have monotonically increasing sequence numbers within a run. The SSE `id`
is the sequence number. Transport delivery is at least once. Clients resume with
`Last-Event-ID` and deduplicate by `(run_id, sequence)`; a cursor older than the
retention window receives `event_cursor_expired` and must fetch the durable trace.

## Trace envelope

```json
{
  "schema_version": "1.0",
  "trace_id": "trc_01J...",
  "run_id": "run_01J...",
  "sequence": 18,
  "event_type": "verification.completed",
  "occurred_at": "2026-09-13T10:01:03.480Z",
  "payload": {},
  "artifacts": ["sha256:..."],
  "redaction": {"policy": "raw", "applied": false}
}
```

The durable store records the representation it actually contains: raw envelopes
use `policy: raw` and `applied: false`. Authenticated HTTP/SSE/MCP reads and static
exports pass each envelope through the selected redactor and return
`applied: true`; callers must not interpret the stored flag as permission to
publish the raw row.

`risk.assessed` is emitted after target resolution and before dispatch. Its safe
payload records the caller/skill declaration, runtime inference, effective risk,
and policy decision. It never includes input text, approval tokens, or raw gate
material.

## Error contract

Errors contain a stable machine code, human summary, retry classification, trace
ID, and safe diagnostic details. Codes:

- `device_unavailable`
- `device_lease_conflict`
- `backend_timeout`
- `backend_restarted`
- `observation_incoherent`
- `hierarchy_unavailable`
- `vision_unavailable`
- `invalid_selector`
- `undefined_semantic_name`
- `stale_target`
- `record_not_relocatable`
- `ambiguous_target`
- `extraction_ambiguous_field`
- `extraction_budget_exhausted`
- `unparsable_value`
- `expectation_failed`
- `outcome_unknown`
- `approval_required`
- `approval_stale`
- `invalid_skill_input`
- `invalid_decision`
- `unexpected_state`
- `unsupported_skill_version`
- `unsupported_import_command`
- `event_cursor_expired`
- `idempotency_conflict`

Retryability is declared by the runtime; callers should not infer it from HTTP
status codes or error text.

## Northbound API surface

```text
POST   /v1/sessions
POST   /v1/sessions/{id}/observe
POST   /v1/sessions/{id}/extract
POST   /v1/sessions/{id}/actions
POST   /v1/sessions/{id}/verify
DELETE /v1/sessions/{id}

POST   /v1/runs
GET    /v1/runs/{id}
GET    /v1/runs/{id}/events            (text/event-stream, Last-Event-ID)
POST   /v1/runs/{id}/decisions
POST   /v1/runs/{id}/approvals
POST   /v1/runs/{id}/cancel

GET    /v1/traces/{id}
POST   /v1/traces/{id}/export

POST   /v1/skills/validate             (lint without a device)
```

Every mutating `POST` requires an `Idempotency-Key`. The server stores the key,
authenticated principal, canonical request digest, response, and expiry. Reusing
the key with the same digest returns the original response; reuse with different
content returns `idempotency_conflict`. This protects API retries but does not
authorize a second irreversible device dispatch.

The MCP adapter exposes `observe`, `extract`, `act`, `verify`, `run_skill`,
`decide`, `approve`, `get_events`, and `get_trace`. It never exposes device
backend methods.
