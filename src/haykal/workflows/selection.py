"""Deterministic selection over typed extraction records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cmp_to_key

from haykal.contracts.extraction import ExtractedRecord
from haykal.contracts.skill import SelectionPolicy, SelectionPredicate
from haykal.contracts.workflow import SelectionResult

from .values import ValueNotFound, get_path, resolve_value


@dataclass(frozen=True, slots=True)
class SelectionNeedsDecision:
    reason: str
    candidates: tuple[ExtractedRecord, ...]


class SelectionEvaluator:
    """Null-excluding predicates, declared ordering, then record-id tie-break."""

    def evaluate(
        self,
        policy: SelectionPolicy,
        records: list[ExtractedRecord],
        context: dict[str, object],
    ) -> SelectionResult:
        included: list[ExtractedRecord] = []
        excluded_null = 0
        for record in records:
            try:
                matched = all(self._predicate(item, record, context) for item in policy.where)
            except ValueNotFound:
                excluded_null += 1
                continue
            if matched:
                included.append(record)
        included.sort(key=cmp_to_key(lambda left, right: self._compare(policy, left, right)))
        if not included:
            return SelectionResult(status="empty", excluded_null=excluded_null)
        if policy.margin is not None and len(included) > 1:
            try:
                first = self._field(included[0], policy.margin.field)
                second = self._field(included[1], policy.margin.field)
                gap = abs(Decimal(str(first)) - Decimal(str(second)))
            except (ValueNotFound, InvalidOperation, TypeError):
                return SelectionResult(
                    status="margin",
                    candidates=included[:2],
                    excluded_null=excluded_null,
                )
            if gap < Decimal(str(policy.margin.min_gap)):
                return SelectionResult(
                    status="margin",
                    candidates=included[:2],
                    excluded_null=excluded_null,
                )
        return SelectionResult(
            status="selected",
            selected=included[0],
            candidates=included,
            excluded_null=excluded_null,
        )

    def _predicate(
        self,
        predicate: SelectionPredicate,
        record: ExtractedRecord,
        context: dict[str, object],
    ) -> bool:
        left = self._field(record, predicate.field)
        if left is None:
            raise ValueNotFound(predicate.field)
        right = resolve_value(predicate.value, context)
        if right is None:
            raise ValueNotFound(str(predicate.value))
        return _operate(left, predicate.op, right)

    def _compare(
        self, policy: SelectionPolicy, left: ExtractedRecord, right: ExtractedRecord
    ) -> int:
        for ordering in policy.order_by:
            left_value = self._field_or_none(left, ordering.field)
            right_value = self._field_or_none(right, ordering.field)
            compared = _compare_values(left_value, right_value)
            if compared:
                return compared if ordering.direction == "asc" else -compared
        return (left.record_id > right.record_id) - (left.record_id < right.record_id)

    @staticmethod
    def _field(record: ExtractedRecord, path: str) -> object:
        return get_path(record.fields, path)

    @staticmethod
    def _field_or_none(record: ExtractedRecord, path: str) -> object | None:
        try:
            return get_path(record.fields, path)
        except ValueNotFound:
            return None


def _compare_values(left: object | None, right: object | None) -> int:
    if left is None or right is None:
        return 0 if left is right else 1 if left is None else -1
    try:
        left_decimal = Decimal(str(left))
        right_decimal = Decimal(str(right))
        return (left_decimal > right_decimal) - (left_decimal < right_decimal)
    except InvalidOperation:
        left_text, right_text = str(left), str(right)
        return (left_text > right_text) - (left_text < right_text)


def _operate(left: object, operator: str, right: object) -> bool:
    if operator == "contains":
        return right in left if isinstance(left, (str, list, tuple, set, dict)) else False
    if operator == "in":
        return left in right if isinstance(right, (str, list, tuple, set, dict)) else False
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    try:
        left_decimal, right_decimal = Decimal(str(left)), Decimal(str(right))
        comparisons = {
            "<": left_decimal < right_decimal,
            "<=": left_decimal <= right_decimal,
            ">": left_decimal > right_decimal,
            ">=": left_decimal >= right_decimal,
        }
        return comparisons[operator]
    except (InvalidOperation, KeyError):
        left_text, right_text = str(left), str(right)
        return {
            "<": left_text < right_text,
            "<=": left_text <= right_text,
            ">": left_text > right_text,
            ">=": left_text >= right_text,
        }[operator]
