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
from .omniparser_v2 import (
    OmniParserCacheError,
    OmniParserModelManifest,
    OmniParserV2Runner,
    OptionalDependencyMissing,
    build_omniparser_v2_adapter,
    load_model_manifest,
    model_manifest_digest,
    packaged_model_manifest,
    prepare_model_cache,
    verify_model_cache,
)
from .quality import QualityPolicy, QualityReport, assess_accessibility

__all__ = [
    "AdapterIdentity",
    "HierarchyParseError",
    "HierarchyPolicy",
    "NormalizedJsonAdapter",
    "OmniParserAdapter",
    "OmniParserCacheError",
    "OmniParserModelManifest",
    "OmniParserV2Runner",
    "OptionalDependencyMissing",
    "PerceptionAdapter",
    "PerceptionCandidate",
    "QualityPolicy",
    "QualityReport",
    "SourceKind",
    "StaticPerceptionAdapter",
    "assess_accessibility",
    "build_omniparser_v2_adapter",
    "intersection_over_union",
    "load_model_manifest",
    "model_manifest_digest",
    "packaged_model_manifest",
    "parse_hierarchy",
    "prepare_model_cache",
    "semantic_content_digest",
    "verify_model_cache",
]
