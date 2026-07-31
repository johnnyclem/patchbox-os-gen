"""Font helpers — DejaVu is installed via fonts-dejavu-core."""

from __future__ import annotations

import os
from functools import lru_cache

from PIL import ImageFont

_DEJAVU = "/usr/share/fonts/truetype/dejavu"
_CANDIDATES = {
    "regular": [
        f"{_DEJAVU}/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
    "bold": [
        f"{_DEJAVU}/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "mono": [
        f"{_DEJAVU}/DejaVuSansMono.ttf",
        f"{_DEJAVU}/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
    ],
}


@lru_cache(maxsize=32)
def font(size: int, weight: str = "regular") -> ImageFont.ImageFont:
    for path in _CANDIDATES.get(weight, _CANDIDATES["regular"]):
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()
