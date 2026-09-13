# MVP plan readiness scorecard

This score measures the quality and implementability of the written MVP plan. It
does not claim that the product already meets its release gates. Evidence replaces
points only after implementation; the plan cannot award itself runtime reliability.

## Score: 95/100

| Dimension | Weight | Score | Evidence in the plan |
| --- | ---: | ---: | --- |
| Product value and positioning | 15 | 15 | Protocol-first semantic runtime, deterministic skills, Arabic/RTL and private deployment wedge |
| Stable MVP boundary | 15 | 14 | Android VM, one backend, two reference apps, four primitives; optional adapters and recorder separated |
| Architecture | 15 | 14 | Device/perception separation, immutable scenes, enrichment, identity, relocatable anchors, durable journal |
| Contract completeness | 15 | 14 | Bounded selectors, typed extraction, formal state failure routes, idempotency and at-least-once events |
| Safety and privacy | 20 | 19 | Separate approval authority, material/target binding, masked extraction, at-most-once dispatch and reconciliation |
| Quality and benchmark credibility | 15 | 14 | Non-gameable metrics, fault injection, two tracks, exact pinning, 30-run distributions and confidence intervals |
| Delivery realism | 5 | 5 | Milestone exits, dependency spikes, 24–28 engineer-week stable-core estimate and explicit launch package |
| **Total** | **100** | **95** | |

## The five unearned points

These are deliberately not filled with prose. Milestone 0 must produce evidence:

1. **OCR/vision selection (1 point):** choose commercially safe, pinned backends
   from the labelled Arabic/English benchmark.
2. **Irreversible dispatch proof (1 point):** demonstrate at the wire/device layer
   that a UIAutomator2 timeout or restart cannot cause a second input event.
3. **Design-partner validation (1 point):** confirm one authorized workflow,
   device ownership, approval policy, and willingness to adopt primitives/skills.
4. **Competitor reproducibility (1 point):** pin and run Agent Device; record
   whether Maestro MCP and ARTEMIS can join the parity track without special
   treatment.
5. **Authoring usability (1 point):** a non-core engineer completes the bounded
   Matjar exercise in eight hours and the resulting skill passes 30 automated
   clean starts.

## Score protection rules

- A failed M0 assumption changes the plan and score through an ADR; it is not
  hidden by lowering a test target after seeing results.
- Safety gates are binary. Any duplicate irreversible dispatch, unauthorized
  approval, secret in an exported trace, or unsafe benchmark action blocks release.
- Competitive wins are not required. Reproducibility, honest losses, and clear
  separation between step-caller and compiled-skill tracks are required.
- “Unsupported” is acceptable only when returned explicitly before an unsafe or
  misleading action.

## Implementation start decision

Scaffolding contracts, parsers, fixtures, and Matjar may begin immediately.
Public stability promises for perception, irreversible actions, and comparative
performance remain provisional until their corresponding M0 evidence is attached
to ADRs.
