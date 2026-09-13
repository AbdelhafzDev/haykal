"""Minimal Python primitive caller; HAYKAL_API_TOKEN stays outside source control."""

from __future__ import annotations

import os

from haykal.contracts import Expectation, Risk, SemanticAction
from haykal.sdk import HaykalClient

client = HaykalClient("http://127.0.0.1:8421", os.environ["HAYKAL_API_TOKEN"])
session_id = client.create_session(os.environ.get("ANDROID_SERIAL", "emulator-5554"))
try:
    scene = client.observe(session_id)
    print(scene.scene_id, len(scene.elements))
    result = client.act(
        session_id,
        SemanticAction(
            action_id="open-search",
            kind="tap",
            target={"selector": {"resource_id": {"ends_with": "id/search"}}},
            risk=Risk(category="navigation", gate="none"),
            expect=Expectation(visible={"resource_id": {"ends_with": "id/search_input"}}),
        ),
    )
    print(result.status, result.trace_id)
finally:
    client.close_session(session_id)
