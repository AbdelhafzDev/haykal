# Skill authoring

The MVP makes a bounded reference skill authorable in one working day. This is a
measured usability target for the Matjar offers exercise, not a promise that an
arbitrary production workflow takes one day. Complexity, app instability, and
security review remain legitimate engineering costs.

## Tools

All tools are subcommands of the `haykal` CLI and consume the public contracts.
They use the same observe, extract, and resolve code the runtime uses, so a
selector that passes dry-run behaves identically inside a run.

### `haykal scene`

Observe the current screen and print it.

```bash
haykal scene --device android-vm-03
haykal scene --device android-vm-03 --json > scenes/results.json
haykal scene --device android-vm-03 --sparse    # only elements with text or actions
```

Table output shows id, role, label, normalized label, resource id, bounds,
state flags, and sources. Elements from OCR or vision are marked so the author
knows which labels are fragile.

### `haykal resolve --dry-run`

Test a selector against a live device or a saved scene without acting.

```bash
haykal resolve --scene scenes/results.json \
  --selector '{"role":"button","label":{"any_contains":["أضف","Add"]}}'
```

Output: ranked candidates with score, margin to the next candidate, whether the
selector would be accepted or return `ambiguous_target`, and the dictionary
expansion if a semantic name was used.

### `haykal extract --dry-run`

Test an extraction request against a saved scene or live device.

```bash
haykal extract --scene scenes/results.json --request extract/offers.yaml
```

Output: records as a table, per-field value and source, `null` fields with the
reason, ambiguities, dropped records, and parse details including the digit system.

### `haykal record` (launch package candidate)

Walk through the app by hand while Haykal records.

```bash
haykal record --device android-vm-03 --app dev.haykal.refapps.matjar --out drafts/offers/
```

When shipped, every manual tap or text entry saves the pre and post scenes, the element
that was hit, and a suggested selector for it ranked by stability: resource id
first, then role plus label, then role plus position. It writes a draft skill
with one state per action, a draft element dictionary with placeholder names, and
the scenes as fixtures. The author renames semantic names, adds expectations,
and adds extraction steps. The recorder does not invent expectations; a draft
with missing expectations fails lint.

### `haykal lint`

Validate a skill without a device.

```bash
haykal lint skills/matjar/offers.yaml
```

Checks:

- Unknown selector fields.
- Semantic names used but not defined; defined but unused.
- Dictionary cycles.
- Under-specified selectors.
- States with no expectation or verify.
- Unreachable states; terminal states with outgoing transitions.
- Irreversible action categories without a gate.
- Inputs referenced but not declared; declared but unused.
- Selection policies referencing fields the extraction does not produce.
- Gate material fields not produced by a declared extraction.
- Regex validity and normalization names.

### `haykal replay`

Run a skill against recorded scenes with no device.

```bash
haykal replay skills/matjar/offers.yaml --fixtures drafts/offers/scenes/
```

Every state resolves its selectors and extractions against the fixture scene
recorded for that state and reports what would have been tapped, extracted, or
escalated. Replay is the unit test for a skill and runs in CI.

## The one-day exercise

Performed by an engineer who has not worked on Haykal, on Matjar, timed.

| Step | Target time |
| --- | --- |
| Install Haykal and Matjar on the reference VM from the docs | 45 min |
| Capture the fixture walk-through; use recorder when included, otherwise the documented fixture command | 30 min |
| Name the dictionary entries, add expectations, add the extract step | 2 h |
| Iterate with dry-run and lint until replay passes | 1.5 h |
| Run on device 10 times; fix settle and scroll budgets | 1.5 h |
| Enable `promo_modal` and confirm escalation and resume | 45 min |
| Write the acceptance scenarios | 30 min |

The authoring session passes when its wall-clock total is at or under 8 hours and
the author produces a lint-clean, replay-passing skill. The resulting skill then
runs through an automated 30-clean-start qualification outside the timed authoring
session. Both the authoring time and qualification result are published. A failure
is triaged to tooling, documentation, runtime reliability, or genuine workflow
complexity rather than automatically attributed to one cause.

## Authoring rules

- Prefer resource ids, then role plus label, then role plus containment, then
  position. Never a coordinate.
- Every dictionary label list includes the Arabic and English forms the app
  actually renders. Check both locales with `haykal scene`.
- Every state has an expectation before it acts and a verify after.
- Extract instead of reading text from a tapped element's label. The extraction
  carries evidence; a label does not.
- Gates come from the risk category, not from the author's mood. Lint enforces it.
- A skill targets one app version range. When the app changes, publish a new
  version; do not widen selectors until they match anything.

## Where drafts and skills live

```text
skills/
  <package>/
    <name>.yaml              published, immutable per version
    fixtures/<version>/      recorded scenes used by replay
    CHANGELOG.md             what changed per version and why
drafts/                      recorder output, never loaded by the runtime
```
