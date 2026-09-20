from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from haykal.authoring import lint_skill, replay_skill

ROOT = Path(__file__).parents[2]


def test_contract_fixture_is_lint_clean_and_replays(tmp_path: Path) -> None:
    fixture = json.loads((ROOT / "fixtures/contracts/v1-valid.json").read_text())
    skill, issues = lint_skill(fixture["skill"])
    assert skill is not None
    assert issues == []
    scenes = tmp_path / "scenes"
    scenes.mkdir()
    fixture["scene"]["elements"] = [
        {
            "id": "search",
            "role": "textbox",
            "label": "بحث",
            "label_normalized": "بحث",
            "text": "",
            "text_normalized": "",
            "resource_id": "dev.haykal:id/search",
            "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 50},
            "state": {
                "enabled": True,
                "visible": True,
                "focused": False,
                "scrollable": False,
            },
            "actions": ["tap", "input_text"],
            "properties": {
                "label": {"confidence": 1, "sources": ["accessibility:search"]},
                "bounds": {"confidence": 1, "sources": ["accessibility:search"]},
            },
            "fingerprint": {"resource_id": "dev.haykal:id/search"},
        }
    ]
    (scenes / "ready.json").write_text(json.dumps(fixture["scene"]), encoding="utf-8")
    result = replay_skill(skill, scenes)
    assert result["passed"] is True


def test_lint_reports_missing_action_contracts() -> None:
    fixture = json.loads((ROOT / "fixtures/contracts/v1-valid.json").read_text())
    payload = fixture["skill"]
    payload["states"]["ready"].update(
        {
            "action": {"kind": "tap", "target": {"semantic_name": "search_box"}},
            "terminal": "completed",
        }
    )
    _skill, issues = lint_skill(payload)
    assert {issue.code for issue in issues} == {"missing_verification"}


@pytest.mark.parametrize("name", ["offers.yaml", "prepare-order.yaml"])
def test_phase4_matjar_reference_skills_are_lint_clean(name: str) -> None:
    payload = yaml.safe_load(
        (ROOT / "skills/dev.haykal.refapps.matjar" / name).read_text(encoding="utf-8")
    )
    skill, issues = lint_skill(payload)
    assert skill is not None
    assert issues == []


@pytest.mark.parametrize("name", ["offers.yaml", "prepare-order.yaml"])
def test_matjar_skills_budget_for_cold_navigation_observation(name: str) -> None:
    payload = yaml.safe_load(
        (ROOT / "skills/dev.haykal.refapps.matjar" / name).read_text(encoding="utf-8")
    )

    verification = payload["states"]["open_search"]["verify"]

    assert verification["timeout_ms"] >= 20_000
