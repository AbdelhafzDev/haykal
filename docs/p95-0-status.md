# P95.0 status: baseline, provenance, and regression locks

Decision: **locally complete; blocked on hosted evidence**

## Baseline

- Pre-hardening baseline commit: `f78ca16`.
- The baseline is explicitly no-go and contains the post-Phase-5 review findings.
- Source inventory: 308 tracked candidates, approximately 1.6 MB before Git
  compression.
- Local secret scan found no credential. Four initial findings were inspected:
  two pinned public checksums/revisions, one documentation placeholder, and one
  ignored generated artifact.

## Regression locks

Seven strict expected-failure tests encode five reviewed defect classes:

1. HTTP coordinate risk downgrade.
2. MCP action whose resolved element is a payment control.
3. Signed skill whose harmless semantic name resolves to a payment control.
4. Trace image without an artifact-matching redaction region.
5. Storage-only health reporting ready without a device.
6. An adapter claiming success while the independent expected state is false.
7. A non-cryptographic benchmark version string accepted as a pin.

The tests use strict `xfail`: the host suite remains runnable while an unexpected
pass fails CI and forces the lock to be converted into a normal passing regression
test in the owning remediation phase.

## CI and secret control

- `.github/workflows/p95.yml` runs the release host gate from a fresh checkout,
  the pinned secret scanner, the strict regression-lock count, and actionlint
  1.7.12.
- `scripts/p95-secret-scan.sh` prints only filename, line, and detector type; it
  never prints the candidate value.
- Public Flutter/toolchain revision checksums are documented false positives.
- The dependency audit initially found advisories in pytest 8.4.2 and Starlette
  0.52.1. The locked environment now uses pytest 9.1.1 and Starlette 1.6.0;
  the repeated audit reports no known vulnerability. The local proprietary
  `haykal-runtime` package is expectedly absent from PyPI and is reported as
  unauditable rather than silently treated as an audited public package.

## Local evidence

- Host gate: 483 passed, 7 strict expected failures, 85.37% coverage.
- Ruff formatting/lint, strict mypy over 95 source files, 21 generated schemas,
  source/wheel build, and isolated wheel installation passed.
- Secret scan: zero unallowlisted findings.
- Dependency audit: zero known vulnerabilities in auditable dependencies.
- Workflow lint: actionlint 1.7.12 passed.
- A separate local clone at commit
  `eafd6c2d32f8b95e7e098bff0053d8a04e1cd1df` repeated the secret scan, complete
  host gate, clean wheel installation, dependency audit, and workflow lint
  successfully. This is fresh-checkout evidence, but not hosted evidence.
- Local wheel: `haykal_runtime-0.0.1-py3-none-any.whl` with SHA-256
  `b731e706cdc7896a0cf226f64fb94966d01780051b119fec205d6df643ecb25d`.
- Pre-hardening baseline commit: `f78ca16`.
- P95.0 implementation commit: `c2ef45973a49202800cec59d922033d2b9c0517b`.

## Evidence required to pass

- Local full gate and actionlint succeed after the P95.0 changes.
- P95.0 commit SHA is recorded and the worktree is clean.
- A hosted workflow URL/run identifier proves a fresh checkout passed.

The repository has no configured remote, so hosted evidence cannot yet exist.
P95.0 remains blocked rather than treating local workflow syntax or local tests as
hosted proof.

Score after local evidence: **70/100 official**, **72/100 conditional on the
required hosted fresh-checkout run**.
