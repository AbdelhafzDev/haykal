from haykal.text.similarity import levenshtein_distance, similarity


def test_levenshtein_ratio_uses_arabic_normalization() -> None:
    assert levenshtein_distance("kitten", "sitting") == 3
    assert similarity("إتمام الطلب", "اتمام الطلب") == 1.0
    assert similarity("بيتزا", "بيتسا") == 0.8
    assert similarity("", "") == 1.0


def test_similarity_material_profile_keeps_taa_marbuta_distinct() -> None:
    assert similarity("مدينة", "مدينه", "arabic-search@1") == 1.0
    assert similarity("مدينة", "مدينه", "arabic-material@1") < 1.0
