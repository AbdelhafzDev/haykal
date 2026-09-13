# Stable MVP plan

This directory is the implementation plan and release contract for the Haykal
MVP. It deliberately separates the product kernel from transports, models, and
device drivers so that the first release is useful without locking the company to
one dependency.

## Outcome

A caller can connect to one controlled Android device and either:

1. Drive it step by step through `observe`, `extract`, `act`, and `verify`; or
2. Start a versioned skill that runs deterministically until it completes, fails,
   reaches an approval gate, or encounters a scene that needs an external decision.

Every action produces enough evidence to answer:

- What did the runtime observe?
- Which element did it resolve and why?
- What data did it extract, from which elements?
- What was executed?
- What changed afterward?
- Did the declared expectation pass?
- Was a human or policy approval required, and what exactly was approved?

## Plan map

| Document | Purpose |
| --- | --- |
| [00-decisions.md](00-decisions.md) | Fixed MVP decisions, four primitives, selector rules, and explicit exclusions |
| [01-product-scope.md](01-product-scope.md) | Users, use cases, requirements including extraction and authoring, release definition |
| [02-architecture.md](02-architecture.md) | Components, extraction pipeline, selection policies, SSE, failure boundaries |
| [03-contracts.md](03-contracts.md) | Normalization, parsers, selector vocabulary, element dictionary, scene, action, extraction, expectation, skill, event, trace |
| [04-delivery-plan.md](04-delivery-plan.md) | Milestones, honest effort, deliverables, exit criteria |
| [05-quality-security.md](05-quality-security.md) | Release gates, datasets, safety, privacy, security |
| [06-risks-and-questions.md](06-risks-and-questions.md) | Risks, M0 decisions, partner questions, kill criteria |
| [07-reference-apps-and-benchmarks.md](07-reference-apps-and-benchmarks.md) | Reference app suite, Matjar fault switches, comparative benchmark |
| [08-skill-authoring.md](08-skill-authoring.md) | Authoring tools, the one-day exercise, authoring rules |
| [09-readiness-scorecard.md](09-readiness-scorecard.md) | Weighted 95/100 plan evaluation and the five M0 evidence points still unearned |
| [10-path-to-95.md](10-path-to-95.md) | Post-Phase-5 remediation and evidence phases from the 70/100 implementation review to a defensible 95/100 |
| [examples/jahez-pizza-offers-lifecycle.md](examples/jahez-pizza-offers-lifecycle.md) | Read-only skill with extraction and escalation |
| [../../jahez-order-pizza-lifecycle.md](../../jahez-order-pizza-lifecycle.md) | Purchase skill with selection policy, approval-bound dispatch, and reconciliation |

## Release principle

The MVP is stable when it satisfies the release gates, not when every planned
feature exists. Unsupported operations return explicit, typed errors. A smaller
deterministic contract is preferable to silent fallback or guessed behavior. A
value that is not on screen is `null`, never inferred.

## Estimated scope

**24–28 engineer-weeks for the stable core, or 14–17 calendar weeks for two
senior engineers.** The broader launch package is 28–32 engineer-weeks.
This includes the reference application suite, extraction, authoring tooling,
and the comparative benchmark, none of which were in the earlier 8–10 week figure.
Model evaluation, third-party app changes, device restrictions, and security
review may extend it. Dates are assigned after Milestone 0.
