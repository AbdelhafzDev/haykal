from pathlib import Path

from haykal.perception.hierarchy import parse_hierarchy
from haykal.perception.quality import assess_accessibility

ROOT = Path(__file__).parents[2]


def test_rich_accessibility_avoids_fallback() -> None:
    candidates = parse_hierarchy((ROOT / "fixtures/perception/basic-rtl.xml").read_bytes())
    report = assess_accessibility(candidates, target_queries=("بيتزا",))

    assert report.actionable_count == 3
    assert report.query_coverage == 1.0
    assert report.required_fallbacks == ()


def test_empty_accessibility_degrades_explicitly() -> None:
    report = assess_accessibility([], target_queries=("بيتزا",))

    assert report.score < 0.5
    assert report.required_fallbacks == ("ocr", "vision")
    assert "accessibility_empty" in report.warnings


def test_structural_containers_do_not_create_false_text_coverage_gaps() -> None:
    xml = (
        "<hierarchy>"
        + "".join(
            f'<node class="android.view.ViewGroup" bounds="[0,{row}][100,{row + 10}]"/>'
            for row in range(20)
        )
        + """<node class="android.widget.Button" clickable="true"
        bounds="[0,100][200,200]"><node class="android.widget.TextView"
        text="اطلب" bounds="[10,110][190,190]"/></node>
        <node class="android.widget.Button" clickable="true"
        bounds="[0,210][200,310]"><node class="android.widget.TextView"
        text="العروض" bounds="[10,220][190,300]"/></node></hierarchy>"""
    )

    report = assess_accessibility(parse_hierarchy(xml))

    assert report.accessibility_coverage == 1.0
    assert report.required_fallbacks == ()
