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
| Caller or skill downgrades action risk | critical | Runtime-owned monotonic risk floor after target resolution across HTTP, MCP, Python, recovery, and skills; bound internal approval capability; irreversible/unknown single-shot dispatch | resolved in P95.1 by transport/skill regressions, property testing, and API 37 Matjar approval evidence |
| Trace/screenshot disclosure | high | Images omitted by default; image-enabled exports require wildcard or per-artifact regions, validate decoded bounds, and abort transactionally on absent/malformed coverage; raw/public trace state is explicit | resolved for the exporter in P95.1; deployments still own the correctness and completeness of configured pixel regions |
| Backup disclosure | high | No embedded credentials, integrity manifest, operational requirement for encrypted destination | accepted limitation; blocks deployments without encrypted backup storage |
| UI text/prompt injection | high | Screen text is data only; deterministic selector/extraction contracts; recovery decisions restricted to verified reversible navigation | resolved by architecture |
| Candidate-patch poisoning | high | Patch is redacted, inert, and never promoted automatically | resolved |
| ADB network exposure | high | Controlled local VM is the supported boundary | deployment blocker if ADB is remotely exposed |
| Dependency/model compromise | high | Locked Python graph, SBOM/license evidence, replaceable model adapter, no production model download at runtime | Python controls implemented; OCR/vision selection still blocking |
| Cross-session leakage | high | Exclusive lease and session-scoped identities; content-addressed artifacts remain deployment-scoped | multi-tenant use unsupported |
| Path traversal during restore | high | Manual archive extraction rejects absolute/traversal/link/device members and verifies declared digests | resolved and tested |
| Resource exhaustion and interrupted infrastructure | medium | Bounded scene history and workflow limits; externally supervised process/SQLite/artifact/lease/disk faults; live ADB/helper/IME recovery; sampled resource limits and online trace retention | P95.2 implementation and 30-minute development evidence complete locally; the eight-hour release soak remains P95.5 |

Any regression in a critical row blocks release. High residual conditions marked
as deployment blockers must be checked in the deployment acceptance record.

The P95.1 evidence and residual limitations are recorded in
[`p95-1-status.md`](p95-1-status.md). This closes the two reviewed implementation
defects; it does not substitute for the clean API 34/35 matrix, hosted CI,
external benchmark, regional authorization, or long soak required by later
phases.
