from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from haykal.traces import TraceConflict, TraceStore


def test_trace_events_are_durable_ordered_and_strictly_owned(tmp_path: Path) -> None:
    database = tmp_path / "trace.sqlite3"
    store = TraceStore(database)
    trace_id = store.new_trace_id()

    first = store.append(
        trace_id=trace_id,
        run_id="run-1",
        event_type="action.prepared",
        payload={"action_id": "action-1"},
    )
    second = store.append(
        trace_id=trace_id,
        run_id="run-1",
        event_type="action.dispatched",
        artifacts=["sha256:" + "a" * 64],
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [item.event_type for item in TraceStore(database).read(trace_id)] == [
        "action.prepared",
        "action.dispatched",
    ]
    with pytest.raises(TraceConflict):
        store.append(
            trace_id=trace_id,
            run_id="run-2",
            event_type="run.failed",
        )


def test_existing_trace_database_is_migrated_for_indexed_retention(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE trace_event (trace_id TEXT, run_id TEXT, sequence INTEGER, "
            "envelope_json TEXT, PRIMARY KEY(trace_id, sequence))"
        )
        connection.execute(
            "INSERT INTO trace_event VALUES (?, ?, ?, ?)",
            (
                "legacy",
                "run",
                1,
                '{"schema_version":"1.0","run_id":"run","sequence":1,'
                '"event_type":"run.started","occurred_at":"2020-01-01T00:00:00Z",'
                '"payload":{},"trace_id":"legacy","artifacts":[],'
                '"redaction":{"policy":"default","applied":true}}',
            ),
        )
        connection.commit()

    store = TraceStore(database)

    assert store.read("legacy")[0].sequence == 1
