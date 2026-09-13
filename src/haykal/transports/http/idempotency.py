"""Durable request-key ledger for safely replayable HTTP responses."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


class IdempotencyConflict(ValueError):
    """A key was reused by the same principal for different content."""


class IdempotencyInProgress(RuntimeError):
    """The original request may have crossed a side-effect boundary."""


@dataclass(frozen=True, slots=True)
class CachedResponse:
    status_code: int
    media_type: str
    body: bytes


class IdempotencyStore:
    def __init__(self, database: str | Path, *, ttl_s: int = 86_400) -> None:
        self._database = str(database)
        self._ttl_s = ttl_s
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_response (
                    principal TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    response_body BLOB NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY(principal, request_key)
                )
                """
            )

    @staticmethod
    def digest(*, method: str, path: str, body: bytes) -> str:
        message = method.encode() + b"\0" + path.encode() + b"\0" + body
        return hashlib.sha256(message).hexdigest()

    def claim(self, principal: str, key: str, request_digest: str) -> CachedResponse | None:
        now = time.time()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM idempotency_response WHERE expires_at <= ?", (now,))
            row = connection.execute(
                "SELECT request_digest, status_code, media_type, response_body "
                "FROM idempotency_response WHERE principal = ? AND request_key = ?",
                (principal, key),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO idempotency_response VALUES (?, ?, ?, -1, '', X'', ?)",
                    (principal, key, request_digest, now + self._ttl_s),
                )
                connection.commit()
                return None
            connection.commit()
        if str(row["request_digest"]) != request_digest:
            raise IdempotencyConflict("idempotency key was reused with different content")
        if int(row["status_code"]) == -1:
            raise IdempotencyInProgress(
                "original request is incomplete; outcome requires operator reconciliation"
            )
        return CachedResponse(
            status_code=int(row["status_code"]),
            media_type=str(row["media_type"]),
            body=bytes(row["response_body"]),
        )

    def get(self, principal: str, key: str, request_digest: str) -> CachedResponse | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT request_digest, status_code, media_type, response_body "
                "FROM idempotency_response WHERE principal = ? AND request_key = ?",
                (principal, key),
            ).fetchone()
        if row is None:
            return None
        if str(row["request_digest"]) != request_digest:
            raise IdempotencyConflict("idempotency key was reused with different content")
        if int(row["status_code"]) == -1:
            raise IdempotencyInProgress(
                "original request is incomplete; outcome requires operator reconciliation"
            )
        return CachedResponse(
            status_code=int(row["status_code"]),
            media_type=str(row["media_type"]),
            body=bytes(row["response_body"]),
        )

    def complete(
        self,
        principal: str,
        key: str,
        request_digest: str,
        response: CachedResponse,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT request_digest, status_code FROM idempotency_response "
                "WHERE principal = ? AND request_key = ?",
                (principal, key),
            ).fetchone()
            if existing is None or str(existing["request_digest"]) != request_digest:
                connection.rollback()
                raise IdempotencyConflict("idempotency claim is missing or does not match")
            connection.execute(
                "UPDATE idempotency_response SET status_code = ?, media_type = ?, "
                "response_body = ?, expires_at = ? WHERE principal = ? AND request_key = ?",
                (
                    response.status_code,
                    response.media_type,
                    response.body,
                    time.time() + self._ttl_s,
                    principal,
                    key,
                ),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection
