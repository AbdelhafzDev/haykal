"""Coherent raw observation capture from the device boundary."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from haykal.artifacts import ArtifactStore
from haykal.contracts.observation import (
    CaptureEvidence,
    Display,
    ForegroundApp,
    KeyboardState,
    RawObservation,
)
from haykal.device import DeviceBackend


@dataclass(frozen=True, slots=True)
class ObservationCapture:
    observation: RawObservation
    hierarchy_xml: bytes
    screenshot_png: bytes


class ObservationService:
    def __init__(
        self,
        backend: DeviceBackend,
        artifact_store: ArtifactStore,
        *,
        session_id: str,
        max_coherence_attempts: int = 2,
        max_capture_skew_ms: int = 500,
    ) -> None:
        if max_coherence_attempts < 1:
            raise ValueError("max_coherence_attempts must be at least one")
        if max_capture_skew_ms < 0:
            raise ValueError("max_capture_skew_ms cannot be negative")
        self._backend = backend
        self._artifacts = artifact_store
        self._session_id = session_id
        self._max_coherence_attempts = max_coherence_attempts
        self._max_capture_skew_ms = max_capture_skew_ms
        self._revision = 0

    async def capture(self) -> ObservationCapture:
        for attempt in range(1, self._max_coherence_attempts + 1):
            before = await self._backend.snapshot()
            hierarchy = (await self._backend.hierarchy()).encode()
            hierarchy_at = datetime.now(UTC)
            screenshot = await self._backend.screenshot()
            screenshot_at = datetime.now(UTC)
            after = await self._backend.snapshot()
            skew = round(abs((screenshot_at - hierarchy_at).total_seconds()) * 1000)
            context_changed = (before.package, before.activity, before.rotation) != (
                after.package,
                after.activity,
                after.rotation,
            )
            if (
                not context_changed and skew <= self._max_capture_skew_ms
            ) or attempt == self._max_coherence_attempts:
                break

        warnings: list[str] = []
        if (before.package, before.activity) != (after.package, after.activity):
            warnings.append("foreground_changed_during_capture")
        if before.rotation != after.rotation:
            warnings.append("rotation_changed_during_capture")
        if skew > self._max_capture_skew_ms:
            warnings.append("capture_skew_exceeded")
        if warnings and self._max_coherence_attempts > 1:
            warnings.append("capture_context_unstable_after_retries")
        hierarchy_artifact = self._artifacts.put(hierarchy)
        screenshot_artifact = self._artifacts.put(screenshot)
        self._revision += 1
        observation = RawObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            session_id=self._session_id,
            revision=self._revision,
            display=Display(
                width=after.width,
                height=after.height,
                density=after.density,
                rotation=after.rotation,
            ),
            foreground=ForegroundApp(package=after.package, activity=after.activity),
            keyboard=KeyboardState(visible=after.keyboard_visible),
            hierarchy=CaptureEvidence(
                artifact=hierarchy_artifact.digest,
                captured_at=hierarchy_at,
                backend="uiautomator2",
            ),
            screenshot=CaptureEvidence(
                artifact=screenshot_artifact.digest,
                media_type="image/png",
                captured_at=screenshot_at,
                backend="uiautomator2",
            ),
            capture_skew_ms=skew,
            warnings=warnings,
        )
        return ObservationCapture(observation, hierarchy, screenshot)
