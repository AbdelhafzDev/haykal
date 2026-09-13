"""Production construction with exclusive lease, heartbeat, and state recovery."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from haykal.artifacts import ArtifactStore
from haykal.device import (
    DeviceLease,
    DeviceLeaseStore,
    DeviceStateJournal,
    Uiautomator2Backend,
)
from haykal.traces import TraceStore

from .session import RuntimeSession


class ManagedRuntimeSession(RuntimeSession):
    def __init__(
        self,
        *,
        lease_store: DeviceLeaseStore,
        lease: DeviceLease,
        heartbeat_s: float,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._lease_store = lease_store
        self._lease = lease
        self._heartbeat_s = heartbeat_s
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def open(self) -> None:
        if self._heartbeat_task is not None:
            return
        try:
            await super().open()
        except BaseException:
            with suppress(Exception):
                self._lease_store.release(self._lease)
            raise
        self._heartbeat_task = asyncio.create_task(self._heartbeat())

    async def close(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        try:
            await super().close()
        finally:
            with suppress(Exception):
                self._lease_store.release(self._lease)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_s)
            self._lease = await asyncio.to_thread(
                self._lease_store.heartbeat,
                self._lease,
                ttl_s=self._heartbeat_s * 3,
            )


def build_runtime(
    *,
    serial: str,
    session_id: str,
    state_directory: str | Path,
    heartbeat_s: float = 20.0,
) -> ManagedRuntimeSession:
    root = Path(state_directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifacts_path = root / "artifacts"
    database = root / "runtime.sqlite3"
    leases = DeviceLeaseStore(database)
    lease = leases.acquire(serial, session_id, ttl_s=heartbeat_s * 3)
    journal = DeviceStateJournal(database)
    backend = Uiautomator2Backend.from_serial(
        serial,
        irreversible_database=database,
        lease=lease,
        state_journal=journal,
    )
    return ManagedRuntimeSession(
        session_id=session_id,
        backend=backend,
        artifact_store=ArtifactStore(artifacts_path),
        trace_store=TraceStore(database),
        lease_store=leases,
        lease=lease,
        heartbeat_s=heartbeat_s,
    )
