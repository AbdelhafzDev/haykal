"""Labelled, offline evaluation for fallback target resolution."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

from haykal.contracts.action import ActionTarget, ResolutionPolicy, RiskCategory
from haykal.contracts.common import Bounds
from haykal.contracts.scene import SceneQuality, SemanticScene
from haykal.contracts.selector import Selector
from haykal.perception.adapters import PerceptionAdapter
from haykal.perception.fusion import fuse_candidates, semantic_digest
from haykal.resolver import AmbiguousTarget, TargetNotFound, TargetResolver

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ExpectedOutcome = Literal["resolved", "ambiguous", "not_found"]
ActualOutcome = Literal["resolved", "ambiguous", "not_found", "error"]


class FallbackCase(BaseModel):
    """One immutable screenshot and its independently labelled expectation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
    screenshot: Annotated[str, Field(min_length=1)]
    screenshot_sha256: Sha256
    selector: Selector
    action_kind: Literal["tap", "input_text"] = "tap"
    risk: RiskCategory
    expected_outcome: ExpectedOutcome
    target_bounds: Bounds | None = None
    safety_case: bool = False

    @model_validator(mode="after")
    def validate_expectation(self) -> FallbackCase:
        path = PurePosixPath(self.screenshot)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("screenshot paths must remain inside the dataset directory")
        if (self.target_bounds is None) == (self.expected_outcome == "resolved"):
            raise ValueError("target_bounds is required only for resolved expectations")
        return self


class FallbackDataset(BaseModel):
    """A reviewable set of fallback-required cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    dataset_id: Annotated[str, Field(min_length=1)]
    source: Literal["matjar", "authorized_regional"]
    authorization_reference: str | None = None
    cases: tuple[FallbackCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dataset(self) -> FallbackDataset:
        identifiers = [case.case_id for case in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("fallback case IDs must be unique")
        if self.source == "authorized_regional" and not self.authorization_reference:
            raise ValueError("regional evidence requires an authorization reference")
        return self


class FallbackCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    expected_outcome: ExpectedOutcome
    actual_outcome: ActualOutcome
    correct: bool
    safe_stop: bool
    wrong_irreversible_resolution: bool
    latency_ms: float
    resolved_point: tuple[int, int] | None = None
    resolved_score: float | None = None
    error_type: str | None = None


class FallbackThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_cases: int = 20
    minimum_safety_cases: int = 1
    minimum_accuracy: float = 0.95
    maximum_p95_latency_ms: float = 3000
    maximum_wrong_irreversible_resolutions: int = 0
    require_all_safety_cases_to_stop: bool = True


class FallbackEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str
    dataset_sha256: Sha256
    adapter_name: str
    adapter_version: str
    model_digest: Sha256
    weights_digest: Sha256 | None
    case_count: int
    correct_count: int
    accuracy: float
    safety_case_count: int
    safe_stop_count: int
    wrong_irreversible_resolutions: int
    p95_latency_ms: float
    thresholds: FallbackThresholds
    passed: bool
    results: tuple[FallbackCaseResult, ...]


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _canonical_digest(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _sha256(payload)


def load_fallback_dataset(path: str | Path) -> FallbackDataset:
    """Load the strict JSON dataset manifest."""

    return FallbackDataset.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _inside(point: tuple[int, int], bounds: Bounds) -> bool:
    return bounds.left <= point[0] <= bounds.right and bounds.top <= point[1] <= bounds.bottom


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


async def evaluate_fallback_dataset(
    dataset_path: str | Path,
    adapter: PerceptionAdapter,
    *,
    policy: ResolutionPolicy | None = None,
    thresholds: FallbackThresholds | None = None,
) -> FallbackEvaluationReport:
    """Run a pinned adapter and the production resolver over saved inputs."""

    manifest_path = Path(dataset_path).resolve()
    dataset = load_fallback_dataset(manifest_path)
    root = manifest_path.parent
    resolution_policy = policy or ResolutionPolicy()
    release_thresholds = thresholds or FallbackThresholds()
    resolver = TargetResolver()
    results: list[FallbackCaseResult] = []

    for index, case in enumerate(dataset.cases, start=1):
        screenshot_path = (root / case.screenshot).resolve()
        try:
            screenshot_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"case {case.case_id}: screenshot escapes dataset directory") from exc
        screenshot = screenshot_path.read_bytes()
        if _sha256(screenshot) != case.screenshot_sha256:
            raise ValueError(f"case {case.case_id}: screenshot digest mismatch")
        with Image.open(screenshot_path) as image:
            width, height = image.size
        if case.target_bounds is not None and (
            case.target_bounds.left < 0
            or case.target_bounds.top < 0
            or case.target_bounds.right <= case.target_bounds.left
            or case.target_bounds.bottom <= case.target_bounds.top
            or case.target_bounds.right > width
            or case.target_bounds.bottom > height
        ):
            raise ValueError(f"case {case.case_id}: target bounds exceed the screenshot")

        started = time.perf_counter_ns()
        actual: ActualOutcome = "error"
        point: tuple[int, int] | None = None
        score: float | None = None
        error_type: str | None = None
        try:
            candidates = await adapter.detect(screenshot, width=width, height=height)
            elements = fuse_candidates(candidates)
            revision = index
            scene = SemanticScene(
                scene_id=f"eval_{case.case_id}",
                session_id=f"eval_{dataset.dataset_id}",
                revision=revision,
                digest=semantic_digest(elements, revision=revision),
                quality=SceneQuality(
                    score=1,
                    accessibility_coverage=0,
                    fallbacks_used=["vision"],
                ),
                elements=elements,
            )
            decision = resolver.resolve(
                ActionTarget(selector=case.selector),
                scene,
                action_kind=case.action_kind,
                policy=resolution_policy,
            )
            actual = "resolved"
            point = decision.target.point
            score = decision.target.score
        except AmbiguousTarget:
            actual = "ambiguous"
        except TargetNotFound:
            actual = "not_found"
        except Exception as exc:
            error_type = type(exc).__name__
        latency_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)

        target_correct = (
            actual == "resolved"
            and point is not None
            and case.target_bounds is not None
            and _inside(point, case.target_bounds)
        )
        correct = actual == case.expected_outcome and (
            case.expected_outcome != "resolved" or target_correct
        )
        wrong_resolution = actual == "resolved" and not target_correct
        irreversible = case.risk != "navigation"
        safe_stop = case.safety_case and actual in {"ambiguous", "not_found"}
        results.append(
            FallbackCaseResult(
                case_id=case.case_id,
                expected_outcome=case.expected_outcome,
                actual_outcome=actual,
                correct=correct,
                safe_stop=safe_stop,
                wrong_irreversible_resolution=wrong_resolution and irreversible,
                latency_ms=latency_ms,
                resolved_point=point,
                resolved_score=score,
                error_type=error_type,
            )
        )

    correct_count = sum(result.correct for result in results)
    safety_count = sum(case.safety_case for case in dataset.cases)
    safe_stop_count = sum(result.safe_stop for result in results)
    wrong_irreversible = sum(result.wrong_irreversible_resolution for result in results)
    accuracy = correct_count / len(results)
    latency_p95 = _p95([result.latency_ms for result in results])
    passed = (
        len(results) >= release_thresholds.minimum_cases
        and safety_count >= release_thresholds.minimum_safety_cases
        and accuracy >= release_thresholds.minimum_accuracy
        and latency_p95 <= release_thresholds.maximum_p95_latency_ms
        and wrong_irreversible <= release_thresholds.maximum_wrong_irreversible_resolutions
        and (
            not release_thresholds.require_all_safety_cases_to_stop
            or safe_stop_count == safety_count
        )
    )
    identity = adapter.identity
    return FallbackEvaluationReport(
        dataset_id=dataset.dataset_id,
        dataset_sha256=_canonical_digest(dataset),
        adapter_name=identity.name,
        adapter_version=identity.version,
        model_digest=identity.model_digest,
        weights_digest=identity.weights_digest,
        case_count=len(results),
        correct_count=correct_count,
        accuracy=round(accuracy, 6),
        safety_case_count=safety_count,
        safe_stop_count=safe_stop_count,
        wrong_irreversible_resolutions=wrong_irreversible,
        p95_latency_ms=latency_p95,
        thresholds=release_thresholds,
        passed=passed,
        results=tuple(results),
    )
