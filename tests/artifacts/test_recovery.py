from __future__ import annotations

from haykal.artifacts import ArtifactStore


def test_store_removes_abandoned_atomic_write_on_reopen(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    directory = store.root / "sha256" / "aa"
    directory.mkdir(parents=True)
    abandoned = directory / ".artifact-crashed"
    abandoned.write_bytes(b"partial")

    ArtifactStore(tmp_path)

    assert not abandoned.exists()
