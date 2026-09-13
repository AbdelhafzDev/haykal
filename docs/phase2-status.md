# Phase 2 implementation status

Phase 2 implementation finished on 2026-09-13. The scene, fusion, adjacent-frame
identity, selector, and extraction kernels are implemented and pass the local
host suite. The real UIAutomator2 path is accepted on the API 37 Pixel VM against
Matjar. Formal release acceptance remains blocked by the Milestone 0 OCR/vision
selection and the full labelled transition/extraction datasets.

## Implemented

- Bounded, entity-safe Android hierarchy parser with canonical roles, state,
  actions, ancestry, and Compose-style descendant-label lifting.
- Swappable normalized JSON OCR and vision adapters with time/detection limits,
  strict output validation, and SHA-256 model/weight identity.
- Accessibility quality policy that requests fallback only when evidence or a
  caller requirement needs it, with explicit unavailable/timeout/failure states.
- Deterministic cross-source fusion using resource IDs, geometry, Arabic-aware
  text similarity, and role compatibility.
- Per-property confidence and raw/adaptor evidence sources on every synthesized
  property.
- Immutable raw observation validation, deterministic scene digests, bounded
  capture-coherence retries, and fallback skew rejection.
- Session-scoped adjacent-frame IDs with monotonic revision enforcement,
  one-to-one matching, ambiguity abstention, and expired/new identity reporting.
- Semantic selector evaluation including dictionary expansion, RTL text matching,
  state, ancestry, proximity, position, and bounded regex input.
- Typed extraction for single, ancestry, repeat, and row groups; scoped field
  binding; text/number/money/rating/duration/boolean parsing; cross-page dedupe;
  budgets; relocatable anchors; ambiguity reports; privacy transforms; and PNG
  crops stored by content digest.
- On-demand extraction enrichment that advances the scene revision, runs only
  required missing adapters, preserves the original input scene ID, and fails
  closed when the requested evidence remains unavailable.
- Transparent precision/recall/F1, extraction-value, record-boundary, and IDF1
  metric functions.
- A repeatable host gate and a real-emulator gate covering both reference apps,
  two coherent Matjar scenes, semantic quality, and unchanged-frame ID stability.

## Latest local evidence

- Host: 419 Python tests pass with 86.88% coverage; Ruff, mypy,
  locked dependency sync, all 13 generated-schema drift checks, and actionlint
  1.7.12 pass.
- Live VM: API 37 ARM64 Pixel, UIAutomator2, Matjar foreground.
- Live second scene: 54 elements, 6 actionable controls, 100% labelled actionable
  ratio, 94.1176% meaningful accessibility coverage, quality score 0.988235,
  no fallback and no warnings.
- Adjacent unchanged frame: 54/54 identities matched; zero new, expired, or
  ambiguous identities.
- Capture: hierarchy and screenshot persisted by SHA-256; latest observed skew
  remained under the 500 ms fusion limit.

Generated local evidence is under `reports/m2/` and intentionally ignored because
screenshots may contain sensitive data.

## Exit criteria

| Criterion | Status | Evidence or blocker |
| --- | --- | --- |
| Every synthesized property identifies evidence | passed | fusion and lifted-label tests |
| Raw evidence immutable and deterministic reconstruction | passed | artifact integrity and committed golden scene tests |
| Missing perception sources degrade explicitly | passed | required-source and unavailable-adapter tests |
| No extracted value without element evidence | passed | binding, ambiguity, privacy, crop, and source tests |
| Identity precision/recall/IDF1 at least 95% | pending labelled gate | algorithm and live unchanged-frame smoke pass; full transition corpus is not yet present |
| Extraction presence P/R and value accuracy at least 98% | pending labelled gate | functional cases pass; full declared field corpus is not yet present |
| Extraction record boundaries at least 99% | provisional only | 100-card synthetic boundary test passes; the complete RTL/Compose/WebView/Flutter/scroll/dialog matrix is pending |
| Production OCR and vision fallback | blocked by M0 | adapter contract passes; engine/weight benchmark and commercial license decision remain open |
| Hosted API 35 gate | configured, awaiting remote | `.github/workflows/phase2.yml`; repository has no GitHub remote |

Phase 2 is **implementation-complete and locally integrated**, but it is not yet a
release-accepted milestone. Claiming the numerical release gates now would confuse
synthetic correctness with measured generalization. Those gates stay visible and
blocking until the labelled data and selected local models are checked in.
