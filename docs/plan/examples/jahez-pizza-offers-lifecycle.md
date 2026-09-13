# Lifecycle example: “Show me pizza offers in Jahez”

This is an illustrative lifecycle, not a claim about Jahez's current private UI
or selectors. The skill must be authored and tested against an authorized account
and declared Jahez app version before release. The identical skill, with a
different element dictionary, runs against the Matjar reference app and is the
first reference skill in Milestone 4.

The task is read-only. It discovers and returns visible offers; it does not add an
item to a basket, expose a precise saved address, place an order, or reach a
payment action.

Every selector, extraction field, parser, and event below uses only the vocabulary
defined in [03-contracts.md](../03-contracts.md).

## Skill definition (excerpt)

```yaml
schema_version: "1.0"
kind: skill
metadata:
  name: jahez.list_pizza_offers
  version: 1.0.0
  package: com.jahez.app            # illustrative
  app_versions: ">=9.0,<10.0"        # illustrative
  locales: [ar-SA, en-SA]

inputs:
  query:           {type: string, min_length: 1}
  location:        {type: saved_ref, namespace: locations}
  maximum_results: {type: integer, min: 1, max: 30, default: 10}

elements:
  search_box:     {role: textbox, label: {any_contains: ["بحث", "مطعم", "طبق", "Search"]}}
  results_list:   {role: list, resource_id: {ends_with: "id/search_results"}}
  offer_card:     {role: list_item, within: {semantic_name: results_list}}
  current_price:  {role: text, resource_id: {ends_with: "id/current_price"}, within: {semantic_name: offer_card}}
  original_price: {role: text, resource_id: {ends_with: "id/original_price"}, within: {semantic_name: offer_card}}
  empty_results:  {role: text, text: {any_contains: ["لا توجد نتائج", "No results"]}}
  location_error: {role: text, text: {any_contains: ["غير متاح في موقعك", "not available in your area"]}}
  close_button:   {role: button, label: {any_contains: ["إغلاق", "Close", "لاحقاً"]}}

start: home

states:
  home:
    expect: {visible: {semantic_name: search_box}}
    action: {kind: tap, target: {semantic_name: search_box}}
    verify: {state_equals: {target: {semantic_name: search_box}, state: focused, value: true}}
    next: type_query

  type_query:
    action:
      kind: input_text
      target: {semantic_name: search_box}
      text: "${query}"
      mode: replace
    verify: {text_equals: {target: {semantic_name: search_box}, value: "${query}"}}
    next: submit

  submit:
    action: {kind: press_key, key: search}
    verify:
      any:
        - visible: {semantic_name: results_list}
        - visible: {semantic_name: empty_results}
        - visible: {semantic_name: location_error}
    branches:
      - when: {visible: {semantic_name: results_list}}
        next: collect
      - when: {visible: {semantic_name: empty_results}}
        terminal: completed_empty
      - when: {visible: {semantic_name: location_error}}
        escalate:
          reason: location_unavailable
          allowed_actions: [cancel]

  collect:
    extract:
      as: offers
      group: {by: ancestry, record: {semantic_name: offer_card}}
      fields:
        restaurant:     {selector: {role: text, position: first}, type: text, required: true}
        title:          {selector: {role: text, text: {any_contains: ["خصم", "عرض", "%", "off"]}}, type: text}
        current_price:  {selector: {semantic_name: current_price}, type: money}
        original_price: {selector: {semantic_name: original_price}, type: money}
        delivery_fee:   {selector: {role: text, text: {any_contains: ["توصيل", "Delivery"]}}, type: money}
        rating:         {selector: {role: text, text: {regex: "^[0-9٠-٩۰-۹]\\.[0-9٠-٩۰-۹]$"}}, type: rating, scale: 5}
        thumb:          {selector: {role: image, position: first}, type: image_crop}
      scroll:
        within: {semantic_name: results_list}
        max_pages: 5
        settle: {stable_samples: 2, interval_ms: 250}
      dedupe_by: [restaurant, title, current_price]
      limits: {max_records: "${maximum_results}", max_ms: 30000}
    terminal: completed
```

`original_price` and `current_price` require distinct dictionary selectors in the
supported app version. When the application exposes no distinct original-price
element, extraction returns `original_price: null`; no undefined post-processing
rule guesses from visual order.

## Caller request

```json
{
  "skill": "jahez.list_pizza_offers",
  "version": "1.0.0",
  "inputs": {
    "query": "بيتزا",
    "location": {"namespace": "locations", "reference": "home"},
    "maximum_results": 10
  }
}
```

`location` is a `saved_ref`. It is resolved inside the deployment. The caller and
trace never receive the underlying street address.

## Lifecycle overview

```text
request received
      |
validate skill + inputs + dictionary + selector vocabulary
      |
create durable run
      |
acquire exclusive device lease
      |
check prerequisites
  logged in? location available? supported app version?
      |
launch or foreground Jahez
      |
observe home scene
      |
run deterministic skill states
  home -> type_query -> submit -> collect
      |                             |
      |                       scroll + dedupe
      |                             |
      +------ unknown state -> pause -> needs_decision
                                             |
                                      bounded recovery
                                             |
                                      resume same state
      |
finish when limit / end of list / scroll budget reached
      |
return typed records + evidence
      |
release device lease and apply retention policy
```

## Detailed execution

### 1. Admission and validation

Haykal:

1. Authenticates the caller.
2. Resolves the exact immutable skill version.
3. Lints the skill: selector vocabulary, dictionary cycles, unreachable states,
   expectation coverage. A published skill has already passed this; it is
   repeated so a corrupted registry cannot run.
4. Validates `query`, `location`, and `maximum_results` against the input types.
5. Confirms the skill supports the installed Jahez version and device locale.
6. Creates `run_id` and `trace_id` before touching a device.
7. Acquires the device lease or returns `device_lease_conflict`.

```json
{"sequence": 1, "event_type": "run.started", "payload": {"skill": "jahez.list_pizza_offers@1.0.0"}}
{"sequence": 2, "event_type": "device.lease_acquired", "payload": {"device": "android-vm-03"}}
```

### 2. Prerequisite check

The backend confirms device and UIAutomator2 health, that Jahez is installed at a
supported version, that an authorized account is signed in, that the saved
location resolves, and that no OTP, CAPTCHA, integrity warning, or account
verification flow is active. Those flows are never solved automatically; the run
pauses with `needs_decision` or fails with a declared unsupported condition.

### 3. Initial observation

```text
raw hierarchy + screenshot + timestamps
              |
      accessibility normalization
              |
       OCR if labels are missing
              |
  vision only if the scene remains sparse
              |
       fusion + logical identity
              |
        semantic scene revision 1
```

Illustrative scene element:

```json
{
  "id": "el_search",
  "role": "textbox",
  "label": "ابحث عن مطعم أو طبق",
  "label_normalized": "ابحث عن مطعم او طبق",
  "state": {"enabled": true, "visible": true, "focused": false},
  "actions": ["tap", "input_text"],
  "properties": {
    "label": {"confidence": 0.96, "sources": ["accessibility:node_14", "ocr:block_3"]}
  }
}
```

### 4. Navigate to search

`search_box` expands through the dictionary to `role: textbox` with
`label.any_contains` over the Arabic and English forms. The resolver ranks
candidates; the trace records the expansion:

```json
{
  "event_type": "target.resolved",
  "payload": {
    "dictionary_expansion": {"semantic_name": "search_box", "selector": {"role": "textbox", "label": {"any_contains": ["بحث", "مطعم", "طبق", "Search"]}}},
    "element_id": "el_search", "score": 0.96, "margin": 0.61, "alternatives": [{"element_id": "el_hint", "score": 0.35}]
  }
}
```

If two candidates remain within the ambiguity margin, Haykal returns
`ambiguous_target` with both; it does not tap the higher score silently.

### 5. Enter the Arabic query

```yaml
kind: input_text
target: {semantic_name: search_box}
text: "بيتزا"
mode: replace
verify:
  text_equals: {target: {semantic_name: search_box}, value: "بيتزا"}
```

The action receipt records `input_strategy` as `accessibility_set_text`,
`helper_ime`, or `clipboard_paste`. When the field value cannot be read back, the
verification is `inconclusive` and the skill follows its declared branch rather
than inventing success.

### 6. Submit and recognize results

`press_key: search` then `verify.any` over three defined semantic names. The
branch table decides: results continue to `collect`, empty results complete with
an empty list, location error escalates with `cancel` as the only allowed action.

### 7. Extract offer cards

Extraction is observation, not an action. Grouping is `ancestry` on `offer_card`.
Each field binds by selector inside the record and parses by type.

```json
{
  "record_id": "rec:sha256:...",
  "fields": {
    "restaurant":     {"raw": "بيتزا مايسترو", "normalized": "بيتزا مايسترو"},
    "title":          {"raw": "خصم ٣٠٪ على البيتزا الكبيرة", "normalized": "خصم 30% على البيتزا الكبيره"},
    "current_price":  {"amount": 42.0, "currency": "SAR", "raw": "٤٢ ر.س", "digits": "arabic-indic"},
    "original_price": {"amount": 60.0, "currency": "SAR", "raw": "٦٠ ر.س", "digits": "arabic-indic"},
    "delivery_fee":   {"amount": 5.0, "currency": "SAR", "raw": "توصيل ٥ ر.س", "digits": "arabic-indic"},
    "rating":         {"value": 4.6, "scale": 5, "raw": "٤.٦"},
    "thumb":          {"artifact": "sha256:..."}
  },
  "evidence": {
    "restaurant":     {"scene_id": "scn_01J...", "element_ids": ["el_c2_name"],  "sources": ["accessibility"]},
    "title":          {"scene_id": "scn_01J...", "element_ids": ["el_c2_badge"], "sources": ["accessibility", "ocr"]},
    "current_price":  {"scene_id": "scn_01J...", "element_ids": ["el_c2_p1"],    "sources": ["ocr"]},
    "original_price": {"scene_id": "scn_01J...", "element_ids": ["el_c2_p2"],    "sources": ["ocr"]},
    "delivery_fee":   {"scene_id": "scn_01J...", "element_ids": ["el_c2_fee"],   "sources": ["accessibility"]},
    "rating":         {"scene_id": "scn_01J...", "element_ids": ["el_c2_rate"],  "sources": ["accessibility"]},
    "thumb":          {"scene_id": "scn_01J...", "element_ids": ["el_c2_img"],   "sources": ["accessibility"]}
  },
  "anchor": {"element_id": "el_c2", "scene_revision": 4},
  "ambiguities": []
}
```

A card with no price renders `current_price: null` with `evidence: null`. A card
with three price-like texts renders `null` and lists all three element IDs under
`ambiguities.current_price`. Nothing is inferred from layout.

### 8. Scroll, settle, and deduplicate

If fewer than `maximum_results` records exist, the runtime swipes inside
`results_list`, waits for two stable fingerprints at 250 ms, and extracts again.
Dedupe uses the declared signature `[restaurant, title, current_price]` plus
tracked element identity. Collection stops on `max_records`, `end_of_list`,
`no_new_records` after two scrolls, `max_pages`, or `max_ms`. A budget stop
returns `truncated: true` with the `stop_reason`. `request_satisfied` records
whether the requested count was reached, independently of `source_exhausted`.

### 9. Unknown screen escalation

A promotional modal covers the results. No branch matches, so the run pauses:

```json
{
  "event_type": "run.needs_decision",
  "payload": {
    "reason": "unrecognized_screen",
    "run_state": "collect",
    "scene_id": "scn_01K...",
    "allowed_actions": ["tap", "press_key", "cancel"],
    "candidate_targets": [
      {"element_id": "el_close", "role": "button", "label": "إغلاق", "matches_semantic_name": "close_button"}
    ],
    "expires_at": "2026-09-13T10:15:00Z"
  }
}
```

The runtime notes that `el_close` matches the dictionary entry `close_button`
even though the state did not expect it. The caller submits one bounded decision:

```json
{
  "kind": "tap",
  "target": {"element_id": "el_close", "scene_revision": 7},
  "expect": {"not_visible": {"element_id": "el_close", "scene_revision": 7}}
}
```

Haykal re-resolves, executes, verifies, records a candidate patch proposing a new
branch in `collect` for `visible: close_button`, and resumes `collect`. The patch
is not promoted automatically.

If the caller does not answer before `expires_at`, the run moves to `suspended`.
A dedicated device may stay parked; otherwise the hold TTL persists a checkpoint
and releases the lease. Resume reacquires a device and starts with a fresh scene.

### 10. Completion

```json
{
  "run_id": "run_01J...",
  "status": "completed",
  "skill": "jahez.list_pizza_offers@1.0.0",
  "inputs_echo": {"query": "بيتزا", "location": "home", "maximum_results": 10},
  "observed_at": "2026-09-13T10:05:00Z",
  "extraction": {"extraction_id": "ext_01J...", "request_satisfied": true, "source_exhausted": false, "truncated": true, "stop_reason": "max_records", "records": 10, "dropped_records": 1},
  "offers": [
    {
      "restaurant": "بيتزا مايسترو",
      "title": "خصم ٣٠٪ على البيتزا الكبيرة",
      "current_price": {"amount": 42.0, "currency": "SAR"},
      "original_price": {"amount": 60.0, "currency": "SAR"},
      "delivery_fee": {"amount": 5.0, "currency": "SAR"},
      "rating": 4.6,
      "thumb": "artifact:sha256:...",
      "evidence": "trace://run_01J.../ext_01J.../rec:sha256:..."
    }
  ],
  "warnings": ["Offers and prices can change after observation."],
  "trace_id": "trc_01J..."
}
```

`dropped_records: 1` means one card lacked the required `restaurant` field and is
listed in the extraction result with its reason. The caller renders offers in
Arabic or English; thumbnails are crops, so no full screenshot leaves the runtime.

### 11. Cleanup

1. Persist the terminal run event and result artifact.
2. Restore any temporary input method or device setting.
3. Return the app to the configured neutral state if policy permits.
4. Release the exclusive device lease.
5. Apply artifact retention and redaction rules.

Cleanup failure is traced and surfaced independently; it does not rewrite a
successfully completed read-only result.

## Where gates apply

This skill contains no purchase gate because it never proposes a purchase.
Permission prompts, OTPs, CAPTCHAs, and account recovery are escalation states,
not branches the skill dismisses.

## Acceptance scenarios

Each scenario names the Matjar fault switch that reproduces it.

| Scenario | Switch |
| --- | --- |
| Arabic query with accessibility-rich results | none |
| English query in Arabic locale | locale `en-US` |
| OCR supplementation for price labels | `sparse_cards` partial |
| Hierarchy-sparse cards requiring vision | `sparse_cards` |
| Arabic-Indic digits in every price and rating | `arabic_indic_digits` |
| No results | query `zzzz` |
| Promotional modal, bounded resume, candidate patch recorded | `promo_modal` |
| Decision expires, run suspended, later resumed | `promo_modal` + no decision |
| Location unavailable, cancel only | `address_out_of_area` |
| Session expired | `otp_challenge` |
| Duplicate cards after scrolling deduped | default paging |
| End of list and partial result on budget | `maximum_results: 30` |
| Card with three prices reported as ambiguity | `duplicate_labels` |
| Process restart while paused, idempotent resume | harness kill |
| Slow animations respected by settle | `slow_settle` |
