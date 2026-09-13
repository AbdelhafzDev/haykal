"""Semantic scene construction and adjacent-frame identity."""

from .builder import (
    ObservationIncoherent,
    ObservationIntegrityError,
    SceneBuilder,
    SceneBuildResult,
)
from .observer import ObservationCapture, ObservationService
from .tracker import (
    ElementIdentityTracker,
    IdentityMatch,
    SceneRevisionError,
    TrackingPolicy,
    TrackingResult,
    identity_score,
)

__all__ = [
    "ElementIdentityTracker",
    "IdentityMatch",
    "ObservationCapture",
    "ObservationIncoherent",
    "ObservationIntegrityError",
    "ObservationService",
    "SceneBuildResult",
    "SceneBuilder",
    "SceneRevisionError",
    "TrackingPolicy",
    "TrackingResult",
    "identity_score",
]
