"""Accessibility quality measurement and fallback decisions."""

from __future__ import annotations

from dataclasses import dataclass

from haykal.text.normalization import normalize

from .model import PerceptionCandidate, SourceKind


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    minimum_score: float = 0.72
    minimum_actionable: int = 2
    minimum_labelled_actionable_ratio: float = 0.65
    run_ocr_below_text_coverage: float = 0.70


@dataclass(frozen=True, slots=True)
class QualityReport:
    score: float
    accessibility_coverage: float
    actionable_count: int
    labelled_actionable_ratio: float
    valid_bounds_ratio: float
    query_coverage: float
    required_fallbacks: tuple[SourceKind, ...]
    warnings: tuple[str, ...]


DEFAULT_QUALITY_POLICY = QualityPolicy()


def assess_accessibility(
    candidates: list[PerceptionCandidate],
    *,
    target_queries: tuple[str, ...] = (),
    require_sources: tuple[SourceKind, ...] = ("accessibility",),
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> QualityReport:
    visible = [candidate for candidate in candidates if candidate.state.visible]
    actionable = [candidate for candidate in visible if candidate.actions]
    labelled_actionable = [
        candidate for candidate in actionable if candidate.label or candidate.text
    ]
    labelled_ratio = len(labelled_actionable) / len(actionable) if actionable else 0.0
    meaningful = [
        candidate
        for candidate in visible
        if candidate.actions or candidate.role in {"text", "textbox", "image"}
    ]
    textual = [candidate for candidate in meaningful if candidate.label or candidate.text]
    text_coverage = len(textual) / len(meaningful) if meaningful else 0.0
    valid_bounds_ratio = 1.0 if visible else 0.0
    normalized_values = [
        normalize(value)
        for candidate in visible
        for value in (candidate.label, candidate.text)
        if value
    ]
    matched_queries = sum(
        any(normalize(query) in value for value in normalized_values) for query in target_queries
    )
    query_coverage = matched_queries / len(target_queries) if target_queries else 1.0
    actionable_score = min(1.0, len(actionable) / max(policy.minimum_actionable, 1))
    score = round(
        0.35 * labelled_ratio
        + 0.25 * actionable_score
        + 0.20 * text_coverage
        + 0.10 * valid_bounds_ratio
        + 0.10 * query_coverage,
        6,
    )
    fallbacks: list[SourceKind] = []
    if "ocr" in require_sources or text_coverage < policy.run_ocr_below_text_coverage:
        fallbacks.append("ocr")
    sparse = len(actionable) < policy.minimum_actionable or labelled_ratio < (
        policy.minimum_labelled_actionable_ratio
    )
    if "vision" in require_sources or sparse or score < policy.minimum_score:
        fallbacks.append("vision")
    warnings: list[str] = []
    if not visible:
        warnings.append("accessibility_empty")
    if actionable and not labelled_actionable:
        warnings.append("actionables_unlabelled")
    if target_queries and query_coverage < 1.0:
        warnings.append("target_query_uncovered")
    return QualityReport(
        score=score,
        accessibility_coverage=round(text_coverage, 6),
        actionable_count=len(actionable),
        labelled_actionable_ratio=round(labelled_ratio, 6),
        valid_bounds_ratio=valid_bounds_ratio,
        query_coverage=round(query_coverage, 6),
        required_fallbacks=tuple(dict.fromkeys(fallbacks)),
        warnings=tuple(warnings),
    )
