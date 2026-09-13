"""SQLite-backed exclusive device leases with heartbeat and stale recovery."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


class LeaseConflict(RuntimeError):
    """Raised when a live owner already holds the device."""


class LeaseLost(RuntimeError):
    """Raised when a token no longer owns its lease."""


@dataclass(frozen=True, slots=True)
class DeviceLease:
    device_id: str
    owner_id: str
    token: str
    generation: int
    expires_at: float


class DeviceLeaseStore:
    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS device_generation (
                    device_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS device_lease (
                    device_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    generation INTEGER NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def acquire(
        self, device_id: str, owner_id: str, *, ttl_s: float, now: float | None = None
    ) -> DeviceLease:
        current = time.time() if now is None else now
        expires_at = current + ttl_s
        token = uuid.uuid4().hex
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_id, generation, expires_at FROM device_lease WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if row is not None and float(row["expires_at"]) > current:
                raise LeaseConflict(f"device {device_id!r} is leased by {row['owner_id']!r}")
            generation_row = connection.execute(
                "SELECT generation FROM device_generation WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            generation = int(generation_row["generation"]) + 1 if generation_row is not None else 1
            connection.execute(
                """
                INSERT INTO device_generation(device_id, generation)
                VALUES (?, ?)
                ON CONFLICT(device_id) DO UPDATE SET generation=excluded.generation
                """,
                (device_id, generation),
            )
            connection.execute(
                """
                INSERT INTO device_lease(device_id, owner_id, token, generation, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    owner_id=excluded.owner_id,
                    token=excluded.token,
                    generation=excluded.generation,
                    expires_at=excluded.expires_at
                """,
                (device_id, owner_id, token, generation, expires_at),
            )
            connection.commit()
        return DeviceLease(device_id, owner_id, token, generation, expires_at)

    def heartbeat(
        self, lease: DeviceLease, *, ttl_s: float, now: float | None = None
    ) -> DeviceLease:
        current = time.time() if now is None else now
        expires_at = current + ttl_s
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE device_lease SET expires_at = ?
                WHERE device_id = ? AND token = ? AND generation = ? AND expires_at > ?
                """,
                (expires_at, lease.device_id, lease.token, lease.generation, current),
            )
            if cursor.rowcount != 1:
                raise LeaseLost(f"lease for {lease.device_id!r} is no longer owned")
        return DeviceLease(
            lease.device_id, lease.owner_id, lease.token, lease.generation, expires_at
        )

    def release(self, lease: DeviceLease) -> None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "DELETE FROM device_lease WHERE device_id = ? AND token = ? AND generation = ?",
                (lease.device_id, lease.token, lease.generation),
            )
            if cursor.rowcount != 1:
                raise LeaseLost(f"lease for {lease.device_id!r} is no longer owned")

    def reap_expired(self, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "DELETE FROM device_lease WHERE expires_at <= ?",
                (current,),
            )
            return cursor.rowcount
