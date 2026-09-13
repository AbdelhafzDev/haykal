from haykal.benchmarks import extraction_metrics, identity_metrics, precision_recall


def test_precision_recall_reports_abstention_and_false_accepts() -> None:
    metrics = precision_recall({"a", "wrong"}, {"a", "missed"})
    assert metrics.true_positive == 1
    assert metrics.false_positive == 1
    assert metrics.false_negative == 1
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.f1 == 0.5


def test_identity_idf1_is_not_hidden_behind_accuracy() -> None:
    metrics = identity_metrics(
        {("frame-2:a", "id-1"), ("frame-2:b", "id-wrong")},
        {("frame-2:a", "id-1"), ("frame-2:b", "id-2")},
    )
    assert metrics.pair_metrics.precision == 0.5
    assert metrics.pair_metrics.recall == 0.5
    assert metrics.idf1 == 0.5


def test_extraction_separates_presence_value_and_boundary_errors() -> None:
    metrics = extraction_metrics(
        predicted_fields={
            ("record-1", "title"): "بيتزا",
            ("record-1", "price"): 40,
            ("record-2", "title"): None,
        },
        expected_fields={
            ("record-1", "title"): "بيتزا",
            ("record-1", "price"): 39,
            ("record-2", "title"): "برجر",
        },
        predicted_records={frozenset({"title-1", "price-1"})},
        expected_records={
            frozenset({"title-1", "price-1"}),
            frozenset({"title-2", "price-2"}),
        },
    )
    assert metrics.field_presence.precision == 1.0
    assert metrics.field_presence.recall == 0.666667
    assert metrics.value_accuracy == 0.5
    assert metrics.record_boundaries.recall == 0.5
