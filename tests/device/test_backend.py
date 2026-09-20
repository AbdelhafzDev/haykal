from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from haykal.device.backend import (
    DeviceBackendTimeout,
    DeviceBackendUnavailable,
    IrreversibleDispatchUnavailable,
    Uiautomator2Backend,
)
from haykal.device.lease import DeviceLeaseStore
from haykal.device.settings import DeviceStateJournal


class ShellResult:
    output = "com.example/.Ime\n"


class FakeClient:
    def __init__(self) -> None:
        self.info = {"serial": "vm-1"}
        self.calls: list[tuple[object, ...]] = []
        self.fail_hierarchy_once = False

    def shell(self, command: list[str]) -> ShellResult:
        self.calls.append(("shell", *command))
        return ShellResult()

    def dump_hierarchy(self, *, compressed: bool) -> str:
        self.calls.append(("hierarchy", compressed))
        if self.fail_hierarchy_once:
            self.fail_hierarchy_once = False
            raise RuntimeError("service died")
        return "<hierarchy/>"

    def screenshot(self, *, format: str) -> bytes:
        self.calls.append(("screenshot", format))
        return b"png"

    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", x, y))

    def swipe(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("swipe", *args, kwargs))

    def send_keys(self, text: str, *, clear: bool) -> None:
        self.calls.append(("send_keys", text, clear))

    def set_input_ime(self, enable: bool = True) -> None:
        self.calls.append(("set_input_ime", enable))

    def press(self, key: str) -> None:
        self.calls.append(("press", key))

    def window_size(self) -> tuple[int, int]:
        return (1080, 2400)

    def app_current(self) -> dict[str, object]:
        return {"package": "dev.haykal", "activity": ".MainActivity"}


@pytest.mark.asyncio
async def test_backend_operations_and_ime_restore() -> None:
    client = FakeClient()
    backend = Uiautomator2Backend(lambda: client)

    await backend.open()
    assert (await backend.health()).healthy
    snapshot = await backend.snapshot()
    assert (snapshot.width, snapshot.height) == (1080, 2400)
    assert snapshot.package == "dev.haykal"
    assert await backend.hierarchy() == "<hierarchy/>"
    assert await backend.screenshot() == b"png"
    await backend.tap(1, 2)
    await backend.swipe(1, 2, 3, 4, 500)
    await backend.type_text("بيتزا", replace=True)
    await backend.press("back")
    await backend.close()

    assert ("shell", "ime", "set", "com.example/.Ime") in client.calls
    assert ("set_input_ime", True) in client.calls
    assert ("send_keys", "بيتزا", False) in client.calls
    assert ("send_keys", "", False) not in client.calls
    assert ("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_CLEAR_TEXT") in client.calls
    focus_clicks = [
        index for index, call in enumerate(client.calls) if call == ("click", 1, 2)
    ]
    ime_index = client.calls.index(("set_input_ime", True))
    clear_index = client.calls.index(
        ("shell", "am", "broadcast", "-a", "ADB_KEYBOARD_CLEAR_TEXT")
    )
    assert len(focus_clicks) == 2
    assert ime_index < focus_clicks[1] < clear_index


@pytest.mark.asyncio
async def test_backend_recovers_once_from_sync_failure() -> None:
    client = FakeClient()
    client.fail_hierarchy_once = True
    restarts: list[object] = []
    backend = Uiautomator2Backend(lambda: client, restart=restarts.append)
    await backend.open()

    assert await backend.hierarchy() == "<hierarchy/>"
    assert restarts == [client]


@pytest.mark.asyncio
async def test_backend_reports_unavailable_after_one_failed_restart() -> None:
    client = FakeClient()
    restarts: list[object] = []

    def unavailable(*, compressed: bool) -> str:
        del compressed
        raise ConnectionError("injected ADB disconnect")

    client.dump_hierarchy = unavailable  # type: ignore[method-assign]
    backend = Uiautomator2Backend(lambda: client, restart=restarts.append)
    await backend.open()

    with pytest.raises(DeviceBackendUnavailable, match="ADB disconnect"):
        await backend.hierarchy()
    assert restarts == [client]


@pytest.mark.asyncio
async def test_backend_timeout_is_bounded() -> None:
    client = FakeClient()

    def slow_factory() -> FakeClient:
        time.sleep(0.1)
        return client

    backend = Uiautomator2Backend(slow_factory, operation_timeout_s=0.01)
    with pytest.raises(DeviceBackendTimeout):
        await backend.open()


@pytest.mark.asyncio
async def test_irreversible_dispatch_fails_closed_without_audited_transport() -> None:
    client = FakeClient()
    backend = Uiautomator2Backend(lambda: client)
    await backend.open()

    with pytest.raises(IrreversibleDispatchUnavailable):
        await backend.dispatch_once(action_id="act-1", method="click", params={"x": 1})


@pytest.mark.asyncio
async def test_durable_uiautomator_single_shot_never_replays_click(tmp_path: Path) -> None:
    client = FakeClient()
    backend = Uiautomator2Backend(
        lambda: client,
        irreversible_database=tmp_path / "single-shot.sqlite3",
    )
    await backend.open()
    first = await backend.dispatch_once(
        action_id="purchase-1", method="tap", params={"x": 10, "y": 20}
    )
    second = await backend.dispatch_once(
        action_id="purchase-1", method="tap", params={"x": 10, "y": 20}
    )
    assert first.status == "dispatched"
    assert second.status == "dispatched"
    assert second.repeated_request is True
    assert client.calls.count(("click", 10, 20)) == 1


@pytest.mark.asyncio
async def test_interrupted_irreversible_transport_is_unknown_and_never_retried(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    attempts = 0

    def disconnect(_x: int, _y: int) -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("injected disconnect after send")

    client.click = disconnect  # type: ignore[method-assign]
    backend = Uiautomator2Backend(
        lambda: client,
        irreversible_database=tmp_path / "single-shot.sqlite3",
    )
    await backend.open()

    first = await backend.dispatch_once(
        action_id="purchase-unknown", method="tap", params={"x": 10, "y": 20}
    )
    second = await backend.dispatch_once(
        action_id="purchase-unknown", method="tap", params={"x": 10, "y": 20}
    )

    assert first.status == "outcome_unknown"
    assert second.status == "outcome_unknown"
    assert second.repeated_request is True
    assert attempts == 1


@pytest.mark.asyncio
async def test_operations_are_serialized() -> None:
    client = FakeClient()
    active = 0
    maximum_active = 0

    def click(x: int, y: int) -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        active -= 1

    client.click = click  # type: ignore[method-assign]
    backend = Uiautomator2Backend(lambda: client)
    await backend.open()

    await asyncio.gather(*(backend.tap(index, index) for index in range(4)))
    assert maximum_active == 1


@pytest.mark.asyncio
async def test_new_lease_recovers_ime_after_abandoned_backend(tmp_path: Path) -> None:
    database = tmp_path / "device.db"
    leases = DeviceLeaseStore(database)
    journal = DeviceStateJournal(database)
    abandoned = leases.acquire("vm-1", "worker-a", ttl_s=5, now=100)
    first_client = FakeClient()
    first = Uiautomator2Backend(
        lambda: first_client,
        lease=abandoned,
        state_journal=journal,
    )
    await first.open()

    replacement = leases.acquire("vm-1", "worker-b", ttl_s=10, now=106)
    second_client = FakeClient()
    second = Uiautomator2Backend(
        lambda: second_client,
        lease=replacement,
        state_journal=journal,
    )
    await second.open()

    assert second_client.calls[0] == ("shell", "ime", "set", "com.example/.Ime")
    await second.close()
    leases.release(replacement)
    next_lease = leases.acquire("vm-1", "worker-c", ttl_s=10, now=107)
    assert journal.pending_before(next_lease) == []
