"""Ed25519 publisher trust and content-addressed immutable skill storage."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from haykal.authoring import lint_skill
from haykal.contracts import Skill


class SkillTrustError(PermissionError):
    pass


class SkillConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PublisherKeyPair:
    private_key: str
    public_key: str

    @classmethod
    def generate(cls) -> PublisherKeyPair:
        private = Ed25519PrivateKey.generate()
        public = private.public_key()
        return cls(
            private_key=base64.b64encode(
                private.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            ).decode(),
            public_key=base64.b64encode(
                public.public_bytes(
                    serialization.Encoding.Raw,
                    serialization.PublicFormat.Raw,
                )
            ).decode(),
        )


class TrustPolicy:
    def __init__(self, publishers: dict[str, str]) -> None:
        self._publishers = dict(publishers)

    def verify(self, skill: Skill) -> None:
        publisher = skill.metadata.publisher
        signature = skill.metadata.signature
        digest = skill.metadata.content_digest
        if not publisher or not signature or not digest:
            raise SkillTrustError("published skill requires publisher, digest, and signature")
        encoded_key = self._publishers.get(publisher)
        if encoded_key is None:
            raise SkillTrustError(f"publisher {publisher!r} is not trusted")
        actual = canonical_skill_digest(skill)
        if not secrets_compare(actual, digest):
            raise SkillTrustError("skill content digest does not match content")
        try:
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded_key, validate=True))
            key.verify(base64.b64decode(signature, validate=True), digest.encode())
        except (ValueError, InvalidSignature) as exc:
            raise SkillTrustError("skill publisher signature is invalid") from exc


def _unsigned_payload(skill: Skill) -> dict[str, object]:
    payload = skill.model_dump(mode="json", by_alias=True)
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    metadata["content_digest"] = None
    metadata["signature"] = None
    return payload


def canonical_skill_digest(skill: Skill) -> str:
    encoded = json.dumps(
        _unsigned_payload(skill),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def sign_skill(skill: Skill, *, publisher: str, private_key: str) -> Skill:
    unsigned = skill.model_copy(
        update={
            "metadata": skill.metadata.model_copy(
                update={"publisher": publisher, "content_digest": None, "signature": None}
            )
        }
    )
    digest = canonical_skill_digest(unsigned)
    try:
        key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key, validate=True))
    except ValueError as exc:
        raise SkillTrustError("publisher private key is invalid") from exc
    signature = base64.b64encode(key.sign(digest.encode())).decode()
    return unsigned.model_copy(
        update={
            "metadata": unsigned.metadata.model_copy(
                update={"content_digest": digest, "signature": signature}
            )
        }
    )


class SkillRegistry:
    def __init__(
        self,
        database: str | Path,
        content_directory: str | Path,
        *,
        trust_policy: TrustPolicy,
    ) -> None:
        self._database = str(database)
        self._content = Path(content_directory)
        self._content.mkdir(parents=True, exist_ok=True)
        self._trust = trust_policy
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_version (
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content_digest TEXT NOT NULL UNIQUE,
                    publisher TEXT NOT NULL,
                    PRIMARY KEY(name, version)
                )
                """
            )

    def publish(self, payload: object) -> Skill:
        skill, issues = lint_skill(payload)
        if skill is None or issues:
            detail = "; ".join(f"{issue.code}:{issue.path}" for issue in issues)
            raise ValueError(f"skill is not publishable: {detail}")
        self._trust.verify(skill)
        assert skill.metadata.content_digest is not None
        digest = skill.metadata.content_digest
        encoded = json.dumps(
            skill.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        path = self._path(digest)
        created_object = False
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT content_digest FROM skill_version WHERE name = ? AND version = ?",
                (skill.metadata.name, skill.metadata.version),
            ).fetchone()
            if row is not None:
                connection.rollback()
                if row["content_digest"] == digest:
                    return self.load(skill.metadata.name, skill.metadata.version)
                raise SkillConflict("immutable skill version already has different content")
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_text(encoding="utf-8") != encoded + "\n":
                    connection.rollback()
                    raise SkillTrustError("content-addressed object has conflicting bytes")
            else:
                temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
                temporary.write_text(encoded + "\n", encoding="utf-8")
                temporary.replace(path)
                created_object = True
            try:
                connection.execute(
                    "INSERT INTO skill_version(name, version, content_digest, publisher) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        skill.metadata.name,
                        skill.metadata.version,
                        digest,
                        skill.metadata.publisher,
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                if created_object:
                    path.unlink(missing_ok=True)
                raise
        return skill

    def load(self, name: str, version: str) -> Skill:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content_digest FROM skill_version WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
        if row is None:
            raise LookupError(f"skill {name}@{version} was not found")
        digest = str(row["content_digest"])
        path = self._path(digest)
        try:
            skill = Skill.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SkillTrustError("skill content object is missing") from exc
        self._trust.verify(skill)
        if skill.metadata.name != name or skill.metadata.version != version:
            raise SkillTrustError("skill index and content disagree")
        return skill

    def _path(self, digest: str) -> Path:
        value = digest.removeprefix("sha256:")
        return self._content / value[:2] / f"{value}.json"


def secrets_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
