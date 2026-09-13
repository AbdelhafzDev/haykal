from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from haykal.text import NormalizationProfile, normalize

FIXTURE = Path(__file__).parents[2] / "fixtures" / "text" / "normalization_matrix.json"


def _cases() -> list[tuple[str, str, str]]:
    matrix = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        (
            f"{wrapper['prefix']}{base['input']}{wrapper['suffix']}",
            base["search"],
            base["material"],
        )
        for base in matrix["base_cases"]
        for wrapper in matrix["wrappers"]
    ]


CASES = _cases()


def test_labelled_matrix_contains_at_least_300_raw_strings() -> None:
    assert len(CASES) >= 300
    assert len({raw for raw, _, _ in CASES}) == len(CASES)


@pytest.mark.parametrize(("raw", "search", "material"), CASES)
def test_normalization_profiles(raw: str, search: str, material: str) -> None:
    assert normalize(raw, NormalizationProfile.SEARCH) == search
    assert normalize(raw, NormalizationProfile.MATERIAL) == material


@given(st.text())
def test_normalization_is_idempotent(raw: str) -> None:
    for profile in NormalizationProfile:
        once = normalize(raw, profile)
        assert normalize(once, profile) == once


def test_material_profile_does_not_collapse_ta_marbuta() -> None:
    assert normalize("مدرسة", NormalizationProfile.MATERIAL) != normalize(
        "مدرسه", NormalizationProfile.MATERIAL
    )
