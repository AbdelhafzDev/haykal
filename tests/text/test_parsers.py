from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from haykal.text import parse_duration, parse_money, parse_number

FIXTURE = Path(__file__).parents[2] / "fixtures" / "text" / "parser_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["money"])
def test_money_cases(case: dict[str, object]) -> None:
    result = parse_money(str(case["raw"]))
    assert result.amount == Decimal(str(case["amount"]))
    assert result.currency == case["currency"]
    assert result.digits == case["digits"]


@pytest.mark.parametrize("case", CASES["duration"])
def test_duration_cases(case: dict[str, object]) -> None:
    result = parse_duration(str(case["raw"]))
    assert result.min_minutes == case["min_minutes"]
    assert result.max_minutes == case["max_minutes"]
    assert result.digits == case["digits"]


@pytest.mark.parametrize("raw", ["free", "", "ر.س"])
def test_number_rejects_missing_digits(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_number(raw)


def test_money_does_not_assume_currency() -> None:
    assert parse_money("٤٢").currency is None
