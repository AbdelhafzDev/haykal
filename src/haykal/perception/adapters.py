"""Swappable OCR and vision adapter boundaries."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from haykal.contracts.common import Bounds
from haykal.contracts.scene import ElementState
from haykal.contracts.selector import Role

from .model import PerceptionCandidate, SourceKind

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROLES: set[str] = {
    "button",
    "textbox",
    "text",
    "image",
    "checkbox",
    "radio",
    "switch",
    "list",
    "list_item",
    "tab",
    "dialog",
    "container",
    "webview",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class AdapterIdentity:
    name: str
    version: str
    model_digest: str
    weights_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.version:
            raise ValueError("adapter name and version are required")
        for digest in (self.model_digest, self.weights_digest):
            if digest is not None and _DIGEST.fullmatch(digest) is None:
                raise ValueError("adapter digests must be SHA-256 addresses")


class PerceptionAdapter(Protocol):
    source: SourceKind
    identity: AdapterIdentity

    async def detect(
        self,
        screenshot: bytes,
        *,
        width: int,
        height: int,
    ) -> list[PerceptionCandidate]: ...


class StaticPerceptionAdapter:
    """Deterministic adapter for recorded outputs and golden-scene tests."""

    def __init__(
        self,
        source: SourceKind,
        identity: AdapterIdentity,
        candidates: Sequence[PerceptionCandidate],
    ) -> None:
        if source == "accessibility":
            raise ValueError("fallback adapter source must be ocr or vision")
        self.source = source
        self.identity = identity
        self._candidates = list(candidates)

    async def detect(
        self,
        screenshot: bytes,
        *,
        width: int,
        height: int,
    ) -> list[PerceptionCandidate]:
        del screenshot, width, height
        return list(self._candidates)


Runner = Callable[[bytes], Sequence[Mapping[str, object]]]


class NormalizedJsonAdapter:
    """Run a pinned local OCR/vision provider and normalize its bounded JSON output."""

    def __init__(
        self,
        *,
        source: SourceKind,
        identity: AdapterIdentity,
        runner: Runner,
        timeout_s: float = 30.0,
        max_detections: int = 10_000,
    ) -> None:
        if source == "accessibility":
            raise ValueError("JSON adapter source must be ocr or vision")
        self.source = source
        self.identity = identity
        self._runner = runner
        self._timeout_s = timeout_s
        self._max_detections = max_detections

    async def detect(
        self,
        screenshot: bytes,
        *,
        width: int,
        height: int,
    ) -> list[PerceptionCandidate]:
        raw = await asyncio.wait_for(
            asyncio.to_thread(self._runner, screenshot), timeout=self._timeout_s
        )
        if len(raw) > self._max_detections:
            raise ValueError("adapter output exceeds detection budget")
        return [
            self._candidate(index, item, width=width, height=height)
            for index, item in enumerate(raw)
        ]

    def _candidate(
        self,
        index: int,
        item: Mapping[str, object],
        *,
        width: int,
        height: int,
    ) -> PerceptionCandidate:
        unknown = set(item) - {"id", "bounds", "role", "label", "text", "confidence"}
        if unknown:
            raise ValueError(f"unknown adapter fields: {', '.join(sorted(unknown))}")
        raw_bounds = item.get("bounds")
        if not isinstance(raw_bounds, Sequence) or isinstance(raw_bounds, (str, bytes)):
            raise ValueError("adapter bounds must be a four-number sequence")
        if len(raw_bounds) != 4 or not all(isinstance(value, int | float) for value in raw_bounds):
            raise ValueError("adapter bounds must contain four numbers")
        left, top, right, bottom = (round(cast(float, value)) for value in raw_bounds)
        if left < 0 or top < 0 or right > width or bottom > height:
            raise ValueError("adapter bounds exceed display")
        if right <= left or bottom <= top:
            raise ValueError("adapter bounds are empty")
        raw_role = item.get("role", "text" if self.source == "ocr" else "unknown")
        if not isinstance(raw_role, str) or raw_role not in _ROLES:
            raise ValueError(f"unsupported adapter role {raw_role!r}")
        confidence = item.get("confidence", 0.75)
        if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
            raise ValueError("adapter confidence must be in [0, 1]")
        label = item.get("label")
        text = item.get("text")
        if label is not None and not isinstance(label, str):
            raise ValueError("adapter label must be a string")
        if text is not None and not isinstance(text, str):
            raise ValueError("adapter text must be a string")
        external_id = item.get("id", str(index))
        if not isinstance(external_id, str):
            raise ValueError("adapter id must be a string")
        properties = {"bounds": float(confidence), "role": float(confidence)}
        if label:
            properties["label"] = float(confidence)
        if text:
            properties["text"] = float(confidence)
        return PerceptionCandidate(
            source=self.source,
            source_id=f"{self.source}:{self.identity.model_digest}#{external_id}",
            bounds=Bounds(left=left, top=top, right=right, bottom=bottom),
            role=cast(Role, raw_role),
            label=label,
            text=text,
            state=ElementState(
                enabled=True,
                visible=True,
                focused=False,
                checked=None,
                selected=None,
                scrollable=False,
            ),
            actions=("tap",) if raw_role in {"button", "checkbox", "radio", "switch"} else (),
            property_confidence=properties,
            order=index,
        )


class OmniParserAdapter(NormalizedJsonAdapter):
    """OmniParser-compatible boundary; model execution stays outside the kernel."""

    def __init__(
        self,
        *,
        identity: AdapterIdentity,
        runner: Runner,
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(
            source="vision",
            identity=identity,
            runner=runner,
            timeout_s=timeout_s,
        )
