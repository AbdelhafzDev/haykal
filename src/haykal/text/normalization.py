"""Contract implementations for Haykal's two Arabic normalization profiles."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum


class NormalizationProfile(StrEnum):
    """Public normalization profile identifiers."""

    SEARCH = "arabic-search@1"
    MATERIAL = "arabic-material@1"


_BIDI_CONTROLS = dict.fromkeys([0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)])
_TASHKEEL_AND_TATWEEL = re.compile(r"[\u0640\u064b-\u0652\u0670]")
_WHITESPACE = re.compile(r"\s+")
_COMMON_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ک": "ك",
        "ی": "ي",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "،": ",",
        "٫": ".",
        "٬": ",",
    }
)


def normalize(value: str, profile: NormalizationProfile | str = NormalizationProfile.SEARCH) -> str:
    """Normalize visible text according to a named, versioned contract."""

    selected = NormalizationProfile(profile)
    result = unicodedata.normalize("NFC", value)
    result = result.translate(_BIDI_CONTROLS)
    result = _TASHKEEL_AND_TATWEEL.sub("", result)
    result = result.translate(_COMMON_TRANSLATION)
    if selected is NormalizationProfile.SEARCH:
        result = result.replace("ة", "ه")
    return _WHITESPACE.sub(" ", result.casefold()).strip()
