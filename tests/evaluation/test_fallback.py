from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from haykal.contracts.common import Bounds
from haykal.contracts.scene import ElementState
from haykal.evaluation import evaluate_fallback_dataset
from haykal.evaluation.fallback import FallbackThresholds
from haykal.perception import AdapterIdentity, StaticPerceptionAdapter
from haykal.perception.model import PerceptionCandidate


def _candidate(source_id: str, label: str, bounds: Bounds) -> PerceptionCandidate:
    return PerceptionCandidate(
        source="vision",
        source_id=source_id,
        bounds=bounds,
        role="button",
        label=label,
        state=ElementState(
            enabled=True,
            visible=True,
            focused=False,
            scrollable=False,
        ),
        actions=("tap",),
        property_confidence={"bounds": 0.98, "role": 0.98, "label": 0.98},
    )


def _adapter(*candidates: PerceptionCandidate) -> StaticPerceptionAdapter:
    return StaticPerceptionAdapter(
        "vision",
        AdapterIdentity(
            name="fixture",
            version="a" * 40,
            model_digest=f"sha256:{'1' * 64}",
            weights_digest=f"sha256:{'2' * 64}",
        ),
        candidates,
    )


def _write_dataset(tmp_path: Path, cases: list[dict[str, object]]) -> Path:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (400, 800), "white").save(screenshot)
    digest = f"sha256:{hashlib.sha256(screenshot.read_bytes()).hexdigest()}"
    for case in cases:
        case["screenshot"] = screenshot.name
        case["screenshot_sha256"] = digest
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "dataset_id": "matjar-fallback-v1",
                "source": "matjar",
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_evaluator_scores_resolution_and_typed_ambiguity(tmp_path: Path) -> None:
    dataset = _write_dataset(
        tmp_path,
        [
            {
                "case_id": "arabic-payment",
                "selector": {"label": {"equals": "ادفع"}},
                "risk": "purchase",
                "expected_outcome": "resolved",
                "target_bounds": {"left": 10, "top": 10, "right": 110, "bottom": 80},
            },
            {
                "case_id": "duplicate-add",
                "selector": {"label": {"equals": "إضافة"}},
                "risk": "purchase",
                "expected_outcome": "ambiguous",
                "safety_case": True,
            },
        ],
    )
    adapter = _adapter(
        _candidate("pay", "ادفع", Bounds(left=10, top=10, right=110, bottom=80)),
        _candidate("add-1", "إضافة", Bounds(left=10, top=100, right=110, bottom=180)),
        _candidate("add-2", "إضافة", Bounds(left=200, top=100, right=300, bottom=180)),
    )

    report = await evaluate_fallback_dataset(
        dataset,
        adapter,
        thresholds=FallbackThresholds(minimum_cases=2),
    )

    assert report.passed is True
    assert report.accuracy == 1
    assert report.safe_stop_count == 1
    assert report.wrong_irreversible_resolutions == 0
    assert [result.actual_outcome for result in report.results] == ["resolved", "ambiguous"]


@pytest.mark.asyncio
async def test_evaluator_fails_wrong_irreversible_resolution(tmp_path: Path) -> None:
    dataset = _write_dataset(
        tmp_path,
        [
            {
                "case_id": "wrong-payment",
                "selector": {"label": {"equals": "ادفع"}},
                "risk": "purchase",
                "expected_outcome": "resolved",
                "target_bounds": {"left": 250, "top": 500, "right": 350, "bottom": 600},
            }
        ],
    )
    adapter = _adapter(_candidate("wrong", "ادفع", Bounds(left=10, top=10, right=110, bottom=80)))

    report = await evaluate_fallback_dataset(dataset, adapter)

    assert report.passed is False
    assert report.correct_count == 0
    assert report.wrong_irreversible_resolutions == 1


@pytest.mark.asyncio
async def test_evaluator_rejects_changed_screenshot(tmp_path: Path) -> None:
    dataset = _write_dataset(
        tmp_path,
        [
            {
                "case_id": "pay",
                "selector": {"label": {"equals": "ادفع"}},
                "risk": "purchase",
                "expected_outcome": "resolved",
                "target_bounds": {"left": 10, "top": 10, "right": 110, "bottom": 80},
            }
        ],
    )
    (tmp_path / "screen.png").write_bytes(b"changed")

    with pytest.raises(ValueError, match="screenshot digest mismatch"):
        await evaluate_fallback_dataset(dataset, _adapter())
