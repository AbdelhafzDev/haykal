from __future__ import annotations

from haykal.contracts.extraction import ExtractedRecord
from haykal.contracts.skill import SelectionPolicy
from haykal.workflows import SelectionEvaluator


def _record(record_id: str, rating: float | None, price: float) -> ExtractedRecord:
    return ExtractedRecord(
        record_id=record_id,
        fields={
            "rating": {"value": rating} if rating is not None else None,
            "price": {"amount": price, "currency": "SAR"},
            "name": {"normalized": record_id},
        },
        evidence={},
    )


def _policy(*, gap: float = 0.1) -> SelectionPolicy:
    return SelectionPolicy.model_validate(
        {
            "from": "candidates",
            "where": [
                {"field": "rating.value", "op": ">=", "value": "${minimum_rating}"},
                {"field": "price.amount", "op": "<=", "value": "${maximum}"},
            ],
            "order_by": [
                {"field": "rating.value", "direction": "desc"},
                {"field": "price.amount", "direction": "asc"},
            ],
            "margin": {"field": "rating.value", "min_gap": gap},
            "as": "chosen",
        }
    )


def test_selection_filters_nulls_and_uses_declared_order() -> None:
    result = SelectionEvaluator().evaluate(
        _policy(gap=0),
        [_record("b", 4.8, 60), _record("a", 4.8, 50), _record("null", None, 20)],
        {"minimum_rating": 4, "maximum": 70},
    )
    assert result.status == "selected"
    assert result.selected is not None
    assert result.selected.record_id == "a"
    assert result.excluded_null == 1


def test_selection_tie_break_and_margin_are_deterministic() -> None:
    records = [_record("b", 4.8, 50), _record("a", 4.8, 50)]
    tied = SelectionEvaluator().evaluate(
        _policy(gap=0), records, {"minimum_rating": 4, "maximum": 70}
    )
    assert tied.selected is not None and tied.selected.record_id == "a"
    margin = SelectionEvaluator().evaluate(
        _policy(gap=0.1), records, {"minimum_rating": 4, "maximum": 70}
    )
    assert margin.status == "margin"
    assert [item.record_id for item in margin.candidates] == ["a", "b"]
