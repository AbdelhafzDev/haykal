from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from haykal.contracts.action import ActionTarget, Risk, SemanticAction
from haykal.contracts.selector import Selector
from haykal.workflows import (
    ApprovalError,
    ApprovalExpired,
    ApprovalReused,
    ApprovalService,
    ApprovalStale,
    RiskClassifier,
)


def _action() -> SemanticAction:
    return SemanticAction(
        action_id="submit-order",
        kind="tap",
        target=ActionTarget(selector=Selector(semantic_name="place_order")),
        risk=Risk(category="navigation", gate="none"),
    )


def _challenge(service: ApprovalService, *, total: float = 55.2):
    return service.challenge(
        run_id="run-1",
        skill_digest="sha256:" + "a" * 64,
        action=_action(),
        target_fingerprint="sha256:" + "b" * 64,
        material={"merchant": " بيتزا  هت ", "total": {"amount": total, "currency": "SAR"}},
        evidence_scene_digest="sha256:" + "c" * 64,
    )


def test_approval_requires_separate_scope_and_is_single_use(tmp_path: Path) -> None:
    service = ApprovalService(tmp_path / "approval.sqlite3", signing_secret=b"x" * 32)
    challenge = _challenge(service)
    with pytest.raises(ApprovalError, match="scope"):
        service.grant(challenge, principal="caller", scopes={"run"})
    grant = service.grant(challenge, principal="approver", scopes={"approve"})
    service.consume(grant.token, challenge)
    with pytest.raises(ApprovalReused, match="already consumed"):
        service.consume(grant.token, challenge)


def test_changed_material_or_target_rejects_stale_approval(tmp_path: Path) -> None:
    service = ApprovalService(tmp_path / "approval.sqlite3", signing_secret=b"x" * 32)
    original = _challenge(service)
    grant = service.grant(original, principal="approver", scopes={"approve"})
    changed = _challenge(service, total=60)
    changed = changed.model_copy(
        update={
            "gate_id": original.gate_id,
            "nonce": original.nonce,
            "expires_at": original.expires_at,
        }
    )
    with pytest.raises(ApprovalStale, match="binding changed"):
        service.consume(grant.token, changed)


def test_expired_challenge_and_token_are_rejected(tmp_path: Path) -> None:
    service = ApprovalService(tmp_path / "approval.sqlite3", signing_secret=b"x" * 32)
    now = datetime.now(UTC)
    challenge = _challenge(service).model_copy(update={"expires_at": now - timedelta(seconds=1)})
    with pytest.raises(ApprovalExpired):
        service.grant(challenge, principal="approver", scopes={"approve"}, now=now)

    active = _challenge(service).model_copy(update={"expires_at": now + timedelta(seconds=1)})
    grant = service.grant(active, principal="approver", scopes={"approve"}, now=now)
    with pytest.raises(ApprovalExpired):
        service.consume(grant.token, active, now=now + timedelta(seconds=2))


def test_risk_classifier_cannot_be_lowered_by_skill() -> None:
    assert RiskClassifier().classify(_action()) == "purchase"
    coordinate = _action().model_copy(
        update={"target": ActionTarget(coordinates=(10, 20), scene_revision=1, description="x")}
    )
    assert RiskClassifier().classify(coordinate) == "unknown"
