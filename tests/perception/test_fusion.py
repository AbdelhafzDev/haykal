from haykal.contracts.common import Bounds
from haykal.contracts.scene import ElementState
from haykal.perception.fusion import (
    candidate_match_score,
    fuse_candidates,
    semantic_content_digest,
)
from haykal.perception.model import PerceptionCandidate


def _state() -> ElementState:
    return ElementState(
        enabled=True,
        visible=True,
        focused=False,
        scrollable=False,
    )


def test_overlapping_sources_fuse_and_retain_property_evidence() -> None:
    accessibility = PerceptionCandidate(
        source="accessibility",
        source_id="accessibility:node_1",
        bounds=Bounds(left=100, top=100, right=500, bottom=250),
        role="button",
        label="إتمام الطلب",
        resource_id="app:id/submit",
        state=_state(),
        actions=("tap",),
        property_confidence={"label": 0.96},
    )
    ocr = PerceptionCandidate(
        source="ocr",
        source_id="ocr:digest#1",
        bounds=Bounds(left=120, top=120, right=480, bottom=230),
        role="text",
        text="اتمام الطلب",
        state=_state(),
        property_confidence={"text": 0.91, "label": 0.91},
    )

    assert candidate_match_score(accessibility, ocr) > 0.8
    elements = fuse_candidates([ocr, accessibility])
    assert len(elements) == 1
    assert elements[0].label_normalized == "اتمام الطلب"
    assert elements[0].properties["label"].sources == [
        "accessibility:node_1",
        "ocr:digest#1",
    ]


def test_distinct_candidates_from_same_source_never_merge() -> None:
    items = [
        PerceptionCandidate(
            source="ocr",
            source_id=f"ocr:{index}",
            bounds=Bounds(left=0, top=0, right=100, bottom=100),
            role="text",
            text="عرض",
            state=_state(),
        )
        for index in range(2)
    ]
    assert len(fuse_candidates(items)) == 2


def test_settle_digest_ignores_frame_local_ids_and_provenance() -> None:
    candidate = PerceptionCandidate(
        source="accessibility",
        source_id="accessibility:node_1",
        bounds=Bounds(left=0, top=0, right=100, bottom=100),
        role="button",
        label="حفظ",
        state=_state(),
        actions=("tap",),
    )
    first = fuse_candidates([candidate])[0]
    second = first.model_copy(
        update={
            "id": "different-frame-id",
            "properties": {
                name: evidence.model_copy(update={"sources": ["accessibility:node_99"]})
                for name, evidence in first.properties.items()
            },
        }
    )
    assert semantic_content_digest([first]) == semantic_content_digest([second])
