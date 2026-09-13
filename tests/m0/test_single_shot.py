from __future__ import annotations

from pathlib import Path

import pytest

from haykal.device.single_shot import (
    AtMostOnceDispatcher,
    IdempotencyConflict,
    outcome_as_dict,
)


class Transport:
    def __init__(self, *, fail_after_effect: bool = False) -> None:
        self.calls = 0
        self.fail_after_effect = fail_after_effect

    def call_once(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        if self.fail_after_effect:
            raise TimeoutError("receipt lost after possible device effect")
        return {"method": method, "params": params, "accepted": True}


def test_successful_action_is_not_dispatched_again(tmp_path: Path) -> None:
    transport = Transport()
    dispatcher = AtMostOnceDispatcher(tmp_path / "dispatch.db", transport)

    first = dispatcher.dispatch(action_id="act-1", method="click", params={"x": 1, "y": 2})
    second = dispatcher.dispatch(action_id="act-1", method="click", params={"x": 1, "y": 2})

    assert first.status == "dispatched"
    assert second.status == "dispatched"
    assert second.repeated_request is True
    assert transport.calls == 1
    assert dispatcher.inspect("act-1") == second.__class__(
        action_id="act-1",
        status="dispatched",
        receipt=first.receipt,
        repeated_request=False,
    )
    assert outcome_as_dict(first)["status"] == "dispatched"
    assert dispatcher.inspect("missing") is None


def test_uncertain_action_is_not_dispatched_again(tmp_path: Path) -> None:
    transport = Transport(fail_after_effect=True)
    database = tmp_path / "dispatch.db"
    first_process = AtMostOnceDispatcher(database, transport)

    first = first_process.dispatch(action_id="act-2", method="click", params={"x": 100, "y": 200})
    restarted_process = AtMostOnceDispatcher(database, transport)
    second = restarted_process.dispatch(
        action_id="act-2", method="click", params={"x": 100, "y": 200}
    )

    assert first.status == "outcome_unknown"
    assert second.status == "outcome_unknown"
    assert transport.calls == 1


def test_action_id_cannot_be_reused_for_different_content(tmp_path: Path) -> None:
    transport = Transport()
    dispatcher = AtMostOnceDispatcher(tmp_path / "dispatch.db", transport)
    dispatcher.dispatch(action_id="act-3", method="click", params={"x": 1, "y": 2})

    with pytest.raises(IdempotencyConflict):
        dispatcher.dispatch(action_id="act-3", method="click", params={"x": 9, "y": 9})

    assert transport.calls == 1
