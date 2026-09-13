from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from haykal.artifacts import ArtifactStore
from haykal.contracts.common import Bounds
from haykal.contracts.extraction import (
    ExtractionField,
    ExtractionGroup,
    ExtractionLimits,
    ExtractionRequest,
    ScrollExtraction,
)
from haykal.contracts.scene import (
    ElementFingerprint,
    ElementState,
    PropertyEvidence,
    SceneQuality,
    SemanticElement,
    SemanticScene,
)
from haykal.contracts.selector import ResourceMatch, Selector, TextMatch
from haykal.extraction import ExtractionEngine, MissingRequiredSource


def _element(
    element_id: str,
    *,
    role: str,
    top: int,
    text: str | None = None,
    label: str | None = None,
    resource_id: str | None = None,
    parent: str | None = None,
    source: str = "accessibility",
) -> SemanticElement:
    source_id = f"{source}:{element_id}"
    properties = {
        "role": PropertyEvidence(confidence=0.95, sources=[source_id]),
        "bounds": PropertyEvidence(confidence=0.95, sources=[source_id]),
    }
    if text:
        properties["text"] = PropertyEvidence(confidence=0.95, sources=[source_id])
    if label:
        properties["label"] = PropertyEvidence(confidence=0.95, sources=[source_id])
    return SemanticElement.model_validate(
        {
            "id": element_id,
            "role": role,
            "label": label,
            "label_normalized": label,
            "text": text,
            "text_normalized": text,
            "resource_id": resource_id,
            "bounds": Bounds(left=10, top=top, right=500, bottom=top + 40),
            "state": ElementState(
                enabled=True,
                visible=True,
                focused=False,
                scrollable=role == "list",
            ),
            "actions": ["tap"] if role == "list_item" else [],
            "parent": parent,
            "properties": properties,
            "fingerprint": ElementFingerprint(
                resource_id=resource_id,
                ancestry=["results"],
                text_key=text or label,
            ),
        }
    )


def _cards_scene(
    count: int,
    *,
    revision: int = 1,
    start: int = 0,
    source: str = "accessibility",
) -> SemanticScene:
    elements = [
        _element(
            "results",
            role="list",
            top=0,
            label="النتائج",
            resource_id="app:id/results",
            source=source,
        )
    ]
    for offset in range(count):
        index = start + offset
        anchor = f"card-{index}"
        top = 100 + offset * 240
        elements.extend(
            [
                _element(
                    anchor,
                    role="list_item",
                    top=top,
                    label=f"عرض {index}",
                    resource_id="app:id/card",
                    parent="results",
                    source=source,
                ),
                _element(
                    f"title-{index}",
                    role="text",
                    top=top + 45,
                    text=f"مطعم بيتزا {index}",
                    resource_id="app:id/title",
                    parent=anchor,
                    source=source,
                ),
                _element(
                    f"price-{index}",
                    role="text",
                    top=top + 90,
                    text=f"{index + 20} ر.س",
                    resource_id="app:id/price",
                    parent=anchor,
                    source=source,
                ),
                _element(
                    f"rating-{index}",
                    role="text",
                    top=top + 135,
                    text="٤٫٥",  # noqa: RUF001
                    resource_id="app:id/rating",
                    parent=anchor,
                    source=source,
                ),
                _element(
                    f"eta-{index}",
                    role="text",
                    top=top + 180,
                    text="٣٠-٤٠ دقيقة",
                    resource_id="app:id/eta",
                    parent=anchor,
                    source=source,
                ),
            ]
        )
    fallbacks = [source] if source in {"ocr", "vision"} else []
    return SemanticScene.model_validate(
        {
            "scene_id": f"scene-{revision}",
            "session_id": "session",
            "revision": revision,
            "digest": "sha256:" + f"{revision:064x}",
            "quality": SceneQuality(
                score=0.9,
                accessibility_coverage=1 if source == "accessibility" else 0,
                fallbacks_used=fallbacks,
            ),
            "elements": elements,
        }
    )


def _request(*, max_records: int | None = None) -> ExtractionRequest:
    return ExtractionRequest(
        group=ExtractionGroup(
            by="ancestry",
            record=Selector(
                role="list_item",
                resource_id=ResourceMatch(ends_with="id/card"),
            ),
        ),
        fields={
            "restaurant": ExtractionField(
                selector=Selector(resource_id=ResourceMatch(ends_with="id/title")),
                type="text",
                required=True,
            ),
            "price": ExtractionField(
                selector=Selector(resource_id=ResourceMatch(ends_with="id/price")),
                type="money",
                required=True,
            ),
            "rating": ExtractionField(
                selector=Selector(resource_id=ResourceMatch(ends_with="id/rating")),
                type="rating",
                scale=5,
            ),
            "eta": ExtractionField(
                selector=Selector(resource_id=ResourceMatch(ends_with="id/eta")),
                type="duration",
            ),
        },
        dedupe_by=["restaurant"],
        limits=ExtractionLimits(max_records=max_records),
    )


def test_ancestry_grouping_parses_values_and_binds_evidence() -> None:
    result = ExtractionEngine().extract_scene(_request(), _cards_scene(2))

    assert len(result.records) == 2
    first = result.records[0]
    assert first.fields["restaurant"] == {
        "raw": "مطعم بيتزا 0",
        "normalized": "مطعم بيتزا 0",
    }
    assert first.fields["price"] == {
        "amount": 20,
        "currency": "SAR",
        "raw": "20 ر.س",
        "digits": "latin",
    }
    assert first.fields["rating"] == {"value": 4.5, "scale": 5, "raw": "٤٫٥"}  # noqa: RUF001
    assert first.fields["eta"] == {
        "min_minutes": 30,
        "max_minutes": 40,
        "raw": "٣٠-٤٠ دقيقة",
        "digits": "arabic-indic",
    }
    assert first.evidence["price"] is not None
    assert first.evidence["price"].element_ids == ["price-0"]
    assert first.anchor is not None
    assert first.anchor.scene_revision == 1


def test_one_hundred_synthetic_cards_have_exact_record_boundaries() -> None:
    result = ExtractionEngine().extract_scene(_request(max_records=100), _cards_scene(100))

    assert len(result.records) == 100
    assert len({record.record_id for record in result.records}) == 100
    assert all(len(record.evidence["restaurant"].element_ids) == 1 for record in result.records)  # type: ignore[union-attr]
    assert result.stop_reason == "max_records"


def test_ambiguous_required_field_drops_record_without_guessing() -> None:
    scene = _cards_scene(1)
    duplicate = _element(
        "title-duplicate",
        role="text",
        top=170,
        text="اسم آخر",
        resource_id="app:id/title",
        parent="card-0",
    )
    scene = scene.model_copy(update={"elements": [*scene.elements, duplicate]})

    result = ExtractionEngine().extract_scene(_request(), scene)
    assert result.records == []
    assert result.dropped_records[0]["reason"] == "required_field_missing"
    ambiguity = result.dropped_records[0]["ambiguities"][0]
    assert ambiguity["candidate_element_ids"] == ["title-0", "title-duplicate"]


def test_missing_requested_fallback_source_is_explicit() -> None:
    request = _request().model_copy(update={"require_sources": ["accessibility", "vision"]})
    with pytest.raises(MissingRequiredSource, match="vision"):
        ExtractionEngine().extract_scene(request, _cards_scene(1))


def test_secret_and_masked_values_never_expose_raw_text() -> None:
    request = ExtractionRequest(
        group=ExtractionGroup(by="single"),
        fields={
            "secret": ExtractionField(
                selector=Selector(label=TextMatch(contains="النتائج")),
                type="text",
                privacy="secret",
            ),
            "masked": ExtractionField(
                selector=Selector(label=TextMatch(contains="النتائج")),
                type="text",
                privacy="masked",
            ),
        },
    )
    result = ExtractionEngine().extract_scene(request, _cards_scene(1))
    encoded = result.model_dump_json()

    assert "النتائج" not in encoded
    assert result.records[0].fields["secret"]["present"] is True  # type: ignore[index]
    assert str(result.records[0].fields["masked"]["masked"]).startswith("••••")  # type: ignore[index]


def test_image_crop_is_content_addressed(tmp_path: Path) -> None:
    scene = _cards_scene(1)
    image = Image.new("RGB", (600, 600), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    store = ArtifactStore(tmp_path / "artifacts")
    request = ExtractionRequest(
        group=ExtractionGroup(by="single"),
        fields={
            "crop": ExtractionField(
                selector=Selector(element_id="price-0", scene_revision=1),
                type="image_crop",
                required=True,
            )
        },
    )

    result = ExtractionEngine(artifact_store=store).extract_scene(
        request,
        scene,
        screenshot_png=buffer.getvalue(),
    )
    pointer = result.records[0].fields["crop"]
    assert store.contains(pointer["artifact"])  # type: ignore[index]


def test_multi_page_extraction_deduplicates_overlapping_records() -> None:
    request = _request().model_copy(
        update={
            "scroll": ScrollExtraction(
                within=Selector(semantic_name="results"),
                max_pages=2,
            )
        }
    )
    engine = ExtractionEngine(
        element_dictionary={"results": Selector(resource_id=ResourceMatch(ends_with="id/results"))}
    )
    result = engine.extract_scenes(
        request,
        [_cards_scene(2, revision=1), _cards_scene(2, revision=2, start=1)],
    )

    assert len(result.records) == 3
    assert result.source_exhausted is True
    assert result.stop_reason == "end_of_list"


def test_rows_grouping_clusters_hierarchy_sparse_elements() -> None:
    scene = _cards_scene(1, source="ocr")
    row_elements = [
        _element("row-a", role="text", top=100, text="مطعم أ", source="ocr"),
        _element("row-a-price", role="text", top=105, text="20 ر.س", source="ocr"),
        _element("row-b", role="text", top=300, text="مطعم ب", source="ocr"),
        _element("row-b-price", role="text", top=305, text="30 ر.س", source="ocr"),
    ]
    scene = scene.model_copy(update={"elements": row_elements})
    request = ExtractionRequest(
        require_sources=["ocr"],
        group=ExtractionGroup(by="rows", band_px=20),
        fields={
            "first": ExtractionField(
                selector=Selector(role="text", position="first"),
                type="text",
                required=True,
            )
        },
    )

    result = ExtractionEngine().extract_scene(request, scene)
    assert [record.fields["first"]["raw"] for record in result.records] == [  # type: ignore[index]
        "مطعم أ",
        "مطعم ب",
    ]


def test_repeat_grouping_uses_repeated_direct_child_shapes() -> None:
    scene = _cards_scene(3)
    request = ExtractionRequest(
        group=ExtractionGroup(
            by="repeat",
            root=Selector(resource_id=ResourceMatch(ends_with="id/results")),
        ),
        fields={
            "restaurant": ExtractionField(
                selector=Selector(resource_id=ResourceMatch(ends_with="id/title")),
                type="text",
                required=True,
            )
        },
    )

    result = ExtractionEngine().extract_scene(request, scene)
    assert len(result.records) == 3
