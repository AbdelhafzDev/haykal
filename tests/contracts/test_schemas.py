from __future__ import annotations

from pathlib import Path

from haykal.contracts.schema import render_schemas

ROOT = Path(__file__).parents[2]


def test_checked_in_schemas_match_models() -> None:
    rendered = render_schemas()
    assert {path.name for path in (ROOT / "schemas/v1").glob("*.schema.json")} == rendered.keys()
    for name, expected in rendered.items():
        assert (ROOT / "schemas/v1" / name).read_text(encoding="utf-8") == expected
