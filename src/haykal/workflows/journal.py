"""Crash-safe SQLite journal for skill runs and action checkpoints."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from haykal.contracts import CandidatePatch, DecisionResponse, RunSnapshot


class RunNotFound(LookupError):
    pass


class JournalConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ActionClaim:
    action_id: str
    status: str
    should_dispatch: bool


class RunJournal:
    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_run (
                    run_id TEXT PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS skill_action_checkpoint (
                    run_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    intent_digest TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('prepared','committed','outcome_unknown')),
                    result_json TEXT,
                    PRIMARY KEY(run_id, action_id)
                );
                CREATE TABLE IF NOT EXISTS candidate_patch (
                    patch_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    patch_json TEXT NOT NULL
                );
                """
            )

    def create(self, snapshot: RunSnapshot) -> RunSnapshot:
        with closing(self._connect()) as connection:
            try:
                connection.execute(
                    "INSERT INTO skill_run(run_id, snapshot_json) VALUES (?, ?)",
                    (snapshot.run_id, snapshot.model_dump_json()),
                )
            except sqlite3.IntegrityError as exc:
                raise JournalConflict(f"run {snapshot.run_id!r} already exists") from exc
        return snapshot

    def get(self, run_id: str) -> RunSnapshot:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM skill_run WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return RunSnapshot.model_validate_json(row["snapshot_json"])

    def update(self, snapshot: RunSnapshot, *, expected_revision: int | None = None) -> int:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM skill_run WHERE run_id = ?", (snapshot.run_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RunNotFound(snapshot.run_id)
            revision = int(row["revision"])
            if expected_revision is not None and revision != expected_revision:
                connection.rollback()
                raise JournalConflict("run revision changed")
            connection.execute(
                "UPDATE skill_run SET snapshot_json = ?, revision = ? WHERE run_id = ?",
                (snapshot.model_dump_json(), revision + 1, snapshot.run_id),
            )
            connection.commit()
        return revision + 1

    def claim_action(self, run_id: str, action_id: str, intent_digest: str) -> ActionClaim:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT intent_digest, status FROM skill_action_checkpoint "
                "WHERE run_id = ? AND action_id = ?",
                (run_id, action_id),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO skill_action_checkpoint "
                    "(run_id, action_id, intent_digest, status) VALUES (?, ?, ?, 'prepared')",
                    (run_id, action_id, intent_digest),
                )
                connection.commit()
                return ActionClaim(action_id, "prepared", True)
            if row["intent_digest"] != intent_digest:
                connection.rollback()
                raise JournalConflict("action ID reused with different intent")
            status = str(row["status"])
            if status == "prepared":
                connection.execute(
                    "UPDATE skill_action_checkpoint SET status = 'outcome_unknown' "
                    "WHERE run_id = ? AND action_id = ?",
                    (run_id, action_id),
                )
                status = "outcome_unknown"
            connection.commit()
            return ActionClaim(action_id, status, False)

    def finish_action(self, run_id: str, action_id: str, *, status: str, result: object) -> None:
        if status not in {"committed", "outcome_unknown"}:
            raise ValueError("unsupported checkpoint status")
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        with closing(self._connect()) as connection:
            changed = connection.execute(
                "UPDATE skill_action_checkpoint SET status = ?, result_json = ? "
                "WHERE run_id = ? AND action_id = ? AND status = 'prepared'",
                (status, encoded, run_id, action_id),
            ).rowcount
        if changed != 1:
            raise JournalConflict("action was not in prepared state")

    def action_status(self, run_id: str, action_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT status FROM skill_action_checkpoint WHERE run_id = ? AND action_id = ?",
                (run_id, action_id),
            ).fetchone()
        return str(row["status"]) if row else None

    def record_patch(
        self,
        *,
        run_id: str,
        skill_digest: str,
        state: str,
        reason: str,
        decision: DecisionResponse,
        scene_digest: str,
    ) -> CandidatePatch:
        safe_decision = decision
        if decision.action is not None and decision.action.text is not None:
            safe_decision = decision.model_copy(
                update={"action": decision.action.model_copy(update={"text": "<redacted>"})}
            )
        patch = CandidatePatch(
            patch_id=f"patch_{uuid.uuid4().hex}",
            run_id=run_id,
            skill_digest=skill_digest,
            state=state,
            reason=reason,
            decision=safe_decision,
            scene_digest=scene_digest,
            created_at=datetime.now(UTC),
        )
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO candidate_patch(patch_id, run_id, patch_json) VALUES (?, ?, ?)",
                (patch.patch_id, run_id, patch.model_dump_json()),
            )
        return patch

    def patches(self, run_id: str) -> list[CandidatePatch]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT patch_json FROM candidate_patch WHERE run_id = ? ORDER BY rowid", (run_id,)
            ).fetchall()
        return [CandidatePatch.model_validate_json(row["patch_json"]) for row in rows]
