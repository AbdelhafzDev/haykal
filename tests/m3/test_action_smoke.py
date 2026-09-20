from haykal.m3.action_smoke import build_smoke_action


def test_shipped_smoke_targets_the_matjar_accessibility_resource() -> None:
    action = build_smoke_action(7)

    assert action.target is not None
    assert action.target.scene_revision == 7
    assert action.target.selector is not None
    assert action.target.selector.resource_id is not None
    assert action.target.selector.resource_id.ends_with == "search_button"
    assert action.expect is not None
    assert action.expect.text_contains == "اعرض النتائج"
