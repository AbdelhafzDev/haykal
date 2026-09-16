from __future__ import annotations

from pathlib import Path

import pytest

from haykal.artifacts import ArtifactStore
from haykal.contracts import ExtractionRequest
from haykal.contracts.action import ActionTarget, Risk, SemanticAction
from haykal.contracts.selector import ResourceMatch, Selector
from haykal.device import DeviceHealth, DeviceSnapshot
from haykal.device.single_shot import DispatchOutcome
from haykal.resolver import TargetNotFound
from haykal.runtime import RuntimeSession
from haykal.traces import TraceStore


class PagedBackend:
    def __init__(self) -> None:
        self.page = 0
        self.swipes = 0

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def health(self) -> DeviceHealth:
        return DeviceHealth(True, "fixture")

    async def snapshot(self) -> DeviceSnapshot:
        return DeviceSnapshot(400, 800, 2, 0, "dev.haykal", ".Main", False)

    async def hierarchy(self) -> str:
        numbers = (1, 2) if self.page == 0 else (2, 3) if self.page == 1 else (3, 4)
        cards = "".join(
            f'''<node index="{index}" text="" resource-id="result_{number}"
              class="android.view.View" package="dev.haykal" content-desc=""
              clickable="true" enabled="true" scrollable="false"
              bounds="[10,{100 + index * 150}][390,{230 + index * 150}]" visible-to-user="true">
                <node index="0" text="عرض {number}" resource-id="name_{number}"
                  class="android.widget.TextView" package="dev.haykal" content-desc=""
                  clickable="false" enabled="true" scrollable="false"
                  bounds="[20,{120 + index * 150}][200,{180 + index * 150}]"
                  visible-to-user="true" />
              </node>'''
            for index, number in enumerate(numbers)
        )
        return f"""<hierarchy rotation="0"><node index="0" text="" resource-id="results"
          class="android.view.View" package="dev.haykal" content-desc=""
          clickable="false" enabled="true" scrollable="true"
          bounds="[0,80][400,700]" visible-to-user="true">{cards}</node></hierarchy>"""

    async def screenshot(self) -> bytes:
        return b"fixture"

    async def tap(self, x: int, y: int) -> None: ...

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self.swipes += 1
        self.page = max(0, self.page - 1) if y2 > y1 else min(2, self.page + 1)

    async def type_text(self, text: str, *, replace: bool) -> None: ...

    async def press(self, key: str) -> None: ...

    async def dispatch_once(
        self, *, action_id: str, method: str, params: dict[str, object]
    ) -> DispatchOutcome:
        return DispatchOutcome(action_id, "dispatched", None, False)


@pytest.mark.asyncio
async def test_runtime_scrolls_settles_and_deduplicates_records(tmp_path: Path) -> None:
    backend = PagedBackend()
    dictionary = {
        "results": Selector(resource_id=ResourceMatch(ends_with="results")),
        "card": Selector(resource_id=ResourceMatch(regex=r"result_[0-9]+$")),
        "name": Selector(resource_id=ResourceMatch(regex=r"name_[0-9]+$")),
    }
    runtime = RuntimeSession(
        session_id="scroll",
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        trace_store=TraceStore(tmp_path / "runtime.sqlite3"),
        element_dictionary=dictionary,
    )
    await runtime.open()
    scene = await runtime.observe()
    result = await runtime.extract(
        ExtractionRequest.model_validate(
            {
                "scene_id": scene.scene_id,
                "group": {"by": "ancestry", "record": {"semantic_name": "card"}},
                "fields": {
                    "name": {
                        "selector": {"semantic_name": "name"},
                        "type": "text",
                        "required": True,
                    }
                },
                "scroll": {
                    "within": {"semantic_name": "results"},
                    "max_pages": 3,
                    "settle": {"stable_samples": 2, "interval_ms": 1},
                },
                "dedupe_by": ["name"],
                "limits": {"max_records": 4},
            }
        )
    )
    assert [record.fields["name"]["normalized"] for record in result.records] == [  # type: ignore[index]
        "عرض 1",
        "عرض 2",
        "عرض 3",
        "عرض 4",
    ]
    assert result.stop_reason == "max_records"
    assert backend.swipes == 2

    first_anchor = result.records[0].anchor
    assert first_anchor is not None
    action = SemanticAction(
        action_id="selected-record",
        kind="tap",
        target=ActionTarget(record_anchor="chosen"),
        risk=Risk(category="navigation", gate="none"),
    )
    source = runtime._source_scene(action, {"chosen": first_anchor})
    assert source is not None
    assert source.revision == first_anchor.scene_revision
    with pytest.raises(TargetNotFound):
        await runtime.resolve(action, record_anchors={"chosen": first_anchor})
    assert backend.page == 2

    revealed = await runtime.reveal(
        action,
        run_id="run-reveal",
        trace_id="trace-reveal",
        record_anchors={"chosen": first_anchor},
    )
    assert revealed is True
    assert backend.page == 0
    reveal_events = runtime.trace("trace-reveal")
    assert [
        event["payload"]["action_id"]
        for event in reveal_events
        if event["event_type"] == "action.dispatched"
    ] == ["selected-record:reveal:1", "selected-record:reveal:2"]

    resolution = await runtime.resolve(action, record_anchors={"chosen": first_anchor})
    assert resolution["accepted"] is True
