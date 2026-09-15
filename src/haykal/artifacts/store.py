"""Atomic content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    digest: str
    size: int
    path: Path


class ArtifactIntegrityError(RuntimeError):
    """Stored content does not match its address."""


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for temporary in self.root.glob("sha256/*/.artifact-*"):
            with suppress(OSError):
                temporary.unlink()

    @staticmethod
    def digest(data: bytes) -> str:
        return f"sha256:{hashlib.sha256(data).hexdigest()}"

    def _path(self, digest: str) -> Path:
        algorithm, separator, hex_digest = digest.partition(":")
        if algorithm != "sha256" or not separator or len(hex_digest) != 64:
            raise ValueError("unsupported or malformed artifact digest")
        int(hex_digest, 16)
        return self.root / "sha256" / hex_digest[:2] / hex_digest[2:]

    def put(self, data: bytes) -> StoredArtifact:
        digest = self.digest(data)
        destination = self._path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not destination.exists():
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".artifact-", dir=destination.parent
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, destination)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        return StoredArtifact(digest=digest, size=len(data), path=destination)

    def get(self, digest: str) -> bytes:
        data = self._path(digest).read_bytes()
        if self.digest(data) != digest:
            raise ArtifactIntegrityError(f"artifact {digest} failed integrity check")
        return data

    def contains(self, digest: str) -> bool:
        return self._path(digest).is_file()

    def prune_before(self, cutoff: datetime, *, dry_run: bool = True) -> int:
        """Remove content older than the configured cutoff, or only count it."""

        sha_root = self.root / "sha256"
        if not sha_root.exists():
            return 0
        cutoff_timestamp = cutoff.timestamp()
        candidates = [
            path
            for path in sha_root.glob("*/*")
            if path.is_file() and path.stat().st_mtime < cutoff_timestamp
        ]
        if dry_run:
            return len(candidates)
        for path in candidates:
            path.unlink()
            with suppress(OSError):
                path.parent.rmdir()
        return len(candidates)
