# Phase 5 security regression report

- Date: 2026-09-13
- Command: `uv run pytest -q tests/hardening tests/workflows/test_approval.py
  tests/m0/test_single_shot.py tests/transports/test_idempotency.py
  tests/skills/test_registry.py tests/transports/test_http.py`
- Result: 27 passed, zero failed
- Remaining warning: Starlette's test client references a deprecated AnyIO alias;
  this is dependency noise and does not bypass a security assertion.

Covered controls include approval credential separation, authenticated detailed
diagnostics, public response redaction, default image omission, mandatory image
regions, retention preview/application, archive traversal rejection, backup
integrity, trace database migration, and static export privacy.

This regression report is not a penetration test. Deployment conditions and open
findings are tracked in `docs/threat-model.md`.
