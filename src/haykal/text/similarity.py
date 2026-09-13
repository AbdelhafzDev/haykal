"""Deterministic normalized text similarity."""

from __future__ import annotations

from .normalization import NormalizationProfile, normalize


def levenshtein_distance(left: str, right: str) -> int:
    """Return edit distance using bounded-memory dynamic programming."""

    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def similarity(
    left: str,
    right: str,
    profile: NormalizationProfile | str = NormalizationProfile.SEARCH,
) -> float:
    """Return the documented Levenshtein ratio after normalization."""

    normalized_left = normalize(left, profile)
    normalized_right = normalize(right, profile)
    longest = max(len(normalized_left), len(normalized_right))
    if longest == 0:
        return 1.0
    return 1.0 - levenshtein_distance(normalized_left, normalized_right) / longest
