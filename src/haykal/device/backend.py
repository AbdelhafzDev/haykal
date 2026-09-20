"""Asynchronous device boundary with serialized, bounded operations."""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, TypeVar, cast

from .lease import DeviceLease
from .settings import DeviceStateJournal, PendingDeviceSetting
from .single_shot import AtMostOnceDispatcher, DispatchOutcome

T = TypeVar("T")


class DeviceBackendError(RuntimeError):
    """Base typed backend failure."""


class DeviceBackendTimeout(DeviceBackendError):
    """A bounded operation exceeded its deadline."""


class DeviceBackendUnavailable(DeviceBackendError):
    """The backend is unavailable after bounded recovery."""


class IrreversibleDispatchUnavailable(DeviceBackendError):
    """The backend has no audited single-shot transport."""


@dataclass(frozen=True, slots=True)
class DeviceHealth:
    healthy: bool
    detail: str


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    width: int
    height: int
    density: float
    rotation: int
    package: str
    activity: str | None
    keyboard_visible: bool


class DeviceBackend(Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def health(self) -> DeviceHealth: ...
    async def snapshot(self) -> DeviceSnapshot: ...
    async def hierarchy(self) -> str: ...
    async def screenshot(self) -> bytes: ...
    async def tap(self, x: int, y: int) -> None: ...
    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None: ...
    async def type_text(self, text: str, *, replace: bool) -> None: ...
    async def press(self, key: str) -> None: ...
    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome: ...


class PngImage(Protocol):
    def save(self, stream: BinaryIO, *, format: str) -> None: ...


class UiautomatorClient(Protocol):
    @property
    def info(self) -> object: ...
    def shell(self, command: list[str]) -> object: ...
    def dump_hierarchy(self, *, compressed: bool) -> str: ...
    def screenshot(self, *, format: str) -> bytes | PngImage: ...
    def click(self, x: int, y: int) -> object: ...
    def swipe(self, x1: int, y1: int, x2: int, y2: int, *, duration: float) -> object: ...
    def set_input_ime(self, enable: bool = True) -> object: ...
    def send_keys(self, text: str, *, clear: bool) -> object: ...
    def press(self, key: str) -> object: ...
    def reset_uiautomator(self) -> object: ...
    def window_size(self) -> tuple[int, int]: ...
    def app_current(self) -> dict[str, object]: ...


class _UiautomatorSingleShotTransport:
    """One raw client call with no backend recovery replay."""

    def __init__(self, client: Callable[[], UiautomatorClient]) -> None:
        self._client = client

    def call_once(self, method: str, params: dict[str, object]) -> dict[str, object]:
        client = self._client()
        if method != "tap":
            raise ValueError(f"single-shot UIAutomator transport does not support {method!r}")
        x, y = params.get("x"), params.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            raise ValueError("single-shot tap requires integer x and y")
        client.click(x, y)
        return {"method": "tap", "accepted": True}


class Uiautomator2Backend:
    """Serialize synchronous UIAutomator2 calls behind async deadlines."""

    def __init__(
        self,
        client_factory: Callable[[], UiautomatorClient],
        *,
        operation_timeout_s: float = 10.0,
        input_timeout_s: float = 30.0,
        restart: Callable[[UiautomatorClient], None] | None = None,
        irreversible_dispatcher: AtMostOnceDispatcher | None = None,
        irreversible_database: str | Path | None = None,
        lease: DeviceLease | None = None,
        state_journal: DeviceStateJournal | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._timeout = operation_timeout_s
        self._input_timeout = input_timeout_s
        self._restart = restart
        if irreversible_dispatcher is not None and irreversible_database is not None:
            raise ValueError("provide an irreversible dispatcher or database, not both")
        self._irreversible_dispatcher = irreversible_dispatcher
        self._lease = lease
        self._state_journal = state_journal
        self._client: UiautomatorClient | None = None
        self._lock = asyncio.Lock()
        self._prior_ime: str | None = None
        self._last_tap: tuple[int, int] | None = None
        if irreversible_database is not None:
            self._irreversible_dispatcher = AtMostOnceDispatcher(
                irreversible_database,
                _UiautomatorSingleShotTransport(self._require_client),
            )

    @classmethod
    def from_serial(
        cls,
        serial: str,
        *,
        operation_timeout_s: float = 10.0,
        input_timeout_s: float = 30.0,
        irreversible_dispatcher: AtMostOnceDispatcher | None = None,
        irreversible_database: str | Path | None = None,
        lease: DeviceLease | None = None,
        state_journal: DeviceStateJournal | None = None,
    ) -> Uiautomator2Backend:
        """Construct the shipped backend from the pinned UIAutomator2 package."""

        from uiautomator2 import connect  # type: ignore[import-untyped]

        def factory() -> UiautomatorClient:
            return cast(UiautomatorClient, connect(serial))

        def restart(client: UiautomatorClient) -> None:
            client.reset_uiautomator()

        return cls(
            factory,
            operation_timeout_s=operation_timeout_s,
            input_timeout_s=input_timeout_s,
            restart=restart,
            irreversible_dispatcher=irreversible_dispatcher,
            irreversible_database=irreversible_database,
            lease=lease,
            state_journal=state_journal,
        )

    async def open(self) -> None:
        async with self._lock:
            if self._client is not None:
                return
            self._client = await self._bounded(self._client_factory)
            try:
                if self._lease is not None and self._state_journal is not None:
                    await self._bounded(self._recover_prior_state)
                self._prior_ime = await self._read_ime()
                lease = self._lease
                journal = self._state_journal
                if self._prior_ime and lease is not None and journal is not None:
                    prior_ime = self._prior_ime
                    await self._bounded(
                        lambda: journal.record_baseline(lease, "default_input_method", prior_ime)
                    )
            except BaseException:
                self._client = None
                self._prior_ime = None
                raise

    async def close(self) -> None:
        async with self._lock:
            if self._client is None:
                return
            try:
                if self._lease is not None and self._state_journal is not None:
                    await self._bounded(self._restore_current_state)
                elif self._prior_ime:
                    prior = self._prior_ime
                    await self._call(lambda client: client.shell(["ime", "set", prior]))
            finally:
                self._client = None
                self._prior_ime = None

    async def health(self) -> DeviceHealth:
        try:
            info = await self._serialized(lambda client: client.info)
        except DeviceBackendError as exc:
            return DeviceHealth(False, str(exc))
        return DeviceHealth(True, f"connected: {bool(info)}")

    async def snapshot(self) -> DeviceSnapshot:
        return await self._serialized(self._snapshot)

    async def hierarchy(self) -> str:
        value = await self._serialized(lambda client: client.dump_hierarchy(compressed=False))
        if not isinstance(value, str) or not value.strip():
            raise DeviceBackendUnavailable("UIAutomator2 returned an empty hierarchy")
        return value

    async def screenshot(self) -> bytes:
        image = await self._serialized(lambda client: client.screenshot(format="pillow"))
        if isinstance(image, bytes):
            return image
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    async def tap(self, x: int, y: int) -> None:
        await self._serialized(lambda client: client.click(x, y))
        self._last_tap = (x, y)

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        await self._serialized(
            lambda client: client.swipe(x1, y1, x2, y2, duration=duration_ms / 1000)
        )

    async def type_text(self, text: str, *, replace: bool) -> None:
        try:
            async with self._lock:
                await self._call(
                    lambda client: self._type_text(client, text, replace=replace),
                    timeout_s=self._input_timeout,
                )
        finally:
            self._last_tap = None

    async def press(self, key: str) -> None:
        await self._serialized(lambda client: client.press(key))

    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome:
        dispatcher = self._irreversible_dispatcher
        if dispatcher is None:
            raise IrreversibleDispatchUnavailable(
                "no audited single-shot transport configured; irreversible action rejected"
            )
        async with self._lock:
            return await self._bounded(
                lambda: dispatcher.dispatch(action_id=action_id, method=method, params=params)
            )

    async def _serialized(self, operation: Callable[[UiautomatorClient], T]) -> T:
        async with self._lock:
            return await self._call(operation)

    async def _call(
        self,
        operation: Callable[[UiautomatorClient], T],
        *,
        timeout_s: float | None = None,
    ) -> T:
        client = self._require_client()
        try:
            return await self._bounded(lambda: operation(client), timeout_s=timeout_s)
        except DeviceBackendTimeout:
            raise
        except Exception as first_error:
            restart = self._restart
            if restart is None:
                raise DeviceBackendUnavailable(str(first_error)) from first_error
            try:
                await self._bounded(lambda: restart(client))
                return await self._bounded(lambda: operation(client), timeout_s=timeout_s)
            except Exception as recovery_error:
                raise DeviceBackendUnavailable(str(recovery_error)) from recovery_error

    async def _bounded(
        self,
        operation: Callable[[], T],
        *,
        timeout_s: float | None = None,
    ) -> T:
        deadline = self._timeout if timeout_s is None else timeout_s
        try:
            return await asyncio.wait_for(asyncio.to_thread(operation), timeout=deadline)
        except TimeoutError as exc:
            raise DeviceBackendTimeout(f"operation exceeded {deadline:.3f}s") from exc

    def _require_client(self) -> UiautomatorClient:
        if self._client is None:
            raise DeviceBackendUnavailable("backend is not open")
        return self._client

    async def _read_ime(self) -> str | None:
        client = self._require_client()
        try:
            response = await self._bounded(
                lambda: client.shell(["settings", "get", "secure", "default_input_method"])
            )
        except Exception:
            return None
        output = getattr(response, "output", response)
        return str(output).strip() or None

    def _snapshot(self, client: UiautomatorClient) -> DeviceSnapshot:
        width, height = client.window_size()
        current = client.app_current()
        info = client.info
        info_mapping = info if isinstance(info, dict) else {}
        density_response = client.shell(["wm", "density"])
        density_output = str(getattr(density_response, "output", density_response))
        density_matches = re.findall(r"(?:Override|Physical) density:\s*(\d+)", density_output)
        # Android prints the physical value first and the effective override last.
        density = int(density_matches[-1]) / 160 if density_matches else 1.0
        keyboard_response = client.shell(["dumpsys", "input_method"])
        keyboard_output = str(getattr(keyboard_response, "output", keyboard_response))
        keyboard_visible = bool(
            re.search(r"m(?:InputShown|IsInputViewShown)=true", keyboard_output)
        )
        package = current.get("package")
        activity = current.get("activity")
        if not isinstance(package, str) or not package:
            raise DeviceBackendUnavailable("foreground package is unavailable")
        return DeviceSnapshot(
            width=width,
            height=height,
            density=density,
            rotation=int(info_mapping.get("displayRotation", 0)),
            package=package,
            activity=activity if isinstance(activity, str) else None,
            keyboard_visible=keyboard_visible,
        )

    def _type_text(self, client: UiautomatorClient, text: str, *, replace: bool) -> None:
        if replace:
            # uiautomator2's clear=True currently calls a hidden InputManager API
            # that is absent on Android 37. Enable and await the Unicode IME
            # without sending an empty value, which would hide it and can drop
            # focus before the real UTF-8 broadcast.
            client.set_input_ime()
            # Switching the IME can invalidate the editor token on a cold
            # Android 15 device. Restore the focus selected immediately before
            # this input action before clearing or broadcasting UTF-8 text.
            if self._last_tap is not None:
                client.click(*self._last_tap)
            client.shell(["am", "broadcast", "-a", "ADB_KEYBOARD_CLEAR_TEXT"])
        client.send_keys(text, clear=False)

    def _recover_prior_state(self) -> None:
        journal = self._state_journal
        lease = self._lease
        if journal is None or lease is None:
            return
        journal.recover_prior(lease, self._restore_setting)

    def _restore_current_state(self) -> None:
        journal = self._state_journal
        lease = self._lease
        if journal is None or lease is None:
            return
        journal.restore_current(lease, self._restore_setting)

    def _restore_setting(self, setting: PendingDeviceSetting) -> None:
        client = self._require_client()
        if setting.key != "default_input_method":
            raise DeviceBackendUnavailable(f"unsupported device setting {setting.key!r}")
        client.shell(["ime", "set", setting.original_value])
