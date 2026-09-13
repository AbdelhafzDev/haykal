"""Public projections that omit interpreter-only journal state."""

from __future__ import annotations

from haykal.contracts import RunSnapshot


def public_run(snapshot: RunSnapshot) -> RunSnapshot:
    return snapshot.model_copy(
        update={
            "outputs": {
                name: value for name, value in snapshot.outputs.items() if not name.startswith("_")
            }
        }
    )
