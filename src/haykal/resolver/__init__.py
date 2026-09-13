"""Semantic target resolution."""

from .resolver import (
    AmbiguousTarget,
    RankedTarget,
    ResolutionDecision,
    StaleTarget,
    TargetNotFound,
    TargetResolutionError,
    TargetResolver,
)

__all__ = [
    "AmbiguousTarget",
    "RankedTarget",
    "ResolutionDecision",
    "StaleTarget",
    "TargetNotFound",
    "TargetResolutionError",
    "TargetResolver",
]
