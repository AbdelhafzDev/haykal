# ADR 0004: evidence-backed scene and extraction kernel

- Status: accepted for implementation
- Date: 2026-09-13

## Decision

Phase 2 keeps raw UIAutomator2 hierarchy XML and PNG screenshots immutable in the
content-addressed artifact store. A bounded, entity-safe parser normalizes the
hierarchy. It may lift descendant text onto an otherwise unlabelled actionable
control, but the synthesized label cites the descendant raw node IDs rather than
the control itself.

Accessibility quality is measured over meaningful controls and content nodes,
not structural containers. OCR and vision execute only when the quality policy or
caller requires them. Both are swappable adapters whose code/model/weight SHA-256
identities and normalized outputs become evidence artifacts. Haykal does not ship
or select production weights until the Milestone 0 corpus and license review are
complete.

Fusion is deterministic and records confidence plus evidence sources per
property. Adjacent-frame identity combines resource IDs, semantic fingerprints,
ancestry, geometry, and raw-node continuity. Raw continuity cannot win alone: it
is scored with role and geometry because a node index may refer to a different
element after a hierarchy mutation.

Extraction groups by single scope, matching ancestry, repeated sibling shape, or
visual rows. Ambiguity produces a dropped field/record report; it never selects
the first candidate implicitly. Parsed fields cite scene, element, property
sources, and optional content-addressed crop evidence.

## Consequences

- The same raw observation reconstructs the same semantic digest.
- Missing OCR or vision is visible in warnings and required sources fail closed.
- Model providers can change without changing the public scene contract.
- Rule confidence is a ranking value, not a calibrated probability.
- Formal identity and extraction release gates require labelled datasets; a
  passing unit suite or unchanged-screen live smoke is not substituted for them.
