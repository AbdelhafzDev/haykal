"""Durable at-most-once dispatch boundary used by the M0 safety spike."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


class SingleShotTransport(Protocol):
    """A transport implementation that performs exactly one low-level call."""

    def call_once(self, method: str, params: dict[str, object]) -> dict[str, object]: ...


class IdempotencyConflict(ValueError):
    """Raised when an action ID is reused for a different request."""


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    action_id: str
    status: str
    receipt: dict[str, object] | None
    repeated_request: bool


class AtMostOnceDispatcher:
    """Never invokes a transport twice for one durable action ID.

    A crash after PREPARED is conservatively treated as an unknown outcome. This
    can sacrifice execution, but it cannot trade safety for a duplicate tap.
    """

    def __init__(self, database: str | Path, transport: SingleShotTransport) -> None:
        self._database = str(database)
        self._transport = transport
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS irreversible_dispatch (
                    action_id TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('prepared', 'dispatched', 'outcome_unknown')),
                    receipt_json TEXT
                )
                """
            )

    @staticmethod
    def _digest(method: str, params: dict[str, object]) -> str:
        payload = json.dumps(
            {"method": method, "params": params},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def dispatch(
        self,
        *,
        action_id: str,
        method: str,
        params: dict[str, object],
    ) -> DispatchOutcome:
        request_digest = self._digest(method, params)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT request_digest, status, receipt_json FROM irreversible_dispatch "
                "WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    raise IdempotencyConflict(f"action ID {action_id!r} has different content")
                status = str(existing["status"])
                if status == "prepared":
                    status = "outcome_unknown"
                    connection.execute(
                        "UPDATE irreversible_dispatch SET status = ? WHERE action_id = ?",
                        (status, action_id),
                    )
                receipt = json.loads(existing["receipt_json"]) if existing["receipt_json"] else None
                connection.commit()
                return DispatchOutcome(action_id, status, receipt, True)
            connection.execute(
                "INSERT INTO irreversible_dispatch "
                "(action_id, request_digest, status) VALUES (?, ?, 'prepared')",
                (action_id, request_digest),
            )
            connection.commit()

        try:
            receipt = self._transport.call_once(method, params)
        except Exception:
            with closing(self._connect()) as connection:
                connection.execute(
                    "UPDATE irreversible_dispatch SET status = 'outcome_unknown' "
                    "WHERE action_id = ?",
                    (action_id,),
                )
            return DispatchOutcome(action_id, "outcome_unknown", None, False)

        encoded_receipt = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE irreversible_dispatch SET status = 'dispatched', receipt_json = ? "
                "WHERE action_id = ?",
                (encoded_receipt, action_id),
            )
        return DispatchOutcome(action_id, "dispatched", receipt, False)

    def inspect(self, action_id: str) -> DispatchOutcome | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT status, receipt_json FROM irreversible_dispatch WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        receipt = json.loads(row["receipt_json"]) if row["receipt_json"] else None
        return DispatchOutcome(action_id, str(row["status"]), receipt, False)


def outcome_as_dict(outcome: DispatchOutcome) -> dict[str, object]:
    """Return a JSON-compatible representation for reports."""

    return asdict(outcome)
