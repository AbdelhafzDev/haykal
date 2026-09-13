"""Durable journal for temporary device settings and crash recovery."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .lease import DeviceLease


class DeviceStateRecoveryError(RuntimeError):
    """A pending device setting could not be restored."""


class DeviceStateConflict(RuntimeError):
    """One lease generation attempted to record two different baselines."""


@dataclass(frozen=True, slots=True)
class PendingDeviceSetting:
    device_id: str
    generation: int
    key: str
    original_value: str


class DeviceStateJournal:
    """Persist baselines before mutation and recover them under a newer lease."""

    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS device_state_journal (
                    device_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    setting_key TEXT NOT NULL,
                    original_value TEXT NOT NULL,
                    restored_at REAL,
                    PRIMARY KEY(device_id, generation, setting_key)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def record_baseline(self, lease: DeviceLease, key: str, original_value: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO device_state_journal(
                    device_id, generation, setting_key, original_value, restored_at
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (lease.device_id, lease.generation, key, original_value),
            )
            row = connection.execute(
                """
                SELECT original_value FROM device_state_journal
                WHERE device_id = ? AND generation = ? AND setting_key = ?
                """,
                (lease.device_id, lease.generation, key),
            ).fetchone()
        if row is None or str(row["original_value"]) != original_value:
            raise DeviceStateConflict(
                f"baseline for {lease.device_id!r}/{key!r} changed within one lease"
            )

    def pending_before(self, lease: DeviceLease) -> list[PendingDeviceSetting]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT device_id, generation, setting_key, original_value
                FROM device_state_journal
                WHERE device_id = ? AND generation < ? AND restored_at IS NULL
                ORDER BY generation, setting_key
                """,
                (lease.device_id, lease.generation),
            ).fetchall()
        return [
            PendingDeviceSetting(
                device_id=str(row["device_id"]),
                generation=int(row["generation"]),
                key=str(row["setting_key"]),
                original_value=str(row["original_value"]),
            )
            for row in rows
        ]

    def recover_prior(
        self,
        lease: DeviceLease,
        restore: Callable[[PendingDeviceSetting], None],
    ) -> int:
        recovered = 0
        for setting in self.pending_before(lease):
            try:
                restore(setting)
            except Exception as exc:
                raise DeviceStateRecoveryError(
                    f"failed to restore {setting.key!r} for {setting.device_id!r}"
                ) from exc
            self._mark_restored(setting)
            recovered += 1
        return recovered

    def restore_current(
        self,
        lease: DeviceLease,
        restore: Callable[[PendingDeviceSetting], None],
    ) -> int:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT device_id, generation, setting_key, original_value
                FROM device_state_journal
                WHERE device_id = ? AND generation = ? AND restored_at IS NULL
                ORDER BY setting_key
                """,
                (lease.device_id, lease.generation),
            ).fetchall()
        settings = [
            PendingDeviceSetting(
                device_id=str(row["device_id"]),
                generation=int(row["generation"]),
                key=str(row["setting_key"]),
                original_value=str(row["original_value"]),
            )
            for row in rows
        ]
        for setting in settings:
            try:
                restore(setting)
            except Exception as exc:
                raise DeviceStateRecoveryError(
                    f"failed to restore {setting.key!r} for {setting.device_id!r}"
                ) from exc
            self._mark_restored(setting)
        return len(settings)

    def _mark_restored(self, setting: PendingDeviceSetting) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE device_state_journal SET restored_at = ?
                WHERE device_id = ? AND generation = ? AND setting_key = ?
                  AND restored_at IS NULL
                """,
                (
                    time.time(),
                    setting.device_id,
                    setting.generation,
                    setting.key,
                ),
            )
