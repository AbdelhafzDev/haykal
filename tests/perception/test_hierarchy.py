from pathlib import Path

import pytest

from haykal.perception.fusion import fuse_candidates
from haykal.perception.hierarchy import HierarchyParseError, HierarchyPolicy, parse_hierarchy

ROOT = Path(__file__).parents[2]


def test_rtl_hierarchy_normalizes_roles_actions_and_ancestry() -> None:
    candidates = parse_hierarchy((ROOT / "fixtures/perception/basic-rtl.xml").read_bytes())

    assert len(candidates) == 6
    search = next(item for item in candidates if item.resource_id == "dev.haykal:id/search")
    assert search.role == "textbox"
    assert search.label == "بحث"
    assert search.actions == ("tap", "input_text")
    price = next(item for item in candidates if item.resource_id == "dev.haykal:id/price")
    assert price.text == "٣٩٫٩٥ ر.س"  # noqa: RUF001
    assert price.ancestry[-1] == "dev.haykal:id/results"


def test_invalid_or_oversized_hierarchy_fails_closed() -> None:
    with pytest.raises(HierarchyParseError):
        parse_hierarchy("<!DOCTYPE x [<!ENTITY e 'boom'>]><hierarchy>&e;</hierarchy>")
    with pytest.raises(HierarchyParseError, match="byte budget"):
        parse_hierarchy(b"<hierarchy/>", policy=HierarchyPolicy(max_bytes=2))


def test_actionable_control_lifts_descendant_text_with_raw_node_evidence() -> None:
    candidates = parse_hierarchy(
        """<hierarchy><node class="android.widget.Button" clickable="true"
        bounds="[0,0][200,100]"><node class="android.view.View" clickable="false"
        bounds="[10,10][190,90]"><node class="android.widget.TextView"
        text="اطلب الآن" bounds="[20,20][180,80]"/></node></node></hierarchy>"""
    )

    button = candidates[0]
    assert button.label == "اطلب الآن"
    assert button.property_sources["label"] == ("accessibility:node_2",)
    element = next(item for item in fuse_candidates(candidates) if item.actions)
    assert element.label == "اطلب الآن"
    assert element.properties["label"].sources == ["accessibility:node_2"]
    assert element.properties["actions"].sources == ["accessibility:node_0"]
