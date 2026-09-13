from __future__ import annotations

import json
from pathlib import Path

import pytest

from haykal.contracts import Skill
from haykal.skills import (
    PublisherKeyPair,
    SkillConflict,
    SkillRegistry,
    SkillTrustError,
    TrustPolicy,
    sign_skill,
)

ROOT = Path(__file__).parents[2]


def _skill() -> Skill:
    fixture = json.loads((ROOT / "fixtures/contracts/v1-valid.json").read_text())
    return Skill.model_validate(fixture["skill"])


def test_signed_registry_round_trip_and_idempotent_publish(tmp_path: Path) -> None:
    keys = PublisherKeyPair.generate()
    registry = SkillRegistry(
        tmp_path / "registry.sqlite3",
        tmp_path / "objects",
        trust_policy=TrustPolicy({"haykal.dev": keys.public_key}),
    )
    signed = sign_skill(_skill(), publisher="haykal.dev", private_key=keys.private_key)
    first = registry.publish(signed.model_dump(mode="json", by_alias=True))
    second = registry.publish(signed.model_dump(mode="json", by_alias=True))
    loaded = registry.load(first.metadata.name, first.metadata.version)
    assert second.metadata.content_digest == first.metadata.content_digest
    assert loaded == first


def test_registry_rejects_tampering_unknown_publisher_and_version_overwrite(
    tmp_path: Path,
) -> None:
    keys = PublisherKeyPair.generate()
    registry = SkillRegistry(
        tmp_path / "registry.sqlite3",
        tmp_path / "objects",
        trust_policy=TrustPolicy({"haykal.dev": keys.public_key}),
    )
    signed = sign_skill(_skill(), publisher="haykal.dev", private_key=keys.private_key)
    registry.publish(signed.model_dump(mode="json", by_alias=True))

    changed = signed.model_copy(
        update={"metadata": signed.metadata.model_copy(update={"app_versions": ">=2,<3"})}
    )
    with pytest.raises(SkillTrustError, match="digest"):
        registry.publish(changed.model_dump(mode="json", by_alias=True))

    resigned = sign_skill(changed, publisher="haykal.dev", private_key=keys.private_key)
    with pytest.raises(SkillConflict, match="immutable"):
        registry.publish(resigned.model_dump(mode="json", by_alias=True))

    other = sign_skill(_skill(), publisher="unknown", private_key=keys.private_key)
    with pytest.raises(SkillTrustError, match="not trusted"):
        registry.publish(other.model_dump(mode="json", by_alias=True))
