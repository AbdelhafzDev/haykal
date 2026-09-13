from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from haykal.contracts import DecisionResponse, RunSnapshot
from haykal.workflows import RunJournal
from haykal.workflows.journal import JournalConflict


def _snapshot() -> RunSnapshot:
    now = datetime.now(UTC)
    return RunSnapshot(
        run_id="run-1",
        trace_id="trace-1",
        session_id="session-1",
        skill="example@1.0.0",
        skill_digest="sha256:" + "a" * 64,
        state="home",
        status="running",
        created_at=now,
        updated_at=now,
    )


def test_journal_persists_run_and_committed_action(tmp_path: Path) -> None:
    journal = RunJournal(tmp_path / "journal.sqlite3")
    journal.create(_snapshot())
    claim = journal.claim_action("run-1", "act-1", "sha256:intent")
    assert claim.should_dispatch is True
    journal.finish_action("run-1", "act-1", status="committed", result={"ok": True})
    assert journal.claim_action("run-1", "act-1", "sha256:intent").should_dispatch is False
    assert journal.action_status("run-1", "act-1") == "committed"
    assert journal.get("run-1").state == "home"


def test_restart_after_prepared_is_unknown_and_never_dispatches_again(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = RunJournal(path)
    journal.create(_snapshot())
    assert journal.claim_action("run-1", "act-1", "sha256:intent").should_dispatch
    restarted = RunJournal(path)
    recovered = restarted.claim_action("run-1", "act-1", "sha256:intent")
    assert recovered.status == "outcome_unknown"
    assert recovered.should_dispatch is False
    with pytest.raises(JournalConflict, match="different intent"):
        restarted.claim_action("run-1", "act-1", "sha256:other")


def test_candidate_patch_is_never_promoted(tmp_path: Path) -> None:
    journal = RunJournal(tmp_path / "journal.sqlite3")
    journal.create(_snapshot())
    patch = journal.record_patch(
        run_id="run-1",
        skill_digest="sha256:" + "a" * 64,
        state="home",
        reason="unrecognized_screen",
        decision=DecisionResponse(cancel=True),
        scene_digest="sha256:" + "b" * 64,
    )
    assert patch.promoted is False
    assert journal.patches("run-1") == [patch]
