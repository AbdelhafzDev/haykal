"""Accessibility-first perception and swappable fallback adapters."""

from .adapters import (
    AdapterIdentity,
    NormalizedJsonAdapter,
    OmniParserAdapter,
    PerceptionAdapter,
    StaticPerceptionAdapter,
)
from .fusion import semantic_content_digest
from .hierarchy import HierarchyParseError, HierarchyPolicy, parse_hierarchy
from .model import PerceptionCandidate, SourceKind, intersection_over_union
from .quality import QualityPolicy, QualityReport, assess_accessibility

__all__ = [
    "AdapterIdentity",
    "HierarchyParseError",
    "HierarchyPolicy",
    "NormalizedJsonAdapter",
    "OmniParserAdapter",
    "PerceptionAdapter",
    "PerceptionCandidate",
    "QualityPolicy",
    "QualityReport",
    "SourceKind",
    "StaticPerceptionAdapter",
    "assess_accessibility",
    "intersection_over_union",
    "parse_hierarchy",
    "semantic_content_digest",
]
