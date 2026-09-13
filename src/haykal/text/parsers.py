"""Deterministic number, money, and duration parsers for M0."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from .normalization import NormalizationProfile, normalize

DigitSystem = Literal["latin", "arabic-indic", "extended-arabic-indic", "mixed"]


@dataclass(frozen=True, slots=True)
class NumberValue:
    value: Decimal
    raw: str
    digits: DigitSystem


@dataclass(frozen=True, slots=True)
class MoneyValue:
    amount: Decimal
    currency: str | None
    raw: str
    digits: DigitSystem


@dataclass(frozen=True, slots=True)
class DurationValue:
    min_minutes: int
    max_minutes: int
    raw: str
    digits: DigitSystem


_NUMBER = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_DURATION_NUMBER = re.compile(r"\d+")
_CURRENCIES: tuple[tuple[str, str], ...] = (
    ("SAR", "SAR"),
    ("ر.س", "SAR"),
    ("ريال", "SAR"),
    ("﷼", "SAR"),
    ("SR", "SAR"),
    ("AED", "AED"),
    ("د.إ", "AED"),
    ("KWD", "KWD"),
    ("د.ك", "KWD"),
    ("BHD", "BHD"),
    ("QAR", "QAR"),
    ("OMR", "OMR"),
    ("EGP", "EGP"),
    ("ج.م", "EGP"),
    ("USD", "USD"),
    ("$", "USD"),
    ("EUR", "EUR"),
    ("€", "EUR"),
)


def detect_digit_system(raw: str) -> DigitSystem:
    systems: set[DigitSystem] = set()
    if re.search(r"[0-9]", raw):
        systems.add("latin")
    if re.search(r"[٠-٩]", raw):
        systems.add("arabic-indic")
    if re.search(r"[۰-۹]", raw):
        systems.add("extended-arabic-indic")
    if len(systems) > 1:
        return "mixed"
    if not systems:
        raise ValueError("value contains no digits")
    return systems.pop()


def _number_token(raw: str) -> str:
    normalized = normalize(raw, NormalizationProfile.MATERIAL)
    match = _NUMBER.search(normalized)
    if match is None:
        raise ValueError(f"no parseable number in {raw!r}")
    return match.group(0).replace(",", "")


def parse_number(raw: str) -> NumberValue:
    """Parse a decimal without guessing units or currency."""

    try:
        value = Decimal(_number_token(raw))
    except InvalidOperation as exc:
        raise ValueError(f"invalid number {raw!r}") from exc
    return NumberValue(value=value, raw=raw, digits=detect_digit_system(raw))


def parse_money(raw: str) -> MoneyValue:
    """Parse money while leaving currency null when no known token is visible."""

    folded = raw.casefold()
    currency = next((code for token, code in _CURRENCIES if token.casefold() in folded), None)
    number = parse_number(raw)
    return MoneyValue(amount=number.value, currency=currency, raw=raw, digits=number.digits)


def parse_duration(raw: str) -> DurationValue:
    """Parse a minute/hour duration or range into inclusive minute bounds."""

    normalized = normalize(raw, NormalizationProfile.MATERIAL)
    values = [int(value) for value in _DURATION_NUMBER.findall(normalized)]
    if not values or len(values) > 2:
        raise ValueError(f"invalid duration {raw!r}")
    hour_pattern = r"(?:ساعة|ساعات|\bhr\b|\bhrs\b|\bhour\b|\bhours\b)"
    multiplier = 60 if re.search(hour_pattern, normalized) else 1
    lower = values[0] * multiplier
    upper = values[-1] * multiplier
    if upper < lower:
        raise ValueError(f"duration range is descending in {raw!r}")
    return DurationValue(
        min_minutes=lower,
        max_minutes=upper,
        raw=raw,
        digits=detect_digit_system(raw),
    )
