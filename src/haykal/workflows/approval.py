"""Risk classification and single-use, content-bound approval grants."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import unicodedata
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Literal, cast

from haykal.contracts import ApprovalChallenge, ApprovalGrant
from haykal.contracts.action import SemanticAction


class ApprovalError(PermissionError):
    """Base approval rejection."""


class ApprovalExpired(ApprovalError):
    pass


class ApprovalReused(ApprovalError):
    pass


class ApprovalStale(ApprovalError):
    pass


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return " ".join(unicodedata.normalize("NFKC", value).split())
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def canonical_digest(value: object, *, normalize_text: bool = False) -> str:
    effective = _normalize(value) if normalize_text else value
    encoded = json.dumps(
        effective,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


RiskCategory = Literal[
    "navigation",
    "purchase",
    "transfer",
    "submission",
    "deletion",
    "permission",
    "credential",
    "communication",
    "unknown",
]


class RiskClassifier:
    """Independent floor: a skill declaration can raise risk, never lower it."""

    _ORDER: ClassVar[dict[str, int]] = {
        "navigation": 0,
        "credential": 1,
        "permission": 2,
        "communication": 3,
        "submission": 4,
        "purchase": 5,
        "transfer": 6,
        "deletion": 7,
        "unknown": 8,
    }

    def classify(
        self,
        action: SemanticAction,
        declared: str | None = None,
        *,
        target_context: str = "",
    ) -> RiskCategory:
        inferred = "navigation"
        semantic = ""
        if action.target and action.target.selector:
            semantic = action.target.selector.semantic_name or ""
        name = f"{semantic} {target_context}".casefold()
        if action.target is not None and action.target.coordinates is not None:
            inferred = "unknown"
        elif action.kind == "input_text":
            inferred = (
                "credential" if any(x in name for x in ("password", "otp", "pin")) else "navigation"
            )
        elif any(
            x in name for x in ("place_order", "buy", "purchase", "pay", "إتمام الطلب", "ادفع")
        ):
            inferred = "purchase"
        elif any(x in name for x in ("transfer", "send_money", "تحويل")):
            inferred = "transfer"
        elif any(x in name for x in ("delete", "remove_account", "حذف")):
            inferred = "deletion"
        candidates = [inferred, action.risk.category]
        if declared is not None:
            candidates.append(declared)
        return cast(RiskCategory, max(candidates, key=self._ORDER.__getitem__))


class ApprovalService:
    def __init__(self, database: str | Path, *, signing_secret: bytes) -> None:
        if len(signing_secret) < 32:
            raise ValueError("approval signing secret must be at least 32 bytes")
        self._database = str(database)
        self._secret = signing_secret
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
                CREATE TABLE IF NOT EXISTS approval_grant (
                    token_hash TEXT PRIMARY KEY,
                    gate_id TEXT NOT NULL UNIQUE,
                    principal TEXT NOT NULL,
                    challenge_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                )
                """
            )

    def challenge(
        self,
        *,
        run_id: str,
        skill_digest: str,
        action: SemanticAction,
        target_fingerprint: str,
        material: dict[str, object],
        evidence_scene_digest: str,
        ttl_s: int = 300,
        now: datetime | None = None,
    ) -> ApprovalChallenge:
        current = now or datetime.now(UTC)
        return ApprovalChallenge(
            gate_id=f"gate_{uuid.uuid4().hex}",
            run_id=run_id,
            skill_digest=skill_digest,
            action_intent_digest=canonical_digest(
                action.model_dump(mode="json", exclude={"action_id"})
            ),
            target_fingerprint=target_fingerprint,
            material=material,
            material_digest=canonical_digest(material, normalize_text=True),
            evidence_scene_digest=evidence_scene_digest,
            expires_at=current + timedelta(seconds=ttl_s),
            nonce=f"nonce_{secrets.token_urlsafe(18)}",
        )

    def grant(
        self,
        challenge: ApprovalChallenge,
        *,
        principal: str,
        scopes: set[str],
        now: datetime | None = None,
    ) -> ApprovalGrant:
        if "approve" not in scopes:
            raise ApprovalError("principal lacks approve scope")
        current = now or datetime.now(UTC)
        if current >= challenge.expires_at:
            raise ApprovalExpired("approval challenge expired")
        raw = secrets.token_urlsafe(32)
        signature = hmac.new(
            self._secret,
            f"{challenge.gate_id}.{raw}".encode(),
            hashlib.sha256,
        ).hexdigest()
        token = f"hka1.{raw}.{signature}"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        encoded = challenge.model_dump_json()
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    "INSERT INTO approval_grant "
                    "(token_hash, gate_id, principal, challenge_json, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        token_hash,
                        challenge.gate_id,
                        principal,
                        encoded,
                        challenge.expires_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ApprovalReused("challenge already granted") from exc
        return ApprovalGrant(
            gate_id=challenge.gate_id,
            token=token,
            expires_at=challenge.expires_at,
        )

    def consume(
        self,
        token: str,
        current: ApprovalChallenge,
        *,
        now: datetime | None = None,
    ) -> None:
        self._verify_token_shape(token, current.gate_id)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        moment = now or datetime.now(UTC)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT challenge_json, expires_at, consumed_at FROM approval_grant "
                "WHERE token_hash = ? AND gate_id = ?",
                (token_hash, current.gate_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ApprovalError("approval token is invalid")
            if row["consumed_at"] is not None:
                connection.rollback()
                raise ApprovalReused("approval token was already consumed")
            if moment >= datetime.fromisoformat(str(row["expires_at"])):
                connection.rollback()
                raise ApprovalExpired("approval token expired")
            bound = ApprovalChallenge.model_validate_json(row["challenge_json"])
            if not self._same_binding(bound, current):
                connection.rollback()
                raise ApprovalStale("approval binding changed after re-observation")
            connection.execute(
                "UPDATE approval_grant SET consumed_at = ? WHERE token_hash = ?",
                (moment.isoformat(), token_hash),
            )
            connection.commit()

    def _verify_token_shape(self, token: str, gate_id: str) -> None:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "hka1":
            raise ApprovalError("approval token is invalid")
        expected = hmac.new(
            self._secret,
            f"{gate_id}.{parts[1]}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(parts[2], expected):
            raise ApprovalError("approval token is invalid")

    @staticmethod
    def _same_binding(bound: ApprovalChallenge, current: ApprovalChallenge) -> bool:
        fields = (
            "gate_id",
            "run_id",
            "skill_digest",
            "action_intent_digest",
            "target_fingerprint",
            "material_digest",
        )
        return all(getattr(bound, field) == getattr(current, field) for field in fields)
