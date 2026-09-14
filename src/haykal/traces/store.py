"""Durable ordered runtime trace storage."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from haykal.contracts.events import EventType, RedactionRecord, TraceEnvelope


class TraceConflict(ValueError):
    """A trace ID cannot be reused across runs."""


class TraceStore:
    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        self._initialize()

    @staticmethod
    def new_trace_id() -> str:
        return f"trc_{uuid.uuid4().hex}"

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
                CREATE TABLE IF NOT EXISTS trace_event (
                    trace_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    PRIMARY KEY(trace_id, sequence)
                )
                """
            )
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(trace_event)")}
            if "occurred_at" not in columns:
                connection.execute("ALTER TABLE trace_event ADD COLUMN occurred_at TEXT")
                rows = connection.execute(
                    "SELECT rowid, envelope_json FROM trace_event WHERE occurred_at IS NULL"
                ).fetchall()
                for row in rows:
                    event = TraceEnvelope.model_validate_json(row["envelope_json"])
                    connection.execute(
                        "UPDATE trace_event SET occurred_at = ? WHERE rowid = ?",
                        (event.occurred_at.isoformat(), row["rowid"]),
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS trace_event_run_sequence "
                "ON trace_event(run_id, sequence)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS trace_event_occurred_at ON trace_event(occurred_at)"
            )

    def append(
        self,
        *,
        trace_id: str,
        run_id: str,
        event_type: EventType,
        payload: dict[str, object] | None = None,
        artifacts: list[str] | None = None,
        redaction_policy: str = "raw",
        redaction_applied: bool = False,
    ) -> TraceEnvelope:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT run_id, MAX(sequence) AS latest FROM trace_event WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            if existing is not None and existing["run_id"] not in {None, run_id}:
                connection.rollback()
                raise TraceConflict(f"trace {trace_id!r} belongs to another run")
            sequence = int(existing["latest"] or 0) + 1
            envelope = TraceEnvelope(
                run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                occurred_at=datetime.now(UTC),
                payload=payload or {},
                trace_id=trace_id,
                artifacts=artifacts or [],
                redaction=RedactionRecord(
                    policy=redaction_policy,
                    applied=redaction_applied,
                ),
            )
            encoded = json.dumps(
                envelope.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            connection.execute(
                "INSERT INTO trace_event(trace_id, run_id, sequence, occurred_at, envelope_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (trace_id, run_id, sequence, envelope.occurred_at.isoformat(), encoded),
            )
            connection.commit()
        return envelope

    def read(self, trace_id: str) -> list[TraceEnvelope]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT envelope_json FROM trace_event WHERE trace_id = ? ORDER BY sequence",
                (trace_id,),
            ).fetchall()
        return [TraceEnvelope.model_validate_json(row["envelope_json"]) for row in rows]

    def read_run(self, run_id: str, *, after_sequence: int = 0) -> list[TraceEnvelope]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT envelope_json FROM trace_event "
                "WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, after_sequence),
            ).fetchall()
        return [TraceEnvelope.model_validate_json(row["envelope_json"]) for row in rows]

    def trace_for_run(self, run_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT trace_id FROM trace_event WHERE run_id = ? ORDER BY sequence LIMIT 1",
                (run_id,),
            ).fetchone()
        return str(row["trace_id"]) if row is not None else None

    def prune_before(self, cutoff: datetime, *, dry_run: bool = True) -> int:
        """Delete trace events older than an RFC 3339 cutoff, or only count them."""

        with closing(self._connect()) as connection:
            encoded = cutoff.isoformat()
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM trace_event WHERE occurred_at < ?", (encoded,)
                ).fetchone()[0]
            )
            if not dry_run and count:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM trace_event WHERE occurred_at < ?", (encoded,))
                connection.commit()
        return count
