"""Cryptographic provenance checks for comparative benchmark inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def contains_sensitive_key(value: object) -> bool:
    sensitive = ("secret", "token", "password", "authorization", "api_key", "apikey")
    if isinstance(value, dict):
        return any(
            any(marker in str(key).casefold() for marker in sensitive)
            or contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_sensitive_key(item) for item in value)
    return False


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: str | Path) -> str:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"pinned input is not a file: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256_bytes(encoded)


class PinnedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    sha256: Sha256

    def verify(self) -> Path:
        source = Path(self.path).expanduser().resolve()
        actual = sha256_file(source)
        if actual != self.sha256:
            raise ValueError(
                f"cryptographic pin mismatch for {source}: expected {self.sha256}, got {actual}"
            )
        return source
