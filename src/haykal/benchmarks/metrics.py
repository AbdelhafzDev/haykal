"""Transparent component metrics used by Phase 2 release evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PrecisionRecall:
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float


def precision_recall(predicted: set[T], expected: set[T]) -> PrecisionRecall:
    true_positive = len(predicted & expected)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    precision = true_positive / len(predicted) if predicted else (1.0 if not expected else 0.0)
    recall = true_positive / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return PrecisionRecall(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
    )


@dataclass(frozen=True, slots=True)
class ExtractionMetrics:
    field_presence: PrecisionRecall
    value_accuracy: float
    record_boundaries: PrecisionRecall


def extraction_metrics(
    *,
    predicted_fields: dict[tuple[str, str], object | None],
    expected_fields: dict[tuple[str, str], object | None],
    predicted_records: set[frozenset[str]],
    expected_records: set[frozenset[str]],
) -> ExtractionMetrics:
    predicted_present = {key for key, value in predicted_fields.items() if value is not None}
    expected_present = {key for key, value in expected_fields.items() if value is not None}
    correctly_present = predicted_present & expected_present
    correct_values = sum(predicted_fields[key] == expected_fields[key] for key in correctly_present)
    value_accuracy = correct_values / len(correctly_present) if correctly_present else 1.0
    return ExtractionMetrics(
        field_presence=precision_recall(predicted_present, expected_present),
        value_accuracy=round(value_accuracy, 6),
        record_boundaries=precision_recall(set(predicted_records), set(expected_records)),
    )


@dataclass(frozen=True, slots=True)
class IdentityMetrics:
    pair_metrics: PrecisionRecall
    idf1: float


def identity_metrics(
    predicted_pairs: set[tuple[str, str]],
    expected_pairs: set[tuple[str, str]],
) -> IdentityMetrics:
    metrics = precision_recall(set(predicted_pairs), set(expected_pairs))
    return IdentityMetrics(pair_metrics=metrics, idf1=metrics.f1)
