from pathlib import Path

import pytest

from haykal.transports.http.idempotency import (
    CachedResponse,
    IdempotencyConflict,
    IdempotencyInProgress,
    IdempotencyStore,
)


def test_incomplete_claim_is_not_reexecuted_after_restart(tmp_path: Path) -> None:
    database = tmp_path / "idempotency.sqlite3"
    first = IdempotencyStore(database)
    assert first.claim("principal", "key", "digest") is None
    restarted = IdempotencyStore(database)
    with pytest.raises(IdempotencyInProgress):
        restarted.claim("principal", "key", "digest")
    with pytest.raises(IdempotencyConflict):
        restarted.claim("principal", "key", "other")
    first.complete("principal", "key", "digest", CachedResponse(200, "application/json", b"{}"))
    assert restarted.claim("principal", "key", "digest") == CachedResponse(
        200, "application/json", b"{}"
    )
