# MVP threat model

## Boundary and assets

The trusted boundary is one private host, its Haykal process, its state directory,
and one exclusively leased Android VM. Screen content, application text, imported
skills, candidate patches, API input, and benchmark adapter output are untrusted.
Assets include device control, logged-in sessions, extracted personal data,
screenshots, approval capability, skill signing keys, and execution history.

## Findings

| Threat | Severity | Control | Residual status |
| --- | --- | --- | --- |
| Unauthorized device control | critical | Loopback default, bearer auth, mutation idempotency, exclusive lease; remote bind requires explicit TLS-proxy acknowledgement | resolved for supported deployment |
| Approval replay/substitution | critical | Separate credential, exact challenge review, HMAC capability stored by hash, nonce/expiry, run/skill/action/target/material binding, atomic consume | resolved and tested |
| Duplicate irreversible tap | critical | Raw UIAutomator2 single-shot transport, durable dispatch ledger, no transparent recovery, Orders reconciliation | resolved on Matjar; broader device matrix pending |
| Caller or skill downgrades action risk | critical | Planned P95.1 effective-risk floor after target resolution across HTTP, MCP, Python, recovery, and skills | open release blocker; primitive risk is caller-controlled and ordinary skill classification lacks resolved target context |
| Trace/screenshot disclosure | high | Images omitted by default; planned P95.1 per-artifact fail-closed region coverage and expanded text corpus | open release blocker; an unmatched artifact can currently export unchanged |
| Backup disclosure | high | No embedded credentials, integrity manifest, operational requirement for encrypted destination | accepted limitation; blocks deployments without encrypted backup storage |
| UI text/prompt injection | high | Screen text is data only; deterministic selector/extraction contracts; recovery decisions restricted to verified reversible navigation | resolved by architecture |
| Candidate-patch poisoning | high | Patch is redacted, inert, and never promoted automatically | resolved |
| ADB network exposure | high | Controlled local VM is the supported boundary | deployment blocker if ADB is remotely exposed |
| Dependency/model compromise | high | Locked Python graph, SBOM/license evidence, replaceable model adapter, no production model download at runtime | Python controls implemented; OCR/vision selection still blocking |
| Cross-session leakage | high | Exclusive lease and session-scoped identities; content-addressed artifacts remain deployment-scoped | multi-tenant use unsupported |
| Path traversal during restore | high | Manual archive extraction rejects absolute/traversal/link/device members and verifies declared digests | resolved and tested |
| Resource exhaustion | medium | Bounded scene history, step/scroll/decision limits, configurable retention, planned P95.2 externally injected fault/growth harness | current harness is a storage-concurrency smoke; real failure and eight-hour device evidence pending |

Any regression in a critical row blocks release. High residual conditions marked
as deployment blockers must be checked in the deployment acceptance record.
