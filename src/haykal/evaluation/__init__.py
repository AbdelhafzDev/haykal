"""Reproducible production-evidence evaluators."""

from .fallback import (
    FallbackDataset,
    FallbackEvaluationReport,
    evaluate_fallback_dataset,
    load_fallback_dataset,
)

__all__ = [
    "FallbackDataset",
    "FallbackEvaluationReport",
    "evaluate_fallback_dataset",
    "load_fallback_dataset",
]
