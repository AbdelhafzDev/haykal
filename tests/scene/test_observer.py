from __future__ import annotations

from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.device import DeviceHealth, DeviceSnapshot
from haykal.device.single_shot import DispatchOutcome
from haykal.scene import ObservationService


class FakeBackend:
    def __init__(self) -> None:
        self.snapshots = [
            DeviceSnapshot(1080, 2400, 2.75, 0, "dev.haykal", ".Home", False),
            DeviceSnapshot(2400, 1080, 2.75, 1, "dev.other", ".Dialog", True),
        ]

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def health(self) -> DeviceHealth:
        return DeviceHealth(True, "fixture")

    async def snapshot(self) -> DeviceSnapshot:
        return self.snapshots.pop(0)

    async def hierarchy(self) -> str:
        return "<hierarchy/>"

    async def screenshot(self) -> bytes:
        return b"png"

    async def tap(self, x: int, y: int) -> None: ...
    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None: ...
    async def type_text(self, text: str, *, replace: bool) -> None: ...
    async def press(self, key: str) -> None: ...

    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_observer_persists_raw_evidence_and_reports_capture_changes(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    service = ObservationService(
        FakeBackend(), store, session_id="session", max_coherence_attempts=1
    )

    capture = await service.capture()

    assert capture.observation.revision == 1
    assert capture.observation.foreground.package == "dev.other"
    assert capture.observation.display.rotation == 1
    assert capture.observation.keyboard.visible is True
    assert capture.observation.warnings == [
        "foreground_changed_during_capture",
        "rotation_changed_during_capture",
    ]
    assert store.get(capture.observation.hierarchy.artifact) == b"<hierarchy/>"
    assert store.get(capture.observation.screenshot.artifact) == b"png"


@pytest.mark.asyncio
async def test_observer_retries_a_context_change_and_returns_a_coherent_frame(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    stable = DeviceSnapshot(1080, 2400, 2.75, 0, "dev.haykal", ".Home", False)
    backend.snapshots.extend([stable, stable])
    service = ObservationService(backend, ArtifactStore(tmp_path), session_id="session")

    capture = await service.capture()

    assert capture.observation.foreground.package == "dev.haykal"
    assert capture.observation.warnings == []
