from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from haykal.artifacts import ArtifactStore
from haykal.hardening import Diagnostics


def test_diagnostics_checks_private_state_database_and_artifacts(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    with closing(sqlite3.connect(state / "runtime.sqlite3")) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.commit()
    ArtifactStore(state / "artifacts").put(b"evidence")

    report = Diagnostics(state, minimum_free_bytes=1).run()

    assert report.status == "ready"
    assert report.as_dict(public=True)["checks"] == {
        "passed": 4,
        "warning": 0,
        "failed": 0,
    }
    assert "generated_at" not in report.as_dict(public=True)


def test_diagnostics_reports_uninitialized_state_without_creating_it(tmp_path: Path) -> None:
    state = tmp_path / "missing"
    report = Diagnostics(state, minimum_free_bytes=1).run()

    assert report.status == "degraded"
    assert not state.exists()
