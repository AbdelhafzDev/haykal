from __future__ import annotations

from pathlib import Path

import pytest

from haykal.artifacts import ArtifactIntegrityError, ArtifactStore


def test_content_is_addressed_and_deduplicated(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first = store.put(b"same bytes")
    second = store.put(b"same bytes")

    assert first.digest == second.digest
    assert first.path == second.path
    assert first.size == len(b"same bytes")
    assert store.contains(first.digest)
    assert store.get(first.digest) == b"same bytes"


def test_integrity_failure_is_detected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = store.put(b"original")
    artifact.path.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        store.get(artifact.digest)


@pytest.mark.parametrize("digest", ["md5:abc", "sha256:nope", "", "sha256:12"])
def test_malformed_digest_is_rejected(tmp_path: Path, digest: str) -> None:
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path).contains(digest)
