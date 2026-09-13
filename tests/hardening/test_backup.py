from __future__ import annotations

import io
import sqlite3
import tarfile
from contextlib import closing
from pathlib import Path

import pytest

from haykal.hardening import BackupError, StateBackup


def test_backup_uses_sqlite_snapshot_and_verified_restore(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    with closing(sqlite3.connect(state / "runtime.sqlite3")) as connection:
        connection.execute("CREATE TABLE values_table(value TEXT)")
        connection.execute("INSERT INTO values_table VALUES ('kept')")
        connection.commit()
    artifact = state / "artifacts" / "sha256" / "aa" / "rest"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"artifact")
    archive = tmp_path / "backup.tar.gz"

    created = StateBackup().create(state, archive)
    restored = tmp_path / "restored"
    result = StateBackup().restore(archive, restored)

    assert created["archive_sha256"] == result["archive_sha256"]
    assert (restored / "artifacts" / "sha256" / "aa" / "rest").read_bytes() == b"artifact"
    with closing(sqlite3.connect(restored / "runtime.sqlite3")) as connection:
        assert connection.execute("SELECT value FROM values_table").fetchone()[0] == "kept"

    with pytest.raises(BackupError, match="empty"):
        StateBackup().restore(archive, restored)


def test_restore_rejects_archive_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))

    with pytest.raises(BackupError, match="unsafe path"):
        StateBackup().restore(archive, tmp_path / "restored")
    assert not (tmp_path / "escape").exists()
