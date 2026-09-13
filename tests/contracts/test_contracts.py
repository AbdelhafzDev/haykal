from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from haykal.contracts import (
    ExtractionRequest,
    RawObservation,
    RunResult,
    RuntimeEvent,
    Selector,
    SemanticAction,
    SemanticScene,
    Skill,
    TraceEnvelope,
    validate_element_dictionary,
)
from haykal.contracts.expectation import Expectation

ROOT = Path(__file__).parents[2]
FIXTURES = json.loads((ROOT / "fixtures/contracts/v1-valid.json").read_text(encoding="utf-8"))
MODELS = {
    "observation": RawObservation,
    "scene": SemanticScene,
    "selector": Selector,
    "action": SemanticAction,
    "extraction-request": ExtractionRequest,
    "expectation": Expectation,
    "runtime-event": RuntimeEvent,
    "trace": TraceEnvelope,
    "run-result": RunResult,
    "skill": Skill,
}


@pytest.mark.parametrize("name", MODELS)
def test_v1_fixture_round_trips(name: str) -> None:
    model = MODELS[name]
    first = model.model_validate(FIXTURES[name])
    encoded = first.model_dump(mode="json", by_alias=True)
    second = model.model_validate(encoded)
    assert first == second


def test_unknown_contract_field_is_rejected() -> None:
    payload = {**FIXTURES["selector"], "guess": True}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Selector.model_validate(payload)


def test_under_specified_selector_is_rejected() -> None:
    with pytest.raises(ValidationError, match="under-specified"):
        Selector.model_validate({"role": "button"})


def test_element_dictionary_rejects_unknown_reference() -> None:
    with pytest.raises(ValueError, match="undefined semantic names"):
        validate_element_dictionary({"card": Selector(semantic_name="missing")})


def test_element_dictionary_rejects_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        validate_element_dictionary(
            {
                "one": Selector(semantic_name="two"),
                "two": Selector(semantic_name="one"),
            }
        )


def test_skill_rejects_unknown_state_destination() -> None:
    payload = json.loads(json.dumps(FIXTURES["skill"]))
    payload["states"]["ready"] = {"next": "missing"}
    with pytest.raises(ValidationError, match="unknown states"):
        Skill.model_validate(payload)


def test_gated_action_requires_uncertain_route() -> None:
    payload = json.loads(json.dumps(FIXTURES["skill"]))
    payload["states"]["ready"] = {
        "gate": {"category": "purchase", "material": {"total": "checkout.total"}},
        "action": {"kind": "tap", "target": {"semantic_name": "search_box"}},
        "retry": "none",
        "terminal": "completed",
    }
    with pytest.raises(ValidationError, match="on_action_uncertain"):
        Skill.model_validate(payload)
